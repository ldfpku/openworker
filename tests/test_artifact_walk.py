"""What the Artifacts panel walks, and what it credits this session with producing.

Part 1 — list_artifacts must never descend into OS application-data directories. On
macOS 14+, merely traversing ~/Library/Application Support (other apps' containers) trips
the App Data TCC protection and the user gets an alarming "OpenWorker would like to access
data from other apps" prompt. The artifacts panel refreshes after every turn, so a
home-directory workspace produced that prompt unprompted. Pruning must happen DURING the
walk (rglob descends first and filters after, which is what caused the bug).

Part 2 — the panel scanned ONLY scratch, while relative paths and `run_shell` both resolve
to the WORKSPACE. A session could therefore write the user's report, say it was done, and
show an empty panel. The session's own conversation says what it made: the write tools name
their path outright, and a `run_shell` call contributes a time window swept for documents.
"""

import json
import os
import time

import pytest

from coworker.server.manager import SessionManager
from coworker.tools.search import OS_DATA_DIRS


def _ws(tmp_path):
    ws = tmp_path / "home"
    (ws / "Library" / "Application Support" / "SomeOtherApp").mkdir(parents=True)
    (ws / "Library" / "Application Support" / "SomeOtherApp" / "secrets.json").write_text("{}")
    (ws / "Library" / "notes.md").write_text("# private")
    (ws / "node_modules" / "pkg").mkdir(parents=True)
    (ws / "node_modules" / "pkg" / "readme.md").write_text("# dep")
    (ws / "report.md").write_text("# real artifact")
    return ws


def test_os_data_dirs_are_not_traversed(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    walked: list[str] = []
    real_walk = os.walk

    def spy(top, *a, **k):
        for dirpath, dirs, files in real_walk(top, *a, **k):
            walked.append(dirpath)
            yield dirpath, dirs, files

    monkeypatch.setattr("coworker.server.manager.os.walk", spy)
    m = SessionManager(data_dir=tmp_path / "data", workspace=str(ws))
    names = [a["name"] for a in m.list_artifacts("s1")]

    assert "report.md" in names
    # The private file is skipped AND its directory was never entered (the TCC trigger).
    assert "notes.md" not in names
    assert "secrets.json" not in names
    assert not any("Library" in p for p in walked), f"descended into Library: {walked}"
    assert not any("node_modules" in p for p in walked)


def test_os_data_dirs_cover_mac_and_windows():
    assert {"Library", "AppData", "Application Data"} <= OS_DATA_DIRS


# -- what this session produced outside scratch ---------------------------------
# The workspace dir name deliberately carries Chinese characters, a space and parentheses:
# every path in this feature travels through JSON, a URL query and Path.as_posix(), and
# that is the name a Windows user's folder actually has.


def _manager(tmp_path):
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient

    class _Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **s):  # pragma: no cover
            return AssistantTurn(text="", finish_reason="stop")

        def capabilities(self, model):  # pragma: no cover
            return ModelCapabilities()

    mgr = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    mgr._prefs["scratch_base"] = str(tmp_path / "scratchbase")
    return mgr


def _gated(tmp_path, sid="sessArt1"):
    """A manager + a workspace-plus-scratch session with a live engine, as after a folder pick."""
    mgr = _manager(tmp_path)
    ws = tmp_path / "新建文件夹 (8)"
    ws.mkdir()
    engine = mgr.get_engine(sid, agent="code", workspace=str(ws))
    assert engine is not None
    return mgr, ws, engine


def _ask(engine, call_id, name, arguments, *, asked=None):
    """The assistant message a real turn appends BEFORE authorization (engine.py appends it,
    and `permission_required` checkpoints it, while the approval card is still open)."""
    engine.messages.append(
        {
            "role": "assistant",
            "content": "",
            "ts": time.time() if asked is None else asked,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        }
    )


def _answer(engine, call_id, result, *, t0=None, finished=None, legacy=False):
    """The tool result `engine._record_result` appends once the call has actually run:
    `t0` = when execution began, `ts` = when it finished. `legacy=True` omits `t0`, as
    every record written before that sidecar existed does."""
    message = {
        "role": "tool",
        "tool_call_id": call_id,
        "content": result if isinstance(result, str) else json.dumps(result),
        "ts": time.time() if finished is None else finished,
    }
    if not legacy:
        message["t0"] = t0 if t0 is not None else message["ts"]
    engine.messages.append(message)


