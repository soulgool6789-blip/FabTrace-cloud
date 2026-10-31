"""CLM's 24-step fabrication traveler, custody and quality boundaries.

All records here are isolated fixtures. The happy path uses the same physical
component, spool and assembly identities throughout; checklist submission does
not stand in for existing weld evidence or quality approvals.
"""

import datetime as dt
import importlib

import pytest
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import accept_weld, add_weld, ok, ready_to_weld


ROOT = "/api/flow"
PROJECT = "FLOW-PRJ"


def detail(api, item_id):
    return ok(api.get(f"{ROOT}/items/{item_id}"))


def catalog(api):
    return ok(api.get(ROOT + "/catalog"))


def create_item(api, item_id, kind="Part", planned=0, project=PROJECT):
    response = api.post("/api/tracking/projects", {"id": project, "name": "Local flow project " + project})
    assert response.status_code in (201, 409), response.text
    ok(api.post("/api/items", {
        "id": item_id, "description": "Local CLM flow fixture", "kind": kind,
        "project": project, "drawing": "FLOW-ISO-REV-A", "location": "Receiving",
        "handler": BADGES["handler"], "welds_required": planned,
    }), 201)
    if kind in ("Spool", "Assembly"):
        ok(api.post(f"/api/tracking/spools/{item_id}/plan", {
            "project_id": project, "planned_welds": planned,
            "zero_weld_reason": "This test package has no additional welded joints" if not planned else "",
        }))
    return item_id


def enroll(api, item_id, route, *, start_step=None, expected_children=0, **values):
    from receiving_helpers import ensure_scope_arrival
    ensure_scope_arrival(api, item_id)
    body = {"route": route, "expected_children": expected_children, **values}
    if route == "spool" and expected_children == 0:
        body.setdefault("material_reference", "TEST-EXISTING-MATERIAL-REGISTER")
    if start_step is not None:
        body.update({"start_step": start_step, "baseline_reference": "TEST-CONTROLLED-BASELINE", "baseline_reason": "Test work was already in progress when the traveler was enrolled"})
    return ok(api.post(f"{ROOT}/items/{item_id}/start", body), 201)


def action_body(api, item_id, **values):
    record = detail(api, item_id)
    current = record["flow"]["current"]
    body = {
        "expected_version": record["flow"]["version"],
        "confirmations": [row["id"] for row in current["checks"]],
    }
    if current["requires_scan"]:
        body["scanned_item_id"] = item_id
    if current["requires_reference"]:
        body["reference"] = f"TEST-REPORT-STEP-{current['number']}"
    if current["requires_handoff"]:
        body.update({"sender_badge": record["item"]["handler"], "receiver_badge": BADGES["handler"],
                     "location_id": "production_staging", "operational_status": "queued",
                     "expected_transfer_version": record["transfer"]["version"]})
    if current["number"] == 3:
        body.update({"location_id": "material_storage", "expected_transfer_version": record["transfer"]["version"]})
    if current["number"] == 24:
        body.update({"carrier": "Test carrier", "shipment_reference": "TEST-BOL-123", "destination": "Test customer delivery site"})
    if current["number"] == 17:
        body["scanned_child_ids"] = [row["item_id"] for row in record["spools"]]
    return {**body, **values}


def advance(api, item_id, *, role="admin", **values):
    return ok(api.post(f"{ROOT}/items/{item_id}/advance", action_body(api, item_id, **values), role=role))


def assert_current(record, step):
    assert record["flow"]["current_step"] == step
    assert record["flow"]["current"]["number"] == step


def inspect_dimensions(api, item_id):
    return ok(api.post(f"/api/items/{item_id}/inspect", {
        "kind": "Dimensional", "result": "Pass", "report": "TEST-FLOW-DIMENSIONS",
        "measurements": "Verified dimensions and alignment against the test isometric",
    }, role="inspector"))


def complete_physical_weld(api, weld_id):
    for operation in ("root", "fill_cap", "complete"):
        ok(api.post(f"/api/tracking/welds/{weld_id}/work", {
            "operation": operation, "notes": "Local flow test welding operation",
        }, role="welder"))


def assign_component(api, component_id, spool_id):
    current = detail(api, component_id)
    return ok(api.post(f"{ROOT}/items/{component_id}/assign-component", {
        "expected_version": current["flow"]["version"], "spool_id": spool_id,
        "reference": "TEST-BOM-REV-A",
    }), 201)


def link_spool(api, assembly_id, spool_id):
    current = detail(api, assembly_id)
    return ok(api.post(f"{ROOT}/items/{assembly_id}/link-spool", {
        "expected_version": current["flow"]["version"], "spool_id": spool_id,
        "reference": "TEST-ASSEMBLY-BOM",
    }), 201)


