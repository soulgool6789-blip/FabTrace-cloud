"""Read-only project parts progress using recorded work and current quality state.

Project ownership is explicit: a spool plan, an assigned component's parent plan,
or an exact project ID on a legacy item. Textual project names are never guessed.
The percentages describe registered records, not an unrecorded intended BOM.
"""
from collections import defaultdict
import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from read_projection import prime_projection, read_response

from main import Employee, Item, Rework, auth, db, utcnow
from tracking import (Project, Subproject, SpoolPlan, Weld, WeldRequirement,
    RequirementEvidence, RequirementReview, WeldWork, TrackingHold,
    _production_complete, _qa_accepted, _weld_blockers, _requirement_satisfied, _after,
    post_fabrication_heat_errors)
from flow import FlowPlan, FlowEvent, FlowException, ComponentLink, ROUTE_BY_ID, STEP_BY_NUMBER

router = APIRouter(prefix='/api/progress', tags=['project progress'])
DEFINITIONS = {
    'scope': 'Registered parts explicitly assigned by spool plan, component parent, or an exact project ID. Unregistered BOM scope is not counted.',
    'finished': 'Current fabrication release with satisfied physical checks; components must complete preparation. Packet approval and handover are separate.',
    'recorded_steps': 'Completed current-route step records out of all route steps. Historical baseline steps remain not recorded; return paths reopen affected steps.',
    'wip': 'Registered parts whose current fabrication checks are not finished.',
    'shipping': 'Shipped and delivered are recorded traveler milestones. A later quality blocker remains visible.',
}


