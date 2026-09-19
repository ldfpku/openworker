"""Secret store — one canonical, file-backed store for connector/MCP credentials.

Design (from OpenClaw): secrets **never enter the model's context, prompts, or traces**.
The store holds profiles keyed by `connector[:account]`; values may be literals OR
`${ENV_VAR}` references resolved at read time from the process env / `~/.config/coworker/.env`.

v1 is a `0600` JSON file behind this interface; the interface is what callers depend on, so
a Keychain / age-encrypted backend can swap in later without touching them.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import procutil

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_IS_WINDOWS = sys.platform == "win32"

logger = logging.getLogger(__name__)


class SecretStoreError(Exception):
    """Base class for SecretStore failures callers may want to tell apart."""


class SecretStoreReadError(SecretStoreError):
    """The secret file exists but could not be read or parsed.

    Raised instead of answering "empty store", because every writer in this module is a
    read-modify-write: reading `{}` off a file that is merely locked or torn and then
    saving it back would replace every stored credential -- provider API keys, every
    OAuth token, every connector profile -- with the single entry being written. None of
    that is recoverable locally; the user would have to re-issue keys at each provider
    and walk through every OAuth flow again.

    `detail` is safe to log: it is an errno string for OS failures and a bare exception
    class name for decode/parse failures, never any bytes from the file itself. The
    underlying exception is deliberately NOT chained or retained -- `json.JSONDecodeError`
    carries the entire document in `.doc`, so keeping it reachable would put the whole
    secret file one `repr()` away from an error report.
    """

    def __init__(self, path: Path, detail: str = "") -> None:
        super().__init__(
            f"secret store {path} exists but could not be read"
            + (f": {detail}" if detail else "")
        )
        self.path = path
        self.detail = detail


def state_dir() -> Path:
    """Where coworker keeps its state — the one cross-platform source of truth.

    Resolution order:
    1. `$COWORKER_STATE_DIR` — explicit override on any OS (used by tests/sidecars).
    2. Windows: `%APPDATA%\\coworker` (e.g. `C:\\Users\\You\\AppData\\Roaming\\coworker`),
       the native per-user app-data location.
    3. macOS / Linux: `~/.config/coworker` (XDG-style, unchanged from prior behavior).
    """
    base = os.environ.get("COWORKER_STATE_DIR")
    if base:
        return Path(base).expanduser()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "coworker"
    return Path.home() / ".config" / "coworker"


def _load_dotenv(path: Path) -> dict[str, str]:
    """`${VAR}` fallbacks from the sidecar `.env`; unreadable means "no fallbacks".

    This sits underneath `SecretStore.get`, which promises not to raise, so a locked
    or non-UTF-8 `.env` (cp936 machines write those) must not become an exception out
    of a credential lookup. Nothing is written from here, so degrading is safe: the
    worst case is a `${VAR}` ref left unresolved, which `resolve` already handles.
    """
    env: dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return env
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("ignoring unreadable %s (%s)", path, type(exc).__name__)
        return env
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _restrict_to_user(path: Path, *, is_dir: bool) -> None:
    """Restrict a path so only the current user can access it.

    POSIX expresses this with mode bits (0700 dir / 0600 file). Windows has no such bits —
    `os.chmod` there only toggles the read-only flag, so a 0600 chmod is a silent no-op and
    the file inherits broad ACLs (SYSTEM, Administrators, …). Use an ACL instead: strip
    inherited entries and grant the current user alone. Best-effort on Windows so a transient
    icacls failure never blocks saving a key."""
    if _IS_WINDOWS:
        user = os.environ.get("USERNAME")
        if not user:
            return
        domain = os.environ.get("USERDOMAIN")
        account = f"{domain}\\{user}" if domain else user
        # A directory grant MUST be inheritable — (OI) object-inherit for files, (CI)
        # container-inherit for subdirs — so everything created inside (the SQLite stores,
        # conversations, …) inherits the user's access. Without these flags, /inheritance:r
        # leaves the directory with a non-inheritable ACE and any child file ends up with an
        # empty DACL → sqlite3 "unable to open database file", crashing the server on launch.
        grant = f"{account}:(OI)(CI)F" if is_dir else f"{account}:F"
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", grant],
                capture_output=True,
                check=False,
                **procutil.popen_kwargs(),
            )
        except OSError:
            pass
        return
    os.chmod(path, 0o700 if is_dir else 0o600)


def _atomic_private_write(target: Path, content: str) -> Path:
    """Write `content` to `target` atomically, never exposing it through a readable temp.

    The temp file used to be created by `Path.write_text` and only chmod-ed afterwards, so
    the plaintext sat on disk at the umask default (0644 on a normal box) for the length of
    the write — readable by every local process and by anything backing the directory up.
    That is issue #143; the same pattern was in both writers here.

    `tempfile.mkstemp` creates with 0600 and O_EXCL before a byte is written, which also
    removes the fixed `<name>.tmp` filename. That name was predictable, so a local attacker
    could pre-create it as a symlink and have the write land wherever the link pointed.

    Windows gets no mode bits from mkstemp, so the ACL is applied to the still-empty file
    before the content goes in.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _restrict_to_user(target.parent, is_dir=True)
    except OSError:
        pass

    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        _restrict_to_user(tmp, is_dir=False)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return target


def write_private_text(path: str | Path, content: str) -> Path:
    """Atomically write a user-only text file using the SecretStore's OS protections."""
    return _atomic_private_write(Path(path).expanduser(), content)


