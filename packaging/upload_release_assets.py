#!/usr/bin/env python3
"""Upload a release's assets one file at a time, then prove the finished set is right.

Why this exists: `softprops/action-gh-release` hands every file to uploads.github.com
at once, and that endpoint returns a transient HTTP 500 often enough that v0.6.2's
release job failed twice in a row (2026-09-17). Re-running made it worse, not better:
the action defaults to `overwrite_files: true`, so it DELETES the assets that did make
it and starts the whole set over. An interrupted upload also leaves a `state=starter`
stub behind, which `gh release view` and the web UI both hide — only
`GET repos/{repo}/releases/{id}/assets` shows it.

This script replaces that upload step, and it is built around one rule:

    NEVER delete an asset whose state is "uploaded".

Everything else follows. A re-run uploads only what is missing, deletes only
half-finished (`state != "uploaded"`) stubs, and refuses to touch a draft that already
holds a DIFFERENT build's assets. `gh`'s exit code is not trusted anywhere — behind a
proxy it can hang for a quarter of an hour after the bytes are already on GitHub, and
it can also exit 0 having uploaded nothing. The only accepted proof of success is the
assets API reporting `state == "uploaded"` AND `digest == "sha256:" + <local sha256>`.

Subcommands:

    upload              serial, idempotent upload of dist/ into an existing release
    verify              read-only audit of the finished release (assets + latest.json)
    make-selftest-dist  build a throwaway dist/ of the right shape, for dry runs
    cleanup-selftest    delete a dry run's draft release (three guards before it does)

All GitHub access goes through the `gh` CLI (CI: the GH_TOKEN env var; a laptop: gh's
own stored login). This script never reads, logs or passes a token itself.

Log lines are deliberately plain ASCII: a Chinese-locale Windows console is cp936 and
raises UnicodeEncodeError on anything else.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# --------------------------------------------------------------------------------------
# The expected asset set. This is a TRIPWIRE, not a convenience: adding or dropping a
# platform must be a deliberate edit here as well, or `upload` refuses to run at all.
#
# Keep in sync with:
#   - .github/workflows/release.yml, the "Stage artifacts (versioned + stable names)"
#     step (it produces both the stable and the versioned name of every installer), and
#   - packaging/make_update_manifest.py's ARTIFACTS (the three updater artifacts, each
#     of which also ships its `.sig`) plus the latest.json it writes.
# --------------------------------------------------------------------------------------

MANIFEST_ASSET = "latest.json"

# Stable names — the website links to releases/latest/download/<stable name>.
STABLE_ASSETS: tuple[str, ...] = (
    "OpenWorker-macos-arm64.app.tar.gz",
    "OpenWorker-macos-arm64.app.tar.gz.sig",
    "OpenWorker-macos-arm64.dmg",
    "OpenWorker-macos-x64.app.tar.gz",
    "OpenWorker-macos-x64.app.tar.gz.sig",
    "OpenWorker-macos-x64.dmg",
    "OpenWorker-windows-setup.exe",
    "OpenWorker-windows-setup.exe.sig",
    "OpenWorker-windows.msi",
)

# Versioned names — Tauri's own bundle names, kept as the archive copy.
VERSIONED_ASSETS: tuple[str, ...] = (
    "OpenWorker_{version}_aarch64.dmg",
    "OpenWorker_{version}_x86_64.dmg",
    "OpenWorker_{version}_x64-setup.exe",
    "OpenWorker_{version}_x64_en-US.msi",
)

# Stable name -> versioned name of the SAME bytes (the Stage-artifacts step copies one
# file under both names). Used only by `make-selftest-dist`, to give a dry run the same
# duplicate-content shape a real release has. The two .app.tar.gz updater artifacts have
# no versioned twin.
SELFTEST_TWINS: dict[str, str] = {
    "OpenWorker-macos-arm64.dmg": "OpenWorker_{version}_aarch64.dmg",
    "OpenWorker-macos-x64.dmg": "OpenWorker_{version}_x86_64.dmg",
    "OpenWorker-windows-setup.exe": "OpenWorker_{version}_x64-setup.exe",
    "OpenWorker-windows.msi": "OpenWorker_{version}_x64_en-US.msi",
}

EXPECTED_ASSET_COUNT = 1 + len(STABLE_ASSETS) + len(VERSIONED_ASSETS)  # 14

# --- tunables -------------------------------------------------------------------------

_TERMINATE_GRACE = 10.0  # seconds to wait for a terminated gh before SIGKILL
_RECHECK_TRIES = 3  # API re-reads after gh exits, before calling the attempt failed
_RECHECK_INTERVAL = 5.0
_EMPTY_DIGEST_INTERVAL = 5.0  # GitHub fills `digest` a moment after state flips
_EMPTY_DIGEST_BUDGET = 60.0
_OUTPUT_TAIL_LINES = 20
_API_RETRIES = 5  # read-only `gh api` calls get their own small retry
_API_BACKOFF_BASE = 2.0
_BACKOFF_CAP = 300.0
_JITTER_FRACTION = 0.2

SELFTEST_TAG_PREFIX = "selftest-upload-"

_REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------


def expected_assets(version: str) -> list[str]:
    """The exact 14 names a release of *version* must end up holding."""
    names = [MANIFEST_ASSET, *STABLE_ASSETS]
    names += [tmpl.format(version=version) for tmpl in VERSIONED_ASSETS]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate names in the expected set: {sorted(names)}")
    return names


def upload_order(names: Iterable[str]) -> list[str]:
    """Everything else first (sorted), latest.json LAST.

    The manifest is what shipped apps poll; a draft that somehow got published early
    should never advertise an update whose payload has not landed yet.
    """
    rest = sorted(n for n in names if n != MANIFEST_ASSET)
    return rest + [n for n in names if n == MANIFEST_ASSET]


def sha256_file(path: Path) -> str:
    """`sha256:<hex>` — the same shape the assets API reports in `digest`."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _asset_digest(asset: dict) -> str:
    return str(asset.get("digest") or "").strip()


