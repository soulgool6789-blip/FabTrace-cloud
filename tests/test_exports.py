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
EXCLUDED_COLUMNS = {"Packet issues": {"print_html"}}
TABLES = {
    "Employees": ("main", "Employee"),
    "Employee access states": ("administration", "EmployeeAccessState"),
    "Items": ("main", "Item"),
    "Inspections": ("main", "Inspection"),
    "Reworks": ("main", "Rework"),
    "Audit events": ("main", "Audit"),
    "Item transfer states": ("transfers", "ItemTransferState"),
    "Transfer locations": ("transfers", "TransferLocation"),
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
    "Flow plans": ("flow", "FlowPlan"),
    "Flow events": ("flow", "FlowEvent"),
    "Flow exceptions": ("flow", "FlowException"),
    "Component links": ("flow", "ComponentLink"),
    "Spool parts plans": ("parts", "SpoolPartsPlan"),
    "Spool part lines": ("parts", "PartLine"),
    "Part allocations": ("parts", "PartAllocation"),
    "Spool parts events": ("parts", "PartEvent"),
    "Quality workspaces": ("quality", "QualityWorkspace"),
    "Quality requirements": ("quality", "QualityRequirement"),
    "Quality documents": ("quality", "QualityDocument"),
    "Quality evidence": ("quality", "QualityEvidence"),
    "Quality actions": ("quality", "QualityAction"),
    "Quality reviews": ("quality", "QualityReview"),
    "Quality events": ("quality", "QualityEvent"),
    "Packet projects": ("dossier", "DossierProject"),
    "Packet checklist": ("dossier", "DossierEntry"),
    "Packet documents": ("dossier", "DossierDocument"),
    "Packet reviews": ("dossier", "DossierReview"),
    "Packet issues": ("dossier", "DossierIssue"),
    "Packet handovers": ("dossier", "DossierHandover"),
    "Packet events": ("dossier", "DossierEvent"),
}
PROCESS_REPORTS = ["Process visits", "Process totals"]
FLOW_DEFINITIONS = ["Flow steps"]
QUALITY_REPORTS = ["Audit readiness"]
DELIVERY_REPORTS = ["Project progress", "Part progress", "Job Packet readiness", "Spool parts progress"]


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

    def full_text(self, record, column):
        value = record[column].value
        match = re.fullmatch(r'\[Text overflow (OVF-[0-9]+); ([0-9]+) chunks\]', value or '')
        if not match:
            return value
        parts = [row for name in self.sheets if name == 'Text overflow' or name.startswith('Text overflow ')
                 for row in self.records(name) if row['overflow_id'].value == match[1]]
        parts.sort(key=lambda row: row['chunk_index'].value)
        assert len(parts) == int(match[2])
        assert [row['chunk_index'].value for row in parts] == list(range(1, len(parts) + 1))
        return ''.join(row['text'].value for row in parts)


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
            columns = EMPLOYEE_COLUMNS if name == "Employees" else [key for key in model.__table__.columns.keys() if key not in EXCLUDED_COLUMNS.get(name, set())]
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
    assert list(workbook.sheets) == ["Export info", *TABLES, *PROCESS_REPORTS, *FLOW_DEFINITIONS, *QUALITY_REPORTS, *DELIVERY_REPORTS]
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
                      **{name: 0 for name in PROCESS_REPORTS}, "Flow steps": 24, "Audit readiness": 0,
                      "Project progress": 1, "Part progress": 1, "Job Packet readiness": 0, "Spool parts progress": 0}
    assert sources == {**{name: model.__tablename__ for name, model in models().items()},
                       **{name: "derived:tracking_process_events" for name in PROCESS_REPORTS},
                       "Flow steps": "definition:CLM-process-flow", "Audit readiness": "derived:quality_readiness",
                       "Project progress": "derived:project_progress", "Part progress": "derived:part_progress",
                       "Job Packet readiness": "derived:packet_readiness", "Spool parts progress": "derived:spool_parts_progress"}
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
    assert list(workbook.sheets) == ["Export info", *TABLES, *PROCESS_REPORTS, *FLOW_DEFINITIONS, *QUALITY_REPORTS, *DELIVERY_REPORTS]
    for name, model in models().items():
        expected_columns = EMPLOYEE_COLUMNS if name == "Employees" else [key for key in model.__table__.columns.keys() if key not in EXCLUDED_COLUMNS.get(name, set())]
        assert workbook.headers(name) == expected_columns
        assert len(workbook.records(name)) == (len(BADGES) if name == "Employees" else 0)
    exporter = importlib.import_module("exports")
    assert workbook.headers("Process visits") == list(exporter.PROCESS_VISIT_COLUMNS)
    assert workbook.headers("Process totals") == list(exporter.PROCESS_TOTAL_COLUMNS)
    assert all(not workbook.records(name) for name in PROCESS_REPORTS)
    assert workbook.headers("Audit readiness") == list(exporter.QUALITY_REPORT_COLUMNS)
    assert not workbook.records("Audit readiness")
    assert workbook.headers("Flow steps") == list(exporter.FLOW_STEP_COLUMNS)
    assert [row["number"].value for row in workbook.records("Flow steps")] == list(range(1, 25))
    for name, columns in (("Project progress", exporter.PROJECT_PROGRESS_COLUMNS),
                          ("Part progress", exporter.PART_PROGRESS_COLUMNS),
                          ("Job Packet readiness", exporter.PACKET_READINESS_COLUMNS),
                          ("Spool parts progress", exporter.SPOOL_PARTS_PROGRESS_COLUMNS)):
        assert workbook.headers(name) == list(columns)
        assert not workbook.records(name)