def completed_spool(api, item_id):
    create_item(api, item_id, kind="Spool")
    enroll(api, item_id, "spool", start_step=15)
    inspect_dimensions(api, item_id)
    advance(api, item_id, role="inspector")
    advance(api, item_id)
    return item_id


def test_catalog_covers_the_photo_routes_and_explicit_quality_and_shipping_points(api):
    definition = catalog(api)
    steps = definition["steps"]
    assert [row["number"] for row in steps] == list(range(1, 25))
    assert {row["number"] for row in steps if row["qa"]} == {2, 11, 15, 19, 22}
    assert [(row["id"], row["first_step"], row["last_step"]) for row in definition["routes"]] == [
        ("component", 1, 8), ("spool", 9, 16), ("assembly", 17, 24),
    ]
    for row in steps:
        assert row["title"] and row["roles"] and row["checks"]
        assert len({check["id"] for check in row["checks"]}) == len(row["checks"])
    for number in (11, 15, 19, 22):
        assert set(steps[number - 1]["roles"]) == {"admin", "inspector"}
    assert steps[10]["return_steps"] == [10]
    assert steps[14]["return_steps"] == [14]
    assert set(steps[18]["return_steps"]) == {17, 18}
    assert set(steps[21]["return_steps"]) == {17, 18, 19, 20, 21}


def test_flow_requires_auth_and_does_not_invent_existing_history(api):
    item_id = create_item(api, "FLOW-AUTH")
    assert api.get(ROOT + "/catalog", role=None).status_code == 401
    assert api.get(ROOT + "/items", role=None).status_code == 401
    assert api.get(f"{ROOT}/items/{item_id}", role=None).status_code == 401
    assert api.post(f"{ROOT}/items/{item_id}/start", {"route": "component"}, role=None).status_code == 401
    before = detail(api, item_id)
    assert before["flow"] is None
    assert before["events"] == []
    first = enroll(api, item_id, "component")
    assert_current(first, 1)
    assert not any(row["status"] in ("completed", "not_recorded") for row in first["flow"]["steps"])
    assert first["production_process"]["status"] == "running"
    assert len(first["production_process"]["visits"]) == 1


def test_all_twenty_four_steps_keep_component_spool_assembly_identity_and_confirm_delivery(api):
    component = create_item(api, "FLOW-COMPONENT")
    spool_id = create_item(api, "FLOW-SPOOL", kind="Spool", planned=1)
    assembly = create_item(api, "FLOW-ASSEMBLY", kind="Assembly")
    weld = add_weld(api, spool_id)
    enroll(api, component, "component")
    enroll(api, spool_id, "spool", expected_children=1)
    enroll(api, assembly, "assembly", expected_children=1)

    for step in range(1, 9):
        assert_current(detail(api, component), step)
        if step == 5:
            assign_component(api, component, spool_id)
        advance(api, component, role="inspector" if step == 2 else "admin", **({"target_spool_id": spool_id} if step == 5 else {}))
    component_done = detail(api, component)
    assert component_done["flow"]["current"] is None
    assert all(row["status"] == "completed" for row in component_done["flow"]["steps"])

    for step in range(9, 17):
        assert_current(detail(api, spool_id), step)
        if step == 10:
            ready_to_weld(api, spool_id, weld["id"])
        if step == 11:
            inspect_dimensions(api, spool_id)
        if step == 14:
            complete_physical_weld(api, weld["id"])
        if step == 15:
            accept_weld(api, spool_id, weld["id"])
            inspect_dimensions(api, spool_id)
        advance(api, spool_id, role="inspector" if step in (11, 15) else "admin")
    spool_done = detail(api, spool_id)
    assert spool_done["flow"]["current"] is None
    assert spool_done["item"]["released"] is True
    assert spool_done["item"]["id"] == spool_id
    assert len(spool_done["components"]) == 1
    assert spool_done["components"][0]["item_id"] == component

    link_spool(api, assembly, spool_id)
    for step in range(17, 25):
        assert_current(detail(api, assembly), step)
        if step in (19, 22):
            inspect_dimensions(api, assembly)
        advance(api, assembly, role="inspector" if step in (19, 22) else "admin")
    shipped = detail(api, assembly)
    assert shipped["flow"]["status"] == "shipped"
    assert shipped["flow"].get("delivered_at") is None
    assert shipped["item"]["released"] is True
    assert shipped["flow"]["current"] is None
    assert len(shipped["spools"]) == 1
    assert shipped["spools"][0]["item_id"] == spool_id
    assert api.post(f"{ROOT}/items/{assembly}/deliver", {
        "expected_version": shipped["flow"]["version"], "receipt_reference": "", "recipient": "",
    }).status_code == 422
    delivered = ok(api.post(f"{ROOT}/items/{assembly}/deliver", {
        "expected_version": shipped["flow"]["version"],
        "receipt_reference": "TEST-SIGNED-POD", "recipient": "Test customer receiver",
    }))
    assert delivered["flow"]["status"] == "delivered"
    assert delivered["flow"]["delivered_at"]
    assert delivered["flow"]["receipt_reference"] == "TEST-SIGNED-POD"
    assert delivered["flow"]["recipient"] == "Test customer receiver"
    for identity in (component, spool_id, assembly):
        record = detail(api, identity)
        assert record["item"]["id"] == identity
        assert record["production_process"]["current"] is None
        assert len(record["production_process"]["visits"]) == 8
        assert all(row["status"] == "finished" for row in record["production_process"]["visits"])
    with api.session_factory() as session:
        identities = session.scalars(select(api.application.Item.id)).all()
        assert set(identities) == {component, spool_id, assembly}