def _harden_streams() -> None:
    """Never let a stray non-ASCII byte in gh's output kill the run on a cp936 console."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass


def _log(message: str) -> None:
    print(message, flush=True)


def _error(message: str) -> None:
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") == "true" else "error: "
    print(prefix + message, file=sys.stderr, flush=True)


def _backoff_delay(attempt: int, rand: Callable[[], float]) -> float:
    """min(10 * 2**(n-1), 300) seconds, plus a little jitter."""
    base = min(10.0 * (2 ** (attempt - 1)), _BACKOFF_CAP)
    return base * (1.0 + _JITTER_FRACTION * rand())


# --------------------------------------------------------------------------------------
# GitHub access — the ONLY place that shells out to gh
# --------------------------------------------------------------------------------------


class GhError(RuntimeError):
    pass


class _GhUpload:
    """A running `gh release upload`. Its exit code is advisory; the API is the truth."""

    def __init__(self, proc: subprocess.Popen, log_path: Path) -> None:
        self._proc = proc
        self._log_path = log_path
        self.returncode: int | None = None

    def poll(self) -> int | None:
        rc = self._proc.poll()
        if rc is not None:
            self.returncode = rc
        return rc

    def stop(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=_TERMINATE_GRACE)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                try:
                    self._proc.wait(timeout=_TERMINATE_GRACE)
                except subprocess.TimeoutExpired:
                    pass
        self.returncode = self._proc.poll()

    def output_tail(self, lines: int = _OUTPUT_TAIL_LINES) -> str:
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])

    def close(self) -> None:
        try:
            self._log_path.unlink()
        except OSError:
            pass


class GhApi:
    """Thin `gh` wrapper. Core logic talks to this shape, tests substitute a fake."""

    def __init__(self, repo: str, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.repo = repo
        self._sleep = sleep

    # -- plumbing ----------------------------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GH_PROMPT_DISABLED"] = "1"
        env["GH_NO_UPDATE_NOTIFIER"] = "1"
        return env

    def _api(self, path: str, *, method: str = "GET", allow_404: bool = False) -> Any:
        cmd = ["gh", "api", "--method", method, "-H", "Accept: application/vnd.github+json", path]
        last = ""
        for attempt in range(1, _API_RETRIES + 1):
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._env(),
            )
            if proc.returncode == 0:
                body = (proc.stdout or "").strip()
                if not body:
                    return None
                try:
                    return json.loads(body)
                except json.JSONDecodeError as exc:  # pragma: no cover - gh shape change
                    last = f"unparseable response: {exc}"
                    break
            combined = ((proc.stdout or "") + (proc.stderr or "")).strip()
            if allow_404 and ("HTTP 404" in combined or "Not Found" in combined):
                return None
            last = combined[-500:]
            if attempt < _API_RETRIES:
                self._sleep(_API_BACKOFF_BASE**attempt)
        raise GhError(f"gh api {method} {path} failed: {last}")

    def _paginated(self, path: str, per_page: int = 100) -> list[dict]:
        joiner = "&" if "?" in path else "?"
        out: list[dict] = []
        page = 1
        while True:
            chunk = self._api(f"{path}{joiner}per_page={per_page}&page={page}")
            if not chunk:
                break
            out.extend(chunk)
            if len(chunk) < per_page:
                break
            page += 1
        return out

    # -- reads -------------------------------------------------------------------------

    def list_releases(self) -> list[dict]:
        return self._paginated(f"repos/{self.repo}/releases")

    def list_assets(self, release_id: int) -> list[dict]:
        return self._paginated(f"repos/{self.repo}/releases/{release_id}/assets")

    def get_asset(self, asset_id: int) -> dict | None:
        return self._api(f"repos/{self.repo}/releases/assets/{asset_id}", allow_404=True)

    def get_release(self, release_id: int) -> dict | None:
        return self._api(f"repos/{self.repo}/releases/{release_id}", allow_404=True)

    def list_tag_refs(self, prefix: str) -> list[dict]:
        refs = self._api(f"repos/{self.repo}/git/matching-refs/tags/{prefix}", allow_404=True)
        return list(refs or [])

    # -- writes ------------------------------------------------------------------------

    def delete_asset(self, asset_id: int) -> None:
        self._api(
            f"repos/{self.repo}/releases/assets/{asset_id}", method="DELETE", allow_404=True
        )

    def delete_release(self, release_id: int) -> None:
        self._api(f"repos/{self.repo}/releases/{release_id}", method="DELETE", allow_404=True)

    def start_upload(self, tag: str, path: Path) -> _GhUpload:
        """No `--clobber`: this script must never overwrite an uploaded asset."""
        handle, log_name = tempfile.mkstemp(prefix="gh-upload-", suffix=".log")
        os.close(handle)
        log_path = Path(log_name)
        stream = open(log_path, "wb")
        try:
            proc = subprocess.Popen(
                ["gh", "release", "upload", tag, str(path), "--repo", self.repo],
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                env=self._env(),
            )
        finally:
            stream.close()
        return _GhUpload(proc, log_path)


# --------------------------------------------------------------------------------------
# core types
# --------------------------------------------------------------------------------------


@dataclass
class _Ctx:
    api: Any
    release_id: int
    tag: str
    sleep: Callable[[float], None]
    monotonic: Callable[[], float]
    log: Callable[[str], None]


@dataclass
class _Reconciled:
    done: bool = False
    fatal: str | None = None
    deleted_stale: bool = False


@dataclass
class _Attempt:
    ok: bool = False
    fatal: str | None = None
    reason: str = ""


@dataclass
class FileResult:
    name: str
    action: str  # "skipped" | "uploaded" | "replaced-stale"
    attempts: int
    size: int
    seconds: float


@dataclass
class UploadRun:
    ok: bool = False
    results: list[FileResult] = field(default_factory=list)
    backoffs: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def uploaded(self) -> int:
        return sum(1 for r in self.results if r.action != "skipped")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.action == "skipped")


@dataclass
class VerifyRun:
    ok: bool = False
    problems: list[str] = field(default_factory=list)
    rows: list[tuple[str, str, int, bool]] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# release resolution
# --------------------------------------------------------------------------------------


def resolve_release(api: Any, tag: str, release_id: int | None = None) -> dict:
    """Exactly one release must carry *tag*. Raises GhError otherwise.

    Paginated on purpose: a repo with more than 100 releases would silently hide the
    right one behind a single-page fetch, and "no release for tag" on a good tag is a
    far more confusing failure than a slow listing.
    """
    matches = [r for r in api.list_releases() if r.get("tag_name") == tag]
    if not matches:
        raise GhError(f"no release for tag {tag} in {api.repo}")
    if len(matches) > 1:
        ids = ", ".join(str(r.get("id")) for r in matches)
        raise GhError(
            f"{len(matches)} releases share tag {tag} (ids: {ids}) - delete the duplicate "
            "drafts by hand, then re-run"
        )
    release = matches[0]
    if release_id is not None and int(release.get("id", -1)) != int(release_id):
        raise GhError(
            f"--release-id {release_id} is not the release for tag {tag} "
            f"(that tag's release is id {release.get('id')})"
        )
    return release


# --------------------------------------------------------------------------------------
# upload
# --------------------------------------------------------------------------------------


def _assets_by_name(api: Any, release_id: int, name: str) -> list[dict]:
    return [a for a in api.list_assets(release_id) if a.get("name") == name]


def _judge_uploaded(
    ctx: _Ctx, name: str, asset: dict, local_digest: str
) -> _Reconciled:
    """Decide about an asset already in `state == "uploaded"`. Never deletes it."""
    digest = _asset_digest(asset)
    if not digest:
        # GitHub fills `digest` shortly after the state flips; give it a moment rather
        # than declaring an unverifiable asset immediately.
        waited = 0.0
        while not digest and waited < _EMPTY_DIGEST_BUDGET:
            ctx.sleep(_EMPTY_DIGEST_INTERVAL)
            waited += _EMPTY_DIGEST_INTERVAL
            found = [a for a in _assets_by_name(ctx.api, ctx.release_id, name) if a.get("state") == "uploaded"]
            if not found:
                return _Reconciled()  # it vanished — treat as absent and upload
            asset = found[0]
            digest = _asset_digest(asset)
        if not digest:
            return _Reconciled(
                fatal=(
                    f"{name} is uploaded but reports no digest after {int(_EMPTY_DIGEST_BUDGET)}s "
                    "- it cannot be verified, and an uploaded asset is never deleted. "
                    "Inspect the draft by hand."
                )
            )
    if digest == local_digest:
        return _Reconciled(done=True)
    return _Reconciled(
        fatal=(
            f"{name} is already uploaded with a DIFFERENT digest\n"
            f"    remote: {digest}\n"
            f"    local:  {local_digest}\n"
            "    The draft holds another build's assets. Delete that draft by hand, then re-run."
        )
    )


def _reconcile(ctx: _Ctx, name: str, local_digest: str) -> _Reconciled:
    """Bring the remote record for *name* to one of: done / absent / fatal.

    Half-finished (`state != "uploaded"`) records are re-read BY ID before anything is
    deleted — a listing can be a few seconds stale, and the record may have finished in
    the meantime. All half-finished records for the name go in one pass, so a draft that
    accumulated several stubs does not burn one attempt per stub.
    """
    assets = _assets_by_name(ctx.api, ctx.release_id, name)
    settled = [a for a in assets if a.get("state") == "uploaded"]
    if settled:
        return _judge_uploaded(ctx, name, settled[0], local_digest)

    deleted = False
    for stale in assets:
        fresh = ctx.api.get_asset(stale["id"])
        if fresh is None:
            continue  # 404 — already gone
        if fresh.get("state") == "uploaded":
            return _judge_uploaded(ctx, name, fresh, local_digest)
        ctx.api.delete_asset(fresh["id"])
        ctx.log(
            f"    removed half-finished asset {name} "
            f"(id={fresh.get('id')}, state={fresh.get('state')})"
        )
        deleted = True
    return _Reconciled(deleted_stale=deleted)


def _settled_ok(ctx: _Ctx, name: str, local_digest: str) -> _Reconciled | None:
    """Cheap in-flight check: is the asset uploaded yet, and does it match?"""
    settled = [
        a for a in _assets_by_name(ctx.api, ctx.release_id, name) if a.get("state") == "uploaded"
    ]
    if not settled:
        return None
    digest = _asset_digest(settled[0])
    if not digest:
        return None  # not decidable yet; keep polling
    if digest == local_digest:
        return _Reconciled(done=True)
    return _judge_uploaded(ctx, name, settled[0], local_digest)


def _run_attempt(
    ctx: _Ctx,
    name: str,
    path: Path,
    local_digest: str,
    *,
    attempt_timeout: float,
    poll_interval: float,
) -> _Attempt:
    """One `gh release upload`, judged entirely by the assets API."""
    started = ctx.monotonic()
    handle = ctx.api.start_upload(ctx.tag, path)
    outcome = _Attempt(reason="the upload loop ended without a verdict")
    try:
        while True:
            rc = handle.poll()
            verdict = _settled_ok(ctx, name, local_digest)
            if verdict is not None and verdict.done:
                outcome = _Attempt(ok=True)
                break
            if verdict is not None and verdict.fatal:
                outcome = _Attempt(fatal=verdict.fatal)
                break

            if rc is not None:
                # gh exited. Its code proves nothing either way, so re-read the API a
                # few times: a proxy can make it exit non-zero on a finished upload, and
                # it can exit 0 having uploaded nothing.
                for _ in range(_RECHECK_TRIES):
                    ctx.sleep(_RECHECK_INTERVAL)
                    verdict = _settled_ok(ctx, name, local_digest)
                    if verdict is not None and verdict.done:
                        outcome = _Attempt(ok=True)
                        break
                    if verdict is not None and verdict.fatal:
                        outcome = _Attempt(fatal=verdict.fatal)
                        break
                else:
                    outcome = _Attempt(
                        reason=f"gh exited with code {rc} and the asset is not uploaded"
                    )
                break

            if ctx.monotonic() - started >= attempt_timeout:
                outcome = _Attempt(reason=f"attempt exceeded {int(attempt_timeout)}s")
                break

            ctx.sleep(poll_interval)
    finally:
        handle.stop()
        if not outcome.ok and not outcome.fatal:
            tail = handle.output_tail()
            if tail:
                outcome.reason += "\n" + "\n".join("      | " + ln for ln in tail.splitlines())
        handle.close()
    return outcome


def _upload_one(
    ctx: _Ctx,
    name: str,
    path: Path,
    local_digest: str,
    *,
    max_attempts: int,
    attempt_timeout: float,
    poll_interval: float,
    rand: Callable[[], float],
    backoffs: list[float],
) -> tuple[FileResult | None, str | None]:
    size = path.stat().st_size
    started = ctx.monotonic()
    replaced = False
    last_reason = ""

    for attempt in range(1, max_attempts + 1):
        state = _reconcile(ctx, name, local_digest)
        if state.fatal:
            return None, state.fatal
        replaced = replaced or state.deleted_stale
        if state.done:
            action = "skipped" if (attempt == 1 and not replaced) else (
                "replaced-stale" if replaced else "uploaded"
            )
            ctx.log(f"  {name}: {action}")
            return FileResult(name, action, attempt, size, ctx.monotonic() - started), None

        ctx.log(f"  {name}: uploading ({size} bytes), attempt {attempt}/{max_attempts}")
        handle_result = _run_attempt(
            ctx,
            name,
            path,
            local_digest,
            attempt_timeout=attempt_timeout,
            poll_interval=poll_interval,
        )
        if handle_result.fatal:
            return None, handle_result.fatal
        if handle_result.ok:
            action = "replaced-stale" if replaced else "uploaded"
            ctx.log(f"  {name}: {action} (attempt {attempt})")
            return FileResult(name, action, attempt, size, ctx.monotonic() - started), None

        last_reason = handle_result.reason
        ctx.log(f"  {name}: attempt {attempt} failed - {last_reason}")
        if attempt < max_attempts:
            delay = _backoff_delay(attempt, rand)
            backoffs.append(delay)
            ctx.log(f"  {name}: backing off {delay:.1f}s")
            ctx.sleep(delay)

    return None, f"{name}: gave up after {max_attempts} attempts ({last_reason})"


def preflight_local(dist: Path, expected: Sequence[str]) -> list[str]:
    """dist/ must hold EXACTLY the expected names, each non-empty."""
    problems: list[str] = []
    if not dist.is_dir():
        return [f"dist directory {dist} does not exist"]
    present = {p.name for p in dist.iterdir() if p.is_file()}
    wanted = set(expected)
    for name in sorted(wanted - present):
        problems.append(f"missing from {dist}: {name}")
    for name in sorted(present - wanted):
        problems.append(f"unexpected file in {dist}: {name}")
    for name in sorted(wanted & present):
        if (dist / name).stat().st_size == 0:
            problems.append(f"empty file in {dist}: {name}")
    return problems


def preflight_remote(
    remote: Sequence[dict], expected: Sequence[str], digests: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Refuse to touch a draft that already holds someone else's assets.

    Returns (fatal problems, warnings). Half-finished records outside the expected set
    are only warned about here — they are not ours to delete, and `verify` fails on them.
    """
    problems: list[str] = []
    warnings: list[str] = []
    wanted = set(expected)
    for asset in remote:
        name = str(asset.get("name"))
        if asset.get("state") != "uploaded":
            if name not in wanted:
                warnings.append(
                    f"half-finished asset not in the expected set, left alone: "
                    f"{name} (id={asset.get('id')}, state={asset.get('state')})"
                )
            continue
        if name not in wanted:
            problems.append(f"release already holds an unexpected uploaded asset: {name}")
            continue
        digest = _asset_digest(asset)
        if digest and digest != digests[name]:
            problems.append(
                f"{name}: uploaded with a different digest (remote {digest}, "
                f"local {digests[name]})"
            )
    return problems, warnings


