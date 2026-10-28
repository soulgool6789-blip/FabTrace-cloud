"""Behavioral checks of the actual XLSX download, using only the Python stdlib."""

from dataclasses import dataclass
import datetime as dt
import importlib
import io
import json
import posixpath
import re
from xml.etree import ElementTree as ET
import zipfile

import pytest
from sqlalchemy import select

from conftest import BADGES, TEST_PIN, TEST_SECRET


NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EMPLOYEE_COLUMNS = ["badge", "name", "role", "active", "created_at"]
TABLES = {
    "Employees": ("main", "Employee"),
    "Items": ("main", "Item"),
    "Inspections": ("main", "Inspection"),
    "Reworks": ("main", "Rework"),
    "Audit events": ("main", "Audit"),
    "Projects": ("tracking", "Project"),
    "Subprojects": ("tracking", "Subproject"),
    "Spool plans": ("tracking", "SpoolPlan"),
    "Weld templates": ("tracking", "RequirementTemplate"),
    "Welds": ("tracking", "Weld"),
    "Requirements": ("tracking", "WeldRequirement"),
    "Evidence": ("tracking", "RequirementEvidence"),
    "Reviews": ("tracking", "RequirementReview"),
    "Weld work": ("tracking", "WeldWork"),
    "Weld repairs": ("tracking", "WeldRepair"),
    "Holds": ("tracking", "TrackingHold"),
    "Process events": ("production", "SpoolProcessEvent"),
}
PROCESS_REPORTS = ["Process visits", "Process totals"]


@dataclass
class Cell:
    value: object
    kind: str
    style: int


def decode_excel_text(value):
    # OOXML escapes XML-forbidden characters; decode once so a source literal
    # such as _x0001_ (escaped as _x005F_x0001_) stays literal.
    return re.sub(r"_x([0-9A-Fa-f]{4})_", lambda match: chr(int(match.group(1), 16)), value)


class Workbook:
    def __init__(self, payload):
        self.sheets = {}
        self.formulas = []
        self.date_styles = set()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            assert archive.testzip() is None
            self.xml = b"\n".join(archive.read(name) for name in archive.namelist() if name.endswith(".xml"))
            book = ET.fromstring(archive.read("xl/workbook.xml"))
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {row.attrib["Id"]: row.attrib["Target"] for row in relationships}
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared = ["".join(row.itertext()) for row in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
            styles = ET.fromstring(archive.read("xl/styles.xml"))
            formats = {
                int(row.attrib["numFmtId"]): row.attrib["formatCode"]
                for row in styles.findall("s:numFmts/s:numFmt", NS)
            }
            for index, row in enumerate(styles.findall("s:cellXfs/s:xf", NS)):
                format_id = int(row.attrib.get("numFmtId", "0"))
                code = formats.get(format_id, "").lower()
                if format_id in (*range(14, 23), *range(45, 48)) or ("yy" in code and "dd" in code):
                    self.date_styles.add(index)
            for sheet in book.findall("s:sheets/s:sheet", NS):
                target = targets[sheet.attrib[f"{{{REL_NS}}}id"]]
                path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
                document = ET.fromstring(archive.read(path))
                self.formulas.extend(document.findall(".//s:f", NS))
                rows = []
                for row in document.findall("s:sheetData/s:row", NS):
                    cells = {}
                    for cell in row.findall("s:c", NS):
                        letters = "".join(char for char in cell.attrib["r"] if char.isalpha())
                        column = 0
                        for letter in letters:
                            column = column * 26 + ord(letter) - ord("A") + 1
                        kind = cell.attrib.get("t", "n")
                        value = cell.findtext("s:v", default=None, namespaces=NS)
                        if kind == "inlineStr":
                            value = decode_excel_text("".join(node.text or "" for node in cell.findall("s:is//s:t", NS)))
                        elif kind == "s":
                            value = decode_excel_text(shared[int(value)])
                        elif kind == "b":
                            value = value == "1"
                        elif kind == "n" and value is not None:
                            value = float(value) if any(char in value.lower() for char in ".e") else int(value)
                        cells[column] = Cell(value, kind, int(cell.attrib.get("s", "0")))
                    rows.append(cells)
                self.sheets[sheet.attrib["name"]] = rows

    def headers(self, name):
        row = self.sheets[name][0]
        return [row[index].value for index in sorted(row)]

    def records(self, name):
        headers = self.headers(name)
        return [
            {header: row.get(index, Cell(None, "n", 0)) for index, header in enumerate(headers, 1)}
            for row in self.sheets[name][1:]
        ]


def download(api):
    response = api.get("/api/exports/excel")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].split(";")[0] == MIME
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition and ".xlsx" in disposition
    return response, Workbook(response.content)


