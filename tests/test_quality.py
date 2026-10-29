"""Audit-readiness behavior with synthetic records and real public API calls.

No customer PDFs, production credentials, or real audit evidence are used here.
These tests distinguish written plans, submitted records, and signed review.
"""

import datetime as dt
import importlib

import pytest
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import add_weld, ok


ROOT = "/api/quality"
PAST = "2026-01-15"
FUTURE = (dt.date.today() + dt.timedelta(days=365)).isoformat()


def workspace(api, *, template="blank", project_id=None, name="Local audit readiness"):
    return ok(api.post(ROOT + "/workspaces", {
        "name": name, "customer": "Kelvion", "project_id": project_id,
        "purchase_order": "TEST-PO-QUALITY", "owner_badge": BADGES["supervisor"],
        "template": template,
    }), 201)


def current(api, workspace_id):
    return ok(api.get(f"{ROOT}/workspaces/{workspace_id}"))


def mutate(api, workspace_id, suffix, body, *, method="post", role="admin", version=None):
    if version is None:
        version = current(api, workspace_id)["workspace"]["version"]
    return getattr(api, method)(f"{ROOT}/workspaces/{workspace_id}/{suffix}", {
        **body, "expected_version": version,
    }, role=role)


def requirement_body(**values):
    return {
        "item_number": "TEST-1", "title": "Synthetic audit requirement",
        "requirement_text": "Demonstrate the specified activity using a controlled record.",
        "response_text": "CLM records the activity and retains its reviewed evidence.",
        "source_document": "Synthetic customer quality plan", "source_revision": "TEST-A",
        "source_section": "Test clause 1", "source_reference": "TEST-SOURCE-RECORD",
        "supporting_documents": "Controlled test procedure and actual test records",
        "required_evidence": "The actual dated record and an independent review",
        "gaps": "", "priority": "high", "owner_badge": BADGES["supervisor"],
        "due_date": None, "applicability": "applicable", "applicability_reason": "",
        "required_evidence_types": ["other"], "document_ids": [],
        "requires_closed_action": False, "requires_approved_document": False, "gate": "none", **values,
    }


def create_requirement(api, workspace_id, **values):
    response = ok(mutate(api, workspace_id, "requirements", requirement_body(**values)), 201)
    return response["requirements"][-1]["id"]


def req(api, workspace_id, requirement_id):
    return next(row for row in current(api, workspace_id)["requirements"] if row["id"] == requirement_id)


def edit_requirement(api, workspace_id, requirement_id, **values):
    row = req(api, workspace_id, requirement_id)
    keys = requirement_body().keys()
    body = {key: row[key] for key in keys}
    return ok(mutate(api, workspace_id, f"requirements/{requirement_id}", {**body, **values}, method="put"))


def review(api, workspace_id, target_type, target_id, decision, *, role="inspector", **values):
    return mutate(api, workspace_id, "reviews", {
        "target_type": target_type, "target_id": target_id, "decision": decision,
        "reference": "TEST-REVIEW-RECORD", "notes": "The reviewer checked the specified synthetic record and its current scope.",
        **values,
    }, role=role)


def review_ok(response):
    return ok(response, 201)


def confirm_source(api, workspace_id, requirement_id):
    return review_ok(review(api, workspace_id, "source", requirement_id, "confirmed"))


def create_document(api, workspace_id, *, code="TEST-QMS", revision="A", **values):
    response = ok(mutate(api, workspace_id, "documents", {
        "code": code, "title": "Synthetic controlled procedure", "revision": revision,
        "reference": "TEST-CONTROLLED-DOCUMENT-" + revision, "effective_date": PAST,
        "requires_training": False, "required_badges": [], "notes": "Local test revision only",
        **values,
    }), 201)
    return response["documents"][-1]["id"]


def create_evidence(api, workspace_id, requirement_id, *, type="other", data=None, **values):
    response = ok(mutate(api, workspace_id, "evidence", {
        "requirement_id": requirement_id, "type": type, "title": "Synthetic actual record",
        "reference": "TEST-ACTUAL-RECORD", "occurred_on": PAST, "notes": "Local observed record",
        "document_id": None, "related_evidence_id": None, "item_id": None, "weld_id": None,
        "participants": [], "performed_by": "Synthetic responsible person",
        "data": data if data is not None else {"scope": "Synthetic scope", "result": "pass"},
        **values,
    }), 201)
    return response["evidence"][-1]["id"]


