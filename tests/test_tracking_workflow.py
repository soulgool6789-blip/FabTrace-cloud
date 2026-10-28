"""Release-critical behavior for project, spool, weld and requirement tracking."""

import pytest

from tracking_helpers import (
    accept_weld,
    add_weld,
    approve,
    complete_weld,
    find_requirement,
    make_spool,
    ok,
    requirement,
    review,
    serialized_history,
    spool,
    submit,
    weld,
)


def test_tracking_reads_and_mutations_require_authentication(api):
    assert api.get("/api/tracking/overview", role=None).status_code == 401
    assert api.get("/api/tracking/projects", role=None).status_code == 401
    assert api.post(
        "/api/tracking/projects", {"id": "PRJ", "name": "Test project"}, role=None
    ).status_code == 401


@pytest.mark.parametrize("role", ["welder", "handler", "inspector"])
def test_only_scope_managers_can_create_projects(api, role):
    assert api.post(
        "/api/tracking/projects", {"id": "PRJ", "name": "Test project"}, role=role
    ).status_code == 403


def test_subproject_cannot_be_attached_to_different_project(api):
    item_id = make_spool(api)
    ok(api.post("/api/tracking/projects", {"id": "OTHER", "name": "Other job"}), 201)
    ok(
        api.post(
            "/api/tracking/subprojects",
            {"id": "OTHER-PACKAGE", "project_id": "OTHER", "name": "Other package"},
        ),
        201,
    )
    current = spool(api, item_id)["plan"]
    response = api.post(
        f"/api/tracking/spools/{item_id}/plan",
        {
            "project_id": "TEST-PROJECT",
            "subproject_id": "OTHER-PACKAGE",
            "planned_welds": 1,
            "expected_version": current["version"],
        },
    )
    assert response.status_code == 422, response.text
    assert spool(api, item_id)["plan"].get("subproject_id") is None


def test_weld_number_is_unique_within_a_spool(api):
    item_id = make_spool(api, planned=2)
    first = add_weld(api, item_id)
    response = api.post(f"/api/tracking/spools/{item_id}/welds", {"number": "W01"})
    assert response.status_code == 409, response.text
    assert [row["id"] for row in spool(api, item_id)["welds"]] == [first["id"]]


def test_empty_scope_requires_explicit_zero_weld_basis(api):
    api.item(welds_required=0)
    ok(
        api.post("/api/tracking/projects", {"id": "PRJ", "name": "Test project"}),
        201,
    )
    response = api.post(
        "/api/tracking/spools/TEST-SPOOL-01/plan",
        {"project_id": "PRJ", "planned_welds": 0},
    )
    assert response.status_code == 422, response.text


def test_material_traceability_is_required_for_material_acceptance(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id, heat_b="", mtr_b="")
    req = find_requirement(api, item_id, record["id"], check="materials")
    submit(api, item_id, req["id"])
    response = review(api, item_id, req["id"])
    assert response.status_code == 409, response.text
    assert requirement(api, item_id, req["id"])["status"] != "accepted"


