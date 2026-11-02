"""Job-position authorization acceptance against real API mutations.

Fixtures are disposable local records. A denied action must leave every
persisted table unchanged, including audit, flow and process timing history.
"""

import json

import pytest
from fastapi.testclient import TestClient

from conftest import BADGES, TEST_PIN
from receiving_helpers import accept_arrival
from tracking_helpers import add_weld, approve, make_spool, ok, spool, weld
from test_admin import employee_body
from test_dossier import (
    PROJECT, TODAY, checks, entry, issue_item, issue_project, issued_fixture,
    make_project, packet, project, review, signed, upload, version,
)
from test_flow import action_body, create_item, detail as flow_detail, enroll
from test_progress import database_state
from test_quality import assembly_at_step
from test_transfers import transfer_body


TESTING_POSITIONS = ("pressure_testing_technician", "ndt")
TRADES = ("welder", "fitup_welder", "process_welder", "painter", "finisher", "misc", *TESTING_POSITIONS)
CURRENT_POSITIONS = {
    "admin": "Administrator", "supervisor": "Shop Foreman", "handler": "Material coordinator",
    "fitup_welder": "Fit-up welder", "process_welder": "Process welder", "inspector": "QA/QC",
    "painter": "Painter", "finisher": "Fab Prep Technician",
    "pressure_testing_technician": "Pressure Testing Technician", "ndt": "NDT",
}
LEGACY_POSITIONS = {"welder": "Welder", "misc": "Miscellaneous"}


def denied(api, request, status=403):
    before = database_state(api)
    response = request()
    assert response.status_code == status, response.text
    assert database_state(api) == before, "A denied action changed stored records"
    return response


def test_authenticated_position_catalog_and_control_hints_are_current_and_read_only(api):
    item_id = api.item()["id"]
    denied(api, lambda: api.get("/api/permissions", role=None), 401)
    before = database_state(api)
    for role in BADGES:
        catalog = ok(api.get("/api/permissions", role=role))
        identity = ok(api.get("/api/me", role=role))
        all_positions = {row["id"]: row for row in catalog["roles"]}
        positions = {key: row for key, row in all_positions.items() if row["selectable"] is True}
        legacy = {row["id"]: row for row in catalog["legacy_roles"]}
        assert {key: row["label"] for key, row in positions.items()} == CURRENT_POSITIONS
        assert {key: row["label"] for key, row in legacy.items()} == LEGACY_POSITIONS
        assert all(row["selectable"] is True for row in positions.values())
        assert all(row["selectable"] is False for row in legacy.values())
        # An already-open older select must still find the employee's saved
        # role instead of defaulting a legacy Welder edit to Administrator.
        assert {key: row for key, row in all_positions.items() if row["selectable"] is False} == legacy
        assert set(positions) | set(legacy) == set(BADGES)
        assert role in all_positions
        assert identity["role_label"] == {**positions, **legacy}[role]["label"]
        assert identity["permissions"] == catalog["current"]
        item = ok(api.get(f"/api/items/{item_id}", role=role))
        assert item["permissions"]["can_weld"] is (role in ("admin", "welder", "process_welder"))
        assert item["permissions"]["can_inspect"] is (role in ("admin", "inspector"))
    staff = ok(api.get("/api/admin/employees"))
    assert staff["roles"] == catalog["roles"] and staff["legacy_roles"] == catalog["legacy_roles"]
    assert {row["role"] for row in staff["employees"]} <= {row["id"] for row in staff["roles"]}
    assert database_state(api) == before


@pytest.mark.parametrize("position", ["fitup_welder", "process_welder", "painter", "finisher", *TESTING_POSITIONS])
def test_administrator_can_enroll_each_job_position_without_granting_management(api, position):
    badge = "NEW-" + position.upper().replace("_", "-")
    body = {"badge": badge, "name": "Synthetic " + position, "role": position, "pin": TEST_PIN}
    result = ok(api.post("/api/employees", body), 201)
    assert result["role"] == position and result["badge"] == badge
    identity = ok(api.get("/api/me", role=badge))
    assert identity["role"] == position
    denied(api, lambda: api.get("/api/admin/overview", role=badge))
    denied(api, lambda: api.post("/api/employees", {
        **body, "badge": badge + "-ADMIN", "role": "admin",
    }, role=badge))


