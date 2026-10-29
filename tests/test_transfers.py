"""Two identified badges, controlled destinations and passive operational status.

All identities, locations and records are synthetic isolated fixtures. Scanning
a badge does not authenticate that person or create their acknowledgement.
Custody metadata never substitutes for numbered work, timing or QA decisions.
"""

import pytest

from conftest import BADGES
from tracking_helpers import ok
from test_flow import action_body, advance, create_item, detail as flow_detail, enroll, inspect_dimensions
from test_progress import database_state
from test_dossier import physical_release


ROOT = "/api/transfers"
STATUSES = {"queued", "in_progress", "awaiting_inspection", "waiting_material", "paused", "ready_next_operation"}
BUILTIN_LOCATIONS = {"receiving", "material_storage", "kitting", "fabrication_prep", "production_staging",
                     "fit_up", "welding", "qa_qc", "assembly", "blast_paint", "shipping"}


def options(api, role="admin"):
    return ok(api.get(ROOT + "/options", role=role))


def transfer_state(api, item_id, role="admin"):
    return ok(api.get(f"{ROOT}/items/{item_id}", role=role))


def item(api, item_id="TRANSFER-SPOOL", kind="Spool"):
    return create_item(api, item_id, kind=kind)


def transfer_body(api, item_id, **changes):
    current = transfer_state(api, item_id)
    return {"sender_badge": current["handler"], "handler": current["handler"],
            "location_id": "production_staging", "operational_status": "queued",
            "expected_transfer_version": current["version"],
            "notes": "Synthetic actual transfer recorded by the signed-in operator",
            "scan_method": "employee_qr", **changes}


def transfer(api, item_id, *, role="handler", **changes):
    return ok(api.post(f"/api/items/{item_id}/transfer", transfer_body(api, item_id, **changes), role=role))


def rejected(api, response, before, statuses=(409, 422)):
    assert response.status_code in statuses, response.text
    assert database_state(api) == before


def custody(api, item_id):
    return sorted(ok(api.get(f"/api/items/{item_id}/custody")), key=lambda row: row["id"])


def location_label(api, location_id):
    return next(row["label"] for row in options(api)["locations"] if row["id"] == location_id)


def test_options_and_current_state_require_authentication_and_never_seed_records(api):
    item_id = item(api)
    before = database_state(api)
    for path in (ROOT + "/options", f"{ROOT}/items/{item_id}"):
        assert api.get(path, role=None).status_code == 401
    for role in BADGES:
        catalog = options(api, role)
        assert {row["id"] for row in catalog["statuses"]} == STATUSES
        assert {row["id"] for row in catalog["locations"] if row["kind"] == "builtin"} == BUILTIN_LOCATIONS
        assert catalog["keep_current_location_id"] == "current"
        assert catalog["can_manage_locations"] is (role in ("admin", "supervisor"))
        current = transfer_state(api, item_id, role)
        assert current["version"] == 0 and current["operational_status"] is None
        assert current["handler"] == BADGES["handler"] and current["handler_active"] is True
        assert current["location"] == "Receiving"
    assert api.get(ROOT + "/items/NO-SUCH-ITEM").status_code == 404
    assert ok(api.get(f"/api/items/{item_id}"))["transfer"]["version"] == 0
    assert flow_detail(api, item_id)["transfer"]["version"] == 0
    assert database_state(api) == before