def accepted_evidence(api, workspace_id, requirement_id, **values):
    evidence_id = create_evidence(api, workspace_id, requirement_id, **values)
    review_ok(review(api, workspace_id, "evidence", evidence_id, "accepted"))
    return evidence_id


def verified_requirement(api, workspace_id, **values):
    requirement_id = create_requirement(api, workspace_id, **values)
    confirm_source(api, workspace_id, requirement_id)
    evidence_id = accepted_evidence(api, workspace_id, requirement_id)
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    assert req(api, workspace_id, requirement_id)["status"] == "verified"
    return requirement_id, evidence_id


def document_row(api, workspace_id, document_id):
    return next(row for row in current(api, workspace_id)["documents"] if row["id"] == document_id)


def test_template_is_a_draft_matrix_and_never_creates_completed_activities(api):
    assert ok(api.get(ROOT + "/workspaces"))["workspaces"] == []
    catalog = ok(api.get(ROOT + "/catalog"))
    assert len(catalog["source_documents"]) == 7
    detail = workspace(api, template="kelvion")
    by_number = {row["item_number"]: row for row in detail["requirements"]}
    assert {"3–6", "7", "8", "9", "10–12", "13", "14"} <= set(by_number)
    for number in ("7", "9", "13", "14"):
        assert by_number[number]["priority"] in {"high", "critical"}
    assert all(row["status"] != "verified" and row["source_status"] != "confirmed" for row in detail["requirements"])
    assert all(row["gate"] == "none" for row in detail["requirements"])
    assert not detail["documents"] and not detail["evidence"] and not detail["actions"] and not detail["reviews"]
    assert detail["metrics"]["verified"] == 0
    assert all(row["requirement_text"] and row["required_evidence"] for row in detail["requirements"])


def test_authentication_and_roles_apply_to_reads_writes_and_signed_reviews(api):
    assert api.get(ROOT + "/catalog", role=None).status_code == 401
    assert api.get(ROOT + "/workspaces", role=None).status_code == 401
    assert api.post(ROOT + "/workspaces", {"name": "Forbidden", "template": "blank"}, role="welder").status_code == 403
    detail = workspace(api)
    workspace_id = detail["workspace"]["id"]
    for role in ("welder", "handler"):
        assert api.get(f"{ROOT}/workspaces/{workspace_id}", role=role).status_code == 200
        assert mutate(api, workspace_id, "requirements", requirement_body(), role=role).status_code == 403
    requirement_id = create_requirement(api, workspace_id)
    assert review(api, workspace_id, "source", requirement_id, "confirmed", role="supervisor").status_code == 403
    confirm_source(api, workspace_id, requirement_id)
    assert req(api, workspace_id, requirement_id)["status"] != "verified"


def test_draft_response_and_submitted_evidence_are_not_verified_performance(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id)
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    confirm_source(api, workspace_id, requirement_id)
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    evidence_id = create_evidence(api, workspace_id, requirement_id)
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    review_ok(review(api, workspace_id, "evidence", evidence_id, "accepted"))
    assert req(api, workspace_id, requirement_id)["status"] == "ready_for_review"
    result = review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    assert result["metrics"]["verified"] == 1
    row = req(api, workspace_id, requirement_id)
    assert row["status"] == "verified" and row["blockers"] == []
    assert row["latest_review"]["actor"] == BADGES["inspector"]


def test_source_confirmation_requires_exact_document_revision_clause_and_reference(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, source_revision="", source_section="")
    response = review(api, workspace_id, "source", requirement_id, "confirmed")
    assert response.status_code in (409, 422), response.text
    edit_requirement(api, workspace_id, requirement_id, source_revision="B", source_section="4.2")
    confirm_source(api, workspace_id, requirement_id)
    assert req(api, workspace_id, requirement_id)["source_status"] == "confirmed"


