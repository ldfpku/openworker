"""The machine-local layer over the read-only library pack.

The pack (``library-pack/``, see ``pack.py``) ships with the app and is replaced wholesale
on every update, so nothing a person types can live in it. Their edits live here instead,
under ``state_dir()/library-local/``:

    experts/<lib>/<pack id>.md      an EDITED copy of a pack expert (an override — the pack's
                                    own file is untouched; delete the override to go back)
    experts/<lib>/local/<slug>.md   an expert the person wrote themselves

Both are ordinary expert markdown: YAML frontmatter (name, description, emoji, color,
category, categoryName) + the prompt as the body — the same shape the pack uses, so a file
copied out of here IS a shareable expert, and one dropped in by hand is picked up as-is.

``LibraryOverlay`` is what the API and the installer see: the pack's listing with the
overrides applied and the local experts appended, each row saying where it came from
(``local`` / ``modified``). Everything downstream — ``convert.build_expert_bundle``, the
status route, the persona ids — reads through it, so an edited prompt reaches the installed
coworker the same way the pack's did.

Local expert ids are ``local/<slug>``; the slug is chosen so its basename collides with no
other basename in that lib's listing, because ``convert.expert_persona_id`` derives persona
ids from basenames and prefixes them only on collision — a new local expert must never
change the persona id an already-installed pack expert resolves to.
"""

from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from ..secrets import state_dir

LOCAL_PREFIX = "local/"
_LIBS = ("zh", "en")
# Ids are relative paths inside the lib: lowercase slug segments joined by "/".
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*$")
_SLUG_INVALID = re.compile(r"[^a-z0-9_-]+")
_MAX_ID_LEN = 120
_MAX_NAME_LEN = 80
_MAX_DESCRIPTION_LEN = 2000
_MAX_PROMPT_LEN = 200_000
_MAX_CATEGORY_LEN = 40
# Frontmatter keys we read/write; anything else an author added by hand is preserved.
_META_KEYS = ("name", "description", "emoji", "color", "category", "categoryName")


