"""Read-only spool exports retain pieces, repeats, failures and true time scopes."""
import datetime as dt
import importlib
import io
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import BADGES
from test_exports import Workbook, snapshot, NS, MIME
from test_order_labels import generate, labels, public_qr_url
from test_order_setup import create_setup


WHEN=dt.datetime(2024,1,2,10,0,0,tzinfo=dt.timezone.utc)


def seed(api):
    setup=create_setup(api,purchase_order='000-EXPORT-PO',assemblies=[{
        'gpn':'000007','assembly_number':'000123','assembly_quantity':1,
        'spools':[{'spool_number':'EXPORT-SP-01','quantity_per_assembly':2,'welds_per_spool':2}]}])
    project=setup['order']['project_id']
    generate(api,project)
    spools=labels(api,project)['items']
    a,b=[row['id'] for row in spools]
    models=importlib.import_module('spool_boms')
    tracking=importlib.import_module('tracking')
    order_spools=importlib.import_module('order_spools')
    flow=importlib.import_module('flow')
    production=importlib.import_module('production')
    receiving=importlib.import_module('spool_receiving')
    dossier=importlib.import_module('dossier')
    hour=lambda n:WHEN+dt.timedelta(hours=n)
    with api.session_factory() as s:
        parent=s.get(order_spools.OrderSpool,a).assembly_id
        definition={'catalog_id':'synthetic','spool_number':'EXPORT-SP-01','revision':'A',
            'lines':[{'item':'1','piece_key_prefix':'PIECE','quantity':2,'part_number':'000042',
                      'description':'=HYPERLINK("https://example.invalid","literal")','unit':'EA','material':'Carbon steel'}],
            'traceable':True,'_source':{'kind':'synthetic','sha256':'a'*64}}
        s.add(models.SpoolBomTrace(spool_id=a,catalog_id='synthetic',spool_number='EXPORT-SP-01',source_sha256='a'*64,
            definition=definition,version=1,created_by=BADGES['admin'],updated_by=BADGES['admin'],created_at=WHEN,updated_at=WHEN))
        s.flush()
        s.add_all([models.SpoolBomMaterial(spool_id=a,piece_key=f'PIECE-{n}',supplier='Synthetic supplier',supplier_piece_id=f'SUP-{n}',
            heat_number=f'0000{n}',mtr_reference=f'00009{n}',notes='Individual piece '+str(n),updated_by=BADGES['admin'],updated_at=WHEN)
            for n in (1,2)])
        s.add(models.SpoolBomEvent(spool_id=a,version=1,actor=BADGES['admin'],at=WHEN,reason='Synthetic imported source',
            changes=[{'piece_key':'PIECE-1','before':{'heat_number':''},'after':{'heat_number':'00001'}}]))
        for version,result in [(1,'Fail'),(2,'Pass')]:
            s.add(receiving.SpoolMaterialInspection(spool_id=a,piece_key='PIECE-1',version=version,check_code='QA-001',result=result,
                actor=BADGES['inspector'],at=hour(version),reference='REPORT-'+str(version),notes='Keep historical '+result,
                basis_sha256='b'*64,basis={'synthetic':True,'heat_number':'00001'}))
        welds=list(s.scalars(select(tracking.Weld).where(tracking.Weld.item_id==a).order_by(tracking.Weld.number)))
        w=welds[0]
        w.component_a='PIECE-1';w.component_b='PIECE-2';w.heat_a='00001';w.mtr_a='000091'
        w.heat_b='CONFLICT';w.mtr_b='000092';w.wps='WPS-TEST';w.wps_revision='C';w.cycle=2
        s.add_all([tracking.WeldWork(weld_id=w.id,cycle=1,operation='root',actor=BADGES['process_welder'],at=hour(1),notes='First root event'),
            tracking.WeldWork(weld_id=w.id,cycle=2,operation='root',actor=BADGES['process_welder'],at=hour(4),notes='Second root after repair'),
            tracking.WeldRepair(weld_id=w.id,cycle=2,reason='Synthetic root defect retained',opened_by=BADGES['inspector'],opened_at=hour(3))])
        root=tracking.WeldRequirement(item_id=a,weld_id=w.id,code='ROOT_VISUAL',label='Root visual inspection',stage='after_welding',
            status='pending',cycle=7,created_by=BADGES['admin'],owner_role='inspector',created_at=WHEN,updated_at=WHEN)
        s.add(root);s.flush()
        s.add_all([tracking.RequirementEvidence(requirement_id=root.id,cycle=6,reference='ROOT-FAIL',notes='Failed root retained',result='Fail',actor=BADGES['inspector'],at=hour(2)),
            tracking.RequirementEvidence(requirement_id=root.id,cycle=7,reference='ROOT-PASS',notes='Later root evidence',result='Pass',actor=BADGES['inspector'],at=hour(5))])
        s.add(flow.FlowPlan(item_id=a,route='spool',current_step=11,status='active',version=4,expected_children=0,baseline_step=10,
            baseline_reference='SYNTHETIC-BASELINE',baseline_reason='Prior steps intentionally unrecorded',material_reference='BOM-SYNTHETIC',
            started_by=BADGES['admin'],started_at=WHEN,step_entered_at=hour(3),updated_at=hour(3)))
        for sequence,action,step,t,data in [(1,'start',10,0,{}),(2,'advance',10,1,{'next_step':11}),
                                          (3,'fail',11,2,{'return_step':10}),(4,'advance',10,3,{'next_step':11})]:
            s.add(flow.FlowEvent(item_id=a,sequence=sequence,action=action,step=step,actor=BADGES['inspector'],at=hour(t),
                reference='FLOW-'+str(sequence),notes='Synthetic '+action,data=data))
        for sequence,event,step,t in [(1,'start',10,0),(2,'move',11,1),(3,'move',10,2),(4,'move',11,3)]:
            s.add(production.SpoolProcessEvent(item_id=a,sequence=sequence,event=event,process_key=f'clm_{step:02}',process_name='Step '+str(step),
                actor=BADGES['admin'],at=hour(t),notes='Synthetic timer event'))
        s.add_all([production.SpoolProcessEvent(item_id=parent,sequence=1,event='start',process_key='clm_17',process_name='Assembly testing',actor=BADGES['admin'],at=hour(4),notes='Shared assembly timing'),
            production.SpoolProcessEvent(item_id=parent,sequence=2,event='finish',process_key='clm_17',process_name='Assembly testing',actor=BADGES['admin'],at=hour(6),notes='Shared assembly timer finished')])
        s.add(flow.FlowException(item_id=a,step=11,return_step=10,reason='Synthetic failed fit-up dimensions',reference='DIM-FAIL',
            opened_by=BADGES['inspector'],opened_at=hour(2),closed_by=BADGES['inspector'],closed_at=hour(5),resolution='Synthetic documented correction'))
        s.add(api.application.Rework(item_id=a,kind='Weld correction',reason='Physical correction only',assigned=BADGES['process_welder'],
            opened_at=hour(2),closed_by=BADGES['handler'],closed_at=hour(4),close_notes='Physical correction completed; QA still required'))
        s.add(tracking.TrackingHold(item_id=a,reason='Synthetic documentation hold',opened_by=BADGES['admin'],opened_at=hour(1),
            closed_by=BADGES['supervisor'],closed_at=hour(4),close_notes='Hold removed, no inspection claim'))
        s.add(dossier.DossierProject(project_id=project,manufacturer_name='Synthetic CLM',manufacturer_contact='Synthetic contact',
            purchase_order='000-EXPORT-PO',source_reference='Synthetic packet source',expected_packets=2,
            created_by=BADGES['admin'],created_at=WHEN,updated_at=WHEN))
        s.flush()
        s.add_all([dossier.DossierReview(project_id=project,item_id=a,code='materials',decision=decision,
            reference='PACKET-'+decision,notes='Keep every packet review',fingerprint='c'*64,snapshot={'synthetic':True},
            actor=BADGES['inspector'],at=hour(n)) for n,decision in [(5,'rejected'),(6,'accepted')]])
        for n,stage in enumerate(['floor','welding','floor']):
            s.add(api.application.Audit(item_id=a,actor=BADGES['handler'],event='TRANSFER',at=hour(n),
                details={'location_changed':True,'from':{'location_id':'inventory' if n==0 else ['floor','welding'][n-1]},
                         'to':{'location_id':stage,'location':stage,'handler':BADGES['handler']},'notes':'Synthetic physical movement'}))
        s.commit()
    return {'project':project,'spools':spools,'a':a,'b':b,'parent':parent}


