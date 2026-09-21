"""Tests for the SecretStore (C0)."""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import sys
import time
import traceback
from pathlib import Path

import pytest

import coworker.secrets as secrets_module
from coworker.secrets import SecretStore, SecretStoreReadError


def test_put_get_round_trip(tmp_path):
    store = SecretStore(tmp_path / "secrets.json")
    store.put("slack:default", {"type": "token", "bot_token": "xoxb-123"})
    assert store.get("slack:default") == {"type": "token", "bot_token": "xoxb-123"}
    assert store.get("missing") is None


def test_env_ref_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_TOK", "from-env")
    store = SecretStore(tmp_path / "secrets.json")
    store.put("slack:default", {"type": "token", "bot_token": "${MY_TOK}"})
    assert store.get("slack:default")["bot_token"] == "from-env"


def test_dotenv_ref_resolution(tmp_path):
    (tmp_path / ".env").write_text('DOCS_TOKEN = "shhh"\n', encoding="utf-8")
    store = SecretStore(tmp_path / "secrets.json")
    store.put("docs:default", {"headers": {"Authorization": "Bearer ${DOCS_TOKEN}"}})
    assert store.get("docs:default")["headers"]["Authorization"] == "Bearer shhh"


def test_unresolved_ref_left_intact(tmp_path):
    store = SecretStore(tmp_path / "secrets.json")
    store.put("x", {"v": "${NOPE_NOT_SET}"})
    assert store.get("x")["v"] == "${NOPE_NOT_SET}"


def test_status_hides_values(tmp_path):
    store = SecretStore(tmp_path / "secrets.json")
    store.put(
        "gmail:default",
        {
            "type": "oauth",
            "access": "secret",
            "account_id": "me@x.com",
            "expires": time.time() - 10,
        },
    )
    store.put("slack:default", {"type": "token", "bot_token": "xoxb"})
    status = {row["profile"]: row for row in store.status()}
    assert status["gmail:default"]["type"] == "oauth"
    assert status["gmail:default"]["account"] == "me@x.com"
    assert status["gmail:default"]["expired"] is True
    assert status["slack:default"]["expired"] is False
    # No secret material anywhere in the status payload.
    blob = str(store.status())
    assert "secret" not in blob and "xoxb" not in blob


