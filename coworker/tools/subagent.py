"""The `explore` tool — a read-only research subagent with its own context window.

Broad questions ("where is retry logic handled?") burn the main session's context on
dozens of file reads. `explore` spawns a child TurnEngine over the same workspace with
read-only tools and a fresh context; only its final report returns to the caller.

The child runs in plan mode — the PermissionEngine hard-blocks writes/shell no matter
what the child decides — with no approver, so it never needs an approval round-trip.
That's what lets `explore` carry low-risk metadata, which in turn makes several explores
in one assistant turn eligible for the engine's parallel execution. No recursion: the
child registry has no `explore` tool.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional, TypeVar

import aisuite as ai

from ..engine import TurnEngine
from ..events import EventType
from ..permissions import Mode, PermissionEngine
from ..tools import ToolRegistry
from .files import file_tools
from .git import git_tools
from .search import search_tools

EXPLORER_INSTRUCTIONS = """You are a read-only code explorer working inside the user's workspace. \
Answer the research task you're given by searching and reading the code (`grep`, `read_file`, \
`list_files`, `git_log`, `git_status`, `git_diff`). You cannot write files or run commands.

Your final message is your report — it goes back to the agent that spawned you, not to the \
user. Make it self-contained: answer the task directly, reference code as path:line, quote the \
key snippets, and note anything surprising you found along the way. If you couldn't find \
something, say what you searched so the caller doesn't repeat the same searches."""

_CHILD_MAX_ITERATIONS = 10

_T = TypeVar("_T")


def _run_without_joining_executor(main: Coroutine[Any, Any, _T]) -> _T:
    """`asyncio.run`, minus its wait for the loop's executor threads on the way out.

    `asyncio.run` ends by joining the loop's default executor for up to
    `asyncio.constants.THREAD_JOIN_TIMEOUT` — 300 seconds on Python 3.13. The child
    engine's stream producer runs in that executor (`TurnEngine._astream`), and after a
    Stop it is typically still inside a provider read that nothing can interrupt. The
    child's turn was over in milliseconds, yet `explore` — and with it the parent's tool
    call and the parent's whole turn — sat waiting for that read to come back, which for
    a stalled stream can be as late as the SDK's own read timeout.

    Nothing the child's turn needs is left in that thread by then: once the read returns,
    the producer drops what it would have delivered to the closed loop, lets go of the
    provider's stream and ends — see `deliver` in `_astream`. (The SDK's HTTP response is
    closed when the garbage collector reclaims the SDK's stream object, exactly as after
    any Stop; nothing here changes that.)
    So everything else is done the way `asyncio.run` does it — a fresh loop, set as this
    thread's loop while it runs, leftover tasks cancelled, async generators finalised —
    and the executor is shut down without waiting, which is what `loop.close()` does.

    The abandoned thread is still an ordinary executor worker: it ends when its read
    returns, and a normal interpreter exit before that waits for it (`concurrent.futures`
    joins its workers at exit). The desktop sidecar never exits that way — the shell kills
    it and the orphan watchdog uses `os._exit` (server/run.py) — and the session's own
    stream producers, on the server's loop, were always joined the same way.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # no loop in this thread: the only way this is ever meant to be called
    else:
        main.close()  # never started; closing it spares the "never awaited" warning
        raise RuntimeError("the explorer cannot run inside a running event loop")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(main)
    finally:
        try:
            _cancel_leftover_tasks(loop)
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