def test_before_welding_requirements_block_root_work(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    response = api.post(
        f"/api/tracking/welds/{record['id']}/work",
        {"operation": "root", "notes": "Attempt to bypass prerequisites"},
        role="welder",
    )
    assert response.status_code == 409, response.text
    assert weld(api, item_id, record["id"])["production_complete"] is False


def test_evidence_submission_is_not_inspector_acceptance(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    req = find_requirement(api, item_id, record["id"], check="materials")
    changed = submit(api, item_id, req["id"])
    assert changed["status"] != "accepted"
    assert changed["version"] > req["version"]
    assert review(api, item_id, req["id"], role="welder").status_code == 403
    assert review(api, item_id, req["id"], role="supervisor").status_code == 403
    ok(review(api, item_id, req["id"]))
    assert requirement(api, item_id, req["id"])["status"] == "accepted"


def test_stale_review_cannot_accept_replaced_evidence(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    req = find_requirement(api, item_id, record["id"], check="materials")
    first = submit(api, item_id, req["id"], reference="REPORT-ORIGINAL")
    submit(api, item_id, req["id"], reference="REPORT-REVISED")
    response = review(api, item_id, req["id"], expected_version=first["version"])
    assert response.status_code == 409, response.text
    assert requirement(api, item_id, req["id"])["status"] != "accepted"
    assert "REPORT-ORIGINAL" in serialized_history(api, item_id)


def test_new_evidence_reopens_previously_accepted_requirement(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    req = find_requirement(api, item_id, record["id"], check="materials")
    accepted = approve(api, item_id, req["id"], reference="ACCEPTED-REPORT")
    changed = submit(api, item_id, req["id"], reference="REPLACEMENT-REPORT")
    assert changed["status"] != "accepted"
    assert changed["version"] > accepted["version"]
    history = serialized_history(api, item_id)
    assert "ACCEPTED-REPORT" in history
    assert "REPLACEMENT-REPORT" in history


def test_failed_evidence_cannot_be_reviewed_as_accepted(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    req = find_requirement(api, item_id, record["id"], check="materials")
    submit(api, item_id, req["id"], result="fail")
    response = review(api, item_id, req["id"])
    assert response.status_code == 409, response.text
    assert requirement(api, item_id, req["id"])["status"] != "accepted"


def test_postweld_evidence_recorded_before_work_cannot_certify_later_work(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    req = find_requirement(api, item_id, record["id"], code="VT")
    premature = submit(api, item_id, req["id"], reference="VT-BEFORE-WELDING")
    complete_weld(api, item_id, record["id"])
    current = requirement(api, item_id, req["id"])
    assert current["cycle"] > premature["cycle"]
    assert review(api, item_id, req["id"]).status_code == 409
    assert "VT-BEFORE-WELDING" in serialized_history(api, item_id)
    approved = approve(api, item_id, req["id"], reference="VT-AFTER-WELDING")
    assert approved["status"] == "accepted"


def test_fitup_work_requires_fresh_review_of_premature_fitup_approval(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    req = find_requirement(api, item_id, record["id"], code="FIT_UP")
    previous = approve(api, item_id, req["id"], reference="PREMATURE-FIT-UP")
    ok(
        api.post(
            f"/api/tracking/welds/{record['id']}/work",
            {"operation": "fitup", "notes": "Actual fit-up observation"},
            role="welder",
        )
    )
    current = requirement(api, item_id, req["id"])
    assert current["cycle"] > previous["cycle"]
    assert current["status"] != "accepted"
    assert review(api, item_id, req["id"]).status_code == 409


def test_failing_optional_requirement_cannot_be_dismissed_as_not_applicable(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    req = ok(
        api.post(
            f"/api/tracking/welds/{record['id']}/requirements",
            {
                "code": "OPTIONAL-TEST",
                "label": "Conditional test requirement",
                "allow_na": True,
                "stage": "release",
            },
        ),
        201,
    )
    submit(api, item_id, req["id"], reference="FAILED-TEST", result="fail")
    response = review(api, item_id, req["id"], decision="not_applicable")
    assert response.status_code == 409, response.text
    assert requirement(api, item_id, req["id"])["status"] == "rejected"


def test_required_material_check_cannot_be_dismissed_as_not_applicable(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    req = find_requirement(api, item_id, record["id"], check="materials")
    response = review(api, item_id, req["id"], decision="not_applicable")
    assert response.status_code in (409, 422), response.text
    assert requirement(api, item_id, req["id"])["status"] != "not_applicable"


def test_tracked_spool_rejects_aggregate_weld_count_and_inspection_shortcuts(api):
    item_id = make_spool(api)
    add_weld(api, item_id)
    response = api.post(
        f"/api/items/{item_id}/weld",
        {"count": 1, "weld_ids": "W01", "notes": "Legacy shortcut"},
        role="welder",
    )
    assert response.status_code == 409, response.text
    response = api.post(
        f"/api/items/{item_id}/inspect",
        {
            "kind": "Weld",
            "result": "Pass",
            "report": "AGGREGATE-REPORT",
            "measurements": "Legacy blanket approval",
        },
        role="inspector",
    )
    assert response.status_code == 409, response.text


def test_legacy_green_flags_cannot_bypass_incomplete_weld_requirements(api):
    item_id = make_spool(api)
    add_weld(api, item_id)
    with api.session_factory() as session:
        item = session.get(api.application.Item, item_id)
        item.welds_done = item.welds_required
        item.dimensional = item.weld = "Pass"
        item.reinspection_due = False
        item.dimension_at = item.weld_at = api.application.utcnow()
        session.commit()
    response = api.post(
        f"/api/items/{item_id}/release", {"reference": "TEST-RELEASE"}, role="inspector"
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["release_blockers"]


def test_single_pass_configuration_does_not_force_unneeded_root_operation(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id, required_operations=["fill_cap"])
    complete = complete_weld(api, item_id, record["id"], operations=("fill_cap",))
    assert complete["production_complete"] is True
    assert complete["qa_accepted"] is False


def test_production_and_quality_counts_remain_independent(api):
    item_id = make_spool(api, planned=2)
    first = add_weld(api, item_id, "W01")
    second = add_weld(api, item_id, "W02")
    complete_weld(api, item_id, first["id"])
    complete_weld(api, item_id, second["id"])
    accept_weld(api, item_id, first["id"])
    accept_weld(api, item_id, second["id"], skip_codes=("NDE_PLAN", "FINAL_QA"))
    detail = spool(api, item_id)
    assert sum(row["production_complete"] for row in detail["welds"]) == 2
    assert sum(row["qa_accepted"] for row in detail["welds"]) == 1
    assert detail["summary"]["production_complete"] == 2
    assert detail["summary"]["qa_accepted"] == 1
    assert detail["summary"]["ready_to_release"] is False
    overview = ok(api.get("/api/tracking/overview"))
    assert overview["metrics"]["welds_defined"] == 2
    assert overview["metrics"]["production_complete"] == 2
    assert overview["metrics"]["qa_accepted"] == 1
    filtered = ok(api.get("/api/tracking/overview?project_id=TEST-PROJECT"))
    assert filtered["metrics"] == overview["metrics"]


def test_repair_invalidates_acceptance_without_erasing_history(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    complete_weld(api, item_id, record["id"])
    previous = accept_weld(api, item_id, record["id"])
    assert previous["qa_accepted"] is True
    response = api.post(
        f"/api/tracking/welds/{record['id']}/repairs",
        {"reason": "Test repair requiring new examination"},
        role="inspector",
    )
    assert response.status_code in (200, 201), response.text
    changed = weld(api, item_id, record["id"])
    assert changed["cycle"] > previous["cycle"]
    assert changed["production_complete"] is False
    assert changed["qa_accepted"] is False
    assert "REPORT-" in serialized_history(api, item_id)
    req = find_requirement(api, item_id, record["id"], check="materials")
    # Approval of the prior cycle's evidence must not certify new work.
    assert review(api, item_id, req["id"]).status_code == 409
    assert len(spool(api, item_id)["welds"]) == 1


def test_open_hold_blocks_release_after_all_welds_are_accepted(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    complete_weld(api, item_id, record["id"])
    accept_weld(api, item_id, record["id"])
    response = api.post(
        f"/api/tracking/spools/{item_id}/holds",
        {"reason": "Test client hold-point release pending", "weld_id": record["id"]},
        role="inspector",
    )
    assert response.status_code in (200, 201), response.text
    response = api.post(
        f"/api/items/{item_id}/release", {"reference": "TEST"}, role="inspector"
    )
    assert response.status_code == 409
    assert "hold" in response.text.lower()


def test_defined_weld_count_must_match_planned_scope_before_release(api):
    item_id = make_spool(api, planned=2)
    record = add_weld(api, item_id)
    complete_weld(api, item_id, record["id"])
    accept_weld(api, item_id, record["id"])
    # This spool is missing its second planned joint even though its sole
    # defined weld has every approval.
    response = api.post(
        f"/api/items/{item_id}/release", {"reference": "TEST"}, role="inspector"
    )
    assert response.status_code == 409
    assert spool(api, item_id)["summary"]["ready_to_release"] is False


def test_fully_accepted_tracked_spool_can_be_released_after_dimensions(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    complete_weld(api, item_id, record["id"])
    accept_weld(api, item_id, record["id"])
    response = api.post(
        f"/api/items/{item_id}/inspect",
        {
            "kind": "Dimensional",
            "result": "Pass",
            "report": "TEST-DIMENSIONAL",
            "measurements": "Test dimensions accepted after welding",
        },
        role="inspector",
    )
    assert response.status_code == 200, response.text
    response = api.post(
        f"/api/items/{item_id}/release", {"reference": "TEST-RELEASE"}, role="inspector"
    )
    assert response.status_code == 200, response.text
    assert response.json()["released"] is True
    assert api.post(
        f"/api/tracking/welds/{record['id']}/repairs",
        {"reason": "Test accidental edit after shipment release"},
        role="inspector",
    ).status_code == 409


def test_admin_reopen_requires_fresh_qa_but_preserves_physical_work(api):
    item_id = make_spool(api)
    record = add_weld(api, item_id)
    complete_weld(api, item_id, record["id"])
    accepted = accept_weld(api, item_id, record["id"])
    # Fixture-only release setup isolates the reopen behavior from the release
    # success path covered by the preceding test.
    with api.session_factory() as session:
        item = session.get(api.application.Item, item_id)
        item.released = True
        item.released_at = api.application.utcnow()
        session.commit()
    response = api.post(f"/api/items/{item_id}/reopen")
    assert response.status_code == 200, response.text
    reopened = weld(api, item_id, record["id"])
    assert reopened["production_complete"] is True
    assert reopened["qa_accepted"] is False
    assert reopened["cycle"] == accepted["cycle"]
    req = find_requirement(api, item_id, record["id"], code="VT")
    assert review(api, item_id, req["id"]).status_code == 409


def test_template_revision_does_not_mutate_existing_weld_requirements(api):
    item_id = make_spool(api, planned=2)
    template = {
        "code": "TEST-PROFILE",
        "name": "Test inspection profile",
        "revision": 1,
        "source": "Test-only approved plan",
        "requirements": [
            {
                "code": "TEST-EXTRA",
                "label": "Additional test inspection",
                "stage": "after_welding",
                "allow_na": False,
                "evidence_required": True,
                "check": "welding_complete",
            }
        ],
    }
    original = ok(api.post("/api/tracking/templates", template), 201)
    first = add_weld(api, item_id, "W01", template_id=original["id"])
    original_requirements = {
        row["code"]: (row["label"], row["source"])
        for row in weld(api, item_id, first["id"])["requirements"]
    }
    template["revision"] = 2
    template["requirements"][0]["label"] = "Revised inspection requirement"
    revised = ok(api.post("/api/tracking/templates", template), 201)
    assert revised["id"] != original["id"]
    unchanged = {
        row["code"]: (row["label"], row["source"])
        for row in weld(api, item_id, first["id"])["requirements"]
    }
    assert unchanged == original_requirements


@pytest.mark.parametrize("enrolled_parent", [False, True])
def test_assembly_cannot_move_to_a_different_project_from_existing_child(api, enrolled_parent):
    api.item("PARENT-ASSEMBLY", kind="Assembly", welds_required=0)
    child = make_spool(api, assembly_id="PARENT-ASSEMBLY")
    parent_body = {
        "project_id": "TEST-PROJECT",
        "planned_welds": 0,
        "zero_weld_reason": "Assembly has no directly welded joints",
    }
    if enrolled_parent:
        ok(api.post("/api/tracking/spools/PARENT-ASSEMBLY/plan", parent_body))
        parent_body["expected_version"] = spool(api, "PARENT-ASSEMBLY")["plan"]["version"]
    ok(api.post("/api/tracking/projects", {"id": "OTHER", "name": "Other job"}), 201)
    response = api.post(
        "/api/tracking/spools/PARENT-ASSEMBLY/plan",
        {**parent_body, "project_id": "OTHER"},
    )
    assert response.status_code == 422, response.text
    assert spool(api, child)["plan"]["assembly_id"] == "PARENT-ASSEMBLY"
    parent_plan = spool(api, "PARENT-ASSEMBLY")["plan"]
    assert (parent_plan["project_id"] if parent_plan else None) == (
        "TEST-PROJECT" if enrolled_parent else None
    )


def test_assembly_parent_links_cannot_form_a_cycle(api):
    ok(api.post("/api/tracking/projects", {"id": "PRJ", "name": "Test project"}), 201)
    for item_id, parent in (("ASSEMBLY-A", None), ("ASSEMBLY-B", "ASSEMBLY-A")):
        api.item(item_id, kind="Assembly", welds_required=0)
        ok(
            api.post(
                f"/api/tracking/spools/{item_id}/plan",
                {
                    "project_id": "PRJ",
                    "assembly_id": parent,
                    "planned_welds": 0,
                    "zero_weld_reason": "Assembly has no directly welded joints",
                },
            )
        )
    current = spool(api, "ASSEMBLY-A")["plan"]
    response = api.post(
        "/api/tracking/spools/ASSEMBLY-A/plan",
        {
            "project_id": "PRJ",
            "assembly_id": "ASSEMBLY-B",
            "planned_welds": 0,
            "zero_weld_reason": "Assembly has no directly welded joints",
            "expected_version": current["version"],
        },
    )
    assert response.status_code == 422, response.text
    assert spool(api, "ASSEMBLY-A")["plan"]["assembly_id"] is None
