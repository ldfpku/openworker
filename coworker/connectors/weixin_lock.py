"""One-poller-per-token guard for the weixin connector.

`getupdates` is consume-on-read: whichever poller asks first takes the batch and the
other never sees it. Two openworker processes on one bot token therefore split the
inbound stream roughly in half, silently — no error anywhere, messages simply go
missing. The invariant was documented (weixin_adapter's module docstring) but nothing
enforced it, and the repo's own README hands people the recipe: a hand-run
`openworker-server --port 8765` alongside `npm run tauri dev` is two server processes
over one `%APPDATA%` profile, each starting a gateway.

An OS advisory lock rather than a PID file, deliberately: the kernel drops the lock
when the holding process exits, however it exits, so there is no stale lock to reclaim
and no way for a crash to wedge the connector shut. A PID file would need liveness
checks and a dead-owner override, and getting that wrong strands the user with a
connector that will not start.

The lock is keyed by a token fingerprint, never the token: this path is logged and
listed by anything browsing the state dir.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# The pid record lives at offset 0; the lock byte sits far past it. On Windows a
# byte-range lock blocks every other handle -- including our own reader -- so locking
# byte 0 made `holder_pid()` unreadable and the "held by pid N" message empty.
_PID_FIELD = 16
_LOCK_OFFSET = 4096

# The error the user sees when a second poller loses the race. Phrased as the action
# that fixes it, because the symptom (half the messages, no error) gives no clue.
LOCK_BUSY_MESSAGE = (
    "another OpenWorker instance on this computer is already receiving WeChat "
    "messages for this bot. Close the other one — two pollers on one bot token "
    "each take half the messages."
)


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


class TokenLock:
    """Exclusive, process-scoped claim on one bot token. Not reentrant.

    `acquire()` returns False rather than raising when another process holds it —
    losing the race is an expected outcome, not an error path.
    """

    def __init__(self, token: str, root: Path):
        self.path = Path(root) / f"poller-{token_fingerprint(token)}.lock"
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True  # already ours
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            # A state dir we cannot write to must not take the connector down with
            # it: run unlocked and say so, rather than refusing to receive messages.
            logger.warning("weixin: cannot open poll lock (%s) — continuing", exc)
            return True
        try:
            _lock_exclusive(fd)
        except OSError:
            os.close(fd)
            return False
        except Exception as exc:  # no locking primitive on this platform
            logger.warning("weixin: poll lock unsupported (%s) — continuing", exc)
            os.close(fd)
            return True
        self._fd = fd
        # Diagnostics only — the lock excludes, not this text. Written as a
        # fixed-width record rather than truncate-then-write, because Windows
        # refuses to truncate across the byte range we just locked, which left the
        # file empty and the "held by pid N" message with nothing to say.
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, f"{os.getpid():<{_PID_FIELD}}".encode("ascii"))
        except OSError:
            pass
        return True

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock(fd)
        except Exception:
            pass  # closing the fd drops the lock regardless
        try:
            os.close(fd)
        except OSError:
            pass
        # The file is left behind on purpose: unlinking it races another process
        # that has just opened it and would hand both of them "their own" lock.

    def holder_pid(self) -> Optional[int]:
        """The pid recorded by whoever holds it, for the error message. Advisory —
        the file may be empty or stale-looking mid-handover."""
        try:
            raw = self.path.read_text(encoding="ascii")[:_PID_FIELD].strip()
            return int(raw) if raw else None
        except (OSError, ValueError):
            return None


if os.name == "nt":  # pragma: no cover - platform split, both sides covered by tests

    import msvcrt

    def _lock_exclusive(fd: int) -> None:
        # One byte at _LOCK_OFFSET -- past EOF, which is legal on Windows, and clear
        # of the pid record so that stays readable.
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:  # pragma: no cover - platform split

    import fcntl

    def _lock_exclusive(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