def run_upload(
    api: Any,
    *,
    tag: str,
    version: str,
    dist: Path,
    release_id: int | None = None,
    max_attempts: int = 6,
    attempt_timeout: float = 1800.0,
    poll_interval: float = 15.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    rand: Callable[[], float] = random.random,
    log: Callable[[str], None] = _log,
) -> UploadRun:
    run = UploadRun()
    expected = expected_assets(version)

    try:
        release = resolve_release(api, tag, release_id)
    except GhError as exc:
        run.errors.append(str(exc))
        return run
    resolved_id = int(release["id"])
    log(f"release: id={resolved_id} tag={tag} draft={release.get('draft')}")

    problems = preflight_local(dist, expected)
    if problems:
        run.errors.extend(problems)
        return run

    digests = {name: sha256_file(dist / name) for name in expected}

    try:
        remote = api.list_assets(resolved_id)
    except GhError as exc:
        run.errors.append(str(exc))
        return run
    fatal, warnings = preflight_remote(remote, expected, digests)
    for warning in warnings:
        log("warning: " + warning)
    if fatal:
        run.errors.extend(fatal)
        run.errors.append(
            "the draft holds assets from another build - delete that draft by hand, then re-run"
        )
        return run

    ctx = _Ctx(api=api, release_id=resolved_id, tag=tag, sleep=sleep, monotonic=monotonic, log=log)
    for name in upload_order(expected):
        try:
            result, failure = _upload_one(
                ctx,
                name,
                dist / name,
                digests[name],
                max_attempts=max_attempts,
                attempt_timeout=attempt_timeout,
                poll_interval=poll_interval,
                rand=rand,
                backoffs=run.backoffs,
            )
        except GhError as exc:
            run.errors.append(f"{name}: {exc}")
            return run
        if failure or result is None:
            run.errors.append(failure or f"{name}: failed")
            return run
        run.results.append(result)

    run.ok = True
    return run