def test_admin_release_and_account_changes_export_without_fabricated_qa_or_secrets(api):
    from test_admin import employee, employee_body, release
    from test_flow import create_item
    from tracking_helpers import ok

    item_id = create_item(api, "EXPORT-ADMIN-RELEASE", kind="Spool")
    released = release(api, item_id)
    assert released["release"]["mode"] == "admin_override"
    row = employee(api, BADGES["welder"])
    ok(api.patch(f"/api/admin/employees/{row['badge']}", employee_body(api, row["badge"], name="Export account revision")))
    row = employee(api, row["badge"])
    new_pin = "synthetic-export-pin-never-for-production-123"
    ok(api.post(f"/api/admin/employees/{row['badge']}/pin", {
        "expected_version": row["version"], "pin": new_pin, "reason": "Synthetic local export security verification",
    }))
    before = snapshot(api)
    _, workbook = download(api)
    part = next(row for row in workbook.records("Part progress") if row["item_id"].value == item_id)
    assert part["released"].value is True
    assert part["release_mode"].value == "admin_override"
    assert part["release_label"].value == "Administrative release"
    assert part["administrative_release"].value is True
    assert part["fabrication_finished"].value is False
    assert part["qa_accepted"].value == 0
    access = workbook.records("Employee access states")[0]
    assert access["badge"].value == BADGES["welder"]
    assert access["version"].value == 2 and access["session_version"].value == 1
    audit_row = next(row for row in workbook.records("Audit events") if row["event"].value == "ADMIN_RELEASE_OVERRIDE")
    recorded = json.loads(workbook.full_text(audit_row, "details"))
    assert recorded["bypassed_blockers"]
    assert recorded["quality_acceptance_recorded"] is False
    assert new_pin.encode() not in workbook.xml
    with api.session_factory() as session:
        for current in session.scalars(select(api.application.Employee)):
            assert current.pin_hash.encode() not in workbook.xml
    assert snapshot(api) == before


def test_transfer_export_retains_both_badges_status_and_original_location_labels(api):
    from tracking_helpers import ok

    item_id = "EXPORT-HANDOFF"
    api.item(item_id, welds_required=0)
    created = ok(api.post("/api/transfers/locations", {"label": "North fabrication bay"}), 201)
    record = ok(api.get(f"/api/items/{item_id}"))
    updated = ok(api.post(f"/api/items/{item_id}/transfer", {
        "sender_badge": record["handler"], "handler": BADGES["welder"],
        "location_id": created["id"], "operational_status": "waiting_material",
        "expected_transfer_version": record["transfer"]["version"], "notes": "Awaiting the identified fitting",
    }))
    ok(api.patch(f"/api/transfers/locations/{created['id']}", {
        "label": "North fabrication bay 2", "active": False, "expected_version": created["version"],
    }))
    before = snapshot(api)
    _, workbook = download(api)
    state = workbook.records("Item transfer states")[0]
    assert state["item_id"].value == item_id
    assert state["version"].value == updated["transfer"]["version"] == 1
    assert state["operational_status"].value == "waiting_material"
    assert state["updated_by"].value == BADGES["admin"]
    location = workbook.records("Transfer locations")[0]
    assert location["label"].value == "North fabrication bay 2"
    assert location["active"].value is False and location["version"].value == 2
    item = workbook.records("Items")[0]
    assert item["handler"].value == BADGES["welder"]
    assert item["location"].value == "North fabrication bay"
    event = next(row for row in workbook.records("Audit events") if row["event"].value == "TRANSFER")
    details = json.loads(workbook.full_text(event, "details"))
    assert details["sender_badge"] == record["handler"]
    assert details["receiver_badge"] == BADGES["welder"]
    assert details["handoff_recorded_by"] == BADGES["admin"]
    assert details["to"]["location"] == "North fabrication bay"
    assert details["to"]["operational_status"] == "waiting_material"
    assert details["recipient_acknowledged"] is False
    assert snapshot(api) == before