def test_signed_in_recorder_can_identify_two_other_people_without_claiming_their_signatures(api):
    item_id = item(api)
    first = transfer_state(api, item_id)
    result = transfer(api, item_id, role="admin", handler=BADGES["welder"], location_id="welding",
                      operational_status="in_progress")
    current = result["transfer"]
    assert current["version"] == first["version"] + 1
    assert current["handler"] == BADGES["welder"]
    assert current["location"] == location_label(api, "welding")
    assert current["operational_status"] == "in_progress" and current["updated_by"] == BADGES["admin"]
    history = custody(api, item_id)
    assert len(history) == 1 and history[0]["actor"] == BADGES["admin"]
    record = history[0]["details"]
    assert record["sender"] == {"badge": BADGES["handler"], "name": "Test handler"}
    assert record["receiver"] == {"badge": BADGES["welder"], "name": "Test welder"}
    assert record["sender_badge"] == BADGES["handler"] and record["receiver_badge"] == BADGES["welder"]
    assert record["from"]["handler"] == first["handler"] and record["from"]["location"] == first["location"]
    assert record["to"]["handler"] == BADGES["welder"] and record["to"]["operational_status"] == "in_progress"
    assert record["handoff_recorded_by"] == BADGES["admin"]
    assert record["sender_acknowledged"] is False and record["recipient_acknowledged"] is False
    assert record["custody_changed"] is True
    assert record["previous_transfer_version"] == first["version"]
    assert record["transfer_version"] == current["version"]


@pytest.mark.parametrize("missing", ["sender_badge", "handler", "location_id", "operational_status", "expected_transfer_version"])
def test_both_badges_destination_status_and_current_version_are_required(api, missing):
    item_id = item(api)
    body = transfer_body(api, item_id)
    del body[missing]
    before = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", body), before, (422,))


def test_wrong_sender_cannot_override_the_locked_current_custodian(api):
    item_id = item(api)
    body = transfer_body(api, item_id, sender_badge=BADGES["supervisor"], handler=BADGES["welder"])
    before = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", body, role="admin"), before, (409,))
    transfer(api, item_id, role="admin", handler=BADGES["welder"])
    body = transfer_body(api, item_id, sender_badge=BADGES["handler"], handler=BADGES["supervisor"])
    before = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", body, role="admin"), before, (409,))


@pytest.mark.parametrize("field", ["sender_badge", "handler"])
def test_unknown_or_inactive_badges_never_create_a_transfer(api, field):
    item_id = item(api)
    body = transfer_body(api, item_id, **{field: "NO-SUCH-BADGE"})
    before = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", body), before, (404,))
    inactive = BADGES["handler"] if field == "sender_badge" else BADGES["welder"]
    with api.session_factory() as session:
        session.get(api.application.Employee, inactive).active = False
        session.commit()
    body = transfer_body(api, item_id, **{field: inactive})
    before = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", body, role="admin"), before, (404,))


@pytest.mark.parametrize("role", [None])
def test_generic_transfer_requires_an_authenticated_recorder(api, role):
    item_id = item(api)
    body = transfer_body(api, item_id)
    before = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", body, role=role), before,
             (401,) if role is None else (403,))


@pytest.mark.parametrize("role", list(BADGES))
def test_every_authorized_recorder_can_save_a_real_metadata_change(api, role):
    item_id = item(api)
    result = transfer(api, item_id, role=role, operational_status="waiting_material")
    assert result["transfer"]["operational_status"] == "waiting_material"
    assert custody(api, item_id)[0]["actor"] == BADGES[role]


def test_same_custodian_location_and_status_updates_are_allowed_but_a_noop_is_not(api):
    item_id = item(api)
    first = transfer(api, item_id, location_id="current", operational_status="queued")
    assert first["handler"] == BADGES["handler"] and first["location"] == "Receiving"
    event = custody(api, item_id)[0]["details"]
    assert event["custody_changed"] is False and event["location_changed"] is False and event["status_changed"] is True
    body = transfer_body(api, item_id, location_id="current", operational_status="queued")
    before = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", body), before, (409,))
    second = transfer(api, item_id, location_id="material_storage", operational_status="queued")
    assert second["transfer"]["version"] == first["transfer"]["version"] + 1
    event = custody(api, item_id)[-1]["details"]
    assert event["custody_changed"] is False and event["location_changed"] is True


