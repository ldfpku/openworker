"""A failed read of the global `mcp.json` must never look like an empty config.

Every mutator in `coworker/mcp/config.py` is read-modify-write-the-WHOLE-file. `_read`
used to answer `{}` for `OSError` and `JSONDecodeError` alike, so one transient read
failure — file locked, volume error, an outside editor's half-written JSON, non-UTF-8
bytes — made `put_global_server` rewrite `mcp.json` from an empty base and delete EVERY
server the user had configured, silently and with nothing to recover from.

The split these tests pin down: "no file" is a legal empty config (the first add creates
it), while "cannot read the file" raises `MCPConfigError` and writes nothing at all. The
display-only readers (`list_mcp`, `load_mcp_servers`) still degrade rather than 500 the
Settings poll or fail session open — but they log, and they can no longer be the first
step of a wipe, because the mutators refuse.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path

import pytest

from coworker.mcp.config import (
    MCPConfigError,
    delete_global_server,
    global_mcp_path,
    load_mcp_servers,
    patch_global_server,
    put_global_server,
    read_global,
)
from coworker.secrets import SecretStore
from coworker.server.manager import SessionManager

TWO_SERVERS = {
    "sales-db": {"command": "sales", "args": ["--stdio"]},
    "docs": {"url": "https://docs.example/mcp", "auth": "oauth"},
}


def _seed_two_servers() -> Path:
    """The user's real config: two servers they would hate to lose."""
    path = global_mcp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": TWO_SERVERS}), encoding="utf-8")
    return path


def _write_global_raw(text: str) -> Path:
    path = global_mcp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_unreadable(monkeypatch, path: Path) -> None:
    """Make exactly `path` raise on read, leaving every other file alone.

    Scoped to one path on purpose: a blanket `Path.read_text` failure would take the
    SecretStore and half the manager with it and prove nothing about this code. Only
    `read_text` is patched, so the tests can still compare the file's bytes.
    """
    real = Path.read_text

    def boom(self, *args, **kwargs):
        if Path(self) == path:
            raise OSError(13, "the file is locked by another process")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", boom)


# -- the legal "empty" cases: absent, not unreadable ---------------------------
def test_a_missing_file_is_a_legal_empty_config():
    """No `mcp.json` yet is the first-run state, not a failure: the first add creates it."""
    assert not global_mcp_path().exists()
    assert read_global() == {}

    put_global_server("sales-db", {"command": "sales"})
    assert read_global() == {"sales-db": {"command": "sales"}}


def test_a_blank_file_is_treated_as_an_empty_config():
    """A zero-byte file holds no servers, so reading it as empty loses nothing — and
    refusing to write would wedge the user out of ever adding a server again."""
    _write_global_raw("   \n")
    assert read_global() == {}

    put_global_server("docs", {"url": "https://docs.example/mcp"})
    assert set(read_global()) == {"docs"}


def test_a_bom_prefixed_file_is_read_not_refused():
    """Windows PowerShell 5.1's `Set-Content`/`Out-File` write UTF-8 WITH a BOM, and
    `mcp.json` is a file people open and save by hand. A BOM is not damage: refusing
    it would lock the user out of every write for good over an invisible byte."""
    path = global_mcp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"mcpServers": TWO_SERVERS}).encode())

    assert read_global() == TWO_SERVERS
    put_global_server("notes", {"command": "notes"})
    assert set(read_global()) == {"sales-db", "docs", "notes"}
    # What we write back stays plain BOM-less UTF-8.
    assert path.read_bytes().startswith(b"{")


def test_an_all_nul_file_is_treated_as_an_empty_config():
    """All-NUL is what NTFS commonly leaves after power loss mid-write: the size was
    committed, the data never was. The real contents are already gone from this file,
    so — exactly like a zero-byte file — refusing would only wedge the user forever."""
    path = global_mcp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 4096)

    assert read_global() == {}
    put_global_server("notes", {"command": "notes"})
    assert read_global() == {"notes": {"command": "notes"}}


def test_nul_padding_after_real_json_is_still_refused():
    """The carve-out is for files with NOTHING in them. Real JSON trailed by NULs
    still holds the user's servers — overwriting it is exactly the loss this module
    exists to prevent, so it stays a refusal."""
    path = global_mcp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps({"mcpServers": TWO_SERVERS}).encode() + b"\x00" * 64)
    before = path.read_bytes()

    with pytest.raises(MCPConfigError):
        put_global_server("notes", {"command": "notes"})
    assert path.read_bytes() == before


