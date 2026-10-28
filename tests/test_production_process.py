"""Elapsed spool process timing, independent of weld work and QA acceptance."""

import datetime as dt
import importlib

import pytest
from sqlalchemy import select

from conftest import BADGES
from tracking_helpers import add_weld, make_spool, ok, spool


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += dt.timedelta(seconds=seconds)
        return self.value


@pytest.fixture
def clock(application, monkeypatch):
    production = importlib.import_module("production")
    # Tomorrow keeps signed test cookies valid when main.utcnow is also
    # patched for the exact release timestamp assertion.
    timer = Clock(application.utcnow().replace(microsecond=0) + dt.timedelta(days=1))
    monkeypatch.setattr(production, "utcnow", timer)
    return timer


def process(api, item_id):
    return ok(api.get(f"/api/tracking/spools/{item_id}/process"))


def change(api, item_id, action, version, role="welder", **values):
    response = api.post(
        f"/api/tracking/spools/{item_id}/process",
        {"action": action, "expected_version": version, **values},
        role=role,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def durations(row, elapsed, active, paused):
    assert row["elapsed_seconds"] == pytest.approx(elapsed)
    assert row["active_seconds"] == pytest.approx(active)
    assert row["paused_seconds"] == pytest.approx(paused)
    assert row["elapsed_seconds"] == pytest.approx(row["active_seconds"] + row["paused_seconds"])


def test_process_tracking_requires_authentication_and_explicit_enrollment(api, clock):
    item_id = api.item()["id"]
    route = f"/api/tracking/spools/{item_id}/process"
    assert api.get("/api/tracking/processes", role=None).status_code == 401
    assert api.get(route, role=None).status_code == 401
    assert api.post(route, {"action": "start", "expected_version": 0, "process_key": "welding"}, role=None).status_code == 401
    assert api.get(route).status_code == 409
    assert api.post(route, {"action": "start", "expected_version": 0, "process_key": "welding"}).status_code == 409
    assert api.get("/api/tracking/spools/MISSING/process").status_code == 404
    production = importlib.import_module("production")
    with api.session_factory() as session:
        assert session.scalars(select(production.SpoolProcessEvent)).all() == []


def test_no_timing_is_inferred_until_first_start_and_catalog_is_stable(api, clock):
    item_id = make_spool(api)
    clock.advance(7 * 86400)
    current = process(api, item_id)
    assert current["status"] == "not_started"
    assert current["version"] == 0
    assert current["current"] is None
    assert current["events"] == current["visits"] == current["by_process"] == []
    durations(current["totals"], 0, 0, 0)
    assert current["totals"]["visits"] == 0
    catalog = ok(api.get("/api/tracking/processes"))
    assert {row["key"] for row in catalog} == {
        "material_prep", "cutting_beveling", "fit_up", "welding", "nde",
        "pwht", "dimensional", "coating", "final_qa", "dispatch",
    }
    assert all(row["label"].strip() for row in catalog)
    assert spool(api, item_id)["production_process"] == current


@pytest.mark.parametrize("role", list(BADGES))
def test_each_shop_role_can_record_a_process_with_its_own_identity(api, clock, role):
    item_id = make_spool(api)
    current = change(api, item_id, "start", 0, role=role, process_key="fit_up", notes="At the fit-up station")
    assert current["status"] == "running"
    assert current["version"] == 1
    assert current["current"]["process_key"] == "fit_up"
    assert current["events"][0]["actor"] == BADGES[role]
    assert current["events"][0]["notes"] == "At the fit-up station"
    assert dt.datetime.fromisoformat(current["events"][0]["at"]).utcoffset() == dt.timedelta(0)
    durations(current["current"], 0, 0, 0)


def test_pauses_moves_revisits_and_idle_gaps_have_correct_process_totals(api, clock):
    item_id = make_spool(api)
    current = change(api, item_id, "start", 0, process_key="fit_up")
    clock.advance(600)
    current = change(api, item_id, "pause", current["version"], notes="Waiting for material")
    durations(current["current"], 600, 600, 0)
    clock.advance(900)
    current = process(api, item_id)
    assert current["status"] == "paused"
    durations(current["current"], 1500, 600, 900)
    clock.advance(300)
    current = change(api, item_id, "resume", current["version"])
    clock.advance(600)
    current = change(api, item_id, "move", current["version"], process_key="welding")
    durations(current["visits"][0], 2400, 1200, 1200)
    assert current["visits"][0]["ended_at"] == current["visits"][1]["started_at"]
    clock.advance(600)
    current = change(api, item_id, "pause", current["version"], notes="Awaiting consumables")
    clock.advance(300)
    current = change(api, item_id, "move", current["version"], process_key="nde", role="inspector")
    assert current["status"] == "running"
    durations(current["visits"][1], 900, 600, 300)
    clock.advance(1200)
    current = change(api, item_id, "finish", current["version"], role="inspector")
    finished = current["totals"].copy()
    assert current["status"] == "finished" and current["current"] is None
    clock.advance(3600)
    assert process(api, item_id)["totals"] == finished
    current = change(api, item_id, "start", current["version"], process_key="welding", notes="Return for a repair")
    clock.advance(300)
    current = change(api, item_id, "finish", current["version"])
    assert current["totals"]["visits"] == 4
    durations(current["totals"], 4800, 3300, 1500)
    totals = {row["process_key"]: row for row in current["by_process"]}
    durations(totals["fit_up"], 2400, 1200, 1200)
    durations(totals["welding"], 1200, 900, 300)
    durations(totals["nde"], 1200, 1200, 0)
    assert totals["welding"]["visits"] == 2
    assert [row["sequence"] for row in current["events"]] == list(range(1, current["version"] + 1))
    assert all(row["status"] == "finished" for row in current["visits"])


def test_custom_process_names_are_normalized_and_revisits_aggregate(api, clock):
    item_id = make_spool(api)
    current = change(api, item_id, "start", 0, process_key="custom", process_name="  Client   witness  ")
    assert current["current"]["process_name"] == "Client witness"
    clock.advance(60)
    current = change(api, item_id, "finish", current["version"])
    current = change(api, item_id, "start", current["version"], process_key="custom", process_name="client WITNESS")
    clock.advance(30)
    current = change(api, item_id, "finish", current["version"])
    assert len(current["by_process"]) == 1
    assert current["by_process"][0]["visits"] == 2
    durations(current["by_process"][0], 90, 90, 0)


def test_stale_and_illegal_transitions_do_not_append_events_or_audits(api, clock):
    item_id = make_spool(api)
    route = f"/api/tracking/spools/{item_id}/process"
    for action in ("move", "pause", "resume", "finish"):
        body = {"action": action, "expected_version": 0, "notes": "Transition check"}
        if action == "move":
            body["process_key"] = "welding"
        assert api.post(route, body).status_code == 409
    current = change(api, item_id, "start", 0, process_key="welding")
    with api.session_factory() as session:
        audit_count = session.query(api.application.Audit).count()
    for body in (
        {"action": "start", "expected_version": 0, "process_key": "welding"},
        {"action": "start", "expected_version": 1, "process_key": "nde"},
        {"action": "move", "expected_version": 1, "process_key": "welding"},
        {"action": "resume", "expected_version": 1},
    ):
        assert api.post(route, body).status_code == 409
    assert process(api, item_id) == current
    with api.session_factory() as session:
        assert session.query(api.application.Audit).count() == audit_count
    paused = change(api, item_id, "pause", 1, notes="Material wait")
    assert api.post(route, {"action": "pause", "expected_version": 2, "notes": "Repeat pause"}).status_code == 409
    assert process(api, item_id) == paused


@pytest.mark.parametrize("body", [
    {"action": "start", "process_key": "welding"},
    {"action": "start", "expected_version": -1, "process_key": "welding"},
    {"action": "start", "expected_version": True, "process_key": "welding"},
    {"action": "start", "expected_version": 0, "process_key": "unknown"},
    {"action": "start", "expected_version": 0, "process_key": "welding", "process_name": "Override built-in"},
    {"action": "start", "expected_version": 0, "process_key": "custom", "process_name": " "},
    {"action": "start", "expected_version": 0, "process_key": "custom", "process_name": "x" * 81},
    {"action": "start", "expected_version": 0, "process_key": "welding", "notes": "x" * 2001},
    {"action": "start", "expected_version": 0, "process_key": "welding", "actor": "SPOOFED-BADGE"},
    {"action": "start", "expected_version": 0, "process_key": "welding", "at": "2000-01-01T00:00:00Z"},
    {"action": "delete", "expected_version": 0},
    {"action": "pause", "expected_version": 0, "notes": "  "},
    {"action": "pause", "expected_version": 0, "notes": "xy"},
    {"action": "resume", "expected_version": 0, "process_key": "welding"},
])
def test_invalid_process_inputs_are_rejected_without_inventing_history(api, clock, body):
    item_id = make_spool(api)
    response = api.post(f"/api/tracking/spools/{item_id}/process", body)
    assert response.status_code == 422, response.text
    assert process(api, item_id)["events"] == []


def test_timing_changes_do_not_complete_welds_or_satisfy_qa_requirements(api, clock):
    item_id = make_spool(api)
    add_weld(api, item_id)
    before = spool(api, item_id)
    current = change(api, item_id, "start", 0, process_key="welding")
    clock.advance(1800)
    current = change(api, item_id, "move", current["version"], process_key="final_qa", role="inspector")
    clock.advance(600)
    change(api, item_id, "finish", current["version"], role="inspector")
    after = spool(api, item_id)
    assert after["welds"] == before["welds"]
    assert after["requirements"] == before["requirements"]
    for key in ("welds_done", "welds_required", "dimensional", "weld", "last_work_at", "released", "reinspection_due"):
        assert after["item"][key] == before["item"][key]
    assert api.post(f"/api/items/{item_id}/release", {"reference": "TIME-DOES-NOT-APPROVE"}, role="inspector").status_code == 409
    overview = ok(api.get("/api/tracking/overview"))
    summary = next(row for row in overview["spools"] if row["item_id"] == item_id)
    assert summary["production_process"]["status"] == "finished"
    durations(summary["production_process"]["totals"], 2400, 2400, 0)


def test_clock_regression_never_creates_negative_or_backdated_intervals(api, clock):
    item_id = make_spool(api)
    current = change(api, item_id, "start", 0, process_key="welding")
    clock.advance(-60)
    behind = process(api, item_id)
    durations(behind["current"], 0, 0, 0)
    assert dt.datetime.fromisoformat(behind["as_of"]) >= dt.datetime.fromisoformat(current["events"][0]["at"])
    response = api.post(f"/api/tracking/spools/{item_id}/process", {"action": "pause", "expected_version": 1, "notes": "Clock moved back"})
    assert response.status_code == 409, response.text
    assert process(api, item_id)["version"] == 1


def test_final_release_closes_paused_timer_once_and_reopen_does_not_restart_it(api, clock, monkeypatch):
    item_id = make_spool(api, planned=0, zero_weld_reason="Test package has no welded joints")
    current = change(api, item_id, "start", 0, process_key="final_qa", role="inspector")
    clock.advance(600)
    current = change(api, item_id, "pause", current["version"], notes="Waiting for release signature", role="inspector")
    clock.advance(300)
    monkeypatch.setattr(api.application, "utcnow", clock)
    ok(api.post(f"/api/items/{item_id}/inspect", {
        "kind": "Dimensional", "result": "Pass", "report": "LOCAL-DIMENSION-REPORT",
        "measurements": "Local dimensions accepted before release",
    }, role="inspector"))
    released = ok(api.post(f"/api/items/{item_id}/release", {"reference": "LOCAL-RELEASE"}, role="inspector"))
    assert released["released"] is True
    current = process(api, item_id)
    assert current["status"] == "finished" and current["current"] is None
    assert current["events"][-1]["event"] == "release"
    assert dt.datetime.fromisoformat(current["visits"][-1]["ended_at"]) == dt.datetime.fromisoformat(released["released_at"])
    durations(current["totals"], 900, 600, 300)
    assert api.post(f"/api/items/{item_id}/release", {"reference": "DUPLICATE"}, role="inspector").status_code == 409
    assert api.post(f"/api/tracking/spools/{item_id}/process", {"action": "start", "expected_version": current["version"], "process_key": "welding"}).status_code == 409
    clock.advance(3600)
    ok(api.post(f"/api/items/{item_id}/reopen"))
    reopened = process(api, item_id)
    assert reopened["status"] == "finished"
    assert reopened["events"] == current["events"]
    assert reopened["totals"] == current["totals"]
    restarted = change(api, item_id, "start", reopened["version"], process_key="welding")
    assert restarted["status"] == "running"
    assert len(restarted["visits"]) == 2
    durations(restarted["totals"], 900, 600, 300)