def table_rows(book,sheet,first_header):
    rows=book.sheets[sheet]
    start=next(i for i,row in enumerate(rows) if row.get(1) and row[1].value==first_header)
    headers=[rows[start][n].value for n in sorted(rows[start])]
    result=[]
    for row in rows[start+1:]:
        if len(row)<=1:
            break
        result.append({header:row.get(i).value if row.get(i) else None for i,header in enumerate(headers,1)})
    return result


def test_spool_record_download_preserves_scope_history_and_native_dates(api,tmp_path,public_qr_url):
    data=seed(api)
    before=snapshot(api)
    exporter=importlib.import_module('spool_records')
    file,name,media=exporter.build_export(api.session_factory.kw['bind'],[data['a']],WHEN+dt.timedelta(hours=75))
    try:
        payload=file.read()
    finally:
        file.close()
    (tmp_path/'synthetic-spool-record.xlsx').write_bytes(payload)
    assert media==MIME and '..' not in name and '/' not in name
    book=Workbook(payload)
    assert list(book.sheets)==list(exporter.SHEET_NAMES)
    identity={row[1].value:row[2].value for row in book.sheets['Spool Record'] if 1 in row and 2 in row}
    assert identity['GPN']=='000007' and identity['Assembly number']=='000123'
    assert identity['Permanent spool ID']==data['a'] and identity['Permanent assembly ID']==data['parent']
    assert identity['Permanent GPN record ID']
    materials=table_rows(book,'Material Traceability','Piece key')
    assert [(x['Piece key'],x['Heat number'],x['MTR reference']) for x in materials]==[('PIECE-1','00001','000091'),('PIECE-2','00002','000092')]
    inspections=table_rows(book,'Inspection History','Record ID')
    assert [x['Saved result'] for x in inspections]==['Fail','Pass']
    assert inspections[0]['Current validity']=='Historical; superseded'
    assert inspections[1]['Current validity']=='Current needs reinspection'
    route=table_rows(book,'24-step Route','Step')
    assert len([row for row in route if row['Step']==10])==2
    eleven=[row for row in route if row['Step']==11]
    assert [row['Status'] for row in eleven]==['Failed','In progress']
    assert eleven[-1]['Departed (UTC)'] is None
    assert eleven[-1]['Elapsed HH:MM:SS']==3  # 72 hours as native Excel days.
    assert route[0]['Entered (UTC)'] is None and route[0]['Elapsed HH:MM:SS'] is None
    assert any(row['Record scope']=='Shared parent assembly: '+data['parent'] for row in route)
    welds=table_rows(book,'Weld Register','Weld')
    assert len(welds)==2 and welds[0]['Root visual status']=='ROOT_VISUAL: pending'
    work=table_rows(book,'Work and Rework','Event ID')
    assert [row['Cycle'] for row in work[:2]]==[1,2]
    assert all(row['Started (UTC)'] is None and row['Elapsed HH:MM:SS'] is None for row in work[:2])
    assert [row['Cycle'] for row in work[2:]]==['Requirement cycle 6','Requirement cycle 7']
    reworks=table_rows(book,'Work and Rework','Rework ID')
    assert any(row['Defect / reason']=='Synthetic root defect retained' for row in reworks)
    assert any(row['Corrective work']=='Synthetic documented correction' for row in reworks)
    for row in reworks:
        if row['Rework ID'].startswith(('REWORK-','HOLD-')):
            assert row['QA/QC reviewer'] is None and row['Reinspection result'] is None
    closures=table_rows(book,'Work and Rework','Record ID')
    assert all(row['Closed (UTC)'] is not None and row['Closed by badge'] for row in closures)
    packet=next(i for i,row in enumerate(book.sheets['Inspection History']) if row.get(1) and row[1].value=='Job Packet review history')
    assert [row[5].value for row in book.sheets['Inspection History'][packet+2:packet+4]]==['rejected','accepted']
    assert b'CONFLICT' in book.xml and b'saved weld value differs from current piece' in book.xml
    assert b'formatCode="[h]:mm:ss"' in book.xml
    assert not any('HYPERLINK' in (f.text or '') for f in book.formulas)
    assert b'=HYPERLINK' in book.xml and b'pin_hash' not in book.xml
    assert snapshot(api)==before


