"""Independent Job Packet acceptance tests using synthetic local records.

These tests do not read customer files or deployed data. They distinguish
uploaded evidence, signed checklist decisions, physical release, immutable
issued packets, dispatch of a packet, and acknowledged receipt of a packet.
"""

import datetime as dt
import hashlib
import importlib
import io
import json
import zipfile

import pytest
from sqlalchemy import event, select

from conftest import BADGES, TEST_PIN, TEST_SECRET
from tracking_helpers import add_weld, approve, complete_weld, find_requirement, ok
from test_flow import (
    PROJECT, action_body, advance, create_item, detail as flow_detail,
    enroll, inspect_dimensions, link_spool,
)
from test_progress import database_state
from test_quality import assembly_at_step


ROOT = "/api/dossier"
TODAY = dt.date.today().isoformat()
PDF = b"%PDF-1.4\n% Synthetic local test attachment; no customer evidence.\n%%EOF\n"
REQUIRED = {
    "contact", "purchase_order", "contents", "drawings", "materials", "itp",
    "dimensions", "nonconformance", "release", "packing_slip",
}
FILE_SECTIONS = {"purchase_order": "01", "drawings": "01", "materials": "02", "itp": "04", "packing_slip": "09"}
PRESSURE_VALUES = {
    "test_id": "TEST-PRESSURE-PACKAGE covers the selected synthetic spool",
    "pressure": "150 psi (synthetic fixture value)", "duration": "30 minutes",
    "basis": "TEST-APPROVED-PLAN and TEST-GAUGE-CAL-001",
    "result": "pass", "approval": "TEST-QA-PRESSURE-APPROVAL",
}


def project(api, project_id=PROJECT):
    return ok(api.get(f"{ROOT}/projects/{project_id}"))


def packet(api, item_id):
    return ok(api.get(f"{ROOT}/items/{item_id}"))


def checks(detail):
    return {row["code"]: row for section in detail["sections"] for row in section["checks"]}


def check(api, item_id, code):
    return checks(packet(api, item_id))[code]


def version(api, project_id=PROJECT):
    return project(api, project_id)["version"]


def config_body(**values):
    return {
        "manufacturer_name": "CLM Synthetic Test Fabrication",
        "manufacturer_contact": "Synthetic QA desk, test@example.invalid",
        "purchase_order": "TEST-PO-JOB-PACKET", "work_order": "TEST-WORK-ORDER",
        "advisements": "Synthetic preservation instructions apply to the fixture only.",
        "source_reference": "TEST-QF-QAS-100-REV-B-P8 plus synthetic PO review",
        "expected_packets": 1, "shipping_gate": True,
        "customer_approval_required": False, "notes": "Isolated test project applicability",
        **values,
    }


def configure(api, project_id=PROJECT, *, role="admin", expected_version=0, **values):
    response = api.put(f"{ROOT}/projects/{project_id}/config", {
        **config_body(**values), "expected_version": expected_version,
    }, role=role)
    assert response.status_code in (200, 201), response.text
    return project(api, project_id)


def sign_source(api, project_id=PROJECT, *, role="inspector", **values):
    return api.post(f"{ROOT}/projects/{project_id}/source-review", {
        "expected_version": version(api, project_id), "reference": "TEST-SOURCE-APPLICABILITY-REVIEW",
        "notes": "The synthetic current PO, sources, scope, and quality codes were reviewed.",
        **values,
    }, role=role)


def signed(response):
    assert response.status_code in (200, 201), response.text
    return response.json()


def upload(api, *, project_id=PROJECT, code="TEST-DOCUMENT", revision="A", section="01", item_id=None,
           filename="synthetic-evidence.pdf", content=PDF, media_type="application/pdf", role="supervisor",
           expected_version=None):
    before = version(api, project_id) if expected_version is None else expected_version
    data = {"expected_version": str(before), "code": code, "title": "Synthetic actual supporting record",
            "revision": revision, "section": section, "reference": "TEST-CONTROLLED-FILE"}
    if item_id is not None:
        data["item_id"] = item_id
    return api.request("POST", f"{ROOT}/projects/{project_id}/documents", role=role,
        data=data, files={"file": (filename, content, media_type)})


def document(api, **values):
    signed(upload(api, **values))
    rows = project(api, values.get("project_id", PROJECT))["documents"]
    return max(rows, key=lambda row: row["id"])


def entry(api, item_id, code, *, project_id=PROJECT, role="supervisor", expected_version=None, **values):
    return api.put(f"{ROOT}/items/{item_id}/checks/{code}", {
        "expected_version": version(api, project_id) if expected_version is None else expected_version,
        "applicability": "required", "reference": "TEST-RECORD-" + code.upper(),
        "notes": "Synthetic record reviewed against the explicitly stated test scope.",
        "document_ids": [], "values": {}, **values,
    }, role=role)


