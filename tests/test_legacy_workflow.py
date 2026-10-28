"""Preserve existing fabrication flows while enforcing the new tracking gates."""

from conftest import BADGES, TEST_PIN


def inspect_both(api, item_id):
    for kind in ("Dimensional", "Weld"):
        response = api.post(
            f"/api/items/{item_id}/inspect",
            {
                "kind": kind,
                "result": "Pass",
                "report": "LOCAL-TEST-REPORT",
                "measurements": "Test measurements meet the test traveler",
            },
            role="inspector",
        )
        assert response.status_code == 200, response.text


def test_staff_records_require_a_valid_session(api):
    assert api.get("/api/items", role=None).status_code == 401
    assert api.get("/api/items", role="NONEXISTENT").status_code == 401
    assert api.get("/healthz", role=None).status_code == 200


def test_badge_login_still_works(api):
    response = api.post(
        "/api/login", {"badge": BADGES["welder"], "pin": TEST_PIN}, role=None
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "welder"
    assert "fabtrace_session" in response.cookies
    assert "httponly" in response.headers["set-cookie"].lower()


def test_untracked_items_keep_existing_completion_and_release_flow(api):
    item_id = api.item()["id"]
    response = api.post(
        f"/api/items/{item_id}/weld",
        {"count": 1, "weld_ids": "W01", "notes": "Local test"},
        role="welder",
    )
    assert response.status_code == 200, response.text
    assert response.json()["welds_done"] == 1
    inspect_both(api, item_id)
    response = api.post(
        f"/api/items/{item_id}/release",
        {"reference": "LOCAL-RELEASE"},
        role="inspector",
    )
    assert response.status_code == 200, response.text
    assert response.json()["released"] is True


def test_welder_cannot_inspect_or_release(api):
    item_id = api.item()["id"]
    response = api.post(
        f"/api/items/{item_id}/inspect",
        {
            "kind": "Weld",
            "result": "Pass",
            "report": "TEST-REPORT",
            "measurements": "Test observation",
        },
        role="welder",
    )
    assert response.status_code == 403
    assert api.post(
        f"/api/items/{item_id}/release", {"reference": "TEST"}, role="welder"
    ).status_code == 403


def test_rework_close_does_not_restore_old_inspections(api):
    item_id = api.item(welds_required=0)["id"]
    inspect_both(api, item_id)
    response = api.post(
        f"/api/items/{item_id}/rework",
        {
            "kind": "Correction",
            "reason": "Test dimensional correction",
            "assigned": BADGES["welder"],
        },
        role="inspector",
    )
    assert response.status_code == 201, response.text
    rework_id = response.json()["reworks"][0]["id"]
    response = api.post(
        f"/api/items/{item_id}/rework/{rework_id}/close",
        {"notes": "Test correction completed"},
        role="welder",
    )
    assert response.status_code == 200, response.text
    response = api.post(
        f"/api/items/{item_id}/release", {"reference": "TEST"}, role="inspector"
    )
    assert response.status_code == 409
    inspect_both(api, item_id)
    assert api.post(
        f"/api/items/{item_id}/release", {"reference": "TEST"}, role="inspector"
    ).status_code == 200


def test_inactive_employee_session_is_rejected(api):
    with api.session_factory() as session:
        employee = session.get(api.application.Employee, BADGES["welder"])
        employee.active = False
        session.commit()
    assert api.get("/api/items", role="welder").status_code == 401