def test_secrets_file_is_restricted(tmp_path):
    """The secrets file must be restricted to the current user. POSIX expresses this as mode
    0600; Windows has no such bits, so we assert the ACL instead (inheritance stripped, only
    the current user granted)."""
    path = tmp_path / "secrets.json"
    SecretStore(path).put("x", {"a": 1})
    if sys.platform == "win32":
        # encoding/errors: icacls prints in the console codepage (cp936 on a zh-CN box),
        # and decoding that as UTF-8 raises inside subprocess's reader thread, losing stdout.
        out = subprocess.run(
            ["icacls", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
        user = os.environ.get("USERNAME", "")
        assert user and user in out  # current user is granted
        # Inherited broad principals must be gone after /inheritance:r.
        assert "NT AUTHORITY\\SYSTEM" not in out
        assert "BUILTIN\\Administrators" not in out
    else:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_delete(tmp_path):
    store = SecretStore(tmp_path / "secrets.json")
    store.put("x", {"a": 1})
    assert store.delete("x") is True
    assert store.delete("x") is False
    assert store.get("x") is None


# --- unreadable store: never overwrite what cannot be read ------------------------
#
# Every writer here is a read-modify-write over the whole file. `_read` used to answer
# `{}` for "file exists but would not read", so one transient failure -- a backup agent
# holding a lock, an IO error, a torn or externally mangled file, cp936 bytes from some
# other tool -- made the next save replace every provider key, OAuth token and connector
# profile with the single entry being written. None of that is locally recoverable.


def _unreadable(monkeypatch, path, exc):
    """Make exactly `path` fail to read, leaving every other file alone."""
    original = Path.read_text

    def guarded(self, *args, **kwargs):
        if self == path:
            raise exc
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)


def _stocked(tmp_path, name="secrets.json"):
    """A store with two real credentials already on disk, plus its raw bytes."""
    store = SecretStore(tmp_path / name)
    store.put("provider:openai", {"type": "token", "api_key": "sk-REAL-1"})
    store.put("gmail:me@x.com", {"type": "oauth", "refresh_token": "rt-REAL-2"})
    return store, store.path.read_bytes()


def test_put_refuses_when_read_raises_oserror(tmp_path, monkeypatch):
    store, before = _stocked(tmp_path)
    _unreadable(monkeypatch, store.path, OSError(13, "Permission denied"))
    with pytest.raises(SecretStoreReadError) as caught:
        store.put("provider:anthropic", {"type": "token", "api_key": "sk-NEW"})
    assert caught.value.path == store.path
    assert store.path.read_bytes() == before  # not one byte written


def test_put_refuses_on_corrupt_json(tmp_path):
    store, _ = _stocked(tmp_path)
    torn = '{"provider:openai": {"api_key": "sk-REAL-1"}, "gmail'
    store.path.write_text(torn, encoding="utf-8")
    with pytest.raises(SecretStoreReadError):
        store.put("provider:anthropic", {"type": "token", "api_key": "sk-NEW"})
    assert store.path.read_text(encoding="utf-8") == torn


def test_put_refuses_on_non_utf8_bytes(tmp_path):
    """cp936 boxes have written GBK over coworker state files before; that used to
    escape as a raw UnicodeDecodeError, which the old `except` clause never caught."""
    store, _ = _stocked(tmp_path)
    gbk = '{"provider:openai": {"note": "\u5bc6\u94a5"}}'.encode("gbk")
    store.path.write_bytes(gbk)
    with pytest.raises(SecretStoreReadError):
        store.put("provider:anthropic", {"type": "token", "api_key": "sk-NEW"})
    assert store.path.read_bytes() == gbk


@pytest.mark.parametrize("body", ["null", "[]", '"a string"', "42"])
def test_put_refuses_when_top_level_is_not_an_object(tmp_path, body):
    store, _ = _stocked(tmp_path)
    store.path.write_text(body, encoding="utf-8")
    with pytest.raises(SecretStoreReadError):
        store.put("provider:anthropic", {"api_key": "sk-NEW"})
    assert store.path.read_text(encoding="utf-8") == body


def test_delete_refuses_when_unreadable(tmp_path):
    """`delete` used to answer False here -- "no such profile" -- which is a lie that
    invites the caller to move on as though the credential were already gone."""
    store, _ = _stocked(tmp_path)
    store.path.write_text("not json at all", encoding="utf-8")
    with pytest.raises(SecretStoreReadError):
        store.delete("provider:openai")
    assert store.path.read_text(encoding="utf-8") == "not json at all"


def test_missing_file_still_accepts_the_first_secret(tmp_path):
    store = SecretStore(tmp_path / "nested" / "secrets.json")
    assert not store.path.exists()
    store.put("provider:openai", {"type": "token", "api_key": "sk-1"})
    assert store.get("provider:openai") == {"type": "token", "api_key": "sk-1"}


@pytest.mark.parametrize("body", ["", "   \n\t "])
def test_empty_file_is_treated_as_an_empty_store(tmp_path, body):
    """The one deliberate hole: a zero-length file holds nothing left to protect, and
    refusing it would strand the user with a store they can never add to again."""
    store = SecretStore(tmp_path / "secrets.json")
    store.path.write_text(body, encoding="utf-8")
    store.put("provider:openai", {"type": "token", "api_key": "sk-1"})
    assert store.get("provider:openai")["api_key"] == "sk-1"


def test_writes_leave_neighbouring_profiles_alone(tmp_path):
    store, _ = _stocked(tmp_path)
    store.put("slack:default", {"type": "token", "bot_token": "xoxb"})
    store.put("provider:openai", {"type": "token", "api_key": "sk-ROTATED"})
    assert store.delete("gmail:me@x.com") is True
    on_disk = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(on_disk) == {"provider:openai", "slack:default"}
    assert on_disk["provider:openai"]["api_key"] == "sk-ROTATED"
    assert on_disk["slack:default"]["bot_token"] == "xoxb"


def test_read_paths_degrade_and_log_instead_of_raising(tmp_path, caplog):
    """`get`/`status` run on session start, tool loading and every provider lookup, so
    they must not raise -- but they must not stay quiet either."""
    store, _ = _stocked(tmp_path)
    store.path.write_text("{oops", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="coworker.secrets"):
        assert store.get("provider:openai") is None
        assert store.status() == []
        assert store.get("gmail:me@x.com") is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1  # once per failure streak, not once per call
    assert str(store.path) in warnings[0].getMessage()


def test_warning_fires_again_after_the_file_breaks_a_second_time(tmp_path, caplog):
    store, good = _stocked(tmp_path)
    with caplog.at_level(logging.WARNING, logger="coworker.secrets"):
        store.path.write_text("{oops", encoding="utf-8")
        store.get("x")
        store.path.write_bytes(good)
        assert store.get("provider:openai")["api_key"] == "sk-REAL-1"  # streak ends
        store.path.write_text("{oops", encoding="utf-8")
        store.get("x")
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2


def test_degraded_read_cannot_lead_to_an_overwrite(tmp_path):
    """The full loss chain, end to end: the UI reads "nothing configured" off a damaged
    file and the user reconnects. The save must fail rather than clobber the file."""
    store, before = _stocked(tmp_path)
    store.path.write_text('{"provider:openai": {"api_k', encoding="utf-8")
    assert store.status() == []  # looks like a fresh install
    assert store.get("provider:openai") is None
    with pytest.raises(SecretStoreReadError):
        store.put("provider:openai", {"type": "token", "api_key": "sk-RECONFIGURED"})
    assert store.path.read_bytes() != before  # still damaged...
    assert b"sk-RECONFIGURED" not in store.path.read_bytes()  # ...but not overwritten


# A made-up value planted in damaged files; no error, log line or frame may ever carry it.
_CANARY = "sk-TEST-CANARY-0000"

# One payload per way the file can fail to load. Each decode/parse error keeps the whole
# file somewhere a shallow check misses: UnicodeDecodeError in its C-level `.object`,
# JSONDecodeError in `.doc` (which its own repr() leaves out), and a parsed non-object
# top level in whatever local still holds it.
_DAMAGED = [
    pytest.param(('{"provider:openai": {"api_key": "%s"' % _CANARY).encode(), id="torn-json"),
    pytest.param(
        ('{"provider:openai": {"api_key": "%s", "note": "密钥"}}' % _CANARY).encode(
            "gbk"
        ),
        id="gbk-bytes",
    ),
    pytest.param(('["%s"]' % _CANARY).encode(), id="top-level-array"),
]


def _reachable_texts(root, depth=8):
    """Every rendering of every object reachable from `root`: exception messages and
    args, instance attributes (`vars`), the payloads decode/parse errors hide outside
    `vars` (`.object`, `.doc`), anything chained on `__cause__`/`__context__`, and the
    contents of containers -- recursively, so an exception kept as an attribute of the
    error is searched as deeply as the error itself."""
    # `alive` pins every visited object: `vars()` and friends build temporaries, and a
    # freed temporary's id can be reused, which would make `seen` skip a real object.
    seen, alive, out = set(), [], []

    def walk(obj, left):
        if obj is None or left < 0 or id(obj) in seen:
            return
        seen.add(id(obj))
        alive.append(obj)
        if isinstance(obj, BaseException):
            out.extend((str(obj), repr(obj)))
            walk(obj.args, left - 1)
            walk(vars(obj), left - 1)
            for attr in ("object", "doc"):
                walk(getattr(obj, attr, None), left - 1)
            walk(obj.__cause__, left - 1)
            walk(obj.__context__, left - 1)
        elif isinstance(obj, dict):
            for key, value in obj.items():
                walk(key, left - 1)
                walk(value, left - 1)
        elif isinstance(obj, (list, tuple, set, frozenset)):
            for value in obj:
                walk(value, left - 1)
        else:
            out.append(repr(obj))

    walk(root, depth)
    return out


@pytest.mark.parametrize("payload", _DAMAGED)
@pytest.mark.parametrize("op", ["put", "delete"])
def test_error_text_never_carries_secret_material(tmp_path, op, payload):
    store = SecretStore(tmp_path / "secrets.json")
    store.path.write_bytes(payload)
    with pytest.raises(SecretStoreReadError) as caught:
        if op == "put":
            store.put("x", {"a": 1})
        else:
            store.delete("provider:openai")
    exc = caught.value
    assert not [t for t in _reachable_texts(exc) if _CANARY in t]
    # Nothing chained: raising inside an `except` block leaves the original on
    # `__context__` even with `from None`.
    assert exc.__cause__ is None and exc.__context__ is None
    # Nothing kept: only the path and a string reason, never an exception object.
    assert set(vars(exc)) == {"path", "detail"}
    assert isinstance(exc.detail, str)


def _is_store_frame(filename):
    """True for code in coworker/secrets.py. Only the store's own frames are checked:
    the test's frames legitimately hold the payload it planted."""
    norm = lambda p: os.path.normcase(os.path.abspath(p))  # noqa: E731
    return norm(filename) == norm(secrets_module.__file__)


@pytest.mark.parametrize("payload", _DAMAGED)
@pytest.mark.parametrize("op", ["put", "delete"])
def test_no_store_frame_keeps_the_plaintext(tmp_path, op, payload):
    """A raised error drags every frame it left through along on `__traceback__`,
    locals and all -- which a debugger, a crash reporter, or plain
    `TracebackException(capture_locals=True)` will read. By the time the store raises,
    none of its frames may still hold the file it could not use."""
    store = SecretStore(tmp_path / "secrets.json")
    store.path.write_bytes(payload)
    with pytest.raises(SecretStoreReadError) as caught:
        if op == "put":
            store.put("x", {"a": 1})
        else:
            store.delete("provider:openai")
    exc = caught.value

    checked = []
    tb = exc.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        if _is_store_frame(frame.f_code.co_filename):
            checked.append(frame.f_code.co_name)
            for name, value in frame.f_locals.items():
                held = [t for t in _reachable_texts(value) if _CANARY in t]
                assert not held, f"{frame.f_code.co_name}() still holds the file in {name!r}"
        tb = tb.tb_next
    # Guard against a vacuous pass: the filter must actually have matched our frames.
    assert {op, "_read"} <= set(checked), checked

    # The stock exit that renders those locals must come out clean too.
    rendered = traceback.TracebackException.from_exception(exc, capture_locals=True)
    ours = [fs for fs in rendered.stack if _is_store_frame(fs.filename)]
    assert ours
    for fs in ours:
        assert not [v for v in (fs.locals or {}).values() if _CANARY in v], fs.name


@pytest.mark.parametrize("payload", _DAMAGED)
def test_degraded_reads_never_log_secret_material(tmp_path, caplog, payload):
    store = SecretStore(tmp_path / "secrets.json")
    store.path.write_bytes(payload)
    with caplog.at_level(logging.DEBUG, logger="coworker.secrets"):
        assert store.get("provider:openai") is None
        assert store.status() == []
    assert caplog.records  # the degradation was logged at all...
    for record in caplog.records:  # ...and nothing it logged carries the file
        assert not [t for t in _reachable_texts((record.getMessage(), record.args)) if _CANARY in t]


def test_unreadable_dotenv_does_not_break_a_lookup(tmp_path, monkeypatch):
    """`_load_dotenv` sits underneath `get`, which promises not to raise."""
    store = SecretStore(tmp_path / "secrets.json")
    store.put("docs:default", {"token": "${DOCS_TOKEN}"})
    (tmp_path / ".env").write_bytes('DOCS_TOKEN="\u5bc6\u94a5"'.encode("gbk"))
    assert store.get("docs:default")["token"] == "${DOCS_TOKEN}"  # ref left intact
    _unreadable(monkeypatch, tmp_path / ".env", OSError(13, "Permission denied"))
    assert store.get("docs:default")["token"] == "${DOCS_TOKEN}"
