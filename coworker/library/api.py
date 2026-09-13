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

The P4 routes (``POST``/``DELETE /v1/library/expert``) are the machine-local layer
(``local.py``): edit any expert's text in place, write a new one, restore a shipped
original, delete a local one — nothing ever touches the pack, and an expert already
installed as a coworker is re-installed from the saved text.

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
from .local import LibraryOverlay, LocalLibrary, LocalLibraryError, is_local_id
from .pack import LibraryPack

_pack: Optional[LibraryPack] = None
_local: Optional[LocalLibrary] = None
_LIBS = ("zh", "en")


def _get_pack() -> LibraryPack:
    global _pack
    if _pack is None:
        _pack = LibraryPack()
    return _pack


def _get_local() -> LocalLibrary:
    """The machine-local layer (edited + hand-written experts, ``local.py``). Re-created
    when the state dir moves (tests isolate it per test via COWORKER_STATE_DIR)."""
    global _local
    expected = state_dir() / "library-local"
    if _local is None or _local.root != expected:
        _local = LocalLibrary(expected)
    return _local


def _library() -> LibraryOverlay:
    """What every expert-facing route and the installer read: the pack with the local
    layer applied. Skills pass straight through to the pack."""
    return LibraryOverlay(_get_pack(), _get_local())


def set_pack_for_tests(pack: Optional[LibraryPack]) -> None:
    """Test hook: swap the module-level singleton. ``None`` resets it so the next call
    re-locates a pack from the environment."""
    global _pack, _local
    _pack = pack
    _local = None


def _library_staged_dir() -> Path:
    """Where install-expert renders manifest.md bundles before handing them to the
    persona registry — one subdirectory per persona_id, regenerated on every install."""
    return state_dir() / "library-staged"


_STAGED_MARKER = "library.json"


def _write_staged_marker(dest_dir: Path, lib: str, expert_id: str, worker: bool) -> None:
    """Record WHICH library entry a staged bundle was rendered from. The persona id alone
    is ambiguous — a zh/en pair shares one id, and so do two experts with the same
    basename in different categories — so a later re-sync must not rebuild a coworker
    from the other language's text (audit 2026-09-10)."""
    import json

    (dest_dir / _STAGED_MARKER).write_text(
        json.dumps({"lib": lib, "id": expert_id, "worker": worker}, ensure_ascii=False),
        encoding="utf-8",
    )


