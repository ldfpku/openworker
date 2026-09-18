"""Line-numbered file reading (`read_file`) and an honest `write_file` — both replace the
aisuite toolkit's originals.

The toolkit's `read_file` returns raw text (the agent can't cite path:line without
counting) and raises outright on large files (the agent errors and guesses). This one
returns `cat -n`-style numbered lines, windows big files instead of failing, and tells
the agent how to continue reading. Read-only, workspace-scoped.

`write_file` is the toolkit's own, wrapped (see `write_file_tools`): it reports the
ABSOLUTE path it wrote plus which root that is, and it refuses the ZIP-container Office
formats it can only ever corrupt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple, Optional

import aisuite as ai

from ..roots import resolved_paths

_DEFAULT_MAX_LINES = 2000
_MAX_LINE_CHARS = 500

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read a text file, returning numbered lines ('   12\\ttext') so code can be "
            "referenced as path:line. Large files are windowed: pass start_line to continue "
            "where the previous read stopped. Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path, relative to the workspace.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read, 1-based (default 1).",
                },
                "max_lines": {
                    "type": "integer",
                    "description": f"How many lines (default {_DEFAULT_MAX_LINES}).",
                },
            },
            "required": ["path"],
        },
    },
}


def file_tools(workspace: str, roots: Optional[list] = None) -> list:
    """Windowed read_file rooted at `workspace`. With `roots` (RootDir list), absolute
    paths inside ANY root also resolve — multi-root sessions (universal scratch) address
    their scratch/extra dirs by the absolute paths the roots context advertises."""
    root = Path(workspace).resolve()
    # `roots` is kept BY REFERENCE and resolved on every call (see resolved_paths) — never
    # snapshotted here. Materialising the paths at build time made read_file the one
    # consumer blind to a runtime grant, because the engine holding this closure is built
    # once per session and cached: it kept answering "path escapes the session's
    # directories" for a folder the user had just approved, which the model reads as a
    # denial and answers with another request_directory — an endless grant loop
    # (owner-hit 2026-08-31).

    def read_file(
        path: str,
        start_line: int = 1,
        max_lines: int = _DEFAULT_MAX_LINES,
    ) -> dict[str, Any]:
        start = start_line if isinstance(start_line, int) and start_line > 0 else 1
        n = (
            max_lines
            if isinstance(max_lines, int) and max_lines > 0
            else _DEFAULT_MAX_LINES
        )
        n = min(n, _DEFAULT_MAX_LINES)
        target = (root / path).resolve()
        home = root
        try:
            target.relative_to(root)  # keep reads inside the workspace
        except ValueError:
            for r in resolved_paths(roots):
                try:
                    target.relative_to(r)
                    home = r
                    break
                except ValueError:
                    continue
            else:
                return {"error": "path escapes the session's directories"}
        if not target.is_file():
            return {"error": f"not a file: {path}"}

        selected: list[str] = []
        total = 0
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    total = i
                    if i < start or len(selected) >= n:
                        continue
                    text = line.rstrip("\n")
                    if len(text) > _MAX_LINE_CHARS:
                        text = text[:_MAX_LINE_CHARS] + "… (line truncated)"
                    selected.append(f"{i:>6}\t{text}")
        except OSError as exc:
            return {"error": f"read failed: {exc}"}

        end = start + len(selected) - 1 if selected else start - 1
        result: dict[str, Any] = {
            "path": str(target.relative_to(home)) if home == root else str(target),
            "start_line": start,
            "end_line": end,
            "total_lines": total,
            "content": "\n".join(selected),
        }
        if end < total:
            result["note"] = (
                f"showing lines {start}-{end} of {total}; "
                f"call again with start_line={end + 1} to continue"
            )
        return result

    read_file.__name__ = "read_file"
    read_file.__doc__ = _SCHEMA["function"]["description"]
    read_file.__aisuite_tool_metadata__ = ai.ToolMetadata(
        name="read_file",
        category="filesystem",
        risk_level="low",
        capabilities=["read"],
        requires_approval=False,
    )
    read_file.__coworker_schema__ = _SCHEMA
    return [read_file]


# Office formats `write_file` must refuse. It encodes its `content` as UTF-8, so every one
# of these comes out a text file wearing the wrong extension: Excel and Word refuse to open
# it, and the agent — having seen a success — tells the user the spreadsheet is ready.
# Refusing costs one turn and names the way that works.
#
# Split by family because the families have different answers. Spreadsheets and Word
# documents each have a real one in this app (`tools/office.py`, `tools/document.py`) and
# share `_writer_error`; PowerPoint has no in-app writer yet, so its refusal still has to
# route around the missing capability and keeps its own text.
#
# `.xls` and `.doc` are in their families but are NOT ZIP containers — they are the OLE2
# binary formats Office 97 wrote, and on a Chinese office PC they are still what
# "Excel 文件" / "Word 文档" often mean, so a model asked for one reaches for write_file
# exactly like it would for .xlsx / .docx. Nothing in this app writes them (neither
# openpyxl nor python-docx can), and they must not be written as text either, so each is
# refused with the modern format offered in its place.
_ZIP_SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm"}
_LEGACY_SPREADSHEET_SUFFIXES = {".xls"}
_SPREADSHEET_SUFFIXES = _ZIP_SPREADSHEET_SUFFIXES | _LEGACY_SPREADSHEET_SUFFIXES
_ZIP_WORD_SUFFIXES = {".docx", ".docm"}
_LEGACY_WORD_SUFFIXES = {".doc"}
_WORD_SUFFIXES = _ZIP_WORD_SUFFIXES | _LEGACY_WORD_SUFFIXES
_PRESENTATION_SUFFIXES = {".pptx", ".pptm"}
_ZIP_CONTAINER_SUFFIXES = (
    _ZIP_SPREADSHEET_SUFFIXES | _ZIP_WORD_SUFFIXES | _PRESENTATION_SUFFIXES
)


class _Writer(NamedTuple):
    """The in-app tool that owns a format family, plus the words its refusal needs.

    One record per family rather than one function per family: the message is the same
    five sentences with five substitutions, and the two copies it replaced had already
    started to drift apart in wording.
    """

    tool: str  # the tool to name, and to materialise on the exception
    noun: str  # "workbook" / "document" — what the user is being handed
    modern: str  # the suffix that IS on offer
    macro: str  # the macro-enabled suffix of this family, which cannot be produced
    app: str  # "Excel" / "Word", for the legacy-format wording and the opens-with list
    delivers: str  # what the tool produces, in the refusal's own voice
    legacy: frozenset  # the family's non-container suffixes (OLE2 binaries)


_WRITERS: dict[str, _Writer] = {}


def _register_writer(suffixes, writer: _Writer) -> None:
    for suffix in suffixes:
        _WRITERS[suffix] = writer


_register_writer(
    _SPREADSHEET_SUFFIXES,
    _Writer(
        tool="write_spreadsheet",
        noun="workbook",
        modern=".xlsx",
        macro=".xlsm",
        app="Excel",
        delivers=(
            "it writes a real .xlsx in this app — several sheets, merged cells, borders, "
            "number formats, formulas — and needs neither Python nor Excel on this machine"
        ),
        legacy=frozenset(_LEGACY_SPREADSHEET_SUFFIXES),
    ),
)
_register_writer(
    _WORD_SUFFIXES,
    _Writer(
        tool="write_document",
        noun="document",
        modern=".docx",
        macro=".docm",
        app="Word",
        delivers=(
            "it turns Markdown into a real .docx in this app — headings, paragraphs, "
            "lists, tables, bold and italic, links, page breaks — and needs neither "
            "Python nor Word on this machine"
        ),
        legacy=frozenset(_LEGACY_WORD_SUFFIXES),
    ),
)


def _writer_error(suffix: str) -> ValueError:
    """Refuse, and hand over the tool that does it properly.

    `materialize_tools` is read by `engine._execute_sync`: the named tool is registered on
    the spot, so it is in the model's tool list on the very next round trip even if it
    never calls `load_office_tools`. The sentence naming the loader stays anyway — a
    resumed session, a replayed transcript or a persona without the loader all reach this
    text too, and a model that calls a deferred name directly gets it loaded.
    """
    w = _WRITERS[suffix]
    detail = (
        f"{suffix} is a ZIP container, so what write_file would produce is a text file "
        f"with a {suffix} name that no app can open"
        if suffix in _ZIP_CONTAINER_SUFFIXES
        else f"{suffix} is the old binary {w.app} format, which it cannot produce at all"
    )
    if suffix == w.macro:
        note = (
            f" Macros cannot be generated, so deliver the {w.noun} as {w.modern} instead "
            f"of {suffix}."
        )
    elif suffix in w.legacy:
        note = (
            f" Deliver the {w.noun} as {w.modern} instead of {suffix}; {w.app}, WPS and "
            "LibreOffice all open it."
        )
    else:
        note = ""
    error = ValueError(
        f"write_file writes UTF-8 text only, and {detail}. Use {w.tool} instead: "
        f"{w.delivers}. If {w.tool} is not in your tool list, call load_office_tools "
        f"to add it.{note} Tell the user which format you actually delivered."
    )
    error.materialize_tools = (w.tool,)
    return error


def _judged_suffix(path: str) -> str:
    """The extension the FILESYSTEM will end up giving this file, lowercased.

    Not `Path(path).suffix`: Windows silently drops trailing spaces and dots when it
    creates a file, so `write_file(path="报告.docx ")` lands on disk as `报告.docx` — but
    `Path("报告.docx ").suffix` is `".docx "`, which matches none of the sets above, and a
    5-byte text file goes out wearing a .docx name. `报告.docx.` is worse still: its suffix
    computes as `""`. Both were measured on Windows 11 (2026-09-18) — the refusal was
    skipped and the file was written.

    Stripping is for the JUDGEMENT only; the original `path` is what gets written, so
    nothing changes for an extension that was allowed anyway. On a filesystem that does
    keep the padding, `报告.docx ` is still a file no Word will open, so refusing it is
    right there too.
    """
    return Path(str(path).rstrip(" .")).suffix.lower()


def _presentation_error(suffix: str) -> str:
    """PowerPoint: no in-app writer yet, so route to the option that always works.

    The script route needs Python AND the right library on the USER's machine — the
    packaged backend is a frozen exe and `run_shell` spawns the user's own shell, so on an
    ordinary office PC neither is a given. Leading with it gets a plausible-looking plan
    that fails three commands later; leading with `.csv` gets the user a file they can
    open. The BOM note is for Excel specifically: without it Excel reads a UTF-8 CSV as the
    local ANSI codepage and every non-ASCII character comes out mangled.
    """
    return (
        f"write_file writes UTF-8 text only, and {suffix} is a ZIP container — what it "
        f"would produce is a text file with a {suffix} name that no app can open. "
        "Deliver .csv, .md or .html instead, which write_file writes properly (begin a "
        "CSV meant for Excel with the BOM U+FEFF or non-ASCII text arrives mangled). "
        "Only once you have checked with run_shell that this machine has Python and "
        "python-pptx should you generate it with a script — then verify the file exists. "
        "Either way, tell the user which format you actually delivered."
    )


def _root_entries(roots: Optional[list]) -> list[tuple[Path, str]]:
    """(resolved path, label) for each root, resolved on EVERY call — same reason as
    `resolved_paths`: the list is shared and mutated in place when a folder is granted."""
    out: list[tuple[Path, str]] = []
    for r in roots or []:
        if isinstance(r, dict):
            raw, label = r.get("path", ""), str(r.get("label") or "")
        elif isinstance(r, (str, Path)):
            raw, label = r, ""
        else:  # duck-typed RootDir-like
            raw, label = getattr(r, "path", ""), str(getattr(r, "label", "") or "")
        if raw:
            path = Path(str(raw)).expanduser().resolve()
            out.append((path, label or path.name))
    return out


def write_file_tools(
    inner: Any, workspace: str, roots: Optional[list] = None
) -> list:
    """The aisuite `write_file`, wrapped so its RESULT names the file it actually wrote.

    The toolkit reports `_relative(path)` — a bare `report.csv` for anything under the
    primary root. In a workspace+scratch session that is exactly the ambiguity that made
    the agent lie: it wrote a relative path (which resolves to the WORKSPACE), read back
    `report.csv`, and told the user the file was in scratch / in the Artifacts panel. An
    absolute path plus the root's own label leaves nothing to guess at, and it is the
    string the agent is now told to quote verbatim (see `roots.render_context`).

    Nothing consumes this result programmatically — the permission engine, provenance and
    the GUI's tool card all read the ARGUMENTS — so the extra words cost only tokens.
    """
    primary = Path(workspace).resolve()

    def write_file(path: str, content: str, overwrite: bool = True) -> str:
        """Write a UTF-8 text file under the configured root."""
        suffix = _judged_suffix(path)
        # Refuse BEFORE writing: a half-written .xlsx on disk is worse than none, and the
        # model would cite it as proof the spreadsheet exists.
        if suffix in _WRITERS:
            raise _writer_error(suffix)
        if suffix in _PRESENTATION_SUFFIXES:
            raise ValueError(_presentation_error(suffix))
        written = inner(path=path, content=content, overwrite=overwrite)
        try:
            p = Path(str(path)).expanduser()
            entries = _root_entries(roots)
            base = entries[0][0] if entries else primary
            target = p.resolve() if p.is_absolute() else (base / p).resolve()
            # Deepest matching root wins, so a folder nested inside another is labelled
            # with the one the user actually granted.
            label, depth = "", -1
            for root_path, root_label in entries:
                if not target.is_relative_to(root_path):
                    continue
                if len(root_path.parts) > depth:
                    label, depth = root_label, len(root_path.parts)
            return f"Wrote {target}" + (f" (root: {label})" if label else "")
        except Exception:
            # The bytes are already on disk. Everything past `inner` is cosmetics, so a
            # failure here must not be reported as a failed write — the engine turns a
            # raised tool into `{"error": …}`, and the model would then retry the write or
            # tell the user the file does not exist. Deliberately broad: no formatting bug
            # is worth turning a completed write into a lie. Fall back to what the toolkit
            # itself would have answered.
            return written

    write_file.__name__ = "write_file"
    write_file.__aisuite_tool_metadata__ = getattr(
        inner, "__aisuite_tool_metadata__", None
    ) or ai.ToolMetadata(
        name="write_file",
        category="filesystem",
        risk_level="medium",
        capabilities=["write_file"],
        requires_approval=True,
    )
    # Reuse the toolkit's own schema verbatim: the model must see the same tool it always
    # saw (same name, params, wording), so the prompt budget can't drift on a wrapper.
    from .registry import _schema_for

    write_file.__coworker_schema__ = _schema_for(inner)
    return [write_file]
