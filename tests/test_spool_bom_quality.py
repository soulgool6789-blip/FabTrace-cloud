"""A heat/MTR correction invalidates quality proof for its physical scope."""
from test_order_labels import public_qr_url
from test_spool_reference_bom import physical_copies, trace_body, trace_record
from test_quality import (workspace, create_requirement, confirm_source,
                          accepted_evidence, review, review_ok, current, req)
from tracking_helpers import ok


def test_material_correction_stales_quality_proof_without_rewriting_reviews_or_other_spools(api):
    saved, rows = physical_copies(api)
    first, second = rows
    for row, marker in ((first, 'A'), (second, 'B')):
        ok(api.put(row['bom']['api_url'] + '/traceability', trace_body(trace_record(api, row), marker), role='handler'))
    workspace_id = workspace(api, project_id=saved['order']['project_id'])['workspace']['id']
    proofs = {}
    for row in rows:
        requirement_id = create_requirement(api, workspace_id, item_number=row['id'],
            title='Supplier material record for ' + row['id'], required_evidence_types=['production'])
        confirm_source(api, workspace_id, requirement_id)
        evidence_id = accepted_evidence(api, workspace_id, requirement_id, type='production', item_id=row['id'])
        review_ok(review(api, workspace_id, 'requirement', requirement_id, 'verified'))
        assert req(api, workspace_id, requirement_id)['status'] == 'verified'
        proofs[row['id']] = (requirement_id, evidence_id)
    before = current(api, workspace_id)
    changed = trace_body(trace_record(api, first), 'A')
    changed['reason'] = 'Correct the first flange heat against its supplier MTR'
    changed['materials'][1]['heat_number'] = 'CORRECTED-FLANGE-HEAT'
    ok(api.put(first['bom']['api_url'] + '/traceability', changed, role='inspector'))
    after = current(api, workspace_id)
    evidence = {row['id']: row for row in after['evidence']}
    first_req, first_ev = proofs[first['id']]
    second_req, second_ev = proofs[second['id']]
    assert evidence[first_ev]['stale'] is True
    assert evidence[first_ev]['status'] != 'accepted'
    assert req(api, workspace_id, first_req)['status'] != 'verified'
    assert evidence[second_ev]['stale'] is False
    assert evidence[second_ev]['status'] == 'accepted'
    assert req(api, workspace_id, second_req)['status'] == 'verified'
    assert before['reviews'] == after['reviews'], 'Correction retains the original signed review history'