def review(api, item_id, code, *, project_id=PROJECT, role="inspector", expected_version=None,
           decision="accepted", **values):
    return api.post(f"{ROOT}/items/{item_id}/checks/{code}/review", {
        "expected_version": version(api, project_id) if expected_version is None else expected_version,
        "decision": decision, "reference": "TEST-QA-REVIEW-" + code.upper(),
        "notes": "The current synthetic evidence and actual scope were independently reviewed.",
        **values,
    }, role=role)


def issue_item(api, item_id, *, project_id=PROJECT, role="inspector", **values):
    return api.post(f"{ROOT}/items/{item_id}/issue", {
        "expected_version": version(api, project_id), "reference": "TEST-ISSUED-ITEM-PACKET",
        "notes": "Synthetic complete packet reviewed and authorized for issue.", **values,
    }, role=role)


def issue_project(api, project_id=PROJECT, *, role="inspector", **values):
    return api.post(f"{ROOT}/projects/{project_id}/issue", {
        "expected_version": version(api, project_id), "reference": "TEST-ISSUED-PROJECT-PACKET",
        "notes": "Every expected synthetic packet and physical release was reviewed.", **values,
    }, role=role)


def make_project(api, item_id="DOSSIER-SPOOL", *, project_id=PROJECT, planned=0, **values):
    create_item(api, item_id, kind="Spool", planned=planned, project=project_id)
    record_drawing_revision(api, item_id, project_id=project_id)
    configure(api, project_id, **values)
    return item_id


def record_drawing_revision(api, item_id, *, project_id=PROJECT):
    plan = ok(api.get(f"/api/tracking/spools/{item_id}"))["plan"]
    return ok(api.post(f"/api/tracking/spools/{item_id}/plan", {
        "expected_version": plan["version"], "project_id": project_id,
        "planned_welds": plan["planned_welds"], "zero_weld_reason": plan["zero_weld_reason"],
        "drawing_revision": "TEST-REV-A", "subproject_id": plan["subproject_id"],
        "assembly_id": plan["assembly_id"],
    }))


def physical_release(api, item_id):
    inspect_dimensions(api, item_id)
    return ok(api.post(f"/api/items/{item_id}/release", {"reference": "TEST-DOSSIER-PHYSICAL-QA"}, role="inspector"))


def complete_packet(api, item_id, *, project_id=PROJECT, source=True, customer_shipping=False,
                    required_values=None, skip_checks=()):
    """Prepare explicit fixture evidence; this helper never issues a packet."""
    if source:
        signed(sign_source(api, project_id))
    required_values = required_values or {}
    required = REQUIRED | ({"customer_shipping"} if customer_shipping else set()) | set(required_values)
    for code, row in checks(packet(api, item_id)).items():
        if code in skip_checks:
            continue
        if code in required:
            values = {}
            if code in FILE_SECTIONS or code == "customer_shipping" or code in required_values:
                attachment = document(api, project_id=project_id, code="TEST-" + code.upper() + "-" + item_id,
                    section=FILE_SECTIONS.get(code, row["section"]), item_id=item_id)
                values["document_ids"] = [attachment["id"]]
            if code in required_values:
                values["values"] = required_values[code]
            if code == "customer_shipping":
                values["values"] = {"scope": "Synthetic PO and selected item authorized",
                                    "authority": "Synthetic authorized customer approver TEST-D04"}
            signed(entry(api, item_id, code, project_id=project_id, **values))
            signed(review(api, item_id, code, project_id=project_id))
        else:
            signed(entry(api, item_id, code, project_id=project_id, applicability="not_applicable",
                reference="TEST-APPROVED-SCOPE-EXCLUSION",
                notes="The synthetic approved scope excludes this activity for this zero-weld uncoated fixture."))
            signed(review(api, item_id, code, project_id=project_id, decision="not_applicable"))
    return packet(api, item_id)


def issued_fixture(api, item_id="DOSSIER-ISSUED", *, project_id=PROJECT):
    make_project(api, item_id, project_id=project_id)
    physical_release(api, item_id)
    ready = complete_packet(api, item_id, project_id=project_id)
    assert ready["status"] == "ready_for_issue", ready["blockers"]
    signed(issue_item(api, item_id, project_id=project_id))
    return packet(api, item_id)["latest_issue"]


def test_template_is_draft_and_tracks_job_packet_sources_without_inventing_acceptance(api):
    item_id = make_project(api)
    detail = packet(api, item_id)
    rows = checks(detail)
    assert len(detail["sections"]) == 10 and len(rows) == 25
    assert {"contact", "purchase_order", "advisements", "contents", "drawings", "product_data", "materials", "itp"} <= set(rows)
    assert "QF-QAS-100" in rows["itp"]["source"] and "p8" in rows["itp"]["source"]
    assert "100% VT" in rows["visual"]["source"]
    assert "3.9.C.2" in rows["pressure"]["source"]
    assert "D04" in rows["customer_shipping"]["source"]
    assert all(row["status"] not in ("accepted", "not_applicable") for row in rows.values())
    assert detail["percent"] == 0 and detail["source_status"] != "confirmed"
    assert detail["issues"] == [] and detail["latest_issue"] is None
    assert detail["documents"] == [] and detail["records"]["tracking"]["welds"] == []
    assert issue_item(api, item_id).status_code == 409
    assert issue_project(api).status_code == 409