def test_baseline_marks_earlier_steps_not_recorded_and_requires_evidence(api):
    item_id = create_item(api, "FLOW-BASELINE", kind="Spool")
    response = api.post(f"{ROOT}/items/{item_id}/start", {
        "route": "spool", "start_step": 14, "expected_children": 0,
        "material_reference": "TEST-MATERIAL-REGISTER",
    })
    assert response.status_code in (409, 422), response.text
    assert detail(api, item_id)["flow"] is None
    record = enroll(api, item_id, "spool", start_step=14)
    assert_current(record, 14)
    assert {row["number"] for row in record["flow"]["steps"] if row["status"] == "not_recorded"} == set(range(9, 14))
    assert not any(row["status"] == "completed" for row in record["flow"]["steps"])
    assert len(record["production_process"]["visits"]) == 1
    assert api.post(f"{ROOT}/items/{item_id}/start", {"route": "spool", "material_reference": "TEST"}).status_code == 409


def test_step_cannot_advance_without_every_check_exact_scan_and_reference(api):
    item_id = create_item(api, "FLOW-CHECKS")
    enrolled = enroll(api, item_id, "component")
    route = f"{ROOT}/items/{item_id}/advance"
    complete = action_body(api, item_id)
    attempts = [
        {**complete, "confirmations": []},
        {**complete, "confirmations": complete["confirmations"][:-1]},
        {**complete, "scanned_item_id": "OTHER-PHYSICAL-COMPONENT"},
        {**complete, "scanned_item_id": ""},
        {**complete, "reference": ""},
        {**complete, "confirmations": complete["confirmations"] + ["invented_check"]},
        {**complete, "next_step": 8},
        {**complete, "actor": "SPOOFED"},
        {**complete, "at": "2000-01-01T00:00:00Z"},
    ]
    for body in attempts:
        response = api.post(route, body)
        assert response.status_code in (409, 422), response.text
    after = detail(api, item_id)
    assert after["flow"]["version"] == enrolled["flow"]["version"]
    assert after["events"] == enrolled["events"]
    assert_current(after, 1)


@pytest.mark.parametrize("role", ["handler", "welder", "supervisor"])
def test_only_quality_roles_can_approve_formal_spool_qa(api, role):
    item_id = create_item(api, "FLOW-QA-ROLE", kind="Spool")
    enrolled = enroll(api, item_id, "spool", start_step=11)
    response = api.post(f"{ROOT}/items/{item_id}/advance", action_body(api, item_id), role=role)
    assert response.status_code == 403, response.text
    assert detail(api, item_id)["events"] == enrolled["events"]


def test_handoff_requires_active_recipient_and_records_custody_and_location(api):
    item_id = create_item(api, "FLOW-HANDOFF")
    current = enroll(api, item_id, "component", start_step=6)
    route = f"{ROOT}/items/{item_id}/advance"
    for values in (
        {"receiver_badge": ""}, {"receiver_badge": "MISSING-BADGE"}, {"location_id": " "},
    ):
        response = api.post(route, action_body(api, item_id, **values))
        assert response.status_code in (404, 409, 422), response.text
    with api.session_factory() as session:
        session.get(api.application.Employee, BADGES["welder"]).active = False
        session.commit()
    assert api.post(route, action_body(api, item_id, receiver_badge=BADGES["welder"])).status_code == 404
    after = advance(api, item_id, receiver_badge=BADGES["handler"], location_id="fabrication_prep")
    location = next(row["label"] for row in ok(api.get("/api/transfers/options"))["locations"] if row["id"] == "fabrication_prep")
    assert after["flow"]["version"] == current["flow"]["version"] + 1
    assert after["item"]["handler"] == BADGES["handler"]
    assert after["item"]["location"] == location
    history = ok(api.get(f"/api/items/{item_id}/custody"))
    assert len(history) == 1
    assert history[0]["actor"] == BADGES["admin"]
    assert history[0]["details"]["to"]["handler"] == BADGES["handler"]
    assert history[0]["details"]["to"]["location"] == location