def test_spool_parts_export_uses_required_quantities_and_actual_recorded_component_progress(api):
    from test_parts import allocate, component, detail, line, plan, prepare, spool
    from test_progress import database_state

    spool_id = spool(api, "EXPORT-QUANTITY-SPOOL")
    record = plan(api, spool_id, [line(3, part_number="000-ELBOW", description="=1+1 < & synthetic part")])
    component(api, "EXPORT-PART-001", part_number="000-ELBOW")
    component(api, "EXPORT-PART-002", part_number="000-ELBOW")
    allocate(api, spool_id, record["lines"][0]["id"], ["EXPORT-PART-001", "EXPORT-PART-002"])
    prepare(api, "EXPORT-PART-001", spool_id)
    prepare(api, "EXPORT-PART-002", spool_id, start_step=8)
    expected = detail(api, spool_id)
    before = database_state(api)
    _, workbook = download(api)
    assert database_state(api) == before
    assert workbook.formulas == []
    assert len(workbook.records("Spool parts plans")) == 1
    assert len(workbook.records("Spool part lines")) == 1
    assert len(workbook.records("Part allocations")) == 2
    assert len(workbook.records("Spool parts events")) == len(expected["events"])
    row = workbook.records("Spool parts progress")[0]
    assert row["spool_id"].value == spool_id
    assert row["part_number"].value == "000-ELBOW"
    assert row["description"].value == "=1+1 < & synthetic part"
    for key, value in {"required_qty": 3, "assigned_qty": 2, "received_qty": 1, "prepared_qty": 1,
                       "short_qty": 1, "remaining_qty": 2}.items():
        assert row[key].kind == "n" and row[key].value == value
    assert row["prepared_percent"].value == pytest.approx(33.3)
    assert json.loads(row["component_ids"].value) == ["EXPORT-PART-001", "EXPORT-PART-002"]
    assert row["blockers"].value
    assert row["as_of"].style in workbook.date_styles


def test_packet_export_keeps_immutable_issues_and_current_readiness_separate_from_progress(api):
    from test_dossier import (PDF, PROJECT, checks, entry, issued_fixture, packet,
                              signed, issue_project)
    from test_progress import database_state

    item_id = 'EXPORT-PACKET-SPOOL'
    issue = issued_fixture(api, item_id)
    signed(issue_project(api))
    original = packet(api, item_id)
    before = database_state(api)
    _, workbook = download(api)
    assert database_state(api) == before
    assert workbook.formulas == []
    metadata = workbook.records('Packet documents')
    assert metadata and all(row['sha256'].value and row['size_bytes'].value == len(PDF) for row in metadata)
    assert PDF not in workbook.xml
    assert all('content' not in workbook.headers(name) for name in TABLES)
    assert 'dossier_files' not in {spec.table for spec in importlib.import_module('exports').TABLE_SPECS}
    issues = workbook.records('Packet issues')
    item_issue = next(row for row in issues if row['id'].value == str(issue['id']))
    preserved = json.loads(workbook.full_text(item_issue, 'snapshot'))
    assert item_issue['sha256'].value == issue['sha256']
    assert preserved and len(issues) == 2
    readiness = workbook.records('Job Packet readiness')
    assert len(readiness) == len(checks(original))
    assert all(row['packet_status'].value == 'issued' and row['issue_current'].value for row in readiness)
    assert all(row['latest_issue_id'].value == str(issue['id']) for row in readiness)
    assert all(row['as_of'].style in workbook.date_styles for row in readiness)
    assert all(row['last_review_at'].style in workbook.date_styles for row in readiness)
    summary = workbook.records('Project progress')[0]
    part = workbook.records('Part progress')[0]
    assert summary['project_id'].value == PROJECT and summary['finished'].value == 1
    assert summary['finished_percent'].value == 100
    assert part['fabrication_finished'].value and part['progress_percent'].value == 100
    assert part['progress_basis'].value == 'qa_release'

    signed(entry(api, item_id, 'contact', notes='Revised synthetic contact needs a new QA review.'))
    before = database_state(api)
    _, changed = download(api)
    assert database_state(api) == before
    current = changed.records('Job Packet readiness')
    contact = next(row for row in current if row['code'].value == 'contact')
    assert contact['check_status'].value == 'stale' and contact['packet_status'].value == 'stale'
    assert not contact['issue_current'].value
    assert changed.records('Part progress')[0]['fabrication_finished'].value
    historical = next(row for row in changed.records('Packet issues') if row['id'].value == str(issue['id']))
    assert historical['sha256'].value == issue['sha256']
    assert json.loads(changed.full_text(historical, 'snapshot')) == preserved


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