def test_same_handler_concurrent_location_or_status_changes_reject_a_stale_form(api):
    item_id = item(api)
    stale = transfer_body(api, item_id, handler=BADGES["welder"], location_id="welding", operational_status="in_progress")
    transfer(api, item_id, location_id="material_storage", operational_status="waiting_material")
    before = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", stale), before, (409,))
    assert transfer_state(api, item_id)["handler"] == BADGES["handler"]


def test_status_cannot_set_quality_shipping_or_other_server_owned_fields(api):
    item_id = item(api)
    for bad_status in ("approved", "finished", "released", "shipped", "delivered", "on_hold", "", None):
        body = transfer_body(api, item_id, operational_status=bad_status)
        before = database_state(api)
        rejected(api, api.post(f"/api/items/{item_id}/transfer", body), before, (422,))
    for fields in ({"released": True}, {"actor": BADGES["inspector"]}, {"recipient_acknowledged": True},
                   {"sender_acknowledged": True}, {"expected_transfer_version": True},
                   {"location_id": "invented-place"}, {"location": "Uncontrolled injected destination"}):
        body = transfer_body(api, item_id, **fields)
        before = database_state(api)
        rejected(api, api.post(f"/api/items/{item_id}/transfer", body), before, (422,))


def test_passive_status_does_not_pause_manual_timer_or_change_quality(api):
    item_id = item(api)
    process = ok(api.post(f"/api/tracking/spools/{item_id}/process", {
        "action": "start", "process_key": "fit_up", "expected_version": 0,
        "notes": "Synthetic process already running before custody metadata changes",
    }), 201)
    before = ok(api.get(f"/api/items/{item_id}"))
    result = transfer(api, item_id, operational_status="paused", location_id="qa_qc")
    after_process = ok(api.get(f"/api/tracking/spools/{item_id}/process"))
    assert result["transfer"]["operational_status"] == "paused"
    assert after_process["status"] == "running"
    assert after_process["version"] == process["version"] and after_process["events"] == process["events"]
    assert after_process["current"]["process_key"] == "fit_up"
    for key in ("released", "released_at", "released_by", "on_hold", "dimensional", "weld",
                "welds_done", "last_work_at", "reinspection_due"):
        assert result[key] == before[key]


def test_scan_only_keeps_custody_status_and_numbered_timing_unchanged(api):
    item_id = item(api, kind="Part")
    enroll(api, item_id, "component")
    before = flow_detail(api, item_id)
    ok(api.post(f"/api/items/{item_id}/scan"))
    after = flow_detail(api, item_id)
    assert after["transfer"] == before["transfer"]
    assert after["flow"] == before["flow"]
    assert after["events"] == before["events"]
    assert after["production_process"]["events"] == before["production_process"]["events"]
    assert custody(api, item_id) == []


def test_generic_custody_invalidates_an_open_flow_form_without_advancing_or_retiming(api):
    item_id = item(api, kind="Part")
    enroll(api, item_id, "component", start_step=6)
    before = flow_detail(api, item_id)
    stale = action_body(api, item_id)
    transfer(api, item_id, handler=BADGES["welder"], operational_status="waiting_material")
    after = flow_detail(api, item_id)
    assert after["flow"]["current_step"] == before["flow"]["current_step"]
    assert after["flow"]["version"] > before["flow"]["version"]
    assert after["flow"]["steps"] == before["flow"]["steps"]
    assert after["production_process"]["events"] == before["production_process"]["events"]
    snapshot = database_state(api)
    rejected(api, api.post(f"/api/flow/items/{item_id}/advance", stale), snapshot, (409,))


