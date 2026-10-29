"""Optional per-spool piece quantities use actual unique Part identities.

These acceptance tests use the isolated SQLite fixture only. Required pieces,
allocation, recorded receipt and current recorded preparation are separate
facts; an approved late baseline never supplies missing receipt/prep events.
"""

import importlib

import pytest
from conftest import BADGES
from tracking_helpers import add_weld, ok
from test_flow import (
    PROJECT, action_body, advance, assign_component as legacy_assign_component,
    create_item, detail as flow_detail, enroll, inspect_dimensions,
)
from test_progress import database_state, part as progress_part
from test_dossier import (
    check as packet_check, complete_packet, configure, issue_item, issue_project,
    issued_fixture, make_project, packet, physical_release, project as packet_project,
    sign_source, signed,
)


ROOT = "/api/parts/spools"
REFERENCE = "TEST-APPROVED-BOM-REV-A"
REASON = "Synthetic approved bill of materials scope for isolated tests"


def spool(api, item_id="PARTS-SPOOL", *, project=PROJECT, planned=0):
    return create_item(api, item_id, kind="Spool", planned=planned, project=project)


def component(api, item_id, *, part_number="", project=PROJECT, kind="Part"):
    create_item(api, item_id, kind=kind, project=project)
    if part_number:
        ok(api.patch(f"/api/items/{item_id}/part-number", {"google_part_number": part_number}))
    return item_id


def detail(api, spool_id, *, role="admin"):
    return ok(api.get(f"{ROOT}/{spool_id}", role=role))


def line(qty=1, *, part_number="", description="Synthetic individual material piece", **values):
    return {"part_number": part_number, "description": description, "required_qty": qty, "notes": "", **values}


def plan_body(api, spool_id, lines, **values):
    return {"expected_version": detail(api, spool_id)["version"], "reference": REFERENCE,
            "reason": REASON, "lines": lines, **values}


def plan(api, spool_id, lines=None, *, role="supervisor", **values):
    return ok(api.put(f"{ROOT}/{spool_id}/plan",
        plan_body(api, spool_id, lines if lines is not None else [line()], **values), role=role))


def saved_lines(record):
    return [{key: row[key] for key in ("id", "part_number", "description", "required_qty", "notes")}
            for row in record["lines"]]


def allocation_body(api, spool_id, line_id, component_ids, **values):
    return {"expected_version": detail(api, spool_id)["version"], "line_id": line_id,
            "component_ids": component_ids, "reference": REFERENCE,
            "notes": "Actual test QR identities allocated to this BOM position", **values}


def allocate(api, spool_id, line_id, component_ids, *, role="handler", **values):
    return ok(api.post(f"{ROOT}/{spool_id}/allocations",
        allocation_body(api, spool_id, line_id, component_ids, **values), role=role))


def removal_body(api, spool_id, **values):
    return {"expected_version": detail(api, spool_id)["version"], "reference": REFERENCE,
            "notes": "Correct this allocation before issuing selected material", **values}


def totals(record, *, required, assigned, received, prepared):
    actual = record["totals"]
    assert {key: actual[key] for key in ("required_qty", "assigned_qty", "received_qty", "prepared_qty")} == {
        "required_qty": required, "assigned_qty": assigned, "received_qty": received, "prepared_qty": prepared,
    }
    assert actual["short_qty"] == required - assigned
    assert actual["remaining_qty"] == required - prepared
    for label, value in (("assigned", assigned), ("received", received), ("prepared", prepared)):
        assert actual[label + "_percent"] == pytest.approx(100 * value / required, abs=0.11)


def prepare(api, component_id, spool_id, *, start_step=1):
    enroll(api, component_id, "component", **({"start_step": start_step} if start_step != 1 else {}))
    for step in range(start_step, 9):
        advance(api, component_id, **({"target_spool_id": spool_id} if step == 5 else {}))


def assert_rejected_without_changes(api, response, before, statuses=(409, 422)):
    assert response.status_code in statuses, response.text
    assert database_state(api) == before