def test_authentication_and_roles_distinguish_evidence_writing_from_qa_signoff(api):
    item_id = make_project(api)
    for path in ("/catalog", "/projects", f"/projects/{PROJECT}", f"/items/{item_id}"):
        assert api.get(ROOT + path, role=None).status_code == 401
    for role in ("handler", "welder"):
        assert api.get(f"{ROOT}/items/{item_id}", role=role).status_code == 200
        assert entry(api, item_id, "advisements", role=role).status_code == 403
        assert upload(api, role=role).status_code == 403
        assert issue_item(api, item_id, role=role).status_code == 403
    signed(entry(api, item_id, "advisements", role="supervisor"))
    assert review(api, item_id, "advisements", role="supervisor").status_code == 403
    assert sign_source(api, role="supervisor").status_code == 403
    assert issue_item(api, item_id, role="supervisor").status_code == 403
    signed(sign_source(api))
    signed(review(api, item_id, "advisements"))
    row = check(api, item_id, "advisements")
    assert row["status"] == "accepted"
    assert row["latest_review"]["actor"] == BADGES["inspector"]


def test_supervisor_cannot_disable_configured_shipping_controls_or_spoof_review_actor(api):
    item_id = make_project(api, customer_approval_required=True)
    before = database_state(api)
    response = api.put(f"{ROOT}/projects/{PROJECT}/config", {
        **config_body(shipping_gate=False, customer_approval_required=False),
        "expected_version": version(api),
    }, role="supervisor")
    assert response.status_code == 403, response.text
    assert database_state(api) == before
    signed(sign_source(api))
    signed(entry(api, item_id, "advisements"))
    response = review(api, item_id, "advisements", actor=BADGES["admin"])
    assert response.status_code == 422, response.text
    assert check(api, item_id, "advisements")["latest_review"] is None


def test_evidence_submission_alone_never_means_accepted_or_ready_to_issue(api):
    item_id = make_project(api)
    signed(sign_source(api))
    file = document(api)
    signed(entry(api, item_id, "purchase_order", document_ids=[file["id"]]))
    row = check(api, item_id, "purchase_order")
    assert row["status"] not in ("accepted", "not_applicable") and row["latest_review"] is None
    assert packet(api, item_id)["percent"] == 0
    signed(review(api, item_id, "purchase_order"))
    assert check(api, item_id, "purchase_order")["status"] == "accepted"
    assert issue_item(api, item_id).status_code == 409


def test_every_mutation_uses_the_current_project_version_and_stale_writes_are_atomic(api):
    item_id = make_project(api)
    prior_version = version(api)
    signed(entry(api, item_id, "advisements", expected_version=prior_version))
    before = database_state(api)
    response = entry(api, item_id, "product_data", expected_version=prior_version)
    assert response.status_code == 409, response.text
    assert upload(api, expected_version=prior_version).status_code == 409
    assert review(api, item_id, "advisements", expected_version=prior_version).status_code == 409
    assert database_state(api) == before
    assert version(api) == prior_version + 1


@pytest.mark.parametrize("overrides", [
    {"expected_packets": 0}, {"expected_packets": -1}, {"expected_packets": True},
    {"expected_version": True}, {"expected_version": -1}, {"manufacturer_contact": " "},
])
def test_invalid_project_scope_and_versions_do_not_create_a_packet_configuration(api, overrides):
    create_item(api, "DOSSIER-INVALID", kind="Spool")
    before = database_state(api)
    response = api.put(f"{ROOT}/projects/{PROJECT}/config", {
        **config_body(), "expected_version": 0, **overrides,
    })
    assert response.status_code == 422, response.text
    assert database_state(api) == before


def test_mandatory_checks_and_customer_shipping_cannot_be_waived_and_na_needs_rationale(api):
    item_id = make_project(api, customer_approval_required=True)
    signed(sign_source(api))
    for code in ("materials", "drawings", "itp", "release", "customer_shipping"):
        response = entry(api, item_id, code, applicability="not_applicable", reference="TEST-EXCLUSION",
            notes="Attempt to exclude a mandatory control in a synthetic test.")
        if response.status_code in (200, 201):
            response = review(api, item_id, code, decision="not_applicable")
        assert response.status_code in (409, 422), response.text
        assert check(api, item_id, code)["status"] != "not_applicable"
    response = entry(api, item_id, "brazing_bonding", applicability="not_applicable", reference="", notes="")
    if response.status_code in (200, 201):
        response = review(api, item_id, "brazing_bonding", decision="not_applicable")
    assert response.status_code in (409, 422), response.text
    signed(entry(api, item_id, "brazing_bonding", applicability="not_applicable",
        reference="TEST-APPROVED-BOM", notes="This synthetic BOM has only welded joints and no brazed or bonded joints."))
    signed(review(api, item_id, "brazing_bonding", decision="not_applicable"))
    assert check(api, item_id, "brazing_bonding")["status"] == "not_applicable"