def test_stale_step_submit_is_atomic_and_does_not_create_second_visit(api):
    item_id = create_item(api, "FLOW-STALE")
    enroll(api, item_id, "component")
    body = action_body(api, item_id)
    first = ok(api.post(f"{ROOT}/items/{item_id}/advance", body))
    assert api.post(f"{ROOT}/items/{item_id}/advance", body).status_code == 409
    current = detail(api, item_id)
    assert current["flow"]["version"] == first["flow"]["version"]
    assert current["events"] == first["events"]
    assert current["production_process"]["events"] == first["production_process"]["events"]
    assert len(current["production_process"]["visits"]) == 2


def test_flow_controls_step_timers_and_manual_stage_changes_cannot_skip_it(api):
    item_id = create_item(api, "FLOW-CLOCK", kind="Spool")
    current = enroll(api, item_id, "spool")
    process_route = f"/api/tracking/spools/{item_id}/process"
    version = current["production_process"]["version"]
    for body in (
        {"action": "start", "expected_version": version, "process_key": "welding"},
        {"action": "move", "expected_version": version, "process_key": "welding"},
        {"action": "finish", "expected_version": version},
    ):
        assert api.post(process_route, body).status_code == 409
    assert_current(detail(api, item_id), 9)
    assert detail(api, item_id)["production_process"]["events"] == current["production_process"]["events"]


def test_numbered_steps_share_one_clock_and_rework_adds_a_new_visit(api, monkeypatch):
    item_id = create_item(api, "FLOW-EXACT-TIMING")
    flow = importlib.import_module("flow")
    production = importlib.import_module("production")
    now = [api.application.utcnow() + dt.timedelta(minutes=1)]
    monkeypatch.setattr(flow, "utcnow", lambda: now[0])
    monkeypatch.setattr(production, "utcnow", lambda: now[0])
    current = enroll(api, item_id, "component")
    assert current["production_process"]["current"]["process_key"] == "clm_01"
    now[0] += dt.timedelta(seconds=60)
    ok(api.post(f"/api/tracking/spools/{item_id}/process", {
        "action": "pause", "expected_version": current["production_process"]["version"],
        "notes": "Awaiting material documents",
    }, role="handler"), 201)
    now[0] += dt.timedelta(seconds=120)
    current = advance(api, item_id)
    timing = current["production_process"]
    assert timing["current"]["process_key"] == "clm_02" and timing["status"] == "running"
    first = timing["visits"][0]
    assert first["elapsed_seconds"] == 180
    assert first["active_seconds"] == 60
    assert first["paused_seconds"] == 120
    now[0] += dt.timedelta(seconds=30)
    failed = ok(api.post(f"{ROOT}/items/{item_id}/fail", {
        "expected_version": current["flow"]["version"], "reason": "Material certificate requires correction",
        "reference": "TEST-DOCUMENT-NCR",
    }, role="inspector"))
    assert len(failed["production_process"]["visits"]) == 3
    assert failed["production_process"]["visits"][1]["elapsed_seconds"] == 30
    now[0] += dt.timedelta(seconds=90)
    passed = advance(api, item_id, role="inspector", resolution="Correct material certificate reviewed and accepted")
    timing = passed["production_process"]
    assert timing["current"]["process_key"] == "clm_03"
    assert timing["totals"]["elapsed_seconds"] == 300
    assert timing["totals"]["active_seconds"] == 180
    assert timing["totals"]["paused_seconds"] == 120
    material_qa = next(row for row in timing["by_process"] if row["process_key"] == "clm_02")
    assert material_qa["visits"] == 2 and material_qa["elapsed_seconds"] == 120
    assert sum(row["ended_at"] is None for row in timing["visits"]) == 1
    assert all(left["ended_at"] == right["started_at"] for left, right in zip(timing["visits"], timing["visits"][1:]))


