"""Guards the "no accidental console-flash on Windows" invariant across the whole package.

Companion to the Rust side's `window_flash_regression_tests` (`surfaces/gui/src-tauri/src/
lib.rs`) and `stt_never_spawns_a_process` (`stt/src/lib.rs`), fixed in 08bcfb9 for the one
call site (`voice_input_compatibility()`'s `cmd /C ver` probe) that was actually observed
flashing. This file is the Python-side equivalent PLUS the piece 08bcfb9 didn't add: CI only
runs `cargo test --manifest-path stt/Cargo.toml` (see .github/workflows/ci.yml's rust-unit
job), so `only_new_command_calls_command_new` in `surfaces/gui/src-tauri/src/lib.rs` has never
actually run in CI — only locally, by hand. R6 below mirrors that Rust assertion as a plain
text check so it runs wherever this file does (ubuntu-latest, same as every other pytest job).

Every rule here is a static check — AST or plain text — not a real Windows spawn. That is
deliberate: this suite runs in CI on ubuntu-latest, where creationflags/STARTUPINFO don't
exist. A real end-to-end exercise of the Windows-only code paths lives in
`tests/test_shell.py` (persistent-shell / background-task spawns) and in
`Test_LocalExecutorShellPath` below, which — because this machine genuinely runs Windows —
actually spawns real processes through `coworker.procutil.popen_kwargs()` and checks output
and timeout-kill still behave.

**Why any of this matters (see coworker/procutil.py's module docstring for the full story):**
none of the ~15 capturing `subprocess.run` calls in `coworker/` flash a window in the packaged
desktop app TODAY, but only because of an unenforced, cross-file accident: the PyInstaller
spec builds the sidecar with `console=True` (R5's `test_sidecar_console_and_hidden_launch_
stay_paired`), and the Tauri shell launches it with `CREATE_NO_WINDOW` — so every uncovered
Python spawn inherits a hidden console instead of getting a fresh, visible one. Change either
side of that pairing (or start the sidecar some other way — a service, a scheduled task) and
every call this file guards starts flashing at once. R5 pins that pairing down explicitly so a
change to either file gets caught here, rather than showing up as a support ticket.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from coworker import procutil, toolchain

REPO_ROOT = Path(__file__).resolve().parent.parent
COWORKER_ROOT = REPO_ROOT / "coworker"

_WIN = sys.platform == "win32"

# -- shared: functions inside coworker/ that spawn something the user is meant to SEE, and
# therefore must NOT be hidden — reveal-in-file-manager / open-in-default-app. Both the
# inline `# procutil-exempt:` comment (checked by R3) AND this table must be present, so
# removing either one re-triggers the R1 failure. Keyed by "path relative to repo root
# (forward slashes)::enclosing function name" so a file move doesn't silently invalidate an
# entry (a rename still would, which is the point — nothing here should go stale unnoticed).
EXEMPT: dict[str, str] = {
    "coworker/server/manager.py::reveal_artifact": (
        "opens the file in Finder/Explorer/the default app for the USER to see; explorer.exe "
        "and os.startfile are not console-subsystem programs in the first place, and open/"
        "xdg-open are meant to be visible"
    ),
    "coworker/server/manager.py::reveal_skill": (
        "same rationale as reveal_artifact — opens the skill's folder for the user to see"
    ),
}

_SPAWN_ATTRS: dict[str, set[str]] = {
    "subprocess": {"Popen", "run", "call", "check_call", "check_output"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
}

# Windows creation-flag / STARTUPINFO identifiers: procutil.py is their one legal home (R4).
# Checked as AST Name/Attribute identifiers, NOT a text substring search — a docstring or
# comment elsewhere in coworker/ that merely TALKS ABOUT CREATE_NO_WINDOW (several already do,
# pointing readers at procutil.py) is not a duplicate implementation and must not trip this.
_RESERVED_WIN_IDENTIFIERS = {
    "CREATE_NO_WINDOW",
    "CREATE_NEW_PROCESS_GROUP",
    "STARTUPINFO",
    "STARTF_USESHOWWINDOW",
}


def _iter_python_files():
    for path in sorted(COWORKER_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _span_start_with_leading_comments(lines: list[str], lineno: int) -> int:
    """0-indexed start of the text span to search for '# procutil-exempt:' — the call's own
    line(s), PLUS any comment-only lines directly above it. The exemption comment reads more
    naturally sitting just above a multi-line `subprocess.Popen(...)` call than crammed onto
    its first line, and the AST Call node's own line range never includes a preceding
    comment (comments aren't AST nodes), so this walks upward past them explicitly."""
    idx = lineno - 1  # 0-indexed line of `lineno`
    i = idx - 1
    while i >= 0 and lines[i].strip().startswith("#"):
        i -= 1
    return i + 1


def _is_popen_kwargs_splat(keyword: ast.keyword) -> bool:
    """True for a `**popen_kwargs(...)` / `**procutil.popen_kwargs(...)` keyword."""
    if keyword.arg is not None:  # not a ** splat
        return False
    value = keyword.value
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id == "popen_kwargs"
    if isinstance(func, ast.Attribute):
        return func.attr == "popen_kwargs"
    return False


def _is_shell_true(keyword: ast.keyword) -> bool:
    return (
        keyword.arg == "shell"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
    )


class _Scanner(ast.NodeVisitor):
    """One pass over one file's AST: collects every finding R1/R2/R4 care about, tagged
    with the enclosing function (for R1's exemption lookup) and line numbers."""

    def __init__(self) -> None:
        self._func_stack: list[str] = []
        self.unwrapped_spawns: list[tuple[int, int, str]] = []  # (lineno, end_lineno, func)
        self.banned_calls: list[tuple[int, str]] = []  # (lineno, description)
        self.reserved_identifiers: list[tuple[int, str]] = []  # (lineno, name)

    def _enter_func(self, node):
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_FunctionDef = _enter_func
    visit_AsyncFunctionDef = _enter_func

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _RESERVED_WIN_IDENTIFIERS:
            self.reserved_identifiers.append((node.lineno, node.id))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _RESERVED_WIN_IDENTIFIERS:
            self.reserved_identifiers.append((node.lineno, node.attr))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        module_name = None
        attr_name = None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module_name, attr_name = func.value.id, func.attr

        if module_name == "os" and (attr_name in ("system", "popen") or (attr_name or "").startswith("spawn")):
            self.banned_calls.append((node.lineno, f"os.{attr_name}"))

        is_spawn = module_name in _SPAWN_ATTRS and attr_name in _SPAWN_ATTRS[module_name]
        if is_spawn:
            for kw in node.keywords:
                if _is_shell_true(kw):
                    self.banned_calls.append((node.lineno, f"{module_name}.{attr_name}(shell=True)"))
            if not any(_is_popen_kwargs_splat(kw) for kw in node.keywords):
                enclosing = self._func_stack[-1] if self._func_stack else "<module>"
                end = node.end_lineno or node.lineno
                self.unwrapped_spawns.append((node.lineno, end, enclosing))

        self.generic_visit(node)


# ---------------------------------------------------------------------------------------
# R1 + R2 + R3: every process-spawning call in coworker/ goes through popen_kwargs(), no
# shell=True / os.system / os.popen / os.spawn* anywhere, and every exception is double-
# signed (inline comment + this file's EXEMPT table).
# ---------------------------------------------------------------------------------------


def test_every_spawn_goes_through_popen_kwargs_or_is_exempt():
    violations: list[str] = []
    used_exemptions: set[str] = set()

    for path in _iter_python_files():
        rel = _rel(path)
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError as exc:  # pragma: no cover - would fail collection anyway
            pytest.fail(f"{rel}: failed to parse — {exc}")
        scanner = _Scanner()
        scanner.visit(tree)

        if scanner.banned_calls:
            for lineno, what in scanner.banned_calls:
                violations.append(
                    f"{rel}:{lineno}: {what} is banned outright (no way to pass Windows "
                    f"creation flags to a shell string, or it bypasses argv-list safety) — "
                    f"use subprocess with an argv list and **popen_kwargs() instead"
                )

        if not scanner.unwrapped_spawns:
            continue

        lines = source.splitlines()
        for lineno, end_lineno, func_name in scanner.unwrapped_spawns:
            key = f"{rel}::{func_name}"
            reason = EXEMPT.get(key)
            span_start = _span_start_with_leading_comments(lines, lineno)
            span = "\n".join(lines[span_start:end_lineno])
            has_marker = "# procutil-exempt:" in span
            if reason is not None and has_marker:
                used_exemptions.add(key)
                continue
            if reason is not None and not has_marker:
                violations.append(
                    f"{rel}:{lineno}: '{func_name}' is in the EXEMPT table but the call has "
                    f"no inline '# procutil-exempt:' comment — add one (both signatures are "
                    f"required) or remove the table entry"
                )
                continue
            violations.append(
                f"{rel}:{lineno}: call inside '{func_name}' spawns a process without "
                f"**popen_kwargs() (see coworker/procutil.py) — on Windows, an unflagged "
                f"spawn from a console-less parent flashes a visible console window. Add "
                f"**popen_kwargs(...) to this call, or if it deliberately shows the user "
                f"something (reveal-in-Finder, open-in-app), add a '# procutil-exempt: "
                f"<reason>' comment on the call AND an entry in this test file's EXEMPT table"
            )

    assert not violations, "subprocess hygiene violation(s):\n" + "\n".join(violations)

    stale = set(EXEMPT) - used_exemptions
    assert not stale, (
        "EXEMPT table entries that no longer match any unwrapped spawn call — the function "
        f"was renamed/removed or now uses popen_kwargs(): {sorted(stale)}. Delete the stale "
        "entries (an orphaned exemption is worse than none — it hides that nothing checks "
        "that call anymore)."
    )


def test_reserved_windows_identifiers_live_only_in_procutil():
    """R4: CREATE_NO_WINDOW / CREATE_NEW_PROCESS_GROUP / STARTUPINFO / STARTF_USESHOWWINDOW
    as actual Python identifiers (not prose) may only appear inside procutil.py — that is
    the ONE place allowed to know these values, mirroring the Rust side's single
    `new_command()`. A second definition elsewhere is how the two drift apart silently."""
    offenders: list[str] = []
    procutil_path = COWORKER_ROOT / "procutil.py"
    for path in _iter_python_files():
        if path == procutil_path:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=_rel(path))
        scanner = _Scanner()
        scanner.visit(tree)
        for lineno, name in scanner.reserved_identifiers:
            offenders.append(f"{_rel(path)}:{lineno}: references {name} directly")
    assert not offenders, (
        "Windows creation-flag/STARTUPINFO identifiers used outside coworker/procutil.py — "
        "route through popen_kwargs() instead of reimplementing it:\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------------------
# R5: the cross-file invariant that makes the Python side safe TODAY even before this PR —
# make it explicit and checkable instead of implicit and undiscoverable.
# ---------------------------------------------------------------------------------------


def test_sidecar_console_and_hidden_launch_stay_paired():
    spec_path = REPO_ROOT / "packaging" / "openworker-server.spec"
    lib_rs_path = REPO_ROOT / "surfaces" / "gui" / "src-tauri" / "src" / "lib.rs"
    spec_text = spec_path.read_text(encoding="utf-8")
    lib_rs_text = lib_rs_path.read_text(encoding="utf-8")

    assert "console=True" in spec_text, (
        f"{_rel(spec_path)} no longer builds the sidecar with console=True. That single line "
        "is why every coworker/ subprocess call that doesn't pass its own creation flags "
        "doesn't flash a window in the packaged app TODAY: the sidecar inherits a hidden "
        "console rather than getting a fresh, visible one. If this build has switched to "
        "console=False, re-audit every subprocess.run/Popen call in coworker/ for window "
        "flashing before shipping — none of them can rely on the inherited-console accident "
        "anymore."
    )
    assert "creation_flags(0x0800_0000)" in lib_rs_text, (
        f"{_rel(lib_rs_path)} no longer launches the sidecar with CREATE_NO_WINDOW "
        "(0x0800_0000, inside new_command()). That flag is the other half of the pairing "
        "test_sidecar_console_and_hidden_launch_stay_paired guards — without it the sidecar's "
        "console becomes visible and every child process it spawns without its own creation "
        "flags starts flashing. If new_command()'s implementation changed shape, update this "
        "assertion deliberately rather than deleting it."
    )


def test_rust_shell_spawns_go_through_new_command():
    """R6: mirrors surfaces/gui/src-tauri/src/lib.rs's own
    `only_new_command_calls_command_new` test as plain text, because that Rust test has never
    actually run in CI — .github/workflows/ci.yml's rust-unit job only runs
    `cargo test --manifest-path stt/Cargo.toml`, not the surfaces/gui/src-tauri crate (which
    needs webkit2gtk and friends, and is minutes slower to build). This costs nothing to run
    here and closes that gap; it does not replace running `cargo test` locally before a
    src-tauri change ships."""
    lib_rs_path = REPO_ROOT / "surfaces" / "gui" / "src-tauri" / "src" / "lib.rs"
    text = lib_rs_path.read_text(encoding="utf-8")
    # Built at runtime for the same reason lib.rs's own test builds it at runtime: naming the
    # needle as a literal here would itself be an extra "Command::new(" occurrence if anyone
    # ever inlined this file's text into a docstring, and more simply just reads oddly next to
    # the very thing it's counting.
    needle = "Command" + "::new("
    occurrences = text.count(needle)
    assert occurrences == 1, (
        f"found {occurrences} raw Command::new(...) call site(s) in surfaces/gui/src-tauri/"
        f"src/lib.rs, expected exactly 1 (inside new_command() itself, see lib.rs's own "
        f"'only_new_command_calls_command_new' test) — every process this app spawns must go "
        f"through new_command so a Windows child never flashes a console window"
    )


def test_stt_crate_still_never_spawns_a_process():
    """Text mirror of stt/src/lib.rs's `stt_never_spawns_a_process` — that one DOES run in
    CI already (the rust-unit job covers stt/Cargo.toml), so this is redundant on purpose:
    belt-and-braces at near-zero cost, and it keeps all the window-flash guards in one place
    for a reader auditing this specific concern."""
    stt_src = REPO_ROOT / "stt" / "src"
    for name in ("audio.rs", "engine.rs", "models.rs"):
        text = (stt_src / name).read_text(encoding="utf-8")
        assert "std::process" not in text and "Command::new" not in text, (
            f"stt/src/{name} appears to spawn an OS process — stt must stay spawn-free "
            "(downloads via ureq, hashing via sha2, mic access via cpal); an unflagged spawn "
            "flashes a console window on Windows"
        )


# ---------------------------------------------------------------------------------------
# R7: coworker/toolchain.py's `_KNOWN_DIRS` and lib.rs's `KNOWN_TOOL_DIRS` (+ its
# HOME-relative counterparts) must list the same directories — toolchain.py's own comment
# says "keep the two in step" and nothing used to check that it actually happened.
# ---------------------------------------------------------------------------------------


def test_known_tool_dirs_stay_in_sync_with_rust_sidecar_env():
    lib_rs_path = REPO_ROOT / "surfaces" / "gui" / "src-tauri" / "src" / "lib.rs"
    rust_text = lib_rs_path.read_text(encoding="utf-8")
    missing = []
    for py_dir in toolchain._KNOWN_DIRS:
        # Absolute dirs (Homebrew, MacPorts, …) are literal string entries in Rust's
        # KNOWN_TOOL_DIRS array; "~/..." dirs (rustup, Go) can't be — a plain `&[&str]`
        # can't hold a runtime-expanded HOME — so lib.rs instead joins the suffix onto
        # $HOME at runtime. Either way the exact path segment should appear as a string
        # literal in the source; check that substring rather than fully parsing the array,
        # which would need to understand two different Rust code shapes for one comparison.
        needle = py_dir[2:] if py_dir.startswith("~/") else py_dir
        if needle not in rust_text:
            missing.append(py_dir)
    assert not missing, (
        "coworker/toolchain.py's _KNOWN_DIRS has entries not mirrored anywhere in "
        f"surfaces/gui/src-tauri/src/lib.rs: {missing}. toolchain.py's own comment on "
        "_KNOWN_DIRS says 'keep the two in step' — update lib.rs's KNOWN_TOOL_DIRS (or its "
        "HOME-relative dirs loop in sidecar_env()) to match."
    )


# ---------------------------------------------------------------------------------------
# R8: pure bit-arithmetic / kwargs-shape unit tests. Platform-independent by construction —
# these run and mean the same thing on the ubuntu CI runner and on a real Windows box.
# ---------------------------------------------------------------------------------------


def test_windows_creationflags_group_adds_no_window_and_group():
    flags = procutil._windows_creationflags(group=True)
    assert flags == procutil.CREATE_NO_WINDOW | procutil.CREATE_NEW_PROCESS_GROUP


def test_windows_creationflags_console_ctrl_omits_no_window():
    flags = procutil._windows_creationflags(console_ctrl=True, group=True)
    assert flags & procutil.CREATE_NO_WINDOW == 0
    assert flags & procutil.CREATE_NEW_PROCESS_GROUP == procutil.CREATE_NEW_PROCESS_GROUP


def test_windows_creationflags_preserves_callers_extra_flags():
    DETACHED_PROCESS = 0x00000008  # real win32 value; not worth importing win32process for
    flags = procutil._windows_creationflags(extra=DETACHED_PROCESS, group=True)
    assert flags & DETACHED_PROCESS == DETACHED_PROCESS
    assert flags & procutil.CREATE_NEW_PROCESS_GROUP == procutil.CREATE_NEW_PROCESS_GROUP
    assert flags & procutil.CREATE_NO_WINDOW == procutil.CREATE_NO_WINDOW


def test_popen_kwargs_rejects_duplicate_create_no_window():
    with pytest.raises(ValueError):
        procutil.popen_kwargs(extra_flags=procutil.CREATE_NO_WINDOW)
    with pytest.raises(ValueError):
        procutil.popen_kwargs(console_ctrl=True, extra_flags=procutil.CREATE_NO_WINDOW)


@pytest.mark.skipif(_WIN, reason="POSIX-only shape: exercised for real on this platform")
def test_popen_kwargs_posix_shape():
    assert procutil.popen_kwargs() == {}
    assert procutil.popen_kwargs(group=True, console_ctrl=True) == {}
    assert procutil.popen_kwargs(session=True) == {"start_new_session": True}


@pytest.mark.skipif(not _WIN, reason="Windows-only shape: exercised for real on this platform")
def test_popen_kwargs_windows_shape():
    plain = procutil.popen_kwargs()
    assert plain == {"creationflags": procutil.CREATE_NO_WINDOW}

    grouped = procutil.popen_kwargs(group=True)
    assert grouped == {"creationflags": procutil.CREATE_NO_WINDOW | procutil.CREATE_NEW_PROCESS_GROUP}

    hidden = procutil.popen_kwargs(group=True, console_ctrl=True)
    assert hidden["creationflags"] == procutil.CREATE_NEW_PROCESS_GROUP
    si = hidden["startupinfo"]
    assert si.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert si.wShowWindow == 0  # SW_HIDE

    # session=True is a POSIX-only no-op on Windows — group/console_ctrl cover the same need.
    assert "start_new_session" not in procutil.popen_kwargs(session=True, group=True)


def test_popen_kwargs_result_is_directly_usable_by_subprocess_run():
    """Smoke test: whatever popen_kwargs() returns for THIS platform must be kwargs
    subprocess.run() actually accepts — on ubuntu CI this exercises the empty-dict path, on
    a Windows dev machine (like this one) it exercises the real creationflags/startupinfo
    path end to end."""
    result = subprocess.run(
        [sys.executable, "-c", "print(1)"],
        capture_output=True,
        text=True,
        timeout=10,
        **procutil.popen_kwargs(),
    )
    assert result.stdout.strip() == "1"


# ---------------------------------------------------------------------------------------
# Integration: the shell tool's actual Windows spawn path (coworker/tools/shell.py), now
# routed through popen_kwargs(group=True, console_ctrl=True, session=True) — confirms the
# behavior the module docstring promises is unchanged: output capture and timeout-kill still
# work, and CTRL_BREAK_EVENT delivery (the reason console_ctrl exists at all) isn't broken.
# ---------------------------------------------------------------------------------------


@pytest.mark.skipif(not _WIN, reason="exercises the Windows-only persistent-shell spawn path")
class TestLocalExecutorShellPath:
    def test_output_capture_still_works(self, tmp_path):
        from coworker.tools.shell import LocalExecutor

        ex = LocalExecutor(cwd=tmp_path, default_timeout=15)
        try:
            result = ex.run("cmd /c echo hi")
            assert result["exit_code"] == 0
            assert "hi" in result["output"]
        finally:
            ex.close()

    def test_timeout_still_kills_and_shell_recovers(self, tmp_path):
        from coworker.tools.shell import LocalExecutor

        ex = LocalExecutor(cwd=tmp_path, default_timeout=15)
        try:
            timed_out = ex.run("Start-Sleep -Seconds 30", timeout=2)
            assert timed_out["timed_out"] is True
            # The shell self-heals (respawns) after a Windows timeout-kill — the session
            # must still be usable for the next command, not left wedged.
            recovered = ex.run("cmd /c echo still-alive")
            assert recovered["exit_code"] == 0
            assert "still-alive" in recovered["output"]
        finally:
            ex.close()