def test_reads_require_login_and_never_enroll_or_create_physical_records(api):
    spool_id = spool(api)
    before = database_state(api)
    assert api.get(ROOT, role=None).status_code == 401
    assert api.get(f"{ROOT}/{spool_id}", role=None).status_code == 401
    for role in BADGES:
        listing = ok(api.get(ROOT, role=role, params={"project_id": PROJECT}))
        assert "items" in listing
        record = detail(api, spool_id, role=role)
        assert record["configured"] is False
        assert record["version"] == 0 and record["lines"] == []
    assert api.get(f"{ROOT}/NO-SUCH-SPOOL").status_code == 404
    assert database_state(api) == before


def test_required_quantities_are_scope_only_and_reads_preserve_the_recorded_plan(api):
    spool_id = spool(api)
    record = plan(api, spool_id, [line(2, part_number="TEST-ELBOW"), line(3, part_number="TEST-PIPE")])
    assert record["configured"] is True and record["version"] == 1
    assert len(record["lines"]) == 2
    totals(record, required=5, assigned=0, received=0, prepared=0)
    assert flow_detail(api, spool_id)["flow"] is None
    assert ok(api.get("/api/items"))["total"] == 1
    before = database_state(api)
    for path in (ROOT, f"{ROOT}/{spool_id}", f"/api/tracking/spools/{spool_id}",
                 f"/api/flow/items/{spool_id}", f"/api/progress/projects/{PROJECT}"):
        assert api.get(path).status_code == 200
    assert database_state(api) == before
    assert progress_part(api, spool_id)["fabrication_finished"] is False


def test_plan_roles_and_optimistic_versions_are_enforced_without_side_effects(api):
    spool_id = spool(api)
    body = plan_body(api, spool_id, [line(2)])
    before = database_state(api)
    for role in (None, "handler", "welder", "inspector"):
        response = api.put(f"{ROOT}/{spool_id}/plan", body, role=role)
        assert_rejected_without_changes(api, response, before, (401,) if role is None else (403,))
    first = ok(api.put(f"{ROOT}/{spool_id}/plan", body, role="supervisor"))
    assert first["version"] == 1
    before = database_state(api)
    assert_rejected_without_changes(api, api.put(f"{ROOT}/{spool_id}/plan", body), before, (409,))
    second = plan(api, spool_id, [{**saved_lines(first)[0], "required_qty": 3}], role="admin")
    assert second["version"] == 2
    totals(second, required=3, assigned=0, received=0, prepared=0)


@pytest.mark.parametrize("lines,changes", [
    ([], {}), ([line(0)], {}), ([line(-1)], {}), ([line(True)], {}),
    ([line(1.5)], {}), ([line("2")], {}), ([line(10001)], {}),
    ([line(6000), line(5000)], {}), ([line(description="")], {}),
    ([line()], {"expected_version": True}), ([line()], {"reference": ""}),
    ([line()], {"reason": ""}), ([line()], {"actor": BADGES["inspector"]}),
])
def test_invalid_plan_inputs_do_not_create_scope_or_history(api, lines, changes):
    spool_id = spool(api)
    body = plan_body(api, spool_id, lines, **changes)
    before = database_state(api)
    assert_rejected_without_changes(api, api.put(f"{ROOT}/{spool_id}/plan", body), before, (422,))