def test_spool_collection_requires_declared_components_and_completed_preparation(api):
    spool_id = create_item(api, "FLOW-COLLECT-SPOOL", kind="Spool")
    component = create_item(api, "FLOW-COLLECT-PART")
    enroll(api, spool_id, "spool", expected_children=1)
    enroll(api, component, "component", start_step=5)
    assert api.post(f"{ROOT}/items/{spool_id}/advance", action_body(api, spool_id)).status_code == 409
    assign_component(api, component, spool_id)
    assert api.post(f"{ROOT}/items/{spool_id}/advance", action_body(api, spool_id)).status_code == 409
    for step in range(5, 9):
        advance(api, component, **({"target_spool_id": spool_id} if step == 5 else {}))
    ready = advance(api, spool_id)
    assert_current(ready, 10)


def test_prepared_component_with_open_rework_cannot_be_issued_into_a_spool(api):
    spool_id = create_item(api, "FLOW-REWORK-CHILD-SPOOL", kind="Spool")
    component = create_item(api, "FLOW-REWORK-CHILD-PART")
    enroll(api, spool_id, "spool", expected_children=1)
    enroll(api, component, "component", start_step=5)
    assign_component(api, component, spool_id)
    for step in range(5, 9):
        advance(api, component, **({"target_spool_id": spool_id} if step == 5 else {}))
    response = api.post(f"/api/items/{component}/rework", {
        "kind": "Material", "reason": "Prepared material found damaged before fit-up",
        "assigned": BADGES["welder"],
    }, role="inspector")
    # A controlled-flow guard may reject this generic mutation. If it accepts
    # the rework ticket, child readiness must block the parent's next step.
    assert response.status_code in (201, 409), response.text
    if response.status_code == 201:
        issued = api.post(f"{ROOT}/items/{spool_id}/advance", action_body(api, spool_id))
        assert issued.status_code == 409, issued.text
        assert_current(detail(api, spool_id), 9)


def test_zero_component_scope_requires_material_register_and_assembly_requires_spools(api):
    spool_id = create_item(api, "FLOW-ZERO-SPOOL", kind="Spool")
    assembly = create_item(api, "FLOW-ZERO-ASSEMBLY", kind="Assembly")
    for item_id, route in ((spool_id, "spool"), (assembly, "assembly")):
        response = api.post(f"{ROOT}/items/{item_id}/start", {"route": route, "expected_children": 0})
        assert response.status_code in (409, 422), response.text
        assert detail(api, item_id)["flow"] is None


def test_component_assignment_rejects_cross_project_wrong_type_and_changes_after_selection(api):
    component = create_item(api, "FLOW-LINK-PART")
    spool_a = create_item(api, "FLOW-LINK-SPOOL-A", kind="Spool")
    spool_b = create_item(api, "FLOW-LINK-SPOOL-B", kind="Spool")
    other = create_item(api, "FLOW-LINK-OTHER", kind="Spool", project="FLOW-OTHER-PRJ")
    for item_id in (spool_a, spool_b):
        enroll(api, item_id, "spool", expected_children=1)
    enroll(api, other, "spool", expected_children=1)
    enroll(api, component, "component", start_step=5)
    for target in (component, other, "MISSING-SPOOL"):
        current = detail(api, component)
        response = api.post(f"{ROOT}/items/{component}/assign-component", {
            "expected_version": current["flow"]["version"], "spool_id": target,
        })
        assert response.status_code in (404, 409, 422), response.text
    assign_component(api, component, spool_a)
    advance(api, component, target_spool_id=spool_a)
    current = detail(api, component)
    response = api.post(f"{ROOT}/items/{component}/assign-component", {
        "expected_version": current["flow"]["version"], "spool_id": spool_b,
    })
    assert response.status_code == 409, response.text


def test_spool_final_qa_requires_weld_acceptance_and_cannot_use_release_endpoint_to_skip_flow(api):
    item_id = create_item(api, "FLOW-QA-GATES", kind="Spool", planned=1)
    record = add_weld(api, item_id)
    enroll(api, item_id, "spool", start_step=14)
    route = f"{ROOT}/items/{item_id}/advance"
    assert api.post(route, action_body(api, item_id), role="welder").status_code == 409
    ready_to_weld(api, item_id, record["id"])
    complete_physical_weld(api, record["id"])
    advance(api, item_id)
    assert_current(detail(api, item_id), 15)
    assert api.post(route, action_body(api, item_id), role="inspector").status_code == 409
    accept_weld(api, item_id, record["id"])
    inspect_dimensions(api, item_id)
    assert api.post(f"/api/items/{item_id}/release", {"reference": "BYPASS-ATTEMPT"}, role="inspector").status_code == 409
    approved = advance(api, item_id, role="inspector")
    assert approved["item"]["released"] is True
    assert_current(approved, 16)
    done = advance(api, item_id)
    assert done["flow"]["current"] is None