# --------------------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------------------


def run_verify(
    api: Any,
    *,
    tag: str,
    version: str,
    dist: Path,
    release_id: int | None = None,
    log: Callable[[str], None] = _log,
) -> VerifyRun:
    out = VerifyRun()
    expected = expected_assets(version)
    wanted = set(expected)

    try:
        release = resolve_release(api, tag, release_id)
    except GhError as exc:
        out.problems.append(str(exc))
        return out
    resolved_id = int(release["id"])

    out.problems.extend(preflight_local(dist, expected))

    try:
        remote = api.list_assets(resolved_id)
    except GhError as exc:
        out.problems.append(str(exc))
        return out

    settled: dict[str, dict] = {}
    for asset in remote:
        name = str(asset.get("name"))
        if asset.get("state") != "uploaded":
            out.problems.append(
                f"half-finished asset left on the release: {name} "
                f"(id={asset.get('id')}, state={asset.get('state')})"
            )
            continue
        if name not in wanted:
            out.problems.append(f"unexpected asset on the release: {name}")
            continue
        settled[name] = asset

    for name in expected:
        if name not in settled:
            out.problems.append(f"asset missing from the release: {name}")

    for name in sorted(settled):
        asset = settled[name]
        local_path = dist / name
        digest = _asset_digest(asset)
        ok = False
        if not local_path.is_file():
            pass  # already reported by preflight_local
        elif not digest:
            out.problems.append(f"{name}: the release reports no digest - cannot be verified")
        else:
            local_digest = sha256_file(local_path)
            ok = digest == local_digest
            if not ok:
                out.problems.append(
                    f"{name}: digest mismatch (remote {digest}, local {local_digest})"
                )
        out.rows.append((name, str(asset.get("state")), int(asset.get("size") or 0), ok))

    # An updater .sig without its payload would make the manifest point at nothing.
    for name in sorted(settled):
        if name.endswith(".sig") and name[: -len(".sig")] not in settled:
            out.problems.append(f"{name} is uploaded but its payload {name[:-4]} is not")

    out.problems.extend(_verify_manifest(api.repo, tag, version, dist, set(settled)))

    out.ok = not out.problems
    return out


