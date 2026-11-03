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