def models():
    return {name: getattr(importlib.import_module(module), model) for name, (module, model) in TABLES.items()}


def snapshot(api):
    result = {}
    with api.session_factory() as session:
        for name, model in models().items():
            columns = EMPLOYEE_COLUMNS if name == "Employees" else list(model.__table__.columns.keys())
            result[name] = {
                "columns": columns,
                "keys": [column.name for column in model.__table__.primary_key.columns],
                "rows": [{key: getattr(row, key) for key in columns} for row in session.scalars(select(model)).all()],
            }
    return result


@pytest.fixture
def populated_export(api):
    app = api.application
    tracking = importlib.import_module("tracking")
    when = dt.datetime(2024, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)
    with api.session_factory() as session:
        first_employee = session.get(app.Employee, BADGES["admin"])
        session.add(app.Employee(
            badge="000007", name="=SUM(1,2)", role="welder", active=False,
            pin_hash=first_employee.pin_hash, created_at=when,
        ))
        session.add_all([
            app.Item(
                id="000042", description="=1+1", kind="Part", project="Legacy project",
                google_part_number="0000000123", drawing="+SUM(1,2)", location="-1+2",
                handler=BADGES["welder"], welds_required=7, welds_done=3,
                dimensional="Pass", dimension_at=when, on_hold=True, created_at=when,
            ),
            app.Item(
                id="EXPORT-ASSEMBLY", description="Export parent", kind="Assembly",
                location="Test bay", handler=BADGES["welder"],
            ),
            app.Item(
                id="EXPORT-SPOOL", description="Unicode α < & > 😀\r\nCRLF\rCR\nLF; literal _x0001_; control \x01", kind="Spool",
                location="Test bay", handler=BADGES["welder"], welds_required=1,
            ),
        ])
        session.add(tracking.Project(id="PRJ-EXPORT", name="Export project", created_by=BADGES["admin"], created_at=when))
        session.flush()
        session.add(tracking.Subproject(
            id="SUB-EXPORT", project_id="PRJ-EXPORT", name="Export package", created_by=BADGES["admin"],
        ))
        session.add(tracking.RequirementTemplate(
            id="TPL-EXPORT", code="EXPORT-PROFILE", name="Export profile", revision=1,
            requirements=[{"code": "VT", "label": "Visual & α", "allow_na": False}],
            required_operations=["root", "fill_cap"], created_by=BADGES["admin"],
        ))
        session.flush()
        session.add(tracking.SpoolPlan(
            item_id="EXPORT-SPOOL", project_id="PRJ-EXPORT", subproject_id="SUB-EXPORT",
            assembly_id="EXPORT-ASSEMBLY", planned_welds=1, drawing_revision="0003",
            due_date="2024-03-01", notes="Controlled export test", version=2, created_by=BADGES["admin"],
        ))
        session.add(tracking.Weld(
            id="WLD-EXPORT", item_id="EXPORT-SPOOL", number="0009", description="@SUM(1,2)",
            component_a="PIECE-A", heat_a="000011", mtr_a="MTR-A",
            component_b="PIECE-B", heat_b="000012", mtr_b="MTR-B",
            wps="TEST-WPS", wps_revision="A", template_id="TPL-EXPORT",
            required_operations=["root", "fill_cap"], cycle=3, version=5, created_by=BADGES["admin"],
        ))
        session.flush()
        req = tracking.WeldRequirement(
            item_id="EXPORT-SPOOL", weld_id="WLD-EXPORT", code="VT", label="Visual examination",
            stage="after_welding", check_kind="welding_complete", cycle=3,
            template_id="TPL-EXPORT", created_by=BADGES["admin"],
        )
        session.add(req)
        session.flush()
        evidence = [tracking.RequirementEvidence(
            requirement_id=req.id, cycle=1 if index < 60 else 2, reference=f"REPORT-{index:04}",
            notes=f"Historical evidence {index}", result="pass", actor=BADGES["welder"], at=when,
        ) for index in range(113)]
        session.add_all(evidence)
        session.flush()
        session.add_all(tracking.RequirementReview(
            requirement_id=req.id, evidence_id=row.id, cycle=row.cycle, decision="accepted",
            notes=f"Historical review {index}", actor=BADGES["inspector"], at=when,
        ) for index, row in enumerate(evidence[:111]))
        session.add_all(tracking.WeldWork(
            weld_id="WLD-EXPORT", cycle=cycle, operation=operation,
            notes="Historical operation", actor=BADGES["welder"], at=when,
        ) for cycle in (1, 2) for operation in ("fitup", "root", "fill_cap", "complete"))
        session.add_all(tracking.WeldRepair(
            weld_id="WLD-EXPORT", cycle=cycle, reason=f"Repair cycle {cycle}",
            opened_by=BADGES["inspector"], opened_at=when,
        ) for cycle in (2, 3))
        session.add_all([
            tracking.TrackingHold(
                item_id="EXPORT-SPOOL", weld_id="WLD-EXPORT", reason="Closed hold retained",
                opened_by=BADGES["inspector"], opened_at=when, closed_at=when,
                closed_by=BADGES["inspector"], close_notes="Historical disposition",
            ),
            tracking.TrackingHold(item_id="EXPORT-SPOOL", reason="Open hold", opened_by=BADGES["inspector"]),
        ])
        session.add_all(app.Inspection(
            id=9_007_199_254_740_993 + index,
            item_id="000042", kind="Dimensional" if index % 2 else "Weld", result="Pass",
            inspector=BADGES["inspector"], report=f"LEGACY-REPORT-{index:04}",
            measurements=f"Legacy observation {index}", at=when,
        ) for index in range(106))
        session.add_all([
            app.Rework(item_id="000042", kind="Weld", reason="Previous repair", assigned=BADGES["welder"],
                       opened_at=when, closed_at=when, closed_by=BADGES["inspector"], close_notes="Repair accepted"),
            app.Rework(item_id="000042", kind="Dimensional", reason="Open correction", assigned=BADGES["welder"]),
        ])
        session.add_all(app.Audit(
            item_id="000042", actor=BADGES["admin"], event="EXPORT_HISTORY",
            details={"sequence": index, "text": "=1+1 < & α 😀", "nested": {"ids": ["001", "002"], "flags": [True, False, None]}},
            at=when,
        ) for index in range(130))
        session.commit()
    return snapshot(api)