def _record_call(engine, call_id, name, arguments, result, *, started=None, finished=None):
    """A complete call: asked, then run and answered."""
    _ask(engine, call_id, name, arguments, asked=started)
    _answer(engine, call_id, result, t0=started, finished=finished)


def _by_name(artifacts):
    return {a["name"]: a for a in artifacts}


def test_relative_write_lands_in_the_workspace_and_is_listed_and_openable(tmp_path):
    """The reported bug, end to end: the model writes `报告.csv` with a relative path, the
    file lands in the workspace, and the panel must show it — openable by the `path` the
    panel itself handed out."""
    mgr, ws, engine = _gated(tmp_path)
    sid = "sessArt1"
    args = {"path": "报告.csv", "content": "名称,数量\n甲,1\n"}
    result = engine.registry.execute("write_file", args)
    _record_call(engine, "c1", "write_file", args, result)
    mgr.save(sid, engine)

    assert (ws / "报告.csv").exists()
    entry = _by_name(mgr.list_artifacts(sid))["报告.csv"]
    assert entry["root"] == "workspace"
    assert entry["path"] == (ws.resolve() / "报告.csv").as_posix()
    assert "/" in entry["path"] and "\\" not in entry["path"]

    # Both viewer routes resolve that exact `path` — read, and reveal's target lookup.
    assert mgr.read_artifact(sid, entry["path"])["ok"] is True
    target, err = mgr._artifact_target(sid, entry["path"], allow_dir=True)
    assert err is None and target == (ws.resolve() / "报告.csv")


def test_a_write_mid_turn_is_listed_before_anything_is_persisted(tmp_path):
    """The panel refreshes the instant a write tool finishes, and the .jsonl is only
    appended at a checkpoint (`iteration_end`) — so mid-turn the file is an iteration
    behind. The live engine's messages are what must be read."""
    mgr, ws, engine = _gated(tmp_path, "sessArtLive")
    sid = "sessArtLive"
    args = {"path": "进行中.md", "content": "# wip\n"}
    _record_call(engine, "c1", "write_file", args, engine.registry.execute("write_file", args))

    assert mgr.session_store.load(sid) is None  # nothing has been checkpointed yet
    assert "进行中.md" in _by_name(mgr.list_artifacts(sid))


def test_shell_written_file_is_credited_to_the_call_that_was_running(tmp_path):
    """`run_shell` names no output path — a script writes what it writes — so the call's
    time window is what credits the file. A workspace file whose mtime sits outside every
    window is the user's own and must stay out of the panel."""
    mgr, ws, engine = _gated(tmp_path, "sessArt2")
    sid = "sessArt2"
    stale = ws / "旧报告.md"
    stale.write_text("# 上周的", encoding="utf-8")
    os.utime(stale, (time.time() - 3600, time.time() - 3600))

    started = time.time()
    produced = ws / "测试报告_标准模版.xlsx"
    produced.write_bytes(b"PK\x03\x04 stand-in for a real workbook")
    _record_call(
        engine,
        "c1",
        "run_shell",
        {"command": "python 生成报表.py"},
        "ok",
        started=started,
        finished=time.time(),
    )
    mgr.save(sid, engine)

    names = _by_name(mgr.list_artifacts(sid))
    assert "测试报告_标准模版.xlsx" in names
    assert names["测试报告_标准模版.xlsx"]["root"] == "workspace"
    assert "旧报告.md" not in names


def test_source_files_written_into_the_workspace_are_not_artifacts(tmp_path):
    """A non-scratch root is the user's own project. Crediting the session with every `.py`
    it touched would turn the panel back into a file browser."""
    mgr, ws, engine = _gated(tmp_path, "sessArt3")
    sid = "sessArt3"
    for i, (path, content) in enumerate(
        [("生成报表.py", "print('x')\n"), ("说明.md", "# 说明\n")]
    ):
        args = {"path": path, "content": content}
        _record_call(engine, f"c{i}", "write_file", args, engine.registry.execute("write_file", args))
    mgr.save(sid, engine)

    names = _by_name(mgr.list_artifacts(sid))
    assert "说明.md" in names
    assert "生成报表.py" not in names


