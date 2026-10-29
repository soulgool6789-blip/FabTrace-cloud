"""Project progress is derived from actual registered work and current QA.

Fixtures contain synthetic local items only. Baseline enrollment, weld work,
QA release, shipment, and delivery deliberately remain separate observations.
"""

import json

import pytest
from sqlalchemy import event, select

from conftest import BADGES
from tracking_helpers import add_weld, complete_weld, ok
from test_flow import (
    PROJECT, action_body, advance, assign_component, completed_spool, create_item,
    detail as flow_detail, enroll, inspect_dimensions,
)
from test_quality import assembly_at_step


ROOT = "/api/progress"


def project(api, project_id=PROJECT, **filters):
    return ok(api.get(f"{ROOT}/projects/{project_id}", params=filters))


def part(api, item_id, project_id=PROJECT):
    return next(row for row in project(api, project_id)["items"] if row["id"] == item_id)


def database_state(api):
    """Capture values, not just counts, so a silent update is observable."""
    with api.session_factory() as session:
        values = {
            table.name: [dict(row) for row in session.execute(
                select(table).order_by(*table.primary_key.columns)
            ).mappings()]
            for table in api.application.Base.metadata.sorted_tables
        }
    return json.dumps(values, sort_keys=True, default=str)


def test_progress_requires_authentication_and_valid_project_and_filter_scope(api):
    create_item(api, "PROGRESS-AUTH")
    assert api.get(ROOT + "/projects", role=None).status_code == 401
    assert api.get(f"{ROOT}/projects/{PROJECT}", role=None).status_code == 401
    assert api.get(ROOT + "/projects/DOES-NOT-EXIST").status_code == 404
    for params in ({"status": "approved"}, {"kind": "pipe"}, {"sort": "random"}):
        response = api.get(f"{ROOT}/projects/{PROJECT}", params=params)
        assert response.status_code == 422, response.text
    for role in BADGES:
        assert api.get(ROOT + "/projects", role=role).status_code == 200
        assert api.get(f"{ROOT}/projects/{PROJECT}", role=role).status_code == 200


def test_empty_project_has_no_invented_parts_or_completion(api):
    ok(api.post("/api/tracking/projects", {
        "id": PROJECT, "name": "Empty local project", "client": "Synthetic customer",
    }), 201)
    result = project(api)
    assert result["items"] == [] and result["total"] == 0
    for key in ("total_parts", "wip", "finished", "shipped", "delivered", "blocked",
                "finished_percent", "recorded_steps_completed", "recorded_steps_total", "recorded_percent"):
        assert result["counts"][key] == 0, (key, result["counts"])
    listing = ok(api.get(ROOT + "/projects"))
    assert len(listing["projects"]) == 1
    assert listing["projects"][0]["total_parts"] == 0


def test_project_membership_uses_plan_then_parent_then_exact_legacy_id(api):
    spool_id = create_item(api, "PROGRESS-SCOPE-SPOOL", kind="Spool")
    component = create_item(api, "PROGRESS-SCOPE-COMPONENT")
    unplanned = create_item(api, "PROGRESS-SCOPE-LEGACY")
    create_item(api, "PROGRESS-OTHER", project="PROGRESS-OTHER-PROJECT")
    ok(api.post("/api/items", {
        "id": "PROGRESS-NAME-ONLY", "description": "Legacy display-name assignment",
        "kind": "Part", "project": "Local flow project " + PROJECT,
        "location": "Test rack", "handler": BADGES["handler"], "welds_required": 0,
    }), 201)
    enroll(api, component, "component", start_step=5)
    enroll(api, spool_id, "spool", expected_children=1)
    assign_component(api, component, spool_id)
    # Earlier versions stored a free-form display label. An explicit plan or
    # component assignment takes precedence if that old label remains stale.
    with api.session_factory() as session:
        session.get(api.application.Item, spool_id).project = "PROGRESS-OTHER-PROJECT"
        session.get(api.application.Item, component).project = "PROGRESS-OTHER-PROJECT"
        session.commit()
    result = project(api)
    by_id = {row["id"]: row for row in result["items"]}
    assert set(by_id) == {spool_id, component, unplanned}
    assert result["counts"]["total_parts"] == 3
    assert by_id[spool_id]["kind"] == "spool"
    assert by_id[component]["kind"] == "component"
    assert by_id[component]["parent_id"] == spool_id
    assert by_id[unplanned]["kind"] == "unplanned"
    assert by_id[unplanned]["progress_percent"] == 0
    assert result["counts"]["planning_needed"] == 1
    assert {row["id"] for row in project(api, "PROGRESS-OTHER-PROJECT")["items"]} == {"PROGRESS-OTHER"}