class LocalLibraryError(ValueError):
    """A save/delete was refused — the message is safe to show to the person."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """``(frontmatter, body)`` for an expert markdown file. A missing or unparseable
    frontmatter block → ``({}, text)``; the body comes back stripped."""
    if not text.startswith("---"):
        return {}, text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text.strip()
    raw = text[3:end]
    body = text[end + 4 :]
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body.strip()


def render_expert_md(meta: dict[str, Any], prompt: str) -> str:
    """The on-disk shape: safe-dumped frontmatter (quoting handles colons, quotes and
    emoji; no line wrapping so no value can smuggle a ``\\n---`` in) + the prompt."""
    frontmatter = yaml.safe_dump(
        meta,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1 << 20,
    )
    return f"---\n{frontmatter}---\n\n{prompt.strip()}\n"


def _slugify(raw: str) -> str:
    slug = _SLUG_INVALID.sub("-", raw.strip().lower()).strip("-_")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:48]


def validate_lib(lib: str) -> str:
    lib = (lib or "").strip()
    if lib not in _LIBS:
        raise LocalLibraryError(f"Unknown library: {lib}")
    return lib


def validate_id(expert_id: str) -> str:
    expert_id = (expert_id or "").strip()
    if not expert_id or len(expert_id) > _MAX_ID_LEN or not _ID_RE.match(expert_id):
        raise LocalLibraryError(f"Invalid expert id: {expert_id!r}")
    return expert_id


def is_local_id(expert_id: str) -> bool:
    return (expert_id or "").startswith(LOCAL_PREFIX)


def _clean_meta(fields: dict[str, Any]) -> dict[str, Any]:
    """Normalize + bound the editable fields. Raises ``LocalLibraryError`` on the ones a
    person must fix (a missing name); trims the rest quietly."""
    name = " ".join(str(fields.get("name") or "").split())
    if not name:
        raise LocalLibraryError("Name is required.")
    if len(name) > _MAX_NAME_LEN:
        raise LocalLibraryError(f"Name too long (limit {_MAX_NAME_LEN} characters).")
    description = " ".join(str(fields.get("description") or "").split())[:_MAX_DESCRIPTION_LEN]
    emoji = str(fields.get("emoji") or "").strip()[:8]
    color = str(fields.get("color") or "").strip()[:32]
    category = _slugify(str(fields.get("category") or ""))[:_MAX_CATEGORY_LEN] or "local"
    category_name = " ".join(str(fields.get("categoryName") or "").split())[:_MAX_CATEGORY_LEN]
    return {
        "name": name,
        "description": description,
        "emoji": emoji,
        "color": color,
        "category": category,
        "categoryName": category_name or category,
    }


def _clean_prompt(prompt: Any) -> str:
    text = str(prompt or "").replace("\r\n", "\n").strip()
    if not text:
        raise LocalLibraryError("The prompt is required.")
    if len(text) > _MAX_PROMPT_LEN:
        raise LocalLibraryError(f"Prompt too long (limit {_MAX_PROMPT_LEN} characters).")
    return text


class LocalLibrary:
    """Folder-backed CRUD over the local expert files. Every operation is a file
    operation guarded against escaping ``root``; the lock serializes writers (the API
    routes are sync defs on FastAPI's threadpool)."""

    def __init__(self, root: Optional[str | Path] = None) -> None:
        self.root = Path(root) if root is not None else state_dir() / "library-local"
        self._lock = threading.Lock()

    # -- paths ----------------------------------------------------------------------
    def experts_dir(self, lib: str) -> Path:
        return self.root / "experts" / validate_lib(lib)

    def path_for(self, lib: str, expert_id: str) -> Path:
        base = self.experts_dir(lib)
        expert_id = validate_id(expert_id)
        candidate = base / f"{expert_id}.md"
        try:
            base_r = base.resolve()
            cand_r = candidate.resolve()
        except OSError as e:
            raise LocalLibraryError(f"Unreadable path: {e}") from e
        if base_r != cand_r and base_r not in cand_r.parents:
            raise LocalLibraryError(f"Invalid expert id: {expert_id!r}")
        return candidate

    # -- reads ----------------------------------------------------------------------
    def read(self, lib: str, expert_id: str) -> Optional[dict[str, Any]]:
        """The local file for ``(lib, id)`` as ``{id, name, …, prompt, updated_at}`` or
        ``None`` when there is none (or it can't be read)."""
        try:
            path = self.path_for(lib, expert_id)
        except LocalLibraryError:
            return None
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError:
            return None
        meta, body = split_frontmatter(text)
        row = {"id": expert_id}
        for key in _META_KEYS:
            value = meta.get(key)
            row[key] = "" if value is None else str(value)
        row["prompt"] = body
        row["updated_at"] = stamp.replace(microsecond=0).isoformat()
        return row

    def ids(self, lib: str) -> list[str]:
        """Every id with a local file in ``lib`` (overrides and local experts alike)."""
        try:
            base = self.experts_dir(lib)
        except LocalLibraryError:
            return []
        if not base.is_dir():
            return []
        out: list[str] = []
        for md in sorted(base.rglob("*.md")):
            if not md.is_file():
                continue
            rel = md.relative_to(base).with_suffix("")
            expert_id = "/".join(rel.parts)
            if _ID_RE.match(expert_id) and len(expert_id) <= _MAX_ID_LEN:
                out.append(expert_id)
        return out

    def local_rows(self, lib: str) -> list[dict[str, Any]]:
        """Listing rows (the pack index shape) for the experts written here."""
        rows: list[dict[str, Any]] = []
        for expert_id in self.ids(lib):
            if not is_local_id(expert_id):
                continue
            row = self.read(lib, expert_id)
            if row is None:
                continue
            rows.append(
                {
                    "id": expert_id,
                    "category": row["category"] or "local",
                    "categoryName": row["categoryName"] or row["category"] or "local",
                    "name": row["name"] or expert_id.rsplit("/", 1)[-1],
                    "description": row["description"],
                    "emoji": row["emoji"],
                    "color": row["color"] or "#888",
                    "pair": False,
                    "local": True,
                    "modified": False,
                    "updated_at": row["updated_at"],
                }
            )
        return rows

    # -- writes ---------------------------------------------------------------------
    def new_id(self, lib: str, name: str, taken_basenames: set[str]) -> str:
        """A fresh ``local/<slug>`` id whose basename collides with nothing in
        ``taken_basenames`` (every basename already listed in this lib) nor with an
        existing local file. Non-latin names (most Chinese ones) slugify to nothing, so
        those get a short stable hash of the name instead — the id is an address, the
        name is what people see."""
        slug = _slugify(name)
        if not slug:
            slug = "expert-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        taken = set(taken_basenames)
        for existing in self.ids(lib):
            taken.add(existing.rsplit("/", 1)[-1])
        candidate = slug
        n = 2
        while candidate in taken:
            candidate = f"{slug}-{n}"
            n += 1
        return f"{LOCAL_PREFIX}{candidate}"

    def write(self, lib: str, expert_id: str, fields: dict[str, Any], prompt: Any) -> dict[str, Any]:
        """Create or replace the local file for ``(lib, id)``. Returns what ``read`` would.
        Unknown frontmatter keys an author added by hand survive a save from the app."""
        path = self.path_for(lib, expert_id)
        meta = _clean_meta(fields)
        body = _clean_prompt(prompt)
        with self._lock:
            existing: dict[str, Any] = {}
            if path.is_file():
                try:
                    existing, _ = split_frontmatter(path.read_text(encoding="utf-8"))
                except OSError:
                    existing = {}
            merged: dict[str, Any] = dict(meta)
            for key, value in existing.items():  # hand-added extras survive
                if key not in _META_KEYS and key != "updated_at":
                    merged[key] = value
            merged["updated_at"] = _now()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".md.tmp")
            tmp.write_text(render_expert_md(merged, body), encoding="utf-8")
            tmp.replace(path)
        row = self.read(lib, expert_id)
        assert row is not None
        return row

    def delete(self, lib: str, expert_id: str) -> bool:
        """Remove the local file. True if one was there. For a pack id this is the
        "restore the original" action; for a local id it deletes the expert."""
        path = self.path_for(lib, expert_id)
        with self._lock:
            if not path.is_file():
                return False
            try:
                path.unlink()
            except OSError as e:
                raise LocalLibraryError(f"Could not delete: {e}") from e
            # Tidy an emptied local/ folder; never the lib dir itself.
            parent = path.parent
            try:
                if parent != self.experts_dir(lib) and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
        return True