def test_a_dangling_shell_call_never_opens_an_endless_window(tmp_path):
    """The assistant message is appended and CHECKPOINTED before authorization, so a user
    who quits at a `run_shell` approval card leaves a call with no result in the .jsonl
    forever. Treating that as "still running" would make every later refresh — days later,
    from a cold start — claim everything they have since touched in their own workspace."""
    mgr, ws, engine = _gated(tmp_path, "sessArtDangle")
    sid = "sessArtDangle"
    _ask(engine, "c1", "run_shell", {"command": "python 生成.py"})  # card still open
    mgr.save(sid, engine)  # what the permission_required checkpoint persists

    # …the user then works in their own folder, long after the session was abandoned.
    (ws / "我的私人笔记.md").write_text("# mine", encoding="utf-8")

    assert _by_name(mgr.list_artifacts(sid)) == {}  # live engine
    assert _by_name(_manager(tmp_path).list_artifacts(sid)) == {}  # cold, from the jsonl


def test_the_window_excludes_the_time_spent_at_the_approval_card(tmp_path):
    """`ts` on the assistant message is when the model ASKED; `t0` on the result is when the
    command actually started. Everything in between is the human deciding — and the files
    they touch while deciding are theirs."""
    mgr, ws, engine = _gated(tmp_path, "sessArtWait")
    sid = "sessArtWait"

    now = time.time()
    asked, t0 = now - 60, now - 1  # a minute at the card, then the command runs
    theirs = ws / "用户在审批时改的.md"
    theirs.write_text("# theirs", encoding="utf-8")
    os.utime(theirs, (now - 50, now - 50))  # saved while the card was open
    (ws / "命令写出的.md").write_text("# ours", encoding="utf-8")
    _ask(engine, "c1", "run_shell", {"command": "python 生成.py"}, asked=asked)
    _answer(engine, "c1", "ok", t0=t0, finished=now)
    mgr.save(sid, engine)

    names = _by_name(mgr.list_artifacts(sid))
    assert "命令写出的.md" in names
    assert "用户在审批时改的.md" not in names

    # …and `t0` is what excludes it: drop the sidecar and the fallback window, which can
    # only bound itself by the shell's own timeout, reaches back over the whole wait.
    engine.messages[-1].pop("t0")
    assert "用户在审批时改的.md" in _by_name(mgr.list_artifacts(sid))


def test_a_record_without_t0_falls_back_to_the_shell_timeout(tmp_path):
    """Sessions written before `t0` existed still have to work. `run_shell` cannot outlive
    its own maximum timeout, so anything older than that is provably not the call's doing —
    that bound is the fallback window, not "since the model asked"."""
    from coworker.tools.shell import _MAX_TIMEOUT

    mgr, ws, engine = _gated(tmp_path, "sessArtLegacy")
    sid = "sessArtLegacy"
    now = time.time()
    # The model asked long enough ago that only the timeout bounds the fallback window.
    asked = now - _MAX_TIMEOUT * 3
    inside = ws / "命令写出的.md"
    inside.write_text("# ours", encoding="utf-8")
    outside = ws / "超时之前就在的.md"
    outside.write_text("# theirs", encoding="utf-8")
    os.utime(outside, (now - _MAX_TIMEOUT - 60, now - _MAX_TIMEOUT - 60))
    _ask(engine, "c1", "run_shell", {"command": "python 生成.py"}, asked=asked)
    _answer(engine, "c1", "ok", legacy=True, finished=now)
    mgr.save(sid, engine)

    names = _by_name(mgr.list_artifacts(sid))
    assert "命令写出的.md" in names
    # Older than the command could possibly have been running: provably not its doing.
    assert "超时之前就在的.md" not in names


@pytest.mark.parametrize(
    "outcome",
    [
        # The three shapes of "never reached the tool": engine.py's denial, its stop path,
        # and its answer to arguments that never parsed. All three are error results with
        # no `t0`, because only `_execute_sync` records one.
        {"error": "tool call not executed", "reason": "denied by the user"},
        {"error": "tool call not executed", "reason": "interrupted by user"},
        {"error": "tool call not executed", "reason": "arguments did not parse"},
    ],
    ids=["denied", "interrupted", "mangled"],
)
def test_a_call_that_never_ran_opens_no_window_however_long_the_card_was_open(
    tmp_path, outcome
):
    """A call answered without ever running has `ts` but no `t0`, so it would otherwise take
    the legacy fallback — and an approval card left open for an hour before Deny would hand
    back a window the length of the shell timeout, over the user's own afternoon."""
    mgr, ws, engine = _gated(tmp_path, "sessArtNeverRan")
    sid = "sessArtNeverRan"
    now = time.time()
    theirs = ws / "用户下午写的.md"
    theirs.write_text("# theirs", encoding="utf-8")
    os.utime(theirs, (now - 300, now - 300))  # saved five minutes ago

    _ask(engine, "c1", "run_shell", {"command": "python 生成.py"}, asked=now - 3600)
    _answer(engine, "c1", outcome, legacy=True, finished=now)  # no t0: it never ran
    mgr.save(sid, engine)

    assert "用户下午写的.md" not in _by_name(mgr.list_artifacts(sid))