def test_batch_allocation_is_atomic_and_one_unique_part_is_one_piece(api):
    spool_id = spool(api)
    record = plan(api, spool_id, [line(2, part_number="TEST-PN")])
    target = record["lines"][0]["id"]
    good = component(api, "PARTS-GOOD", part_number="TEST-PN")
    mismatch = component(api, "PARTS-WRONG-PN", part_number="OTHER-PN")
    blank = component(api, "PARTS-BLANK-PN")
    other = component(api, "PARTS-OTHER-PROJECT", part_number="TEST-PN", project="PARTS-OTHER-PROJECT")
    wrong_kind = component(api, "PARTS-ASSEMBLY", part_number="TEST-PN", kind="Assembly")
    tracked_part = component(api, "PARTS-ALREADY-TRACKED", part_number="TEST-PN")
    ok(api.post(f"/api/tracking/spools/{tracked_part}/plan", {"project_id": PROJECT, "planned_welds": 0,
        "zero_weld_reason": "Existing tracked spool has a legacy Part item type"}))
    for ids in ([good, good], [good, "NO-SUCH-PART"], [good, mismatch], [good, blank],
                [good, other], [good, wrong_kind], [good, tracked_part]):
        body = allocation_body(api, spool_id, target, ids)
        before = database_state(api)
        assert_rejected_without_changes(api, api.post(f"{ROOT}/{spool_id}/allocations", body), before, (404, 409, 422))
        totals(detail(api, spool_id), required=2, assigned=0, received=0, prepared=0)
    second = component(api, "PARTS-GOOD-2", part_number="TEST-PN")
    allocated = allocate(api, spool_id, target, [good, second])
    totals(allocated, required=2, assigned=2, received=0, prepared=0)
    assert {row["id"] for row in allocated["lines"][0]["components"]} == {good, second}
    assert flow_detail(api, good)["flow"] is None
    assert flow_detail(api, second)["flow"] is None
    third = component(api, "PARTS-GOOD-3", part_number="TEST-PN")
    before = database_state(api)
    body = allocation_body(api, spool_id, target, [third])
    assert_rejected_without_changes(api, api.post(f"{ROOT}/{spool_id}/allocations", body), before, (409,))


def test_completed_existing_components_can_be_categorized_without_repeating_work(api):
    spool_id = spool(api)
    child = component(api, "PARTS-EXISTING-COMPONENT", part_number="TEST-EXISTING-PN")
    enroll(api, child, "component")
    for step in range(1, 9):
        if step == 5:
            legacy_assign_component(api, child, spool_id)
        advance(api, child, **({"target_spool_id": spool_id} if step == 5 else {}))
    before_child = flow_detail(api, child)
    configured = plan(api, spool_id, [line(part_number="TEST-EXISTING-PN")])
    assert [row["id"] for row in configured["unallocated_components"]] == [child]
    totals(configured, required=1, assigned=0, received=0, prepared=0)
    allocated = allocate(api, spool_id, configured["lines"][0]["id"], [child])
    totals(allocated, required=1, assigned=1, received=1, prepared=1)
    after_child = flow_detail(api, child)
    assert after_child["flow"]["status"] == "completed"
    assert after_child["events"][:len(before_child["events"])] == before_child["events"]
    assert after_child["production_process"]["events"] == before_child["production_process"]["events"]


def test_existing_qr_cannot_fill_two_lines_or_two_spools(api):
    first = spool(api, "PARTS-SPOOL-A")
    second = spool(api, "PARTS-SPOOL-B")
    first_plan = plan(api, first, [line(), line(description="Second distinct BOM position")])
    second_plan = plan(api, second)
    child = component(api, "PARTS-ONE-QR")
    allocate(api, first, first_plan["lines"][0]["id"], [child])
    for parent, line_id in ((first, first_plan["lines"][1]["id"]), (second, second_plan["lines"][0]["id"])):
        body = allocation_body(api, parent, line_id, [child])
        before = database_state(api)
        assert_rejected_without_changes(api, api.post(f"{ROOT}/{parent}/allocations", body), before, (409,))
    totals(detail(api, first), required=2, assigned=1, received=0, prepared=0)
    totals(detail(api, second), required=1, assigned=0, received=0, prepared=0)


def test_allocation_roles_stale_forms_and_line_scope_are_checked_atomically(api):
    spool_id = spool(api)
    configured = plan(api, spool_id, [line(2)])
    target = configured["lines"][0]["id"]
    first = component(api, "PARTS-VERSION-A")
    second = component(api, "PARTS-VERSION-B")
    body = allocation_body(api, spool_id, target, [first])
    before = database_state(api)
    for role in (None, "welder", "inspector"):
        assert_rejected_without_changes(api,
            api.post(f"{ROOT}/{spool_id}/allocations", body, role=role), before,
            (401,) if role is None else (403,))
    allocated = ok(api.post(f"{ROOT}/{spool_id}/allocations", body, role="handler"))
    assert allocated["version"] == configured["version"] + 1
    before = database_state(api)
    assert_rejected_without_changes(api,
        api.post(f"{ROOT}/{spool_id}/allocations", {**body, "component_ids": [second]}), before, (409,))
    for change in ({"expected_version": True}, {"component_ids": []}, {"line_id": "NO-SUCH-LINE"},
                   {"notes": ""}, {"reference": ""}, {"actor": BADGES["inspector"]}):
        request = {**allocation_body(api, spool_id, target, [second]), **change}
        assert_rejected_without_changes(api, api.post(f"{ROOT}/{spool_id}/allocations", request), before, (422,))
    removal = removal_body(api, spool_id)
    for role in (None, "welder", "inspector"):
        assert_rejected_without_changes(api,
            api.post(f"{ROOT}/{spool_id}/allocations/{first}/remove", removal, role=role), before,
            (401,) if role is None else (403,))


