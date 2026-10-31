"""Read-only, exact-spool weld progress with honest required-quantity scope."""
import importlib

from sqlalchemy import select

from conftest import BADGES
from test_order_setup import branch, create_setup, detail
from test_order_labels import generate, labels, public_qr_url
from test_progress import database_state


def setup(api, number='WELD-PROGRESS', quantity=2, copies=2, count=2):
    spool = {'spool_number': 'REPEATED-SPOOL', 'quantity_per_assembly': copies}
    if count is not None:
        spool['welds_per_spool'] = count
    return create_setup(api, purchase_order=number,
        assemblies=[branch('REPEATED-ASSEMBLY', quantity, [spool])])['order']['project_id']


def progress(api, project):
    return detail(api, project)['assemblies'][0]['spools'][0]['weld_progress']


def record_work(api, item_id, operations=('root', 'fill_cap', 'complete'), timestamp=True):
    """Seed recorded historical work, without inventing arrival acceptance."""
    tracking = importlib.import_module('tracking')
    with api.session_factory() as session:
        weld = session.scalar(select(tracking.Weld).where(tracking.Weld.item_id == item_id)
                              .order_by(tracking.Weld.number))
        for operation in operations:
            session.add(tracking.WeldWork(weld_id=weld.id, cycle=weld.cycle,
                operation=operation, notes='Synthetic historical work', actor=BADGES['welder']))
        if timestamp:
            weld.completed_at = api.application.utcnow()
            weld.completed_by = BADGES['welder']
        session.commit()
        return weld.id


def test_required_but_unregistered_spools_remain_in_denominator(api, monkeypatch):
    project = setup(api)
    original = progress(api, project)
    assert (original['total'], original['required_spools'], original['registered_spools']) == (8, 4, 0)
    assert original['percent'] == original['completed'] == 0
    monkeypatch.setattr(importlib.import_module('order_labels'), 'WELD_GENERATION_LIMIT', 2)
    generate(api, project)
    row = labels(api, project)['items'][0]
    record_work(api, row['id'])
    before = database_state(api)
    current = progress(api, project)
    assert (current['total'], current['completed'], current['percent']) == (8, 1, 12.5)
    assert current['registered_spools'] == 1 and not current['scope_warning']
    assert database_state(api) == before
    receipt = api.get('/api/spool-boms/spools/' + row['id']).json()['arrival']
    assert receipt['status'] == 'pending' and not receipt['can_proceed']


def test_only_complete_current_cycle_work_receives_credit(api):
    project = setup(api, quantity=1, copies=4)
    generate(api, project)
    rows = labels(api, project)['items']
    record_work(api, rows[0]['id'], operations=())  # A timestamp is not a work record.
    record_work(api, rows[1]['id'], operations=('root', 'complete'))
    record_work(api, rows[2]['id'], timestamp=False)
    completed = record_work(api, rows[3]['id'])
    assert progress(api, project)['completed'] == 1
    tracking = importlib.import_module('tracking')
    with api.session_factory() as session:
        weld = session.get(tracking.Weld, completed)
        weld.cycle += 1
        # A stale completion timestamp and prior repair-cycle work do not count.
        session.commit()
    assert progress(api, project)['completed'] == 0


def test_matching_numbers_in_another_order_do_not_cross_count(api):
    first, second = setup(api, 'ORDER-ONE'), setup(api, 'ORDER-TWO')
    generate(api, first)
    generate(api, second)
    record_work(api, labels(api, second)['items'][0]['id'])
    assert progress(api, first)['completed'] == 0
    assert progress(api, second)['completed'] == 1


def test_removed_physical_spool_and_parent_do_not_count(api):
    project = setup(api, quantity=2, copies=1)
    generate(api, project)
    rows = labels(api, project)['items']
    for row in rows:
        record_work(api, row['id'])
    removal = importlib.import_module('removals')
    with api.session_factory() as session:
        for index, identity in enumerate((rows[0]['id'], rows[1]['assembly_id'])):
            session.add(removal.RecordRemoval(kind='item', record_id=identity, removed=True,
                version=1, batch_id=f'progress-removal-{index}', root_kind='item', root_id=identity,
                reason='Synthetic removed physical scope', changed_by=BADGES['admin']))
        session.commit()
    current = progress(api, project)
    assert current['completed'] == current['registered_spools'] == current['percent'] == 0
    assert current['required_spools'] == 2 and current['total'] == 4


def test_missing_or_conflicting_weld_scope_is_flagged_without_percentage(api):
    project = setup(api, quantity=1, copies=1)
    generate(api, project)
    row = labels(api, project)['items'][0]
    tracking = importlib.import_module('tracking')
    with api.session_factory() as session:
        session.get(tracking.SpoolPlan, row['id']).planned_welds = 3
        session.commit()
    current = progress(api, project)
    assert current['defined'] and current['percent'] is None
    assert 'declared weld plan' in current['scope_warning']


def test_declared_zero_and_undeclared_do_not_claim_completion(api):
    zero = progress(api, setup(api, 'ZERO', count=0))
    unknown = progress(api, setup(api, 'UNKNOWN', count=None))
    assert zero['defined'] and zero['total'] == 0 and zero['percent'] is None
    assert not unknown['defined'] and unknown['total'] is None and unknown['percent'] is None