class LibraryOverlay:
    """The pack as the person sees it: pack rows with local overrides applied, plus the
    local experts. Same query surface as ``LibraryPack`` (``convert.py`` and the routes
    call ``experts`` / ``expert_prompt`` / ``skills`` / ``skill`` and read ``root``), so it
    drops in wherever the pack did."""

    def __init__(self, pack: Any, local: LocalLibrary) -> None:
        self.pack = pack
        self.local = local

    @property
    def root(self) -> Optional[Path]:
        return self.pack.root

    def overview(self) -> dict[str, Any]:
        out = self.pack.overview()
        if not out.get("ok"):
            return out
        counts = dict(out.get("experts") or {})
        for lib in _LIBS:
            counts[lib] = counts.get(lib, 0) + len(self.local.local_rows(lib))
        out["experts"] = counts
        out["local_dir"] = str(self.local.root)
        return out

    def experts(self, lib: str = "zh") -> dict[str, Any]:
        out = self.pack.experts(lib)
        if not out.get("ok"):
            return out
        lib = (lib or "zh").strip()
        overridden = {i for i in self.local.ids(lib) if not is_local_id(i)}
        rows: list[dict[str, Any]] = []
        for row in out.get("experts", []) or []:
            row = dict(row)
            row["local"] = False
            row["modified"] = row.get("id") in overridden
            if row["modified"]:
                # The override's identity fields win in the listing (a renamed expert
                # must read renamed); the pack keeps category/pair/color.
                over = self.local.read(lib, str(row["id"])) or {}
                for key in ("name", "description", "emoji"):
                    if over.get(key):
                        row[key] = over[key]
                row["updated_at"] = over.get("updated_at", "")
            rows.append(row)
        rows.extend(self.local.local_rows(lib))
        return {"ok": True, "experts": rows}

    def expert_prompt(self, lib: str, expert_id: str) -> dict[str, Any]:
        lib = (lib or "zh").strip()
        expert_id = (expert_id or "").strip()
        local = self.local.read(lib, expert_id) if expert_id else None
        if is_local_id(expert_id):
            if local is None:
                return {"ok": False, "error": f"Unknown expert: {expert_id}"}
            return {
                "ok": True,
                "id": expert_id,
                "name": local["name"],
                "prompt": local["prompt"],
                "local": True,
                "modified": False,
                "meta": {k: local[k] for k in _META_KEYS},
                "updated_at": local["updated_at"],
            }
        out = self.pack.expert_prompt(lib, expert_id)
        if not out.get("ok"):
            return out
        entry = next(
            (r for r in (self.pack.experts(lib).get("experts") or []) if r.get("id") == expert_id),
            {},
        )
        meta = {k: str(entry.get(k) or "") for k in _META_KEYS}
        out = dict(out)
        out["local"] = False
        out["modified"] = False
        out["pack_prompt"] = out["prompt"]
        if local is not None:
            for key in ("name", "description", "emoji"):
                if local.get(key):
                    meta[key] = local[key]
            out.update(
                {
                    "name": local["name"] or out.get("name", ""),
                    "prompt": local["prompt"],
                    "modified": True,
                    "updated_at": local["updated_at"],
                }
            )
        out["meta"] = meta
        return out

    def skills(self) -> dict[str, Any]:
        return self.pack.skills()

    def skill(self, name: str) -> dict[str, Any]:
        return self.pack.skill(name)