def _verify_manifest(
    repo: str, tag: str, version: str, dist: Path, settled: set[str]
) -> list[str]:
    """Audit latest.json — the one asset a wrong value in turns into a broken auto-update.

    The digest check above already proved the local copy is byte-identical to the
    uploaded one, so reading it locally is the same as reading the published file.
    """
    problems: list[str] = []
    manifest_path = dist / MANIFEST_ASSET
    if not manifest_path.is_file():
        return [f"{MANIFEST_ASSET} is missing from {dist}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{MANIFEST_ASSET} is not readable JSON: {exc}"]

    if manifest.get("version") != version:
        problems.append(
            f"{MANIFEST_ASSET}: version is {manifest.get('version')!r}, expected {version!r}"
        )

    prefix = f"https://github.com/{repo}/releases/download/{tag}/"
    platforms = manifest.get("platforms") or {}
    if not isinstance(platforms, dict) or not platforms:
        return problems + [f"{MANIFEST_ASSET}: no platforms"]

    referenced_sigs: set[str] = set()
    for platform, entry in sorted(platforms.items()):
        url = str((entry or {}).get("url", ""))
        if not url.startswith(prefix):
            # Catches the upstream repo, the wrong tag, and `releases/latest/download/`
            # (which would make a shipped app follow whatever ships next) in one check.
            problems.append(f"{MANIFEST_ASSET}[{platform}]: url does not start with {prefix} - {url}")
            continue
        asset_name = url[len(prefix) :]
        if asset_name not in settled:
            problems.append(
                f"{MANIFEST_ASSET}[{platform}]: url points at {asset_name}, which is not an "
                "uploaded asset of this release"
            )
            continue
        sig_name = asset_name + ".sig"
        referenced_sigs.add(sig_name)
        sig_path = dist / sig_name
        if not sig_path.is_file():
            problems.append(f"{MANIFEST_ASSET}[{platform}]: no local {sig_name} to compare against")
            continue
        expected_sig = sig_path.read_text(encoding="utf-8").strip()
        if str((entry or {}).get("signature", "")) != expected_sig:
            problems.append(f"{MANIFEST_ASSET}[{platform}]: signature does not match {sig_name}")

    for path in sorted(dist.glob("*.sig")):
        if path.name not in referenced_sigs:
            problems.append(
                f"{path.name} ships in the release but no {MANIFEST_ASSET} platform references it "
                "- that platform would silently never see the update"
            )
    return problems


