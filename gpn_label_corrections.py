"""Apply explicitly confirmed business-label corrections without changing scope.

The retained GPN remains the identity basis for physical records, uploaded files
and signed QA. These corrections only supply current business labels. An
immutable audit marker makes each correction run once and respects later edits.
"""
from sqlalchemy import select

from main import Audit, audit, utcnow
from orders import (OrderGpn, PurchaseOrder, _guard_group_number, _key,
                    _set_assembly_number, business_gpn)


ACTOR = 'system:init-db:gpn-label-v1'
EVENT = 'ORDER_GPN_LABEL_CORRECTED'
CORRECTIONS = ({
    'key': '2026-11-02-kelvion-01-1193403',
    'project_id': 'PO-1F80E4618276345B54CEBFFA',
    'purchase_order': 'Kelvion-01',
    'gpn_id': 'OGPN-90D187E3E996EDE04EB841E8',
    'retained_gpn': '1193403643-777',
    'gpn_label': '1193403',
    'assembly_number': '643-777',
    'reason': 'User confirmed that 643-777 is the separate Assembly Number, '
              'not part of GPN 1193403; correct current labels for this saved group.',
},)


def _identity(group):
    return {'gpn_id': group.id, 'gpn': group.gpn, 'gpn_label': group.gpn_label,
            'business_gpn': business_gpn(group), 'assembly_number': group.assembly_number}


def apply_confirmed_gpn_label_corrections(s):
    """Run inside the initializer transaction; never commit independently.

    Only exact, confirmed records are eligible. Conflicting metadata stops the
    transaction. Missing target groups are irrelevant to other installations.
    The audit identifies this system migration, never a human employee.
    """
    from flow import lock_topology
    from removals import gpn_is_removed, project_is_removed

    lock_topology(s)
    report = {'applied': 0, 'already_applied': 0, 'not_applicable': 0}
    markers = {(row.details.get('correction_id'), row.details.get('project_id'),
                row.details.get('gpn_id')) for row in s.scalars(
                    select(Audit).where(Audit.actor == ACTOR, Audit.event == EVENT))
               if isinstance(row.details, dict)}
    for change in CORRECTIONS:
        marker = (change['key'], change['project_id'], change['gpn_id'])
        if marker in markers:
            report['already_applied'] += 1
            continue
        order = s.scalar(select(PurchaseOrder).where(
            PurchaseOrder.project_id == change['project_id']).with_for_update()
            .execution_options(populate_existing=True))
        group = s.scalar(select(OrderGpn).where(OrderGpn.id == change['gpn_id'])
            .with_for_update().execution_options(populate_existing=True))
        if group is None:
            report['not_applicable'] += 1
            continue
        if (order is None or group.project_id != change['project_id']
                or _key(order.purchase_order) != _key(change['purchase_order'])
                or group.gpn != change['retained_gpn']
                or group.normalized_gpn != _key(change['retained_gpn'])):
            raise RuntimeError('Confirmed GPN label correction found a different saved identity; no correction was committed')
        if project_is_removed(s, order.project_id) or gpn_is_removed(s, group.id):
            raise RuntimeError('Confirmed GPN label correction targets removed records; no correction was committed')
        if (group.gpn_label not in (None, '', change['retained_gpn'], change['gpn_label'])
                or group.assembly_number not in ('', change['assembly_number'])
                or group.normalized_assembly_number != (_key(group.assembly_number) if group.assembly_number else None)):
            raise RuntimeError('Confirmed GPN label correction found conflicting current labels; no correction was committed')
        _guard_group_number(s, order.project_id, group.gpn, change['assembly_number'], excluding=group.id)
        before, version_before = _identity(group), order.version
        changed = group.gpn_label != change['gpn_label'] or group.assembly_number != change['assembly_number']
        if changed:
            group.gpn_label = change['gpn_label']
            _set_assembly_number(group, change['assembly_number'])
            group.updated_at = order.updated_at = utcnow()
            order.version += 1
            report['applied'] += 1
        else:
            # Record a one-time verification marker even if an authorized user
            # already entered these labels, so future corrections stay intact.
            report['already_applied'] += 1
        audit(s, None, ACTOR, EVENT, {
            'correction_id': change['key'], 'project_id': order.project_id,
            'purchase_order': order.purchase_order, 'gpn_id': group.id,
            'version_before': version_before, 'version': order.version,
            'before': before, 'after': _identity(group), 'reason': change['reason'],
            'execution': 'Versioned startup data correction',
            'outcome': 'corrected' if changed else 'already_correct',
        })
        markers.add(marker)
    s.flush()
    return report
