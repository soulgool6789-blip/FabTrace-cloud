"""Administrator roster removal preserves fabrication identities and evidence.

Every employee and production record here belongs to an isolated local database.
The tests exercise public APIs and retained records, never production accounts.
"""

import json

import pytest
from fastapi.testclient import TestClient

from conftest import BADGES, TEST_PIN
from tracking_helpers import ok
from test_admin import detail as admin_item, disposition_body, edit_employee
from test_dossier import checks, issued_fixture, packet
from test_legacy_workflow import inspect_both
from test_progress import database_state
from test_transfers import custody, transfer, transfer_body


ROOT = "/api/admin/employees"
REASON = "Synthetic employee departure reviewed by the administrator"


def roster(api, include_removed=False):
    return ok(api.get(ROOT, params={"include_removed": include_removed}))


def employee(api, badge):
    return next(row for row in roster(api, True)["employees"] if row["badge"] == badge)


def decision(api, badge, **values):
    return {"expected_version": employee(api, badge)["version"], "reason": REASON, **values}


def remove(api, badge, **values):
    return ok(api.post(f"{ROOT}/{badge}/remove", decision(api, badge, **values)))


def restore(api, badge, **values):
    return ok(api.post(f"{ROOT}/{badge}/restore", decision(api, badge, **values)))


def unchanged_rejection(api, call, status):
    before = database_state(api)
    response = call()
    assert response.status_code == status, response.text
    assert database_state(api) == before
    return response


@pytest.mark.parametrize("role", [None, *[role for role in BADGES if role != "admin"]])
def test_only_current_administrator_can_remove_restore_or_view_removed_roster(api, role):
    badge = BADGES["welder"]
    body = decision(api, badge)
    expected = 401 if role is None else 403
    for action in ("remove", "restore"):
        unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/{action}", body, role=role), expected)
    unchanged_rejection(api, lambda: api.get(ROOT, params={"include_removed": True}, role=role), expected)


def test_removal_hides_rosters_retains_identity_and_records_truthful_audit(api):
    badge = BADGES["welder"]
    initial = employee(api, badge)
    assert initial["removed"] is False and initial["can_remove"] is True
    assert initial["can_restore"] is False
    with api.session_factory() as session:
        original = session.get(api.application.Employee, badge)
        identity = (original.badge, original.name, original.role, original.pin_hash, original.created_at)
    removed = remove(api, badge)
    assert removed["removed"] is True and removed["active"] is False
    assert removed["version"] == initial["version"] + 1
    assert removed["removed_at"] and removed["removed_by"] == BADGES["admin"]
    assert removed["removal_reason"] == REASON
    assert removed["can_restore"] is True
    assert all(removed[key] is False for key in ("can_remove", "can_edit", "can_reset_pin"))
    assert removed["assigned_item_count"] == 0
    for path in (ROOT, "/api/employees", "/api/employees/directory"):
        listing = ok(api.get(path))
        rows = listing["employees"] if isinstance(listing, dict) else listing
        assert badge not in {row["badge"] for row in rows}
    all_staff = roster(api, True)
    assert all_staff["removed_count"] == 1 and all_staff["active_admins"] == 1
    assert len(all_staff["employees"]) == len(BADGES)
    assert employee(api, badge)["removed"] is True
    assert api.get(f"/api/employees/{badge}/qr.png").status_code == 404
    with api.session_factory() as session:
        retained = session.get(api.application.Employee, badge)
        assert (retained.badge, retained.name, retained.role, retained.pin_hash, retained.created_at) == identity
    events = [row for row in ok(api.get("/api/audit")) if row["event"] == "EMPLOYEE_REMOVED"]
    assert len(events) == 1 and events[0]["actor"] == BADGES["admin"]
    assert events[0]["details"]["reason"] == REASON
    assert "pin_hash" not in json.dumps([removed, all_staff, events])
    assert TEST_PIN not in json.dumps([removed, all_staff, events])
    before = database_state(api)
    roster(api)
    roster(api, True)
    api.get("/api/employees")
    api.get("/api/employees/directory")
    assert database_state(api) == before


def test_remove_restore_and_later_enable_never_resurrect_old_session(api):
    badge = BADGES["welder"]
    with TestClient(api.application.app) as signed_in:
        ok(signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        removed = remove(api, badge)
        assert signed_in.get("/api/me").status_code == 401
        assert signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}).status_code == 401
        restored = restore(api, badge, reason="Synthetic administrator restored the retained identity")
        assert restored["removed"] is False and restored["active"] is False
        assert restored["version"] == removed["version"] + 1
        assert restored["restored_at"] and restored["restored_by"] == BADGES["admin"]
        assert restored["can_restore"] is False and restored["can_edit"] is True
        assert roster(api)["removed_count"] == 0
        assert badge in {row["badge"] for row in roster(api)["employees"]}
        assert badge not in {row["badge"] for row in ok(api.get("/api/employees/directory"))}
        assert signed_in.get("/api/me").status_code == 401
        assert signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}).status_code == 401
        edit_employee(api, badge, active=True)
        assert signed_in.get("/api/me").status_code == 401
        ok(signed_in.post("/api/login", json={"badge": badge, "pin": TEST_PIN}))
        assert ok(signed_in.get("/api/me"))["badge"] == badge
    events = ok(api.get("/api/audit"))
    assert len([row for row in events if row["event"] == "EMPLOYEE_REMOVED"]) == 1
    assert len([row for row in events if row["event"] == "EMPLOYEE_RESTORED"]) == 1