def _cancel_leftover_tasks(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel whatever `main` left running and wait them out, as `asyncio.run` does."""
    leftover = asyncio.all_tasks(loop)
    if not leftover:
        return
    for task in leftover:
        task.cancel()
    loop.run_until_complete(asyncio.gather(*leftover, return_exceptions=True))
    for task in leftover:
        if not task.cancelled() and task.exception() is not None:
            loop.call_exception_handler(
                {
                    "message": "unhandled exception while closing the explorer's loop",
                    "exception": task.exception(),
                    "task": task,
                }
            )


def build_explorer_engine(
    *,
    workspace: str | Path,
    provider: Any,
    model: str,
    model_settings: Optional[dict[str, Any]] = None,
    max_iterations: int = _CHILD_MAX_ITERATIONS,
) -> TurnEngine:
    """A child engine with the Code agent's read-only tools and a fresh context."""
    ws = str(Path(workspace).resolve())
    registry = ToolRegistry()
    # Read-only slice of the Code agent's toolset, with the same toolkit replacements
    # (our grep for search_files, our windowed read_file for read_file/read_file_lines).
    replaced = {"search_files", "read_file", "read_file_lines"}
    registry.register_all(
        [
            t
            for t in ai.toolkits.files(root=ws)  # no allow_write → list/read only
            if getattr(t, "__name__", "") not in replaced
        ]
    )
    registry.register_all(file_tools(ws))
    registry.register_all(ai.toolkits.git(root=ws))  # git_status, git_diff
    registry.register_all(git_tools(ws))  # git_log
    registry.register_all(search_tools(ws))  # grep
    permissions = PermissionEngine(workspace_root=Path(ws), mode=Mode.PLAN)
    return TurnEngine(
        provider=provider,
        registry=registry,
        permissions=permissions,
        model=model,
        instructions=EXPLORER_INSTRUCTIONS,
        max_iterations=max_iterations,
        model_settings=model_settings,
    )


def explorer_tools(
    *,
    workspace: str | Path,
    provider: Any,
    model: str,
    model_settings: Optional[dict[str, Any]] = None,
    register_stop_hook: Optional[
        Callable[[Callable[[], None]], Callable[[], None]]
    ] = None,
) -> list:
    """`register_stop_hook` attaches a callable to whatever can stop THIS tool — the
    parent engine — and returns the callable that detaches it again
    (`TurnEngine.add_interrupt_hook` is exactly that shape). Without it the explorer runs
    to its own end no matter what the user presses; the parent wires it in agent.py."""

    def explore(task: str) -> dict:
        """Delegate a broad, read-only research task to a subagent with its own fresh
        context window. It searches and reads the workspace, then returns only its final
        report — the intermediate file reads never touch your context. Use it for
        multi-file questions ("where is X handled?", "how does the Y flow work?"); for a
        single known file, just read it yourself. Independent explore calls run in
        parallel when requested together. State the task precisely and say what the
        report should include.

        Args:
            task (str): The research question, with any constraints and the expected
                shape of the report.
        """
        engine = build_explorer_engine(
            workspace=workspace,
            provider=provider,
            model=model,
            model_settings=model_settings,
        )
        # Per CALL, never in the enclosing closure: several explores run at once when the
        # model asks for them together, each with its own child engine to stop.
        detach: list[Callable[[], None]] = []

        def _relay_stop() -> None:
            """Put this child engine on the receiving end of the parent's Stop.

            Attached on the child's FIRST event, not before its loop starts: `run()` clears
            the stop flag as its first act, so a hook attached any earlier would have the
            Stop it relayed wiped and the explorer would finish as if nobody had pressed
            it. The other side of that window — the Stop landing between the dispatch and
            this line — is closed by `add_interrupt_hook`, which fires the hook on the
            spot when a Stop is already pending.
            """
            if register_stop_hook is not None and not detach:
                detach.append(register_stop_hook(engine.request_interrupt))

        async def _run() -> tuple[str, str]:
            report, status = "", "unknown"
            async for event in engine.run(task):
                _relay_stop()
                if event.type == EventType.ASSISTANT_MESSAGE and event.data.get("text"):
                    report = event.data["text"]
                elif event.type == EventType.TURN_END:
                    status = event.data.get("status", "unknown")
                elif event.type == EventType.INTERRUPTED:
                    status = "interrupted"
                elif event.type == EventType.ERROR:
                    return report, f"error: {event.data.get('error', '')}"
            return report, status

        # Tools execute in a worker thread (no running loop), so this thread can run a
        # loop of its own — one that does not wait on a producer a Stop has abandoned.
        try:
            report, status = _run_without_joining_executor(_run())
        finally:
            # Whatever the exit — stopped, finished, blown up — the hook goes: it holds
            # this child engine, and with it a whole conversation history, alive on the
            # parent for as long as the session lasts.
            for remove in detach:
                remove()
        if not report:
            return {"error": f"explorer produced no report (status: {status})"}
        result: dict[str, Any] = {"report": report}
        if status != "completed":
            result["note"] = (
                f"explorer stopped early ({status}); the report may be partial"
            )
        return result

    return [
        ai.tool(
            explore,
            metadata=ai.ToolMetadata(
                category="search",
                risk_level="low",
                capabilities=["search"],
                requires_approval=False,
            ),
        )
    ]