def test_numbered_handoff_requires_sender_and_saves_custody_step_and_timer_together(api):
    item_id = item(api, kind="Part")
    enroll(api, item_id, "component", start_step=6)
    body = action_body(api, item_id, receiver_badge=BADGES["welder"], location_id="fabrication_prep", operational_status="in_progress")
    for field in ("sender_badge", "receiver_badge", "location_id", "operational_status", "expected_transfer_version"):
        invalid = {key: value for key, value in body.items() if key != field}
        snapshot = database_state(api)
        rejected(api, api.post(f"/api/flow/items/{item_id}/advance", invalid), snapshot, (422,))
    before = flow_detail(api, item_id)
    after = ok(api.post(f"/api/flow/items/{item_id}/advance", body))
    assert after["flow"]["current_step"] == 7 and after["flow"]["version"] == before["flow"]["version"] + 1
    assert after["transfer"]["version"] == before["transfer"]["version"] + 1
    assert after["item"]["handler"] == BADGES["welder"]
    assert after["transfer"]["operational_status"] == "in_progress"
    assert len(after["production_process"]["events"]) == len(before["production_process"]["events"]) + 1
    record = custody(api, item_id)[0]["details"]
    assert record["sender_badge"] == BADGES["handler"] and record["receiver_badge"] == BADGES["welder"]
    assert record["handoff_recorded_by"] == BADGES["admin"] and record["flow_step"] == 6
    assert record["sender_acknowledged"] is False and record["recipient_acknowledged"] is False


def test_quality_or_scope_blocker_rolls_back_all_valid_handoff_inputs(api):
    item_id = item(api)
    enroll(api, item_id, "spool", expected_children=1)
    body = action_body(api, item_id, receiver_badge=BADGES["welder"], operational_status="in_progress")
    before = database_state(api)
    rejected(api, api.post(f"/api/flow/items/{item_id}/advance", body), before, (409,))
    assert transfer_state(api, item_id)["version"] == 0
    assert flow_detail(api, item_id)["flow"]["current_step"] == 9


def test_location_only_step3_invalidates_stale_transfer_without_inventing_status(api):
    item_id = item(api, kind="Part")
    enroll(api, item_id, "component", start_step=3)
    stale = transfer_body(api, item_id, handler=BADGES["welder"])
    before = transfer_state(api, item_id)
    after = advance(api, item_id, location_id="material_storage")
    assert after["flow"]["current_step"] == 4
    assert after["transfer"]["version"] == before["version"] + 1
    assert after["transfer"]["handler"] == before["handler"]
    assert after["transfer"]["operational_status"] is None
    assert after["item"]["location"] == location_label(api, "material_storage")
    snapshot = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", stale), snapshot, (409,))


def test_unrelated_numbered_step_cannot_accept_hidden_handoff_fields(api):
    item_id = item(api, kind="Part")
    enroll(api, item_id, "component", start_step=2)
    body = action_body(api, item_id, sender_badge=BADGES["handler"], receiver_badge=BADGES["welder"],
                       location_id="qa_qc", operational_status="awaiting_inspection", expected_transfer_version=0)
    before = database_state(api)
    rejected(api, api.post(f"/api/flow/items/{item_id}/advance", body), before, (422,))


def test_released_items_keep_generic_lock_but_allow_authorized_post_qa_handoff(api):
    plain = item(api, "TRANSFER-RELEASED-PLAIN")
    physical_release(api, plain)
    body = transfer_body(api, plain)
    snapshot = database_state(api)
    rejected(api, api.post(f"/api/items/{plain}/transfer", body), snapshot, (409,))
    numbered = item(api, "TRANSFER-RELEASED-FLOW")
    enroll(api, numbered, "spool", start_step=15)
    inspect_dimensions(api, numbered)
    before = advance(api, numbered, role="inspector")
    assert before["item"]["released"] is True and before["flow"]["current_step"] == 16
    after = advance(api, numbered, operational_status="ready_next_operation")
    assert after["item"]["released"] is True and after["flow"]["status"] == "completed"
    assert after["item"]["released_at"] == before["item"]["released_at"]
    assert after["transfer"]["operational_status"] == "ready_next_operation"
    assert custody(api, numbered)[-1]["details"]["custody_changed"] is False