def test_removed_account_cannot_be_reactivated_edited_reset_or_replaced_without_restore(api):
    badge = BADGES["welder"]
    removed = remove(api, badge)
    patch = {"expected_version": removed["version"], "reason": REASON,
             "name": removed["name"], "role": removed["role"], "active": True}
    unchanged_rejection(api, lambda: api.patch(f"{ROOT}/{badge}", patch), 409)
    unchanged_rejection(api, lambda: api.patch(f"{ROOT}/{badge}", {
        **patch, "name": "Attempted renamed removed employee", "active": False}), 409)
    unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/pin", {
        "expected_version": removed["version"], "reason": REASON, "pin": "new-synthetic-pin-only-123"}), 409)
    unchanged_rejection(api, lambda: api.post("/api/employees", {
        "badge": badge, "name": "Attempted replacement person", "role": "handler", "pin": TEST_PIN}), 409)
    assert employee(api, badge)["removed"] is True


@pytest.mark.parametrize("changes", [
    {"reason": " "}, {"reason": "bad\x00reason"}, {"reason": "x" * 3001},
    {"expected_version": True}, {"expected_version": "0"}, {"expected_version": -1},
    {"actor": BADGES["inspector"]}, {"active": True}, {"removed_at": "2020-01-01"},
])
def test_remove_and_restore_validate_reason_version_and_server_owned_fields(api, changes):
    badge = BADGES["welder"]
    body = decision(api, badge, **changes)
    for action in ("remove", "restore"):
        unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/{action}", body), 422)


def test_stale_repeated_missing_and_wrong_state_decisions_have_no_side_effects(api):
    badge = BADGES["welder"]
    before_edit = decision(api, badge)
    edit_employee(api, badge, name="Renamed synthetic welder before removal")
    unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/remove", before_edit), 409)
    unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/restore", decision(api, badge)), 409)
    before_remove = decision(api, badge)
    removed = remove(api, badge)
    unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/remove", before_remove), 409)
    unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/remove", {
        "expected_version": removed["version"], "reason": REASON}), 409)
    unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/restore", before_remove), 409)
    restored = restore(api, badge)
    unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/restore", {
        "expected_version": restored["version"], "reason": REASON}), 409)
    for action in ("remove", "restore"):
        unchanged_rejection(api, lambda: api.post(f"{ROOT}/NO-SUCH-BADGE/{action}", {
            "expected_version": 0, "reason": REASON}), 404)


def test_last_active_admin_cannot_be_removed_or_count_restored_inactive_as_replacement(api):
    badge = BADGES["admin"]
    assert employee(api, badge)["can_remove"] is False
    unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/remove", decision(api, badge)), 409)
    edit_employee(api, BADGES["supervisor"], role="admin")
    assert employee(api, badge)["can_remove"] is True
    remove(api, BADGES["supervisor"])
    restore(api, BADGES["supervisor"])
    assert roster(api)["active_admins"] == 1
    assert employee(api, badge)["can_remove"] is False
    unchanged_rejection(api, lambda: api.post(f"{ROOT}/{badge}/remove", decision(api, badge)), 409)


def test_admin_may_remove_self_when_another_active_admin_remains(api):
    edit_employee(api, BADGES["supervisor"], role="admin")
    body = decision(api, BADGES["admin"])
    with TestClient(api.application.app) as signed_in:
        ok(signed_in.post("/api/login", json={"badge": BADGES["admin"], "pin": TEST_PIN}))
        result = ok(signed_in.post(f"{ROOT}/{BADGES['admin']}/remove", json=body))
        assert result["reauthenticate"] is True
        assert result["removed"] is True and result["active"] is False
        assert signed_in.get(ROOT).status_code == 401
        ok(signed_in.post("/api/login", json={"badge": BADGES["supervisor"], "pin": TEST_PIN}))
        staff = ok(signed_in.get(ROOT, params={"include_removed": True}))
        assert staff["active_admins"] == 1 and staff["removed_count"] == 1
        assert len(staff["employees"]) == len(BADGES)


def test_inactive_employee_can_be_removed_and_removal_cycles_keep_audit_and_versions(api):
    badge = BADGES["welder"]
    edit_employee(api, badge, active=False)
    first = remove(api, badge)
    restore(api, badge)
    second = remove(api, badge, reason="Second synthetic removal with a new reviewed reason")
    assert second["version"] == first["version"] + 2
    assert second["active"] is False and second["removed"] is True
    assert second["removal_reason"] != first["removal_reason"]
    events = [row for row in ok(api.get("/api/audit")) if row["event"] == "EMPLOYEE_REMOVED"]
    assert len(events) == 2
    assert {row["details"]["reason"] for row in events} == {first["removal_reason"], second["removal_reason"]}