def test_receipt_and_preparation_come_from_actual_steps_not_baseline_position(api):
    spool_id = spool(api)
    configured = plan(api, spool_id, [line(3)])
    children = [component(api, f"PARTS-HISTORY-{suffix}") for suffix in ("FULL", "LATE7", "LATE8")]
    allocate(api, spool_id, configured["lines"][0]["id"], children)
    first, late7, late8 = children
    enroll(api, first, "component")
    advance(api, first)
    totals(detail(api, spool_id), required=3, assigned=3, received=1, prepared=0)
    for step in range(2, 8):
        advance(api, first, **({"target_spool_id": spool_id} if step == 5 else {}))
    totals(detail(api, spool_id), required=3, assigned=3, received=1, prepared=0)
    advance(api, first)
    prepare(api, late7, spool_id, start_step=7)
    prepare(api, late8, spool_id, start_step=8)
    current = detail(api, spool_id)
    totals(current, required=3, assigned=3, received=1, prepared=2)
    rows = {row["id"]: row for row in current["lines"][0]["components"]}
    assert rows[first]["received"] is True and rows[first]["prepared"] is True
    assert rows[late7]["received"] is False and rows[late7]["prepared"] is True
    assert rows[late8]["received"] is False and rows[late8]["prepared"] is False
    assert rows[late8]["blockers"]


def test_open_component_rework_removes_prepared_readiness_without_erasing_receipt(api):
    spool_id = spool(api)
    configured = plan(api, spool_id)
    child = component(api, "PARTS-REWORK-CHILD")
    allocate(api, spool_id, configured["lines"][0]["id"], [child])
    prepare(api, child, spool_id)
    totals(detail(api, spool_id), required=1, assigned=1, received=1, prepared=1)
    ok(api.post(f"/api/items/{child}/rework", {"kind": "Material", "reason": "Actual prepared piece found damaged",
        "assigned": BADGES["welder"]}, role="inspector"), 201)
    changed = detail(api, spool_id)
    totals(changed, required=1, assigned=1, received=1, prepared=0)
    assert any("rework" in message.lower() for message in changed["lines"][0]["components"][0]["blockers"])


def test_bom_cannot_be_bypassed_by_starting_a_zero_or_smaller_component_scope(api):
    spool_id = spool(api)
    plan(api, spool_id, [line(2)])
    before = database_state(api)
    for declared in (0, 1, 3):
        response = api.post(f"/api/flow/items/{spool_id}/start", {"route": "spool", "expected_children": declared,
            "material_reference": "TEST-EXISTING-MATERIAL-REFERENCE"})
        assert_rejected_without_changes(api, response, before, (409, 422))
    assert flow_detail(api, spool_id)["flow"] is None


def test_scope_sync_invalidates_open_forms_without_restarting_parent_timer(api):
    spool_id = spool(api)
    configured = plan(api, spool_id, [line(2)])
    enroll(api, spool_id, "spool", expected_children=2)
    before = flow_detail(api, spool_id)
    stale_step = action_body(api, spool_id)
    lines = [{**saved_lines(configured)[0], "required_qty": 3}]
    plan(api, spool_id, lines)
    after = flow_detail(api, spool_id)
    assert after["flow"]["expected_children"] == 3
    assert after["flow"]["version"] > before["flow"]["version"]
    assert after["production_process"]["events"] == before["production_process"]["events"]
    assert after["production_process"]["current"]["started_at"] == before["production_process"]["current"]["started_at"]
    snapshot = database_state(api)
    assert_rejected_without_changes(api, api.post(f"/api/flow/items/{spool_id}/advance", stale_step), snapshot, (409,))
    body = {"expected_version": after["flow"]["version"], "expected_children": 0,
            "material_reference": "TEST-LEGACY-SCOPE", "reference": REFERENCE, "reason": REASON}
    assert_rejected_without_changes(api, api.post(f"/api/flow/items/{spool_id}/scope", body), snapshot, (409,))


