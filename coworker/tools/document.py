"""Real Word files, written in-process — `write_document` (.docx) from Markdown.

Second tenant of the story `tools/office.py` opens: `write_file` can only ever produce a
text file wearing a `.docx` extension, and the script route needs Python AND python-docx on
the USER's machine. The packaged backend is a frozen exe on an office PC that has neither,
so the ZIP container is built here, in the backend process, with python-docx bundled.

**Markdown in, not a block DSL.** Every model already writes Markdown fluently and spends
no tokens learning it, and a document is prose — where a spreadsheet is a grid, and so got
`sheets[].rows[][]`. The cost is that Markdown has no notion of a merged table cell, which
a Chinese report header needs constantly, so two markers extend GFM tables: a cell holding
only `<` merges into the cell on its left, `^` into the cell above.

**The default look is a Chinese office document**, because that is who runs this build:
A4, 宋体 body over Times New Roman for Latin, 黑体 headings, 1.5 line spacing, a 2-character
first-line indent, centred page numbers. `style="plain"` leaves the stylesheet alone.

Three things worth knowing before editing:

* **Built-in styles are MODIFIED, not bypassed.** The look could be set per paragraph, and
  it would render the same — and Word's navigation pane would be empty, a table of contents
  would come out blank, and the user could not restyle the document. So `Normal`, `Title`
  and `Heading 1`–`Heading 4` are edited in `styles.xml` and every paragraph just names one.
  The corollary is that the list, quote, heading, header and footer styles have to zero the
  first-line indent they inherit from `Normal`, or the page number sits 2 characters right
  of centre.
* **Every ordered list restarts at 1.** `List Number` points at one shared `w:num`, so two
  numbered lists in one document would run 1,2,3,4,5,6. Each list gets a fresh `w:num`
  pointing at the same `abstractNum` with `startOverride`.
* **Paths, atomic write and the receipt prefix are `office.py`'s**, imported rather than
  copied: `tests/test_office_tools.py` cross-checks that layer against aisuite's
  `write_file`, and a second copy would be a second thing to keep in step with it.

python-docx and markdown-it-py are imported lazily, inside the call, for the same reason
openpyxl is: a build without them must still start.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import aisuite as ai

from coworker.tools.office import (
    ILLEGAL_XML_CHARS,
    atomic_write,
    prepare_target,
    receipt_head,
    root_label,
)

# -- limits ---------------------------------------------------------------------
_MAX_MARKDOWN_CHARS = 2_000_000
_MAX_TABLE_ROWS = 5_000  # one table
_MAX_LIST_DEPTH = 3  # Word ships list styles for three levels; deeper is clamped
_MAX_HEADING_LEVEL = 4  # h5/h6 render as h4 — a report with six levels has a structure bug

# -- the office look ------------------------------------------------------------
_BODY_EASTASIA = "宋体"
_BODY_LATIN = "Times New Roman"
_HEADING_EASTASIA = "黑体"
_HEADING_LATIN = "Arial"
_CODE_FONT = "Consolas"

_BODY_PT = 12  # 小四
_CELL_PT = 10.5  # 五号
_CODE_PT = 10
_TITLE_PT = 22  # 二号
_HEADING_PT = {1: 18, 2: 16, 3: 14, 4: 12}

_HEADER_FILL = "DDEBF7"  # the same header blue write_spreadsheet uses
_CODE_FILL = "F2F2F2"
_QUOTE_COLOR = "595959"
_LINK_COLOR = "0563C1"  # Word's own Hyperlink blue
_BLACK = "000000"

_FIRST_LINE_CHARS = 200  # w:ind/@w:firstLineChars is in hundredths of a character
_LINE_150 = 360  # w:line, twentieths of a point: 1.5 x 240
_LINE_SINGLE = 240
_QUOTE_INDENT_CM = 0.74

# Styles that inherit from Normal and must NOT inherit its first-line indent.
_NO_INDENT_STYLES = (
    "Title",
    "Heading 1",
    "Heading 2",
    "Heading 3",
    "Heading 4",
    "List Bullet",
    "List Bullet 2",
    "List Bullet 3",
    "List Number",
    "List Number 2",
    "List Number 3",
    "Quote",
    "Header",
    "Footer",
)

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_document",
        "description": (
            "Create a real Word .docx file from Markdown (works without Python or Word "
            "installed). Supports headings, paragraphs, bold/italic/code/strikethrough, "
            "links, nested lists, GFM tables (a cell containing only < merges into the "
            "cell on its left, ^ into the cell above), block quotes, code blocks, --- "
            "rules and <!-- pagebreak -->. Default style is a Chinese office layout "
            "(SimSun body, SimHei headings, 1.5 line spacing, 2-char first-line indent, "
            "A4, page numbers). Overwrites an existing file. Path rules are the same as "
            "write_file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Output path; must end with .docx",
                },
                "markdown": {
                    "type": "string",
                    "description": (
                        "Document content in Markdown. A leading '# ' heading becomes the "
                        "centered document title."
                    ),
                },
                "style": {
                    "type": "string",
                    "enum": ["office", "plain"],
                    "description": (
                        "office (default): Chinese office layout; plain: Word defaults"
                    ),
                },
            },
            "required": ["path", "markdown"],
        },
    },
}

_STYLES = ("office", "plain")


# -- lazy backends --------------------------------------------------------------
#
# `_qn` and `_OxmlElement` are module globals bound by `_load_backends`, which every entry
# point calls first. The XML helpers below reach for them by name rather than taking them
# as arguments: they are the only two python-docx primitives used outside the renderer, and
# threading them through forty call sites buys nothing.
_qn = None
_OxmlElement = None


def _load_backends() -> SimpleNamespace:
    """Import python-docx and markdown-it-py, or say what to deliver instead."""
    global _qn, _OxmlElement
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
        from docx.opc.constants import RELATIONSHIP_TYPE
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm, Mm, Pt, RGBColor
        from markdown_it import MarkdownIt
    except ImportError as exc:  # a build that trimmed the dependency
        raise RuntimeError(
            "this build is missing python-docx (or markdown-it-py), so it cannot write "
            ".docx files; deliver the same content as a Markdown .md file with write_file "
            "instead, and tell the user which format you actually delivered."
        ) from exc
    _qn, _OxmlElement = qn, OxmlElement
    return SimpleNamespace(
        Document=Document,
        MarkdownIt=MarkdownIt,
        Cm=Cm,
        Mm=Mm,
        Pt=Pt,
        RGBColor=RGBColor,
        ALIGN=WD_ALIGN_PARAGRAPH,
        BREAK=WD_BREAK,
        HYPERLINK=RELATIONSHIP_TYPE.HYPERLINK,
    )


# -- raw OOXML helpers ----------------------------------------------------------
#
# ECMA-376 fixes the child order of these property elements and Word refuses a document
# that gets it wrong ("unreadable content"), so nothing is ever appended blindly: the
# sequences below are the schema's, and `_ordered` inserts ahead of the first successor
# that is already present. python-docx exposes `get_or_add_*` for the children it models
# (pStyle, numPr, spacing, ind, jc); these are the ones it does not.

_PPR_SEQ = (
    "w:pStyle",
    "w:keepNext",
    "w:keepLines",
    "w:pageBreakBefore",
    "w:framePr",
    "w:widowControl",
    "w:numPr",
    "w:suppressLineNumbers",
    "w:pBdr",
    "w:shd",
    "w:tabs",
    "w:suppressAutoHyphens",
    "w:kinsoku",
    "w:wordWrap",
    "w:overflowPunct",
    "w:topLinePunct",
    "w:autoSpaceDE",
    "w:autoSpaceDN",
    "w:bidi",
    "w:adjustRightInd",
    "w:snapToGrid",
    "w:spacing",
    "w:ind",
    "w:contextualSpacing",
    "w:mirrorIndents",
    "w:suppressOverlap",
    "w:jc",
    "w:textDirection",
    "w:textAlignment",
    "w:textboxTightWrap",
    "w:outlineLvl",
    "w:divId",
    "w:cnfStyle",
    "w:rPr",
    "w:sectPr",
    "w:pPrChange",
)

_TBLPR_SEQ = (
    "w:tblStyle",
    "w:tblpPr",
    "w:tblOverlap",
    "w:bidiVisual",
    "w:tblStyleRowBandSize",
    "w:tblStyleColBandSize",
    "w:tblW",
    "w:jc",
    "w:tblCellSpacing",
    "w:tblInd",
    "w:tblBorders",
    "w:shd",
    "w:tblLayout",
    "w:tblCellMar",
    "w:tblLook",
    "w:tblCaption",
    "w:tblDescription",
    "w:tblPrChange",
)

_TCPR_SEQ = (
    "w:cnfStyle",
    "w:tcW",
    "w:gridSpan",
    "w:hMerge",
    "w:vMerge",
    "w:tcBorders",
    "w:shd",
    "w:noWrap",
    "w:tcMar",
    "w:textDirection",
    "w:tcFitText",
    "w:vAlign",
    "w:hideMark",
    "w:headers",
    "w:cellIns",
    "w:cellDel",
    "w:cellMerge",
    "w:tcPrChange",
)

_TRPR_SEQ = (
    "w:cnfStyle",
    "w:divId",
    "w:gridBefore",
    "w:gridAfter",
    "w:wBefore",
    "w:wAfter",
    "w:cantSplit",
    "w:trHeight",
    "w:tblHeader",
    "w:tblCellSpacing",
    "w:jc",
    "w:hidden",
    "w:ins",
    "w:del",
    "w:trPrChange",
)

_NUMPR_SEQ = ("w:ilvl", "w:numId", "w:numberingChange", "w:ins")
_PBDR_SEQ = ("w:top", "w:left", "w:bottom", "w:right", "w:between", "w:bar")


def _el(tag: str, attrs: Optional[dict] = None):
    node = _OxmlElement(tag)
    for key, value in (attrs or {}).items():
        node.set(_qn(key), str(value))
    return node


def _ordered(parent, tag: str, seq: tuple):
    """The existing `tag` child of `parent`, or a new one inserted in schema order.

    Plain lxml rather than python-docx's `insert_element_before`: that is a method of its
    `BaseOxmlElement` mixin, and a tag python-docx does not model (`w:pBdr`, for one) comes
    back from `OxmlElement` as a bare `lxml` element without it.
    """
    found = parent.find(_qn(tag))
    if found is not None:
        return found
    node = _OxmlElement(tag)
    successors = {_qn(name) for name in seq[seq.index(tag) + 1 :]}
    for child in parent:
        if child.tag in successors:
            child.addprevious(node)
            return node
    parent.append(node)
    return node


def _drop(parent, tag: str) -> None:
    for node in parent.findall(_qn(tag)):
        parent.remove(node)


def _set_attrs(node, attrs: dict) -> None:
    for key, value in attrs.items():
        node.set(_qn(key), str(value))


def _clear_theme(node, *names: str) -> None:
    """Strip the theme-backed attributes that would override a value we set explicitly.

    `<w:color w:val="365F91" w:themeColor="accent1" w:themeShade="BF"/>` renders as the
    THEME colour: Word reads the theme attributes in preference to `w:val`. The built-in
    Heading and Title styles ship exactly that, plus `w:asciiTheme`/`w:eastAsiaTheme` on
    their fonts, so setting only the explicit attribute leaves blue Calibri headings and
    looks like nothing worked.

    Every name is spelled out by the caller rather than derived from a stem, because the
    naming only LOOKS regular: `w:color`'s modifiers are `w:themeTint` and `w:themeShade`,
    not `w:themeColorTint`, while `w:shd`'s really are `w:themeFillTint` and
    `w:themeFillShade`. Deriving them left `w:themeShade="BF"` on Title and Heading 1.
    """
    for name in names:
        key = _qn(f"w:{name}")
        if node.get(key) is not None:
            del node.attrib[key]


def _fonts(rpr, latin: str, eastasia: str) -> None:
    """`w:rFonts` for all three scripts. Word picks `eastAsia` per CJK character and
    `ascii`/`hAnsi` for Latin, so a mixed Chinese/English line comes out in both faces."""
    rfonts = rpr.get_or_add_rFonts()
    _clear_theme(rfonts, "asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme")
    _set_attrs(
        rfonts,
        {
            "w:ascii": latin,
            "w:hAnsi": latin,
            "w:eastAsia": eastasia,
            "w:cs": latin,
        },
    )


def _color(rpr, hex_rgb: str) -> None:
    node = rpr.get_or_add_color()
    _clear_theme(node, "themeColor", "themeTint", "themeShade")
    node.set(_qn("w:val"), hex_rgb)


def _indent(ppr, *, first_line_chars: int, first_line_twips: int, left_twips: int = 0):
    """`w:ind`, with both the character and the absolute measure.

    `w:firstLineChars` is the attribute a Chinese Word writes and the only one that keeps a
    2-character indent 2 characters wide when the font size changes — but LibreOffice and
    older WPS ignore it entirely and fall back to `w:firstLine`. Writing both means the
    indent survives whichever program the user actually has; Word prefers Chars when both
    are present, so there is no conflict.
    """
    ind = ppr.get_or_add_ind()
    _set_attrs(
        ind,
        {
            "w:firstLineChars": first_line_chars,
            "w:firstLine": first_line_twips,
        },
    )
    if left_twips:
        ind.set(_qn("w:left"), str(left_twips))
    return ind


def _shade(ppr_or_tcpr, fill: str, seq: tuple) -> None:
    # `w:shd` carries two independent theme pairs — one behind `w:color` (the pattern) and
    # one behind `w:fill` (the background). Both are cleared, because both attributes are
    # being set here.
    node = _ordered(ppr_or_tcpr, "w:shd", seq)
    _clear_theme(
        node,
        "themeColor",
        "themeTint",
        "themeShade",
        "themeFill",
        "themeFillTint",
        "themeFillShade",
    )
    _set_attrs(node, {"w:val": "clear", "w:color": "auto", "w:fill": fill})


def _spacing(ppr, *, line: int, before: int = 0, after: int = 0) -> None:
    node = ppr.get_or_add_spacing()
    _set_attrs(
        node,
        {
            "w:line": line,
            "w:lineRule": "auto",
            "w:before": before,
            "w:after": after,
        },
    )


# -- markdown preprocessing -----------------------------------------------------

# `<!-- pagebreak -->` alone on a line. The substitution below wraps it in blank lines so
# it is always its own block: without them, a break between two unblanked lines lands in
# the MIDDLE of one CommonMark paragraph, where a page break cannot be expressed.
_PAGEBREAK_LINE = re.compile(r"^[ \t]*<!--[ \t]*pagebreak[ \t]*-->[ \t]*$", re.IGNORECASE)
_FENCE_LINE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
# U+E000 is private use: it has no meaning of its own, so it cannot collide with anything
# the author meant. Any pre-existing copy is stripped first, which makes the sentinel
# unforgeable from the input.
_PAGEBREAK = "\ue000pagebreak\ue000"
# Spelled by code point on purpose: a literal BOM in the source is invisible in
# every editor, and the next person to touch this line cannot see what it strips.
_BOM = chr(0xFEFF)


def _preprocess(markdown: str) -> str:
    """Normalise line endings, drop XML-illegal control characters, and turn pagebreak
    comments into a sentinel.

    The line endings come FIRST and are not optional. markdown-it normalises `\\r\\n` and
    `\\r` to `\\n` itself, but that happens inside `parse()` — everything this function does
    runs before it, splits on `\\n`, and matches line patterns anchored with `$`. A
    `<!-- pagebreak -->` arriving with CRLF (a model quoting a file the user pasted from
    Notepad, or any Windows-side round trip) would keep a trailing `\\r`, miss
    `_PAGEBREAK_LINE`, and be printed into the document as literal text.

    A leading BOM goes the same way: `\\ufeff# 标题` is not a heading, it is a paragraph
    that happens to start with a hash.

    The scan tracks fenced code blocks so a Markdown cheat sheet that SHOWS the pagebreak
    comment inside a ``` fence gets a code line, not a page break.
    """
    text = markdown.lstrip(_BOM).replace("\r\n", "\n").replace("\r", "\n")
    text = ILLEGAL_XML_CHARS.sub("", text).replace(_PAGEBREAK, "")
    out: list[str] = []
    fence = ""
    for line in text.split("\n"):
        opener = _FENCE_LINE.match(line)
        if fence:
            if opener and opener.group(1)[0] == fence[0] and len(opener.group(1)) >= len(fence):
                fence = ""
            out.append(line)
            continue
        if opener:
            fence = opener.group(1)
            out.append(line)
            continue
        if _PAGEBREAK_LINE.match(line):
            out.append(f"\n{_PAGEBREAK}\n")
            continue
        out.append(line)
    return "\n".join(out)


def _is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _softbreak_space(prev: str, nxt: str) -> bool:
    """Whether a soft line break becomes a space.

    CommonMark says a soft break is a space, and for Latin text it has to be or words run
    together. Between two CJK characters it must NOT be: Chinese has no inter-word space,
    so a report whose author wrapped a paragraph in their editor would come out with a
    visible gap at every line they happened to break.
    """
    if not prev or not nxt or prev.isspace() or nxt.isspace():
        return False
    return not (_is_wide(prev) and _is_wide(nxt))


# -- table merge markers --------------------------------------------------------

_MERGE_LEFT = "<"
_MERGE_UP = "^"
_MERGE_RULE = (
    "a cell holding only < merges into the cell on its left and ^ into the cell above; "
    "the markers must form a rectangle whose top-left cell holds the content"
)


def _merge_plan(
    markers: list[list[Optional[str]]], table_no: int
) -> list[tuple[int, int, int, int]]:
    """(top, left, bottom, right) per merged block, or a ValueError naming the cell.

    A block is grown from its anchor — the cell that still holds content: the run of `<` to
    its right sets the width, and each following row extends the height only if the anchor's
    own column holds `^` there AND the rest of the block's width is markers too. Anything
    left over is a marker that belongs to no block, which is nearly always a row the model
    lost count of, so it is refused rather than quietly dropped.
    """
    rows, cols = len(markers), (len(markers[0]) if markers else 0)
    where = f"table {table_no}"

    for r in range(rows):
        if markers[r][0] == _MERGE_LEFT:
            raise ValueError(
                f"{where}, row {r + 1}, column 1: < has no cell to its left. "
                f"{_MERGE_RULE}."
            )
    for c in range(cols):
        if markers[0][c] == _MERGE_UP:
            raise ValueError(
                f"{where}, row 1, column {c + 1}: ^ has no cell above it — the header row "
                f"cannot merge upwards. {_MERGE_RULE}."
            )

    claimed = [[False] * cols for _ in range(rows)]
    blocks: list[tuple[int, int, int, int]] = []
    for r in range(rows):
        for c in range(cols):
            if markers[r][c] is not None:
                continue  # a marker; it is claimed by the anchor above or to its left
            width = 1
            while c + width < cols and markers[r][c + width] == _MERGE_LEFT:
                width += 1
            height = 1
            while r + height < rows:
                if markers[r + height][c] != _MERGE_UP:
                    break
                if any(
                    markers[r + height][c + k] is None for k in range(1, width)
                ):  # a real cell under the block: the block stops above it
                    break
                height += 1
            for rr in range(r, r + height):
                for cc in range(c, c + width):
                    claimed[rr][cc] = True
            if width > 1 or height > 1:
                blocks.append((r, c, r + height - 1, c + width - 1))

    for r in range(rows):
        for c in range(cols):
            if markers[r][c] is not None and not claimed[r][c]:
                raise ValueError(
                    f"{where}, row {r + 1}, column {c + 1}: the "
                    f"{markers[r][c]} marker is not part of any merged block. "
                    f"{_MERGE_RULE}."
                )
    return blocks


# -- the renderer ---------------------------------------------------------------


class _Writer:
    """One document. Walks markdown-it's token stream and builds the .docx as it goes."""

    def __init__(self, dx: SimpleNamespace, style: str):
        self.dx = dx
        self.style = style
        self.office = style == "office"
        self.doc = dx.Document()
        self.paragraphs = 0  # prose paragraphs and list items; code lines are not counted
        self.headings = 0
        self.tables = 0
        self.lists = 0  # top-level list blocks; a nested list is part of its parent
        self.page_breaks = 0
        self.images = 0
        self._title_pending = False
        self._abstract_cache: dict[str, Optional[str]] = {}

    # -- entry ------------------------------------------------------------------

    def build(self, tokens: list) -> None:
        if self.office:
            self._office_stylesheet()
        self._title_pending = bool(tokens) and (
            tokens[0].type == "heading_open" and tokens[0].tag == "h1"
        )
        self._blocks(tokens, 0, len(tokens))
        self._page_numbers()
        # A document the user forwards: no names, no machine, no account.
        self.doc.core_properties.author = "OpenWorker"
        self.doc.core_properties.last_modified_by = "OpenWorker"

    # -- stylesheet -------------------------------------------------------------

    def _office_stylesheet(self) -> None:
        dx = self.dx
        for section in self.doc.sections:
            section.page_width = dx.Mm(210)  # A4
            section.page_height = dx.Mm(297)
            section.top_margin = dx.Mm(25.4)
            section.bottom_margin = dx.Mm(25.4)
            section.left_margin = dx.Mm(31.7)
            section.right_margin = dx.Mm(31.7)

        normal = self.doc.styles["Normal"]
        rpr = normal.element.get_or_add_rPr()
        _fonts(rpr, _BODY_LATIN, _BODY_EASTASIA)
        normal.font.size = dx.Pt(_BODY_PT)
        ppr = normal.element.get_or_add_pPr()
        _spacing(ppr, line=_LINE_150)
        _indent(
            ppr,
            first_line_chars=_FIRST_LINE_CHARS,
            first_line_twips=int(_BODY_PT * 20 * _FIRST_LINE_CHARS / 100),
        )

        title = self.doc.styles["Title"]
        t_ppr = title.element.get_or_add_pPr()
        _drop(t_ppr, "w:pBdr")  # the built-in Title's blue rule is not an office look
        _spacing(t_ppr, line=_LINE_150, after=240)
        t_ppr.get_or_add_jc().set(_qn("w:val"), "center")
        t_rpr = title.element.get_or_add_rPr()
        _fonts(t_rpr, _HEADING_LATIN, _HEADING_EASTASIA)
        _color(t_rpr, _BLACK)
        title.font.size = dx.Pt(_TITLE_PT)
        title.font.bold = True

        for level, size in _HEADING_PT.items():
            style = self.doc.styles[f"Heading {level}"]
            h_ppr = style.element.get_or_add_pPr()
            _spacing(h_ppr, line=_LINE_150, before=240, after=120)
            h_rpr = style.element.get_or_add_rPr()
            _fonts(h_rpr, _HEADING_LATIN, _HEADING_EASTASIA)
            _color(h_rpr, _BLACK)
            style.font.size = dx.Pt(size)
            style.font.bold = True

        quote = self.doc.styles["Quote"]
        q_rpr = quote.element.get_or_add_rPr()
        _color(q_rpr, _QUOTE_COLOR)
        quote.font.italic = False  # slanted 宋体 is a synthesised fake, and it shows
        quote.paragraph_format.left_indent = dx.Cm(_QUOTE_INDENT_CM)

        # Everything based on Normal inherits its 2-character first line. A numbered item,
        # a table caption or a centred page number pushed 2 characters right is the single
        # most visible way this look goes wrong.
        for name in _NO_INDENT_STYLES:
            n_ppr = self.doc.styles[name].element.get_or_add_pPr()
            _indent(n_ppr, first_line_chars=0, first_line_twips=0)

    def _page_numbers(self) -> None:
        """A centred `PAGE` field in the footer, both styles. Written as field characters
        rather than `fldSimple` because that is the form Word itself emits and the one WPS
        updates reliably."""
        for section in self.doc.sections:
            footer = section.footer
            footer.is_linked_to_previous = False
            paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
            paragraph.alignment = self.dx.ALIGN.CENTER
            run = paragraph.add_run()
            run._r.append(_el("w:fldChar", {"w:fldCharType": "begin"}))
            instr = _el("w:instrText", {"xml:space": "preserve"})
            instr.text = " PAGE "
            run._r.append(instr)
            run._r.append(_el("w:fldChar", {"w:fldCharType": "end"}))

    # -- token walking ----------------------------------------------------------

    @staticmethod
    def _close(tokens: list, index: int, end: int) -> int:
        """Index of the token closing `tokens[index]`, or `end` if the stream is unbalanced
        (markdown-it never emits that; the fallback just stops the loop)."""
        level = 0
        for j in range(index, end):
            level += tokens[j].nesting
            if level == 0:
                return j
        return end

    def _blocks(
        self,
        tokens: list,
        start: int,
        end: int,
        *,
        quote: bool = False,
        depth: int = 0,
        item: Optional[dict] = None,
    ) -> None:
        i = start
        while i < end:
            token = tokens[i]
            kind = token.type
            if kind == "heading_open":
                close = self._close(tokens, i, end)
                self._heading(token, tokens[i + 1 : close])
                i = close + 1
            elif kind == "paragraph_open":
                close = self._close(tokens, i, end)
                self._paragraph(tokens[i + 1 : close], quote=quote, item=item)
                i = close + 1
            elif kind in ("bullet_list_open", "ordered_list_open"):
                close = self._close(tokens, i, end)
                self._list(
                    tokens,
                    i,
                    close,
                    ordered=kind == "ordered_list_open",
                    depth=depth + 1,
                    quote=quote,
                )
                i = close + 1
            elif kind == "blockquote_open":
                close = self._close(tokens, i, end)
                self._blocks(tokens, i + 1, close, quote=True, depth=depth)
                i = close + 1
            elif kind in ("fence", "code_block"):
                self._code(token)
                i += 1
            elif kind == "hr":
                self._rule()
                i += 1
            elif kind == "table_open":
                close = self._close(tokens, i, end)
                self._table(tokens, i + 1, close)
                i = close + 1
            elif kind == "inline":  # a stray inline; render it rather than lose the text
                self._paragraph([token], quote=quote, item=item)
                i += 1
            else:
                i += 1

    # -- blocks -----------------------------------------------------------------

    def _new_paragraph(self, style: Optional[str] = None):
        return self.doc.add_paragraph(style=style) if style else self.doc.add_paragraph()

    @staticmethod
    def _children(inline_tokens: list) -> list:
        out: list = []
        for token in inline_tokens:
            if token.type == "inline":
                out.extend(token.children or [])
        return out

    @staticmethod
    def _plain(inline_tokens: list) -> str:
        return "".join(t.content for t in inline_tokens if t.type == "inline")

    def _heading(self, token, inline_tokens: list) -> None:
        # h5/h6 land on Heading 4: Word only ships four levels of the office look, and a
        # report that needs six is telling you about its outline, not its typography.
        level = min(int(token.tag[1:] or 1), _MAX_HEADING_LEVEL)
        if self._title_pending:
            self._title_pending = False
            style = "Title"
        else:
            style = f"Heading {level}"
        paragraph = self._new_paragraph(style)
        self._inline(paragraph, self._children(inline_tokens))
        self.headings += 1

    def _paragraph(
        self, inline_tokens: list, *, quote: bool = False, item: Optional[dict] = None
    ) -> None:
        if self._plain(inline_tokens).strip() == _PAGEBREAK:
            self._page_break()
            return
        if item is not None:
            paragraph = self._new_paragraph(item["style"])
            if item["first"]:
                # A fresh w:num per ordered list, so it starts at 1 (see the module note).
                self._numbering(paragraph, item["num"])
                item["first"] = False
            else:
                # A second paragraph inside one list item keeps the indent but must not
                # draw a second bullet. numId 0 is OOXML for "no numbering".
                self._numbering(paragraph, 0)
        else:
            paragraph = self._new_paragraph("Quote" if quote else None)
        self._inline(paragraph, self._children(inline_tokens))
        self.paragraphs += 1

    def _page_break(self) -> None:
        run = self._new_paragraph().add_run()
        run.add_break(self.dx.BREAK.PAGE)
        self.page_breaks += 1

    def _rule(self) -> None:
        paragraph = self._new_paragraph()
        ppr = paragraph._p.get_or_add_pPr()
        border = _ordered(ppr, "w:pBdr", _PPR_SEQ)
        bottom = _ordered(border, "w:bottom", _PBDR_SEQ)
        _set_attrs(
            bottom,
            {"w:val": "single", "w:sz": 6, "w:space": 1, "w:color": "auto"},
        )
        if self.office:
            _indent(ppr, first_line_chars=0, first_line_twips=0)

    def _code(self, token) -> None:
        """One paragraph per line, shaded as a block. Word has no multi-line run, and a
        single paragraph with `w:br` between lines loses the shading on the blank ones."""
        lines = token.content.split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        for line in lines or [""]:
            paragraph = self._new_paragraph()
            ppr = paragraph._p.get_or_add_pPr()
            _shade(ppr, _CODE_FILL, _PPR_SEQ)
            _spacing(ppr, line=_LINE_SINGLE)
            if self.office:
                _indent(ppr, first_line_chars=0, first_line_twips=0)
            run = paragraph.add_run(line) if line else paragraph.add_run()
            _fonts(run._r.get_or_add_rPr(), _CODE_FONT, _CODE_FONT)
            run.font.size = self.dx.Pt(_CODE_PT)

    # -- lists ------------------------------------------------------------------

    def _abstract_num_for(self, style_name: str) -> Optional[str]:
        """The `abstractNumId` behind a built-in list style, via the `w:num` it names."""
        if style_name in self._abstract_cache:
            return self._abstract_cache[style_name]
        found: Optional[str] = None
        try:
            ppr = self.doc.styles[style_name].element.pPr
            num_id = ppr.numPr.numId.val if ppr is not None and ppr.numPr is not None else None
            if num_id is not None:
                numbering = self.doc.part.numbering_part.element
                for num in numbering.findall(_qn("w:num")):
                    if num.get(_qn("w:numId")) == str(num_id):
                        abstract = num.find(_qn("w:abstractNumId"))
                        if abstract is not None:
                            found = abstract.get(_qn("w:val"))
                        break
        except (AttributeError, KeyError, NotImplementedError):
            found = None  # a stand-in template without numbering: fall back to the style
        self._abstract_cache[style_name] = found
        return found

    def _fresh_num(self, style_name: str) -> Optional[int]:
        abstract = self._abstract_num_for(style_name)
        if abstract is None:
            return None
        numbering = self.doc.part.numbering_part.element
        used = [
            int(n.get(_qn("w:numId")) or 0) for n in numbering.findall(_qn("w:num"))
        ]
        new_id = max(used) + 1 if used else 1
        num = _el("w:num", {"w:numId": new_id})
        num.append(_el("w:abstractNumId", {"w:val": abstract}))
        override = _el("w:lvlOverride", {"w:ilvl": 0})
        override.append(_el("w:startOverride", {"w:val": 1}))
        num.append(override)
        # `w:num` is the last repeated child of `w:numbering`, so appending is in order.
        numbering.append(num)
        return new_id

    def _numbering(self, paragraph, num_id: Optional[int]) -> None:
        if num_id is None:
            return  # a bullet list: the style's own w:num is already right
        ppr = paragraph._p.get_or_add_pPr()
        numpr = ppr.get_or_add_numPr()
        _ordered(numpr, "w:ilvl", _NUMPR_SEQ).set(_qn("w:val"), "0")
        _ordered(numpr, "w:numId", _NUMPR_SEQ).set(_qn("w:val"), str(num_id))

    def _list(
        self,
        tokens: list,
        open_i: int,
        close_i: int,
        *,
        ordered: bool,
        depth: int,
        quote: bool,
    ) -> None:
        if depth == 1:
            self.lists += 1
        level = min(depth, _MAX_LIST_DEPTH)
        base = "List Number" if ordered else "List Bullet"
        style = base if level == 1 else f"{base} {level}"
        num_id = self._fresh_num(style) if ordered else None

        i = open_i + 1
        while i < close_i:
            if tokens[i].type == "list_item_open":
                item_close = self._close(tokens, i, close_i)
                item = {"style": style, "num": num_id, "first": True}
                # `- ` with only a nested list under it (and `- ` with nothing at all) give
                # a list_item containing NO paragraph, so nothing would consume `first` and
                # the outer item would lose its own bullet — the nested items would appear
                # to hang off nothing. Give it an empty list paragraph to sit on, BEFORE
                # the nested content, which is where the marker belongs.
                opens_with = tokens[i + 1].type if i + 1 < item_close else ""
                if opens_with != "paragraph_open":
                    self._empty_item(item)
                self._blocks(
                    tokens,
                    i + 1,
                    item_close,
                    quote=quote,
                    depth=depth,
                    item=item,
                )
                i = item_close + 1
            else:
                i += 1

    def _empty_item(self, item: dict) -> None:
        """The list item's own marker line, with no text of its own."""
        paragraph = self._new_paragraph(item["style"])
        self._numbering(paragraph, item["num"])
        item["first"] = False
        self.paragraphs += 1

    # -- inline -----------------------------------------------------------------

    def _inline(self, paragraph, children: list) -> None:
        """Render one `inline` token's children into `paragraph`.

        `link` is the open `w:hyperlink` element; runs are created with python-docx's own
        API and then MOVED into it, which keeps the run formatting API and still produces a
        real relationship-backed hyperlink rather than blue underlined text.
        """
        state = {"bold": False, "italic": False, "strike": False, "link": None}
        last = ""

        def emit(text: str, *, code: bool = False) -> str:
            if not text:
                return last
            run = paragraph.add_run(text)
            if state["bold"]:
                run.bold = True
            if state["italic"]:
                run.italic = True
            if state["strike"]:
                run.font.strike = True
            if code:
                _fonts(run._r.get_or_add_rPr(), _CODE_FONT, _CODE_FONT)
                run.font.size = self.dx.Pt(_CODE_PT)
            if state["link"] is not None:
                run.font.color.rgb = self.dx.RGBColor.from_string(_LINK_COLOR)
                run.font.underline = True
                state["link"].append(run._r)  # lxml move: out of w:p, into w:hyperlink
            return text[-1]

        pending_url = ""  # a link whose scheme was refused; spelled out after its text
        for index, token in enumerate(children):
            kind = token.type
            if kind == "text":
                last = emit(token.content)
            elif kind == "code_inline":
                last = emit(token.content, code=True)
            elif kind == "strong_open":
                state["bold"] = True
            elif kind == "strong_close":
                state["bold"] = False
            elif kind == "em_open":
                state["italic"] = True
            elif kind == "em_close":
                state["italic"] = False
            elif kind == "s_open":
                state["strike"] = True
            elif kind == "s_close":
                state["strike"] = False
            elif kind == "link_open":
                href = str((token.attrs or {}).get("href") or "")
                if _linkable(href):
                    state["link"] = self._hyperlink(paragraph, href)
                    pending_url = ""
                else:
                    # A javascript:, file: or data: target is not something to put one
                    # click away in a document the user forwards. The text still reads,
                    # with the target spelled out beside it.
                    state["link"] = None
                    pending_url = href
            elif kind == "link_close":
                state["link"] = None
                if pending_url:
                    last = emit(f" ({pending_url})")
                    pending_url = ""
            elif kind == "image":
                self.images += 1
                alt = (token.content or "").strip()
                last = emit(f"[图片: {alt}]" if alt else "[图片]")
            elif kind == "hardbreak":
                paragraph.add_run().add_break()
                last = ""
            elif kind == "softbreak":
                if _softbreak_space(last, _next_char(children, index)):
                    last = emit(" ")
            elif token.content:  # html_inline and anything else: keep the text
                last = emit(token.content)

    def _hyperlink(self, paragraph, href: str):
        rid = paragraph.part.relate_to(href, self.dx.HYPERLINK, is_external=True)
        link = _el("w:hyperlink", {"r:id": rid})
        paragraph._p.append(link)
        return link

    # -- tables -----------------------------------------------------------------

    def _table(self, tokens: list, start: int, end: int) -> None:
        self.tables += 1
        table_no = self.tables
        rows: list[list[Optional[Any]]] = []
        aligns: list[Optional[str]] = []
        head_rows = 0
        in_head = False

        i = start
        while i < end:
            token = tokens[i]
            kind = token.type
            if kind == "thead_open":
                in_head = True
            elif kind == "thead_close":
                in_head = False
            elif kind == "tr_open":
                close = self._close(tokens, i, end)
                cells: list[Optional[Any]] = []
                j = i + 1
                while j < close:
                    cell = tokens[j]
                    if cell.type in ("th_open", "td_open"):
                        cell_close = self._close(tokens, j, close)
                        inline = next(
                            (t for t in tokens[j + 1 : cell_close] if t.type == "inline"),
                            None,
                        )
                        cells.append(inline)
                        if in_head and not rows:
                            aligns.append(_align_of(cell))
                        j = cell_close + 1
                    else:
                        j += 1
                rows.append(cells)
                if in_head:
                    head_rows += 1
                i = close + 1
                continue
            i += 1

        if not rows:
            return
        if len(rows) > _MAX_TABLE_ROWS:
            raise ValueError(
                f"table {table_no} has {len(rows)} rows, over the {_MAX_TABLE_ROWS} limit "
                "for one table — split it, or deliver the data as a spreadsheet with "
                "write_spreadsheet."
            )

        # markdown-it already pads a short row and drops a long one against the header, but
        # a token stream is not a contract: normalise so the grid below is rectangular.
        cols = max(len(rows[0]), 1)
        grid = [(row + [None] * cols)[:cols] for row in rows]
        while len(aligns) < cols:
            aligns.append(None)

        markers: list[list[Optional[str]]] = [
            [
                text
                if (text := (cell.content.strip() if cell is not None else ""))
                in (_MERGE_LEFT, _MERGE_UP)
                else None
                for cell in row
            ]
            for row in grid
        ]
        blocks = _merge_plan(markers, table_no)

        table = self.doc.add_table(rows=len(grid), cols=cols)
        table.style = "Table Grid"
        table.autofit = True
        # Fill the text column, whatever the page size or column count: a table that stops
        # at 60% of the line looks like a mistake in a report.
        width = _ordered(table._tbl.tblPr, "w:tblW", _TBLPR_SEQ)
        _set_attrs(width, {"w:type": "pct", "w:w": 5000})

        # Repeat the header on every page a long table spills onto. Word will not infer
        # this, and a 200-row report whose second page has unlabelled columns is the sort
        # of thing the reader notices and the author does not.
        for row in table.rows[:head_rows]:
            _ordered(row._tr.get_or_add_trPr(), "w:tblHeader", _TRPR_SEQ)

        # Merge BEFORE writing: `_Cell.merge` concatenates the cells' contents, so a table
        # filled first would carry the literal "<" and "^" markers into the merged cell.
        for top, left, bottom, right in blocks:
            table.cell(top, left).merge(table.cell(bottom, right))

        for r, row in enumerate(grid):
            for c, inline in enumerate(row):
                if markers[r][c] is not None:
                    continue  # covered by the block anchored above/left of it
                cell = table.cell(r, c)
                for extra in list(cell.paragraphs)[1:]:  # merge leftovers, if any
                    extra._p.getparent().remove(extra._p)
                paragraph = cell.paragraphs[0]
                header = r < head_rows
                self._cell_format(paragraph, header=header, align=aligns[c])
                self._inline(paragraph, inline.children or [] if inline is not None else [])
                if self.office:
                    # 五号 in a cell: body size crowds a table off the page. Set per run,
                    # because a cell's paragraph style has to stay Normal for the reader to
                    # be able to restyle the document.
                    for run in _all_runs(paragraph):
                        run.font.size = self.dx.Pt(_CELL_PT)
                if header:
                    _shade(cell._tc.get_or_add_tcPr(), _HEADER_FILL, _TCPR_SEQ)
                    for run in _all_runs(paragraph):
                        run.bold = True

    def _cell_format(self, paragraph, *, header: bool, align: Optional[str]) -> None:
        if self.office:
            ppr = paragraph._p.get_or_add_pPr()
            # Cells are short; a 2-character first line inside one just looks broken, and
            # 1.5 spacing doubles the height of a data table.
            _indent(ppr, first_line_chars=0, first_line_twips=0)
            _spacing(ppr, line=_LINE_SINGLE)
        if header or align == "center":
            paragraph.alignment = self.dx.ALIGN.CENTER
        elif align == "right":
            paragraph.alignment = self.dx.ALIGN.RIGHT
        elif align == "left":
            paragraph.alignment = self.dx.ALIGN.LEFT

    # -- receipt ----------------------------------------------------------------

    def summary(self) -> str:
        return (
            f"Document: {self.paragraphs} paragraph(s), {self.headings} heading(s), "
            f"{self.tables} table(s), {self.lists} list(s), "
            f"{self.page_breaks} page break(s); style {self.style}."
        )


def _all_runs(paragraph) -> list:
    """Every run in the paragraph, including the ones living inside a `w:hyperlink`.

    `Paragraph.runs` walks the direct `w:r` children only, so a cell whose whole content is
    a link would come back with no runs at all and miss the header bolding.
    """
    from docx.text.run import Run

    return [Run(r, paragraph) for r in paragraph._p.iter(_qn("w:r"))]


def _align_of(token) -> Optional[str]:
    """`text-align:left|center|right` off a th/td, which markdown-it derives from the
    delimiter row's colons. No attribute means the column had no colon."""
    style = str((token.attrs or {}).get("style") or "")
    match = re.search(r"text-align:\s*(left|center|right)", style)
    return match.group(1) if match else None


def _next_char(children: list, index: int) -> str:
    for token in children[index + 1 :]:
        if token.type in ("text", "code_inline") and token.content:
            return token.content[0]
        if token.type == "image":
            return "["
        if token.type in ("softbreak", "hardbreak"):
            return ""
    return ""


_LINKABLE = re.compile(r"^(?:https?://|mailto:)", re.IGNORECASE)


def _linkable(href: str) -> bool:
    return bool(_LINKABLE.match(href.strip()))


# -- paths ----------------------------------------------------------------------


def _check_suffix(path: str) -> None:
    """Same reasoning as `write_spreadsheet`'s: the extension is never added for us, so a
    wrong one has to be a refusal rather than a silent rename."""
    suffix = Path(str(path)).suffix.lower()
    if suffix == ".docx":
        return
    if suffix == ".docm":
        raise ValueError(
            f"write_document cannot create macros, so .docm is not supported: {path}. "
            "Pass the same path ending in .docx instead."
        )
    if suffix == ".doc":
        raise ValueError(
            f".doc is the old binary Word format, which this tool cannot write: {path}. "
            "Pass the same path ending in .docx instead — Word and WPS both open it."
        )
    raise ValueError(
        f"path must end in .docx (got: {path}). The extension is never added for you, "
        "because the artifact panel and the approval prompt name this exact path: pass "
        'e.g. "报告.docx" or an absolute path like "C:/Users/me/Desktop/报告.docx".'
    )


# -- writing --------------------------------------------------------------------


def _save_document(document: Any, path: Path) -> None:
    """Seam: the one call that can fail deep inside python-docx/lxml."""
    document.save(str(path))


def _receipt(target: Path, label: str, summary: str, images: int) -> str:
    parts = [f"{receipt_head(target, label)}. {summary}"]
    if images:
        parts.append(
            f"Images are not embedded in this version: {images} omitted (alt text kept)."
        )
    return " ".join(parts)


def document_tools(workspace: str, roots: Optional[list] = None) -> list:
    """`write_document`, rooted like the file tools: relative paths resolve against
    `workspace` (or the primary root), absolute paths must land in one of `roots`, and a
    read-only root is refused. `roots` is held BY REFERENCE and re-read per call.

    `office_tools` composes this with `write_spreadsheet`; both are exposed together.
    """
    primary = Path(workspace).resolve()

    def write_document(path: str, markdown: str, style: str = "office") -> str:
        """Create a real Word .docx file at `path` from `markdown`. Headings, lists,
        GFM tables (with `<`/`^` merge markers), quotes, code blocks, links, `---` rules
        and `<!-- pagebreak -->` are supported. `style` is "office" or "plain"."""
        dx = _load_backends()

        # Path first, like write_spreadsheet: if the path is out of bounds, that is the
        # answer the model needs, whatever else is also wrong with the call. Nothing here
        # touches the filesystem — the directory is only created by `atomic_write`.
        _check_suffix(path)
        target, entries = prepare_target(path, roots, primary, "write_document")

        chosen = str(style or "office").strip().casefold() or "office"
        if chosen not in _STYLES:
            raise ValueError(
                f'style must be "office" or "plain" (got: {style!r}). office is a Chinese '
                "office layout (A4, 宋体/黑体, 1.5 line spacing, 2-character first-line "
                "indent); plain uses Word's own defaults."
            )
        if not isinstance(markdown, str):
            raise ValueError(
                f"markdown must be a string of Markdown text, not "
                f"{type(markdown).__name__} — e.g. "
                '"# 季度报告\\n\\n## 一、概况\\n\\n本季度……"'
            )
        if len(markdown) > _MAX_MARKDOWN_CHARS:
            raise ValueError(
                f"markdown is {len(markdown)} characters, over the "
                f"{_MAX_MARKDOWN_CHARS} limit — split the document across files, or "
                "deliver the bulk of the data as a spreadsheet with write_spreadsheet."
            )
        source = _preprocess(markdown)
        if not source.strip():
            raise ValueError(
                "markdown is empty; pass the document's content, e.g. "
                '"# 季度报告\\n\\n## 一、概况\\n\\n本季度……"'
            )

        parser = dx.MarkdownIt("commonmark", {"html": False}).enable(
            ["table", "strikethrough"]
        )
        writer = _Writer(dx, chosen)
        writer.build(parser.parse(source))

        atomic_write(target, lambda p: _save_document(writer.doc, p), app="Word")

        try:
            return _receipt(
                target, root_label(target, entries), writer.summary(), writer.images
            )
        except Exception:
            # The file is on disk. Everything past the write is cosmetics, and the engine
            # turns a raised tool into `{"error": …}` — which would send the model back to
            # rewrite the file, or make it tell the user the document does not exist.
            return f"Wrote {target}"

    write_document.__name__ = "write_document"
    write_document.__aisuite_tool_metadata__ = ai.ToolMetadata(
        name="write_document",
        category="filesystem",
        risk_level="medium",
        capabilities=["write_file"],
        requires_approval=True,
    )
    write_document.__coworker_schema__ = _SCHEMA
    return [write_document]
