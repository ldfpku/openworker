"""Prompt-caching breakpoints on the Anthropic provider (OPE-42 follow-up).

The provider opts every request into 1h ephemeral caching: one breakpoint on the last
tool definition, one on the last system block (tools + system), and one on the final
message's last content block (conversation prefix) — skipping the engine's per-turn
`<system-context>` tail, which changes every turn and would never be worth caching.
"""

from __future__ import annotations

from coworker.providers.anthropic_provider import _CACHE_TTL, AnthropicProvider
from coworker.providers.base import SYSTEM_CONTEXT_OPEN

MARKER = {"type": "ephemeral", "ttl": _CACHE_TTL}


def _kwargs(messages, tools=None):
    return AnthropicProvider(client=object())._request_kwargs(
        model="claude-haiku-4-5", messages=messages, tools=tools, settings={}
    )


def test_ttl_is_1h_on_every_marker():
    assert _CACHE_TTL == "1h"
    kwargs = _kwargs(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ],
        tools=[
            {"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}
        ],
    )
    assert kwargs["system"][-1]["cache_control"]["ttl"] == "1h"
    assert kwargs["tools"][-1]["cache_control"]["ttl"] == "1h"
    assert kwargs["messages"][-1]["content"][-1]["cache_control"]["ttl"] == "1h"


def test_system_becomes_cached_block_list():
    kwargs = _kwargs(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ]
    )
    assert kwargs["system"] == [
        {"type": "text", "text": "be terse", "cache_control": MARKER}
    ]


def test_last_tool_carries_breakpoint():
    kwargs = _kwargs(
        [{"role": "user", "content": "hi"}],
        tools=[
            {"type": "function", "function": {"name": "a", "parameters": {"type": "object"}}},
            {"type": "function", "function": {"name": "b", "parameters": {"type": "object"}}},
        ],
    )
    tools = kwargs["tools"]
    assert tools[-1]["cache_control"] == MARKER
    assert "cache_control" not in tools[0]


def test_no_tools_is_fine():
    kwargs = _kwargs([{"role": "user", "content": "hi"}])
    assert "tools" not in kwargs


def test_last_message_last_block_carries_breakpoint():
    kwargs = _kwargs(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
    )
    messages = kwargs["messages"]
    assert messages[-1]["content"][-1]["cache_control"] == MARKER
    # Only the FINAL message is marked — earlier turns stay unmarked so the
    # prefix bytes match the previous request's cache.
    for message in messages[:-1]:
        assert all("cache_control" not in b for b in message["content"])


def test_tool_result_last_block_carries_breakpoint():
    kwargs = _kwargs(
        [
            {"role": "user", "content": "run it"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "t1",
                        "type": "function",
                        "function": {"name": "ls", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "t1", "content": "README.md"},
        ]
    )
    last = kwargs["messages"][-1]["content"][-1]
    assert last["type"] == "tool_result"
    assert last["cache_control"] == MARKER


def test_persisted_history_is_never_mutated():
    history = [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
    ]
    _kwargs(history)
    assert history == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
    ]


def test_no_system_prompt_is_fine():
    kwargs = _kwargs([{"role": "user", "content": "hi"}])
    assert "system" not in kwargs
    assert kwargs["messages"][-1]["content"][-1]["cache_control"] == MARKER


def test_system_context_tail_is_skipped_message_before_it_is_marked():
    # The engine appends the per-turn <system-context> block as its OWN trailing user
    # message (live clock — changes every turn). It must not be marked; the message
    # underneath it — the actual conversation prefix — gets the breakpoint instead.
    kwargs = _kwargs(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": f"{SYSTEM_CONTEXT_OPEN}\ntime: 12:00\n</system-context>"},
        ]
    )
    messages = kwargs["messages"]
    tail = messages[-1]
    marked = messages[-2]
    assert all("cache_control" not in b for b in tail["content"])
    assert marked["content"][-1]["cache_control"] == MARKER


