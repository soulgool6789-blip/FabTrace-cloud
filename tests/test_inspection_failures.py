"""The failed-inspections board shows signed, unresolved findings only."""

import datetime as dt
import importlib

from sqlalchemy import event, func, select

from conftest import BADGES


PATH = '/api/flow/inspection-failures'
BASE = dt.datetime(2026, 10, 2, 9, tzinfo=dt.timezone.utc)


def family(api, prefix='FAIL', count=2, *, flows=True, legacy=False):
    flow = importlib.import_module('flow')
    tracking = importlib.import_module('tracking')
    identities = importlib.import_module('order_spools')
    project, assembly = prefix + '-PROJECT', prefix + '-ASSEMBLY'
    spool_ids = [prefix + '-SPOOL-' + str(index) for index in range(count)]
    with api.session_factory() as session:
        session.add(tracking.Project(id=project, name='Isolated failure board test',
            created_by=BADGES['admin']))
        session.add_all(api.application.Item(id=identifier, description='Local test ' + identifier,
            kind='Assembly' if identifier == assembly else 'Spool', project=project,
            google_part_number='' if identifier == assembly else 'SAME-DRAWING-NUMBER',
            handler=BADGES['handler'], location='Local test bay', welds_required=0)
            for identifier in [assembly, *spool_ids])
        session.flush()
        session.add_all(tracking.SpoolPlan(item_id=identifier, project_id=project,
            assembly_id=assembly if identifier != assembly else None, planned_welds=0,
            zero_weld_reason='Isolated projection fixture', created_by=BADGES['admin'])
            for identifier in [assembly, *spool_ids])
        session.add_all(identities.SpoolQrIdentity(item_id=identifier,
            spool_number='SAME-DRAWING-NUMBER', normalized_number=prefix.lower(),
            sequence=index + 1, display_code=f'{prefix}-COPY-[{index + 1:03d}]',
            normalized_code=f'{prefix.lower()}-copy-{index + 1}',
            created_by=BADGES['admin'], source='local-test')
            for index, identifier in enumerate(spool_ids))
        if flows:
            session.add_all(flow.FlowPlan(item_id=identifier,
                catalog_version=None if legacy else flow.VERSION,
                route='assembly' if identifier == assembly else 'spool',
                current_step=17 if identifier == assembly else 10,
                status='active', baseline_step=17 if identifier == assembly else 9,
                started_by=BADGES['admin']) for identifier in [assembly, *spool_ids])
        session.commit()
    return project, assembly, spool_ids


def failure(api, item_id, step, *, context=None, closed=False, at=None):
    flow = importlib.import_module('flow')
    with api.session_factory() as session:
        plan = session.get(flow.FlowPlan, item_id)
        sequence = (session.scalar(select(func.max(flow.FlowEvent.sequence)).where(
            flow.FlowEvent.item_id == item_id)) or 0) + 1
        now = at or BASE + dt.timedelta(minutes=sequence)
        finding = flow.FlowException(item_id=item_id, step=step,
            return_step=flow.QA_REWORK_STEPS[step],
            reason=f'Actual recorded defect at step {step}', reference=f'FAIL-{step}',
            opened_by=BADGES['inspector'], opened_at=now,
            closed_by=BADGES['inspector'] if closed else None,
            closed_at=now + dt.timedelta(minutes=1) if closed else None)
        session.add(finding)
        session.flush()
        data = {'exception_id': finding.id, 'return_step': finding.return_step,
                'step_definition': dict(flow.step_definition(plan, step)),
                'definition_version': flow.catalog_version(plan), **(context or {})}
        session.add(flow.FlowEvent(item_id=item_id, sequence=sequence, action='fail',
            step=step, actor=BADGES['inspector'], at=now,
            reference=finding.reference, notes=finding.reason, data=data))
        if plan:
            plan.current_step = finding.return_step
        session.commit()
        return finding.id


def correction(api, item_id, exception_id, step, *, description='Completed the documented repair', context=None):
    flow = importlib.import_module('flow')
    with api.session_factory() as session:
        sequence = (session.scalar(select(func.max(flow.FlowEvent.sequence)).where(
            flow.FlowEvent.item_id == item_id)) or 0) + 1
        row = flow.FlowEvent(item_id=item_id, sequence=sequence, action='advance', step=step,
            actor=BADGES['fitup_welder'] if step == 10 else BADGES['process_welder'],
            at=BASE + dt.timedelta(minutes=20 + sequence), reference='REPAIR-REFERENCE',
            notes='Worker repair evidence', data={'reworked_exception_ids': [exception_id],
                'resolution': description, **(context or {})})
        session.add(row)
        session.commit()
        return row.id