@pytest.mark.parametrize("role,status", [(None, 401), ("welder", 403), ("handler", 403), ("inspector", 403), ("supervisor", 403)])
def test_full_database_export_requires_an_administrator(api, role, status):
    response = api.get("/api/exports/excel", role=role)
    assert response.status_code == status
    assert not response.content.startswith(b"PK")


def test_export_contains_every_business_record_and_column(api, populated_export, tmp_path):
    response, workbook = download(api)
    assert list(workbook.sheets) == ["Export info", *TABLES, *PROCESS_REPORTS]
    assert workbook.formulas == []
    for name, expected in populated_export.items():
        assert workbook.headers(name) == expected["columns"]
        records = workbook.records(name)
        assert len(records) == len(expected["rows"]), name
        actual = {tuple(str(row[key].value) for key in expected["keys"]): row for row in records}
        for original in expected["rows"]:
            row = actual[tuple(str(original[key]) for key in expected["keys"])]
            for key, value in original.items():
                cell = row[key]
                if value is None:
                    assert cell.value in (None, ""), (name, key)
                elif isinstance(value, bool):
                    assert cell.kind == "b" and cell.value is value, (name, key)
                elif isinstance(value, dt.datetime):
                    normalized = value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)
                    serial = (normalized - dt.datetime(1899, 12, 30, tzinfo=dt.timezone.utc)).total_seconds() / 86400
                    assert cell.kind == "n" and cell.style in workbook.date_styles, (name, key)
                    assert cell.value == pytest.approx(serial, rel=0, abs=1e-8), (name, key)
                elif isinstance(value, (int, float)):
                    if key == "id" or key.endswith("_id"):
                        assert cell.kind in ("inlineStr", "s") and cell.value == str(value), (name, key)
                    else:
                        assert cell.kind == "n" and cell.value == value, (name, key)
                elif isinstance(value, (list, dict)):
                    assert cell.kind in ("inlineStr", "s") and json.loads(cell.value) == value, (name, key)
                else:
                    assert cell.kind in ("inlineStr", "s") and cell.value == value, (name, key)
    assert len(workbook.records("Audit events")) == 130
    assert len(workbook.records("Inspections")) == 106
    assert len(workbook.records("Evidence")) == 113
    assert len(workbook.records("Reviews")) == 111
    manifest = workbook.records("Export info")
    counts = {row["entry"].value: row["value"].value for row in manifest if row["section"].value == "Sheet rows"}
    sources = {row["entry"].value: row["value"].value for row in manifest if row["section"].value == "Source table"}
    assert counts == {**{name: len(expected["rows"]) for name, expected in populated_export.items()},
                      **{name: 0 for name in PROCESS_REPORTS}}
    assert sources == {**{name: model.__tablename__ for name, model in models().items()},
                       **{name: "derived:tracking_process_events" for name in PROCESS_REPORTS}}
    # Downloading must not edit business records or silently log into the data snapshot.
    assert snapshot(api) == populated_export
    assert "pin_hash" not in workbook.headers("Employees")
    with api.session_factory() as session:
        for employee in session.scalars(select(api.application.Employee)).all():
            assert employee.pin_hash.encode() not in workbook.xml
    assert TEST_PIN.encode() not in workbook.xml and TEST_SECRET.encode() not in workbook.xml
    # A disposable synthetic artifact is useful for an independent reader check.
    (tmp_path / "synthetic-export.xlsx").write_bytes(response.content)