def test_legacy_component_assignment_cannot_bypass_or_move_a_bom_allocation(api):
    spool_id = spool(api, "PARTS-BOM-PARENT")
    plain = spool(api, "PARTS-LEGACY-PARENT")
    configured = plan(api, spool_id)
    child = component(api, "PARTS-BYPASS-CHILD")
    enroll(api, child, "component", start_step=5)
    for parent in (spool_id,):
        body = {"expected_version": flow_detail(api, child)["flow"]["version"],
                "spool_id": parent, "reference": REFERENCE}
        before = database_state(api)
        assert_rejected_without_changes(api, api.post(f"/api/flow/items/{child}/assign-component", body), before, (409,))
    allocate(api, spool_id, configured["lines"][0]["id"], [child])
    body = {"expected_version": flow_detail(api, child)["flow"]["version"],
            "spool_id": plain, "reference": REFERENCE}
    before = database_state(api)
    assert_rejected_without_changes(api, api.post(f"/api/flow/items/{child}/assign-component", body), before, (409,))


def test_removal_preserves_item_and_history_and_locks_after_selection(api):
    spool_id = spool(api)
    configured = plan(api, spool_id)
    child = component(api, "PARTS-REMOVE-CHILD")
    enroll(api, child, "component", start_step=5)
    allocate(api, spool_id, configured["lines"][0]["id"], [child])
    before = flow_detail(api, child)
    removed = ok(api.post(f"{ROOT}/{spool_id}/allocations/{child}/remove", removal_body(api, spool_id), role="handler"))
    totals(removed, required=1, assigned=0, received=0, prepared=0)
    after = flow_detail(api, child)
    assert after["item"]["id"] == child
    assert after["flow"]["current_step"] == 5
    assert after["events"][:len(before["events"])] == before["events"]
    assert after["production_process"]["events"] == before["production_process"]["events"]
    flow_module = importlib.import_module("flow")
    with api.session_factory() as session:
        assert session.get(flow_module.ComponentLink, child) is None
    allocate(api, spool_id, configured["lines"][0]["id"], [child])
    advance(api, child, target_spool_id=spool_id)
    body = removal_body(api, spool_id)
    snapshot = database_state(api)
    assert_rejected_without_changes(api, api.post(f"{ROOT}/{spool_id}/allocations/{child}/remove", body), snapshot, (409,))


def test_plan_edits_cannot_drop_allocated_lines_reduce_below_parts_or_reidentify_them(api):
    spool_id = spool(api)
    configured = plan(api, spool_id, [line(2, part_number="TEST-PN-A"), line(description="Unallocated position")])
    first = component(api, "PARTS-EDIT-A", part_number="TEST-PN-A")
    second = component(api, "PARTS-EDIT-B", part_number="TEST-PN-A")
    current = allocate(api, spool_id, configured["lines"][0]["id"], [first, second])
    existing = saved_lines(current)
    changes = [
        [existing[1]],
        [{**existing[0], "required_qty": 1}, existing[1]],
        [{**existing[0], "part_number": "TEST-PN-B"}, existing[1]],
        [existing[0], existing[0]],
        [{**existing[0], "id": "FOREIGN-LINE-ID"}, existing[1]],
    ]
    before = database_state(api)
    for lines in changes:
        request = plan_body(api, spool_id, lines)
        assert_rejected_without_changes(api, api.put(f"{ROOT}/{spool_id}/plan", request), before)