def test_authenticated_single_and_multi_downloads_and_invalid_selection(api,public_qr_url):
    data=seed(api)
    before=snapshot(api)
    selected=api.get('/api/spool-records/spools',params={'project_id':data['project']})
    assert selected.status_code==200,selected.text
    assert {row['item_id'] for row in selected.json()['spools']}=={data['a'],data['b']}
    single=api.get('/api/spool-records/spools/'+data['a']+'/record.xlsx',role='inspector')
    assert single.status_code==200,single.text
    assert single.headers['content-type'].split(';')[0]==MIME
    assert int(single.headers['content-length'])==len(single.content)
    assert 'no-store' in single.headers['cache-control']
    multiple=api.post('/api/spool-records/export',{'item_ids':[data['a'],data['b']]})
    assert multiple.status_code==200,multiple.text
    with zipfile.ZipFile(io.BytesIO(multiple.content)) as archive:
        assert len(archive.namelist())==2
        assert all(len(Workbook(archive.read(name)).sheets)==7 for name in archive.namelist())
    assert api.post('/api/spool-records/export',{'item_ids':[]}).status_code==422
    assert api.post('/api/spool-records/export',{'item_ids':[data['a'],data['a']]}).status_code==422
    assert api.post('/api/spool-records/export',{'item_ids':[data['a'],'does-not-exist']}).status_code==404
    assert api.post('/api/spool-records/export',{'item_ids':[data['parent']]}).status_code==404
    assert api.get('/api/spool-records/spools',role=None).status_code==401
    assert api.get('/api/spool-records/spools/'+data['a']+'/record.xlsx',role=None).status_code==401
    assert snapshot(api)==before