def test_a_command_that_ran_and_then_failed_still_opens_its_real_window(tmp_path):
    """The flip side of the rule above: a command that really executed carries `t0` even
    when it raised or timed out, and whatever it wrote before dying is still the session's.
    """
    mgr, ws, engine = _gated(tmp_path, "sessArtRanAndFailed")
    sid = "sessArtRanAndFailed"
    t0 = time.time()
    (ws / "半成品报告.md").write_text("# partial", encoding="utf-8")
    _ask(engine, "c1", "run_shell", {"command": "python 生成.py"}, asked=t0)
    _answer(
        engine,
        "c1",
        {"error": "command timed out after 120s", "error_type": "TimeoutError"},
        t0=t0,
    )
    mgr.save(sid, engine)

    assert "半成品报告.md" in _by_name(mgr.list_artifacts(sid))


def test_an_orphan_sessions_relative_writes_resolve_to_scratch_not_a_granted_folder(tmp_path):
    """An orphan session's PRIMARY root is its scratch dir. Reading the primary off the
    post-filter list made `write_file("报告.csv")` resolve into whatever folder the user had
    granted — where a same-named file of theirs was listed as this session's work, and
    could be opened from the panel."""
    mgr = _manager(tmp_path)
    sid = "sessArtOrphan"
    granted = tmp_path / "用户的资料库"
    granted.mkdir()
    theirs = granted / "报告.csv"
    theirs.write_text("这是用户自己的文件\n", encoding="utf-8")

    engine = mgr.get_engine(sid, agent="cowork")  # orphan: ws == scratch, primary
    assert mgr.add_root(sid, str(granted), writable=True)["ok"]

    args = {"path": "报告.csv", "content": "a,b\n"}
    _record_call(engine, "c1", "write_file", args, engine.registry.execute("write_file", args))
    mgr.save(sid, engine)

    entries = mgr.list_artifacts(sid)
    assert [(a["name"], a["root"]) for a in entries] == [("报告.csv", "scratch")]
    assert theirs.read_text(encoding="utf-8") == "这是用户自己的文件\n"  # untouched


def test_a_dangling_write_does_not_claim_a_file_it_never_wrote(tmp_path):
    """No result is not success. A call denied at the card — or one the process died on —
    leaves the same dangling assistant message, and its `path` may well name a file that
    was already there and belongs to the user."""
    mgr, ws, engine = _gated(tmp_path, "sessArtDanglingWrite")
    sid = "sessArtDanglingWrite"
    theirs = ws / "用户的季度总结.md"
    theirs.write_text("# theirs", encoding="utf-8")

    _ask(engine, "c1", "write_file", {"path": "用户的季度总结.md", "content": "overwritten"})
    mgr.save(sid, engine)

    assert "用户的季度总结.md" not in _by_name(mgr.list_artifacts(sid))
    assert theirs.read_text(encoding="utf-8") == "# theirs"


def test_a_clipped_error_result_still_reads_as_a_failure(tmp_path):
    """Tool results are clipped at 8k before they are stored, so "won't parse as JSON" must
    not mean "succeeded" — an error object is recognisable from its opening alone."""
    mgr, ws, engine = _gated(tmp_path, "sessArtClipped")
    sid = "sessArtClipped"
    (ws / "半途而废.md").write_text("# partial", encoding="utf-8")
    clipped = '{"error": "disk full while writing 半途而废.md and then the message was cut'
    _record_call(engine, "c1", "write_file", {"path": "半途而废.md", "content": "x"}, clipped)
    mgr.save(sid, engine)

    assert "半途而废.md" not in _by_name(mgr.list_artifacts(sid))


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are a Windows feature")
def test_a_junction_out_of_the_roots_is_not_swept_or_listed(tmp_path):
    """A junction inside the workspace is a door out of it. Windows reports one as a plain
    directory, so walking it collects paths that only LOOK contained: the viewer resolves
    before it scopes, so each row opens to "path escapes workspace" — after the panel has
    already shown the outside file's name, size and mtime."""
    import _winapi

    mgr, ws, engine = _gated(tmp_path, "sessArtJunction")
    sid = "sessArtJunction"
    outside = tmp_path / "别人的文件夹"
    outside.mkdir()
    try:
        _winapi.CreateJunction(str(outside), str(ws / "快捷方式"))
    except (OSError, AttributeError) as exc:  # pragma: no cover - policy/filesystem
        pytest.skip(f"could not create a junction here: {exc}")

    started = time.time()
    (outside / "外部机密.md").write_text("# not ours", encoding="utf-8")
    _record_call(
        engine, "c1", "run_shell", {"command": "python 生成.py"}, "ok", started=started
    )
    mgr.save(sid, engine)

    assert "外部机密.md" not in _by_name(mgr.list_artifacts(sid))