def test_prepared_part_number_drift_blocks_parent_and_final_release(api):
    spool_id = spool(api)
    configured = plan(api, spool_id, [line(part_number="TEST-PN-A")])
    child = component(api, "PARTS-DRIFT-CHILD", part_number="TEST-PN-A")
    allocate(api, spool_id, configured["lines"][0]["id"], [child])
    prepare(api, child, spool_id)
    totals(detail(api, spool_id), required=1, assigned=1, received=1, prepared=1)
    enroll(api, spool_id, "spool", expected_children=1)
    ok(api.patch(f"/api/items/{child}/part-number", {"google_part_number": "TEST-PN-B"}))
    changed = detail(api, spool_id)
    assert changed["lines"][0]["components"][0]["blockers"]
    assert progress_part(api, spool_id)["blocked"] is True
    before = database_state(api)
    assert_rejected_without_changes(api, api.post(f"/api/flow/items/{spool_id}/advance", action_body(api, spool_id)), before, (409,))


def test_bom_shortfall_blocks_generic_release_even_without_a_numbered_spool_route(api):
    spool_id = spool(api)
    plan(api, spool_id, [line(2)])
    inspect_dimensions(api, spool_id)
    before = database_state(api)
    response = api.post(f"/api/items/{spool_id}/release", {"reference": "TEST-QA-RELEASE"}, role="inspector")
    assert_rejected_without_changes(api, response, before, (409,))
    assert flow_detail(api, spool_id)["flow"] is None
    assert progress_part(api, spool_id)["fabrication_finished"] is False


def test_completed_step9_freezes_plan_allocation_and_removal(api):
    spool_id = spool(api)
    configured = plan(api, spool_id)
    child = component(api, "PARTS-FROZEN-CHILD")
    allocate(api, spool_id, configured["lines"][0]["id"], [child])
    prepare(api, child, spool_id)
    enroll(api, spool_id, "spool", expected_children=1)
    advance(api, spool_id)
    extra = component(api, "PARTS-FROZEN-EXTRA")
    current = detail(api, spool_id)
    edit = plan_body(api, spool_id, [{**saved_lines(current)[0], "required_qty": 2}])
    allocation = allocation_body(api, spool_id, current["lines"][0]["id"], [extra])
    remove = removal_body(api, spool_id)
    before = database_state(api)
    for response in (
        api.put(f"{ROOT}/{spool_id}/plan", edit),
        api.post(f"{ROOT}/{spool_id}/allocations", allocation),
        api.post(f"{ROOT}/{spool_id}/allocations/{child}/remove", remove),
    ):
        assert_rejected_without_changes(api, response, before, (409,))


def test_opt_in_is_blocked_after_real_weld_work_and_existing_final_release(api):
    working = spool(api, "PARTS-WORKING-SPOOL", planned=1)
    weld = add_weld(api, working)
    ok(api.post(f"/api/tracking/welds/{weld['id']}/work", {"operation": "fitup", "notes": "Actual fixture fit-up work"}, role="fitup_welder"))
    released = spool(api, "PARTS-RELEASED-SPOOL")
    physical_release(api, released)
    for spool_id in (working, released):
        body = plan_body(api, spool_id, [line()])
        before = database_state(api)
        assert_rejected_without_changes(api, api.put(f"{ROOT}/{spool_id}/plan", body), before, (409,))


def _legacy_structure(records):
    """Frozen pre-BOM fingerprint contract, retained as a migration oracle."""
    tracking = records["tracking"]
    weld_keys = ("id", "number", "version", "cycle", "component_a", "heat_a", "mtr_a",
                 "component_b", "heat_b", "mtr_b", "wps", "wps_revision", "required_operations",
                 "completed_at", "work", "repairs")
    return {"item_id": tracking["item"]["id"], "drawing": tracking["item"]["drawing"],
        "plan": {key: tracking["plan"][key] for key in ("project_id", "subproject_id", "assembly_id",
                 "planned_welds", "drawing_revision", "zero_weld_reason")},
        "welds": [{key: weld[key] for key in weld_keys} for weld in tracking["welds"]],
        "components": records["component_links"],
        "children": [{"item_id": child["item_id"], "physical_basis": child.get("physical_basis")}
                     for child in records["child_spools"]],
        "reworks": records["reworks"],
        "physical_events": [event for event in records["flow_events"]
            if (event["action"] == "advance" and event["step"] in (1, 7, 18))
            or (event["action"] in ("fail", "reopen") and (event["data"].get("return_step", event["step"]) or 0) <= 19)],
    }