def test_weld_mapping_never_guesses_or_crosses_parent_scope(api,public_qr_url):
    data=seed(api)
    module=importlib.import_module('spool_records')
    with api.session_factory() as s:
        record=module._load_record(s,data['a'],WHEN+dt.timedelta(hours=75))
        weld=record['welds'][0]
        fields,status=module._weld_mapping(weld,record['state']['materials'],record)
        assert fields[:3]==['PIECE-1','00001','000091']
        assert fields[3:]==['PIECE-2','CONFLICT','000092']
        assert 'differs' in status
        weld.component_a='An ambiguous description';weld.heat_a='';weld.mtr_a=''
        fields,status=module._weld_mapping(weld,record['state']['materials'],record)
        assert fields[1:3]==['',''] and 'not verified' in status
        weld.component_a='PIECE-1';weld.item_id=data['parent']
        fields,status=module._weld_mapping(weld,record['state']['materials'],record)
        assert fields[1:3]==['',''] and 'not verified' in status


@pytest.mark.parametrize('step',[2,18])
def test_same_step_failure_is_not_reused_by_next_visit(step,application):
    module=importlib.import_module('spool_records')
    identity='COMP' if step==2 else 'ASM'
    t1=WHEN+dt.timedelta(hours=1)
    visits=[]
    # Two failures at the same recorded time each finish exactly one visit.
    for n,start,end in [(1,WHEN,t1),(2,t1,t1),(3,t1,None)]:
        visits.append({'id':n,'process_key':f'clm_{step:02}','started_at':start.isoformat(),
            'ended_at':end.isoformat() if end else None,'status':'finished' if end else 'running',
            'started_by':'QA','elapsed_seconds':3600 if n!=2 else 0,'active_seconds':3600 if n!=2 else 0,'paused_seconds':0})
    record={'item':SimpleNamespace(id='SP'), 'parent':'ASM','components':['COMP'] if step==2 else [],
        'timers':{'SP':{'visits':[]},'ASM':{'visits':visits if step==18 else []},'COMP':{'visits':visits if step==2 else []}},
        'names':{'QA':'Synthetic QA'},'flow':[SimpleNamespace(id=n,item_id=identity,step=step,action='fail',actor='QA',at=t1,
            reference='FAIL-'+str(n),notes='Self-return failure',data={}) for n in (1,2)]}
    rows=[row for row in module._route_rows(record) if row[0]==step]
    assert [row[9] for row in rows]==['Failed','Failed','In progress']
    assert [row[10] for row in rows]==['FAIL-1','FAIL-2','']


def test_root_visual_label_requires_explicit_inspection_identity(application):
    from spool_records import _is_root
    assert _is_root(SimpleNamespace(code='ROOT_VISUAL',label='Approved root checkpoint'))
    assert _is_root(SimpleNamespace(code='QA_14',label='Root pass visual inspection'))
    assert not _is_root(SimpleNamespace(code='CAUSE',label='Visual root cause investigation'))
    assert not _is_root(SimpleNamespace(code='GENERAL_VT',label='Final visual examination'))