def test_empty_tables_keep_their_column_headers(api):
    _, workbook = download(api)
    assert list(workbook.sheets) == ["Export info", *TABLES, *PROCESS_REPORTS]
    for name, model in models().items():
        expected_columns = EMPLOYEE_COLUMNS if name == "Employees" else list(model.__table__.columns.keys())
        assert workbook.headers(name) == expected_columns
        assert len(workbook.records(name)) == (len(BADGES) if name == "Employees" else 0)
    exporter = importlib.import_module("exports")
    assert workbook.headers("Process visits") == list(exporter.PROCESS_VISIT_COLUMNS)
    assert workbook.headers("Process totals") == list(exporter.PROCESS_TOTAL_COLUMNS)
    assert all(not workbook.records(name) for name in PROCESS_REPORTS)


def test_process_export_retains_events_and_reports_repeated_visits_and_pauses(api, monkeypatch):
    from tracking_helpers import make_spool

    production = importlib.import_module("production")
    exporter = importlib.import_module("exports")
    item_id = make_spool(api, item_id="000042")
    make_spool(api, item_id="UNSTARTED-SPOOL")
    start = dt.datetime(2024, 2, 1, 8, tzinfo=dt.timezone.utc)
    actions = [
        (0, {"action": "start", "process_key": "welding"}),
        (2, {"action": "pause", "notes": "Waiting for a controlled inspection"}),
        (3, {"action": "resume"}),
        (4, {"action": "move", "process_key": "fit_up"}),
        (5, {"action": "move", "process_key": "welding", "notes": "Repair visit"}),
    ]
    for version, (hour, action) in enumerate(actions):
        monkeypatch.setattr(production, "utcnow", lambda hour=hour: start + dt.timedelta(hours=hour))
        response = api.post(f"/api/tracking/spools/{item_id}/process",
                            {**action, "expected_version": version}, role="welder")
        assert response.status_code == 201, response.text
    as_of = start + dt.timedelta(hours=6)
    monkeypatch.setattr(exporter, "utcnow", lambda: as_of)
    before = snapshot(api)
    _, workbook = download(api)
    assert snapshot(api) == before
    assert len(workbook.records("Process events")) == 5
    assert workbook.records("Process events")[1]["notes"].value == actions[1][1]["notes"]
    visits = workbook.records("Process visits")
    assert len(visits) == 3
    assert [row["visit_id"].value for row in visits] == ["1", "4", "5"]
    assert [row["elapsed_hours"].value for row in visits] == [4, 1, 1]
    assert [row["active_hours"].value for row in visits] == [3, 1, 1]
    assert [row["paused_hours"].value for row in visits] == [1, 0, 0]
    assert visits[-1]["ended_at"].value is None
    assert visits[-1]["status"].value == "running"
    for row in visits:
        assert row["item_id"].value == "000042" and row["item_id"].kind == "inlineStr"
        assert row["project_id"].value == "TEST-PROJECT"
        assert row["started_at"].style in workbook.date_styles
        assert row["as_of"].style in workbook.date_styles
        assert row["elapsed_seconds"].kind == "n"
        assert row["elapsed_seconds"].value == row["active_seconds"].value + row["paused_seconds"].value
    totals = {row["process_key"].value: row for row in workbook.records("Process totals")}
    assert set(totals) == {"welding", "fit_up"}
    assert totals["welding"]["visits"].value == 2
    assert totals["welding"]["elapsed_hours"].value == 5
    assert totals["welding"]["active_hours"].value == 4
    assert totals["welding"]["paused_hours"].value == 1
    assert totals["fit_up"]["elapsed_hours"].value == 1
    manifest = workbook.records("Export info")
    counts = {row["entry"].value: row["value"].value for row in manifest if row["section"].value == "Sheet rows"}
    assert counts["Process events"] == 5 and counts["Process visits"] == 3 and counts["Process totals"] == 2


