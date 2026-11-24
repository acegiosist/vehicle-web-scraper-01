"""Excel export: the .xlsx is a valid zip of SpreadsheetML that keeps every table column."""
import xml.etree.ElementTree as ET
import zipfile

from vehicle_scraper import cli
from vehicle_scraper.models import VehicleRecord
from vehicle_scraper.storage import Storage
from vehicle_scraper.xlsx import col_letter, write_xlsx

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _sheet(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        for part in ("[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml"):
            ET.fromstring(z.read(part))            # every part is well-formed XML
        return ET.fromstring(z.read("xl/worksheets/sheet1.xml"))


def _cells(sheet):
    """{ref: (type, text)} for every written cell."""
    out = {}
    for c in sheet.iter(f"{{{NS['m']}}}c"):
        text = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t")) or (c.findtext("m:v", namespaces=NS))
        out[c.get("r")] = (c.get("t"), text)
    return out


def test_col_letter():
    assert [col_letter(i) for i in (0, 25, 26, 51, 52, 701, 702)] == ["A", "Z", "AA", "AZ", "BA", "ZZ", "AAA"]


def test_write_xlsx_types_and_escaping(tmp_path):
    path = tmp_path / "t.xlsx"
    rows = [["<a & b>", 3, 2.5, True, None, "=HYPERLINK(\"x\")", "bad\x01char", " pad "]]
    assert write_xlsx(path, list("ABCDEFGH"), rows, sheet_name="vehicles") == 1
    sheet = _sheet(path)
    cells = _cells(sheet)
    assert cells["A2"] == ("inlineStr", "<a & b>")
    assert cells["B2"] == (None, "3") and cells["C2"] == (None, "2.5")
    assert cells["D2"] == ("b", "1")
    assert "E2" not in cells                                   # None -> empty cell
    assert cells["F2"] == ("inlineStr", '=HYPERLINK("x")')      # text, never a formula
    assert not list(sheet.iter(f"{{{NS['m']}}}f"))
    assert cells["G2"][1] == "badchar"                          # control char stripped
    assert cells["H2"][1] == " pad "
    assert sheet.find("m:autoFilter", NS).get("ref") == "A1:H2"
    assert sheet.find(".//m:pane", NS).get("state") == "frozen"


def test_storage_export_xlsx_has_all_columns(cfg, tmp_path, monkeypatch):
    store = Storage(cfg.db_path)
    store.conn.execute('ALTER TABLE vehicles ADD COLUMN "legacy_col"')   # a column outside the schema
    store.save(VehicleRecord(source_site="s", source_url="https://x/1", listing_id="1", make="Mazda", abs=True))
    store.conn.execute("UPDATE vehicles SET legacy_col='kept'")
    store.conn.commit()
    columns = [r[1] for r in store.conn.execute("PRAGMA table_info(vehicles)")]
    assert "parse_warnings" in columns
    columns.remove("parse_warnings")                                    # left out of the Excel file
    store.close()

    monkeypatch.setattr(cli, "settings", cfg)
    out = tmp_path / "v.xlsx"
    assert cli.main(["export", "--format", "xlsx", "--out", str(out)]) == 0
    cells = _cells(_sheet(out))
    header = [cells[f"{col_letter(i)}1"][1] for i in range(len(columns))]
    assert header == columns and header[-1] == "legacy_col"
    assert f"{col_letter(len(columns))}1" not in cells                  # no extra column
    assert "parse_warnings" not in header
    values = {h: cells.get(f"{col_letter(i)}2", (None, None)) for i, h in enumerate(header)}
    assert values["make"] == ("inlineStr", "Mazda")
    assert values["abs"] == ("b", "1")
    assert values["legacy_col"][1] == "kept"


def test_workbook_round_trip_with_lists(tmp_path):
    from vehicle_scraper.xlsx import Sheet, read_sheet, write_workbook
    path = tmp_path / "w.xlsx"
    write_workbook(path, [Sheet("Casos", ["id", "decisión"], [[1, None], [2, "aprobar"]], lists={1: ["aprobar", "rechazar"]}),
                          Sheet("Instrucciones", ["a"], [["texto libre"]], table=False)])
    with zipfile.ZipFile(path) as z:
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        assert sheet.find(".//m:dataValidation", NS).get("sqref") == "B2:B3"
        assert ET.fromstring(z.read("xl/worksheets/sheet2.xml")).find("m:autoFilter", NS) is None
    assert read_sheet(path, "Casos") == [["id", "decisión"], [1], [2, "aprobar"]]
    assert read_sheet(path, "Instrucciones") == [["a"], ["texto libre"]]


def test_read_sheet_as_excel_saves_it(tmp_path):
    """Excel re-saves with shared strings, sparse cells and sheet paths of its own."""
    from vehicle_scraper.xlsx import read_sheet
    path = tmp_path / "excel.xlsx"
    m = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {m} xmlns:r="{rel_ns}"><sheets>'
                                      '<sheet name="Casos" sheetId="1" r:id="rId7"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{pkg_ns}"><Relationship Id="rId7" '
                                                 'Type="x" Target="/xl/worksheets/hoja1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {m}><si><t>id</t></si><si><t>corregir</t></si>'
                                           '<si><r><t>Chan</t></r><r><t>gan</t></r></si></sst>')
        z.writestr("xl/worksheets/hoja1.xml", f'<worksheet {m}><sheetData>'
                                              '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
                                              '<row r="3"><c r="A3"><v>12</v></c><c r="C3" t="s"><v>1</v></c>'
                                              '<c r="D3" t="s"><v>2</v></c><c r="E3"><v>1.5</v></c>'
                                              '<c r="F3" t="b"><v>1</v></c><c r="G3" t="str"><f>A3</f><v>12</v></c>'
                                              '</row></sheetData></worksheet>')
    assert read_sheet(path, "Casos") == [["id"], [], [12, None, "corregir", "Changan", 1.5, True, "12"]]