def test_named_writes_claim_the_non_scratch_budget_before_swept_files(tmp_path):
    """A single `ls` credits the session with every file the user saved around it — far more
    than the 40 non-scratch entries on offer. The exact source spends that budget first, so
    a file the agent demonstrably wrote is never dropped to make room for the noise.

    A BUDGET rule only. Ranking the finished list by how each file was found was tried and
    reverted: see the regression below."""
    mgr, ws, engine = _gated(tmp_path, "sessArtCap")
    sid = "sessArtCap"
    args = {"path": "交付报告.md", "content": "# the deliverable\n"}
    _record_call(engine, "c1", "write_file", args, engine.registry.execute("write_file", args))

    started = time.time()
    # 300 files the user saved while a listing command ran — all NEWER than the deliverable,
    # so a budget spent newest-first would spend all 40 slots before reaching it.
    noise = ws / "用户的资料"
    noise.mkdir()
    for i in range(300):
        (noise / f"同期保存{i:03d}.md").write_text("# noise", encoding="utf-8")
    os.utime(ws / "交付报告.md", (started - 600, started - 600))
    _record_call(engine, "c2", "run_shell", {"command": "ls"}, "ok", started=started)
    mgr.save(sid, engine)

    assert "交付报告.md" in _by_name(mgr.list_artifacts(sid))


def test_the_newest_file_leads_whichever_directory_it_is_in(tmp_path):
    """The regression that reverted tiered ordering. Scratch is where INTERMEDIATE files
    live, so ranking it above the workspace put the report a script had just written behind
    every temp file the turn produced — and the rail renders 16 rows. After a turn the user
    is looking for whatever changed last, wherever it landed."""
    mgr, ws, engine = _gated(tmp_path, "sessArtNewestFirst")
    sid = "sessArtNewestFirst"
    scratch = mgr.scratch_base() / sid
    base = time.time()
    for i in range(20):  # intermediate files, all older than the deliverable
        path = scratch / f"中间文件{i:02d}.md"
        path.write_text("# step", encoding="utf-8")
        os.utime(path, (base - 300 + i, base - 300 + i))

    started = time.time()
    (ws / "交付报告.md").write_text("# generated by the script", encoding="utf-8")
    _record_call(
        engine, "c1", "run_shell", {"command": "python 生成.py"}, "ok", started=started
    )
    mgr.save(sid, engine)

    entries = mgr.list_artifacts(sid)
    assert entries[0]["name"] == "交付报告.md"
    assert entries[0]["root"] == "workspace"
    # No internal bookkeeping rides along in the API response — the whole table, not row 0.
    assert not [k for e in entries for k in e if k.startswith("_")]

    # …and it still surfaces when scratch alone would overrun the 80-entry cap.
    for i in range(120):
        path = scratch / f"更多中间文件{i:03d}.md"
        path.write_text("# step", encoding="utf-8")
        os.utime(path, (base - 300 + i, base - 300 + i))
    assert mgr.list_artifacts(sid)[0]["name"] == "交付报告.md"


def test_a_scratch_only_session_is_ordered_exactly_as_before(tmp_path):
    """Nothing about the added source may reorder a session that never left scratch."""
    mgr, ws, engine = _gated(tmp_path, "sessArtScratchOrder")
    sid = "sessArtScratchOrder"
    scratch = mgr.scratch_base() / sid
    base = time.time()
    for i, name in enumerate(["最旧.md", "居中.md", "最新.md"]):
        path = scratch / name
        path.write_text("# x", encoding="utf-8")
        os.utime(path, (base - 100 + i * 10, base - 100 + i * 10))
    mgr.save(sid, engine)

    assert [a["name"] for a in mgr.list_artifacts(sid)] == ["最新.md", "居中.md", "最旧.md"]