def test_put_preserves_the_other_servers():
    """The plain read-modify-write guarantee, guarded so a later refactor can't quietly
    turn an add into a replace-everything."""
    _seed_two_servers()

    put_global_server("notes", {"command": "notes"})
    assert set(read_global()) == {"sales-db", "docs", "notes"}

    put_global_server("docs", {"url": "https://docs.example/v2"})
    after = read_global()
    assert set(after) == {"sales-db", "docs", "notes"}
    assert after["docs"] == {"url": "https://docs.example/v2"}
    assert after["sales-db"] == TWO_SERVERS["sales-db"]


# -- the read failures: refuse, never rewrite from an empty base ---------------
def test_put_refuses_to_write_when_the_read_errors(monkeypatch):
    """The original bug, with an IO error: `put_global_server` used to swallow it,
    read `{}`, and write a file holding only the new server."""
    path = _seed_two_servers()
    before = path.read_bytes()
    _make_unreadable(monkeypatch, path)

    with pytest.raises(MCPConfigError) as failure:
        put_global_server("notes", {"command": "notes"})

    assert failure.value.path == path
    assert failure.value.detail == "EACCES"
    assert path.read_bytes() == before, "the config on disk must be byte-for-byte intact"


def test_put_refuses_to_write_when_the_json_is_corrupt():
    """Same bug via the likelier trigger: something outside us left half a JSON object
    behind. The servers are still in those bytes — overwriting them is the only way to
    actually lose them."""
    path = _write_global_raw('{"mcpServers": {"sales-db": {"command"')
    before = path.read_bytes()

    with pytest.raises(MCPConfigError) as failure:
        put_global_server("notes", {"command": "notes"})

    assert failure.value.detail == "JSONDecodeError"
    assert path.read_bytes() == before, "the config on disk must be byte-for-byte intact"


def test_a_non_object_top_level_counts_as_unreadable():
    """Callers index the parsed result with `.get`, so a JSON list used to blow up as an
    AttributeError inside whichever caller reached it first."""
    path = _write_global_raw('["sales-db", "docs"]')
    before = path.read_bytes()

    with pytest.raises(MCPConfigError):
        read_global()
    with pytest.raises(MCPConfigError):
        put_global_server("notes", {"command": "notes"})
    assert path.read_bytes() == before


def test_non_utf8_bytes_count_as_unreadable():
    """A mojibake'd file (GBK-encoded on a Chinese Windows box, say) is not an empty one."""
    path = global_mcp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"mcpServers": {"\xd6\xd0\xce\xc4": {"command": "x"}}}')
    before = path.read_bytes()

    with pytest.raises(MCPConfigError):
        read_global()
    with pytest.raises(MCPConfigError):
        put_global_server("notes", {"command": "notes"})
    assert path.read_bytes() == before


def test_patch_and_delete_refuse_rather_than_reporting_absent():
    """`False` means "no such server". An unreadable file must not borrow that answer:
    it would tell the user their server is gone while it sits on disk untouched, and
    both of these rewrite the whole file too."""
    path = _write_global_raw('{"mcpServers": {"sales-db": {"command"')
    before = path.read_bytes()

    with pytest.raises(MCPConfigError):
        patch_global_server("sales-db", {"enabled": False})
    with pytest.raises(MCPConfigError):
        delete_global_server("sales-db")
    assert path.read_bytes() == before


def test_load_mcp_servers_degrades_on_an_unreadable_global_file(tmp_path):
    """The session-open hot path is the one place that still degrades: losing servers
    for a turn is recoverable, failing every session open is not. The trusted
    workspace file beside it still contributes."""
    _write_global_raw('{"mcpServers": {"sales-db": {"command"')
    ws = tmp_path / "ws"
    (ws / ".coworker").mkdir(parents=True)
    (ws / ".coworker" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"local": {"command": "local"}}}), encoding="utf-8"
    )

    names = {
        s.name
        for s in load_mcp_servers(
            ws, secrets=SecretStore(), workspace_trusted=True
        )
    }
    assert names == {"local"}


# -- the exception must not be a way back into the file -------------------------
# `mcp.json` can hold literal secrets (`env`/`headers` values, a token in a URL query).
_FAKE_SECRET = "sk-live-FAKE-do-not-leak-7f3a9c"