def test_source_changes_stale_verification_but_unrelated_requirement_changes_do_not(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id, _ = verified_requirement(api, workspace_id)
    unrelated = create_requirement(api, workspace_id, item_number="TEST-2", title="Separate requirement")
    edit_requirement(api, workspace_id, unrelated, response_text="An unrelated draft was revised.")
    assert req(api, workspace_id, requirement_id)["status"] == "verified"
    before = current(api, workspace_id)["reviews"]
    edit_requirement(api, workspace_id, requirement_id, source_revision="B")
    changed = req(api, workspace_id, requirement_id)
    assert changed["status"] != "verified" and changed["source_status"] != "confirmed"
    assert current(api, workspace_id)["reviews"] == before
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    confirm_source(api, workspace_id, requirement_id)
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    assert req(api, workspace_id, requirement_id)["status"] == "verified"


def test_rejected_evidence_invalidates_a_signed_requirement_and_keeps_prior_reviews(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id, evidence_id = verified_requirement(api, workspace_id)
    before = current(api, workspace_id)
    review_ok(review(api, workspace_id, "evidence", evidence_id, "rejected", notes="The report identification does not match the required scope."))
    after = current(api, workspace_id)
    assert req(api, workspace_id, requirement_id)["status"] != "verified"
    assert after["reviews"][:len(before["reviews"])] == before["reviews"]
    assert len(after["evidence"]) == len(before["evidence"])
    assert after["evidence"][0]["status"] == "rejected"
    accepted_evidence(api, workspace_id, requirement_id, reference="TEST-CORRECTED-REPLACEMENT")
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    final = current(api, workspace_id)
    assert final["evidence"][0]["status"] == "rejected"
    assert len(final["evidence"]) == 2 and req(api, workspace_id, requirement_id)["status"] == "verified"


def test_unresolved_written_gap_cannot_be_signed_off_as_verified(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, gaps="The current inspection procedure has not been implemented.")
    confirm_source(api, workspace_id, requirement_id)
    accepted_evidence(api, workspace_id, requirement_id)
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    edit_requirement(api, workspace_id, requirement_id, gaps="")
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))


def test_draft_placeholder_response_must_be_replaced_before_verification(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id,
        response_text="DRAFT — implementation not verified. CLM will establish this procedure.")
    confirm_source(api, workspace_id, requirement_id)
    accepted_evidence(api, workspace_id, requirement_id)
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    edit_requirement(api, workspace_id, requirement_id,
        response_text="CLM uses the controlled procedure and the identified actual records demonstrate implementation.")
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))


def test_revision_approval_and_training_are_specific_to_people_and_document_revision(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, required_evidence_types=["training"])
    document_id = create_document(api, workspace_id, requires_training=True, required_badges=[BADGES["welder"], BADGES["handler"]])
    edit_requirement(api, workspace_id, requirement_id, document_ids=[document_id])
    confirm_source(api, workspace_id, requirement_id)
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    review_ok(review(api, workspace_id, "document", document_id, "approved"))
    for index, badge in enumerate((BADGES["welder"], BADGES["handler"])):
        accepted_evidence(api, workspace_id, requirement_id, type="training", document_id=document_id,
            participants=[badge], performed_by=BADGES["supervisor"],
            data={"topic": "Controlled procedure revision A", "assessment": "Employee demonstrated the specified steps."})
        if index == 0:
            assert document_row(api, workspace_id, document_id)["training_gaps"]
            assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    assert document_row(api, workspace_id, document_id)["training_gaps"] == []
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    next_document = create_document(api, workspace_id, revision="B", requires_training=True,
        required_badges=[BADGES["welder"], BADGES["handler"]])
    review_ok(review(api, workspace_id, "document", next_document, "approved"))
    assert document_row(api, workspace_id, document_id)["status"] == "superseded"
    assert req(api, workspace_id, requirement_id)["status"] != "verified"
    edit_requirement(api, workspace_id, requirement_id, document_ids=[next_document])
    assert document_row(api, workspace_id, next_document)["training_gaps"]
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409


def test_future_effective_document_cannot_support_current_readiness(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, required_evidence_types=[])
    document_id = create_document(api, workspace_id, effective_date=FUTURE)
    edit_requirement(api, workspace_id, requirement_id, document_ids=[document_id])
    confirm_source(api, workspace_id, requirement_id)
    review_ok(review(api, workspace_id, "document", document_id, "approved"))
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409