@pytest.mark.parametrize("position", ["welder", "misc"])
def test_legacy_positions_may_be_retained_for_profile_edits_but_not_newly_assigned(api, position):
    denied(api, lambda: api.post("/api/employees", {
        "badge": "NEW-RETIRED-" + position.upper(), "name": "New retired-position attempt",
        "role": position, "pin": TEST_PIN,
    }), 422)
    target = BADGES["painter"]
    denied(api, lambda: api.patch(f"/api/admin/employees/{target}",
        employee_body(api, target, role=position)), 422)

    badge = BADGES[position]
    changed = ok(api.patch(f"/api/admin/employees/{badge}",
        employee_body(api, badge, name="Retained historical " + position)))
    assert changed["badge"] == badge and changed["role"] == position
    assert changed["role_label"] == LEGACY_POSITIONS[position]
    assert ok(api.get("/api/me", role=position))["name"] == changed["name"]
    disabled = ok(api.patch(f"/api/admin/employees/{badge}",
        employee_body(api, badge, active=False)))
    assert disabled["role"] == position and disabled["active"] is False
    enabled = ok(api.patch(f"/api/admin/employees/{badge}",
        employee_body(api, badge, active=True)))
    assert enabled["role"] == position and enabled["active"] is True
    events = [row for row in ok(api.get("/api/audit")) if row["event"] == "EMPLOYEE_UPDATED"]
    assert len(events) == 3
    assert all(row["details"]["from"]["role"] == row["details"]["to"]["role"] == position
               for row in events)


def test_roster_and_directory_show_current_name_and_position_without_changing_badge_identity(api, monkeypatch):
    monkeypatch.setattr(api.application, "PUBLIC_BASE_URL", "https://example.invalid")
    badge = BADGES["finisher"]
    qr_path = f"/api/employees/{badge}/qr.png"
    original_qr = api.get(qr_path)
    assert original_qr.status_code == 200 and original_qr.headers["content-type"] == "image/png"
    original_link = api.application.phone_link("badge", badge)
    original = next(row for row in ok(api.get("/api/employees")) if row["badge"] == badge)
    assert original["role_label"] == "Fab Prep Technician"
    assigned = ok(api.post("/api/items", {
        "id": "POSITION-STABLE-CUSTODY", "kind": "Part", "handler": badge, "welds_required": 0,
        "location": "Test preparation station",
    }), 201)

    changed = ok(api.patch(f"/api/admin/employees/{badge}", employee_body(api, badge,
        name="Updated testing employee", role="pressure_testing_technician")))
    assert changed["badge"] == badge and changed["role_label"] == "Pressure Testing Technician"
    for path in ("/api/employees", "/api/employees/directory"):
        current = next(row for row in ok(api.get(path)) if row["badge"] == badge)
        assert current["name"] == "Updated testing employee"
        assert current["role"] == "pressure_testing_technician"
        assert current["role_label"] == "Pressure Testing Technician"
    assert api.application.phone_link("badge", badge) == original_link
    assert api.get(qr_path).content == original_qr.content
    assert ok(api.get(f"/api/items/{assigned['id']}"))["handler"] == badge
    event = next(row for row in ok(api.get("/api/audit")) if row["event"] == "EMPLOYEE_UPDATED")
    assert event["details"]["from"]["badge"] == event["details"]["to"]["badge"] == badge