def _capture(fn, *args) -> MCPConfigError:
    """Call `fn` and hand back the MCPConfigError it raised. Its own frame holds no file
    contents, so anything the walk below finds really did come from the exception."""
    try:
        fn(*args)
    except MCPConfigError as exc:
        return exc
    raise AssertionError(f"{fn.__name__} did not raise MCPConfigError")


def _everything_reachable(exc: BaseException) -> list[str]:
    """Every rendering of `exc` a future log line could plausibly produce."""
    out = [repr(exc), str(exc), repr(exc.args), repr(vars(exc))]
    out += traceback.format_exception(exc)
    out += traceback.TracebackException.from_exception(exc, capture_locals=True).format()
    seen: BaseException | None = exc
    while seen is not None:  # the whole __cause__/__context__ chain, if any
        out.append(repr(seen))
        tb = seen.__traceback__
        while tb is not None:
            out += [repr(value) for value in tb.tb_frame.f_locals.values()]
            tb = tb.tb_next
        seen = seen.__cause__ or seen.__context__
    return out


@pytest.mark.parametrize(
    "raw",
    [
        # Half-written JSON: JSONDecodeError.doc is the whole document.
        ('{"mcpServers": {"api": {"env": {"TOKEN": "' + _FAKE_SECRET + '"}').encode(),
        # Valid JSON, but not UTF-8: UnicodeDecodeError.object is the whole byte string,
        # and its repr prints it.
        b'{"mcpServers": {"api": {"env": {"TOKEN": "'
        + _FAKE_SECRET.encode()
        + b'"}}, "\xd6\xd0": {}}}',
        # Parses, but the top level isn't an object: the parsed list holds the secret.
        ('["' + _FAKE_SECRET + '"]').encode(),
    ],
    ids=["corrupt-json", "not-utf8", "non-object"],
)
def test_the_exception_cannot_reach_the_file_contents(raw):
    """No attribute, no chained exception, no rendering and no traceback frame's locals
    may lead from the raised MCPConfigError back to what the file contains."""
    path = global_mcp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)

    for exc in (_capture(read_global), _capture(put_global_server, "notes", {"x": 1})):
        assert exc.__cause__ is None and exc.__context__ is None
        assert not hasattr(exc, "cause")
        leaks = [r for r in _everything_reachable(exc) if _FAKE_SECRET in r]
        assert leaks == [], f"file contents reachable from the exception: {leaks[:1]}"


# -- the manager surface: the failure reaches the caller ------------------------
def test_add_mcp_reports_the_read_failure_instead_of_wiping(tmp_path, monkeypatch):
    """The REST path the GUI's "Add server" button lands on. Before: `{"ok": true}` and
    two servers gone. Now: `ok: false` with a reason, and the file untouched."""
    manager = SessionManager(data_dir=tmp_path / "data")
    path = _seed_two_servers()
    before = path.read_bytes()
    _make_unreadable(monkeypatch, path)

    out = manager.add_mcp("notes", {"command": "notes"})
    assert out["ok"] is False
    assert out["name"] == "notes"
    # A stable machine code for the GUI to translate, and prose with NO absolute path:
    # `str(exc)` names the user's config file and belongs in the log, not on the wire.
    assert out["code"] == "config_unreadable"
    assert out["error"] and str(tmp_path) not in out["error"]
    assert path.read_bytes() == before


def test_patch_and_delete_mcp_report_the_read_failure(tmp_path, monkeypatch):
    manager = SessionManager(data_dir=tmp_path / "data")
    path = _seed_two_servers()
    before = path.read_bytes()
    _make_unreadable(monkeypatch, path)

    patched = manager.patch_mcp("sales-db", {"enabled": False})
    deleted = manager.delete_mcp("sales-db")
    assert patched["ok"] is False and patched["code"] == "config_unreadable"
    assert deleted["ok"] is False and deleted["code"] == "config_unreadable"
    assert str(tmp_path) not in patched["error"] + deleted["error"]
    assert path.read_bytes() == before


def test_the_refusal_sent_to_the_user_never_carries_the_file_path(tmp_path, monkeypatch):
    """`MCPConfigError` keeps the path for the log and hands the wire a code instead.

    The GUI shows `error` verbatim for any code it doesn't know, so this prose is
    user-facing copy — an absolute home-directory path has no business in it.
    """
    manager = SessionManager(data_dir=tmp_path / "data")
    path = _seed_two_servers()
    _make_unreadable(monkeypatch, path)

    out = manager.add_mcp("notes", {"command": "notes"})
    assert out["error"] == "the MCP server config file could not be read"
    assert str(path) not in out["error"] and "mcp.json" not in out["error"]

    # The diagnostic form still names the file — that is what the log line prints.
    with pytest.raises(MCPConfigError) as failure:
        read_global()
    assert str(path) in str(failure.value)
    assert failure.value.code == "config_unreadable"