def test_long_text_and_json_overflow_can_be_reconstructed_without_loss(api):
    app = api.application
    long_text = "=Full retained text: " + "α<&>😀Z\n" * 12000
    with api.session_factory() as session:
        session.add(app.Item(id="OVERFLOW-ITEM", description="Overflow fixture", location="Local bay", handler=BADGES["welder"]))
        session.flush()
        rework = app.Rework(item_id="OVERFLOW-ITEM", kind="Weld", reason=long_text, assigned=BADGES["welder"])
        audit = app.Audit(item_id="OVERFLOW-ITEM", actor=BADGES["admin"], event="LONG_TEXT", details={"full_text": long_text})
        session.add_all([rework, audit])
        session.commit()
        record_ids = {"Reworks": rework.id, "Audit events": audit.id}
    _, workbook = download(api)
    assert workbook.formulas == []
    chunks = workbook.records("Text overflow")
    for sheet, column, table in (("Reworks", "reason", "reworks"), ("Audit events", "details", "audit_events")):
        source = workbook.records(sheet)[0]
        parts = [row for row in chunks if row["source_sheet"].value == sheet and row["column"].value == column]
        assert len(parts) > 1
        parts.sort(key=lambda row: row["chunk_index"].value)
        assert [row["chunk_index"].value for row in parts] == list(range(1, len(parts) + 1))
        assert all(row["chunk_count"].value == len(parts) for row in parts)
        assert all(row["source_table"].value == table and row["row_number"].value == 2 for row in parts)
        assert all(json.loads(row["row_id"].value) == {"id": record_ids[sheet]} for row in parts)
        assert parts[0]["overflow_id"].value in source[column].value
        reconstructed = "".join(row["text"].value for row in parts)
        assert (json.loads(reconstructed)["full_text"] if column == "details" else reconstructed) == long_text
        assert all(row["text"].kind in ("inlineStr", "s") for row in parts)
        assert all(len(row["text"].value.encode("utf-16-le")) // 2 <= 32767 for row in parts)


def test_excel_row_limit_creates_continuations_without_dropping_records(api, monkeypatch):
    exporter = importlib.import_module("exports")
    monkeypatch.setattr(exporter, "EXCEL_MAX_ROWS", 7)
    with api.session_factory() as session:
        session.add_all(api.application.Audit(
            item_id=None, actor=BADGES["admin"], event="CONTINUATION", details={"sequence": index},
        ) for index in range(15))
        session.commit()
    _, workbook = download(api)
    names = [name for name in workbook.sheets if name == "Audit events" or name.startswith("Audit events ")]
    assert names == ["Audit events", "Audit events 2", "Audit events 3"]
    assert [len(workbook.records(name)) for name in names] == [6, 6, 3]
    assert all(workbook.headers(name) == workbook.headers("Audit events") for name in names)
    records = [row for name in names for row in workbook.records(name)]
    assert sorted(json.loads(row["details"].value)["sequence"] for row in records) == list(range(15))
    assert len({row["id"].value for row in records}) == 15
    assert all(len(rows) <= 7 for rows in workbook.sheets.values())