@pytest.mark.parametrize("route,kind,step,return_step", [
    ("component", "Part", 2, 2),
    ("spool", "Spool", 11, 10),
    ("spool", "Spool", 15, 14),
    ("assembly", "Assembly", 19, 18),
    ("assembly", "Assembly", 22, 21),
])
def test_quality_failure_opens_exception_and_routes_back_without_erasing_attempts(api, route, kind, step, return_step):
    item_id = create_item(api, f"FLOW-FAIL-{step}", kind=kind)
    current = enroll(api, item_id, route, start_step=step, expected_children=1 if route == "assembly" else 0)
    response = api.post(f"{ROOT}/items/{item_id}/fail", {
        "expected_version": current["flow"]["version"], "reason": "Test nonconformance requires documented rework",
        "reference": "TEST-NCR-123", "return_step": return_step,
    }, role="inspector")
    failed = ok(response)
    assert_current(failed, return_step)
    assert len(failed["exceptions"]) == 1
    assert failed["exceptions"][0]["closed_at"] is None
    assert len(failed["events"]) > len(current["events"])
    assert failed["events"][:len(current["events"])] == current["events"]
    assert len(failed["production_process"]["visits"]) == 2
    assert failed["production_process"]["visits"][0]["ended_at"] == failed["production_process"]["visits"][1]["started_at"]


def test_passing_failed_material_check_requires_documented_resolution(api):
    item_id = create_item(api, "FLOW-RESOLUTION")
    current = enroll(api, item_id, "component", start_step=2)
    ok(api.post(f"{ROOT}/items/{item_id}/fail", {
        "expected_version": current["flow"]["version"], "reason": "Dimensions outside test tolerance",
        "reference": "TEST-NCR-DIMENSIONS",
    }, role="inspector"))
    response = api.post(f"{ROOT}/items/{item_id}/advance", action_body(api, item_id), role="inspector")
    assert response.status_code in (409, 422), response.text
    passed = advance(api, item_id, role="inspector", resolution="Replacement component inspected to the correct drawing dimensions")
    assert_current(passed, 3)
    assert passed["exceptions"][0]["closed_at"]


def test_failed_weld_qa_requires_new_acceptance_and_resolution_before_release(api):
    item_id = create_item(api, "FLOW-WELD-NCR", kind="Spool", planned=1)
    weld = add_weld(api, item_id)
    enroll(api, item_id, "spool", start_step=14)
    ready_to_weld(api, item_id, weld["id"])
    complete_physical_weld(api, weld["id"])
    advance(api, item_id)
    accept_weld(api, item_id, weld["id"])
    inspect_dimensions(api, item_id)
    before = detail(api, item_id)
    failed = ok(api.post(f"{ROOT}/items/{item_id}/fail", {
        "expected_version": before["flow"]["version"], "reason": "NDE report needs corrected examination and review",
        "reference": "TEST-WELD-NCR", "return_step": 14,
    }, role="inspector"))
    assert_current(failed, 14)
    tracked = ok(api.get(f"/api/tracking/spools/{item_id}"))
    assert tracked["welds"][0]["production_complete"] is True
    assert tracked["welds"][0]["qa_accepted"] is False
    advance(api, item_id)
    response = api.post(f"{ROOT}/items/{item_id}/advance", action_body(api, item_id,
        resolution="Corrected examination supplied and reviewed"), role="inspector")
    assert response.status_code == 409, response.text
    unchanged = detail(api, item_id)
    assert unchanged["exceptions"][0]["closed_at"] is None
    assert unchanged["item"]["released"] is False
    accept_weld(api, item_id, weld["id"])
    inspect_dimensions(api, item_id)
    approved = advance(api, item_id, role="inspector", resolution="Corrected examination supplied and reviewed")
    assert approved["item"]["released"] is True
    assert approved["exceptions"][0]["closed_at"]
    assert approved["exceptions"][0]["closed_by"] == BADGES["inspector"]
    assert_current(approved, 16)


def test_delivery_is_rejected_before_shipment_and_shipment_fields_cannot_be_fabricated_by_skipping(api):
    item_id = create_item(api, "FLOW-NOT-SHIPPED", kind="Assembly")
    current = enroll(api, item_id, "assembly", expected_children=1)
    response = api.post(f"{ROOT}/items/{item_id}/deliver", {
        "expected_version": current["flow"]["version"], "receipt_reference": "TEST-POD", "recipient": "Test recipient",
    })
    assert response.status_code == 409, response.text
    assert_current(detail(api, item_id), 17)
    assert detail(api, item_id)["flow"].get("delivered_at") is None