def seed_testing_history(api,data,*,decision='YES'):
    """Saved protocol events, including distinct test and QA evidence links."""
    flow=importlib.import_module('flow')
    testing=importlib.import_module('flow_testing')
    production=importlib.import_module('production')
    parent=data['parent']
    def hour(n):
        return WHEN+dt.timedelta(hours=n)
    # step, phase, action, kind, attempt, result, actor role, next phase
    rows=[(17,'decision','decision',None,1,None,'handler','ndt' if decision=='YES' else 'not_required')]
    if decision=='YES':
        rows += [
            (17,'ndt','start','ndt',1,None,'ndt','ndt'),
            (17,'ndt','complete','ndt',1,'FAIL','admin','ndt_qa'),
            (18,'ndt_qa','review','ndt',1,'FAIL','inspector','ndt_rework'),
            (17,'ndt_rework','correct','ndt',1,None,'ndt','ndt'),
            (17,'ndt','start','ndt',2,None,'ndt','ndt'),
            (17,'ndt','complete','ndt',2,'PASS','ndt','ndt_qa'),
            (18,'ndt_qa','review','ndt',2,'PASS','inspector','floor_before_pressure'),
            (19,'floor_before_pressure','handoff','ndt',2,None,'handler','pressure_test'),
            (17,'pressure_test','start','pressure',1,None,'pressure_testing_technician','pressure_test'),
            (17,'pressure_test','complete','pressure',1,'PASS','pressure_testing_technician','pressure_qa'),
            (18,'pressure_qa','review','pressure',1,'PASS','inspector','floor_before_paint'),
            (19,'floor_before_paint','handoff','pressure',1,None,'handler','complete'),
        ]
    reports={}
    review_ids={}
    ids=[]
    exception_id=None
    with api.session_factory() as s:
        s.add(flow.FlowPlan(item_id=parent,route='assembly',current_step=20,status='active',version=len(rows)+1,
            expected_children=2,baseline_step=17,started_by=BADGES['admin'],started_at=hour(9),
            step_entered_at=hour(9+len(rows)),updated_at=hour(9+len(rows))))
        s.add(production.SpoolProcessEvent(item_id=parent,sequence=3,event='start',process_key='clm_17',
            process_name='Determine testing requirements',actor=BADGES['admin'],at=hour(9),notes='Synthetic phase timer'))
        for n,(step,phase,action,kind,attempt,result,role,next_phase) in enumerate(rows,1):
            at=hour(9+n)
            detail={'testing_protocol':testing.PROTOCOL,'testing_cycle':1,'testing_phase':phase,
                'testing_action':action,'test_kind':kind,'testing_attempt':attempt,'test_result':result,
                'phase_only':action in ('decision','start','correct'),'next_phase':next_phase,
                'step_definition':{'number':step,'title':f'Saved {kind or "testing"} {action}, attempt {attempt}'}}
            if action=='decision':
                detail['testing_decision']=decision
                if decision=='NO':
                    detail['not_required_steps']=[18,19]
            if action=='review':
                detail['report']=dict(reports[(kind,attempt)])
            elif action=='complete':
                detail['report']={'result':result,'reference':f'{kind}-{action}-{attempt}-{result}',
                    'basis_sha256':'a'+str(attempt)*63}
            if result=='FAIL' and action=='review':
                exception=flow.FlowException(item_id=parent,step=18,return_step=17,
                    reason='Synthetic failed NDT requires actual correction',reference='NDT-QA-FAIL',
                    opened_by=BADGES['inspector'],opened_at=at,closed_by=BADGES['inspector'],
                    closed_at=hour(17),resolution='Corrected, retested and reviewed')
                s.add(exception);s.flush();exception_id=exception.id
                detail.update(exception_id=exception.id,return_step=17,
                    return_to={'sender_badge':BADGES['ndt'],'sender_name':'Saved original NDT employee',
                               'location_id':'testing','location_label':'Testing'})
            if action=='correct':
                detail['correction']={'exception_id':exception_id,'attempt':attempt,'test_kind':kind,
                    'reference':'NDT-CORRECTION-REF','resolution':'Removed defect and completed required correction',
                    'actor':BADGES[role],'at':at.isoformat()}
            if action=='review' and result=='PASS':
                detail['closed_exception_ids']=[exception_id] if kind=='ndt' else []
                detail['remaining_exception_ids']=[]
                detail['remaining_exception_kinds']={}
                if kind=='ndt':
                    detail['ndt_accepted_basis']={'basis_sha256':'b'*64,
                        'report_event_id':reports[(kind,attempt)]['event_id']}
            if action in ('start','complete','handoff') or result=='FAIL' and action=='review':
                tester=BADGES['ndt' if kind=='ndt' else 'pressure_testing_technician']
                if action=='start':
                    sender,receiver,old,new=BADGES['handler'],tester,'floor','testing'
                elif action=='complete':
                    sender,receiver,old,new=tester,BADGES['inspector'],'testing','qa_test_results'
                elif action=='handoff':
                    sender,receiver,old,new=BADGES['inspector'],BADGES['handler'],'qa_test_results','floor'
                else:
                    sender,receiver,old,new=BADGES['inspector'],tester,'qa_test_results','testing'
                detail['handoff']={'from':{'location_id':old,'location':old},'to':{'location_id':new,'location':new},
                    'sender':{'badge':sender,'name':'Saved '+sender},'receiver':{'badge':receiver,'name':'Saved '+receiver},
                    'sender_badge':sender,'receiver_badge':receiver,'handoff_recorded_by':BADGES[role]}
            event=flow.FlowEvent(item_id=parent,sequence=n,action='fail' if action=='review' and result=='FAIL' else 'advance',
                step=step,actor=BADGES[role],at=at,reference=f'{kind or "DECISION"}-{action}-{attempt}-{result or decision}',
                notes='Synthetic '+action+' evidence',data=detail)
            s.add(event);s.flush();ids.append(event.id)
            if action=='review' and result=='PASS':
                review_ids[(kind,attempt)]=event.id
            if action=='complete':
                reports[(kind,attempt)]={'test_kind':kind,'attempt':attempt,'cycle':1,'result':result,
                    'reference':event.reference,'notes':event.notes,'actor':event.actor,'at':at.isoformat(),
                    'event_id':event.id,'basis_sha256':'a'+str(attempt)*63}
            next_step=rows[n][0] if n<len(rows) else 20
            next_name=f'Saved {rows[n][3] or "testing"} {rows[n][2]}, attempt {rows[n][4]}' if n<len(rows) else 'Release to paint'
            s.add(production.SpoolProcessEvent(item_id=parent,sequence=n+3,event='move',process_key=f'clm_{next_step:02}',
                process_name=next_name,actor=event.actor,at=at,notes='Synthetic saved phase handoff'))
        state=testing.FlowTestingState(item_id=parent,protocol=testing.PROTOCOL,cycle=1,
            phase='complete' if decision=='YES' else 'not_required',decision=decision,decision_by=BADGES['handler'],
            decision_at=hour(10),test_kind='pressure' if decision=='YES' else None,attempt=1,
            phase_entered_at=hour(9+len(rows)),created_at=hour(9),updated_at=hour(9+len(rows)))
        if decision=='YES':
            report=reports[('pressure',1)]
            state.report_result=report['result'];state.report_reference=report['reference']
            state.reported_by=report['actor'];state.reported_at=_date_from_iso(report['at']);state.report_event_id=report['event_id']
            state.report_basis=report['basis_sha256']
            state.ndt_basis='b'*64
            state.ndt_report_event_id=reports[('ndt',2)]['event_id']
            state.ndt_review_event_id=review_ids[('ndt',2)]
            state.qa_result='PASS';state.qa_reference='pressure-review-1-PASS'
            state.reviewed_by=BADGES['inspector'];state.reviewed_at=hour(21)
        s.add(state);s.commit()
    return {'event_ids':ids,'reports':reports,'review_ids':review_ids,'exception_id':exception_id}


