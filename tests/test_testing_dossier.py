"""New testing logistics preserve proof; recorded failures/work invalidate it."""

import copy
import datetime as dt
import importlib

import pytest

from conftest import BADGES
from test_dossier import (PRESSURE_VALUES, check, document, entry, make_project,
                          packet, review, sign_source, signed)
from tracking_helpers import add_weld, ok


def signed_pressure(api):
    item_id = make_project(api, planned=1)
    weld = add_weld(api, item_id)
    signed(sign_source(api))
    file = document(api, code='TEST-PHASE-PRESSURE', section='06', item_id=item_id)
    signed(entry(api, item_id, 'pressure', document_ids=[file['id']], values=PRESSURE_VALUES))
    signed(review(api, item_id, 'pressure'))
    before=check(api, item_id, 'pressure')
    dossier=importlib.import_module('dossier')
    with api.session_factory() as s:
        before['_saved_snapshot']=copy.deepcopy(s.get(dossier.DossierReview,before['latest_review']['id']).snapshot)
    return item_id, weld, before


def save_event(api, item_id, *, action='advance', step=18, testing_action='review',
               phase='pressure_qa', protocol='CLM-TEST-v1', sequence=1, **values):
    flow = importlib.import_module('flow')
    with api.session_factory() as s:
        event = flow.FlowEvent(item_id=item_id, sequence=sequence, action=action,
            step=step, actor=BADGES['inspector'], at=api.application.utcnow() + dt.timedelta(seconds=sequence),
            reference='TEST-SAVED-PHASE-' + str(sequence), notes='Synthetic append-only phase record',
            data={'testing_protocol':protocol, 'testing_phase':phase, 'testing_action':testing_action,
                  'testing_cycle':1, 'testing_attempt':1, 'test_kind':'pressure',
                  'test_result':'FAIL' if action == 'fail' else 'PASS', **values})
        s.add(event)
        s.commit()
        return event.id


def test_new_successful_testing_phases_do_not_stale_their_approved_evidence(api):
    item_id, _, before = signed_pressure(api)
    phases = [('decision',17,'decision'), ('start',17,'ndt'), ('complete',17,'ndt'),
              ('review',18,'ndt_qa'), ('handoff',19,'floor_before_pressure'),
              ('start',17,'pressure_test'), ('complete',17,'pressure_test'),
              ('review',18,'pressure_qa'), ('handoff',19,'floor_before_paint')]
    ids = []
    for sequence,(action,step,phase) in enumerate(phases,1):
        ids.append(save_event(api,item_id,step=step,testing_action=action,phase=phase,sequence=sequence))
        current = check(api,item_id,'pressure')
        assert current['status'] == 'accepted'
        assert current['fingerprint'] == before['fingerprint']
        assert current['latest_review'] == before['latest_review']
    # They remain in the issued-record source; filtering a structural basis
    # never removes or rewrites the saved traveler evidence.
    detail = packet(api,item_id)
    assert [event['id'] for event in detail['records']['flow_events']] == ids
    dossier=importlib.import_module('dossier')
    with api.session_factory() as s:
        assert s.get(dossier.DossierReview,before['latest_review']['id']).snapshot == before['_saved_snapshot']


@pytest.mark.parametrize('change', ['qa_failure','correction','legacy_qa','unrecognized_protocol','material','work','scope'])
def test_actual_testing_invalidation_and_legacy_bases_remain_effective(api,change):
    item_id, weld, before = signed_pressure(api)
    if change == 'qa_failure':
        save_event(api,item_id,action='fail',return_step=17)
    elif change == 'correction':
        save_event(api,item_id,step=17,testing_action='correct',phase='pressure_rework',
            correction={'reference':'TEST-CORRECTION','resolution':'Actual corrective work recorded'})
    elif change == 'legacy_qa':
        save_event(api,item_id,protocol=None)
    elif change == 'unrecognized_protocol':
        save_event(api,item_id,protocol='UNKNOWN-TEST-PROTOCOL')
    elif change == 'material':
        ok(api.patch('/api/tracking/welds/'+weld['id'],{
            'expected_version':weld['version'],'heat_a':'NEW-PHYSICAL-HEAT',
            'change_reason':'Actual replacement material after the saved pressure proof'}))
    elif change == 'work':
        from receiving_helpers import accept_arrival
        accept_arrival(api,item_id)
        ok(api.post('/api/tracking/welds/'+weld['id']+'/work',{
            'operation':'fitup','notes':'Actual fit-up work after the recorded proof'},role='welder'))
    else:
        # The fingerprint binds exact actual scope even for zero production
        # activity. This isolated persisted change tests that structural rule.
        tracking = importlib.import_module('tracking')
        with api.session_factory() as s:
            s.get(tracking.SpoolPlan,item_id).planned_welds = 2
            s.commit()
    current = check(api,item_id,'pressure')
    assert current['status'] == 'stale'
    assert current['fingerprint'] != before['fingerprint']
    assert current['latest_review'] == before['latest_review']
    dossier=importlib.import_module('dossier')
    with api.session_factory() as s:
        assert s.get(dossier.DossierReview,before['latest_review']['id']).snapshot == before['_saved_snapshot']


def test_legacy_structural_projection_is_byte_for_byte_unchanged(api):
    item_id, _, _ = signed_pressure(api)
    for sequence,(action,step,return_step) in enumerate([
        ('advance',1,None),('advance',7,None),('advance',17,None),('advance',18,None),
        ('advance',19,None),('fail',18,17),('fail',22,21),('reopen',22,17)],1):
        save_event(api,item_id,action=action,step=step,protocol=None,
            testing_action=None,sequence=sequence,return_step=return_step)
    dossier = importlib.import_module('dossier')
    records = packet(api,item_id)['records']
    actual = dossier._structural(records)
    expected = copy.deepcopy(actual)
    expected['physical_events'] = [event for event in records['flow_events']
        if (event['action']=='advance' and event['step'] in (1,7,18)) or
           (event['action'] in ('fail','reopen') and
            (event['data'].get('return_step',event['step']) or 0)<=19)]
    assert dossier._digest(actual) == dossier._digest(expected)
    assert actual == expected
