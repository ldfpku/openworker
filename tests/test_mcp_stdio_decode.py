"""Regression test: a stdio MCP server's non-UTF-8 stdout must not kill the connection.

`mcp.client.stdio.StdioServerParameters` (the MCP SDK; installed as `mcp==1.29.0` in
this repo's `.venv`) defaults `encoding_error_handler` to `"strict"`. Its
`stdout_reader()` decodes the child process's stdout with
`TextReceiveStream(process.stdout, encoding=server.encoding,
errors=server.encoding_error_handler)` and does not catch `UnicodeDecodeError` — so a
single non-UTF-8 byte anywhere in that stream (a stray console-codepage log line from
the server or one of its own subprocesses, a mis-encoded string inside an otherwise
well-formed JSON-RPC message — routine on a zh-CN Windows box whose console codepage
is GBK/cp936) raises inside the SDK's `anyio` TaskGroup. That propagates out of
`stdio_client()` as an `ExceptionGroup` and lands in the broad
`except Exception as exc:` in `coworker/mcp/client.py::MCPManager._serve()`, whose
`finally` pops the connection out of `self._conns` / `self._tasks` — the whole
connection is torn down, taking every tool the server provided with it.

Reproduced 2026-09-22 against a fake stdio server driven through
`coworker.mcp.client.MCPManager` exactly as `coworker/server/manager.py` drives real
servers: BOTH forms below killed the very first `MCPManager.ensure()` call outright
(the fault landed in the same read chunk as the `tools/list` response in that repro,
so the connection never even became visible to the caller as briefly-alive).

  (a) a syntactically well-formed JSON-RPC notification whose string payload is raw
      GBK-encoded bytes instead of UTF-8 (`UnicodeDecodeError` while decoding what
      looks like a normal protocol message);
  (b) a stray line that is not JSON at all — raw GBK-encoded text, the kind of thing a
      subprocess prints to its own stdout by mistake.

Passing `encoding_error_handler="replace"` to `StdioServerParameters` (this test's
fix) keeps the connection alive in both cases: bad bytes become U+FFFD instead of
raising. For (b) the SDK's own `stdout_reader()` still logs "Failed to parse JSONRPC
message from server" for the un-parseable line (verified via caplog below) and reports
that failure to the pending caller via `read_stream_writer.send(exc)` — that is the
SDK's existing, separate handling of malformed-but-valid-UTF-8 input, not something
this fix changes; what changes is that the connection is no longer destroyed.
"""
from __future__ import annotations

import asyncio
import sys

import pytest

from coworker.mcp.client import MCPManager
from coworker.mcp.config import MCPServerDef

# Bounds for every await below: this repo's pytest has no configured timeout, and a
# stdio subprocess that never speaks the protocol would otherwise hang the suite.
_ENSURE_TIMEOUT = 20
_CALL_TIMEOUT = 20
_CLOSE_TIMEOUT = 10

# A tiny stdio MCP server, spawned as `sys.executable -c <script> <mode>` — no repo
# file needed (mirrors `_crash_cmd` in test_mcp.py, which uses the same trick for a
# cross-platform stand-in child process). Speaks just enough of the protocol to
# satisfy `ClientSession.initialize()` and one `tools/list` + `tools/call` round trip;
# right after answering `tools/list` it writes `mode`-dependent bytes to stdout:
#   a - a well-formed-looking JSON-RPC notification whose string value is raw
#       GBK-encoded bytes (not valid UTF-8).
#   b - a stray non-JSON line, raw GBK-encoded text.
_FAKE_SERVER_SCRIPT = r"""
import json, sys

mode = sys.argv[1]

def send_json(obj):
    sys.stdout.buffer.write(json.dumps(obj).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()

def send_raw(data):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()

while True:
    line = sys.stdin.buffer.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    req = json.loads(line.decode("utf-8"))
    method, req_id = req.get("method"), req.get("id")
    if method == "initialize":
        send_json({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        })
    elif method == "tools/list":
        send_json({"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}})
        if mode == "a":
            prefix = (
                b'{"jsonrpc": "2.0", "method": "notifications/message", '
                b'"params": {"level": "info", "logger": "child", "data": "'
            )
            gbk_bytes = "中文日志".encode("gbk")  # "中文日志"
            send_raw(prefix + gbk_bytes + b'"}}\n')
        elif mode == "b":
            send_raw("这是一条诊断日志\n".encode("gbk"))
    elif method == "tools/call":
        send_json({
            "jsonrpc": "2.0", "id": req_id,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        })
    elif method == "ping":
        send_json({"jsonrpc": "2.0", "id": req_id, "result": {}})
"""


def _fake_server(mode: str) -> MCPServerDef:
    return MCPServerDef(
        name="fake-noncompliant",
        transport="stdio",
        command=sys.executable,
        args=["-c", _FAKE_SERVER_SCRIPT, mode],
    )


@pytest.mark.parametrize("mode", ["a", "b"])
async def test_non_utf8_stdout_does_not_kill_the_connection(mode):
    """Before the fix (`encoding_error_handler` left at the SDK's "strict" default)
    this raises out of `ensure()` — see the module docstring for the exact traceback
    observed. After the fix the connection survives and a tool call still works."""
    mgr = MCPManager()
    server = _fake_server(mode)
    try:
        conn = await asyncio.wait_for(mgr.ensure(server), timeout=_ENSURE_TIMEOUT)
        assert conn.tools == []

        # The connection must still be usable after the fault: a fresh ensure() is
        # the SAME connection (not silently torn down + reconnected), and a tool
        # call round-trips normally.
        conn2 = await asyncio.wait_for(mgr.ensure(server), timeout=_ENSURE_TIMEOUT)
        assert conn2 is conn

        result = await asyncio.wait_for(
            mgr.call("fake-noncompliant", "noop", {}), timeout=_CALL_TIMEOUT
        )
        assert result == "ok"
    finally:
        await asyncio.wait_for(mgr.aclose(), timeout=_CLOSE_TIMEOUT)


async def test_non_json_line_is_logged_not_fatal(caplog):
    """Mode "b"'s stray line is not valid JSON even after replace-decoding (it
    decodes to Unicode replacement characters, still not a JSON-RPC message) — the
    SDK's own `stdout_reader()` logs that parse failure. This just confirms the
    fix doesn't hide it while also confirming it is non-fatal (no exception at all
    reaches this test, unlike the pre-fix `ensure()` crash)."""
    import logging

    mgr = MCPManager()
    server = _fake_server("b")
    try:
        with caplog.at_level(logging.ERROR, logger="mcp.client.stdio"):
            await asyncio.wait_for(mgr.ensure(server), timeout=_ENSURE_TIMEOUT)
            # Give the reader task a beat to process the fault line.
            await asyncio.sleep(1)
        assert any(
            "Failed to parse JSONRPC message" in r.message for r in caplog.records
        )
    finally:
        await asyncio.wait_for(mgr.aclose(), timeout=_CLOSE_TIMEOUT)