# --------------------------------------------------------------------------------------
# selftest helpers
# --------------------------------------------------------------------------------------


def run_cleanup_selftest(
    api: Any, *, release_id: int, log: Callable[[str], None] = _log
) -> int:
    """Delete a dry run's draft. Three guards stand between this and a real release."""
    try:
        release = api.get_release(release_id)
    except GhError as exc:
        _error(str(exc))
        return 1
    if release is None:
        log(f"release {release_id} is already gone")
        return 0

    tag = str(release.get("tag_name", ""))
    if not release.get("draft"):
        _error(f"refusing to delete release {release_id} ({tag}): it is NOT a draft")
        return 2
    if not tag.startswith(SELFTEST_TAG_PREFIX):
        _error(
            f"refusing to delete release {release_id}: tag {tag!r} does not start with "
            f"{SELFTEST_TAG_PREFIX!r}"
        )
        return 2

    api.delete_release(release_id)
    log(f"deleted draft release {release_id} ({tag})")

    # A draft never creates a tag, so this should always be empty. If it is not,
    # something published the draft — say so loudly and let a human delete the tag.
    try:
        refs = api.list_tag_refs(SELFTEST_TAG_PREFIX)
    except GhError as exc:
        _error(str(exc))
        return 1
    if refs:
        names = ", ".join(str(r.get("ref")) for r in refs)
        _error(
            f"selftest tags exist in the repo and were NOT deleted by this script: {names} "
            "- delete them by hand"
        )
        return 1
    return 0