def test_changed_job_assignment_revokes_session_and_new_login_uses_new_controls(api):
    item_id = api.item(welds_required=1)["id"]
    badge = BADGES["welder"]
    with TestClient(api.application.app) as worker:
        ok(worker.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        body = employee_body(api, badge, role="painter")
        changed = ok(api.patch(f"/api/admin/employees/{badge}", body))
        assert changed["role"] == "painter"
        denied(api, lambda: worker.post(f"/api/items/{item_id}/weld", json={
            "count": 1, "weld_ids": "W01", "notes": "Old role must be revoked",
        }), 401)
        ok(worker.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        assert ok(worker.get("/api/me"))["role"] == "painter"
        denied(api, lambda: worker.post(f"/api/items/{item_id}/weld", json={
            "count": 1, "weld_ids": "W01", "notes": "New position lacks welding permission",
        }))


@pytest.mark.parametrize("authorized", ["admin", "welder", "process_welder"])
def test_legacy_weld_logging_requires_a_production_welding_position(api, authorized):
    item_id = api.item(welds_required=1)["id"]
    body = {"count": 1, "weld_ids": "W01", "notes": "Synthetic weld completion"}
    for role in ("supervisor", "handler", "inspector", "fitup_welder", "painter", "finisher", "misc", *TESTING_POSITIONS):
        denied(api, lambda role=role: api.post(f"/api/items/{item_id}/weld", body, role=role))
    result = ok(api.post(f"/api/items/{item_id}/weld", body, role=authorized))
    assert result["welds_done"] == 1
    event = next(row for row in ok(api.get(f"/api/items/{item_id}/audit")) if row["event"] == "WELDS_COMPLETED")
    assert event["actor"] == BADGES[authorized]


def test_fitup_and_process_welders_have_distinct_operations_and_keep_real_actor_ids(api):
    item_id = make_spool(api)
    accept_arrival(api, item_id)
    record = add_weld(api, item_id)
    route = f"/api/tracking/welds/{record['id']}/work"
    for role in ("process_welder", "supervisor", "handler", "inspector", "painter", "finisher", "misc", *TESTING_POSITIONS):
        denied(api, lambda role=role: api.post(route, {"operation": "fitup"}, role=role))
    ok(api.post(route, {"operation": "fitup", "notes": "Fit-up by assigned trade"}, role="fitup_welder"))
    for requirement in weld(api, item_id, record["id"])["requirements"]:
        if requirement["stage"] == "before_welding":
            approve(api, item_id, requirement["id"])
    for operation in ("root", "fill_cap", "complete"):
        for role in ("fitup_welder", "supervisor", "handler", "inspector", "painter", "finisher", "misc", *TESTING_POSITIONS):
            denied(api, lambda role=role, operation=operation: api.post(route, {"operation": operation}, role=role))
        ok(api.post(route, {"operation": operation}, role="process_welder"))
    result = weld(api, item_id, record["id"])
    assert result["production_complete"] is True
    assert result["completed_by"] == BADGES["process_welder"]
    actors = {row["operation"]: row["actor"] for row in result["work"]}
    assert actors == {"fitup": BADGES["fitup_welder"], **{op: BADGES["process_welder"] for op in ("root", "fill_cap", "complete")}}


@pytest.mark.parametrize("step,authorized,forbidden", [
    (2, "inspector", ("handler", "supervisor", "welder", "finisher")),
    (7, "finisher", ("handler", "supervisor", "welder", "painter")),
    (10, "fitup_welder", ("handler", "supervisor", "process_welder", "finisher")),
    (14, "process_welder", ("handler", "supervisor", "fitup_welder", "painter")),
    (21, "painter", ("handler", "supervisor", "welder", "finisher")),
])
def test_numbered_production_steps_require_the_correct_job_and_denials_are_atomic(api, step, authorized, forbidden):
    if step == 21:
        item_id = assembly_at_step(api, 21)
    else:
        component = step < 9
        item_id = create_item(api, f"PERMISSION-STEP-{step}", kind="Part" if component else "Spool")
        enroll(api, item_id, "component" if component else "spool", start_step=step)
    route = f"/api/flow/items/{item_id}/advance"
    body = action_body(api, item_id)
    before = flow_detail(api, item_id)
    for role in forbidden:
        detail = ok(api.get(f"/api/flow/items/{item_id}", role=role))
        assert "advance" not in detail["allowed_actions"]
        denied(api, lambda role=role: api.post(route, body, role=role))
    allowed = ok(api.get(f"/api/flow/items/{item_id}", role=authorized))
    assert "advance" in allowed["allowed_actions"]
    result = ok(api.post(route, body, role=authorized))
    assert result["flow"]["current_step"] == step + 1
    assert len(result["events"]) == len(before["events"]) + 1
    assert result["events"][-1]["actor"] == BADGES[authorized]


def test_trade_badge_handoff_does_not_confer_manufacturing_or_inspection_control(api):
    item_id = create_item(api, "PERMISSION-CUSTODY", kind="Spool")
    enroll(api, item_id, "spool", start_step=14)
    before = flow_detail(api, item_id)
    body = transfer_body(api, item_id, handler=BADGES["painter"], location_id="blast_paint", operational_status="queued")
    ok(api.post(f"/api/items/{item_id}/transfer", body, role="painter"))
    after = flow_detail(api, item_id)
    assert after["item"]["handler"] == BADGES["painter"]
    assert after["flow"]["current_step"] == before["flow"]["current_step"]
    assert after["production_process"]["events"] == before["production_process"]["events"]
    assert after["flow"]["steps"] == before["flow"]["steps"]
    denied(api, lambda: api.post(f"/api/flow/items/{item_id}/advance", action_body(api, item_id), role="painter"))
    denied(api, lambda: api.post(f"/api/items/{item_id}/inspect", {
        "kind": "Dimensional", "result": "Pass", "report": "TEST-FORBIDDEN-QA", "measurements": "Synthetic observation",
    }, role="painter"))


@pytest.mark.parametrize("owner,key,other", [
    ("fitup_welder", "fit_up", "painter"),
    ("process_welder", "welding", "fitup_welder"),
    ("painter", "coating", "welder"),
    ("finisher", "cutting_beveling", "painter"),
    ("inspector", "nde", "process_welder"),
    ("handler", "dispatch", "misc"),
    ("misc", "custom", "welder"),
    ("pressure_testing_technician", "nde", "handler"),
    ("ndt", "nde", "handler"),
])
def test_manual_timing_is_scoped_to_position_for_start_pause_resume_and_finish(api, owner, key, other):
    item_id = make_spool(api, planned=0, zero_weld_reason="Synthetic non-welded fixture")
    accept_arrival(api, item_id)
    route = f"/api/tracking/spools/{item_id}/process"
    start = {"action": "start", "expected_version": 0, "process_key": key}
    if key == "custom":
        start["process_name"] = "Miscellaneous support task"
    denied(api, lambda: api.post(route, start, role=other))
    current = ok(api.post(route, start, role=owner), 201)
    for action in ("pause", "resume", "finish"):
        body = {"action": action, "expected_version": current["version"], "notes": "Synthetic station timing"}
        denied(api, lambda body=body: api.post(route, body, role=other))
        current = ok(api.post(route, body, role=owner), 201)
    assert current["status"] == "finished"
    assert {row["actor"] for row in current["events"]} == {BADGES[owner]}


@pytest.mark.parametrize("position", TESTING_POSITIONS)
def test_testing_timers_retain_arrival_and_post_fabrication_traceability_gates(api, position):
    from test_heat_deadline import receive
    item_id = create_item(api, "POSITION-TESTING-TRACEABILITY", kind="Spool")
    route = f"/api/tracking/spools/{item_id}/process"
    start = {"action": "start", "expected_version": 0, "process_key": "nde"}
    rejected = denied(api, lambda: api.post(route, start, role=position), 409)
    assert "receiving_blockers" in rejected.text

    receive(api, item_id, heat="", reference="")
    rejected = denied(api, lambda: api.post(route, start, role=position), 409)
    assert "heat_blockers" in rejected.text and "heat number" in rejected.text and "MTR reference" in rejected.text
    receive(api, item_id, heat="TEST-CURRENT-HEAT", reference="TEST-CURRENT-MTR")
    started = ok(api.post(route, start, role=position), 201)
    assert started["status"] == "running" and started["events"][-1]["actor"] == BADGES[position]


def test_manual_move_requires_both_departing_and_receiving_process_authority(api):
    item_id = make_spool(api, planned=0, zero_weld_reason="Synthetic non-welded fixture")
    accept_arrival(api, item_id)
    route = f"/api/tracking/spools/{item_id}/process"
    current = ok(api.post(route, {"action": "start", "expected_version": 0, "process_key": "welding"}, role="process_welder"), 201)
    body = {"action": "move", "expected_version": current["version"], "process_key": "coating"}
    denied(api, lambda: api.post(route, body, role="process_welder"))
    denied(api, lambda: api.post(route, body, role="painter"))
    coordinated = ok(api.post(route, body, role="supervisor"), 201)
    assert coordinated["current"]["process_key"] == "coating"
    assert coordinated["events"][-1]["actor"] == BADGES["supervisor"]
    denied(api, lambda: api.post(f"/api/items/{item_id}/weld", {"count": 1, "weld_ids": "W01"}, role="supervisor"))


def test_numbered_timer_permissions_follow_current_step_without_advancing_it(api):
    item_id = create_item(api, "PERMISSION-NUMBERED-TIMER")
    initial = enroll(api, item_id, "component", start_step=7)
    route = f"/api/tracking/spools/{item_id}/process"
    body = {"action": "pause", "expected_version": initial["production_process"]["version"], "notes": "Preparation paused"}
    for role in ("painter", "welder", "inspector", "misc", *TESTING_POSITIONS):
        view = ok(api.get(f"/api/flow/items/{item_id}", role=role))
        assert "pause" not in view["allowed_actions"]
        denied(api, lambda role=role: api.post(route, body, role=role))
    paused = ok(api.post(route, body, role="finisher"), 201)
    ok(api.post(route, {"action": "resume", "expected_version": paused["version"]}, role="supervisor"), 201)
    assert flow_detail(api, item_id)["flow"]["current_step"] == 7
    assert flow_detail(api, item_id)["events"] == initial["events"]


@pytest.mark.parametrize("position", TESTING_POSITIONS)
@pytest.mark.parametrize("step", [17, 18])
def test_testing_positions_control_only_the_testing_clock_without_flow_or_qa_authority(api, position, step):
    item_id = assembly_at_step(api, step)
    initial = flow_detail(api, item_id)
    route = f"/api/tracking/spools/{item_id}/process"
    viewer = ok(api.get(f"/api/flow/items/{item_id}", role=position))
    assert "pause" in viewer["allowed_actions"]
    assert "advance" not in viewer["allowed_actions"] and "fail" not in viewer["allowed_actions"]
    denied(api, lambda: api.post(f"/api/flow/items/{item_id}/advance", action_body(api, item_id), role=position))
    if step == 18:
        denied(api, lambda: api.post(f"/api/flow/items/{item_id}/fail", {
            "expected_version": initial["flow"]["version"], "return_step": 17,
            "reference": "TEST-UNAUTHORIZED-RETURN", "reason": "A testing position cannot sign the QA disposition",
        }, role=position))
    denied(api, lambda: api.post(f"/api/items/{item_id}/inspect", {
        "kind": "Dimensional", "result": "Pass", "report": "TEST-SELF-APPROVAL",
        "measurements": "A testing position cannot accept dimensions",
    }, role=position))
    for action in ("move", "finish"):
        denied(api, lambda action=action: api.post(route, {
            "action": action, "expected_version": initial["production_process"]["version"],
            **({"process_key": "nde"} if action == "move" else {}),
        }, role=position), 409)
    paused = ok(api.post(route, {"action": "pause",
        "expected_version": initial["production_process"]["version"],
        "notes": "Testing technician paused the current testing work"}, role=position), 201)
    assert "resume" in paused["permissions"]["allowed_actions"]
    resumed = ok(api.post(route, {"action": "resume", "expected_version": paused["version"]}, role=position), 201)
    assert resumed["status"] == "running" and resumed["current"]["process_key"] == f"clm_{step:02d}"
    assert {row["actor"] for row in resumed["events"][-2:]} == {BADGES[position]}
    after = flow_detail(api, item_id)
    assert after["events"] == initial["events"]
    assert after["flow"]["version"] == initial["flow"]["version"]
    assert after["flow"]["current_step"] == step
    assert {key: after["item"].get(key) for key in ("released", "dimensional", "weld")} == {
        key: initial["item"].get(key) for key in ("released", "dimensional", "weld")}


@pytest.mark.parametrize("owner,allowed,forbidden", [
    ("painter", "painter", "welder"),
    ("finisher", "finisher", "painter"),
    ("fitup_welder", "welder", "process_welder"),
    ("process_welder", "welder", "fitup_welder"),
    ("welder", "welder", "process_welder"),
    ("misc", "misc", "handler"),
    ("pressure_testing_technician", "pressure_testing_technician", "ndt"),
    ("ndt", "ndt", "pressure_testing_technician"),
])
def test_requirement_owner_scopes_evidence_without_granting_qa_acceptance(api, owner, allowed, forbidden):
    item_id = make_spool(api, planned=0, zero_weld_reason="Synthetic non-welded fixture")
    accept_arrival(api, item_id)
    req = ok(api.post(f"/api/tracking/spools/{item_id}/requirements", {
        "code": "POSITION-RECORD", "label": "Assigned-position supporting record", "stage": "release",
        "owner_role": owner, "evidence_required": True, "source": "Synthetic controlled job requirement",
    }), 201)
    route = f"/api/tracking/requirements/{req['id']}/evidence"
    body = {"expected_version": req["version"], "reference": "TEST-POSITION-EVIDENCE", "notes": "Actual fixture record", "result": "recorded"}
    denied(api, lambda: api.post(route, body, role=forbidden))
    recorded = ok(api.post(route, body, role=allowed), 201)
    assert recorded["status"] == "submitted"
    denied(api, lambda: api.post(f"/api/tracking/requirements/{req['id']}/review", {
        "expected_version": recorded["version"], "decision": "accepted", "notes": "Attempted worker self-approval",
    }, role=allowed))
    recorded = ok(api.post(route, {**body, "expected_version": recorded["version"]}, role="supervisor"), 201)
    reviewed = ok(api.post(f"/api/tracking/requirements/{req['id']}/review", {
        "expected_version": recorded["version"], "decision": "accepted", "notes": "QA verified supporting record",
    }, role="inspector"))
    assert reviewed["status"] == "accepted"


def test_payload_identity_or_role_claims_cannot_grant_welding_or_admin_authority(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    denied(api, lambda: api.post(f"/api/tracking/welds/{record['id']}/work", {
        "operation": "fitup", "actor": BADGES["welder"], "role": "admin",
    }, role="painter"), 422)
    denied(api, lambda: api.patch(f"/api/admin/employees/{BADGES['painter']}", {
        **employee_body(api, BADGES["painter"]), "role": "admin",
    }, role="painter"))
    assert weld(api, item_id, record["id"])["work"] == []


def test_free_text_legacy_rework_close_is_a_management_decision(api):
    item_id = api.item(welds_required=0)["id"]
    item = ok(api.post(f"/api/items/{item_id}/rework", {
        "kind": "Correction", "reason": "Synthetic unspecified mixed-trade correction", "assigned": BADGES["finisher"],
    }, role="inspector"), 201)
    rework_id = item["reworks"][0]["id"]
    route = f"/api/items/{item_id}/rework/{rework_id}/close"
    for role in TRADES:
        denied(api, lambda role=role: api.post(route, {"notes": "Unscoped closure attempt"}, role=role))
    result = ok(api.post(route, {"notes": "Supervisor verified the recorded correction"}, role="supervisor"))
    assert result["reworks"][0]["closed_by"] == BADGES["supervisor"]
    assert result["reinspection_due"] is True


@pytest.mark.parametrize("role,codes,sections", [
    ("painter", ("surface", "coating"), ("08",)),
    ("finisher", ("surface", "packaging"), ("08", "09")),
    ("welder", ("procedures", "brazing_bonding"), ("03",)),
    ("fitup_welder", ("procedures", "brazing_bonding"), ("03",)),
    ("process_welder", ("procedures", "brazing_bonding"), ("03",)),
    ("handler", ("materials", "packaging", "packing_slip"), ("02", "09")),
    ("pressure_testing_technician", ("pressure",), ("06",)),
    ("ndt", ("nde",), ("04",)),
])
def test_job_packet_writers_are_scoped_to_their_trade_and_cannot_sign_qa(api, role, codes, sections):
    item_id = make_project(api)
    for code in codes:
        signed(entry(api, item_id, code, role=role))
    for section in sections:
        signed(upload(api, role=role, section=section, code="TEST-POSITION-" + section, item_id=item_id))
    forbidden_code = "coating" if "coating" not in codes else "procedures"
    denied(api, lambda: entry(api, item_id, forbidden_code, role=role))
    denied(api, lambda: upload(api, role=role, section="01", code="TEST-OTHER-SECTION"))
    denied(api, lambda: review(api, item_id, codes[0], role=role))
    denied(api, lambda: issue_item(api, item_id, role=role))
    assert all(row["actor"] == BADGES[role] for row in project(api)["documents"])


def test_misc_has_no_job_packet_writing_or_qa_authority(api):
    item_id = make_project(api)
    for code in ("procedures", "surface", "coating", "packaging", "advisements"):
        denied(api, lambda code=code: entry(api, item_id, code, role="misc"))
    denied(api, lambda: upload(api, role="misc", section="09"))
    denied(api, lambda: issue_item(api, item_id, role="misc"))


@pytest.mark.parametrize("shared", [False, True])
def test_trade_cannot_supersede_restricted_document_by_relabelling_its_section(api, shared):
    item_id = make_project(api)
    scope = None if shared else item_id
    signed(upload(api, role="admin", code="CONTROLLED-CROSS-SECTION", revision="A", section="03", item_id=scope))
    # A manager's later correction does not erase the earlier restricted
    # identity; authorization must inspect all revisions, not only the latest.
    signed(upload(api, role="admin", code="CONTROLLED-CROSS-SECTION", revision="B", section="08", item_id=scope))
    denied(api, lambda: upload(api, role="painter", code="CONTROLLED-CROSS-SECTION",
        revision="C", section="08", item_id=scope))
    signed(upload(api, role="painter", code="SEPARATE-COATING-RECORD", revision="A", section="08", item_id=scope))
    restricted = [row for row in project(api)["documents"] if row["code"] == "CONTROLLED-CROSS-SECTION"]
    assert {row["revision"] for row in restricted} == {"A", "B"}


def test_handler_can_record_packet_dispatch_and_receipt_but_cannot_issue_it(api):
    issued_fixture(api)
    denied(api, lambda: issue_project(api, role="handler"))
    signed(issue_project(api))
    issued = project(api)["latest_issue"]
    body = {"expected_version": version(api), "issue_id": issued["id"], "channel": "physical",
        "recipient": "Synthetic recipient", "organization": "Synthetic customer", "reference": "TEST-HANDLER-DISPATCH",
        "notes": "Existing approved packet physically handed over", "occurred_on": TODAY}
    denied(api, lambda: api.post(f"/api/dossier/projects/{PROJECT}/handovers", body, role="misc"))
    result = signed(api.post(f"/api/dossier/projects/{PROJECT}/handovers", body, role="handler"))
    dispatch = next(row for row in result["handovers"] if row["event"] == "dispatch")
    assert dispatch["actor"] == BADGES["handler"]
    signed(api.post(f"/api/dossier/handovers/{dispatch['id']}/receipt", {
        "expected_version": version(api), "recipient": "Synthetic confirming receiver", "reference": "TEST-HANDLER-RECEIPT",
        "notes": "Receipt of the issued packet independently confirmed", "occurred_on": TODAY,
    }, role="handler"))
    assert next(row for row in project(api)["handovers"] if row["event"] == "receipt")["actor"] == BADGES["handler"]


def test_user_permission_metadata_does_not_change_frozen_packet_fingerprints_or_records(api):
    issued = issued_fixture(api)
    item_id = "DOSSIER-ISSUED"
    original = packet(api, item_id)
    fingerprints = {code: row["fingerprint"] for code, row in checks(original).items()}
    frozen = ok(api.get(f"/api/dossier/issues/{issued['id']}"))
    before = database_state(api)
    for role in BADGES:
        current = ok(api.get(f"/api/dossier/items/{item_id}", role=role))
        assert current["latest_issue"]["current"] is True
        assert current["latest_issue"]["sha256"] == issued["sha256"]
        assert {code: row["fingerprint"] for code, row in checks(current).items()} == fingerprints
        assert ok(api.get(f"/api/dossier/issues/{issued['id']}", role=role)) == frozen
    assert database_state(api) == before
    # Permission hints belong to the authenticated view, never physical or
    # quality evidence whose digest establishes a retained issued revision.
    frozen_records = frozen["snapshot"]["packet"]["records"]
    assert "tracking" in frozen_records
    assert '"permissions"' not in json.dumps(frozen_records)
    assert '"allowed_operations"' not in json.dumps(frozen_records)