def test_location_catalog_changes_are_controlled_versioned_and_do_not_relocate_items(api):
    item_id = item(api)
    create = {"label": "Synthetic Controlled Bay"}
    before = database_state(api)
    for role in (None, "handler", "welder", "inspector"):
        rejected(api, api.post(ROOT + "/locations", create, role=role), before,
                 (401,) if role is None else (403,))
    location = ok(api.post(ROOT + "/locations", create, role="supervisor"), 201)
    assert location["version"] == 1 and location["active"] is True and location["kind"] == "custom"
    assert location["created_by"] == BADGES["supervisor"]
    moved = transfer(api, item_id, location_id=location["id"])
    current = transfer_state(api, item_id)
    renamed = ok(api.patch(ROOT + "/locations/" + location["id"], {
        "label": "Synthetic Renamed Bay", "active": True, "expected_version": location["version"],
    }, role="admin"))
    assert renamed["version"] == 2
    assert transfer_state(api, item_id) == current
    assert moved["location"] == create["label"]
    stale = {"label": "Stale rename", "active": True, "expected_version": 1}
    before = database_state(api)
    rejected(api, api.patch(ROOT + "/locations/" + location["id"], stale), before, (409,))
    deactivated = ok(api.patch(ROOT + "/locations/" + location["id"], {
        "label": renamed["label"], "active": False, "expected_version": renamed["version"],
    }, role="supervisor"))
    assert deactivated["active"] is False
    body = transfer_body(api, item_id, location_id=location["id"], operational_status="in_progress")
    before = database_state(api)
    rejected(api, api.post(f"/api/items/{item_id}/transfer", body), before, (422,))


def test_location_labels_are_canonicalized_for_duplicates_and_builtin_controls(api):
    created = ok(api.post(ROOT + "/locations", {"label": "BAY-7"}), 201)
    for label in (" bay-7 ", "ＢＡＹ-７", location_label(api, "welding")):
        before = database_state(api)
        rejected(api, api.post(ROOT + "/locations", {"label": label}), before, (409,))
    # U+FDFA expands to eighteen characters under NFKC. Its original length is
    # valid, but the normalized unique key must still fit its PostgreSQL column.
    for body in ({"label": ""}, {"label": "New label", "actor": BADGES["handler"]}, {"label": "\ufdfa" * 160}):
        before = database_state(api)
        rejected(api, api.post(ROOT + "/locations", body), before, (422,))
    before = database_state(api)
    rejected(api, api.patch(ROOT + "/locations/" + created["id"], {
        "label": "New label", "active": True, "expected_version": True,
    }), before, (422,))


def test_existing_legacy_locations_and_transfer_history_are_not_backfilled_as_new_scans(api):
    item_id = item(api)
    with api.session_factory() as session:
        physical = session.get(api.application.Item, item_id)
        physical.location = "Actual legacy rack 42"
        api.application.audit(session, item_id, BADGES["admin"], "TRANSFER", {
            "from": {"handler": BADGES["supervisor"], "location": "Legacy receiving"},
            "to": {"handler": BADGES["handler"], "location": physical.location, "name": "Test handler"},
            "notes": "Historic fixture predates sender-badge capture", "scan_method": "manual",
            "handoff_recorded_by": BADGES["admin"], "recipient_acknowledged": False,
        })
        session.commit()
    historical = custody(api, item_id)[0]
    before = database_state(api)
    current = transfer_state(api, item_id)
    assert current["version"] == 0 and current["operational_status"] is None
    assert current["location"] == "Actual legacy rack 42"
    assert "sender_badge" not in custody(api, item_id)[0]["details"]
    assert database_state(api) == before
    moved = transfer(api, item_id, location_id="current", operational_status="queued")
    assert moved["location"] == "Actual legacy rack 42"
    assert custody(api, item_id)[0] == historical