def test_a_failed_write_is_not_listed_even_though_the_call_is_in_history(tmp_path):
    mgr, ws, engine = _gated(tmp_path, "sessArt4")
    sid = "sessArt4"
    args = {"path": "没写成.md", "content": "x"}
    _record_call(
        engine,
        "c1",
        "write_file",
        args,
        {"error": "Path is in a read-only directory: 没写成.md", "error_type": "PermissionError"},
    )
    mgr.save(sid, engine)
    assert "没写成.md" not in _by_name(mgr.list_artifacts(sid))


def test_a_cold_manager_rebuilds_the_list_from_the_persisted_jsonl(tmp_path):
    """Nothing is persisted for this feature beyond the conversation itself, so a restart
    must reach the same answer from the .jsonl alone — no live engine, no cached state."""
    mgr, ws, engine = _gated(tmp_path, "sessArt5")
    sid = "sessArt5"
    args = {"path": "报告.csv", "content": "a,b\n"}
    _record_call(engine, "c1", "write_file", args, engine.registry.execute("write_file", args))

    started = time.time()
    (ws / "图表.png").write_bytes(b"\x89PNG stand-in")
    _record_call(
        engine, "c2", "run_shell", {"command": "python 画图.py"}, "ok", started=started
    )
    mgr.save(sid, engine)

    cold = _manager(tmp_path)  # fresh manager + fresh store: only the jsonl survives
    assert cold._engines == {}
    names = _by_name(cold.list_artifacts(sid))
    assert {"报告.csv", "图表.png"} <= set(names)
    assert names["报告.csv"]["root"] == "workspace"


def test_the_sweep_stops_at_its_budget_instead_of_walking_a_monorepo(tmp_path):
    """Best-effort by design: the panel refreshes every turn, so whichever bound trips first
    ends the sweep. Only the shell-window source is budgeted — a named write is exact and
    costs one stat."""
    import coworker.server.manager as manager_module

    mgr, ws, engine = _gated(tmp_path, "sessArt6")
    sid = "sessArt6"
    deep = ws / "a" / "b" / "c"
    deep.mkdir(parents=True)
    started = time.time()
    (deep / "深层报告.md").write_text("# deep", encoding="utf-8")
    _record_call(
        engine, "c1", "run_shell", {"command": "python 生成.py"}, "ok", started=started
    )
    mgr.save(sid, engine)

    assert "深层报告.md" in _by_name(mgr.list_artifacts(sid))

    # One visited entry and the sweep is over — the file is no longer reachable.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(manager_module, "_SWEEP_MAX_ENTRIES", 1)
        assert "深层报告.md" not in _by_name(mgr.list_artifacts(sid))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(manager_module, "_SWEEP_MAX_DEPTH", 1)
        assert "深层报告.md" not in _by_name(mgr.list_artifacts(sid))


def test_scratch_still_lists_when_the_session_scan_blows_up(tmp_path):
    """The added source is derived, optional and best-effort. It must never cost the caller
    the scratch listing the panel has always had."""
    mgr, ws, engine = _gated(tmp_path, "sessArt7")
    sid = "sessArt7"
    scratch = mgr.scratch_base() / sid
    (scratch / "草稿.md").write_text("# draft", encoding="utf-8")
    mgr.save(sid, engine)

    def boom(self, session_id, *, scratch):
        raise RuntimeError("session scan exploded")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SessionManager, "_session_artifacts", boom)
        entries = mgr.list_artifacts(sid)
    assert _by_name(entries)["草稿.md"]["root"] == "scratch"


def test_scratch_entries_keep_their_relative_path_and_scratch_label(tmp_path):
    mgr, ws, engine = _gated(tmp_path, "sessArt8")
    sid = "sessArt8"
    scratch = mgr.scratch_base() / sid
    (scratch / "分析").mkdir()
    (scratch / "分析" / "结果.md").write_text("# out", encoding="utf-8")
    mgr.save(sid, engine)

    entry = _by_name(mgr.list_artifacts(sid))["结果.md"]
    assert entry["root"] == "scratch"
    assert entry["path"] == str(os.path.join("分析", "结果.md"))
    assert mgr.read_artifact(sid, entry["path"])["ok"] is True