def test_late_flow_baseline_is_unrecorded_and_never_creates_percentage(api):
    item_id = create_item(api, "PROGRESS-BASELINE", kind="Spool")
    enroll(api, item_id, "spool", start_step=14)
    row = part(api, item_id)
    assert row["progress_basis"] == "recorded_steps"
    assert row["current_step"] == 14
    assert row["completed_steps"] == 0
    assert row["total_steps"] == 8
    assert row["not_recorded_steps"] == 5
    assert row["progress_percent"] == 0
    assert row["status"] == "wip" and not row["fabrication_finished"]
    advance(api, item_id)
    row = part(api, item_id)
    assert row["completed_steps"] == 1
    assert row["not_recorded_steps"] == 5
    assert row["progress_percent"] == pytest.approx(12.5)
    # A subsequent physical release may finish the spool, but still cannot
    # claim records for the five steps completed before this traveler existed.
    inspect_dimensions(api, item_id)
    advance(api, item_id, role="inspector")
    advance(api, item_id)
    row = part(api, item_id)
    assert row["fabrication_finished"] and row["status"] == "finished"
    assert row["completed_steps"] == 3
    assert row["not_recorded_steps"] == 5
    assert row["progress_percent"] == pytest.approx(37.5)


def test_rejected_quality_step_invalidates_downstream_recorded_progress(api):
    item_id = assembly_at_step(api, 22)
    before = part(api, item_id)
    assert before["completed_steps"] == 5
    assert before["progress_percent"] == pytest.approx(62.5)
    flow = flow_detail(api, item_id)
    ok(api.post(f"/api/flow/items/{item_id}/fail", {
        "expected_version": flow["flow"]["version"],
        "reason": "Synthetic final inspection found an assembly defect",
        "reference": "PROGRESS-NCR-001", "return_step": 18,
    }, role="inspector"))
    after = part(api, item_id)
    assert after["completed_steps"] == 1
    assert after["progress_percent"] == pytest.approx(12.5)
    assert after["current_step"] == 18
    assert after["blocked"] and after["blockers"]
    assert not after["fabrication_finished"]
    assert len(flow_detail(api, item_id)["events"]) > len(flow["events"])


def test_unrouted_weld_work_uses_planned_joint_count_and_does_not_claim_qa(api):
    item_id = create_item(api, "PROGRESS-WELDED", kind="Spool", planned=2)
    weld = add_weld(api, item_id)
    complete_weld(api, item_id, weld["id"])
    row = part(api, item_id)
    assert row["planned_welds"] == 2 and row["completed_welds"] == 1
    assert row["progress_basis"] == "weld_completion"
    assert row["progress_percent"] == pytest.approx(50)
    assert row["qa_accepted"] == 0
    assert row["status"] == "wip" and not row["fabrication_finished"]
    assert project(api)["counts"]["total_parts"] == 1
    # Recording an unreviewed second weld is still not completed physical work.
    add_weld(api, item_id, number="W02")
    assert part(api, item_id)["progress_percent"] == pytest.approx(50)


def test_zero_weld_scope_needs_actual_release_and_reopen_returns_it_to_wip(api):
    item_id = create_item(api, "PROGRESS-NO-WELDS", kind="Spool")
    row = part(api, item_id)
    assert row["progress_percent"] == 0 and not row["fabrication_finished"]
    inspect_dimensions(api, item_id)
    ok(api.post(f"/api/items/{item_id}/release", {"reference": "PROGRESS-QA-RELEASE"}, role="inspector"))
    row = part(api, item_id)
    assert row["progress_basis"] == "qa_release" and row["progress_percent"] == 100
    assert row["status"] == "finished" and row["fabrication_finished"]
    ok(api.post(f"/api/items/{item_id}/reopen"))
    row = part(api, item_id)
    assert row["status"] == "wip" and not row["fabrication_finished"]
    assert row["progress_percent"] == 0
    assert project(api)["counts"]["finished"] == 0