def test_deleting_a_server_that_is_already_gone_succeeds(tmp_path):
    """Idempotent delete: the user wants it gone and it is. Reporting that as a failure
    put "Couldn't save that change." on the detail page and kept the user there."""
    manager = SessionManager(data_dir=tmp_path / "data")
    _seed_two_servers()

    first = manager.delete_mcp("sales-db")
    again = manager.delete_mcp("sales-db")
    never = manager.delete_mcp("never-was")

    assert first == {"ok": True, "name": "sales-db", "existed": True}
    assert again == {"ok": True, "name": "sales-db", "existed": False}
    assert never == {"ok": True, "name": "never-was", "existed": False}
    assert set(read_global()) == {"docs"}


def test_an_unreadable_config_is_not_mistaken_for_an_absent_server(tmp_path, monkeypatch):
    """The other side of idempotent delete: "can't read the file" must never be taken
    for "it isn't there" — the server may still be in the file, and removing one means
    rewriting the rest. Still refused, still says why."""
    manager = SessionManager(data_dir=tmp_path / "data")
    path = _seed_two_servers()
    before = path.read_bytes()
    _make_unreadable(monkeypatch, path)

    out = manager.delete_mcp("sales-db")
    assert out["ok"] is False and out["code"] == "config_unreadable"
    assert "existed" not in out
    assert path.read_bytes() == before


def test_list_mcp_degrades_instead_of_raising(tmp_path, monkeypatch):
    """Display-only, polled every few seconds by the GUI: it must not become a 500 loop.
    An empty tab here is no longer a step towards losing anything, because every
    mutator refuses to write while the file is unreadable."""
    manager = SessionManager(data_dir=tmp_path / "data")
    path = _seed_two_servers()
    _make_unreadable(monkeypatch, path)

    assert manager.list_mcp() == []


def test_begin_mcp_connect_flags_nothing_on_an_unreadable_config(tmp_path, monkeypatch):
    """A name flagged `authorizing` with no server behind it is the stuck-spinner bug
    this method exists to prevent — an unreadable config must not reintroduce it."""
    manager = SessionManager(data_dir=tmp_path / "data")
    path = _seed_two_servers()
    _make_unreadable(monkeypatch, path)

    manager.begin_mcp_connect("sales-db")
    assert manager._mcp_authorizing == set()


def test_connect_after_an_unreadable_config_leaves_no_flag_and_no_error(
    tmp_path, monkeypatch
):
    """Pins what `begin_mcp_connect`'s comment says happens next, so the two can't drift
    apart again. The flag is never left set; the connect answers "unknown MCP server";
    and `_mcp_errors` stays EMPTY — a known gap (nothing from this path reaches the UI).
    Whoever closes that gap updates this test and that comment together."""
    manager = SessionManager(data_dir=tmp_path / "data")
    path = _seed_two_servers()
    _make_unreadable(monkeypatch, path)

    manager.begin_mcp_connect("sales-db")
    out = asyncio.run(manager.connect_mcp("sales-db"))

    assert manager._mcp_authorizing == set()
    assert out == {"ok": False, "error": "unknown MCP server: sales-db"}
    assert manager._mcp_errors == {}


def test_mcp_connect_connector_reports_a_read_failure_and_writes_nothing(
    tmp_path, monkeypatch
):
    """The connector one-click snapshots the previous entry before seeding its own. With
    the old swallow, the snapshot came back `None` (as if nothing were configured), the
    seed then rewrote `mcp.json` down to just this connector, and a later rollback
    deleted even that — an empty file from one read error."""
    manager = SessionManager(data_dir=tmp_path / "data")
    path = _seed_two_servers()
    before = path.read_bytes()

    async def never(name):  # pragma: no cover - asserted not to run
        raise AssertionError("connect_mcp must not run once the read has failed")

    monkeypatch.setattr(manager, "connect_mcp", never)
    _make_unreadable(monkeypatch, path)

    out = asyncio.run(manager.mcp_connect_connector("monday"))
    assert out["ok"] is False
    assert out["code"] == "config_unreadable"
    assert str(tmp_path) not in out["error"]
    assert path.read_bytes() == before