def test_training_cannot_be_accepted_against_an_unapproved_procedure(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, required_evidence_types=["training"])
    document_id = create_document(api, workspace_id)
    training_id = create_evidence(api, workspace_id, requirement_id, type="training", document_id=document_id,
        participants=[BADGES["welder"]], performed_by=BADGES["supervisor"],
        data={"topic": "Controlled test procedure", "assessment": "Employee demonstrated the specified procedure"})
    assert review(api, workspace_id, "evidence", training_id, "accepted").status_code == 409
    review_ok(review(api, workspace_id, "document", document_id, "approved"))
    review_ok(review(api, workspace_id, "evidence", training_id, "accepted"))


def test_document_supersession_stales_evidence_even_without_a_direct_requirement_link(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id)
    document_id = create_document(api, workspace_id)
    review_ok(review(api, workspace_id, "document", document_id, "approved"))
    confirm_source(api, workspace_id, requirement_id)
    evidence_id = accepted_evidence(api, workspace_id, requirement_id, document_id=document_id)
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    assert req(api, workspace_id, requirement_id)["document_ids"] == []
    newer = create_document(api, workspace_id, revision="B")
    review_ok(review(api, workspace_id, "document", newer, "approved"))
    detail = current(api, workspace_id)
    evidence = next(row for row in detail["evidence"] if row["id"] == evidence_id)
    assert evidence["status"] != "accepted"
    assert req(api, workspace_id, requirement_id)["status"] != "verified"


def test_approved_schedule_is_not_a_completed_internal_audit(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, required_evidence_types=["internal_audit"])
    confirm_source(api, workspace_id, requirement_id)
    accepted_evidence(api, workspace_id, requirement_id, type="audit_schedule", data={
        "scope": "QMS and production records", "auditor": "Test auditor", "scheduled_for": FUTURE,
        "approval_reference": "TEST-SCHEDULE-APPROVAL",
    })
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    accepted_evidence(api, workspace_id, requirement_id, type="internal_audit", data={
        "scope": "QMS and production records", "auditor": "Test auditor",
        "findings": "Finding TEST-01 was recorded for missing document acknowledgment.",
        "outcome": "Completed audit; findings require corrective action.",
    })
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))


def test_quality_alert_requires_the_actual_alert_and_its_assigned_training(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, required_evidence_types=["quality_alert", "training"])
    confirm_source(api, workspace_id, requirement_id)
    alert_id = accepted_evidence(api, workspace_id, requirement_id, type="quality_alert", data={
        "issue": "Synthetic traceability alert", "containment": "Affected items identified and held",
        "training_required": True, "required_participants": [BADGES["welder"], BADGES["handler"]],
    })
    accepted_evidence(api, workspace_id, requirement_id, type="training", related_evidence_id=alert_id,
        participants=[BADGES["welder"]], performed_by=BADGES["supervisor"],
        data={"topic": "Quality Alert TEST", "assessment": "Demonstrated revised identification controls"})
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    accepted_evidence(api, workspace_id, requirement_id, type="training", related_evidence_id=alert_id,
        participants=[BADGES["handler"]], performed_by=BADGES["supervisor"],
        data={"topic": "Quality Alert TEST", "assessment": "Demonstrated revised identification controls"})
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))


def test_rejecting_an_alert_invalidates_training_that_relied_on_that_alert(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, required_evidence_types=["quality_alert", "training"])
    confirm_source(api, workspace_id, requirement_id)
    alert_id = accepted_evidence(api, workspace_id, requirement_id, type="quality_alert", data={
        "issue": "Synthetic issued alert", "containment": "Affected work identified",
        "training_required": True, "required_participants": [BADGES["welder"]],
    })
    training_id = accepted_evidence(api, workspace_id, requirement_id, type="training", related_evidence_id=alert_id,
        participants=[BADGES["welder"]], performed_by=BADGES["supervisor"],
        data={"topic": "Exact issued Quality Alert", "assessment": "Required actions demonstrated"})
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    review_ok(review(api, workspace_id, "evidence", alert_id, "rejected", notes="The alert record was found to identify the wrong affected process."))
    detail = current(api, workspace_id)
    training = next(row for row in detail["evidence"] if row["id"] == training_id)
    assert training["status"] != "accepted"
    assert req(api, workspace_id, requirement_id)["status"] != "verified"