def test_assembly_collection_needs_full_declared_scope_and_each_child_scan(api):
    assembly = create_item(api, "FLOW-COLLECT-ASSEMBLY", kind="Assembly")
    first = completed_spool(api, "FLOW-ASSEMBLY-SPOOL-A")
    second = completed_spool(api, "FLOW-ASSEMBLY-SPOOL-B")
    enroll(api, assembly, "assembly", expected_children=2)
    link_spool(api, assembly, first)
    route = f"{ROOT}/items/{assembly}/advance"
    assert api.post(route, action_body(api, assembly)).status_code == 409
    link_spool(api, assembly, second)
    for scanned in ([], [first], [first, first], [first, "WRONG-SPOOL"]):
        response = api.post(route, action_body(api, assembly, scanned_child_ids=scanned))
        assert response.status_code in (409, 422), response.text
    current = advance(api, assembly)
    assert_current(current, 18)
    assert {row["item_id"] for row in current["spools"]} == {first, second}


def test_parent_processing_freezes_child_reopen_and_requires_fresh_assembly_dimensions(api):
    assembly = create_item(api, "FLOW-FROZEN-ASSEMBLY", kind="Assembly")
    child = completed_spool(api, "FLOW-FROZEN-SPOOL")
    enroll(api, assembly, "assembly", expected_children=1)
    link_spool(api, assembly, child)
    advance(api, assembly)
    advance(api, assembly)
    assert_current(detail(api, assembly), 19)
    response = api.post(f"/api/items/{child}/reopen")
    assert response.status_code == 409, response.text
    assert detail(api, child)["item"]["released"] is True
    assert api.post(f"{ROOT}/items/{assembly}/advance", action_body(api, assembly), role="inspector").status_code == 409
    inspect_dimensions(api, assembly)
    approved = advance(api, assembly, role="inspector")
    assert_current(approved, 20)


def test_assembly_link_rejects_self_wrong_kind_other_project_and_duplicate_parent(api):
    first = create_item(api, "FLOW-LINK-ASSEMBLY-A", kind="Assembly")
    second = create_item(api, "FLOW-LINK-ASSEMBLY-B", kind="Assembly")
    part = create_item(api, "FLOW-LINK-NOT-SPOOL")
    child = completed_spool(api, "FLOW-LINK-GOOD-SPOOL")
    other = create_item(api, "FLOW-LINK-OTHER-SPOOL", kind="Spool", project="FLOW-OTHER-PRJ")
    enroll(api, first, "assembly", expected_children=1)
    enroll(api, second, "assembly", expected_children=1)
    for target in (first, second, part, other):
        current = detail(api, first)
        response = api.post(f"{ROOT}/items/{first}/link-spool", {
            "expected_version": current["flow"]["version"], "spool_id": target,
        })
        assert response.status_code in (409, 422), response.text
    link_spool(api, first, child)
    current = detail(api, second)
    response = api.post(f"{ROOT}/items/{second}/link-spool", {
        "expected_version": current["flow"]["version"], "spool_id": child,
    })
    assert response.status_code == 409, response.text


def test_failed_final_qa_preserves_old_steps_but_invalidates_current_downstream_approvals(api):
    assembly = create_item(api, "FLOW-REWORK-ASSEMBLY", kind="Assembly")
    child = completed_spool(api, "FLOW-REWORK-SPOOL")
    enroll(api, assembly, "assembly", expected_children=1)
    link_spool(api, assembly, child)
    for step in range(17, 22):
        if step == 19:
            inspect_dimensions(api, assembly)
        advance(api, assembly, role="inspector" if step == 19 else "admin")
    before = detail(api, assembly)
    assert_current(before, 22)
    assert all(row["status"] == "completed" for row in before["flow"]["steps"] if row["number"] in range(17, 22))
    failed = ok(api.post(f"{ROOT}/items/{assembly}/fail", {
        "expected_version": before["flow"]["version"], "reason": "Final test dimensions require assembly rework",
        "reference": "TEST-FINAL-NCR", "return_step": 18,
    }, role="inspector"))
    assert_current(failed, 18)
    assert failed["events"][:len(before["events"])] == before["events"]
    assert all(row["status"] != "completed" for row in failed["flow"]["steps"] if row["number"] in range(18, 23))
    assert next(row for row in failed["flow"]["steps"] if row["number"] == 17)["status"] == "completed"
    assert failed["item"]["dimensional"] != "Pass"
    advance(api, assembly)
    assert api.post(f"{ROOT}/items/{assembly}/advance", action_body(api, assembly), role="inspector").status_code == 409


