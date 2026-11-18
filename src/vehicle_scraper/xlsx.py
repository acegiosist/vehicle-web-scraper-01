"""Minimal .xlsx writer (standard library only: zipfile + XML).

Writes a single sheet with a bold, frozen header row and an autofilter. Every string is
written as an inline string, never as a formula, so scraped text such as "=HYPERLINK(...)"
can't run as a formula when the file is opened in Excel.
"""
from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path
from typing import Iterable, Sequence
from xml.sax.saxutils import escape

MAX_ROWS = 1_048_576          # Excel's row limit (including the header)
MAX_CELL_CHARS = 32_767       # Excel's per-cell text limit
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
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


def write_xlsx(path: Path, headers: Sequence[str], rows: Iterable[Sequence], sheet_name: str = "Sheet1") -> int:
    """Write `headers` + `rows` to one sheet. None values become empty cells. Returns the row count."""
    rows = list(rows)
    if len(rows) + 1 > MAX_ROWS:
        raise ValueError(f"{len(rows)} rows exceed Excel's limit of {MAX_ROWS - 1}; export by --site or as CSV")
    sheet_name = _INVALID_SHEET_CHARS.sub("_", sheet_name)[:31] or "Sheet1"
    last = f"{col_letter(max(len(headers) - 1, 0))}{len(rows) + 1}"

    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, v in enumerate(row):
            if v is not None:
                widths[i] = max(widths[i], len(str(v)))
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{min(max(w, 6) + 2, 60)}" customWidth="1"/>'
                   for i, w in enumerate(widths))

    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        '</sheetView></sheetViews>'
        f'<cols>{cols}</cols><sheetData>',
        '<row r="1">' + "".join(_cell(f"{col_letter(i)}1", h, style=1) for i, h in enumerate(headers)) + "</row>",
    ]
    for r, row in enumerate(rows, start=2):
        cells = "".join(_cell(f"{col_letter(i)}{r}", v) for i, v in enumerate(row) if v is not None)
        parts.append(f'<row r="{r}">{cells}</row>')
    parts.append(f'</sheetData><autoFilter ref="A1:{last}"/></worksheet>')

    quoted = "'" + sheet_name.replace("'", "''") + "'"
    abs_ref = "$" + re.sub(r"(\d+)$", r"$\1", last)
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name, {chr(34): "&quot;"})}" sheetId="1" r:id="rId1"/></sheets>'
        '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
        f'{escape(quoted)}!$A$1:{abs_ref}</definedName></definedNames>'
        '</workbook>'
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr("xl/worksheets/sheet1.xml", "".join(parts))
    return len(rows)