class SecretStore:
    """File-backed secret store. Reads resolve `${VAR}` refs; status never leaks values."""

    def __init__(self, path: Optional[str | Path] = None) -> None:
        self.path = Path(path).expanduser() if path else state_dir() / "secrets.json"
        self._dotenv_path = self.path.parent / ".env"
        self._lock = threading.Lock()
        self._read_warned = False

    # -- reads ------------------------------------------------------------------
    def get(self, profile: str) -> Optional[dict[str, Any]]:
        """Return a profile with `${VAR}` refs resolved, or None if absent.

        Degrades to None when the file is unreadable — see `_read_or_empty`.
        """
        data = self._read_or_empty("get").get(profile)
        if data is None:
            return None
        return self.resolve(data)

    def resolve(self, value: Any) -> Any:
        """Resolve `${VAR}` refs in a value (recursively) from env + the local `.env`."""
        env = _load_dotenv(self._dotenv_path)

        def _walk(v: Any) -> Any:
            if isinstance(v, str):
                return _REF.sub(
                    lambda m: os.environ.get(m.group(1))
                    or env.get(m.group(1))
                    or m.group(0),
                    v,
                )
            if isinstance(v, dict):
                return {k: _walk(x) for k, x in v.items()}
            if isinstance(v, list):
                return [_walk(x) for x in v]
            return v

        return _walk(value)

    def status(self) -> list[dict[str, Any]]:
        """Profile metadata only — **never** the secret values themselves.

        Degrades to an empty list when the file is unreadable — see `_read_or_empty`.
        """
        out: list[dict[str, Any]] = []
        for profile, data in self._read_or_empty("status").items():
            data = data if isinstance(data, dict) else {}
            expires = data.get("expires")
            expired = isinstance(expires, (int, float)) and expires < time.time()
            out.append(
                {
                    "profile": profile,
                    "type": data.get("type"),
                    "account": data.get("account_id"),
                    "expired": bool(expired),
                }
            )
        return out

    # -- writes -----------------------------------------------------------------
    # Both writers are read-modify-write over the whole file, so both start from
    # `_read` (the raising variant). If the current contents cannot be read, they
    # raise `SecretStoreReadError` and touch nothing: a caller that cannot save is
    # a caller that can retry, while a caller that saved over everything is not.
    def put(self, profile: str, data: dict[str, Any]) -> None:
        """Store a profile. Raises `SecretStoreReadError` (writing nothing) if the
        existing file cannot be read — see `_read`."""
        with self._lock:
            store = self._read()
            store[profile] = data
            self._write(store)

    def delete(self, profile: str) -> bool:
        """Drop a profile; False if it was not there. Raises `SecretStoreReadError`
        (writing nothing) if the existing file cannot be read — see `_read`."""
        with self._lock:
            store = self._read()
            if profile not in store:
                return False
            del store[profile]
            self._write(store)
            return True

    # -- internals --------------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        """The whole store, or `SecretStoreReadError` — never a silent `{}`.

        Two cases that used to look identical here have opposite consequences:

        * **No file.** A legitimately empty store; this is how the first secret ever
          gets saved. Answer `{}`.
        * **A file that exists but will not read or parse.** A lock held by a backup
          agent, an IO error, a torn or externally mangled file, GBK bytes written by
          some other tool. Answering `{}` made the next `put`/`delete` write that `{}`
          back with one key added, destroying every other credential on disk.

        The one deliberate hole is a file that is empty or all whitespace: there is
        nothing left in it to protect (`_atomic_private_write` never leaves a partial
        file, but an fsync-less `os.replace` plus a power cut can still leave a
        zero-length one), and refusing to write would strand the user with a store they
        can never add to again without deleting the file by hand.
        """
        # Every `raise` below happens *outside* its `except` block, on purpose. Raising
        # from inside one leaves the original on `__context__` even with `from None`, and
        # `json.JSONDecodeError` keeps the entire document in `.doc` — that would put the
        # whole plaintext secret file one attribute hop away from any error reporter.
        raw: Optional[str] = None
        detail = ""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            detail = str(exc)  # errno strings carry no file content
        except UnicodeDecodeError as exc:
            detail = type(exc).__name__
        if raw is None:
            raise SecretStoreReadError(self.path, detail)
        if not raw.strip():
            return {}
        data: Any = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            detail = type(exc).__name__
        if detail:
            raise SecretStoreReadError(self.path, detail)
        if not isinstance(data, dict):
            raise SecretStoreReadError(self.path, "top-level JSON is not an object")
        return data

    def _read_or_empty(self, op: str) -> dict[str, Any]:
        """Read-only variant: degrade to "nothing configured", but say so in the log.

        `get`/`status` sit on hot paths — session start, tool loading, every provider
        lookup — so raising there would take down work that has nothing to do with the
        damaged file. They degrade instead. Degrading normally opens its own path to
        data loss (the UI shows no credential, the user reconnects, the save clobbers
        the file); that path is closed here because `put` and `delete` share `_read`
        and refuse to write at all while the file is unreadable.
        """
        try:
            store = self._read()
        except SecretStoreReadError as exc:
            # Once per failure streak: `get` runs often enough to flood the log.
            if not self._read_warned:
                self._read_warned = True
                logger.warning(
                    "secret store %s is unreadable (%s); %s reports nothing configured "
                    "and saving stays disabled until the file can be read again",
                    exc.path,
                    exc.detail,
                    op,
                )
            return {}
        self._read_warned = False
        return store

    def _write(self, store: dict[str, Any]) -> None:
        _atomic_private_write(self.path, json.dumps(store, indent=2))
