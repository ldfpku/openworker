"""``/v1/library*`` — browsing, installing, and activating the pre-built library pack
(experts + skills).

The five ``GET`` routes (P0) are read-only pack browsing and never need a manager. The
four P2 routes turn a pack entry into something real: ``install-expert``/
``activate-expert`` convert an expert into a persona bundle and run it through
``PersonaRegistry``'s normal install/consent path (see ``convert.py``); ``install-skills``
copies a skill folder into the global skills dir; ``status`` reports what's already
installed. They need the session's ``SessionManager`` (for its persona registry and
skill store) — when it isn't wired in, they report ``{"ok": false, "error": "library
install unavailable"}`` rather than 404, so a client can tell "not available here" apart
from "not found".

Follows the codebase's API convention throughout: validation failures (a missing pack, an
unknown id, a bad name, ...) return ``{"ok": False, "error": …}`` bodies rather than raw
4xx (see /v1/skills).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

from ..secrets import state_dir
from ..skills import hygiene
from ..skills.store import validate_name
from .convert import build_expert_bundle, expert_persona_id, load_index
from .pack import LibraryPack

_pack: Optional[LibraryPack] = None
_LIBS = ("zh", "en")


def _get_pack() -> LibraryPack:
    global _pack
    if _pack is None:
        _pack = LibraryPack()
    return _pack


def set_pack_for_tests(pack: Optional[LibraryPack]) -> None:
    """Test hook: swap the module-level singleton. ``None`` resets it so the next call
    re-locates a pack from the environment."""
    global _pack
    _pack = pack


def _library_staged_dir() -> Path:
    """Where install-expert renders manifest.md bundles before handing them to the
    persona registry — one subdirectory per persona_id, regenerated on every install."""
    return state_dir() / "library-staged"


def _is_library_staged_source(source: str) -> bool:
    """Whether an installed persona's recorded ``installed_meta.source`` lives under our
    own staging dir — the activate-expert safety gate: only ever activate a persona this
    library flow itself installed, never an arbitrary third-party one."""
    if not source:
        return False
    try:
        staged_root = _library_staged_dir().resolve()
        candidate = Path(source).resolve()
    except OSError:
        return False
    return staged_root == candidate or staged_root in candidate.parents


def register_library_routes(
    app: Any, manager: Any = None, pack: Optional[LibraryPack] = None
) -> None:
    """Register the ``/v1/library*`` routes on ``app``. Pass ``pack`` to bind a specific
    ``LibraryPack`` (tests); omitted, routes use the module-level singleton (created on
    first use). Pass ``manager`` (the session's ``SessionManager``) to enable the P2
    install/activate/status routes — omitted, they report unavailable."""
    if pack is not None:
        set_pack_for_tests(pack)

    # -- P0: read-only pack browsing --------------------------------------------------

    @app.get("/v1/library")
    def library_overview() -> dict[str, Any]:
        return _get_pack().overview()

    @app.get("/v1/library/experts")
    def library_experts(lib: str = "zh") -> dict[str, Any]:
        return _get_pack().experts(lib)

    @app.get("/v1/library/expert-prompt")
    def library_expert_prompt(lib: str = "zh", id: str = "") -> dict[str, Any]:
        return _get_pack().expert_prompt(lib, id)

    @app.get("/v1/library/skills")
    def library_skills() -> dict[str, Any]:
        return _get_pack().skills()

    @app.get("/v1/library/skill")
    def library_skill(name: str = "") -> dict[str, Any]:
        return _get_pack().skill(name)

    # -- P2: install / activate / status (need a SessionManager) ----------------------

    @app.post("/v1/library/install-expert")
    def library_install_expert(body: dict) -> dict[str, Any]:
        if manager is None:
            return {"ok": False, "error": "library install unavailable"}
        body = body or {}
        lib = str(body.get("lib", "zh") or "zh").strip()
        pack_id = str(body.get("id", "")).strip()
        worker = bool(body.get("worker", False))
        if lib not in _LIBS:
            return {"ok": False, "error": f"Unknown library: {lib}"}
        if not pack_id:
            return {"ok": False, "error": "id required"}

        pk = _get_pack()
        try:
            index = load_index(pk)
            if index is None:
                return {"ok": False, "error": "library pack not found"}
            persona_id = expert_persona_id(index, lib, pack_id, worker)
            dest_dir = _library_staged_dir() / persona_id
            build_expert_bundle(pk, lib, pack_id, worker, dest_dir)
            summaries = manager.personas.install_from_dir(dest_dir)
        except Exception as e:  # surface manifest/registry errors to the caller
            return {"ok": False, "error": str(e)}
        return {"ok": True, "persona_id": persona_id, "consent": summaries}

    @app.post("/v1/library/activate-expert")
    def library_activate_expert(body: dict) -> dict[str, Any]:
        if manager is None:
            return {"ok": False, "error": "library install unavailable"}
        persona_id = str((body or {}).get("persona_id", "")).strip()
        if not persona_id:
            return {"ok": False, "error": "persona_id required"}
        reg = manager.personas
        if reg.get(persona_id) is None:
            return {"ok": False, "error": f"unknown persona: {persona_id}"}
        meta = reg.installed_meta(persona_id)
        if not _is_library_staged_source(str(meta.get("source", ""))):
            return {
                "ok": False,
                "error": f"{persona_id} was not installed from the library",
            }
        # enable() implies surfacing (registry.set_enabled) — library experts stay out
        # of the new-session picker, so surface must be forced back off after.
        reg.set_enabled(persona_id, True)
        reg.set_surfaced(persona_id, False)
        return {"ok": True, "enabled": True}

    @app.post("/v1/library/install-skills")
    def library_install_skills(body: dict) -> dict[str, Any]:
        if manager is None:
            return {"ok": False, "error": "library install unavailable"}
        names = (body or {}).get("names")
        if not isinstance(names, list):
            return {"ok": False, "error": "names must be a list"}

        pk = _get_pack()
        pack_skills = pk.skills()
        if not pack_skills.get("ok"):
            return {"ok": False, "error": pack_skills.get("error") or "library pack not found"}
        pack_names = {s.get("name") for s in pack_skills.get("skills", []) if s.get("name")}
        global_dir = manager.skill_store.global_dir

        results: list[dict[str, Any]] = []
        for raw in names:
            name = str(raw)
            row: dict[str, Any] = {"name": name}
            try:
                validate_name(name)
            except ValueError as e:
                row["ok"] = False
                row["error"] = str(e)
                results.append(row)
                continue
            if name not in pack_names:
                row["ok"] = False
                row["error"] = f"unknown skill: {name}"
                results.append(row)
                continue
            dest = global_dir / name
            if dest.exists():
                row["ok"] = False
                row["error"] = "already installed"
                results.append(row)
                continue
            src = (pk.root / "skills" / name) if pk.root is not None else None
            if src is None or not src.is_dir():
                row["ok"] = False
                row["error"] = f"unknown skill: {name}"
                results.append(row)
                continue
            try:
                # 排除表来自 skills/hygiene.py，与用户上传 zip / 导入文件夹共用同一张表，
                # 两条路不会再各自维护一份而飘移。SKILL.zh.md 是库内浏览用的译文层：
                # 安装进全局技能目录的保持英文原件，agent 消费面不变。
                def _ignore(directory: str, names: list[str]) -> set[str]:
                    return hygiene.copytree_ignore()(directory, names) | {
                        n for n in names if n == "SKILL.zh.md"
                    }

                shutil.copytree(src, dest, ignore=_ignore)
                row["ok"] = True
            except OSError as e:
                row["ok"] = False
                row["error"] = str(e)
            results.append(row)
        return {"ok": True, "results": results}

    @app.get("/v1/library/status")
    def library_status() -> dict[str, Any]:
        if manager is None:
            return {"ok": False, "error": "library install unavailable"}
        pk = _get_pack()
        index = load_index(pk)
        if index is None:
            return {"ok": False, "error": "library pack not found"}
        reg = manager.personas

        experts_out: dict[str, Any] = {}
        for lib in _LIBS:
            rows = (index.get("experts", {}) or {}).get(lib, []) or []
            for row in rows:
                pack_id = row.get("id")
                if not pack_id:
                    continue
                variants: dict[str, Any] = {}
                for worker, tag in ((False, "solo"), (True, "worker")):
                    pid = expert_persona_id(index, lib, pack_id, worker)
                    if reg.get(pid) is not None:
                        variants[tag] = {"persona_id": pid, "enabled": reg.is_enabled(pid)}
                if variants:
                    experts_out[f"{lib}:{pack_id}"] = variants

        pack_skills = pk.skills()
        pack_names = (
            {s.get("name") for s in pack_skills.get("skills", []) if s.get("name")}
            if pack_skills.get("ok")
            else set()
        )
        global_dir = manager.skill_store.global_dir
        installed_skills = sorted(n for n in pack_names if (global_dir / n).is_dir())

        return {"ok": True, "experts": experts_out, "skills": installed_skills}
