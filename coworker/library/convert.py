"""Turn a library-pack expert into an installable persona bundle (P2).

An "expert" in the library pack is just a name + emoji + a markdown system prompt (see
``library-pack/index.json`` and ``LibraryPack``). Installing one means rendering it into
the same ``manifest.md`` shape a hand-authored persona bundle uses
(``coworker/personas/manifest.py``), so it can ride the existing
``PersonaRegistry.install_from_dir`` consent/install path completely unchanged — this
module only produces the file; ``coworker/library/api.py`` does the installing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml

from ..personas.manifest import load_manifest_file

_SLUG_INVALID = re.compile(r"[^a-z0-9_-]+")
_MAX_BASE_LEN = 56  # + "-worker" (7 chars) stays within manifest.py's 64-char id cap

# Verbatim team-collaboration preamble prepended to a worker variant's system prompt
# (agent-teams design). The persona's own prompt follows after a blank line.
WORKER_PREAMBLE = """你在一个专家团中工作，接受队长（lead）的指派。你的对话对象是队长，不是最终用户——绝不调用 ask_user；有问题写成工作项评论（或在启用 # 团队聊天时 @lead 提问），并继续推进未被阻塞的部分。

团队契约：
- 任务以工作项形式到达：描述即任务书，验收标准是你的交付必须满足的判据；标准含糊就立即评论指出，不要闷头猜。
- 开工把工作项转为 in_progress；没有指派时可以认领（claim）开放且无人认领的工作项，队长看得到每次认领。
- 被阻塞就转为 blocked 并附上确切原因，绝不静默停摆；还有能干的就先干别的。
- 重要产出与依据写进日志（journal_append）：结论用 kind=finding，依据用 kind=evidence。看板评论只放日志引用，不贴大段内容。
- 发现职责范围外但值得做的事，用 create_item 立一个新工作项交队长裁量，然后继续手头的活。
- 完成 = 转 review 并附简洁交接评论：做了什么、产出在哪、日志引用。你永远不把自己的工作标记为 done。
- 收到的引导会标注 [Lead] 或 [User]；[User] 优先于 [Lead]。

以下是你的专业人设："""


def _slugify_base(raw: str) -> str:
    """Lowercase, replace anything outside [a-z0-9_-] with '-', drop a leading run of
    '-'/'_' so the result starts alnum (the only chars left after the substitution), and
    cap the length. Mirrors manifest.py's ``_ID_RE`` charset."""
    slug = _SLUG_INVALID.sub("-", raw.strip().lower()).lstrip("-_")
    return slug[:_MAX_BASE_LEN]


def load_index(pack: Any) -> Optional[dict[str, Any]]:
    """The ``{"experts": {"zh": [...], "en": [...]}}`` shape ``expert_persona_id`` needs,
    built from the pack's own public per-lib accessor (no direct index.json reach-in).
    ``None`` if the pack itself is missing/unreadable."""
    zh = pack.experts("zh")
    en = pack.experts("en")
    if not zh.get("ok") or not en.get("ok"):
        return None
    return {"experts": {"zh": zh.get("experts", []) or [], "en": en.get("experts", []) or []}}


def expert_persona_id(index: dict[str, Any], lib: str, pack_id: str, worker: bool) -> str:
    """The persona_id a (lib, pack_id) library entry installs as.

    Base = the pack id's last path segment. If that base is shared by more than one
    expert within the SAME lib's listing, prefix it with the entry's category
    (``"<category>-<base>"``) to disambiguate — otherwise the base alone. A worker
    variant is the solo id plus ``"-worker"``. Deterministic and pure: no registry or
    filesystem lookups, so both the installer and the status endpoint can call it freely.
    """
    rows = (index.get("experts", {}) or {}).get(lib, []) or []
    base = pack_id.rsplit("/", 1)[-1]
    basenames = [str(r.get("id", "")).rsplit("/", 1)[-1] for r in rows]
    if basenames.count(base) > 1:
        entry = next((r for r in rows if r.get("id") == pack_id), None)
        category = str((entry or {}).get("category") or "").strip()
        raw = f"{category}-{base}" if category else base
    else:
        raw = base
    slug = _slugify_base(raw)
    return f"{slug}-worker" if worker else slug


def _tagline(description: str) -> str:
    """The description, truncated to a settings-list-friendly length. Truncation gets an
    ellipsis; an already-short description is returned as-is."""
    if len(description) > 64:
        return description[:64] + "…"
    return description


def build_expert_bundle(
    pack: Any, lib: str, pack_id: str, worker: bool, dest_dir: str | Path
) -> Path:
    """Render the (lib, pack_id) expert as a persona bundle (``manifest.md``) under
    ``dest_dir`` and return its path. Raises ``ValueError`` if the pack or the expert is
    missing/unreadable. The written file is parsed with ``load_manifest_file`` before
    returning — a bundle that can't be loaded is never handed to the caller.
    """
    index = load_index(pack)
    if index is None:
        raise ValueError("library pack not found")
    lib = (lib or "").strip()
    rows = (index.get("experts", {}) or {}).get(lib, []) or []
    entry = next((r for r in rows if r.get("id") == pack_id), None)
    if entry is None:
        raise ValueError(f"unknown expert: {pack_id}")

    prompt = pack.expert_prompt(lib, pack_id)
    if not prompt.get("ok"):
        raise ValueError(prompt.get("error") or f"unknown expert: {pack_id}")
    body = str(prompt.get("prompt", "")).strip()
    if not body:
        raise ValueError(f"expert has no prompt body: {pack_id}")

    persona_id = expert_persona_id(index, lib, pack_id, worker)
    name = str(entry.get("name") or persona_id).strip() or persona_id
    if worker:
        name = f"{name}（组员）"
    description = " ".join(str(entry.get("description") or "").split())

    meta: dict[str, Any] = {
        "group": "general",
        "id": persona_id,
        "name": name,
        "icon": str(entry.get("emoji") or ""),
        "tagline": _tagline(description),
        "version": "1",
        "tools": ["files", "search", "shell", "todo"],
        "default_permission_mode": "interactive",
        "description": description,
    }
    if worker:
        meta["team"] = "worker"

    # yaml.safe_dump quotes/escapes whatever the description/name throw at it (English
    # colons, quotes, ...) so the frontmatter round-trips through yaml.safe_load
    # regardless of content — no manual escaping to get wrong. `width` disables line
    # wrapping so no value spills across lines (which could otherwise embed a stray
    # "\n---" and confuse manifest.py's naive frontmatter-block scan).
    frontmatter = yaml.safe_dump(
        meta,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1 << 20,
    )
    body_text = f"{WORKER_PREAMBLE}\n\n{body}\n" if worker else f"{body}\n"
    text = f"---\n{frontmatter}---\n\n{body_text}"

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = dest / "manifest.md"
    manifest_path.write_text(text, encoding="utf-8")

    load_manifest_file(manifest_path)  # self-test: must parse before we hand it off
    return manifest_path