def _date_from_iso(value):
    return dt.datetime.fromisoformat(value)


def test_phased_testing_export_retains_failed_attempt_sender_correction_and_distinct_qa(api,public_qr_url,tmp_path):
    data=seed(api)
    history=seed_testing_history(api,data)
    before=snapshot(api)
    response=api.get('/api/spool-records/spools/'+data['a']+'/record.xlsx')
    assert response.status_code==200,response.text
    book=Workbook(response.content)
    assert len(book.sheets)==7
    reports=table_rows(book,'Inspection History','Test report event ID')
    assert [(row['Test'],row['Attempt'],row['Test result']) for row in reports]==[
        ('NDT',1,'FAIL'),('NDT',2,'PASS'),('Pressure test',1,'PASS')]
    assert [row['Report recorded by badge'] for row in reports]==[BADGES['admin'],BADGES['ndt'],BADGES['pressure_testing_technician']]
    assert [row['Testing sender badge'] for row in reports]==[BADGES['ndt'],BADGES['ndt'],BADGES['pressure_testing_technician']]
    reviews=table_rows(book,'Inspection History','Test QA event ID')
    assert [row['QA result'] for row in reviews]==['FAIL','PASS','PASS']
    assert [row['Linked test report event ID'] for row in reviews]==[row['Test report event ID'] for row in reports]
    assert [row['Linked report basis SHA-256'] for row in reviews]==[row['Report basis SHA-256'] for row in reports]
    assert all(row['QA badge']==BADGES['inspector'] for row in reviews)
    assert reviews[1]['Closed exception IDs']==str(history['exception_id'])
    assert reviews[2]['Closed exception IDs'] in ('',None)
    ndt=table_rows(book,'Inspection History','NDT acceptance event ID')
    assert len(ndt)==1 and ndt[0]['Construction basis SHA-256']=='b'*64
    assert ndt[0]['NDT acceptance event ID']==str(history['review_ids'][('ndt',2)])
    assert ndt[0]['Bound NDT report event ID']==reports[1]['Test report event ID']
    returns=table_rows(book,'Work and Rework','Failed test event ID')
    assert len(returns)==1
    assert returns[0]['Return station ID']=='testing'
    assert returns[0]['Required return badge']==returns[0]['Recorded receiving badge']==BADGES['ndt']
    assert returns[0]['Saved return employee name']=='Saved original NDT employee'
    corrections=table_rows(book,'Work and Rework','Testing correction event ID')
    assert corrections[0]['Recorded by badge']==BADGES['ndt']
    assert corrections[0]['Exception ID']==str(history['exception_id'])
    assert corrections[0]['Corrective work']=='Removed defect and completed required correction'
    route=table_rows(book,'24-step Route','Step')
    qa=[row for row in route if row['Step']==18]
    assert [row['Status'] for row in qa]==['QA FAIL','QA PASS','QA PASS']
    assert all(row['Record scope']=='Shared parent assembly: '+data['parent'] for row in qa)
    assert all(row['Elapsed HH:MM:SS']==pytest.approx(1/24) for row in qa)
    assert all(row['Status']!='Completed' for row in route if row['Step'] in (17,18,19))
    events=table_rows(book,'24-step Route','Testing event ID')
    assert [row['Testing event ID'] for row in events]==list(map(str,history['event_ids']))
    assert len(table_rows(book,'24-step Route','Testing handoff event ID'))==9
    (tmp_path/'synthetic-testing-spool-record.xlsx').write_bytes(response.content)
    assert snapshot(api)==before


