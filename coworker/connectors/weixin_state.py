"""Mutable on-disk state for the weixin connector.

Lives under `state_dir()/weixin/` — NOT in the SecretStore, because the sync
cursor is rewritten on every long-poll. Files:

- `runtime.json`                       {"account_id", "base_url"} — lets the
                                       stateless sender find the API base
- `{account_id}.sync.json`             {"get_updates_buf": "<cursor>"}
- `{account_id}.context-tokens.json`   flat {peer_user_id: context_token}
- `media/`                             decrypted inbound media cache

All writes are atomic (tmp file + os.replace) so a crash never truncates
state; corrupt or missing files read back as empty defaults, never raise.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from ..secrets import state_dir

logger = logging.getLogger(__name__)

# Module-level indirection so tests can simulate a failing replace.
_replace = os.replace

# One lock for all context-token read-modify-writes in this process. The adapter
# mutates tokens on the event loop while the sender drops them from a tool
# thread (through its own WeixinState instance), so the lock must be module
# level, not per-instance — otherwise a -14 token drop can be resurrected by a
# concurrent inbound write.
_IO_LOCK = threading.Lock()


def _read_json(path: Path) -> dict:
    """Best-effort read: missing, corrupt, or non-dict content -> {}."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("weixin state: unreadable %s (%s) — treating as empty", path.name, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_json(path: Path, payload: dict) -> bool:
    """Write tmp in the same dir then os.replace — a failure leaves the old
    file intact. Never raises (state persistence must not crash the poller).
    The tmp name is unique per write (two threads writing the same target must
    not truncate each other's tmp), and replace retries briefly on the Windows
    sharing-violation window against a concurrent reader."""
    tmp = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for attempt in range(3):
            try:
                _replace(tmp, path)
                return True
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
        return True
    except Exception as exc:
        logger.warning("weixin state: failed to write %s: %s", path.name, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


class WeixinState:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else state_dir() / "weixin"
        # account_id -> {peer: token}; disk stays the source of truth (see
        # context_token's re-read-on-miss).
        self._tokens: dict[str, dict[str, str]] = {}

    # -- paths ------------------------------------------------------------
    def _runtime_path(self) -> Path:
        return self.root / "runtime.json"

    def _sync_path(self, account_id: str) -> Path:
        return self.root / f"{account_id}.sync.json"

    def _tokens_path(self, account_id: str) -> Path:
        return self.root / f"{account_id}.context-tokens.json"

    # -- runtime (account_id + base_url for the stateless sender) ---------
    def load_runtime(self) -> dict:
        data = _read_json(self._runtime_path())
        out: dict = {}
        if data.get("account_id"):
            out["account_id"] = str(data["account_id"])
        if data.get("base_url"):
            out["base_url"] = str(data["base_url"])
        return out

    def save_runtime(self, account_id: str, base_url: str) -> None:
        _atomic_write_json(
            self._runtime_path(), {"account_id": account_id, "base_url": base_url}
        )

    # -- long-poll cursor -------------------------------------------------
    def load_sync(self, account_id: str) -> str:
        buf = _read_json(self._sync_path(account_id)).get("get_updates_buf", "")
        return buf if isinstance(buf, str) else ""

    def save_sync(self, account_id: str, buf: str) -> None:
        _atomic_write_json(self._sync_path(account_id), {"get_updates_buf": buf})

    # -- context tokens ---------------------------------------------------
    def _load_tokens(self, account_id: str) -> dict[str, str]:
        data = _read_json(self._tokens_path(account_id))
        return {
            str(peer): token
            for peer, token in data.items()
            if isinstance(token, str) and token
        }

    def context_token(self, account_id: str, peer: str) -> str | None:
        cache = self._tokens.get(account_id)
        if cache is None or peer not in cache:
            # The sender runs in a different thread/process from the poller
            # that stored the token — re-read from disk on a cache miss.
            cache = self._load_tokens(account_id)
            self._tokens[account_id] = cache
        return cache.get(peer)

    def set_context_token(self, account_id: str, peer: str, token: str) -> None:
        # Locked read-modify-write: a concurrent drop (sender thread, -14 path)
        # must not be resurrected by this write landing after it.
        with _IO_LOCK:
            tokens = self._load_tokens(account_id)
            tokens[peer] = token
            self._tokens[account_id] = tokens
            _atomic_write_json(self._tokens_path(account_id), tokens)

    def drop_context_token(self, account_id: str, peer: str) -> None:
        with _IO_LOCK:
            tokens = self._load_tokens(account_id)
            tokens.pop(peer, None)
            self._tokens[account_id] = tokens
            _atomic_write_json(self._tokens_path(account_id), tokens)

    # -- media cache ------------------------------------------------------
    def media_dir(self) -> Path:
        path = self.root / "media"
        path.mkdir(parents=True, exist_ok=True)
        return path
