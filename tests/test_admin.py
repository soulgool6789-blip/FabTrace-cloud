"""Explicit administrator dispositions with preserved fabrication facts.

All records are isolated local fixtures. Administrative release is exercised
as the requested exception, never as fabricated inspection or work evidence.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import BADGES, TEST_PIN
from tracking_helpers import add_weld, ok
from test_flow import (
    PROJECT, action_body, advance, create_item, detail as flow_detail, enroll,
    inspect_dimensions,
)
from test_progress import database_state, part as progress_part
from test_dossier import check as packet_check, configure, packet, physical_release
from test_quality import assembly_at_step


ROOT = "/api/admin"
REASON = "Administrator reviewed this synthetic exception and authorized its disposition"


def detail(api, item_id, role="admin"):
    return ok(api.get(f"{ROOT}/items/{item_id}", role=role))


def disposition_body(api, item_id, **values):
    return {"expected_version": detail(api, item_id)["version"], "reason": REASON,
            "reference": "SYNTHETIC-ADMIN-AUTHORIZATION", **values}


def release(api, item_id, **values):
    from receiving_helpers import ensure_scope_arrival
    ensure_scope_arrival(api, item_id)
    return ok(api.post(f"{ROOT}/items/{item_id}/release", disposition_body(api, item_id, **values)))


def return_to_work(api, item_id, **values):
    return ok(api.post(f"{ROOT}/items/{item_id}/return-to-work", disposition_body(api, item_id, **values)))


def employee(api, badge):
    return next(row for row in ok(api.get(ROOT + "/employees"))["employees"] if row["badge"] == badge)


def employee_body(api, badge, **values):
    row = employee(api, badge)
    return {"expected_version": row["version"], "name": row["name"], "role": row["role"],
            "active": row["active"], "reason": REASON, **values}


def edit_employee(api, badge, **values):
    return ok(api.patch(f"{ROOT}/employees/{badge}", employee_body(api, badge, **values)))


def events(api, item_id):
    return ok(api.get(f"/api/items/{item_id}/audit"))


def rejected(api, response, before, expected=(409, 422)):
    assert response.status_code in expected, response.text
    assert database_state(api) == before


@pytest.mark.parametrize("role", [None, "supervisor", "inspector", "handler", "welder"])
def test_administration_endpoints_require_current_administrator_authority(api, role):
    item_id = api.item()["id"]
    body = disposition_body(api, item_id)
    person_body = employee_body(api, BADGES["welder"], name="Unauthorized correction")
    before = database_state(api)
    expected = 401 if role is None else 403
    for path in (ROOT + "/overview", ROOT + "/items", f"{ROOT}/items/{item_id}", ROOT + "/employees"):
        assert api.get(path, role=role).status_code == expected
    for action in ("release", "return-to-work"):
        assert api.post(f"{ROOT}/items/{item_id}/{action}", body, role=role).status_code == expected
    assert api.post(f"{ROOT}/items/{item_id}/custody", {
        **body, "handler": BADGES["handler"], "location_id": "welding", "operational_status": "queued",
    }, role=role).status_code == expected
    assert api.patch(f"{ROOT}/employees/{BADGES['welder']}", person_body, role=role).status_code == expected
    assert api.post(f"{ROOT}/employees/{BADGES['welder']}/pin", {
        "expected_version": person_body["expected_version"], "pin": "Synthetic-reset-PIN-1234", "reason": REASON,
    }, role=role).status_code == expected
    assert database_state(api) == before


def test_admin_read_views_are_pure_and_do_not_invent_access_or_release_state(api):
    item_id = create_item(api, "ADMIN-READ-ONLY", kind="Spool")
    before = database_state(api)
    record = detail(api, item_id)
    assert len(record["version"]) == 64 and int(record["version"], 16) >= 0
    assert record["release"]["mode"] == "not_released"
    assert record["release"]["active_override"] is False
    assert record["release"]["override"] is None
    assert record["blockers"]
    listing = ok(api.get(ROOT + "/items", params={"search": item_id, "limit": 1, "offset": 0}))
    assert listing["total"] == 1 and listing["items"][0]["id"] == item_id
    assert listing["items"][0]["release_mode"] == "not_released"
    assert ok(api.get(ROOT + "/items", params={"search": "NO-MATCH"}))["total"] == 0
    staff = ok(api.get(ROOT + "/employees"))
    assert staff["active_admins"] == 1 and all(row["version"] == 0 for row in staff["employees"])
    assert api.get(ROOT + "/overview").status_code == 200
    assert api.get(ROOT + "/items/NO-SUCH-ITEM").status_code == 404
    assert database_state(api) == before


def test_admin_can_release_legacy_item_despite_missing_welds_inspection_hold_and_rework(api):
    item_id = api.item(welds_required=2)["id"]
    ok(api.post(f"/api/items/{item_id}/rework", {
        "kind": "Dimensional correction", "reason": "Synthetic unresolved fabrication defect",
        "assigned": BADGES["welder"],
    }, role="inspector"), 201)
    with api.session_factory() as session:
        session.get(api.application.Item, item_id).on_hold = True
        session.commit()
    original = ok(api.get(f"/api/items/{item_id}"))
    assert api.post(f"/api/items/{item_id}/release", {"reference": "ORDINARY-QA-RELEASE"}).status_code == 409
    reviewed = detail(api, item_id)
    released = release(api, item_id)
    assert released["item"]["released"] is True
    control = released["release"]
    assert control["mode"] == "admin_override" and control["active_override"] is True
    assert control["qa_released"] is False
    override = control["override"]
    assert override["reason"] == REASON and override["actor"] == BADGES["admin"]
    assert override["reference"] == "SYNTHETIC-ADMIN-AUTHORIZATION" and override["at"]
    assert override["bypassed_blockers"] == reviewed["blockers"]
    current = ok(api.get(f"/api/items/{item_id}"))
    for key in ("welds_required", "welds_done", "dimensional", "weld", "on_hold", "reinspection_due",
                "dimension_at", "weld_at", "last_work_at", "inspections"):
        assert current[key] == original[key], key
    # Release changes the signed-in viewer's available action, not the
    # underlying rework record. Compare every persisted rework field.
    assert [{k: v for k, v in row.items() if k != "can_close"} for row in current["reworks"]] == [
        {k: v for k, v in row.items() if k != "can_close"} for row in original["reworks"]]
    assert original["reworks"][0]["can_close"] is True
    assert current["reworks"][0]["can_close"] is False
    assert current["release_control"] == control
    decisions = [row for row in events(api, item_id) if row["event"] == "ADMIN_RELEASE_OVERRIDE"]
    assert len(decisions) == 1 and decisions[0]["id"] == override["audit_id"]
    assert decisions[0]["actor"] == BADGES["admin"]
    assert not any(row["event"] == "FINAL_RELEASE" for row in events(api, item_id))


@pytest.mark.parametrize("changes", [
    {"reason": "   "}, {"reason": "x" * 3001}, {"reason": "bad\x00reason"},
    {"expected_version": "stale"}, {"expected_version": True},
    {"actor": BADGES["inspector"]}, {"released_at": "2020-01-01"}, {"reference": "x" * 501},
])
def test_admin_release_rejects_invalid_or_forged_input_without_side_effects(api, changes):
    item_id = api.item()["id"]
    body = disposition_body(api, item_id, **changes)
    before = database_state(api)
    rejected(api, api.post(f"{ROOT}/items/{item_id}/release", body), before, (422,))


def test_admin_decision_token_rejects_stale_changes_duplicate_release_and_aba(api):
    item_id = api.item()["id"]
    stale = disposition_body(api, item_id)
    ok(api.patch(f"/api/items/{item_id}/part-number", {"google_part_number": "REVIEWED-PART-2"}))
    before = database_state(api)
    rejected(api, api.post(f"{ROOT}/items/{item_id}/release", stale), before, (409,))
    first = disposition_body(api, item_id)
    release(api, item_id)
    before = database_state(api)
    rejected(api, api.post(f"{ROOT}/items/{item_id}/release", first), before, (409,))
    return_to_work(api, item_id)
    before = database_state(api)
    rejected(api, api.post(f"{ROOT}/items/{item_id}/release", first), before, (409,))
    assert detail(api, item_id)["release"]["mode"] == "not_released"


@pytest.mark.parametrize("kind,route,step,next_step,status", [
    ("Spool", "spool", 9, 16, "active"),
    ("Assembly", "assembly", 17, 23, "active"),
    ("Part", "component", 1, None, "admin_released"),
])
def test_admin_release_records_explicit_route_disposition_without_completed_work(api, kind, route, step, next_step, status):
    item_id = create_item(api, "ADMIN-ROUTE-" + route.upper(), kind=kind, planned=1 if kind == "Spool" else 0)
    initial = enroll(api, item_id, route, expected_children=1 if route == "assembly" else 0)
    assert initial["flow"]["current_step"] == step
    before_tracking = ok(api.get(f"/api/tracking/spools/{item_id}")) if route != "component" else None
    released = release(api, item_id)
    current = flow_detail(api, item_id)
    assert current["item"]["released"] is True
    assert current["release_control"]["mode"] == "admin_override"
    assert current["flow"]["current_step"] == next_step
    assert current["flow"]["status"] == status
    assert current["flow"]["version"] == initial["flow"]["version"] + 1
    assert not any(row["status"] == "completed" for row in current["flow"]["steps"])
    assert current["production_process"]["version"] == initial["production_process"]["version"] + 1
    assert current["flow"]["completed_at"] is None
    assert released["release"]["override"]["prior_flow"]
    row = progress_part(api, item_id)
    assert row["administrative_release"] is True and row["release_mode"] == "admin_override"
    assert row["fabrication_finished"] is False and row["completed_steps"] == 0
    assert row["progress_percent"] == 0 and row["blocked"] is True
    if before_tracking:
        after_tracking = ok(api.get(f"/api/tracking/spools/{item_id}"))
        assert after_tracking["welds"] == before_tracking["welds"]
        assert after_tracking["requirements"] == before_tracking["requirements"]
    returned = return_to_work(api, item_id)
    restored = flow_detail(api, item_id)
    assert returned["release"]["mode"] == "not_released"
    assert returned["release"]["active_override"] is False
    assert restored["flow"]["status"] == "active" and restored["flow"]["current_step"] == step
    assert restored["flow"]["version"] == current["flow"]["version"] + 1
    assert restored["item"]["released"] is False
    assert len([row for row in events(api, item_id) if row["event"] == "ADMIN_RETURN_TO_WORK"]) == 1


def test_admin_override_preserves_individual_weld_records_and_does_not_approve_qa_packet(api):
    item_id = create_item(api, "ADMIN-WELD-FACTS", kind="Spool", planned=1)
    from receiving_helpers import accept_arrival
    accept_arrival(api, item_id)
    add_weld(api, item_id)
    ok(api.post(f"/api/tracking/spools/{item_id}/holds", {"reason": "Synthetic open engineering disposition"}), 201)
    configure(api)
    before = ok(api.get(f"/api/tracking/spools/{item_id}"))
    release(api, item_id)
    after = ok(api.get(f"/api/tracking/spools/{item_id}"))
    assert after["welds"] == before["welds"]
    assert after["requirements"] == before["requirements"]
    assert after["holds"] == before["holds"]
    assert after["summary"]["ready_to_release"] is False
    dossier = packet(api, item_id)
    assert dossier["item"]["release_control"]["mode"] == "admin_override"
    assert any("admin" in text.lower() for text in dossier["blockers"])
    assert packet_check(api, item_id, "release")["status"] not in ("accepted", "not_applicable")


def test_even_otherwise_ready_administrative_release_is_distinct_from_qa_approval(api):
    item_id = create_item(api, "ADMIN-READY-EXCEPTION", kind="Spool")
    inspect_dimensions(api, item_id)
    configure(api)
    release(api, item_id)
    assert detail(api, item_id)["release"]["qa_released"] is False
    assert progress_part(api, item_id)["fabrication_finished"] is False
    assert any("admin" in text.lower() for text in packet(api, item_id)["blockers"])
    return_to_work(api, item_id)
    physical_release(api, item_id)
    ordinary = detail(api, item_id)
    assert ordinary["release"]["mode"] == "qa"
    assert ordinary["release"]["qa_released"] is True and ordinary["release"]["active_override"] is False
    assert ordinary["release"]["override"] is None
    assert not any("admin" in text.lower() for text in packet(api, item_id)["blockers"])


def test_normal_qa_release_retains_normal_review_basis_and_admin_return(api):
    item_id = create_item(api, "ADMIN-NORMAL-QA", kind="Spool")
    physical_release(api, item_id)
    configure(api)
    import dossier as dossier_module
    with api.session_factory() as session:
        item = session.get(api.application.Item, item_id)
        cfg = session.get(dossier_module.DossierProject, PROJECT)
        plan = session.get(dossier_module.SpoolPlan, item_id)
        user = session.get(api.application.Employee, BADGES["admin"])
        records = dossier_module._actual_records(session, item, plan, user)
        spec = next(row for row in dossier_module.CHECKS if row["code"] == "release")
        basis = dossier_module._check_basis(cfg, item, spec, None, records, [])
        assert set(basis["actual"]) == {"released", "at", "by", "requirements", "dimensional", "dimension_at", "holds", "reworks"}
        assert "administrative_override" not in records
    assert detail(api, item_id)["release"]["mode"] == "qa"
    returned = return_to_work(api, item_id)
    assert returned["item"]["released"] is False and returned["release"]["mode"] == "not_released"


def test_admin_custody_correction_can_resolve_released_item_with_inactive_custodian(api):
    item_id = api.item()["id"]
    release(api, item_id)
    edit_employee(api, BADGES["welder"], active=False)
    body = disposition_body(api, item_id, handler=BADGES["handler"], location_id="welding", operational_status="waiting_material")
    result = ok(api.post(f"{ROOT}/items/{item_id}/custody", body))
    assert result["item"]["handler"] == BADGES["handler"]
    assert result["item"]["location"] == "Welding" and result["item"]["released"] is True
    assert result["release"]["mode"] == "admin_override"
    ordinary = ok(api.get(f"/api/items/{item_id}"))
    assert ordinary["transfer"]["operational_status"] == "waiting_material"
    assert ordinary["transfer"]["version"] == 1
    custody_history = ok(api.get(f"/api/items/{item_id}/custody"))
    assert len(custody_history) == 1 and custody_history[0]["event"] == "ADMIN_CUSTODY_CORRECTION"
    assert custody_history[0]["details"]["badge_scans_recorded"] is False
    assert "sender_badge" not in custody_history[0]["details"]
    corrections = [row for row in events(api, item_id) if row["event"] == "ADMIN_CUSTODY_CORRECTION"]
    assert len(corrections) == 1 and corrections[0]["actor"] == BADGES["admin"]
    assert corrections[0]["details"]["reason"] == REASON
    before = database_state(api)
    no_op = disposition_body(api, item_id, handler=BADGES["handler"], location_id="current", operational_status="waiting_material")
    rejected(api, api.post(f"{ROOT}/items/{item_id}/custody", no_op), before, (409,))


def test_admin_custody_correction_invalidates_open_flow_and_handoff_forms(api):
    item_id = create_item(api, "ADMIN-CUSTODY-VERSION")
    enroll(api, item_id, "component")
    old_step = action_body(api, item_id)
    old_transfer = ok(api.get(f"/api/transfers/items/{item_id}"))
    before_flow = flow_detail(api, item_id)
    ok(api.post(f"{ROOT}/items/{item_id}/custody", disposition_body(api, item_id,
        handler=BADGES["welder"], location_id="material_storage", operational_status="queued")))
    after_flow = flow_detail(api, item_id)
    assert after_flow["flow"]["current_step"] == before_flow["flow"]["current_step"]
    assert after_flow["production_process"]["version"] == before_flow["production_process"]["version"]
    assert after_flow["flow"]["version"] == before_flow["flow"]["version"] + 1
    assert after_flow["transfer"]["version"] == old_transfer["version"] + 1
    before = database_state(api)
    rejected(api, api.post(f"/api/flow/items/{item_id}/advance", old_step), before, (409,))


def test_admin_return_does_not_erase_actual_shipment_or_delivery(api):
    item_id = assembly_at_step(api, 24)
    shipped = advance(api, item_id)
    assert shipped["flow"]["status"] == "shipped"
    before = database_state(api)
    body = disposition_body(api, item_id)
    rejected(api, api.post(f"{ROOT}/items/{item_id}/return-to-work", body), before, (409,))
    assert "return_to_work" not in detail(api, item_id)["allowed_actions"]
    delivered = ok(api.post(f"/api/flow/items/{item_id}/deliver", {
        "expected_version": shipped["flow"]["version"],
        "receipt_reference": "SYNTHETIC-RECEIPT", "recipient": "Synthetic receiving customer",
    }))
    assert delivered["flow"]["status"] == "delivered"
    before = database_state(api)
    body = disposition_body(api, item_id)
    rejected(api, api.post(f"{ROOT}/items/{item_id}/return-to-work", body), before, (409,))
    final = flow_detail(api, item_id)
    assert final["flow"]["shipped_at"] == shipped["flow"]["shipped_at"]
    assert final["flow"]["delivered_at"] == delivered["flow"]["delivered_at"]


@pytest.mark.parametrize("changes", [
    {"name": " "}, {"role": "owner"}, {"active": "false"}, {"expected_version": True},
    {"badge": "REPLACEMENT-BADGE"}, {"pin_hash": "forged"}, {"reason": " "},
])
def test_employee_controls_reject_bad_input_and_do_not_rename_badge_identity(api, changes):
    badge = BADGES["welder"]
    body = {**employee_body(api, badge), **changes}
    before = database_state(api)
    rejected(api, api.patch(f"{ROOT}/employees/{badge}", body), before, (422,))


def test_name_edit_is_versioned_audited_and_does_not_end_existing_session(api):
    badge = BADGES["welder"]
    with TestClient(api.application.app) as signed_in:
        ok(signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        old = employee_body(api, badge, name="Synthetic renamed employee")
        updated = ok(api.patch(f"{ROOT}/employees/{badge}", old))
        assert updated["name"] == "Synthetic renamed employee" and updated["version"] == old["expected_version"] + 1
        assert ok(signed_in.get("/api/me"))["name"] == updated["name"]
        before = database_state(api)
        rejected(api, api.patch(f"{ROOT}/employees/{badge}", old), before, (409,))
    audit = ok(api.get("/api/audit"))
    event = next(row for row in audit if row["event"] == "EMPLOYEE_UPDATED")
    assert event["actor"] == BADGES["admin"]
    assert "pin_hash" not in json.dumps(event) and TEST_PIN not in json.dumps(event)


def test_role_change_revokes_old_session_and_new_login_gets_current_authority(api):
    badge = BADGES["welder"]
    with TestClient(api.application.app) as signed_in:
        ok(signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        edit_employee(api, badge, role="supervisor")
        assert signed_in.get("/api/me").status_code == 401
        ok(signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        assert ok(signed_in.get("/api/me"))["role"] == "supervisor"
        assert signed_in.get(ROOT + "/overview").status_code == 403


def test_admin_can_promote_handler_to_admin_with_current_permissions_and_retained_identity(api):
    badge = BADGES['handler']
    ok(api.post('/api/items', {'id': 'POSITION-CHANGE-CUSTODY', 'kind': 'Part',
        'google_part_number': '000-PART', 'location': 'Synthetic receiving',
        'handler': badge, 'welds_required': 0}), 201)
    with api.session_factory() as session:
        person = session.get(api.application.Employee, badge)
        identity = (person.badge, person.name, person.active, person.pin_hash, person.created_at)
        item = session.get(api.application.Item, 'POSITION-CHANGE-CUSTODY')
        recorded_item = {column.name: getattr(item, column.name) for column in item.__table__.columns}
    with TestClient(api.application.app) as signed_in:
        ok(signed_in.post('/api/login', json={'badge': badge, 'pin': TEST_PIN}))
        assert signed_in.get(ROOT + '/overview').status_code == 403
        updated = edit_employee(api, badge, role='admin')
        assert updated['role'] == 'admin' and updated['active'] is True
        assert updated['reauthenticate'] is False, 'The acting administrator remains signed in'
        assert signed_in.get('/api/me').status_code == 401
        assert signed_in.get(ROOT + '/overview').status_code == 401
        ok(signed_in.post('/api/login', json={'badge': badge, 'pin': TEST_PIN}))
        account = ok(signed_in.get('/api/me'))
        assert account['role'] == 'admin' and account['role_label'] == 'Administrator'
        assert 'admin' in account['permissions']['capabilities']
        assert 'manage_production' in account['permissions']['capabilities']
        assert signed_in.get(ROOT + '/overview').status_code == 200
        assert ok(signed_in.get(ROOT + '/employees'))['active_admins'] == 2
    with api.session_factory() as session:
        person = session.get(api.application.Employee, badge)
        assert (person.badge, person.name, person.active, person.pin_hash, person.created_at) == identity
        item = session.get(api.application.Item, 'POSITION-CHANGE-CUSTODY')
        assert {column.name: getattr(item, column.name) for column in item.__table__.columns} == recorded_item
        events = session.scalars(select(api.application.Audit).where(
            api.application.Audit.event == 'EMPLOYEE_UPDATED')).all()
        assert len(events) == 1
        assert events[0].actor == BADGES['admin']
        assert events[0].details['from']['role'] == 'handler'
        assert events[0].details['to']['role'] == 'admin'
        assert events[0].details['existing_sessions_revoked'] is True


def test_deactivate_reactivate_keeps_old_session_revoked_and_history_identity(api):
    badge = BADGES["welder"]
    item_id = api.item()["id"]
    with TestClient(api.application.app) as signed_in:
        ok(signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        edit_employee(api, badge, active=False)
        assert signed_in.get("/api/me").status_code == 401
        assert badge not in {row["badge"] for row in ok(api.get("/api/employees/directory"))}
        assert signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}).status_code == 401
        edit_employee(api, badge, active=True)
        assert signed_in.get("/api/me").status_code == 401
        ok(signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        assert signed_in.get("/api/me").status_code == 200
    assert ok(api.get(f"/api/items/{item_id}"))["handler"] == badge


def test_pin_reset_revokes_old_session_without_exposing_any_authentication_secret(api):
    badge, new_pin = BADGES["welder"], "Synthetic-new-private-PIN-98765"
    with TestClient(api.application.app) as signed_in:
        ok(signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        body = {"expected_version": employee(api, badge)["version"], "pin": new_pin, "reason": REASON}
        updated = ok(api.post(f"{ROOT}/employees/{badge}/pin", body))
        assert updated["version"] == 1
        assert signed_in.get("/api/me").status_code == 401
        assert signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}).status_code == 401
        ok(signed_in.post("/api/login", json={"badge": badge, "pin": new_pin}))
        assert signed_in.get("/api/me").status_code == 200
    audit = ok(api.get("/api/audit"))
    assert any(row["event"] == "EMPLOYEE_PIN_RESET" for row in audit)
    wire = json.dumps([updated, employee(api, badge), audit])
    assert new_pin not in wire and TEST_PIN not in wire and "pin_hash" not in wire
    with api.session_factory() as session:
        stored = session.get(api.application.Employee, badge).pin_hash
        assert api.application.password_hash.verify(new_pin, stored)
        assert stored not in wire
    before = database_state(api)
    rejected(api, api.post(f"{ROOT}/employees/{badge}/pin", body), before, (409,))


def test_invalid_pin_requests_never_echo_the_submitted_secret(api):
    for private_pin in ("S3cr!", "PRIVATE-DO-NOT-ECHO-" + "x" * 130):
        calls = [
            ("/api/login", {"badge": BADGES["welder"], "pin": private_pin}, None),
            ("/api/employees", {"badge": "NEW-SYNTHETIC-USER", "name": "New synthetic user",
                "role": "handler", "pin": private_pin}, "admin"),
            (f"{ROOT}/employees/{BADGES['welder']}/pin", {
                "expected_version": 0, "pin": private_pin, "reason": REASON}, "admin"),
        ]
        for path, body, role in calls:
            before = database_state(api)
            response = api.post(path, body, role=role)
            rejected(api, response, before, (422,))
            assert private_pin not in response.text
            assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])


@pytest.mark.parametrize("changes", [{"active": False}, {"role": "supervisor"}])
def test_last_active_administrator_cannot_be_disabled_or_demoted(api, changes):
    badge = BADGES["admin"]
    body = employee_body(api, badge, **changes)
    before = database_state(api)
    rejected(api, api.patch(f"{ROOT}/employees/{badge}", body), before, (409,))
    assert ok(api.get(ROOT + "/employees"))["active_admins"] == 1


def test_admin_can_transfer_authority_then_demote_self_with_current_session_revocation(api):
    edit_employee(api, BADGES["supervisor"], role="admin")
    assert ok(api.get(ROOT + "/employees"))["active_admins"] == 2
    with TestClient(api.application.app) as signed_in:
        ok(signed_in.post("/api/login", json={"badge": BADGES["admin"], "pin": TEST_PIN}))
        body = employee_body(api, BADGES["admin"], role="supervisor")
        response = signed_in.patch(f"{ROOT}/employees/{BADGES['admin']}", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["reauthenticate"] is True
        assert signed_in.get(ROOT + "/overview").status_code == 401
        ok(signed_in.post("/api/login", json={"badge": BADGES["admin"], "pin": TEST_PIN}))
        assert signed_in.get(ROOT + "/overview").status_code == 403
        ok(signed_in.post("/api/login", json={"badge": BADGES["supervisor"], "pin": TEST_PIN}))
        assert ok(signed_in.get(ROOT + "/employees"))["active_admins"] == 1
