"""Verify migrations, immutable history and concurrent writes on LOCAL PostgreSQL.

Run from the repository root with the development dependencies installed:

    python tests/verify_postgres.py --dsn \
      'postgresql+psycopg://nobody@/fabtrace_test_upgrade?host=/tmp/fabtrace-pg/socket&port=55432'

Local TCP is also supported, for example:

    python tests/verify_postgres.py --dsn \
      'postgresql+psycopg://test_user@127.0.0.1:5432/fabtrace_test_upgrade'

Use a psycopg DSN with one explicit loopback host or absolute Unix-socket
directory and a database matching fabtrace_test_[a-z0-9_]+ (at most 63
characters). Only host and port query parameters are accepted. Remote hosts,
multiple hosts, connection services and caller-supplied options are rejected.
DATABASE_URL and libpq routing environment variables are never inherited.
Every run creates one UUID-named schema and removes it in a finally block.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib
import hashlib
import ipaddress
import io
import json
import os
from pathlib import Path
import re
import sys
from threading import Barrier
import uuid
from xml.etree import ElementTree as ET
import zipfile

from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import BADGES, TEST_PIN, TEST_SECRET, TestAPI
from tracking_helpers import (
    accept_weld,
    add_weld,
    complete_weld,
    find_requirement,
    make_spool,
    ok,
    requirement,
)


LEGACY_TABLES = ("employees", "items", "inspections", "reworks", "audit_events")
LIBPQ_ROUTING_ENV = (
    "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS",
)


def is_loopback_host(host):
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or bool(getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)


def local_test_url(value):
    rejection = "Supply a single explicit local psycopg host and a fabtrace_test_* database; only host/port query parameters are allowed"
    try:
        url = make_url(value)
    except (ArgumentError, TypeError, ValueError):
        raise ValueError(rejection) from None
    query = dict(url.query)
    if (
        url.drivername != "postgresql+psycopg"
        or not re.fullmatch(r"fabtrace_test_[a-z0-9_]+", url.database or "")
        or len(url.database) > 63
        or set(query) - {"host", "port"}
        or any(not isinstance(value, str) for value in query.values())
        or (url.host is None) == (query.get("host") is None)
        or (url.port is not None and "port" in query)
    ):
        raise ValueError(rejection)
    host = url.host if url.host is not None else query["host"]
    socket_directory = (
        host.startswith("/") and "," not in host
        and all(ord(character) >= 32 for character in host)
    )
    port = str(url.port) if url.port is not None else query.get("port", "5432")
    if (
        not (is_loopback_host(host) or socket_directory)
        or not re.fullmatch(r"[0-9]{1,5}", port)
        or not 1 <= int(port) <= 65535
    ):
        raise ValueError(rejection)
    return url


def snapshot_legacy(application):
    with application.engine.connect() as connection:
        return {
            name: [dict(row) for row in connection.execute(
                select(application.Base.metadata.tables[name]).order_by(
                    *application.Base.metadata.tables[name].primary_key.columns
                )
            ).mappings()]
            for name in LEGACY_TABLES
        }


def seed_legacy(application):
    # Build only the original schema. No tracking tables exist before initialize.
    application.Base.metadata.create_all(
        application.engine,
        tables=[application.Base.metadata.tables[name] for name in LEGACY_TABLES],
    )
    hashed_pin = application.password_hash.hash(TEST_PIN)
    with application.SessionLocal() as session:
        session.add_all(
            application.Employee(
                badge=badge, name="PostgreSQL test " + role,
                role=role, pin_hash=hashed_pin, active=True,
            )
            for role, badge in BADGES.items()
        )
        session.flush()
        session.add(application.Item(
            id="LEGACY-UPGRADE-CHECK", description="Preserve this legacy item exactly",
            kind="Part", project="Legacy project", google_part_number="LEGACY-PART-NO",
            drawing="LEGACY-DWG", location="Legacy weld bay", handler=BADGES["welder"],
            welds_required=7, welds_done=3, dimensional="Pass", weld="Not started",
            dimension_at=application.utcnow(), on_hold=True,
        ))
        session.flush()
        session.add(application.Inspection(
            item_id="LEGACY-UPGRADE-CHECK", kind="Dimensional", result="Pass",
            inspector=BADGES["inspector"], report="LEGACY-DIMENSION-REPORT",
            measurements="Original measurements must survive the upgrade",
        ))
        session.add(application.Rework(
            item_id="LEGACY-UPGRADE-CHECK", kind="Dimensional",
            reason="Original legacy rework", assigned=BADGES["welder"],
        ))
        session.add(application.Audit(
            item_id="LEGACY-UPGRADE-CHECK", actor=BADGES["admin"],
            event="LEGACY_TEST_SEED", details={"preserve": True, "weld_count": 3},
        ))
        session.commit()


def verify_history_protection(application, initializer, schema):
    assert set(initializer.HISTORY_TABLES) == {
        "audit_events", "tracking_requirement_evidence", "tracking_requirement_reviews",
        "tracking_weld_work", "tracking_weld_repairs", "tracking_requirement_templates",
        "tracking_process_events", "flow_events", "spool_parts_events",
        "quality_documents", "quality_evidence", "quality_reviews", "quality_events",
        "dossier_documents", "dossier_files", "dossier_reviews", "dossier_issues",
        "dossier_handovers", "dossier_events",
    }
    results = {}
    for name in initializer.HISTORY_TABLES:
        assert name in application.Base.metadata.tables
        declared = application.Base.metadata.tables[name]
        key_columns = list(declared.primary_key.columns)
        assert len(key_columns) == 1, f"Use the declared history key for {name}"
        key = key_columns[0].name
        # Both identifiers come from fixed code / generated UUIDs, never user SQL.
        table = f'"{schema}"."{name}"'
        with application.engine.connect() as connection:
            record_id = connection.scalar(text(f'SELECT "{key}" FROM {table} ORDER BY "{key}" LIMIT 1'))
            before = connection.scalar(text(f"SELECT count(*) FROM {table}"))
            original = dict(connection.execute(select(declared).where(key_columns[0] == record_id)).mappings().one()) if record_id is not None else None
        assert record_id is not None, f"History table has no representative row: {name}"
        for operation, statement in (
            ("UPDATE", f'UPDATE {table} SET "{key}" = "{key}" WHERE "{key}" = :record_id'),
            ("DELETE", f'DELETE FROM {table} WHERE "{key}" = :record_id'),
        ):
            try:
                with application.engine.begin() as connection:
                    connection.execute(text(statement), {"record_id": record_id})
            except DBAPIError as error:
                assert getattr(error.orig, "sqlstate", None) == "P0001", str(error)
                assert "history modification forbidden" in str(error.orig), str(error)
            else:
                raise AssertionError(f"{name} unexpectedly allowed {operation}")
        with application.engine.connect() as connection:
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == before
            assert connection.scalar(
                text(f'SELECT "{key}" FROM {table} WHERE "{key}" = :record_id'),
                {"record_id": record_id},
            ) == record_id
            assert dict(connection.execute(select(declared).where(key_columns[0] == record_id)).mappings().one()) == original
        results[name] = {"update_blocked": True, "delete_blocked": True}
        if name == "dossier_files":
            try:
                with application.engine.begin() as connection:
                    connection.execute(text(f'UPDATE {table} SET content = :content WHERE "{key}" = :record_id'),
                        {"content": b"REPLACEMENT-BYTES-MUST-NOT-BE-SAVED", "record_id": record_id})
            except DBAPIError as error:
                assert getattr(error.orig, "sqlstate", None) == "P0001", str(error)
                assert "history modification forbidden" in str(error.orig), str(error)
            else:
                raise AssertionError("Issued evidence file bytes unexpectedly allowed replacement")
            with application.engine.connect() as connection:
                assert connection.scalar(select(declared.c.content).where(key_columns[0] == record_id)) == original["content"]
            results[name]["content_replacement_blocked"] = True
    return results


def verify_concurrent_evidence(application, tracking, api, item_id, weld_id):
    req = find_requirement(api, item_id, weld_id, code="MATERIALS")
    with application.SessionLocal() as session:
        evidence_before = session.scalars(select(tracking.RequirementEvidence).where(
            tracking.RequirementEvidence.requirement_id == req["id"]
        )).all()
        audit_before = session.scalars(select(application.Audit).where(
            application.Audit.event == "TRACKING_EVIDENCE_SUBMITTED",
            application.Audit.item_id == item_id,
        )).all()

    # Synchronize at the actual database row-lock query, after both requests
    # have read the same old requirement. This exercises stale identity-map
    # refresh plus PostgreSQL row locking, not only sequential stale requests.
    lock_barrier = Barrier(2)

    def synchronize_item_lock(connection, cursor, statement, parameters, context, many):
        if "FROM items" in statement and "FOR UPDATE" in statement:
            lock_barrier.wait(timeout=15)

    def submit_one(reference):
        worker = TestAPI(application, application.SessionLocal)
        try:
            response = worker.post(
                f"/api/tracking/requirements/{req['id']}/evidence",
                {
                    "expected_version": req["version"], "reference": reference,
                    "result": "pass", "notes": "Concurrent local PostgreSQL test",
                },
                role="welder",
            )
            return {"status": response.status_code, "reference": reference, "body": response.json()}
        finally:
            worker.client.close()

    event.listen(application.engine, "before_cursor_execute", synchronize_item_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit_one, reference) for reference in ("RACE-REPORT-A", "RACE-REPORT-B")]
            responses = [future.result(timeout=30) for future in futures]
    finally:
        event.remove(application.engine, "before_cursor_execute", synchronize_item_lock)

    assert sorted(row["status"] for row in responses) == [201, 409], responses
    winner = next(row for row in responses if row["status"] == 201)
    current = requirement(api, item_id, req["id"])
    assert current["version"] == req["version"] + 1
    with application.SessionLocal() as session:
        evidence_after = session.scalars(select(tracking.RequirementEvidence).where(
            tracking.RequirementEvidence.requirement_id == req["id"]
        ).order_by(tracking.RequirementEvidence.id)).all()
        audit_after = session.scalars(select(application.Audit).where(
            application.Audit.event == "TRACKING_EVIDENCE_SUBMITTED",
            application.Audit.item_id == item_id,
        ).order_by(application.Audit.id)).all()
        assert len(evidence_after) == len(evidence_before) + 1
        assert len(audit_after) == len(audit_before) + 1
        evidence = evidence_after[-1]
        audit = audit_after[-1]
        assert evidence.reference == winner["reference"]
        assert audit.details["evidence_id"] == evidence.id
        assert audit.details["requirement_id"] == req["id"]
        assert audit.details["reference"] == evidence.reference
        assert audit.actor == evidence.actor == BADGES["welder"]
    return {"response_codes": sorted(row["status"] for row in responses), "new_evidence_rows": 1, "new_audit_rows": 1}


def verify_concurrent_process_transition(application, production, api, item_id):
    route = f"/api/tracking/spools/{item_id}/process"
    initial = ok(api.get(route))
    assert initial["status"] == "not_started" and initial["version"] == 0
    with application.SessionLocal() as session:
        events_before = session.scalar(select(func.count()).select_from(production.SpoolProcessEvent).where(
            production.SpoolProcessEvent.item_id == item_id,
        ))
        audits_before = session.scalar(select(func.count()).select_from(application.Audit).where(
            application.Audit.item_id == item_id, application.Audit.event == "TRACKING_PROCESS_EVENT",
        ))

    lock_barrier = Barrier(2)

    def synchronize_item_lock(connection, cursor, statement, parameters, context, many):
        # Flow-aware process operations now acquire the topology advisory lock
        # before an Item lock. Synchronize before that first serialization
        # point; a barrier after it would deadlock the second request.
        if "pg_advisory_xact_lock" in statement:
            lock_barrier.wait(timeout=15)

    def start_one(process_key):
        worker = TestAPI(application, application.SessionLocal)
        try:
            response = worker.post(route, {
                "action": "start", "expected_version": initial["version"],
                "process_key": process_key, "notes": "Concurrent local process start",
            }, role="welder")
            return {"status": response.status_code, "process_key": process_key, "body": response.json()}
        finally:
            worker.client.close()

    event.listen(application.engine, "before_cursor_execute", synchronize_item_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = [future.result(timeout=30) for future in [
                pool.submit(start_one, "welding"), pool.submit(start_one, "nde"),
            ]]
    finally:
        event.remove(application.engine, "before_cursor_execute", synchronize_item_lock)

    assert sorted(row["status"] for row in responses) == [201, 409], responses
    winner = next(row for row in responses if row["status"] == 201)
    current = ok(api.get(route))
    assert current["version"] == 1 and current["status"] == "running"
    assert len(current["events"]) == len(current["visits"]) == 1
    assert current["current"]["process_key"] == winner["process_key"]
    with application.SessionLocal() as session:
        process_events = session.scalars(select(production.SpoolProcessEvent).where(
            production.SpoolProcessEvent.item_id == item_id,
        ).order_by(production.SpoolProcessEvent.sequence)).all()
        audits = session.scalars(select(application.Audit).where(
            application.Audit.item_id == item_id, application.Audit.event == "TRACKING_PROCESS_EVENT",
        ).order_by(application.Audit.id)).all()
        assert len(process_events) == events_before + 1
        assert len(audits) == audits_before + 1
        recorded = process_events[-1]
        audit = audits[-1]
        assert recorded.sequence == 1 and recorded.event == "start"
        assert recorded.process_key == winner["process_key"]
        assert audit.details["process_event_id"] == recorded.id
        assert audit.details["sequence"] == recorded.sequence
        assert audit.details["process_key"] == recorded.process_key
        assert audit.actor == recorded.actor == BADGES["welder"]
    return {"response_codes": [201, 409], "new_process_events": 1, "new_audit_rows": 1, "open_visits": 1}


def verify_concurrent_flow_step(application, flow, production, api):
    from test_flow import action_body, create_item, detail, enroll

    item_id = create_item(api, "PG-FLOW-COMPONENT")
    initial = enroll(api, item_id, "component")
    body = action_body(api, item_id)
    with application.SessionLocal() as session:
        flow_before = session.scalar(select(func.count()).select_from(flow.FlowEvent).where(
            flow.FlowEvent.item_id == item_id,
        ))
        process_before = session.scalar(select(func.count()).select_from(production.SpoolProcessEvent).where(
            production.SpoolProcessEvent.item_id == item_id,
        ))

    gate = Barrier(2)

    def synchronize_topology_lock(connection, cursor, statement, parameters, context, many):
        if "pg_advisory_xact_lock" in statement:
            gate.wait(timeout=15)

    def advance_one(note):
        worker = TestAPI(application, application.SessionLocal)
        try:
            response = worker.post(f"/api/flow/items/{item_id}/advance", {**body, "notes": note})
            return {"status": response.status_code, "note": note, "body": response.json()}
        finally:
            worker.client.close()

    event.listen(application.engine, "before_cursor_execute", synchronize_topology_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = [future.result(timeout=30) for future in [
                pool.submit(advance_one, "Concurrent flow request A"),
                pool.submit(advance_one, "Concurrent flow request B"),
            ]]
    finally:
        event.remove(application.engine, "before_cursor_execute", synchronize_topology_lock)

    assert sorted(row["status"] for row in responses) == [200, 409], responses
    current = detail(api, item_id)
    assert current["flow"]["version"] == initial["flow"]["version"] + 1
    assert current["flow"]["current_step"] == 2
    assert len(current["production_process"]["visits"]) == 2
    assert current["production_process"]["current"] is not None
    with application.SessionLocal() as session:
        flow_after = session.scalar(select(func.count()).select_from(flow.FlowEvent).where(
            flow.FlowEvent.item_id == item_id,
        ))
        process_after = session.scalar(select(func.count()).select_from(production.SpoolProcessEvent).where(
            production.SpoolProcessEvent.item_id == item_id,
        ))
        assert flow_after == flow_before + 1
        assert process_after == process_before + 1
    return {"response_codes": [200, 409], "new_flow_events": 1, "new_process_events": 1, "current_step": 2}


def verify_concurrent_quality_evidence(application, quality, api):
    from test_quality import (
        PAST, confirm_source, create_document, create_requirement, current,
        review, workspace,
    )

    workspace_id = workspace(api, name="Isolated PostgreSQL audit workspace")["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id)
    confirm_source(api, workspace_id, requirement_id)
    document_id = create_document(api, workspace_id)
    ok(review(api, workspace_id, "document", document_id, "approved"), 201)
    initial = current(api, workspace_id)
    with application.SessionLocal() as session:
        evidence_before = session.scalar(select(func.count()).select_from(quality.QualityEvidence).where(
            quality.QualityEvidence.workspace_id == workspace_id,
        ))
        events_before = session.scalar(select(func.count()).select_from(quality.QualityEvent).where(
            quality.QualityEvent.workspace_id == workspace_id,
        ))
        audits_before = session.scalar(select(func.count()).select_from(application.Audit))

    gate = Barrier(2)

    def synchronize_topology_lock(connection, cursor, statement, parameters, context, many):
        # Quality writes share production's topology-first lock ordering. Both
        # workers must arrive before serialization, not inside the row lock.
        if "pg_advisory_xact_lock" in statement:
            gate.wait(timeout=15)

    def submit_one(reference):
        worker = TestAPI(application, application.SessionLocal)
        try:
            response = worker.post(f"/api/quality/workspaces/{workspace_id}/evidence", {
                "expected_version": initial["workspace"]["version"],
                "requirement_id": requirement_id, "type": "other",
                "title": "Concurrent isolated audit evidence", "reference": reference,
                "occurred_on": PAST, "data": {"scope": "Local PostgreSQL concurrency test", "result": "pass"},
            }, role="supervisor")
            return {"status": response.status_code, "reference": reference, "body": response.json()}
        finally:
            worker.client.close()

    event.listen(application.engine, "before_cursor_execute", synchronize_topology_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = [future.result(timeout=30) for future in [
                pool.submit(submit_one, "PG-QUALITY-EVIDENCE-A"),
                pool.submit(submit_one, "PG-QUALITY-EVIDENCE-B"),
            ]]
    finally:
        event.remove(application.engine, "before_cursor_execute", synchronize_topology_lock)

    assert sorted(row["status"] for row in responses) == [201, 409], responses
    winner = next(row for row in responses if row["status"] == 201)
    after = current(api, workspace_id)
    assert after["workspace"]["version"] == initial["workspace"]["version"] + 1
    assert len(after["evidence"]) == evidence_before + 1
    assert after["evidence"][-1]["reference"] == winner["reference"]
    assert after["evidence"][-1]["status"] == "submitted"
    assert after["metrics"]["verified"] == 0
    with application.SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(quality.QualityEvent).where(
            quality.QualityEvent.workspace_id == workspace_id,
        )) == events_before + 1
        assert session.scalar(select(func.count()).select_from(application.Audit)) == audits_before + 1
    return {"response_codes": [201, 409], "new_evidence_rows": 1, "new_quality_events": 1,
            "new_audit_rows": 1, "verification_invented": False}


def verify_concurrent_dossier_mutation(application, dossier, api):
    from test_dossier import make_project, packet, project, version

    project_id = "PG-DOSSIER-RACE"
    item_id = make_project(api, "PG-DOSSIER-RACE-SPOOL", project_id=project_id)
    initial_version = version(api, project_id)
    with application.SessionLocal() as session:
        events_before = session.scalar(select(func.count()).select_from(dossier.DossierEvent).where(
            dossier.DossierEvent.project_id == project_id))
        audits_before = session.scalar(select(func.count()).select_from(application.Audit))

    gate = Barrier(2)
    synchronized_connections = set()

    def synchronize_topology_lock(connection, cursor, statement, parameters, context, many):
        # Synchronize before the global topology lock. A barrier inside a
        # project/Item row lock would deadlock the other legitimate writer.
        if "pg_advisory_xact_lock" in statement and id(connection) not in synchronized_connections:
            synchronized_connections.add(id(connection))
            gate.wait(timeout=15)

    def change_one(code):
        worker = TestAPI(application, application.SessionLocal)
        try:
            response = worker.put(f"/api/dossier/items/{item_id}/checks/{code}", {
                "expected_version": initial_version, "applicability": "required",
                "reference": "PG-CONCURRENT-" + code,
                "notes": "Independent synthetic document record entered concurrently.",
                "document_ids": [], "values": {},
            }, role="supervisor")
            return {"status": response.status_code, "code": code, "body": response.json()}
        finally:
            worker.client.close()

    event.listen(application.engine, "before_cursor_execute", synchronize_topology_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = [future.result(timeout=30) for future in [
                pool.submit(change_one, "advisements"), pool.submit(change_one, "product_data"),
            ]]
    finally:
        event.remove(application.engine, "before_cursor_execute", synchronize_topology_lock)
    assert sorted(row["status"] for row in responses) == [200, 409], responses
    winner = next(row for row in responses if row["status"] == 200)
    assert version(api, project_id) == initial_version + 1
    with application.SessionLocal() as session:
        entries = session.scalars(select(dossier.DossierEntry).where(
            dossier.DossierEntry.project_id == project_id)).all()
        assert len(entries) == 1 and entries[0].code == winner["code"]
        assert entries[0].updated_by == BADGES["supervisor"]
        assert session.scalar(select(func.count()).select_from(dossier.DossierEvent).where(
            dossier.DossierEvent.project_id == project_id)) == events_before + 1
        assert session.scalar(select(func.count()).select_from(application.Audit)) == audits_before + 1
        assert session.scalar(select(func.count()).select_from(dossier.DossierReview).where(
            dossier.DossierReview.project_id == project_id)) == 0
    assert packet(api, item_id)["percent"] == 0
    return {"response_codes": [200, 409], "new_check_entries": 1, "new_events": 1,
            "new_audit_rows": 1, "approval_invented": False}


def verify_readonly_dossier_progress_and_immutable_downloads(application, api):
    from test_dossier import TODAY, issued_fixture, issue_project, project, signed, version
    from test_progress import database_state

    project_id = "PG-DOSSIER-SNAPSHOT"
    item_id = "PG-DOSSIER-SNAPSHOT-SPOOL"
    item_issue = issued_fixture(api, item_id, project_id=project_id)
    signed(issue_project(api, project_id))
    project_issue = project(api, project_id)["latest_project_issue"]
    assert len(item_issue["print_sha256"]) == len(project_issue["print_sha256"]) == 64
    signed(api.post(f"/api/dossier/projects/{project_id}/handovers", {
        "expected_version": version(api, project_id), "issue_id": project_issue["id"],
        "channel": "physical", "recipient": "Synthetic PostgreSQL receiver",
        "organization": "Local isolated QA fixture", "reference": "PG-PHYSICAL-DISPATCH",
        "notes": "Printed test packet dispatch actually recorded for this fixture.", "occurred_on": TODAY,
    }, role="supervisor"))
    dispatch = project(api, project_id)["handovers"][-1]
    signed(api.post(f"/api/dossier/handovers/{dispatch['id']}/receipt", {
        "expected_version": version(api, project_id), "recipient": "Synthetic PostgreSQL receiver",
        "reference": "PG-PHYSICAL-RECEIPT", "notes": "The separate receipt was explicitly recorded.",
        "occurred_on": TODAY,
    }, role="supervisor"))
    before = database_state(api)
    unsafe_statements = []

    def observe_queries(connection, cursor, statement, parameters, context, many):
        sql = statement.lstrip().upper()
        if sql.startswith(("INSERT", "UPDATE", "DELETE")) or "FOR UPDATE" in sql or "PG_ADVISORY_XACT_LOCK" in sql:
            unsafe_statements.append(statement)

    event.listen(application.engine, "before_cursor_execute", observe_queries)
    try:
        for path in ("/api/dossier/catalog", "/api/dossier/projects", f"/api/dossier/projects/{project_id}",
                     f"/api/dossier/items/{item_id}", f"/api/dossier/issues/{item_issue['id']}",
                     f"/api/dossier/issues/{project_issue['id']}/print", "/api/progress/projects",
                     f"/api/progress/projects/{project_id}"):
            response = api.get(path)
            assert response.status_code == 200, response.text
        for issue in (item_issue, project_issue):
            printed = api.get(f"/api/dossier/issues/{issue['id']}/print")
            assert printed.status_code == 200
            assert hashlib.sha256(printed.content).hexdigest() == issue["print_sha256"]
            response = api.get(f"/api/dossier/issues/{issue['id']}/download")
            assert response.status_code == 200, response.text
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                assert archive.testzip() is None
                assert any(name.endswith(".pdf") for name in archive.namelist())
        # Exercise the same no-lock guarantee when these projections are
        # consumed from the PostgreSQL read-only Excel snapshot transaction.
        response = api.get("/api/exports/excel")
        assert response.status_code == 200, response.text
    finally:
        event.remove(application.engine, "before_cursor_execute", observe_queries)
    assert unsafe_statements == [], "A GET/export wrote data or acquired production write locks"
    assert database_state(api) == before, "Read-only views or export changed existing records"
    return {"progress_and_dossier_read_views": 12, "write_locks": 0, "mutations": 0,
            "immutable_snapshot_downloads": 2, "retained_print_hashes_verified": 2,
            "download_does_not_dispatch": True}


def verify_readonly_quality_gate_views(application, api):
    from test_flow import PROJECT
    from test_quality import assembly_at_step, create_requirement, workspace

    item_id = assembly_at_step(api, 20)
    workspace_id = workspace(api, project_id=PROJECT, name="Local read-only gate inspection")["workspace"]["id"]
    create_requirement(api, workspace_id, gate="pre_coating")
    locking_statements = []

    def observe_locks(connection, cursor, statement, parameters, context, many):
        if "FOR UPDATE" in statement.upper() or "pg_advisory_xact_lock" in statement:
            locking_statements.append(statement)

    event.listen(application.engine, "before_cursor_execute", observe_locks)
    try:
        detail = ok(api.get(f"/api/flow/items/{item_id}"))
        assert detail["flow"]["blockers"], "The configured unverified gate must remain visible"
        ok(api.get("/api/flow/items"))
        ok(api.get(f"/api/quality/workspaces/{workspace_id}"))
        ok(api.get("/api/quality/workspaces"))
    finally:
        event.remove(application.engine, "before_cursor_execute", observe_locks)
    assert locking_statements == [], "A read-only view acquired write locks out of production lock order"
    return {"flow_and_quality_read_views": 4, "write_locks": 0, "unverified_gate_visible": True}


def verify_concurrent_parts_allocation(application, api):
    """Real row/advisory locks must prevent double counting and scope races."""
    from test_progress import database_state

    item_id = make_spool(api, item_id="PG-PARTS-SPOOL")
    root = f"/api/parts/spools/{item_id}"
    initial = ok(api.put(root + "/plan", {
        "expected_version": 0, "reference": "PG-BOM-A", "reason": "Isolated quantity concurrency test",
        "lines": [{"part_number": "PG-PART-NO", "description": "Synthetic required flange", "required_qty": 1}],
    }))
    line = initial["lines"][0]
    for component in ("PG-PART-A", "PG-PART-B"):
        ok(api.post("/api/items", {
            "id": component, "description": "Synthetic physical part", "kind": "Part", "project": "TEST-PROJECT",
            "google_part_number": "PG-PART-NO", "location": "Test rack", "handler": BADGES["handler"], "welds_required": 0,
        }), 201)

    def race(calls):
        gate, seen = Barrier(2), set()

        def synchronize(connection, cursor, statement, parameters, context, many):
            if "pg_advisory_xact_lock" in statement and id(connection) not in seen:
                seen.add(id(connection))
                gate.wait(timeout=15)

        def submit(call):
            worker = TestAPI(application, application.SessionLocal)
            try:
                method, path, body = call
                response = worker.request(method, path, json=body)
                return {"status": response.status_code, "body": response.json()}
            finally:
                worker.client.close()

        event.listen(application.engine, "before_cursor_execute", synchronize)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = [future.result(timeout=30) for future in [pool.submit(submit, call) for call in calls]]
        finally:
            event.remove(application.engine, "before_cursor_execute", synchronize)
        assert sum(result["status"] in (200, 201) for result in responses) == 1, responses
        assert sum(result["status"] == 409 for result in responses) == 1, responses
        return sorted(result["status"] for result in responses)

    def allocation(component, version):
        return {"expected_version": version, "line_id": line["id"], "component_ids": [component],
                "reference": "PG-ASSIGN", "notes": "Actual isolated allocation for concurrency test"}

    allocation_codes = race([("POST", root + "/allocations", allocation(component, initial["version"]))
                             for component in ("PG-PART-A", "PG-PART-B")])
    assigned = ok(api.get(root))
    assert assigned["version"] == initial["version"] + 1
    assert assigned["totals"]["assigned_qty"] == assigned["totals"]["required_qty"] == 1
    assert assigned["totals"]["received_qty"] == assigned["totals"]["prepared_qty"] == 0
    winner = assigned["lines"][0]["components"][0]["id"]
    loser = next(component for component in ("PG-PART-A", "PG-PART-B") if component != winner)
    expanded = ok(api.put(root + "/plan", {
        "expected_version": assigned["version"], "reference": "PG-BOM-B", "reason": "Add a second real required piece",
        "lines": [{"id": line["id"], "part_number": "PG-PART-NO", "description": "Synthetic required flange", "required_qty": 2}],
    }))
    correction_codes = race([
        ("POST", root + "/allocations", allocation(loser, expanded["version"])),
        ("PUT", root + "/plan", {"expected_version": expanded["version"], "reference": "PG-BOM-C",
            "reason": "Competing controlled scope correction", "lines": [{"id": line["id"], "part_number": "PG-PART-NO",
                "description": "Synthetic required flange", "required_qty": 1}]}),
    ])
    current = ok(api.get(root))
    assert current["version"] == expanded["version"] + 1
    assert current["totals"]["required_qty"] == current["totals"]["assigned_qty"] in (1, 2)
    assert len(current["events"]) == 4
    assert len(current["lines"][0]["components"]) == current["totals"]["assigned_qty"]
    assert current["totals"]["received_qty"] == current["totals"]["prepared_qty"] == 0

    before, unsafe = database_state(api), []

    def observe(connection, cursor, statement, parameters, context, many):
        sql = statement.lstrip().upper()
        if sql.startswith(("INSERT", "UPDATE", "DELETE")) or "FOR UPDATE" in sql or "PG_ADVISORY_XACT_LOCK" in sql:
            unsafe.append(statement)

    event.listen(application.engine, "before_cursor_execute", observe)
    try:
        for path in ("/api/parts/spools", root, "/api/progress/projects/TEST-PROJECT", f"/api/tracking/spools/{item_id}", "/api/exports/excel"):
            response = api.get(path)
            assert response.status_code == 200, response.text
    finally:
        event.remove(application.engine, "before_cursor_execute", observe)
    assert unsafe == []
    assert database_state(api) == before
    return {"competing_allocations": allocation_codes, "allocation_vs_scope_correction": correction_codes,
            "duplicate_counting": False, "recorded_receipts_or_preparation_invented": False,
            "readonly_views_and_export": 5, "write_locks_on_reads": 0, "mutations_on_reads": 0}


def verify_concurrent_transfers(application, api):
    """Exercise actual PostgreSQL serialization across ordinary and flow moves."""
    from test_flow import action_body, create_item, detail, enroll
    from test_progress import database_state

    def race(calls):
        gate, seen = Barrier(2), set()

        def synchronize(connection, cursor, statement, parameters, context, many):
            if "pg_advisory_xact_lock" in statement and id(connection) not in seen:
                seen.add(id(connection))
                gate.wait(timeout=15)

        def submit(call):
            worker = TestAPI(application, application.SessionLocal)
            try:
                method, path, body = call
                response = worker.request(method, path, json=body)
                return {"status": response.status_code, "body": response.json()}
            finally:
                worker.client.close()

        event.listen(application.engine, "before_cursor_execute", synchronize)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = [future.result(timeout=30) for future in [pool.submit(submit, call) for call in calls]]
        finally:
            event.remove(application.engine, "before_cursor_execute", synchronize)
        assert sorted(row["status"] for row in responses) == [200, 409], responses
        return [200, 409]

    def transfer_body(item_id, **values):
        current = ok(api.get(f"/api/transfers/items/{item_id}"))
        return {"sender_badge": current["handler"], "handler": current["handler"],
                "location_id": "welding", "operational_status": "in_progress",
                "expected_transfer_version": current["version"], **values}

    item_id = create_item(api, "PG-TRANSFER-SAME-CUSTODIAN")
    body = transfer_body(item_id)
    ordinary_codes = race([("POST", f"/api/items/{item_id}/transfer", {**body, "location_id": location})
                           for location in ("welding", "fit_up")])
    current = ok(api.get(f"/api/transfers/items/{item_id}"))
    assert current["version"] == 1 and current["handler"] == BADGES["handler"]
    # Handler values alone cannot detect a location-only update or an ABA move.
    assert api.post(f"/api/items/{item_id}/transfer", body).status_code == 409
    ok(api.post(f"/api/items/{item_id}/transfer", transfer_body(item_id, handler=BADGES["welder"])))
    ok(api.post(f"/api/items/{item_id}/transfer", transfer_body(item_id, handler=BADGES["handler"])))
    assert api.post(f"/api/items/{item_id}/transfer", body).status_code == 409
    assert ok(api.get(f"/api/transfers/items/{item_id}"))["version"] == 3

    flow_codes = {}
    for step in (3, 6):
        routed_id = create_item(api, f"PG-TRANSFER-STEP-{step}")
        initial = enroll(api, routed_id, "component", start_step=step)
        ordinary = transfer_body(routed_id, location_id="production_staging", operational_status="queued")
        advance_body = action_body(api, routed_id)
        flow_codes[str(step)] = race([
            ("POST", f"/api/items/{routed_id}/transfer", ordinary),
            ("POST", f"/api/flow/items/{routed_id}/advance", advance_body),
        ])
        after = detail(api, routed_id)
        assert after["flow"]["version"] == initial["flow"]["version"] + 1
        assert after["transfer"]["version"] == 1
        advanced = after["flow"]["current_step"] == step + 1
        assert after["flow"]["current_step"] in (step, step + 1)
        assert after["production_process"]["version"] == initial["production_process"]["version"] + int(advanced)
        if not advanced:
            assert after["flow"]["step_entered_at"] == initial["flow"]["step_entered_at"]
        assert api.post(f"/api/flow/items/{routed_id}/advance", advance_body).status_code == 409

    custom = ok(api.post("/api/transfers/locations", {"label": "PG verified custom work bay"}), 201)
    location_codes = race([("PATCH", f"/api/transfers/locations/{custom['id']}", {
        "label": label, "active": False, "expected_version": custom["version"],
    }) for label in ("PG first renamed work bay", "PG second renamed work bay")])
    options = ok(api.get("/api/transfers/options"))
    updated = next(row for row in options["locations"] if row["id"] == custom["id"])
    assert updated["version"] == 2 and updated["active"] is False
    rejected = api.post(f"/api/items/{item_id}/transfer", transfer_body(item_id, location_id=custom["id"]))
    assert rejected.status_code == 422, rejected.text

    before, unsafe = database_state(api), []

    def observe(connection, cursor, statement, parameters, context, many):
        sql = statement.lstrip().upper()
        if sql.startswith(("INSERT", "UPDATE", "DELETE")) or "FOR UPDATE" in sql or "PG_ADVISORY_XACT_LOCK" in sql:
            unsafe.append(statement)

    paths = ("/api/transfers/options", f"/api/transfers/items/{item_id}", f"/api/items/{item_id}",
             "/api/flow/items/PG-TRANSFER-STEP-6", "/api/exports/excel")
    event.listen(application.engine, "before_cursor_execute", observe)
    try:
        for path in paths:
            response = api.get(path)
            assert response.status_code == 200, response.text
    finally:
        event.remove(application.engine, "before_cursor_execute", observe)
    assert unsafe == []
    assert database_state(api) == before
    return {"same_custodian_competing_moves": ordinary_codes, "stale_ABA_rejected": True,
            "ordinary_vs_numbered_step": flow_codes, "competing_location_edits": location_codes,
            "inactive_destination_rejected": True, "readonly_views_and_export": len(paths),
            "write_locks_on_reads": 0, "mutations_on_reads": 0}


def verify_excel_export(application, api):
    exports = importlib.import_module("exports")
    def row_counts():
        with application.engine.connect() as connection:
            return {
                table.name: connection.scalar(select(func.count()).select_from(table))
                for table in application.Base.metadata.sorted_tables
            }

    before = row_counts()
    export_reads = []

    def observe_export_query(connection, cursor, statement, parameters, context, many):
        if (
            context.execution_options.get("stream_results")
            and statement.lstrip().upper().startswith("SELECT")
            and "count(" not in statement.lower()
        ):
            # Use a separate DBAPI cursor to inspect the same transaction;
            # bypassing SQLAlchemy here avoids recursively invoking this hook.
            with connection.connection.cursor() as probe:
                probe.execute("SHOW transaction_read_only")
                read_only = probe.fetchone()[0]
                probe.execute("SHOW transaction_isolation")
                isolation = probe.fetchone()[0]
                probe.execute("SELECT pg_backend_pid()")
                backend_pid = probe.fetchone()[0]
            export_reads.append((read_only, isolation, backend_pid, bool(getattr(cursor, "name", None))))

    event.listen(application.engine, "before_cursor_execute", observe_export_query)
    try:
        response = api.get("/api/exports/excel")
    finally:
        event.remove(application.engine, "before_cursor_execute", observe_export_query)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheets = [sheet.attrib["name"] for sheet in workbook.findall("s:sheets/s:sheet", namespace)]
    expected_sheets = ["Export info", *[spec.sheet for spec in exports.TABLE_SPECS],
        "Process visits", "Process totals", "Flow steps", "Audit readiness",
        "Project progress", "Part progress", "Job Packet readiness", "Spool parts progress"]
    assert sheets[:len(expected_sheets)] == expected_sheets, sheets
    # A complete retained packet exceeds Excel's per-cell text limit. Its
    # exact JSON is preserved through normal Text overflow continuation rows.
    assert all(re.fullmatch(r"Text overflow(?: [0-9]+)?", name)
               for name in sheets[len(expected_sheets):]), sheets
    # Raw tables, the joined process query, and batched audit-readiness
    # dependency queries all stay in one physical read-only snapshot.
    assert len(export_reads) >= len(exports.TABLE_SPECS) + 2, export_reads
    assert all(read_only == "on" and isolation == "repeatable read" and server_cursor
               for read_only, isolation, _, server_cursor in export_reads), export_reads
    assert len({backend_pid for _, _, backend_pid, _ in export_reads}) == 1
    assert row_counts() == before, "Excel export changed database row counts"
    return {
        "response_code": 200, "business_sheets": len(exports.TABLE_SPECS) + 8, "rows_unchanged": True,
        "isolation": "repeatable read", "read_only": True, "server_side_queries": len(export_reads),
    }


def verify(dsn):
    url = local_test_url(dsn)
    if "main" in sys.modules:
        raise RuntimeError("Run this verifier in a fresh Python process to prevent database reuse")
    schema = "fabtrace_verify_" + uuid.uuid4().hex
    assert re.fullmatch(r"fabtrace_verify_[0-9a-f]{32}", schema)
    control = create_engine(url)
    application = api = None
    schema_created = False
    settings = {
        "DATABASE_URL": url.update_query_dict({"options": "-csearch_path=" + schema}).render_as_string(hide_password=False),
        "JWT_SECRET": TEST_SECRET, "COOKIE_SECURE": "false", "PUBLIC_BASE_URL": "http://testserver",
        "BOOTSTRAP_BADGE": "", "BOOTSTRAP_PIN": "",
    }
    previous = {key: os.environ.get(key) for key in (*settings, *LIBPQ_ROUTING_ENV)}
    try:
        # libpq permits environment hostaddr/service values to alter routing
        # even when a host was supplied. Require the validated DSN to decide it.
        for key in LIBPQ_ROUTING_ENV:
            os.environ.pop(key, None)
        os.environ.update(settings)
        with control.begin() as connection:
            assert connection.scalar(text("SELECT current_database()")) == url.database
            server_address = connection.scalar(text("SELECT inet_server_addr()"))
            assert server_address is None or is_loopback_host(str(server_address))
            server_version = connection.scalar(text("SHOW server_version"))
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            schema_created = True
        application = importlib.import_module("main")
        tracking = importlib.import_module("tracking")
        production = importlib.import_module("production")
        flow = importlib.import_module("flow")
        quality = importlib.import_module("quality")
        dossier = importlib.import_module("dossier")
        parts = importlib.import_module("parts")
        transfers = importlib.import_module("transfers")
        initializer = importlib.import_module("init_db")
        with application.engine.connect() as connection:
            assert connection.scalar(text("SELECT current_schema()")) == schema
        seed_legacy(application)
        assert set(inspect(application.engine).get_table_names(schema=schema)) == set(LEGACY_TABLES)
        legacy = snapshot_legacy(application)
        for _ in range(2):
            initializer.initialize()
            assert snapshot_legacy(application) == legacy, "Initialization rewrote legacy records"
        assert set(inspect(application.engine).get_table_names(schema=schema)) == set(application.Base.metadata.tables)
        issue_columns = {column["name"] for column in inspect(application.engine).get_columns("dossier_issues", schema=schema)}
        assert {"print_html", "print_sha256", "snapshot", "sha256"} <= issue_columns
        with application.SessionLocal() as session:
            assert session.query(tracking.SpoolPlan).count() == 0, "Migration silently enrolled legacy items"
            assert session.query(tracking.Weld).count() == 0, "Migration invented individual welds"
            assert session.query(production.SpoolProcessEvent).count() == 0, "Migration invented process timing history"
            assert session.query(flow.FlowPlan).count() == 0, "Migration invented fabrication travelers"
            assert session.query(flow.FlowEvent).count() == 0, "Migration invented fabrication step history"
            assert session.query(flow.FlowException).count() == 0, "Migration invented quality exceptions"
            assert session.query(flow.ComponentLink).count() == 0, "Migration invented parent-child links"
            for model in (quality.QualityWorkspace, quality.QualityRequirement, quality.QualityDocument,
                          quality.QualityEvidence, quality.QualityAction, quality.QualityReview, quality.QualityEvent):
                assert session.query(model).count() == 0, "Migration invented audit readiness or actual evidence"
            for model in (dossier.DossierProject, dossier.DossierEntry, dossier.DossierDocument,
                          dossier.DossierFile, dossier.DossierReview, dossier.DossierIssue,
                          dossier.DossierHandover, dossier.DossierEvent):
                assert session.query(model).count() == 0, "Migration invented packet scope, evidence, approval, or handover"
            for model in (parts.SpoolPartsPlan, parts.PartLine, parts.PartAllocation, parts.PartEvent):
                assert session.query(model).count() == 0, "Migration invented parts requirements, allocations or history"
            for model in (transfers.ItemTransferState, transfers.TransferLocation):
                assert session.query(model).count() == 0, "Migration invented transfer status or custom shop locations"

        api = TestAPI(application, application.SessionLocal)
        health = ok(api.get("/healthz", role=None))
        assert health["status"] == "ok" and health["version"] == application.APP_VERSION
        item_id = make_spool(api, item_id="PG-TEST-SPOOL")
        record = add_weld(api, item_id)
        complete_weld(api, item_id, record["id"])
        assert accept_weld(api, item_id, record["id"])["qa_accepted"] is True
        ok(api.post("/api/tracking/templates", {
            "code": "PG-TEST-TEMPLATE", "name": "Local immutable test template", "revision": 1,
            "requirements": [{"code": "PG-EXTRA", "label": "Local additional test requirement"}],
        }), 201)
        ok(api.post(f"/api/tracking/welds/{record['id']}/repairs", {
            "reason": "Local repair to verify preserved history and current-cycle evidence",
        }, role="inspector"), 201)
        process_concurrency = verify_concurrent_process_transition(application, production, api, item_id)
        flow_concurrency = verify_concurrent_flow_step(application, flow, production, api)
        quality_concurrency = verify_concurrent_quality_evidence(application, quality, api)
        quality_read_views = verify_readonly_quality_gate_views(application, api)
        dossier_concurrency = verify_concurrent_dossier_mutation(application, dossier, api)
        dossier_read_views = verify_readonly_dossier_progress_and_immutable_downloads(application, api)
        parts_concurrency = verify_concurrent_parts_allocation(application, api)
        transfer_concurrency = verify_concurrent_transfers(application, api)
        history = verify_history_protection(application, initializer, schema)
        concurrency = verify_concurrent_evidence(application, tracking, api, item_id, record["id"])
        excel_export = verify_excel_export(application, api)
        assert ok(api.get("/healthz", role=None))["status"] == "ok"
        with application.SessionLocal() as session:
            item = session.get(application.Item, "LEGACY-UPGRADE-CHECK")
            assert item.welds_done == 3 and item.welds_required == 7 and item.on_hold is True
            assert session.scalar(select(application.Audit).where(application.Audit.event == "LEGACY_TEST_SEED")) is not None
        return {
            "postgresql_version": server_version,
            "additive_upgrade": "passed",
            "idempotent_initializations": 2,
            "frozen_print_schema": {"print_html": True, "print_sha256": True},
            "legacy_rows_preserved": {name: len(rows) for name, rows in legacy.items()},
            "history_protection": history,
            "concurrent_evidence": concurrency,
            "concurrent_process_transition": process_concurrency,
            "concurrent_flow_step": flow_concurrency,
            "concurrent_quality_evidence": quality_concurrency,
            "concurrent_dossier_mutation": dossier_concurrency,
            "concurrent_parts_allocation": parts_concurrency,
            "concurrent_transfers": transfer_concurrency,
            "readonly_quality_gate_views": quality_read_views,
            "readonly_dossier_progress_and_exports": dossier_read_views,
            "excel_export": excel_export,
            "health": health["status"],
            "schema_cleanup": "completed",
        }
    finally:
        if api is not None:
            api.client.close()
        if application is not None:
            application.engine.dispose()
        if schema_created:
            with control.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn", required=True,
        help="Explicit psycopg DSN for a local loopback/Unix-socket database named fabtrace_test_*; only host/port query parameters are accepted",
    )
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.dsn), indent=2))