def material_register(api, item_id, keys=('piece-a', 'piece-b')):
    module = importlib.import_module('spool_boms')
    with api.session_factory() as session:
        session.add(module.SpoolBomTrace(spool_id=item_id, catalog_id='LOCAL-TEST',
            spool_number='SAME-DRAWING-NUMBER', source_sha256='a' * 64,
            definition={'catalog_id': 'LOCAL-TEST', 'spool_number': 'SAME-DRAWING-NUMBER',
                        'lines': []}, version=1,
            created_by=BADGES['handler'], updated_by=BADGES['handler']))
        session.flush()
        session.add_all(module.SpoolBomMaterial(spool_id=item_id, piece_key=key,
            updated_by=BADGES['handler']) for key in keys)
        session.commit()


def receiving_decision(api, item_id, kind='material', piece='piece-a', result='Fail', version=1):
    receiving = importlib.import_module('spool_receiving')
    model = receiving.SpoolMaterialInspection if kind == 'material' else receiving.SpoolArrivalInspection
    with api.session_factory() as session:
        values = {'spool_id': item_id, 'version': version, 'result': result,
            'actor': BADGES['inspector'], 'at': BASE + dt.timedelta(minutes=version),
            'reference': 'RECEIVING-REFERENCE', 'notes': 'Damaged material requires correction',
            'basis_sha256': str(version) * 64,
            'basis': {'material': {'piece_key': piece, 'piece_identifier': item_id + '/MAT-' + piece}}}
        if kind == 'material':
            values.update(piece_key=piece, check_code='QA-001')
        else:
            values['checks'] = {'identity': True, 'bom': True, 'condition': False}
        row = model(**values)
        session.add(row)
        session.commit()
        return row.id


