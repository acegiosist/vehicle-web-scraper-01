"""Minimal .xlsx writer and reader (standard library only: zipfile + XML).

``write_xlsx`` writes one sheet with a bold, frozen header row and an autofilter;
``write_workbook`` writes several, optionally with drop-down lists on some columns. Every
string is written as an inline string, never as a formula, so scraped text such as
"=HYPERLINK(...)" can't run as a formula when the file is opened in Excel.

``read_sheet`` reads a sheet back by name, including files Excel re-saved (shared strings,
sparse cells); formulas give their cached value.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from xml.sax.saxutils import escape

MAX_ROWS = 1_048_576          # Excel's row limit (including the header)
MAX_CELL_CHARS = 32_767       # Excel's per-cell text limit
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")

_CT_SHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{sheets}
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_REL_SHEET = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{sheets}
<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

# cellXfs: 0 = default, 1 = bold (header)
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def col_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s, n = "", index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _text(value: str) -> str:
    value = _ILLEGAL_XML.sub("", value)[:MAX_CELL_CHARS]
    space = ' xml:space="preserve"' if value != value.strip() else ""
    return f"<t{space}>{escape(value)}</t>"


def _cell(ref: str, value, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    if isinstance(value, bool):
        return f'<c r="{ref}"{s} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)) and not (isinstance(value, float) and not math.isfinite(value)):
        return f'<c r="{ref}"{s}><v>{value!r}</v></c>'
    return f'<c r="{ref}"{s} t="inlineStr"><is>{_text(str(value))}</is></c>'


@dataclass
class Sheet:
    """One worksheet. ``lists``: column index -> allowed values (an Excel drop-down);
    ``widths``: column index -> width, overriding the automatic one; ``table``: frozen header
    and autofilter (off for a free-text sheet such as instructions)."""
    name: str
    headers: Sequence[str]
    rows: list
    lists: dict = field(default_factory=dict)
    widths: dict = field(default_factory=dict)
    table: bool = True


def _sheet_xml(sheet: Sheet) -> str:
    rows, headers = sheet.rows, sheet.headers
    last = f"{col_letter(max(len(headers) - 1, 0))}{len(rows) + 1}"
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, v in enumerate(row):
            if v is not None and i < len(widths):
                widths[i] = max(widths[i], len(str(v)))
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" '
                   f'width="{sheet.widths.get(i, min(max(w, 6) + 2, 60))}" customWidth="1"/>'
                   for i, w in enumerate(widths))
    view = ('<sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
            '</sheetView></sheetViews>') if sheet.table else ""
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last}"/>{view}<cols>{cols}</cols><sheetData>',
        '<row r="1">' + "".join(_cell(f"{col_letter(i)}1", h, style=1) for i, h in enumerate(headers)) + "</row>",
    ]
    for r, row in enumerate(rows, start=2):
        cells = "".join(_cell(f"{col_letter(i)}{r}", v) for i, v in enumerate(row) if v is not None)
        parts.append(f'<row r="{r}">{cells}</row>')
    parts.append("</sheetData>")
    if sheet.table:
        parts.append(f'<autoFilter ref="A1:{last}"/>')
    if sheet.lists and rows:
        dv = []
        for i, values in sorted(sheet.lists.items()):
            joined = ",".join(values)
            if len(joined) > 255:                       # Excel's limit for an inline list
                continue
            ref = f"{col_letter(i)}2:{col_letter(i)}{len(rows) + 1}"
            dv.append(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{ref}">'
                      f'<formula1>"{escape(joined)}"</formula1></dataValidation>')
        if dv:
            parts.append(f'<dataValidations count="{len(dv)}">{"".join(dv)}</dataValidations>')
    parts.append("</worksheet>")
    return "".join(parts)


def write_workbook(path: Path, sheets: Sequence[Sheet]) -> None:
    """Write several sheets to one .xlsx (the first one opens on top)."""
    names = []
    for s in sheets:
        if len(s.rows) + 1 > MAX_ROWS:
            raise ValueError(f"{len(s.rows)} rows exceed Excel's limit of {MAX_ROWS - 1}")
        names.append(_INVALID_SHEET_CHARS.sub("_", s.name)[:31] or f"Sheet{len(names) + 1}")
    sheet_tags, defined = [], []
    for n, (s, name) in enumerate(zip(sheets, names), start=1):
        sheet_tags.append(f'<sheet name="{escape(name, {chr(34): "&quot;"})}" sheetId="{n}" r:id="rId{n}"/>')
        if s.table:
            last = f"{col_letter(max(len(s.headers) - 1, 0))}{len(s.rows) + 1}"
            quoted = "'" + name.replace("'", "''") + "'"
            abs_ref = "$" + re.sub(r"(\d+)$", r"$\1", last)
            defined.append(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{n - 1}" hidden="1">'
                           f'{escape(quoted)}!$A$1:{abs_ref}</definedName>')
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(sheet_tags)}</sheets>'
        + (f'<definedNames>{"".join(defined)}</definedNames>' if defined else "")
        + '</workbook>'
    )
    n = len(sheets)
    content_types = _CONTENT_TYPES.format(sheets="\n".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="{_CT_SHEET}"/>' for i in range(1, n + 1)))
    rels = _WORKBOOK_RELS.format(sheets="\n".join(
        f'<Relationship Id="rId{i}" Type="{_REL_SHEET}" Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/styles.xml", _STYLES)
        for i, s in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(s))


def write_xlsx(path: Path, headers: Sequence[str], rows: Iterable[Sequence], sheet_name: str = "Sheet1") -> int:
    """Write `headers` + `rows` to one sheet. None values become empty cells. Returns the row count."""
    rows = list(rows)
    if len(rows) + 1 > MAX_ROWS:
        raise ValueError(f"{len(rows)} rows exceed Excel's limit of {MAX_ROWS - 1}; export by --site or as CSV")
    write_workbook(path, [Sheet(sheet_name, headers, rows)])
    return len(rows)


# --- reading --------------------------------------------------------------------------------
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_sheet(path: Path, name: str) -> list[list]:
    """Rows of sheet ``name`` (header included) as lists; empty cells are None. Numbers come
    back as int when whole, else float; booleans as bool; everything else as str."""
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{_PKG_RELS}Relationship")}
        rid = next((s.get(f"{_RNS}id") for s in wb.iter(f"{_NS}sheet") if s.get("name") == name), None)
        if rid is None:
            raise KeyError(f"{path} has no sheet named {name!r}")
        target = targets[rid].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{_NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
        root = ET.fromstring(z.read(target))
    out: list[list] = []
    for row in root.iter(f"{_NS}row"):
        r = int(row.get("r") or len(out) + 1)
        while len(out) < r - 1:
            out.append([])
        cells: list = []
        for c in row.iter(f"{_NS}c"):
            i = _col_index(c.get("r")) if c.get("r") else len(cells)
            t, v = c.get("t"), c.findtext(f"{_NS}v")
            if t == "inlineStr":
                value = "".join(x.text or "" for x in c.iter(f"{_NS}t"))
            elif t == "s":
                value = shared[int(v)] if v is not None else None
            elif t == "b":
                value = v == "1"
            elif t in ("str", "e"):
                value = v
            elif v is None:
                value = None
            else:
                f = float(v)
                value = int(f) if f.is_integer() else f
            while len(cells) <= i:
                cells.append(None)
            cells[i] = value
        out.append(cells)
    return out