def test_absent_bom_preserves_legacy_packet_fingerprints_and_issued_snapshot(api):
    spool_id = "PARTS-LEGACY-ISSUED"
    issued = issued_fixture(api, spool_id)
    dossier = importlib.import_module("dossier")
    before = packet(api, spool_id)
    assert before["latest_issue"]["current"] is True
    original_snapshot = ok(api.get(f"/api/dossier/issues/{issued['id']}"))
    with api.session_factory() as session:
        cfg = session.get(dossier.DossierProject, PROJECT)
        assert dossier._structural(before["records"]) == _legacy_structure(before["records"])
        legacy_basis = {
            "template": dossier.VERSION, "config": dossier._source_basis(cfg), "advisements": cfg.advisements,
            "source_review": before["source_review"]["id"],
            "checks": [{key: row[key] for key in ("code", "status", "fingerprint")}
                       | {"review_id": (row["latest_review"] or {}).get("id")}
                       for section in before["sections"] for row in section["checks"]],
            "release": {"released": before["item"]["released"], "released_at": before["item"]["released_at"],
                        "released_by": before["item"]["released_by"]},
            "release_errors": [], "structural": _legacy_structure(before["records"]), "child_packets": [],
        }
    assert before["fingerprint"] == dossier._digest(legacy_basis)
    unrelated = spool(api, "PARTS-OTHER-BOM", project="PARTS-UNRELATED-PROJECT")
    plan(api, unrelated, [line(4)])
    after = packet(api, spool_id)
    assert after["fingerprint"] == before["fingerprint"]
    assert after["latest_issue"]["current"] is True
    assert ok(api.get(f"/api/dossier/issues/{issued['id']}")) == original_snapshot


def test_enabled_bom_changes_structural_packet_review_basis(api):
    spool_id = spool(api)
    configure(api)
    signed(sign_source(api))
    before = packet_check(api, spool_id, "materials")["fingerprint"]
    configured = plan(api, spool_id, [line(1, part_number="TEST-NEW-BOM-PN")])
    after_scope = packet_check(api, spool_id, "materials")["fingerprint"]
    assert after_scope != before
    child = component(api, "PARTS-PACKET-CHILD", part_number="TEST-NEW-BOM-PN")
    allocate(api, spool_id, configured["lines"][0]["id"], [child])
    after_allocation = packet_check(api, spool_id, "materials")["fingerprint"]
    assert after_allocation != after_scope
    assert packet(api, spool_id)["blockers"]


def test_later_allocated_identity_drift_stales_current_item_and_project_issues(api):
    spool_id = make_project(api, "PARTS-ISSUED-SPOOL")
    configured = plan(api, spool_id, [line(part_number="TEST-ISSUED-PN")])
    child = component(api, "PARTS-ISSUED-COMPONENT", part_number="TEST-ISSUED-PN")
    allocate(api, spool_id, configured["lines"][0]["id"], [child])
    prepare(api, child, spool_id)
    physical_release(api, spool_id)
    ready = complete_packet(api, spool_id)
    assert ready["blockers"] == []
    signed(issue_item(api, spool_id))
    signed(issue_project(api))
    original_item = packet(api, spool_id)
    original_project = packet_project(api)
    assert original_item["latest_issue"]["current"] is True
    assert original_project["latest_project_issue"]["current"] is True
    item_issue_id = original_item["latest_issue"]["id"]
    project_issue_id = original_project["latest_project_issue"]["id"]
    frozen_item = ok(api.get(f"/api/dossier/issues/{item_issue_id}"))
    frozen_project = ok(api.get(f"/api/dossier/issues/{project_issue_id}"))
    ok(api.patch(f"/api/items/{child}/part-number", {"google_part_number": "TEST-CHANGED-PN"}))
    changed_item = packet(api, spool_id)
    changed_project = packet_project(api)
    assert changed_item["latest_issue"]["current"] is False
    assert changed_project["latest_project_issue"]["current"] is False
    assert changed_item["blockers"] and changed_project["completion_blockers"]
    assert ok(api.get(f"/api/dossier/issues/{item_issue_id}")) == frozen_item
    assert ok(api.get(f"/api/dossier/issues/{project_issue_id}")) == frozen_project