def make_selftest_dist(
    *, version: str, tag: str, repo: str, dist: Path, big_mb: int = 90, log: Callable[[str], None] = _log
) -> int:
    """Write a throwaway dist/ with the real shape: 14 files, twins sharing content.

    Purely local — it never touches the network. latest.json is produced by the REAL
    packaging/make_update_manifest.py, with the same arguments release.yml passes, so a
    dry run exercises the manifest that ships.
    """
    if dist.exists() and any(dist.iterdir()):
        _error(f"{dist} already exists and is not empty - refusing to overwrite it")
        return 1
    dist.mkdir(parents=True, exist_ok=True)

    sizes = {
        "OpenWorker-macos-arm64.app.tar.gz": 1,
        "OpenWorker-macos-x64.app.tar.gz": 1,
        "OpenWorker-macos-arm64.dmg": 2,
        "OpenWorker-macos-x64.dmg": 2,
        "OpenWorker-windows-setup.exe": max(1, big_mb),
        "OpenWorker-windows.msi": 3,
    }
    for name, megabytes in sizes.items():
        _write_random(dist / name, megabytes)
        twin = SELFTEST_TWINS.get(name)
        if twin:
            (dist / twin.format(version=version)).write_bytes((dist / name).read_bytes())
        log(f"wrote {name} ({megabytes} MB)")

    for stem in ("OpenWorker-macos-arm64.app.tar.gz", "OpenWorker-macos-x64.app.tar.gz",
                 "OpenWorker-windows-setup.exe"):
        fake = base64.b64encode(os.urandom(96)).decode("ascii")
        (dist / (stem + ".sig")).write_text(fake + "\n", encoding="utf-8")

    manifest_script = _REPO_ROOT / "packaging" / "make_update_manifest.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(manifest_script),
            "--version", version,
            "--tag", tag,
            "--repo", repo,
            "--dist", str(dist),
            "--out", str(dist / MANIFEST_ASSET),
            "--notes", f"OpenWorker {version}",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    sys.stderr.write(proc.stderr or "")
    if proc.returncode != 0:
        _error(f"make_update_manifest.py failed with code {proc.returncode}")
        return 1
    log((proc.stdout or "").strip())

    made = sorted(p.name for p in dist.iterdir() if p.is_file())
    want = sorted(expected_assets(version))
    if made != want:
        _error(f"generated {len(made)} files, expected {len(want)}: {sorted(set(made) ^ set(want))}")
        return 1
    log(f"selftest dist ready: {len(made)} files in {dist}")
    return 0