def test_removal_preserves_weld_inspection_custody_and_assignment_until_explicit_correction(api):
    badge = BADGES["welder"]
    item_id = api.item(item_id="REMOVAL-TRACEABILITY")["id"]
    ok(api.post(f"/api/items/{item_id}/weld", {
        "count": 1, "weld_ids": "SYNTHETIC-W01", "notes": "Actual local fixture weld event",
    }, role="welder"))
    inspect_both(api, item_id)
    transfer(api, item_id, role="handler", handler=badge, location_id="qa_qc")
    ok(api.post(f"/api/items/{item_id}/rework", {
        "kind": "Dimensional correction", "reason": "Synthetic open rework stays with its recorded assignee",
        "assigned": badge,
    }, role="inspector"), 201)
    original_custody = custody(api, item_id)
    original_item = ok(api.get(f"/api/items/{item_id}"))
    original_audit = ok(api.get(f"/api/items/{item_id}/audit"))
    removed = remove(api, badge)
    assert removed["assigned_item_count"] == 1
    remove(api, BADGES["inspector"])
    current = ok(api.get(f"/api/items/{item_id}"))
    for key in ("handler", "location", "welds_done", "last_work_at", "dimensional", "dimension_at",
                "weld", "weld_at", "reinspection_due", "inspections", "reworks"):
        assert current[key] == original_item[key], key
    assert current["handler"] == badge and current["transfer"]["handler_active"] is False
    assert custody(api, item_id) == original_custody
    assert ok(api.get(f"/api/items/{item_id}/audit")) == original_audit
    assert any(row["actor"] == badge and row["event"] == "WELDS_COMPLETED" for row in original_audit)
    assert all(row["inspector"] == BADGES["inspector"] for row in current["inspections"])
    assert current["reworks"][0]["assigned"] == badge and current["reworks"][0]["closed_at"] is None
    unchanged_rejection(api, lambda: api.post(f"/api/items/{item_id}/transfer", transfer_body(
        api, item_id, handler=BADGES["handler"])), 404)
    ok(api.post(f"/api/admin/items/{item_id}/custody", disposition_body(api, item_id,
        handler=BADGES["handler"], location_id="current", operational_status="queued")))
    corrected = admin_item(api, item_id)
    assert corrected["item"]["handler"] == BADGES["handler"]
    assert employee(api, badge)["assigned_item_count"] == 0
    assert current["inspections"] == corrected["item"]["inspections"]
    assert custody(api, item_id)[0] == original_custody[0]


def test_removed_employee_cannot_receive_new_items_bulk_rows_rework_or_badge_handoffs(api):
    badge = BADGES["welder"]
    item_id = api.item(item_id="REMOVAL-EXISTING-ASSIGNMENT")["id"]
    transfer(api, item_id, role="handler", handler=BADGES["handler"], location_id="material_storage")
    remove(api, badge)
    item = {"id": "REMOVAL-NEW-ASSIGNMENT", "description": "Synthetic forbidden new assignment",
            "kind": "Part", "project": "Test job", "location": "Test rack", "handler": badge}
    unchanged_rejection(api, lambda: api.post("/api/items", item), 422)
    unchanged_rejection(api, lambda: api.post("/api/items/bulk", {"rows": [
        {**item, "google_part_number": "SYNTHETIC-PN", "quantity": 1}]}), 422)
    unchanged_rejection(api, lambda: api.post(f"/api/items/{item_id}/rework", {
        "kind": "Correction", "reason": "New synthetic assignment cannot use a removed badge", "assigned": badge}), 422)
    unchanged_rejection(api, lambda: api.post(f"/api/items/{item_id}/transfer", transfer_body(
        api, item_id, handler=badge)), 404)


def test_employee_removal_leaves_issued_packet_fingerprint_and_downloads_unchanged(api):
    issued = issued_fixture(api)
    item_id = "DOSSIER-ISSUED"
    original = packet(api, item_id)
    fingerprints = {code: row["fingerprint"] for code, row in checks(original).items()}
    frozen = ok(api.get(f"/api/dossier/issues/{issued['id']}"))
    printed = api.get(f"/api/dossier/issues/{issued['id']}/print")
    download = api.get(f"/api/dossier/issues/{issued['id']}/download")
    assert printed.status_code == 200 and download.status_code == 200
    # This employee is the retained custodian of the issued synthetic item.
    assert original["item"]["handler"] == BADGES["handler"]
    remove(api, BADGES["handler"])
    current = packet(api, item_id)
    assert current["latest_issue"]["current"] is True
    assert current["latest_issue"]["sha256"] == issued["sha256"]
    assert {code: row["fingerprint"] for code, row in checks(current).items()} == fingerprints
    assert ok(api.get(f"/api/dossier/issues/{issued['id']}")) == frozen
    assert api.get(f"/api/dossier/issues/{issued['id']}/print").content == printed.content
    assert api.get(f"/api/dossier/issues/{issued['id']}/download").content == download.content