def test_component_issue_found_after_spool_and_assembly_release_still_blocks_shipping(api):
    component = create_item(api, "FLOW-LATE-MATERIAL")
    spool_id = create_item(api, "FLOW-LATE-SPOOL", kind="Spool")
    assembly = create_item(api, "FLOW-LATE-ASSEMBLY", kind="Assembly")
    enroll(api, component, "component", start_step=5)
    enroll(api, spool_id, "spool", expected_children=1)
    assign_component(api, component, spool_id)
    for step in range(5, 9):
        advance(api, component, **({"target_spool_id": spool_id} if step == 5 else {}))
    for step in range(9, 17):
        if step == 15:
            inspect_dimensions(api, spool_id)
        advance(api, spool_id, role="inspector" if step in (11, 15) else "admin")
    enroll(api, assembly, "assembly", expected_children=1)
    link_spool(api, assembly, spool_id)
    for step in range(17, 24):
        if step in (19, 22):
            inspect_dimensions(api, assembly)
        advance(api, assembly, role="inspector" if step in (19, 22) else "admin")
    before = detail(api, assembly)
    assert_current(before, 24)
    assert before["item"]["released"] is True
    opened = api.post(f"/api/items/{component}/rework", {
        "kind": "Material", "reason": "Late material nonconformance identified before shipment",
        "assigned": BADGES["welder"],
    }, role="inspector")
    assert opened.status_code in (201, 409), opened.text
    if opened.status_code == 201:
        response = api.post(f"{ROOT}/items/{assembly}/advance", action_body(api, assembly))
        assert response.status_code == 409, response.text
        after = detail(api, assembly)
        assert_current(after, 24)
        assert after["flow"]["shipped_at"] is None
        assert after["events"] == before["events"]


def test_scope_correction_is_versioned_audited_and_cannot_remove_linked_children_or_restart_time(api):
    spool_id = create_item(api, "FLOW-SCOPE-SPOOL", kind="Spool")
    component = create_item(api, "FLOW-SCOPE-COMPONENT")
    enroll(api, spool_id, "spool", expected_children=2)
    enroll(api, component, "component", start_step=5)
    assign_component(api, component, spool_id)
    before = detail(api, spool_id)
    route = f"{ROOT}/items/{spool_id}/scope"
    body = {
        "expected_version": before["flow"]["version"], "expected_children": 1,
        "reason": "Correct declared component count to the approved BOM", "reference": "TEST-REVISED-BOM",
    }
    assert api.post(route, body, role="welder").status_code == 403
    assert api.post(route, {**body, "expected_children": 0, "material_reference": "TEST-MATERIAL-BASIS"}).status_code in (409, 422)
    corrected = ok(api.post(route, body, role="supervisor"))
    assert corrected["flow"]["expected_children"] == 1
    assert corrected["flow"]["version"] == before["flow"]["version"] + 1
    assert len(corrected["events"]) == len(before["events"]) + 1
    assert corrected["events"][-1]["action"] == "scope"
    assert corrected["events"][-1]["actor"] == BADGES["supervisor"]
    assert corrected["production_process"]["events"] == before["production_process"]["events"]
    assert corrected["production_process"]["current"]["started_at"] == before["production_process"]["current"]["started_at"]
    assert api.post(route, body).status_code == 409
    for step in range(5, 9):
        advance(api, component, **({"target_spool_id": spool_id} if step == 5 else {}))
    current = advance(api, spool_id)
    assert_current(current, 10)
    assert api.post(route, {**body, "expected_version": current["flow"]["version"], "expected_children": 2}).status_code == 409


def test_scope_correction_requires_basis_and_keeps_assembly_minimum_one(api):
    assembly = create_item(api, "FLOW-SCOPE-ASSEMBLY", kind="Assembly")
    current = enroll(api, assembly, "assembly", expected_children=1)
    route = f"{ROOT}/items/{assembly}/scope"
    body = {
        "expected_version": current["flow"]["version"], "expected_children": 2,
        "reason": "Approved scope correction", "reference": "TEST-SCOPE-REV-B",
    }
    for values in ({"expected_children": 0}, {"reason": ""}, {"reference": ""}, {"expected_version": True}):
        response = api.post(route, {**body, **values})
        assert response.status_code in (409, 422), response.text
    assert detail(api, assembly)["events"] == current["events"]