def _write_random(path: Path, megabytes: int) -> None:
    with open(path, "wb") as handle:
        for _ in range(megabytes):
            handle.write(os.urandom(1024 * 1024))


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _write_github_output(run: UploadRun) -> None:
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as handle:
            handle.write(f"uploaded={run.uploaded}\n")
            handle.write(f"skipped={run.skipped}\n")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = ["", "### Release assets", "", "| asset | action | attempts | bytes | seconds |",
                 "| --- | --- | ---: | ---: | ---: |"]
        for r in run.results:
            lines.append(f"| {r.name} | {r.action} | {r.attempts} | {r.size} | {r.seconds:.0f} |")
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def cmd_upload(args: argparse.Namespace) -> int:
    api = GhApi(args.repo)
    run = run_upload(
        api,
        tag=args.tag,
        version=args.version,
        dist=args.dist,
        release_id=args.release_id,
        max_attempts=args.max_attempts,
        attempt_timeout=args.attempt_timeout,
        poll_interval=args.poll_interval,
    )
    print("")
    print(f"{'asset':44s} {'action':16s} {'try':>4s} {'bytes':>12s} {'secs':>7s}")
    for r in run.results:
        print(f"{r.name:44s} {r.action:16s} {r.attempts:4d} {r.size:12d} {r.seconds:7.0f}")
    print(f"uploaded={run.uploaded} skipped={run.skipped}")
    _write_github_output(run)
    if not run.ok:
        for problem in run.errors:
            _error(problem)
        return 1
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    api = GhApi(args.repo)
    out = run_verify(
        api, tag=args.tag, version=args.version, dist=args.dist, release_id=args.release_id
    )
    if not out.ok:
        for problem in out.problems:
            _error(problem)
        print(f"verify FAILED: {len(out.problems)} problem(s)")
        return 1
    print("")
    print(f"{'asset':44s} {'state':10s} {'bytes':>12s}  digest")
    for name, state, size, ok in out.rows:
        print(f"{name:44s} {state:10s} {size:12d}  {'ok' if ok else 'BAD'}")
    print(f"verify OK: {len(out.rows)} assets, digests match, latest.json consistent")
    return 0


def cmd_make_selftest_dist(args: argparse.Namespace) -> int:
    return make_selftest_dist(
        version=args.version, tag=args.tag, repo=args.repo, dist=args.dist, big_mb=args.big_mb
    )


def cmd_cleanup_selftest(args: argparse.Namespace) -> int:
    return run_cleanup_selftest(GhApi(args.repo), release_id=args.release_id)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, help="owner/name, e.g. ldfpku/openworker")
    parser.add_argument("--tag", required=True, help="the release's tag, e.g. v0.6.2")
    parser.add_argument("--dist", required=True, type=Path, help="the staged artifacts dir")
    parser.add_argument(
        "--release-id", type=int, default=None, help="cross-check: must be the tag's release"
    )
    parser.add_argument("--version", default=None, help="bare version (default: tag without 'v')")


def main(argv: Sequence[str] | None = None) -> int:
    _harden_streams()
    ap = argparse.ArgumentParser(description="Serial, idempotent GitHub release asset uploads.")
    subs = ap.add_subparsers(dest="command", required=True)

    up = subs.add_parser("upload", help="upload dist/ into the tag's release, one file at a time")
    _add_common(up)
    up.add_argument("--max-attempts", type=int, default=6)
    up.add_argument("--attempt-timeout", type=float, default=1800.0)
    up.add_argument("--poll-interval", type=float, default=15.0)
    up.set_defaults(func=cmd_upload)

    ve = subs.add_parser("verify", help="read-only audit of the finished release")
    _add_common(ve)
    ve.set_defaults(func=cmd_verify)

    mk = subs.add_parser("make-selftest-dist", help="build a throwaway dist/ for a dry run")
    mk.add_argument("--version", required=True)
    mk.add_argument("--tag", required=True)
    mk.add_argument("--repo", required=True)
    mk.add_argument("--dist", required=True, type=Path)
    mk.add_argument("--big-mb", type=int, default=90)
    mk.set_defaults(func=cmd_make_selftest_dist)

    cl = subs.add_parser("cleanup-selftest", help="delete a dry run's draft release")
    cl.add_argument("--repo", required=True)
    cl.add_argument("--release-id", type=int, required=True)
    cl.set_defaults(func=cmd_cleanup_selftest)

    args = ap.parse_args(argv)
    if getattr(args, "version", None) is None and getattr(args, "tag", None) is not None:
        args.version = args.tag[1:] if args.tag.startswith("v") else args.tag
    try:
        return int(args.func(args))
    except GhError as exc:
        _error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
