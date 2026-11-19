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