def _staged_marker(persona_id: str) -> Optional[dict[str, Any]]:
    import json

    path = _library_staged_dir() / persona_id / _STAGED_MARKER
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


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
    install/activate/status routes — omitted, they report unavailable (the P4 edit
    routes still save files; only the coworker re-sync needs the manager)."""
    if pack is not None:
        set_pack_for_tests(pack)

    # -- P0: read-only pack browsing --------------------------------------------------

    @app.get("/v1/library")
    def library_overview() -> dict[str, Any]:
        return _library().overview()

    @app.get("/v1/library/experts")
    def library_experts(lib: str = "zh") -> dict[str, Any]:
        return _library().experts(lib)

    @app.get("/v1/library/expert-prompt")
    def library_expert_prompt(lib: str = "zh", id: str = "") -> dict[str, Any]:
        return _library().expert_prompt(lib, id)

    # -- P4: the machine-local layer — edit a pack expert in place, write a new one ------
    #
    # Nothing here touches the pack. Edits land in state_dir()/library-local/ (see
    # local.py) and show through the listing/prompt routes above; an expert that is
    # already installed as a coworker is re-installed from the edited text right away, so
    # the next session it hosts runs on what the person just saved (owner ask 2026-09-10:
    # "prompts must be editable in place, kept as this machine's own").

    def _resync_installed(lib: str, expert_id: str) -> list[str]:
        """Re-install every variant (solo / teammate) of ``(lib, id)`` this library flow
        installed before, from the CURRENT text. Enabled state survives (same tool set
        → ``install_from_dir`` keeps it). Returns the persona ids refreshed."""
        if manager is None:
            return []
        library = _library()
        index = load_index(library)
        if index is None:
            return []
        reg = manager.personas
        refreshed: list[str] = []
        for worker in (False, True):
            pid = expert_persona_id(index, lib, expert_id, worker)
            if reg.get(pid) is None:
                continue
            if not _is_library_staged_source(str(reg.installed_meta(pid).get("source", ""))):
                continue
            marker = _staged_marker(pid)
            # A bundle staged before markers existed carries none — treat it as this
            # entry's (the pre-2026-09-10 behaviour); a marker that names the OTHER
            # language or expert means this coworker is not ours to rewrite.
            if marker is not None and (marker.get("lib") != lib or marker.get("id") != expert_id):
                continue
            try:
                dest_dir = _library_staged_dir() / pid
                build_expert_bundle(library, lib, expert_id, worker, dest_dir)
                _write_staged_marker(dest_dir, lib, expert_id, worker)
                reg.install_from_dir(dest_dir)
                refreshed.append(pid)
            except Exception:  # noqa: BLE001 — a stale coworker is not a failed save
                continue
        return refreshed

    def _uninstall_local_expert(lib: str, expert_id: str) -> list[str]:
        """A deleted LOCAL expert takes the coworkers this flow installed for it along —
        otherwise they linger enabled-but-hidden with nothing in the library pointing at
        them (audit 2026-09-10). Sessions born from them resolve to the default coworker,
        like any uninstall. Only bundles our marker ties to this exact entry go."""
        if manager is None:
            return []
        library = _library()
        index = load_index(library)
        if index is None:
            return []
        reg = manager.personas
        removed: list[str] = []
        for worker in (False, True):
            pid = expert_persona_id(index, lib, expert_id, worker)
            entry = reg.get(pid)
            if entry is None or entry.builtin:
                continue
            if not _is_library_staged_source(str(reg.installed_meta(pid).get("source", ""))):
                continue
            marker = _staged_marker(pid)
            if marker is None or marker.get("lib") != lib or marker.get("id") != expert_id:
                continue
            try:
                reg.uninstall(pid)
                shutil.rmtree(_library_staged_dir() / pid, ignore_errors=True)
                removed.append(pid)
            except Exception:  # noqa: BLE001 — best effort; the expert file is gone either way
                continue
        return removed

    @app.post("/v1/library/expert")
    def library_save_expert(body: dict) -> dict[str, Any]:
        """Create (no ``id``) or save (``id`` given) an expert's local text. For a pack id
        the save is an override; for a ``local/…`` id it rewrites the person's own file."""
        body = body or {}
        lib = str(body.get("lib", "zh") or "zh").strip()
        expert_id = str(body.get("id", "") or "").strip()
        library = _library()
        local = _get_local()
        try:
            listing = library.experts(lib)
            if not listing.get("ok"):
                return {"ok": False, "error": listing.get("error") or "library pack not found"}
            rows = listing.get("experts", []) or []
            if expert_id:
                if not any(r.get("id") == expert_id for r in rows):
                    return {"ok": False, "error": f"Unknown expert: {expert_id}"}
                created = False
            else:
                # A new id must not land on an existing coworker's id either — persona
                # ids are app-wide, and basenames become persona ids (a local "Security"
                # would otherwise become `security`, the shipped built-in). Both
                # languages count too: a zh/en pair shares one id.
                taken = set()
                for other in _LIBS:
                    for r in _library().experts(other).get("experts", []) or []:
                        taken.add(str(r.get("id", "")).rsplit("/", 1)[-1])
                if manager is not None:
                    for pid in manager.personas.ids():
                        taken.add(pid)
                        if pid.endswith("-worker"):
                            taken.add(pid[: -len("-worker")])
                expert_id = local.new_id(lib, str(body.get("name") or ""), taken)
                created = True
            saved = local.write(lib, expert_id, body, body.get("prompt"))
        except LocalLibraryError as e:
            return {"ok": False, "error": str(e)}
        except OSError as e:
            return {"ok": False, "error": f"Could not write the file: {e}"}
        refreshed = _resync_installed(lib, expert_id)
        row = next(
            (r for r in (library.experts(lib).get("experts") or []) if r.get("id") == expert_id),
            None,
        )
        return {
            "ok": True,
            "id": expert_id,
            "created": created,
            "expert": row,
            "prompt": saved["prompt"],
            "path": str(local.path_for(lib, expert_id)),
            "reinstalled": refreshed,
        }

    @app.delete("/v1/library/expert")
    def library_delete_expert(lib: str = "zh", id: str = "") -> dict[str, Any]:
        """Drop the local text: for a pack expert that restores the shipped original (and
        re-installs its coworker from it); for a local expert it deletes the expert. An
        installed coworker of a deleted local expert stays installed — sessions born from
        it keep working, and Settings ▸ Coworkers can remove it."""
        expert_id = (id or "").strip()
        if not expert_id:
            return {"ok": False, "error": "id required"}
        local = _get_local()
        try:
            removed = local.delete(lib, expert_id)
        except LocalLibraryError as e:
            return {"ok": False, "error": str(e)}
        if not removed:
            return {"ok": False, "error": f"Nothing local to remove for: {expert_id}"}
        if is_local_id(expert_id):
            return {
                "ok": True,
                "id": expert_id,
                "deleted": True,
                "restored": False,
                "reinstalled": [],
                "uninstalled": _uninstall_local_expert(lib, expert_id),
            }
        return {
            "ok": True,
            "id": expert_id,
            "deleted": False,
            "restored": True,
            "reinstalled": _resync_installed(lib, expert_id),
            "uninstalled": [],
        }

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

        pk = _library()
        try:
            index = load_index(pk)
            if index is None:
                return {"ok": False, "error": "library pack not found"}
            persona_id = expert_persona_id(index, lib, pack_id, worker)
            existing = manager.personas.get(persona_id)
            if existing is not None:
                # Never install OVER a coworker this flow did not put there: a built-in
                # (a local expert named "Security" must not replace the shipped one) or
                # a person's own import. Re-installing our own staged bundle is fine —
                # that is how the other language / an edit lands (audit 2026-09-10).
                meta = manager.personas.installed_meta(persona_id)
                if existing.builtin or not _is_library_staged_source(str(meta.get("source", ""))):
                    return {
                        "ok": False,
                        "error": (
                            f"a coworker with the id '{persona_id}' already exists and was "
                            "not installed from the library — rename this expert"
                        ),
                    }
            dest_dir = _library_staged_dir() / persona_id
            build_expert_bundle(pk, lib, pack_id, worker, dest_dir)
            _write_staged_marker(dest_dir, lib, pack_id, worker)
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
        # of the new-session picker, so surface must be forced back off after. Never for the
        # DEFAULT coworker, though: set_default now forces surfaced=True precisely because a
        # default the picker refuses to offer is an incoherent state, and Settings gives no way
        # back out of it — the detail page disables "in picker" for a non-baseline default
        # (audit 2026-09-13).
        reg.set_enabled(persona_id, True)
        if reg.default_id() != persona_id:
            reg.set_surfaced(persona_id, False)
        return {"ok": True, "enabled": True}

    @app.post("/v1/library/install-skills")
    def library_install_skills(body: dict) -> dict[str, Any]:
        if manager is None:
            return {"ok": False, "error": "library install unavailable"}
        names = (body or {}).get("names")
        if not isinstance(names, list):
            return {"ok": False, "error": "names must be a list"}
        # replace=true re-copies the shipped original over an installed (possibly edited)
        # copy — the "restore the original" action of the library's skill page.
        replace = bool((body or {}).get("replace", False))

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
            if dest.exists() and not replace:
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

                if dest.exists():
                    if dest.is_symlink():
                        dest.unlink()
                    else:
                        shutil.rmtree(dest)
                shutil.copytree(src, dest, ignore=_ignore)
                row["ok"] = True
                if replace:
                    row["replaced"] = True
            except OSError as e:
                row["ok"] = False
                row["error"] = str(e)
            results.append(row)
        return {"ok": True, "results": results}

    @app.get("/v1/library/status")
    def library_status() -> dict[str, Any]:
        if manager is None:
            return {"ok": False, "error": "library install unavailable"}
        pk = _library()
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