@pytest.mark.parametrize("kind,data", [
    ("internal_audit", {"scope": "Test", "auditor": "Test auditor", "findings": "None", "outcome": "Completed"}),
    ("quality_alert", {"issue": "Test issue", "containment": "Test containment", "training_required": False}),
    ("inspection", {"scope": "Test", "result": "pass", "measurements": "Test measured results"}),
    ("effectiveness", {"scope": "Test follow-up", "result": "pass"}),
])
def test_future_dates_do_not_fabricate_completed_activities(api, kind, data):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id)
    before = current(api, workspace_id)
    response = mutate(api, workspace_id, "evidence", {
        "requirement_id": requirement_id, "type": kind, "title": "Future record",
        "reference": "TEST-FUTURE-RECORD", "occurred_on": FUTURE, "data": data,
    })
    assert response.status_code in (409, 422), response.text
    after = current(api, workspace_id)
    assert after["evidence"] == before["evidence"] and after["workspace"]["version"] == before["workspace"]["version"]


def test_training_rejects_unknown_people_missing_revision_and_cross_workspace_documents(api):
    workspace_id = workspace(api)["workspace"]["id"]
    other_workspace = workspace(api, name="Separate workspace")["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id)
    document_id = create_document(api, workspace_id)
    foreign_document = create_document(api, other_workspace)
    body = {"requirement_id": requirement_id, "type": "training", "title": "Test training",
        "reference": "TEST-TRAINING", "occurred_on": PAST, "document_id": document_id,
        "participants": [BADGES["welder"]], "performed_by": BADGES["supervisor"],
        "data": {"topic": "Test topic", "assessment": "Demonstration observed"}}
    for change in ({"participants": ["NONEXISTENT"]}, {"performed_by": "NONEXISTENT"},
                   {"document_id": None}, {"document_id": foreign_document}):
        response = mutate(api, workspace_id, "evidence", {**body, **change})
        assert response.status_code in (404, 409, 422), response.text
    assert not current(api, workspace_id)["evidence"]


def action_body(requirement_id, **values):
    return {"requirement_id": requirement_id, "title": "Synthetic corrective action",
        "owner_badge": BADGES["supervisor"], "due_date": PAST,
        "problem": "Missing revision-specific training record", "containment": "Affected work held",
        "root_cause": "Training distribution did not identify the revised procedure",
        "correction": "Affected people trained on the current revision",
        "corrective_action": "Revision release now includes a named training roster",
        "status": "open", "closure_evidence_ids": [], "effectiveness_evidence_id": None,
        "customer_approval_required": True, "customer_approval_evidence_id": None, **values}


def test_corrective_action_requires_actual_closure_effectiveness_and_customer_disposition(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, requires_closed_action=True)
    confirm_source(api, workspace_id, requirement_id)
    accepted_evidence(api, workspace_id, requirement_id)
    detail = ok(mutate(api, workspace_id, "actions", action_body(requirement_id)), 201)
    action_id = detail["actions"][-1]["id"]
    assert detail["metrics"]["overdue_actions"] == 1
    assert review(api, workspace_id, "action", action_id, "closed").status_code == 409
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    closure_id = accepted_evidence(api, workspace_id, requirement_id, type="corrective_action")
    effectiveness_id = create_evidence(api, workspace_id, requirement_id, type="effectiveness")
    implemented = action_body(requirement_id, status="implemented", closure_evidence_ids=[closure_id],
        effectiveness_evidence_id=effectiveness_id)
    ok(mutate(api, workspace_id, f"actions/{action_id}", implemented, method="put"))
    assert review(api, workspace_id, "action", action_id, "closed").status_code == 409
    review_ok(review(api, workspace_id, "evidence", effectiveness_id, "accepted"))
    assert review(api, workspace_id, "action", action_id, "closed").status_code == 409
    approval_id = accepted_evidence(api, workspace_id, requirement_id, type="customer_approval", data={
        "scope": "Disposition of the specified synthetic finding", "disposition": "Approved specified repair",
        "approved_by": "Named synthetic customer representative",
    })
    implemented["customer_approval_evidence_id"] = approval_id
    ok(mutate(api, workspace_id, f"actions/{action_id}", implemented, method="put"))
    closed = review_ok(review(api, workspace_id, "action", action_id, "closed"))
    assert closed["actions"][0]["status"] == "closed"
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    assert mutate(api, workspace_id, f"actions/{action_id}", implemented, method="put").status_code == 409
    review_ok(review(api, workspace_id, "action", action_id, "reopened"))
    assert req(api, workspace_id, requirement_id)["status"] != "verified"


def test_conditional_and_not_applicable_requirements_need_explicit_reviewer_decision(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, applicability="conditional",
        applicability_reason="Confirm the purchase-order quality code.", required_evidence_types=[])
    assert review(api, workspace_id, "source", requirement_id, "confirmed").status_code == 409
    accepted_evidence(api, workspace_id, requirement_id)
    assert review(api, workspace_id, "requirement", requirement_id, "verified").status_code == 409
    assert mutate(api, workspace_id, f"requirements/{requirement_id}",
        requirement_body(applicability="not_applicable", applicability_reason=""), method="put").status_code == 422
    assert review(api, workspace_id, "requirement", requirement_id, "not_applicable").status_code in (409, 422)
    edit_requirement(api, workspace_id, requirement_id, applicability="not_applicable",
        applicability_reason="The reviewed purchase order excludes this quality code for this scope.")
    confirm_source(api, workspace_id, requirement_id)
    assert review(api, workspace_id, "requirement", requirement_id, "not_applicable", role="supervisor").status_code == 403
    review_ok(review(api, workspace_id, "requirement", requirement_id, "not_applicable"))
    assert req(api, workspace_id, requirement_id)["status"] == "not_applicable"


def test_stale_submission_cannot_duplicate_a_record_or_change_audit_history(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id)
    version = current(api, workspace_id)["workspace"]["version"]
    body = {"requirement_id": requirement_id, "type": "other", "title": "Only one record",
        "reference": "TEST-DUPLICATE-SUBMIT", "occurred_on": PAST, "data": {"scope": "Test scope", "result": "pass"}}
    first = ok(mutate(api, workspace_id, "evidence", body, version=version), 201)
    assert mutate(api, workspace_id, "evidence", body, version=version).status_code == 409
    after = current(api, workspace_id)
    assert after["evidence"] == first["evidence"]
    assert after["events"] == first["events"]
    assert after["workspace"]["version"] == first["workspace"]["version"]


def test_failed_inspection_and_effectiveness_cannot_be_accepted_as_passed_evidence(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id)
    for kind in ("inspection", "effectiveness"):
        data = {"scope": "Failed test scope", "result": "fail"}
        if kind == "inspection":
            data["measurements"] = "Measured result outside specified range"
        evidence_id = create_evidence(api, workspace_id, requirement_id, type=kind,
            data=data)
        assert review(api, workspace_id, "evidence", evidence_id, "accepted").status_code == 409
        review_ok(review(api, workspace_id, "evidence", evidence_id, "rejected"))


def test_linked_item_and_weld_must_match_the_selected_project_and_each_other(api):
    from test_flow import create_item
    first = create_item(api, "QUALITY-LINK-A", kind="Spool", planned=1, project="QUALITY-PROJECT-A")
    second = create_item(api, "QUALITY-LINK-B", kind="Spool", planned=1, project="QUALITY-PROJECT-B")
    first_weld = add_weld(api, first)
    second_weld = add_weld(api, second)
    workspace_id = workspace(api, project_id="QUALITY-PROJECT-A")["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id)
    body = {"requirement_id": requirement_id, "type": "production", "title": "Linked physical record",
        "reference": "TEST-PRODUCTION-RECORD", "occurred_on": PAST,
        "data": {"scope": "Specific physical joint", "result": "pass"}}
    for values in ({"item_id": second}, {"item_id": first, "weld_id": second_weld["id"]},
                   {"item_id": "NONEXISTENT"}, {"weld_id": "NONEXISTENT"}):
        response = mutate(api, workspace_id, "evidence", {**body, **values})
        assert response.status_code in (404, 409, 422), response.text
    ok(mutate(api, workspace_id, "evidence", {**body, "item_id": first, "weld_id": first_weld["id"]}), 201)


def test_physical_work_changes_invalidate_a_review_linked_to_that_weld(api):
    from test_flow import create_item
    item_id = create_item(api, "QUALITY-PHYSICAL", kind="Spool", planned=1, project="QUALITY-PROJECT")
    weld = add_weld(api, item_id)
    workspace_id = workspace(api, project_id="QUALITY-PROJECT")["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, required_evidence_types=["production"])
    confirm_source(api, workspace_id, requirement_id)
    accepted_evidence(api, workspace_id, requirement_id, type="production", item_id=item_id, weld_id=weld["id"])
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    before = current(api, workspace_id)["reviews"]
    ok(api.post(f"/api/tracking/welds/{weld['id']}/work", {"operation": "fitup", "notes": "New physical activity after review"}, role="welder"))
    assert req(api, workspace_id, requirement_id)["status"] != "verified"
    assert current(api, workspace_id)["reviews"] == before


def test_component_evidence_uses_real_parent_scope_and_reassignment_invalidates_review(api):
    from test_flow import PROJECT, assign_component, create_item, enroll
    component = create_item(api, "QUALITY-COMPONENT")
    first = create_item(api, "QUALITY-PARENT-A", kind="Spool")
    second = create_item(api, "QUALITY-PARENT-B", kind="Spool")
    enroll(api, component, "component")
    enroll(api, first, "spool", expected_children=1)
    enroll(api, second, "spool", expected_children=1)
    workspace_id = workspace(api, project_id=PROJECT)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, required_evidence_types=["production"])
    confirm_source(api, workspace_id, requirement_id)
    # The legacy Item.project text is not proof of controlled project scope.
    response = mutate(api, workspace_id, "evidence", {
        "requirement_id": requirement_id, "type": "production", "title": "Unassigned component",
        "reference": "TEST-COMPONENT-RECORD", "occurred_on": PAST, "item_id": component,
        "data": {"scope": "Received physical component", "result": "pass"},
    })
    assert response.status_code in (409, 422), response.text
    assign_component(api, component, first)
    evidence_id = accepted_evidence(api, workspace_id, requirement_id, type="production", item_id=component)
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    assign_component(api, component, second)
    detail = current(api, workspace_id)
    evidence = next(row for row in detail["evidence"] if row["id"] == evidence_id)
    assert evidence["status"] != "accepted" and evidence["stale"]
    assert req(api, workspace_id, requirement_id)["status"] != "verified"


def test_optional_gates_require_project_scope_and_reviewer_permission(api):
    workspace_id = workspace(api)["workspace"]["id"]
    response = mutate(api, workspace_id, "requirements", requirement_body(gate="shipment"))
    assert response.status_code in (409, 422), response.text
    ok(api.post("/api/tracking/projects", {"id": "QUALITY-GATE-PROJECT", "name": "Local gate project"}), 201)
    scoped = workspace(api, project_id="QUALITY-GATE-PROJECT")["workspace"]["id"]
    assert mutate(api, scoped, "requirements", requirement_body(gate="shipment"), role="supervisor").status_code == 403
    requirement_id = create_requirement(api, scoped, gate="shipment")
    assert req(api, scoped, requirement_id)["gate"] == "shipment"


def assembly_at_step(api, step):
    from test_flow import advance, completed_spool, create_item, detail, enroll, inspect_dimensions, link_spool
    assembly = create_item(api, "QUALITY-ASSEMBLY", kind="Assembly")
    child = completed_spool(api, "QUALITY-ASSEMBLY-SPOOL")
    enroll(api, assembly, "assembly", expected_children=1)
    link_spool(api, assembly, child)
    while detail(api, assembly)["flow"]["current_step"] < step:
        current_step = detail(api, assembly)["flow"]["current_step"]
        if current_step in (19, 22):
            inspect_dimensions(api, assembly)
        advance(api, assembly, role="inspector" if current_step in (19, 22) else "admin")
    return assembly


@pytest.mark.parametrize("step,gate", [(20, "pre_coating"), (21, "pre_coating"), (23, "shipment"), (24, "shipment")])
def test_project_gate_blocks_numbered_flow_atomically_until_reviewed_evidence_is_current(api, step, gate):
    from test_flow import PROJECT, action_body, advance, detail
    item_id = assembly_at_step(api, step)
    workspace_id = workspace(api, project_id=PROJECT)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, gate=gate)
    before = detail(api, item_id)
    response = api.post(f"/api/flow/items/{item_id}/advance", action_body(api, item_id))
    assert response.status_code == 409, response.text
    unchanged = detail(api, item_id)
    assert unchanged["flow"]["version"] == before["flow"]["version"]
    assert unchanged["events"] == before["events"]
    assert unchanged["production_process"]["events"] == before["production_process"]["events"]
    confirm_source(api, workspace_id, requirement_id)
    accepted_evidence(api, workspace_id, requirement_id)
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    completed = advance(api, item_id)
    assert completed["flow"]["current_step"] == (None if step == 24 else step + 1)


@pytest.mark.parametrize("step", [23, 24])
def test_late_baseline_cannot_skip_an_active_project_shipping_gate(api, step):
    from test_flow import PROJECT, action_body, advance, create_item, enroll, inspect_dimensions
    item_id = create_item(api, "QUALITY-BASELINE-ASSEMBLY", kind="Assembly")
    child = create_item(api, "QUALITY-BASELINE-SPOOL", kind="Spool")
    plan = ok(api.get(f"/api/tracking/spools/{child}"))["plan"]
    ok(api.post(f"/api/tracking/spools/{child}/plan", {
        "project_id": PROJECT, "assembly_id": item_id, "planned_welds": 0,
        "zero_weld_reason": "This test package has no additional welded joints",
        "expected_version": plan["version"],
    }))
    enroll(api, child, "spool", start_step=15)
    inspect_dimensions(api, child)
    advance(api, child, role="inspector")
    advance(api, child)
    # A legacy released assembly may be enrolled after QA. Historical baseline
    # enrollment is not approval to bypass newly configured shipment controls.
    inspect_dimensions(api, item_id)
    ok(api.post(f"/api/items/{item_id}/release", {"reference": "TEST-LEGACY-RELEASE"}, role="inspector"))
    enroll(api, item_id, "assembly", start_step=step, expected_children=1)
    workspace_id = workspace(api, project_id=PROJECT)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, gate="shipment")
    response = api.post(f"/api/flow/items/{item_id}/advance", action_body(api, item_id))
    assert response.status_code == 409, response.text
    assert "quality" in response.text.lower() or "audit" in response.text.lower() or "requirement" in response.text.lower()
    assert req(api, workspace_id, requirement_id)["status"] != "verified"
    confirm_source(api, workspace_id, requirement_id)
    accepted_evidence(api, workspace_id, requirement_id)
    review_ok(review(api, workspace_id, "requirement", requirement_id, "verified"))
    assert advance(api, item_id)["flow"]["current_step"] == (None if step == 24 else step + 1)


