"""Live material colors stay separate from each piece's immutable QA basis."""
from conftest import BADGES
from receiving_helpers import accept_arrival, receiving_detail, upload_receiving_bom
from test_material_piece_qa import edit_piece
from test_progress import database_state
from test_spool_receiving import create_spool


def test_material_movement_changes_colors_without_rewriting_piece_approvals(api):
    from flow import FlowPlan
    from spool_boms import spool_bom_basis

    item_id = create_spool(api, 'MATERIAL-COLOR-01')
    upload_receiving_bom(api, item_id, quantity=2)
    pending = receiving_detail(api, item_id)['traceability']['materials']
    assert all(row['flow_stage']['key'] == 'qa_001' for row in pending)
    assert all(row['flow_stage']['color'] == 'black' for row in pending)
    approved = accept_arrival(api, item_id)['traceability']['materials']
    with api.session_factory() as session:
        basis = spool_bom_basis(session, item_id)
        # A persisted local traveler position, independent of the material
        # evidence model. The full real transition path is covered in test_flow.
        session.add(FlowPlan(item_id=item_id, route='spool', current_step=12,
            status='active', baseline_step=9, started_by=BADGES['admin']))
        session.commit()

    before_read = database_state(api)
    floor = receiving_detail(api, item_id)['traceability']['materials']
    assert all(row['flow_stage']['key'] == 'floor' and row['flow_stage']['color'] == 'yellow' for row in floor)
    assert [row['qa001']['basis_sha256'] for row in floor] == [row['qa001']['basis_sha256'] for row in approved]
    assert [row['qa001']['latest'] for row in floor] == [row['qa001']['latest'] for row in approved]
    assert database_state(api) == before_read
    with api.session_factory() as session:
        assert spool_bom_basis(session, item_id) == basis
        session.get(FlowPlan, item_id).current_step = 13
        session.commit()

    welding = receiving_detail(api, item_id)['traceability']['materials']
    assert all(row['flow_stage']['color'] == 'blue' for row in welding)
    assert [row['qa001']['latest'] for row in welding] == [row['qa001']['latest'] for row in approved]

    revised = edit_piece(api, item_id, 1, heat_number='MATERIAL-RECHECK-HEAT')
    first, second = revised['traceability']['materials']
    assert first['qa001']['can_proceed'] and first['flow_stage']['color'] == 'blue'
    assert second['qa001']['status'] == 'needs_reinspection'
    assert second['flow_stage']['key'] == 'qa_001' and second['flow_stage']['color'] == 'black'
    assert not revised['arrival']['can_proceed']

