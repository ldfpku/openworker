"""The one place in this package that decides HOW an OS process gets created.

**Why this exists.** On Windows, a process with no console of its own (a GUI-subsystem
app, or a sidecar started with CREATE_NO_WINDOW — see below) that spawns a
console-subsystem program (cmd, powershell, git, rg, python, node, taskkill, icacls, …)
without asking otherwise gets a brand-new console allocated for that child, and Windows
shows it — a black window flashing open and closed. 08bcfb9 fixed one instance of this
(`voice_input_compatibility()`'s `cmd /C ver` probe, surfaced as the dictation status
refresh flickering a console) by routing every `Command::new` in the Tauri shell
(`surfaces/gui/src-tauri/src/lib.rs`) through a `new_command()` helper that always adds
`CREATE_NO_WINDOW`. This module is that helper's Python counterpart: every
`subprocess.Popen/run/call/check_call/check_output` (and, should one show up,
`asyncio.create_subprocess_exec/shell` — the same kwargs work there since asyncio hands
unknown kwargs straight through to `Popen`) in `coworker/` must build its Windows kwargs
via `popen_kwargs()` below. A source scan in `tests/test_subprocess_hygiene.py` enforces
this; see that file's exemption table for the (small, deliberate) set of calls that spawn
something the user is meant to *see* — `explorer`, `os.startfile`, `open`, `xdg-open` —
and therefore must NOT be hidden.

**The cross-file invariant this quietly depends on.** Today, none of the ~15 capturing
`subprocess.run` calls in `coworker/` actually flash a window in the packaged desktop
app, even though most of them (until this change) passed no creation flags at all. That
is not an accident of Windows behavior on its own — it is because
`packaging/openworker-server.spec` builds the sidecar with `console=True` (a real,
hidden console, not "no console"), and `surfaces/gui/src-tauri/src/lib.rs` launches that
sidecar with `CREATE_NO_WINDOW`. The sidecar therefore inherits one hidden console, and
every child it spawns without its own creation flags inherits *that* console instead of
being handed a new, visible one. Change any one of those three facts — spec `console=`,
the Tauri launch flag, or (in the future) some other way of starting the sidecar, e.g. a
service or scheduled task with no console at all — and every uncovered call here starts
flashing at once, silently. `tests/test_subprocess_hygiene.py` pins all three down as an
explicit, checkable invariant so a change to any of them is caught rather than discovered
as a bug report. Passing `**popen_kwargs()` everywhere makes each call correct on its own
merits too, independent of that inherited-console accident.

**console_ctrl — the one real behavior trade-off.** `CREATE_NO_WINDOW` makes Windows
allocate the child its OWN new console. That is harmless for a capturing call (the
child's stdout/stderr are redirected through pipes regardless of console state, and
`TerminateProcess`/`taskkill /T` walk the process tree, not console membership — both
already proven in production by `mcp` 1.29's stdio transport, which sets
CREATE_NO_WINDOW *and* kills its process tree via a Job Object). But it silently breaks
`Popen.send_signal(signal.CTRL_BREAK_EVENT)`: that call is `GenerateConsoleCtrlEvent`
under the hood, which can only reach a process sharing the CALLER's console — a process
in its own new console never receives it. `coworker/tools/shell.py` relies on
CTRL_BREAK_EVENT for its own Windows Ctrl-Break interrupt path, so its two
`CREATE_NEW_PROCESS_GROUP` spawns (the persistent shell and background tasks) pass
`console_ctrl=True`: no CREATE_NO_WINDOW, so the console is inherited/shared as before
(Ctrl-Break keeps working), and the window is instead hidden via
`STARTUPINFO.wShowWindow = SW_HIDE` — same visible result, no signaling regression.

**Boundaries — what this module does NOT cover, on purpose:**
- `os.startfile`, `explorer.exe`, macOS `open`, Linux `xdg-open`, `webbrowser.open` are
  not console-subsystem programs in the first place (no console gets allocated for them),
  and several are deliberately meant to show the user something (reveal-in-Finder,
  "open in default app", the OAuth login page). Not this module's problem.
- Third-party libraries that spawn their own subprocesses (Playwright's
  `chromium.launch(...)`, the `mcp` SDK's stdio transport) manage their own creation
  flags; we cannot and should not inject kwargs into calls we don't make. `mcp>=1.29`
  already sets CREATE_NO_WINDOW itself (`mcp/os/win32/utilities.py`) — worth re-checking
  on SDK upgrades in case that regresses.
- A future pseudo-console (ConPTY) integration is a genuinely different mode —
  `STARTUPINFOEX` + `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE` — and is mutually exclusive
  with CREATE_NO_WINDOW. It needs its own explicit path if it ever shows up; don't try to
  bolt it onto `popen_kwargs()`.

**POSIX (macOS/Linux)** gets none of this — there is no console to allocate. The only
knob is `session=True`, which reproduces the `start_new_session=True` every POSIX call
site already used, unchanged (own process group, so a foreground command can be
interrupted or killed without touching the caller).
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

_IS_WINDOWS = sys.platform == "win32"

# subprocess.CREATE_NO_WINDOW / CREATE_NEW_PROCESS_GROUP only exist as attributes on
# Windows builds of the stdlib. Redefine the (stable, documented, never-changes) win32
# values directly so this module — and its pure-function unit tests — import and run on
# any platform, including the ubuntu CI runner that never touches a real Windows process.
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _windows_creationflags(*, extra: int = 0, group: bool = False, console_ctrl: bool = False) -> int:
    """Pure bit arithmetic for the Windows `creationflags` value — platform-independent
    on purpose, so it is unit-testable without a Windows process actually running.

    `console_ctrl=True` deliberately OMITS CREATE_NO_WINDOW — see the module docstring's
    "console_ctrl" section for why (GenerateConsoleCtrlEvent / Ctrl-Break needs a shared
    console). Never drops `extra`: a caller's own flags (e.g. DETACHED_PROCESS) are always
    preserved, only ever combined with `|`.
    """
    flags = extra
    if group:
        flags |= CREATE_NEW_PROCESS_GROUP
    if not console_ctrl:
        flags |= CREATE_NO_WINDOW
    return flags


def popen_kwargs(
    *,
    group: bool = False,
    console_ctrl: bool = False,
    session: bool = False,
    extra_flags: int = 0,
) -> dict[str, Any]:
    """The kwargs to splat (`**popen_kwargs(...)`) into every `subprocess.Popen/run/call/
    check_call/check_output` (and `asyncio.create_subprocess_exec/shell`, which forwards
    unrecognized kwargs to `Popen` the same way) in this package.

    group=True          add CREATE_NEW_PROCESS_GROUP (Windows only; needed so a later
                         Ctrl-Break can target the child's group without also signaling us).
    console_ctrl=True    the child needs CTRL_BREAK_EVENT delivered to it later — skip
                         CREATE_NO_WINDOW (which would break that) and hide the window via
                         STARTUPINFO/SW_HIDE instead. Default False is right for every
                         purely-capturing call (the overwhelming majority).
    session=True         POSIX only: `start_new_session=True` (own process group, so the
                         child can be interrupted/killed independent of us). No-op on
                         Windows — `group`/`console_ctrl` cover the same need there.
    extra_flags          any additional Windows creationflags the caller already needs
                         (e.g. DETACHED_PROCESS); OR'd in, never dropped.

    Returns `{}` on POSIX unless `session=True`. Never returns an empty dict on Windows —
    CREATE_NO_WINDOW (or the console_ctrl/STARTUPINFO pair) is always present.
    """
    if extra_flags & CREATE_NO_WINDOW:
        # Either a duplicate (popen_kwargs already adds it) or, with console_ctrl=True, a
        # direct contradiction (console_ctrl exists precisely to NOT set this flag).
        raise ValueError(
            "extra_flags must not include CREATE_NO_WINDOW — popen_kwargs() adds it "
            "itself when appropriate; pass console_ctrl=True instead of trying to opt out "
            "of it by hand"
        )
    if not _IS_WINDOWS:
        return {"start_new_session": True} if session else {}

    kwargs: dict[str, Any] = {
        "creationflags": _windows_creationflags(extra=extra_flags, group=group, console_ctrl=console_ctrl)
    }
    if console_ctrl:
        si = subprocess.STARTUPINFO()  # type: ignore[attr-defined]  # Windows-only, guarded by _IS_WINDOWS above
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
        si.wShowWindow = 0  # SW_HIDE — subprocess doesn't expose the win32con constant
        kwargs["startupinfo"] = si
    return kwargs