def test_attachments_preserve_exact_bytes_name_hash_and_authenticated_download(api):
    item_id = make_project(api)
    file = document(api, item_id=item_id, filename="MTR-test-rev-A.pdf")
    assert file["filename"] == "MTR-test-rev-A.pdf"
    assert file["size_bytes"] == len(PDF)
    assert file["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert file["item_id"] == item_id and file["actor"] == BADGES["supervisor"]
    path = f"{ROOT}/documents/{file['id']}/download"
    assert api.get(path, role=None).status_code == 401
    response = api.get(path)
    assert response.status_code == 200 and response.content == PDF
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in response.headers["content-disposition"]


@pytest.mark.parametrize("filename,content,media_type", [
    ("payload.html", b"<script>alert(1)</script>", "text/html"),
    ("payload.pdf", b"not a PDF", "application/pdf"),
    ("empty.txt", b"", "text/plain"),
    ("large.txt", b"x" * (8 * 1024 * 1024 + 1), "text/plain"),
])
def test_unsafe_empty_mismatched_and_oversize_attachments_are_rejected_atomically(api, filename, content, media_type):
    make_project(api)
    before = database_state(api)
    response = upload(api, filename=filename, content=content, media_type=media_type)
    assert response.status_code in (413, 415, 422), response.text
    assert database_state(api) == before


def test_attachment_path_and_header_characters_cannot_escape_download_or_zip_names(api):
    make_project(api)
    response = upload(api, filename="../../outside.pdf")
    assert response.status_code in (200, 201, 422), response.text
    if response.status_code in (200, 201):
        file = project(api)["documents"][-1]
        assert "/" not in file["filename"] and "\\" not in file["filename"]
        assert file["filename"] not in (".", "..")
        response = api.get(f"{ROOT}/documents/{file['id']}/download")
        assert response.status_code == 200
        assert "\r" not in response.headers["content-disposition"] and "\n" not in response.headers["content-disposition"]


def test_files_and_check_references_cannot_cross_project_or_sibling_item_scope(api):
    item_id = make_project(api)
    sibling = create_item(api, "DOSSIER-SIBLING", kind="Spool")
    other = make_project(api, "DOSSIER-OTHER", project_id="DOSSIER-OTHER-PROJECT")
    own_file = document(api, item_id=item_id)
    other_file = document(api, project_id="DOSSIER-OTHER-PROJECT", item_id=other)
    assert upload(api, item_id=other, code="CROSS-PROJECT").status_code == 422
    assert entry(api, item_id, "drawings", document_ids=[other_file["id"]]).status_code == 422
    assert entry(api, sibling, "drawings", document_ids=[own_file["id"]]).status_code == 422
    assert entry(api, item_id, "drawings", document_ids=[999999]).status_code == 422
    shared = document(api, code="PROJECT-SHARED")
    signed(entry(api, sibling, "drawings", document_ids=[shared["id"]]))
    assert check(api, sibling, "drawings")["document_ids"] == [shared["id"]]


def test_new_document_revision_stales_acceptance_without_rewriting_old_file_or_review(api):
    item_id = make_project(api)
    signed(sign_source(api))
    first = document(api, code="TEST-MTR", revision="A", section="02")
    signed(entry(api, item_id, "materials", document_ids=[first["id"]]))
    signed(review(api, item_id, "materials"))
    prior_review = check(api, item_id, "materials")["latest_review"]
    second = document(api, code="TEST-MTR", revision="B", section="02", content=PDF + b"% revision B\n")
    row = check(api, item_id, "materials")
    assert row["status"] != "accepted" and row["latest_review"] == prior_review
    assert any("superseded" in text.lower() for text in row["blockers"])
    assert review(api, item_id, "materials").status_code == 409
    assert api.get(f"{ROOT}/documents/{first['id']}/download").content == PDF
    signed(entry(api, item_id, "materials", document_ids=[second["id"]]))
    signed(review(api, item_id, "materials"))
    assert check(api, item_id, "materials")["status"] == "accepted"


def test_duplicate_document_revision_cannot_replace_original_bytes_or_metadata(api):
    make_project(api)
    first = document(api, code="TEST-NO-OVERWRITE", revision="A")
    before = database_state(api)
    response = upload(api, code="TEST-NO-OVERWRITE", revision="A", filename="replacement.pdf",
        content=PDF + b"% this replacement must not be stored\n")
    assert response.status_code == 409, response.text
    assert database_state(api) == before
    assert api.get(f"{ROOT}/documents/{first['id']}/download").content == PDF


def test_po_and_source_change_require_fresh_confirmation_and_signed_check_review(api):
    item_id = make_project(api)
    signed(sign_source(api))
    signed(entry(api, item_id, "contact"))
    signed(review(api, item_id, "contact"))
    before = check(api, item_id, "contact")
    source_review = project(api)["source_review"]
    configure(api, expected_version=version(api), purchase_order="TEST-REVISED-PO")
    assert project(api)["source_status"] != "confirmed"
    assert project(api)["source_review"] == source_review
    assert check(api, item_id, "contact")["status"] == "stale"
    assert review(api, item_id, "contact").status_code == 409
    signed(sign_source(api))
    assert check(api, item_id, "contact")["status"] == "stale"
    signed(review(api, item_id, "contact"))
    after = check(api, item_id, "contact")
    assert after["status"] == "accepted"
    assert after["latest_review"]["id"] != before["latest_review"]["id"]


def test_contact_only_edit_preserves_pressure_proof_but_requires_source_and_contact_reconfirmation(api):
    item_id = make_project(api)
    signed(sign_source(api))
    signed(entry(api, item_id, "contact"))
    signed(review(api, item_id, "contact"))
    file = document(api, code="TEST-CONTACT-PRESSURE", section="06", item_id=item_id)
    signed(entry(api, item_id, "pressure", document_ids=[file["id"]], values=PRESSURE_VALUES))
    signed(review(api, item_id, "pressure"))
    pressure_before = check(api, item_id, "pressure")
    contact_before = check(api, item_id, "contact")
    source_before = project(api)["source_review"]

    configure(api, expected_version=version(api),
        manufacturer_contact="Updated synthetic QA contact, revised@example.invalid")

    assert project(api)["source_status"] == "needs_confirmation"
    assert project(api)["source_review"] == source_before
    contact_after = check(api, item_id, "contact")
    assert contact_after["status"] == "stale"
    assert contact_after["fingerprint"] != contact_before["fingerprint"]
    assert contact_after["latest_review"] == contact_before["latest_review"]
    pressure_after = check(api, item_id, "pressure")
    assert pressure_after["status"] == "accepted"
    assert pressure_after["fingerprint"] == pressure_before["fingerprint"]
    assert pressure_after["latest_review"] == pressure_before["latest_review"]

    # Reconfirm the changed administrative source basis. This must neither
    # manufacture a fresh pressure test nor require re-review of unchanged
    # technical proof. The changed contact itself still needs its own review.
    signed(sign_source(api))
    assert project(api)["source_status"] == "confirmed"
    assert project(api)["source_review"]["id"] != source_before["id"]
    assert check(api, item_id, "contact")["status"] == "stale"
    assert check(api, item_id, "pressure")["status"] == "accepted"
    assert check(api, item_id, "pressure")["fingerprint"] == pressure_before["fingerprint"]
    assert check(api, item_id, "pressure")["latest_review"] == pressure_before["latest_review"]
    signed(review(api, item_id, "contact"))
    assert check(api, item_id, "contact")["status"] == "accepted"
    assert check(api, item_id, "pressure")["latest_review"] == pressure_before["latest_review"]


def test_material_change_invalidates_signed_pressure_but_routine_custody_does_not(api):
    item_id = make_project(api, planned=1)
    weld = add_weld(api, item_id)
    signed(sign_source(api))
    file = document(api, code="TEST-PRESSURE", section="06", item_id=item_id)
    signed(entry(api, item_id, "pressure", document_ids=[file["id"]], values=PRESSURE_VALUES))
    signed(review(api, item_id, "pressure"))
    signed_before = check(api, item_id, "pressure")
    ok(api.post(f"/api/items/{item_id}/transfer", {
        "location": "Synthetic inspection bay", "handler": BADGES["handler"],
        "notes": "Routine custody only; no material or work changed.",
    }, role="handler"))
    assert check(api, item_id, "pressure")["status"] == "accepted"
    assert check(api, item_id, "pressure")["fingerprint"] == signed_before["fingerprint"]
    ok(api.patch(f"/api/tracking/welds/{weld['id']}", {
        "expected_version": weld["version"], "heat_a": "TEST-REPLACEMENT-HEAT",
        "change_reason": "Controlled replacement material after the recorded pressure test",
    }))
    row = check(api, item_id, "pressure")
    assert row["status"] == "stale"
    assert row["latest_review"] == signed_before["latest_review"]


def test_new_physical_weld_work_stales_pressure_and_visual_cannot_waive_real_welds(api):
    item_id = make_project(api, planned=1)
    weld = add_weld(api, item_id)
    signed(sign_source(api))
    file = document(api, section="06")
    signed(entry(api, item_id, "pressure", document_ids=[file["id"]], values=PRESSURE_VALUES))
    signed(review(api, item_id, "pressure"))
    ok(api.post(f"/api/tracking/welds/{weld['id']}/work", {
        "operation": "fitup", "notes": "New physical weld fit-up after the pressure-test record",
    }, role="welder"))
    assert check(api, item_id, "pressure")["status"] == "stale"
    for code in ("weld_log", "visual", "procedures"):
        response = entry(api, item_id, code, applicability="not_applicable",
            reference="TEST-SCOPE", notes="This waiver must fail because the scope contains an actual weld.")
        if response.status_code in (200, 201):
            response = review(api, item_id, code, decision="not_applicable")
        assert response.status_code in (409, 422), response.text


def test_visual_packet_check_requires_accepted_vt_for_every_actual_weld(api):
    item_id = make_project(api, planned=2)
    first = add_weld(api, item_id, number="W01")
    second = add_weld(api, item_id, number="W02")
    for weld in (first, second):
        complete_weld(api, item_id, weld["id"])
    signed(sign_source(api))
    first_vt = find_requirement(api, item_id, first["id"], code="VT")
    second_vt = find_requirement(api, item_id, second["id"], code="VT")
    approve(api, item_id, first_vt["id"], reference="TEST-VT-W01")
    signed(entry(api, item_id, "visual", reference="TEST-WELD-VT-REGISTER",
        notes="Review each individually identified weld against its actual visual-examination record."))
    response = review(api, item_id, "visual")
    assert response.status_code == 409 and "W02" in response.text, response.text
    approve(api, item_id, second_vt["id"], reference="TEST-VT-W02")
    signed(review(api, item_id, "visual"))
    assert check(api, item_id, "visual")["status"] == "accepted"
    assert issue_item(api, item_id).status_code == 409


@pytest.mark.parametrize("bad_values", [{}, {**PRESSURE_VALUES, "pressure": ""}, {**PRESSURE_VALUES, "result": "fail"}])
def test_pressure_requires_actual_measurements_and_passing_result_before_signoff(api, bad_values):
    item_id = make_project(api)
    signed(sign_source(api))
    file = document(api, section="06")
    response = entry(api, item_id, "pressure", document_ids=[file["id"]], values=bad_values)
    if response.status_code in (200, 201):
        response = review(api, item_id, "pressure")
    assert response.status_code in (409, 422), response.text
    assert check(api, item_id, "pressure")["status"] != "accepted"


def test_project_release_requires_explicit_expected_count_and_all_current_item_packets(api):
    first = make_project(api, expected_packets=2)
    physical_release(api, first)
    complete_packet(api, first)
    signed(issue_item(api, first))
    response = issue_project(api)
    assert response.status_code == 409, response.text
    second = create_item(api, "DOSSIER-SECOND", kind="Spool")
    record_drawing_revision(api, second)
    assert issue_project(api).status_code == 409
    physical_release(api, second)
    complete_packet(api, second, source=False)
    assert issue_project(api).status_code == 409
    signed(issue_item(api, second))
    signed(issue_project(api))
    assert project(api)["latest_issue"]["current"]
    ok(api.post(f"/api/items/{second}/reopen"))
    assert not project(api)["latest_issue"]["current"]
    assert issue_project(api).status_code == 409


def test_project_issue_cannot_hide_an_unplanned_registered_part(api):
    issued_fixture(api)
    create_item(api, "DOSSIER-UNRESOLVED-LEGACY")
    response = issue_project(api)
    assert response.status_code == 409, response.text
    assert "DOSSIER-UNRESOLVED-LEGACY" in response.text


def test_issued_snapshot_and_zip_are_immutable_and_export_no_authentication_secrets(api):
    issued = issued_fixture(api)
    issue_id = issued["id"]
    snapshot_path = f"{ROOT}/issues/{issue_id}"
    download_path = f"{ROOT}/issues/{issue_id}/download"
    before = database_state(api)
    original = ok(api.get(snapshot_path))
    downloaded = api.get(download_path)
    assert downloaded.status_code == 200
    assert database_state(api) == before
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert any(name.endswith(".json") for name in names)
        assert any(name.endswith(".html") for name in names)
        assert any(name.endswith(".pdf") for name in names)
        assert all(not name.startswith(("/", "\\")) and ".." not in name.split("/") for name in names)
        original_files = {name: archive.read(name) for name in names}
        all_bytes = b"\n".join(original_files.values())
        for forbidden in (TEST_PIN, TEST_SECRET, "pin_hash", "password_hash", "fabtrace_session"):
            assert forbidden.encode() not in all_bytes
    # A controlled live document revision must stale the live packet while an
    # already issued package keeps the exact prior evidence and snapshot.
    document(api, code="TEST-PURCHASE_ORDER-DOSSIER-ISSUED", revision="B", item_id="DOSSIER-ISSUED",
        content=PDF + b"% replacement controlled revision\n")
    assert not packet(api, "DOSSIER-ISSUED")["latest_issue"]["current"]
    assert ok(api.get(snapshot_path)) == original
    later = api.get(download_path)
    assert later.status_code == 200
    with zipfile.ZipFile(io.BytesIO(later.content)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == original_files


def test_issued_print_and_zip_retain_exact_html_after_a_later_renderer_change(api, monkeypatch):
    issued = issued_fixture(api)
    printed = api.get(f"{ROOT}/issues/{issued['id']}/print")
    archived = api.get(f"{ROOT}/issues/{issued['id']}/download")
    assert printed.status_code == archived.status_code == 200
    dossier = importlib.import_module("dossier")
    monkeypatch.setattr(dossier, "_render_item", lambda *args, **kwargs: "FUTURE-RENDERER-CONTENT")
    retained_print = api.get(f"{ROOT}/issues/{issued['id']}/print")
    retained_zip = api.get(f"{ROOT}/issues/{issued['id']}/download")
    assert retained_print.content == printed.content
    assert retained_zip.content == archived.content
    assert hashlib.sha256(printed.content).hexdigest() == issued["print_sha256"]


def test_dossier_get_preview_and_download_are_read_only_and_never_record_a_dispatch(api):
    issued = issued_fixture(api)
    before = database_state(api)
    statements = []
    engine = api.session_factory.kw["bind"]

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement.strip().upper())

    event.listen(engine, "before_cursor_execute", observe)
    try:
        for path in ("/catalog", "/projects", f"/projects/{PROJECT}", "/items/DOSSIER-ISSUED",
                     f"/issues/{issued['id']}", f"/issues/{issued['id']}/print", f"/issues/{issued['id']}/download"):
            response = api.get(ROOT + path)
            assert response.status_code == 200, response.text
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert database_state(api) == before
    assert not any(statement.startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements)
    assert not any("FOR UPDATE" in statement or "PG_ADVISORY_XACT_LOCK" in statement for statement in statements)
    assert project(api)["handovers"] == []


def test_digital_and_physical_dispatch_and_receipt_are_separate_explicit_events(api):
    issued_fixture(api)
    signed(issue_project(api))
    issue = project(api)["latest_issue"]
    future = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    invalid_dispatch = {"expected_version": version(api), "issue_id": issue["id"], "channel": "digital",
        "recipient": "Synthetic recipient", "organization": "Synthetic customer", "reference": "TEST-FUTURE",
        "notes": "A future dispatch cannot be recorded as an observed completed transfer.", "occurred_on": future}
    assert api.post(f"{ROOT}/projects/{PROJECT}/handovers", invalid_dispatch).status_code == 422
    assert project(api)["handovers"] == []
    for channel in ("digital", "physical"):
        signed(api.post(f"{ROOT}/projects/{PROJECT}/handovers", {
            "expected_version": version(api), "issue_id": issue["id"], "channel": channel,
            "recipient": "Synthetic recipient", "organization": "Synthetic customer",
            "reference": "TEST-" + channel.upper() + "-DISPATCH",
            "notes": "The exact issued synthetic packet was handed over via the stated channel.",
            "occurred_on": TODAY,
        }, role="supervisor"))
    rows = project(api)["handovers"]
    dispatches = [row for row in rows if row["event"] == "dispatch"]
    assert len(dispatches) == 2 and {row["channel"] for row in dispatches} == {"digital", "physical"}
    assert all(row["actor"] == BADGES["supervisor"] for row in dispatches)
    assert all(row["dispatch_id"] is None for row in dispatches)
    digital = next(row for row in dispatches if row["channel"] == "digital")
    receipt_path = f"{ROOT}/handovers/{digital['id']}/receipt"
    body = {"expected_version": version(api), "recipient": "Synthetic confirming receiver",
        "reference": "TEST-DIGITAL-SIGNED-RECEIPT", "notes": "Receipt independently confirmed for the stated issued revision.",
        "occurred_on": TODAY}
    assert api.post(receipt_path, {**body, "reference": ""}).status_code == 422
    signed(api.post(receipt_path, body, role="supervisor"))
    rows = project(api)["handovers"]
    receipts = [row for row in rows if row["event"] == "receipt"]
    assert len(receipts) == 1 and receipts[0]["channel"] == "digital"
    assert receipts[0]["dispatch_id"] == digital["id"]
    assert receipts[0]["reference"] == "TEST-DIGITAL-SIGNED-RECEIPT"
    assert receipts[0]["actor"] == BADGES["supervisor"]
    assert not any(row["channel"] == "physical" and row["event"] == "receipt" for row in rows)
    assert api.post(receipt_path, {**body, "expected_version": version(api)}).status_code == 409


@pytest.mark.parametrize("step", [20, 21, 23, 24])
def test_configured_packet_gates_block_flow_atomically_including_late_baselines(api, step):
    item_id = assembly_at_step(api, step)
    configure(api, expected_packets=2, customer_approval_required=True)
    before = flow_detail(api, item_id)
    before_db = database_state(api)
    response = api.post(f"/api/flow/items/{item_id}/advance", action_body(api, item_id))
    assert response.status_code == 409, response.text
    assert "packet" in response.text.lower() or "dossier" in response.text.lower() or "pressure" in response.text.lower()
    after = flow_detail(api, item_id)
    assert after["flow"]["version"] == before["flow"]["version"]
    assert after["flow"]["current_step"] == step
    assert after["events"] == before["events"]
    assert after["production_process"]["events"] == before["production_process"]["events"]
    assert database_state(api) == before_db


def accept_pressure(api, item_id):
    file = document(api, code="TEST-PRESSURE-" + item_id, section="06", item_id=item_id)
    signed(entry(api, item_id, "pressure", document_ids=[file["id"]],
        values={**PRESSURE_VALUES, "test_id": "TEST-PRESSURE-PACKAGE for " + item_id}))
    signed(review(api, item_id, "pressure"))
    signed(entry(api, item_id, "customer_hold", applicability="not_applicable",
        reference="TEST-APPROVED-HOLD-POINT-SCHEDULE",
        notes="The synthetic approved ITP has no customer witness or hold point before this coating stage."))
    signed(review(api, item_id, "customer_hold", decision="not_applicable"))


def test_pressure_gate_covers_children_and_finish_coating_does_not_stale_pressure(api):
    item_id = assembly_at_step(api, 20)
    configure(api, expected_packets=2)
    signed(sign_source(api))
    accept_pressure(api, item_id)
    response = api.post(f"/api/flow/items/{item_id}/advance", action_body(api, item_id))
    assert response.status_code == 409, response.text
    assert "QUALITY-ASSEMBLY-SPOOL" in response.text
    accept_pressure(api, "QUALITY-ASSEMBLY-SPOOL")
    approved = check(api, item_id, "pressure")
    advanced = advance(api, item_id)
    assert advanced["flow"]["current_step"] == 21
    assert check(api, item_id, "pressure")["status"] == "accepted"
    advanced = advance(api, item_id)
    assert advanced["flow"]["current_step"] == 22
    after = check(api, item_id, "pressure")
    assert after["status"] == "accepted"
    assert after["fingerprint"] == approved["fingerprint"]
    assert after["latest_review"] == approved["latest_review"]


def test_ready_to_ship_requires_child_packets_and_d04_then_shipping_keeps_issued_proof_current(api):
    assembly = create_item(api, "DOSSIER-SHIP-ASSEMBLY", kind="Assembly")
    child = create_item(api, "DOSSIER-SHIP-CHILD", kind="Spool")
    for item_id in (assembly, child):
        record_drawing_revision(api, item_id)
    enroll(api, child, "spool", start_step=15)
    inspect_dimensions(api, child)
    advance(api, child, role="inspector")
    advance(api, child)
    enroll(api, assembly, "assembly", expected_children=1)
    link_spool(api, assembly, child)
    for step in range(17, 23):
        if step in (19, 22):
            inspect_dimensions(api, assembly)
        advance(api, assembly, role="inspector" if step in (19, 22) else "admin")
    configure(api, expected_packets=2, customer_approval_required=True)
    signed(sign_source(api))
    complete_packet(api, child, source=False, customer_shipping=True)
    coating_records = {
        "pressure": PRESSURE_VALUES,
        "surface": {"preparation": "TEST-PREP-REPORT with approved surface acceptance",
                    "conditions": "TEST-ENV-REPORT records substrate temperature, dew point, and humidity"},
        "coating": {"system": "TEST-SYSTEM batch TEST-PAINT-001", "dft": "TEST-DFT-REPORT actual readings and calibrated instrument",
                    "holiday": "No holiday examination required by the synthetic approved coating system", "result": "pass"},
        "packaging": {"protection": "Synthetic end caps and flange protection inspected",
                      "handling": "TEST-LIFT-PLAN records lifting, weight and securement",
                      "inspection": "TEST-PACKING-CHECK actual preservation and securement findings"},
    }
    complete_packet(api, assembly, source=False, customer_shipping=True,
        required_values=coating_records, skip_checks={"customer_shipping"})
    assert packet(api, assembly)["percent"] == 96
    assert check(api, assembly, "customer_shipping")["status"] == "missing"
    assert issue_item(api, assembly).status_code == 409
    before = database_state(api)
    response = api.post(f"/api/flow/items/{assembly}/advance", action_body(api, assembly))
    assert response.status_code == 409, response.text
    assert "authorization" in response.text.lower()
    assert database_state(api) == before
    authorization = document(api, code="TEST-KELVION-D04", section="10", item_id=assembly)
    signed(entry(api, assembly, "customer_shipping", document_ids=[authorization["id"]], values={
        "scope": "Synthetic PO, assembly and child spool approved for shipment",
        "authority": "TEST-KELVION-QA-APPROVER written authorization TEST-D04-001",
    }))
    signed(review(api, assembly, "customer_shipping"))
    # With every parent check accepted, the child still needs its own issued
    # packet. Released=true and a completed child checklist are insufficient.
    response = issue_item(api, assembly)
    assert response.status_code == 409 and child in response.text, response.text
    signed(issue_item(api, child))
    child_packet = packet(api, child)
    child_issue = child_packet["latest_issue"]
    signed(issue_item(api, assembly))
    issued = packet(api, assembly)["latest_issue"]
    assert issued["current"]
    response = api.get(f"{ROOT}/issues/{issued['id']}/download")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        prefix = f"items/{child_issue['id']}-revision-{child_issue['revision']}/"
        assert prefix + "job-packet.html" in names
        assert prefix + "snapshot.json" in names
        for file in child_packet["documents"]:
            assert f"files/{file['id']}_{file['filename']}" in names
    assert advance(api, assembly)["flow"]["current_step"] == 24
    assert packet(api, assembly)["latest_issue"]["current"]
    assert advance(api, assembly)["flow"]["status"] == "shipped"
    after = packet(api, assembly)["latest_issue"]
    assert after["id"] == issued["id"] and after["current"]
    assert packet(api, child)["latest_issue"]["current"]
    signed(issue_project(api))
    assert project(api)["latest_project_issue"]["current"]
