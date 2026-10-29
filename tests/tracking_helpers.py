"""Behavioral setup helpers using the same public API as the shop interface."""

import json


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def make_spool(api, item_id="TEST-SPOOL-01", planned=1, **plan_values):
    api.item(item_id=item_id, welds_required=planned)
    project = "TEST-PROJECT"
    response = api.post(
        "/api/tracking/projects", {"id": project, "name": "Local test project"}
    )
    assert response.status_code in (200, 201, 409), response.text
    response = api.post(
        f"/api/tracking/spools/{item_id}/plan",
        {"project_id": project, "planned_welds": planned, **plan_values},
    )
    assert response.status_code in (200, 201), response.text
    return item_id


def add_weld(api, item_id, number="W01", **values):
    body = {
        "number": number,
        "component_a": "TEST-PIECE-A",
        "heat_a": "TEST-HEAT-A",
        "mtr_a": "TEST-MTR-A",
        "component_b": "TEST-PIECE-B",
        "heat_b": "TEST-HEAT-B",
        "mtr_b": "TEST-MTR-B",
        "wps": "TEST-WPS-01",
        "wps_revision": "A",
        **values,
    }
    response = api.post(f"/api/tracking/spools/{item_id}/welds", body)
    assert response.status_code in (200, 201), response.text
    return response.json()


def spool(api, item_id):
    return ok(api.get(f"/api/tracking/spools/{item_id}"))


def weld(api, item_id, weld_id):
    return next(row for row in spool(api, item_id)["welds"] if row["id"] == weld_id)


def requirement(api, item_id, req_id):
    detail = spool(api, item_id)
    rows = list(detail.get("requirements", []))
    for entry in detail["welds"]:
        rows.extend(entry["requirements"])
    return next(row for row in rows if row["id"] == req_id)


def find_requirement(api, item_id, weld_id, *, code=None, check=None):
    rows = weld(api, item_id, weld_id)["requirements"]
    return next(
        row
        for row in rows
        if (code is None or row["code"].lower() == code.lower())
        and (check is None or row.get("check") == check)
    )


def submit(api, item_id, req_id, reference="LOCAL-EVIDENCE", result="pass", role="inspector"):
    current = requirement(api, item_id, req_id)
    response = api.post(
        f"/api/tracking/requirements/{req_id}/evidence",
        {
            "expected_version": current["version"],
            "reference": reference,
            "notes": "Isolated test observation and test qualification review",
            "result": result,
        },
        role=role,
    )
    assert response.status_code in (200, 201), response.text
    return requirement(api, item_id, req_id)


def review(api, item_id, req_id, decision="accepted", role="inspector", **values):
    current = requirement(api, item_id, req_id)
    return api.post(
        f"/api/tracking/requirements/{req_id}/review",
        {
            "expected_version": current["version"],
            "decision": decision,
            "notes": "Approved test plan basis and test evidence reviewed",
            **values,
        },
        role=role,
    )


def approve(api, item_id, req_id, reference="LOCAL-EVIDENCE"):
    submit(api, item_id, req_id, reference=reference)
    response = review(api, item_id, req_id)
    assert response.status_code == 200, response.text
    return requirement(api, item_id, req_id)


def ready_to_weld(api, item_id, weld_id):
    response = api.post(
        f"/api/tracking/welds/{weld_id}/work",
        {"operation": "fitup", "notes": "Test fit-up"},
        role="welder",
    )
    assert response.status_code in (200, 201), response.text
    for row in weld(api, item_id, weld_id)["requirements"]:
        if row["stage"] == "before_welding" and row["status"] != "accepted":
            approve(api, item_id, row["id"])


def complete_weld(api, item_id, weld_id, operations=("root", "fill_cap")):
    ready_to_weld(api, item_id, weld_id)
    for operation in (*operations, "complete"):
        response = api.post(
            f"/api/tracking/welds/{weld_id}/work",
            {"operation": operation, "notes": "Local test work"},
            role="welder",
        )
        assert response.status_code in (200, 201), response.text
    return weld(api, item_id, weld_id)


def accept_weld(api, item_id, weld_id, skip_codes=()):
    skipped = {code.lower() for code in skip_codes}
    for row in weld(api, item_id, weld_id)["requirements"]:
        if row["code"].lower() in skipped or row["status"] == "accepted":
            continue
        approve(api, item_id, row["id"], reference="REPORT-" + row["code"])
    return weld(api, item_id, weld_id)


def serialized_history(api, item_id):
    return json.dumps(spool(api, item_id), sort_keys=True)