def test_system_context_tail_as_list_content_is_skipped():
    # Preceding role is "assistant" (not "user") so convert_messages's same-role
    # folding doesn't merge the tail into it — keeps the tail its own message.
    kwargs = _kwargs(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{SYSTEM_CONTEXT_OPEN}\ntime: 12:00\n</system-context>"}
                ],
            },
        ]
    )
    messages = kwargs["messages"]
    assert all("cache_control" not in b for b in messages[-1]["content"])
    assert messages[-2]["content"][-1]["cache_control"] == MARKER


def test_tail_after_real_user_message_is_not_folded_and_still_skipped():
    # THE common turn-end shape: the engine appends the tail right after the user's own
    # message, so convert_messages sees two consecutive user-role entries. The fold
    # must exempt the tail (folding it in would change the real user message's bytes
    # every turn and put the breakpoint on a prefix that never recurs).
    kwargs = _kwargs(
        [
            {"role": "user", "content": "do the thing"},
            {"role": "user", "content": f"{SYSTEM_CONTEXT_OPEN}\ntime: 12:00\n</system-context>"},
        ]
    )
    messages = kwargs["messages"]
    assert len(messages) == 2  # tail kept as its own entry, not folded
    assert messages[0]["content"][0]["text"] == "do the thing"
    assert messages[0]["content"][-1]["cache_control"] == MARKER
    assert all("cache_control" not in b for b in messages[-1]["content"])


def test_tail_after_tool_results_stays_separate_and_results_are_marked():
    # Mid-tool-loop shape: tool results (converted to a user message) + tail. The tail
    # stays its own entry; the breakpoint lands on the tool-result message so the next
    # iteration re-reads this iteration's results from cache.
    kwargs = _kwargs(
        [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "t1", "function": {"name": "read_file", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "t1", "content": "README.md"},
            {"role": "user", "content": f"{SYSTEM_CONTEXT_OPEN}\ntime: 12:01\n</system-context>"},
        ]
    )
    messages = kwargs["messages"]
    results = messages[-2]
    assert results["role"] == "user"
    assert results["content"][0]["type"] == "tool_result"
    assert results["content"][-1]["cache_control"] == MARKER
    assert all("cache_control" not in b for b in messages[-1]["content"])


def test_all_messages_are_system_context_tail_marks_nothing():
    # Degenerate case: no non-tail message exists to mark — must not raise.
    from coworker.providers.anthropic_provider import _add_cache_breakpoints

    kwargs = {
        "messages": [
            {"role": "user", "content": f"{SYSTEM_CONTEXT_OPEN}\ntime: 12:00\n</system-context>"}
        ]
    }
    _add_cache_breakpoints(kwargs)
    assert kwargs["messages"][0]["content"] == (
        f"{SYSTEM_CONTEXT_OPEN}\ntime: 12:00\n</system-context>"
    )


def test_string_content_final_message_is_rewrapped_and_marked():
    # _add_cache_breakpoints is exercised directly here since convert_messages always
    # produces list content — this covers the helper's documented string-content branch
    # defensively, independent of what currently reaches it.
    from coworker.providers.anthropic_provider import _add_cache_breakpoints

    kwargs = {
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "first"}]},
            {"role": "user", "content": "plain string tail"},
        ]
    }
    _add_cache_breakpoints(kwargs)
    marked = kwargs["messages"][-1]
    assert marked["content"] == [
        {"type": "text", "text": "plain string tail", "cache_control": MARKER}
    ]


def test_fresh_marker_dict_per_breakpoint():
    kwargs = _kwargs(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ],
        tools=[
            {"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}
        ],
    )
    system_marker = kwargs["system"][-1]["cache_control"]
    tools_marker = kwargs["tools"][-1]["cache_control"]
    messages_marker = kwargs["messages"][-1]["content"][-1]["cache_control"]
    assert system_marker == tools_marker == messages_marker  # equal by value
    assert system_marker is not tools_marker  # but never the same object
    assert system_marker is not messages_marker
    assert tools_marker is not messages_marker