def board(api, **kwargs):
    response = api.get(PATH, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def by_spool(response):
    return {row['item_id']: row for row in response['spools']}


def test_auth_and_no_false_failures_from_baselines_missing_documents_or_admin_release(api):
    assert api.get(PATH, role=None).status_code == 401
    _, _, spools = family(api)
    flow = importlib.import_module('flow')
    with api.session_factory() as session:
        for identifier in spools:
            item = session.get(api.application.Item, identifier)
            item.released = True
            plan = session.get(flow.FlowPlan, identifier)
            plan.baseline_step, plan.current_step, plan.status = 16, None, 'admin_released'
        session.commit()
    result = board(api, role='handler')
    assert result['spools'] == []
    assert result['totals'] == {'spools': 0, 'failures': 0, 'needs_rework': 0,
                                'awaiting_reinspection': 0, 'return_required': 0}


def test_individual_spools_and_component_failures_keep_exact_identity_and_return_position(api):
    flow = importlib.import_module('flow')
    project, _, spools = family(api)
    first_id = failure(api, spools[0], 11)
    second_id = failure(api, spools[1], 15)
    component_id = 'FAIL-COMPONENT'
    with api.session_factory() as session:
        session.add(api.application.Item(id=component_id, description='Local component',
            kind='Part', project=project, handler=BADGES['handler'], location='Local receiving', welds_required=0))
        session.flush()
        session.add(flow.ComponentLink(component_id=component_id, spool_id=spools[0],
            assigned_by=BADGES['handler']))
        session.add(flow.FlowPlan(item_id=component_id, catalog_version=flow.VERSION,
            route='component', current_step=2, status='active', baseline_step=1,
            started_by=BADGES['admin']))
        session.commit()
    failure(api, component_id, 2)
    rows = by_spool(board(api))
    assert set(rows) == set(spools)
    assert rows[spools[0]]['qr_alias'] != rows[spools[1]]['qr_alias']
    fitup = next(row for row in rows[spools[0]]['failures'] if row['id'] == f'flow:{first_id}')
    weld = rows[spools[1]]['failures'][0]
    assert fitup['inspection_key'] == '002' and fitup['title'] == 'QA/QC-002 - Isometric Dimensions Test'
    assert fitup['return_station'] == {'id': 'fit_up', 'label': 'Fit-up'}
    assert fitup['return_step'] == 10 and 'fitup_welder' in fitup['return_roles']
    assert weld['id'] == f'flow:{second_id}' and weld['inspection_key'] == '003'
    assert weld['return_step'] == 14 and 'process_welder' in weld['return_roles']
    assert weld['return_station']['id'] == 'welding'
    assert fitup['status'] == weld['status'] == 'needs_rework'
    component = next(row for row in rows[spools[0]]['failures'] if row['scope'] == 'component')
    assert component['inspection_key'] == '001'
    assert component['open_kind'] == 'flow' and component['open_item_id'] == component_id
    assert component['return_station']['id'] == 'inventory'


def test_real_correction_remains_outstanding_until_qa_closes_the_finding(api):
    flow = importlib.import_module('flow')
    _, _, spools = family(api, count=1)
    identifier = spools[0]
    finding = failure(api, identifier, 11)
    correction(api, identifier, finding + 100, 10)
    correction(api, identifier, finding, 14)
    assert board(api)['spools'][0]['failures'][0]['correction'] is None
    corrected_id = correction(api, identifier, finding, 10)
    with api.session_factory() as session:
        session.get(flow.FlowPlan, identifier).current_step = 11
        session.commit()
    result = board(api)['spools'][0]['failures'][0]
    assert result['status'] == 'awaiting_reinspection'
    assert result['correction']['event_id'] == corrected_id
    assert result['correction']['description'] == 'Completed the documented repair'
    assert result['reason'] == 'Actual recorded defect at step 11'
    with api.session_factory() as session:
        row = session.get(flow.FlowException, finding)
        row.closed_at, row.closed_by, row.resolution = BASE + dt.timedelta(hours=1), BADGES['inspector'], 'QA reinspection accepted'
        session.commit()
    assert board(api)['spools'] == []


def test_released_spool_retains_unresolved_defect_and_removed_or_resolved_records_disappear(api):
    flow = importlib.import_module('flow')
    removals = importlib.import_module('removals')
    _, _, spools = family(api, count=3)
    finding = failure(api, spools[0], 15)
    failure(api, spools[1], 11, closed=True)
    failure(api, spools[2], 15)
    with api.session_factory() as session:
        session.get(api.application.Item, spools[0]).released = True
        plan = session.get(flow.FlowPlan, spools[0])
        plan.current_step, plan.status = None, 'admin_released'
        session.add(removals.RecordRemoval(kind='item', record_id=spools[2], removed=True,
            version=1, batch_id='LOCAL-REMOVAL', reason='Local removed fixture',
            root_kind='item', root_id=spools[2], changed_by=BADGES['admin']))
        session.commit()
    result = board(api)
    assert [row['item_id'] for row in result['spools']] == [spools[0]]
    remaining = result['spools'][0]['failures'][0]
    assert remaining['id'] == f'flow:{finding}'
    assert remaining['status'] == 'return_required' and remaining['source_released']


def test_latest_piece_and_arrival_failures_work_without_travelers_and_ignore_basis_changes(api):
    boms = importlib.import_module('spool_boms')
    _, _, spools = family(api, flows=False)
    material_register(api, spools[0])
    material_register(api, spools[1])
    failed_piece = receiving_decision(api, spools[0])
    receiving_decision(api, spools[0], piece='piece-b')
    receiving_decision(api, spools[0], piece='piece-b', result='Pass', version=2)
    receiving_decision(api, spools[1])
    receiving_decision(api, spools[1], result='Pass', version=2)
    receiving_decision(api, spools[0], kind='arrival')
    receiving_decision(api, spools[0], kind='arrival', result='Pass', version=2)
    arrival_id = receiving_decision(api, spools[1], kind='arrival')
    with api.session_factory() as session:
        trace = session.get(boms.SpoolBomTrace, spools[0])
        trace.version, trace.source_sha256 = 2, 'z' * 64
        session.commit()
    rows = by_spool(board(api))
    assert len(rows[spools[0]]['failures']) == len(rows[spools[1]]['failures']) == 1
    piece = rows[spools[0]]['failures'][0]
    assert piece['id'] == f'material:{failed_piece}' and piece['inspection_key'] == '001'
    assert piece['piece_identifier'] == spools[0] + '/MAT-piece-a'
    assert piece['material_current'] and piece['routing_known']
    assert piece['open_kind'] == 'material' and piece['open_item_id'] == spools[0]
    assert 'handler' in piece['return_roles']
    assert rows[spools[1]]['failures'][0]['id'] == f'arrival:{arrival_id}'


def test_receiving_correction_does_not_clear_fail_and_archived_failed_piece_stays_explicit(api):
    _, _, spools = family(api, count=1, flows=False)
    material_register(api, spools[0])
    finding = receiving_decision(api, spools[0])
    with api.session_factory() as session:
        session.add(api.application.Audit(item_id=spools[0], actor=BADGES['handler'],
            at=BASE + dt.timedelta(hours=1), event='QA001_REWORK_RECORDED',
            details={'inspection_kind': 'material', 'failure_id': finding,
                'failure_version': 1, 'description': 'Replaced the damaged pipe section',
                'reference': 'RECEIVING-REPAIR'}))
        session.commit()
    corrected = board(api)['spools'][0]['failures'][0]
    assert corrected['status'] == 'awaiting_reinspection'
    assert corrected['correction']['actor'] == BADGES['handler']
    assert corrected['correction']['reference'] == 'RECEIVING-REPAIR'
    boms = importlib.import_module('spool_boms')
    with api.session_factory() as session:
        session.delete(session.get(boms.SpoolBomMaterial, (spools[0], 'piece-a')))
        session.commit()
    archived = board(api)['spools'][0]['failures'][0]
    assert not archived['material_current'] and not archived['routing_known']
    assert 'earlier BOM revision' in archived['routing_note']
    receiving_decision(api, spools[0], result='Pass', version=2)
    assert board(api)['spools'] == []


def _testing_context(flow, *, kind, label, location, badge):
    version = flow.LEGACY_VERSION
    return {'testing_protocol': 'CLM-TEST-v1', 'test_kind': kind,
        'testing_phase': 'ndt_qa' if kind == 'ndt' else 'pressure_qa',
        'testing_cycle': 1, 'testing_attempt': 1, 'testing_action': 'review',
        'step_definition': {**flow.LEGACY_STEP_BY_NUMBER[18],
            'testing_phase': 'ndt_qa' if kind == 'ndt' else 'pressure_qa',
            'title': label},
        'definition_version': version,
        'return_to': {'sender_badge': badge, 'sender_name': 'Recorded test custodian',
                      'location_id': location, 'location_label': location + ' recorded station'}}


def test_assembly_failures_affect_exact_children_and_preserve_legacy_pressure_final_meanings(api):
    flow = importlib.import_module('flow')
    _, assembly, spools = family(api, legacy=True)
    family(api, prefix='UNRELATED', count=1)
    ndt_id = failure(api, assembly, 18, context=_testing_context(flow,
        kind='ndt', label='QA/QC-004 - Previous NDT name', location='ndt-bay', badge=BADGES['ndt']))
    pressure_id = failure(api, assembly, 18, context=_testing_context(flow,
        kind='pressure', label='QA/QC-004 - Previous Pressure name', location='hydro-bay',
        badge=BADGES['pressure_testing_technician']))
    final_id = failure(api, assembly, 22)
    correction(api, assembly, pressure_id, 17, context={
        'testing_protocol': 'CLM-TEST-v1', 'testing_action': 'correct', 'test_kind': 'pressure',
        'testing_cycle': 1, 'testing_attempt': 1,
        'correction': {'exception_id': pressure_id, 'resolution': 'Repaired the pressure-test connection'}})
    result = board(api)
    assert result['totals']['spools'] == 2 and result['totals']['failures'] == 3
    assert {row['item_id'] for row in result['spools']} == set(spools)
    for row in result['spools']:
        findings = {finding['inspection_key']: finding for finding in row['failures']}
        assert set(findings) == {'004', '005', '006'}
        assert all(finding['scope'] == 'assembly' and finding['source_item_id'] == assembly
                   and finding['open_item_id'] == assembly for finding in findings.values())
        ndt, pressure, final = (findings[key] for key in ('004', '005', '006'))
        assert ndt['id'] == f'flow:{ndt_id}' and ndt['return_roles'] == ['admin', 'ndt']
        assert pressure['id'] == f'flow:{pressure_id}' and pressure['saved_qa_code'] == 'QA-004'
        assert pressure['display_qa_code'] == 'QA/QC-005' and pressure['testing_phase'] == 'pressure_qa'
        assert pressure['return_station']['id'] == 'hydro-bay'
        assert pressure['return_employee']['badge'] == BADGES['pressure_testing_technician']
        assert pressure['status'] == 'awaiting_reinspection'
        assert final['id'] == f'flow:{final_id}' and final['saved_qa_code'] == 'QA-005'
        assert final['display_qa_code'] == 'QA/QC-006' and final['return_station']['id'] == 'blast_paint'
        assert final['return_roles'] == ['admin', 'painter']


def test_unknown_retained_testing_never_uses_current_phase_or_old_code_to_guess_test_type(api):
    flow = importlib.import_module('flow')
    _, assembly, _ = family(api, count=1, legacy=True)
    failure(api, assembly, 18)
    with api.session_factory() as session:
        session.add(flow.FlowTestingState(item_id=assembly, protocol='CLM-TEST-v1',
            cycle=2, attempt=1, phase='pressure_qa', test_kind='pressure',
            pending_exception_ids=[], pending_exception_kinds={}))
        session.commit()
    finding = board(api)['spools'][0]['failures'][0]
    assert finding['inspection_key'] == 'legacy_testing' and finding['qa_code'] is None
    assert finding['saved_qa_code'] == 'QA-004'
    assert finding['return_station'] is None and finding['return_employee'] is None
    assert not finding['routing_known'] and finding['return_roles'] == []


def test_nested_assembly_scope_propagates_independently_of_parent_loading_order(api):
    flow = importlib.import_module('flow')
    tracking = importlib.import_module('tracking')
    project, inner, spools = family(api, prefix='Z-INNER', count=1)
    outer = 'A-OUTER-ASSEMBLY'
    direct = 'DIRECT-OUTER-SPOOL'
    with api.session_factory() as session:
        session.add_all(api.application.Item(id=identifier, description=identifier,
            kind='Assembly' if identifier == outer else 'Spool', project=project,
            handler=BADGES['handler'], location='Local nested test bay', welds_required=0) for identifier in (outer, direct))
        session.flush()
        session.add_all(tracking.SpoolPlan(item_id=identifier, project_id=project,
            assembly_id=outer if identifier == direct else None, planned_welds=0,
            zero_weld_reason='Local nested fixture', created_by=BADGES['admin'])
            for identifier in (outer, direct))
        session.get(tracking.SpoolPlan, inner).assembly_id = outer
        session.add(flow.FlowPlan(item_id=outer, catalog_version=flow.VERSION,
            route='assembly', current_step=22, status='active', baseline_step=17,
            started_by=BADGES['admin']))
        session.commit()
    failure(api, outer, 22)
    result = board(api)
    assert {row['item_id'] for row in result['spools']} == {spools[0], direct}
    assert all(row['failures'][0]['source_item_id'] == outer for row in result['spools'])
    assert result['totals']['failures'] == 1


def test_projection_is_batched_read_only_and_never_autoflushes_pending_writes(api):
    engine = api.session_factory.kw['bind']
    statements = []
    def collect(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', collect)
    try:
        counts = []
        for prefix, count in (('ONE', 1), ('MORE', 12)):
            _, _, spools = family(api, prefix=prefix, count=count)
            for identifier in spools:
                failure(api, identifier, 11)
                material_register(api, identifier)
                receiving_decision(api, identifier)
            statements.clear()
            result = board(api, role='painter')
            counts.append(sum(statement.lstrip().upper().startswith('SELECT') for statement in statements))
            assert not any(statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
                           or 'FOR UPDATE' in statement.upper() for statement in statements)
        # The existing station resolver adds 13 bounded reads for this one
        # assembly level; increasing failed-spool count adds no per-item read.
        assert counts[0] == counts[1] and counts[0] <= 27, counts
        assert result['totals']['spools'] == 13 and result['totals']['failures'] == 26
        from flow_failures import inspection_failure_board
        with api.session_factory() as session:
            pending = api.application.Item(id='PENDING-NOT-WRITTEN', description='Pending caller mutation',
                kind='Spool', project='ONE-PROJECT', handler=BADGES['handler'], welds_required=0)
            session.add(pending)
            statements.clear()
            projected = inspection_failure_board(session)
            assert projected['totals'] == result['totals']
            assert pending in session.new
            assert not any(statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
                           for statement in statements)
            session.rollback()
    finally:
        event.remove(engine, 'before_cursor_execute', collect)


def test_project_filter_returns_only_failed_spools_from_that_purchase_order_scope(api):
    project, _, spools = family(api, prefix='PROJECT-ONE', count=1)
    _, _, other = family(api, prefix='PROJECT-TWO', count=1)
    failure(api, spools[0], 11)
    failure(api, other[0], 15)
    result = board(api, params={'project_id': project})
    assert [row['item_id'] for row in result['spools']] == spools


def test_registered_spool_without_tracking_plan_keeps_actual_po_and_assembly_identity(api):
    orders = importlib.import_module('orders')
    setup = importlib.import_module('order_setup')
    identities = importlib.import_module('order_spools')
    tracking = importlib.import_module('tracking')
    project, assembly, spools = family(api, count=1, flows=False)
    with api.session_factory() as session:
        session.add(orders.PurchaseOrder(project_id=project, purchase_order='CUSTOMER-PO-72',
            normalized_number='customer-po-72', created_by=BADGES['admin']))
        session.flush()
        session.add(orders.OrderGpn(id='NAMED-ASSEMBLY-DEFINITION', project_id=project,
            gpn='SEPARATE-GOOGLE-PART', normalized_gpn='separate-google-part',
            assembly_number='ASSEMBLY-NUMBER-31', normalized_assembly_number='assembly-number-31',
            created_by=BADGES['admin']))
        session.flush()
        session.add(orders.OrderAssembly(item_id=assembly, gpn_id='NAMED-ASSEMBLY-DEFINITION',
            assembly_part_number='ASSEMBLY-NUMBER-31-[001]', required_spools=1,
            created_by=BADGES['admin']))
        session.add(setup.OrderSpoolRequirement(id='DECLARED-SPOOL-LINE',
            gpn_id='NAMED-ASSEMBLY-DEFINITION', spool_number='SAME-DRAWING-NUMBER',
            normalized_number='same-drawing-number', quantity_per_assembly=1,
            created_by=BADGES['admin']))
        session.flush()
        session.add(identities.OrderSpool(item_id=spools[0], assembly_id=assembly,
            requirement_id='DECLARED-SPOOL-LINE', created_by=BADGES['admin']))
        session.delete(session.get(tracking.SpoolPlan, spools[0]))
        session.get(api.application.Item, spools[0]).project = 'Legacy free-text project'
        session.commit()
    receiving_decision(api, spools[0], kind='arrival')
    result = board(api, params={'project_id': project})
    assert len(result['spools']) == 1
    row = result['spools'][0]
    assert row['item_id'] == spools[0] and row['qr_alias'] == 'FAIL-COPY-[001]'
    assert row['project_id'] == project and row['purchase_order'] == 'CUSTOMER-PO-72'
    assert row['assembly_id'] == assembly and row['assembly_number'] == 'ASSEMBLY-NUMBER-31-[001]'
    assert row['assembly_number'] != 'SEPARATE-GOOGLE-PART'
    assert row['failures'][0]['inspection_key'] == '001'


def test_failed_spool_color_uses_recorded_station_not_failure_or_return_step(api, monkeypatch):
    stations = importlib.import_module('flow_stations')
    _, _, spools = family(api, count=3)
    failure(api, spools[0], 11)
    failure(api, spools[1], 15)
    with api.session_factory() as session:
        session.add(api.application.Audit(item_id=spools[0], actor=BADGES['handler'],
            at=BASE + dt.timedelta(hours=2), event='TRANSFER', details={
                'from': {'location_id': 'inventory', 'location': 'Inventory'},
                'to': {'location_id': 'blast_paint', 'location': 'Paint',
                       'handler': BADGES['handler']}, 'location_changed': True}))
        session.commit()
    loaded = []
    original = stations.station_positions
    def capture(session, items, **kwargs):
        items = list(items)
        loaded.extend(item.id for item in items)
        return original(session, items, **kwargs)
    monkeypatch.setattr(stations, 'station_positions', capture)
    rows = by_spool(board(api))
    assert set(loaded) == set(spools[:2])
    assert rows[spools[0]]['flow_stage']['key'] == 'paint'
    assert rows[spools[0]]['flow_stage']['color'] == 'pink'
    assert rows[spools[0]]['flow_stage']['position_source'] == 'transfer'
    assert rows[spools[0]]['failures'][0]['return_station']['id'] == 'fit_up'
    assert rows[spools[1]]['flow_stage']['key'] == 'inventory'
    assert rows[spools[1]]['flow_stage']['color'] == 'black'