def test_reviewed_not_applicable_gate_allows_the_relevant_step(api):
    from test_flow import PROJECT, advance
    item_id = assembly_at_step(api, 20)
    workspace_id = workspace(api, project_id=PROJECT)["workspace"]["id"]
    requirement_id = create_requirement(api, workspace_id, gate="pre_coating", applicability="not_applicable",
        applicability_reason="Written customer scope confirms this specific requirement is excluded.")
    confirm_source(api, workspace_id, requirement_id)
    review_ok(review(api, workspace_id, "requirement", requirement_id, "not_applicable"))
    assert advance(api, item_id)["flow"]["current_step"] == 21


def test_organizational_readiness_does_not_implicitly_gate_production(api):
    from test_flow import advance
    item_id = assembly_at_step(api, 20)
    workspace_id = workspace(api, template="kelvion")["workspace"]["id"]
    assert current(api, workspace_id)["metrics"]["verified"] == 0
    result = advance(api, item_id)
    assert result["flow"]["current_step"] == 21


def test_evidence_documents_reviews_and_event_history_have_no_edit_or_delete_routes(api):
    workspace_id = workspace(api)["workspace"]["id"]
    requirement_id, evidence_id = verified_requirement(api, workspace_id)
    document_id = create_document(api, workspace_id)
    for suffix in (f"evidence/{evidence_id}", f"documents/{document_id}", "reviews/1", "events/1"):
        path = f"{ROOT}/workspaces/{workspace_id}/{suffix}"
        assert api.put(path, {}).status_code in (404, 405)
        assert api.request("DELETE", path).status_code in (404, 405)
    quality = importlib.import_module("quality")
    with api.session_factory() as session:
        rows = session.scalars(select(quality.QualityEvent).where(quality.QualityEvent.workspace_id == workspace_id)).all()
        assert rows
        assert all(row.actor in BADGES.values() and row.at is not None for row in rows)