def _group(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[getattr(row, key)].append(row)
    return result


def _stamp(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.isoformat()


def _recorded_steps(plan, events, testing=None):
    if not plan:
        return 0, 0, 0
    route = ROUTE_BY_ID[plan.route]
    states = {n: 'not_recorded' if n < plan.baseline_step else 'pending'
              for n in range(route['first_step'], route['last_step'] + 1)}
    for event in events:
        if event.action in ('fail', 'reopen', 'admin_return_to_work'):
            target = (event.data or {}).get('return_step', event.step)
            if target is not None:
                for n in states:
                    if n >= target:
                        states[n] = 'pending'
        elif event.action == 'advance' and event.step in states and not (event.data or {}).get('phase_only'):
            states[event.step] = 'completed'
    from flow_testing import project_step_states
    states = project_step_states(states, testing)
    if plan.status == 'active' and plan.current_step in states:
        states[plan.current_step] = 'current'
    return (sum(v == 'completed' for v in states.values()),
            sum(v != 'not_required' for v in states.values()),
            sum(v == 'not_recorded' for v in states.values()))


def project_rows(s, project_id=None):
    """Return one row per in-scope physical item, without writes or row locks.

    Preload related history by group, not by requirement. Keep all objects alive
    for SQLAlchemy's identity map while evaluating existing tracking helpers.
    This function deliberately has no dependency on dossier.py and can also be
    used by project-package scope validation and the Excel snapshot connection.
    """
    from administration import release_summary
    from order_spools import OrderSpool
    from orders import OrderAssembly, OrderGpn
    from removals import RecordRemoval
    with s.no_autoflush:
        projects = s.scalars(select(Project).where(Project.id == project_id) if project_id else select(Project)).all()
        project_ids = {p.id for p in projects}
        if not project_ids:
            return []
        all_plans = {p.item_id: p for p in s.scalars(select(SpoolPlan)).all()}
        all_registrations = {r.item_id: r for r in s.scalars(select(OrderSpool)).all()}
        registered_projects = {r.item_id: project for r, project in s.execute(
            select(OrderSpool, OrderGpn.project_id)
            .join(OrderAssembly, OrderAssembly.item_id == OrderSpool.assembly_id)
            .join(OrderGpn, OrderGpn.id == OrderAssembly.gpn_id)).all()}
        all_links = {r.component_id: r for r in s.scalars(select(ComponentLink)).all()}
        selected_ids = {key for key, plan in all_plans.items() if plan.project_id in project_ids}
        selected_ids |= {key for key, project in registered_projects.items() if project in project_ids}
        selected_ids |= {key for key, link in all_links.items() if link.spool_id in selected_ids}
        items = s.scalars(select(Item).where(or_(Item.id.in_(selected_ids), Item.project.in_(project_ids))).order_by(Item.id)).all()
        scopes = {}
        for item in items:
            plan, link = all_plans.get(item.id), all_links.get(item.id)
            registration = all_registrations.get(item.id)
            parent = all_plans.get(link.spool_id) if link else None
            if registration:
                scope = (registered_projects[item.id], plan.subproject_id if plan else None,
                         registration.assembly_id, 'order_spool_registration')
            elif plan:
                scope = (plan.project_id, plan.subproject_id, plan.assembly_id, 'spool_plan')
            elif parent:
                scope = (parent.project_id, parent.subproject_id, parent.item_id, 'component_link')
            else:
                scope = (item.project, None, None, 'item_project_id')
            if scope[0] in project_ids:
                scopes[item.id] = scope
        items = [item for item in items if item.id in scopes]
        prime_projection(s, items)
        ids = [item.id for item in items]
        if not ids:
            return []
        by_id = {item.id: item for item in items}
        removed_ids = set(s.scalars(select(RecordRemoval.record_id).where(
            RecordRemoval.kind == 'item', RecordRemoval.removed.is_(True),
            RecordRemoval.record_id.in_(ids))).all())
        flows = {f.item_id: f for f in s.scalars(select(FlowPlan).where(FlowPlan.item_id.in_(ids))).all()}
        flow_events = _group(s.scalars(select(FlowEvent).where(FlowEvent.item_id.in_(ids),
            FlowEvent.action.in_(('advance', 'fail', 'reopen', 'admin_return_to_work'))).order_by(FlowEvent.sequence)).all(), 'item_id')
        exceptions = _group(s.scalars(select(FlowException).where(FlowException.item_id.in_(ids),
            FlowException.closed_at.is_(None))).all(), 'item_id')
        reworks = _group(s.scalars(select(Rework).where(Rework.item_id.in_(ids), Rework.closed_at.is_(None))).all(), 'item_id')
        holds = _group(s.scalars(select(TrackingHold).where(TrackingHold.item_id.in_(ids))).all(), 'item_id')
        weld_list = s.scalars(select(Weld).where(Weld.item_id.in_(ids)).order_by(Weld.number)).all()
        welds = _group(weld_list, 'item_id')
        requirements = _group(s.scalars(select(WeldRequirement).where(WeldRequirement.item_id.in_(ids))).all(), 'item_id')
        evidence = _group(s.scalars(select(RequirementEvidence).join(WeldRequirement,
            WeldRequirement.id == RequirementEvidence.requirement_id).where(WeldRequirement.item_id.in_(ids))
            .order_by(RequirementEvidence.id.desc())).all(), 'requirement_id')
        reviews = _group(s.scalars(select(RequirementReview).join(WeldRequirement,
            WeldRequirement.id == RequirementReview.requirement_id).where(WeldRequirement.item_id.in_(ids))
            .order_by(RequirementReview.id.desc())).all(), 'requirement_id')
        work = _group(s.scalars(select(WeldWork).join(Weld, Weld.id == WeldWork.weld_id)
            .where(Weld.item_id.in_(ids))).all(), 'weld_id')
        # The existing helper only reads work/requirements/holds. A full repair
        # history is unnecessary for these progress counts.
        subs = {r.id: r for r in s.scalars(select(Subproject)).all()}
        component_children, spool_children = defaultdict(list), defaultdict(set)
        for link in all_links.values():
            component_children[link.spool_id].append(link.component_id)
        for plan in all_plans.values():
            if plan.assembly_id:
                spool_children[plan.assembly_id].add(plan.item_id)
        for registration in all_registrations.values():
            spool_children[registration.assembly_id].add(registration.item_id)
        raw, base_errors = {}, {}
        previous = s.info.get('tracking_read_snapshot')
        try:
            for item in items:
                plan, flow = all_plans.get(item.id), flows.get(item.id)
                from spool_receiving import receiving_errors, receiving_summary
                arrival = receiving_summary(s, item)
                errors = receiving_errors(s, item)
                release_control = release_summary(s, item)
                if release_control['active_override']:
                    errors.append('Administrative release is recorded; ordinary QA release has not been verified')
                if item.on_hold:
                    errors.append('Item is on hold')
                errors.extend('Open hold: ' + hold.reason for hold in holds[item.id] if hold.closed_at is None)
                errors.extend('Open item rework: ' + r.reason for r in reworks[item.id])
                errors.extend(f'Open process exception at step {e.step}: {e.reason}' for e in exceptions[item.id])
                production, qa = 0, 0
                if plan:
                    s.info['tracking_read_snapshot'] = {'item_id': item.id, 'welds': welds[item.id],
                        'requirements': requirements[item.id], 'holds': holds[item.id], 'evidence': evidence,
                        'reviews': reviews, 'work': work, 'repairs': {}, 'open_rework': bool(reworks[item.id])}
                    production = sum(_production_complete(s, w) for w in welds[item.id])
                    qa = sum(_qa_accepted(s, w) for w in welds[item.id])
                    if len(welds[item.id]) != plan.planned_welds:
                        errors.append(f'Weld scope incomplete: {len(welds[item.id])} defined of {plan.planned_welds} planned')
                    if plan.planned_welds == 0 and not plan.zero_weld_reason.strip():
                        errors.append('Zero-weld scope needs its reason')
                    for w in welds[item.id]:
                        errors.extend(f'{w.number}: {message}' for message in _weld_blockers(s, w))
                    errors.extend('Spool requirement: ' + r.label for r in requirements[item.id]
                                  if not r.weld_id and not _requirement_satisfied(s, r))
                    if item.dimensional != 'Pass' or not _after(item.dimension_at, item.last_work_at):
                        errors.append('Current passing dimensional inspection required')
                    if plan.subproject_id and (plan.subproject_id not in subs or subs[plan.subproject_id].project_id != plan.project_id):
                        errors.append('Subproject assignment does not match the project')
                    if not item.released:
                        errors.append('Final quality release is not recorded')
                elif not flow or flow.route != 'component':
                    errors.append('Set up the structured spool plan or component route')
                errors.extend(post_fabrication_heat_errors(s, item))
                from flow import current_step_definition
                from flow_testing import testing_state
                completed, total, unrecorded = _recorded_steps(flow, flow_events[item.id], testing_state(s, flow))
                current_definition = current_step_definition(s, flow) if flow and flow.current_step else None
                kind = 'assembly' if plan and item.kind == 'Assembly' else 'spool' if plan else 'component' if flow and flow.route == 'component' else 'unplanned'
                raw[item.id] = {'id': item.id, 'description': item.description,
                    'google_part_number': item.google_part_number, 'kind': kind, 'item_kind': item.kind,
                    'project_id': scopes[item.id][0], 'subproject_id': scopes[item.id][1],
                    'parent_id': scopes[item.id][2], 'scope_source': scopes[item.id][3],
                    'planned_welds': plan.planned_welds if plan else 0, 'completed_welds': production,
                    'qa_accepted': qa, 'completed_steps': completed, 'total_steps': total,
                    'not_recorded_steps': unrecorded, 'flow_status': flow.status if flow else 'not_started',
                    'current_step': flow.current_step if flow else None,
                    'current_title': current_definition['title'] if current_definition else '',
                    'released': bool(item.released), 'location': item.location, 'handler': item.handler,
                    'release_mode': release_control['mode'], 'release_label': release_control['label'],
                    'administrative_release': release_control['active_override'],
                    'receiving': {key: arrival.get(key) for key in
                                  ('required', 'status', 'can_proceed', 'version', 'blockers', 'latest')},
                    'updated_at': _stamp(item.updated_at)}
                from parts import parts_summary
                parts = parts_summary(s, item.id)
                if parts:
                    raw[item.id]['parts'] = parts
                    errors.extend('Required parts: ' + message for message in parts['blockers'])
                base_errors[item.id] = list(dict.fromkeys(errors))
        finally:
            if previous is None:
                s.info.pop('tracking_read_snapshot', None)
            else:
                s.info['tracking_read_snapshot'] = previous

        def dependencies(item_id, seen=None):
            seen = set(seen or ())
            if item_id in seen:
                return ['Circular parent/child relationship']
            seen.add(item_id)
            flow = flows.get(item_id)
            if not flow or flow.route == 'component':
                return []
            children = component_children[item_id] if flow.route == 'spool' else spool_children[item_id]
            if item_id not in removed_ids:
                children = [child for child in children if child not in removed_ids]
            errors = []
            if len(children) != flow.expected_children:
                errors.append(f'Child scope incomplete: {len(children)} linked of {flow.expected_children} declared')
            if flow.route == 'spool' and not children and not flow.material_reference.strip():
                errors.append('Historical material basis is missing')
            if flow.route == 'assembly' and flow.expected_children < 1:
                errors.append('Assembly child scope is missing')
            for child in children:
                if child not in raw or raw[child]['project_id'] != raw[item_id]['project_id']:
                    errors.append(f'{child}: missing child record or project mismatch')
                    continue
                child_flow = flows.get(child)
                expected_route = 'component' if flow.route == 'spool' else 'spool'
                if not child_flow or child_flow.route != expected_route or child_flow.status != 'completed':
                    errors.append(f'{child}: child route is incomplete')
                errors.extend(f'{child}: {e}' for e in base_errors[child])
                errors.extend(f'{child}: {e}' for e in dependencies(child, seen))
            return errors

        rows = []
        for item in items:
            row, flow = raw[item.id], flows.get(item.id)
            errors = list(dict.fromkeys(base_errors[item.id] + dependencies(item.id)))
            complete = bool(flow and flow.route == 'component' and flow.status == 'completed') if row['kind'] == 'component' else bool(row['released'] and row['kind'] != 'unplanned')
            complete = complete and not errors
            status = flow.status if flow and flow.status in ('shipped', 'delivered') else 'finished' if complete else 'wip'
            if row['total_steps']:
                basis, percent = 'recorded_steps', row['completed_steps'] / row['total_steps'] * 100
            elif row['planned_welds']:
                basis, percent = 'weld_completion', min(100, row['completed_welds'] / row['planned_welds'] * 100)
            elif item.id in all_plans:
                basis, percent = 'qa_release', 100 if complete else 0
            else:
                basis, percent = 'not_started', 0
            row.update(status=status, fabrication_finished=complete, blocked=bool(errors), blockers=errors,
                       progress_percent=round(percent, 1), progress_basis=basis)
            rows.append(row)
        return rows


def summarize(project, rows, has_dossier=False):
    total = len(rows)
    finished = sum(bool(row['fabrication_finished']) for row in rows)
    recorded = sum(row['completed_steps'] for row in rows)
    possible = sum(row['total_steps'] for row in rows)
    return {'id': project.id, 'name': project.name, 'client': project.client,
        'total_parts': total, 'wip': total - finished, 'finished': finished,
        'shipped': sum(row['status'] == 'shipped' for row in rows),
        'delivered': sum(row['status'] == 'delivered' for row in rows),
        'blocked': sum(row['blocked'] for row in rows),
        'finished_percent': round(finished / total * 100, 1) if total else 0,
        'recorded_steps_completed': recorded, 'recorded_steps_total': possible,
        'recorded_percent': round(recorded / possible * 100, 1) if possible else 0,
        'planning_needed': sum(row['kind'] == 'unplanned' for row in rows),
        'has_dossier': has_dossier}


def _configured(s):
    from dossier import DossierProject
    return set(s.scalars(select(DossierProject.project_id)).all())


@router.get('/projects')
@read_response
def projects(user: Employee = Depends(auth), s: Session = Depends(db)):
    from removals import item_not_removed, project_not_removed
    projects = s.scalars(select(Project).where(project_not_removed(Project.id)).order_by(Project.id)).all()
    active_ids = set(s.scalars(select(Item.id).where(item_not_removed())))
    rows = [row for row in project_rows(s) if row['id'] in active_ids]
    configured = _configured(s)
    return {'as_of': _stamp(utcnow()), 'definitions': DEFINITIONS,
            'projects': [summarize(p, [r for r in rows if r['project_id'] == p.id], p.id in configured) for p in projects]}


@router.get('/projects/{project_id}')
@read_response
def project_progress(project_id: str,
    status: Literal['all', 'wip', 'finished', 'shipped', 'delivered'] = 'all',
    subproject_id: str = '', kind: Literal['all', 'component', 'spool', 'assembly', 'unplanned'] = 'all',
    search: str = Query('', max_length=200), sort: Literal['status', 'progress_asc', 'progress_desc', 'id'] = 'status',
    user: Employee = Depends(auth), s: Session = Depends(db)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, 'Project not found')
    from removals import item_not_removed, project_is_removed, removal_summary
    removed = project_is_removed(s, project_id)
    rows = project_rows(s, project_id)
    if not removed:
        active_ids = set(s.scalars(select(Item.id).where(item_not_removed())))
        rows = [row for row in rows if row['id'] in active_ids]
    counts = summarize(project, rows, project_id in _configured(s))
    matches = []
    needle = search.strip().casefold()
    for row in rows:
        if subproject_id and row['subproject_id'] != subproject_id:
            continue
        if kind != 'all' and row['kind'] != kind:
            continue
        if status == 'wip' and row['fabrication_finished'] or status == 'finished' and not row['fabrication_finished']:
            continue
        if status in ('shipped', 'delivered') and row['status'] != status:
            continue
        if needle and needle not in ' '.join(str(row.get(k) or '') for k in ('id', 'description', 'google_part_number', 'current_title')).casefold():
            continue
        matches.append(row)
    order = {'wip': 0, 'finished': 1, 'shipped': 2, 'delivered': 3}
    key = (lambda r: (r['progress_percent'], r['id'])) if sort == 'progress_asc' else (
        (lambda r: (-r['progress_percent'], r['id'])) if sort == 'progress_desc' else (
        (lambda r: r['id']) if sort == 'id' else (lambda r: (order[r['status']], r['id']))))
    matches.sort(key=key)
    # Keep project_rows stable for dossier and export consumers; attach the live
    # physical identity/status only to this selected UI response.
    from spool_presentation import item_presentations
    displays = item_presentations(s, s.scalars(select(Item).where(
        Item.id.in_([row['id'] for row in matches])))) if matches else {}
    matches = [{**row, **displays.get(row['id'], {})} for row in matches]
    return {'project': {'id': project.id, 'name': project.name, 'client': project.client},
        'removal': removal_summary(s, 'order', project_id), 'can_mutate': not removed,
        'as_of': _stamp(utcnow()), 'definitions': DEFINITIONS, 'counts': counts,
        'subprojects': [{'id': p.id, 'name': p.name} for p in s.scalars(select(Subproject).where(Subproject.project_id == project_id).order_by(Subproject.id))],
        'items': matches, 'total': len(matches)}