def test_flow_export_preserves_checklists_exceptions_links_and_component_project(api):
    from tracking_helpers import make_spool

    parent_id = make_spool(api, item_id="FLOW-EXPORT-SPOOL")
    component_id = "000007-COMP"
    response = api.post("/api/items", {
        "id": component_id, "description": "Export component", "kind": "Part", "project": "TEST-PROJECT",
        "location": "Receiving", "handler": BADGES["handler"], "welds_required": 0,
    })
    assert response.status_code == 201, response.text
    path = f"/api/flow/items/{component_id}"
    started = api.post(path + "/start", {"route": "component"})
    assert started.status_code == 201, started.text
    linked = api.post(path + "/assign-component", {
        "expected_version": started.json()["flow"]["version"], "spool_id": parent_id,
        "reference": "BOM-0007", "notes": "Controlled component assignment",
    })
    assert linked.status_code == 201, linked.text
    current = linked.json()["flow"]
    received = api.post(path + "/advance", {
        "expected_version": current["version"],
        "confirmations": [row["id"] for row in current["current"]["checks"]],
        "scanned_item_id": component_id, "reference": "PO-0007", "notes": "Receipt α < & >",
    }, role="handler")
    assert received.status_code == 200, received.text
    failed = api.post(path + "/fail", {
        "expected_version": received.json()["flow"]["version"],
        "reason": "MTR and material dimensions need supplier review", "reference": "NCR-0007",
    }, role="inspector")
    assert failed.status_code == 200, failed.text
    before = snapshot(api)
    _, workbook = download(api)
    assert snapshot(api) == before
    assert workbook.formulas == []
    plan = workbook.records("Flow plans")[0]
    assert plan["item_id"].value == component_id
    assert plan["route"].value == "component" and plan["current_step"].value == 2
    assert plan["version"].value == 4 and plan["status"].value == "active"
    assert plan["shipped_at"].value is None and plan["delivered_at"].value is None
    events = workbook.records("Flow events")
    assert len(events) == 4 and [row["sequence"].value for row in events] == [1, 2, 3, 4]
    receipt = next(row for row in events if row["action"].value == "advance")
    data = json.loads(receipt["data"].value)
    assert data["confirmations"] == [row["id"] for row in current["current"]["checks"]]
    assert data["definition_version"] == "CLM-24-v1"
    assert data["step_definition"]["number"] == 1
    assert receipt["notes"].value == "Receipt α < & >"
    exception = workbook.records("Flow exceptions")[0]
    assert exception["reference"].value == "NCR-0007"
    assert exception["step"].value == exception["return_step"].value == 2
    assert exception["closed_at"].value is None
    link = workbook.records("Component links")[0]
    assert link["component_id"].value == component_id and link["spool_id"].value == parent_id
    visits = workbook.records("Process visits")
    assert len(visits) == 3
    assert all(row["item_id"].value == component_id and row["project_id"].value == "TEST-PROJECT" for row in visits)
    assert [row["process_key"].value for row in visits] == ["clm_01", "clm_02", "clm_02"]
    assert len(workbook.records("Flow steps")) == 24
    shipping = workbook.records("Flow steps")[22]
    assert shipping["number"].value == 23 and shipping["requires_reference"].value is True


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