def test_explicit_no_is_not_required_without_inventing_test_times_or_passes(api,public_qr_url):
    data=seed(api)
    seed_testing_history(api,data,decision='NO')
    before=snapshot(api)
    response=api.get('/api/spool-records/spools/'+data['a']+'/record.xlsx')
    assert response.status_code==200,response.text
    book=Workbook(response.content)
    route=table_rows(book,'24-step Route','Step')
    skipped=[row for row in route if row['Step'] in (18,19)]
    assert [row['Status'] for row in skipped]==['Not required — recorded NO']*2
    assert all(row['Entered (UTC)'] is None and row['Departed (UTC)'] is None and row['Elapsed HH:MM:SS'] is None for row in skipped)
    assert all(row['Employee badge'] is None for row in skipped)
    decision=table_rows(book,'24-step Route','Testing event ID')[0]
    assert decision['Decision / result']=='NO' and decision['Employee badge']==BADGES['handler']
    assert table_rows(book,'Inspection History','Test report event ID')==[]
    assert table_rows(book,'Inspection History','Test QA event ID')==[]
    assert snapshot(api)==before


def test_full_export_preserves_testing_cursor_and_exact_report_link(api,public_qr_url):
    data=seed(api)
    history=seed_testing_history(api,data)
    before=snapshot(api)
    response=api.get('/api/exports/excel')
    assert response.status_code==200,response.text
    book=Workbook(response.content)
    states=book.records('Assembly testing states')
    assert len(states)==1
    current=states[0]
    report=history['reports'][('pressure',1)]
    assert current['item_id'].value==data['parent']
    assert current['protocol'].value=='CLM-TEST-v1'
    assert current['decision'].value=='YES'
    assert current['phase'].value=='complete'
    assert current['report_event_id'].value==str(report['event_id'])
    assert current['report_basis'].value==report['basis_sha256']
    assert current['ndt_basis'].value=='b'*64
    assert current['ndt_report_event_id'].value==str(history['reports'][('ndt',2)]['event_id'])
    assert current['ndt_review_event_id'].value==str(history['review_ids'][('ndt',2)])
    assert current['qa_result'].value=='PASS'
    assert current['reported_at'].style in book.date_styles
    assert snapshot(api)==before