def test_finished_shipped_and_delivered_filters_preserve_physical_and_custody_states(api):
    assembly = assembly_at_step(api, 23)
    pending = create_item(api, "PROGRESS-PENDING")
    result = project(api)
    assert result["counts"]["total_parts"] == 3
    assert result["counts"]["finished"] == 2
    assert result["counts"]["wip"] == 1
    assert result["counts"]["finished_percent"] == pytest.approx(200 / 3, abs=0.1)
    assert {row["id"] for row in project(api, status="wip")["items"]} == {pending}
    assert {row["id"] for row in project(api, status="finished")["items"]} == {assembly, "QUALITY-ASSEMBLY-SPOOL"}
    assert project(api, status="shipped")["items"] == []
    advance(api, assembly)
    shipped = advance(api, assembly)
    assert part(api, assembly)["status"] == "shipped"
    assert part(api, assembly)["fabrication_finished"]
    assert {row["id"] for row in project(api, status="shipped")["items"]} == {assembly}
    assert assembly in {row["id"] for row in project(api, status="finished")["items"]}
    ok(api.post(f"/api/flow/items/{assembly}/deliver", {
        "expected_version": shipped["flow"]["version"],
        "receipt_reference": "PROGRESS-SIGNED-POD", "recipient": "Synthetic customer receiver",
    }))
    assert part(api, assembly)["status"] == "delivered"
    assert {row["id"] for row in project(api, status="delivered")["items"]} == {assembly}
    assert project(api)["counts"]["finished"] == 2


def test_sort_and_scope_filters_are_stable_and_keep_full_project_counts(api):
    zero = create_item(api, "PROGRESS-SORT-ZERO", kind="Spool")
    middle = create_item(api, "PROGRESS-SORT-MIDDLE", kind="Spool")
    full = create_item(api, "PROGRESS-SORT-FULL", kind="Spool")
    ok(api.post("/api/tracking/subprojects", {
        "id": "PROGRESS-SUB-A", "project_id": PROJECT, "name": "Synthetic Area A",
    }), 201)
    plan = ok(api.get(f"/api/tracking/spools/{middle}"))["plan"]
    ok(api.post(f"/api/tracking/spools/{middle}/plan", {
        "project_id": PROJECT, "subproject_id": "PROGRESS-SUB-A",
        "planned_welds": 0, "zero_weld_reason": "Synthetic scope has no welds",
        "expected_version": plan["version"],
    }))
    enroll(api, middle, "spool", start_step=14)
    advance(api, middle)
    inspect_dimensions(api, full)
    ok(api.post(f"/api/items/{full}/release", {"reference": "PROGRESS-SORT-QA"}, role="inspector"))
    assert [row["id"] for row in project(api, sort="progress_asc")["items"]] == [zero, middle, full]
    assert [row["id"] for row in project(api, sort="progress_desc")["items"]] == [full, middle, zero]
    assert [row["id"] for row in project(api, sort="id")["items"]] == sorted([zero, middle, full])
    filtered = project(api, subproject_id="PROGRESS-SUB-A", kind="spool", search="middle")
    assert [row["id"] for row in filtered["items"]] == [middle]
    assert filtered["total"] == 1 and filtered["counts"]["total_parts"] == 3
    assert filtered["counts"]["finished"] == 1
    assert filtered["subprojects"] == [{"id": "PROGRESS-SUB-A", "name": "Synthetic Area A"}]
    assert project(api, kind="assembly")["items"] == []


def test_registered_scope_counts_each_part_once_without_inventing_expected_children(api):
    spool_id = create_item(api, "PROGRESS-ACTUAL-SCOPE", kind="Spool")
    enroll(api, spool_id, "spool", expected_children=7)
    result = project(api)
    assert result["counts"]["total_parts"] == 1
    assert result["counts"]["wip"] == 1
    assert result["counts"]["recorded_steps_total"] == 8
    assert result["counts"]["recorded_steps_completed"] == 0
    assert result["items"][0]["blocked"]
    assert result["counts"]["blocked"] == 1


def test_progress_polling_is_read_only_and_does_not_lock_or_backfill_history(api):
    item_id = create_item(api, "PROGRESS-READONLY", kind="Spool")
    enroll(api, item_id, "spool", start_step=14)
    before = database_state(api)
    statements = []
    engine = api.session_factory.kw["bind"]

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement.strip().upper())

    event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(2):
            assert api.get(ROOT + "/projects").status_code == 200
            assert api.get(f"{ROOT}/projects/{PROJECT}").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert database_state(api) == before
    assert not any(statement.startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements)
    assert not any("FOR UPDATE" in statement or "PG_ADVISORY_XACT_LOCK" in statement for statement in statements)