def test_quality_export_distinguishes_drafts_verified_records_and_stale_reviews(api):
    from test_quality import workspace, verified_requirement, edit_requirement

    first = workspace(api, name="Synthetic verified workspace")
    workspace_id = first["workspace"]["id"]
    requirement_id, evidence_id = verified_requirement(api, workspace_id, item_number="000007")
    drafts = workspace(api, template="kelvion", name="Synthetic draft workspace")
    before = snapshot(api)
    _, workbook = download(api)
    assert snapshot(api) == before
    assert workbook.formulas == []
    report = workbook.records("Audit readiness")
    assert len(report) == 1 + len(drafts["requirements"])
    verified = next(row for row in report if row["requirement_id"].value == str(requirement_id))
    assert verified["item_number"].value == "000007"
    assert verified["verification_status"].value == "verified"
    assert verified["source_status"].value == "confirmed"
    assert verified["last_reviewer"].value == BADGES["inspector"]
    assert "TEST-ACTUAL-RECORD" in verified["collected_evidence"].value
    assert verified["as_of"].style in workbook.date_styles
    assert verified["last_review_at"].style in workbook.date_styles
    for row in report:
        if row["workspace_id"].value != str(drafts["workspace"]["id"]):
            continue
        assert row["verification_status"].value == "draft"
        assert row["source_status"].value == "unconfirmed"
        assert row["clm_response"].value.startswith("DRAFT")
        assert row["blockers"].value
        assert row["collected_evidence"].value == ""
    assert len(workbook.records("Quality evidence")) == 1
    assert workbook.records("Quality evidence")[0]["id"].value == str(evidence_id)
    assert len(workbook.records("Quality reviews")) == 3
    assert not workbook.records("Quality documents")
    assert not workbook.records("Quality actions")
    for name, expected in before.items():
        assert len(workbook.records(name)) == len(expected["rows"]), name

    edit_requirement(api, workspace_id, requirement_id, gaps="Locate the missing actual inspection record.")
    before = snapshot(api)
    _, changed = download(api)
    assert snapshot(api) == before
    row = next(row for row in changed.records("Audit readiness") if row["requirement_id"].value == str(requirement_id))
    assert row["verification_status"].value != "verified"
    assert row["last_review_decision"].value == "verified"
    assert "missing actual inspection" in row["gaps_and_corrective_actions"].value
    assert "gap" in row["blockers"].value.lower()
    assert len(changed.records("Quality reviews")) == 3


def test_audit_readiness_export_includes_training_recorded_under_another_requirement(api):
    from test_quality import (workspace, create_requirement, create_document, edit_requirement,
                              confirm_source, review, review_ok, accepted_evidence)

    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, item_number="DOC-CONTROL",
        required_evidence_types=[], requires_approved_document=True)
    training_requirement_id = create_requirement(api, workspace_id, item_number="TRAINING-REGISTER")
    document_id = create_document(api, workspace_id, requires_training=True, required_badges=[BADGES["welder"]])
    review_ok(review(api, workspace_id, "document", document_id, "approved"))
    edit_requirement(api, workspace_id, requirement_id, document_ids=[document_id])
    confirm_source(api, workspace_id, requirement_id)
    evidence_id = accepted_evidence(api, workspace_id, training_requirement_id, type="training",
        document_id=document_id, participants=[BADGES["welder"]], performed_by=BADGES["supervisor"],
        reference="TEST-EXACT-REVISION-TRAINING", data={"topic": "Controlled revision", "assessment": "Understanding checked"})
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    _, workbook = download(api)
    row = next(row for row in workbook.records("Audit readiness") if row["requirement_id"].value == str(requirement_id))
    assert row["verification_status"].value == "verified"
    assert f"#{evidence_id} training" in row["collected_evidence"].value
    assert "TEST-EXACT-REVISION-TRAINING" in row["collected_evidence"].value
    assert BADGES["welder"] in row["collected_evidence"].value
    assert BADGES["supervisor"] in row["collected_evidence"].value
    assert f"under requirement ID {training_requirement_id}" in row["collected_evidence"].value
    assert "TEST-QMS Rev A" in row["supporting_documentation"].value
