"""The `request_directory` tool — the agent asks the user to grant access to a folder.

Unlike ordinary tools, this one is intercepted by the TurnEngine: it emits a DIRECTORY_REQUESTED
event and waits for the user to pick/approve a folder out-of-band (the GUI surfaces a prompt),
then the live session gains that root and the tool result tells the agent the outcome. The
callable here is only a schema carrier + a safe fallback for surfaces without a requester.
"""

from __future__ import annotations

from aisuite.agents import ToolMetadata, tool


def request_directory_tool() -> object:
    def request_directory(
        reason: str, path: str = "", writable: bool = False, primary: bool = False
    ) -> dict:
        # Trimmed 2026-08-31 for prompt cost. What survives is what changes behaviour:
        # when to reach for it, the `primary` constraint, and the sandbox line. The
        # blank line in the middle of the old text was a docstring accident that reached
        # the model verbatim.
        """Ask the user for access to a directory the task needs but doesn't have — a
        project they mentioned, or somewhere specific to save a deliverable. Say why in
        `reason`. Set `primary=true` only to make the granted folder the session's main
        workspace (the project the whole conversation is about): allowed once, and only
        while the session still runs on its scratch dir. The result says whether it was
        granted. Only ever to serve the user's request — never to reach past sandboxing.
        """
        # Real handling lives in the engine (it needs the out-of-band GUI round-trip). This body
        # only runs if no requester is wired (e.g. a headless surface).
        return {
            "granted": False,
            "error": "directory requests aren't available in this surface",
        }

    return tool(
        request_directory,
        metadata=ToolMetadata(
            category="filesystem",
            risk_level="low",
            capabilities=["request_directory"],
            description=(
                "Ask the user to grant access to a directory (read-only or read-write) when the "
                "task needs files outside the directories you already have."
            ),
        ),
    )