@pytest.mark.parametrize('restart_action,traveler_step',[('reopen',20),('fail',22)])
def test_controlled_testing_restart_remains_visible_without_erasing_prior_results(api,public_qr_url,restart_action,traveler_step):
    data=seed(api)
    history=seed_testing_history(api,data)
    flow=importlib.import_module('flow')
    testing=importlib.import_module('flow_testing')
    restart_actor=BADGES['inspector' if restart_action=='fail' else 'supervisor']
    with api.session_factory() as s:
        state=s.get(testing.FlowTestingState,data['parent'])
        pressure=flow.FlowException(item_id=data['parent'],step=18,return_step=17,
            reason='Retained pressure exception requires fresh pressure QA after restart',
            reference='TEST-OPEN-PRESSURE-EXCEPTION',opened_by=BADGES['inspector'],
            opened_at=WHEN+dt.timedelta(hours=23),resolution='Recorded correction; QA closure still pending')
        s.add(pressure);s.flush();pressure_id=pressure.id
        detail={**testing.event_context(state,action='restart'),'return_step':17,'next_step':17,
            'next_phase':'decision','next_cycle':2,'testing_required_preserved':True,
            'carried_exception_ids':[pressure_id],'carried_exception_kinds':{str(pressure_id):'pressure'}}
        s.add(flow.FlowEvent(item_id=data['parent'],sequence=len(history['event_ids'])+1,
            action=restart_action,step=traveler_step,actor=restart_actor,at=WHEN+dt.timedelta(hours=24),
            reference='TEST-CONTROLLED-RETEST',notes='Changed evidence requires a new controlled testing cycle',data=detail))
        state.cycle=2;state.phase='decision';state.decision='YES';state.decision_by=None;state.decision_at=None
        state.phase_entered_at=WHEN+dt.timedelta(hours=24)
        state.ndt_basis='';state.ndt_report_event_id=None;state.ndt_review_event_id=None
        state.pending_exception_ids=[pressure_id];state.pending_exception_kinds={str(pressure_id):'pressure'}
        testing.clear_attempt(state,None)
        plan=s.get(flow.FlowPlan,data['parent']);plan.current_step=17;plan.version+=1
        s.commit()
    response=api.get('/api/spool-records/spools/'+data['a']+'/record.xlsx')
    assert response.status_code==200,response.text
    book=Workbook(response.content)
    events=table_rows(book,'24-step Route','Testing event ID')
    restarted=events[-1]
    assert restarted['Testing action']=='restart' and restarted['Testing cycle']==1
    assert restarted['Traveler step']==traveler_step
    assert restarted['Employee badge']==restart_actor
    assert restarted['Next phase']=='decision'
    assert 'Next testing cycle: 2.' in restarted['Notes']
    assert 'Return step: 17.' in restarted['Notes']
    assert 'Required testing remains YES.' in restarted['Notes']
    if restart_action=='fail':
        assert restarted['Decision / result']=='FAIL'
        route=table_rows(book,'24-step Route','Step')
        final_qa=next(row for row in route if row['Step']==22)
        assert final_qa['Status']=='Failed; testing restart required'
    carryovers=table_rows(book,'Work and Rework','Testing carryover event ID')
    carry=next(row for row in carryovers if row['Testing action']=='restart')
    assert carry['Carried exception IDs']==str(pressure_id)
    assert carry['Recorded exception types']==f'{pressure_id}: Pressure test'
    assert carry['Closed exception IDs'] in ('',None)
    assert len(table_rows(book,'Inspection History','Test report event ID'))==3
    assert len(table_rows(book,'Inspection History','Test QA event ID'))==3
    with api.session_factory() as s:
        assert s.get(flow.FlowException,pressure_id).closed_at is None


def test_legacy_hydro_history_is_not_reinterpreted_as_phased_testing(api,public_qr_url):
    data=seed(api)
    flow=importlib.import_module('flow')
    with api.session_factory() as s:
        s.add(flow.FlowEvent(item_id=data['parent'],sequence=1,action='advance',step=18,
            actor=BADGES['inspector'],at=WHEN+dt.timedelta(hours=7),reference='LEGACY-HYDRO-REFERENCE',
            notes='The saved legacy acceptance remains a single combined check',
            data={'step_definition':{'title':'Legacy Verify Test Results (Hydro/UT)'}}))
        s.commit()
    response=api.get('/api/spool-records/spools/'+data['a']+'/record.xlsx')
    assert response.status_code==200,response.text
    book=Workbook(response.content)
    route=table_rows(book,'24-step Route','Step')
    qa=[row for row in route if row['Step']==18]
    assert len(qa)==1 and qa[0]['Status']=='Completed'
    assert qa[0]['Activity']=='Legacy Verify Test Results (Hydro/UT)'
    assert qa[0]['Entered (UTC)'] is None and qa[0]['Elapsed HH:MM:SS'] is None
    assert not any(row.get(1) and row[1].value=='Test report event ID' for row in book.sheets['Inspection History'])
