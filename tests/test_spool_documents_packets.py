"""Uploaded spool references follow exact retained packet revisions and exports."""
import hashlib
import io
import json
import zipfile

from pypdf import PdfReader

from tracking_helpers import ok
from test_dossier import (check, complete_packet, document, entry, issue_item,
                          make_project, packet, physical_release, review,
                          sign_source, signed)
from test_exports import download
from test_spool_documents import ROOT, bom_csv, pdf, request_upload
from test_quality import (workspace, create_requirement, confirm_source,
                          accepted_evidence, review as quality_review,
                          review_ok, current)
from test_flow import PROJECT, create_item


def upload_drawing(api, item_id, *, version=0, pages=3):
    return ok(request_upload(api, ROOT+'/spools/'+item_id, kind='isometric', version=version,
        files=[('complete-isometric.pdf',pdf(pages),'application/pdf')]))


def test_drawing_revision_stales_its_signed_packet_basis_without_rewriting_qa(api):
    item_id=make_project(api,'DOC-REVIEW')
    upload_drawing(api,item_id)
    signed(sign_source(api))
    supporting=document(api,item_id=item_id,code='ACTUAL-DRAWING',section='01')
    signed(entry(api,item_id,'drawings',document_ids=[supporting['id']]))
    signed(review(api,item_id,'drawings'))
    before=check(api,item_id,'drawings')
    assert before['status']=='accepted'
    old_records=packet(api,item_id)['records']['spool_documents']
    upload_drawing(api,item_id,version=1,pages=4)
    after=check(api,item_id,'drawings')
    assert after['status']=='stale'
    assert after['fingerprint']!=before['fingerprint']
    assert after['latest_review']==before['latest_review']
    assert packet(api,item_id)['records']['spool_documents'][0]['document_id']!=old_records[0]['document_id']


def test_issued_packet_embeds_complete_files_and_retains_old_revision_after_new_upload(api):
    item_id=make_project(api,'DOC-ISSUED')
    drawing=upload_drawing(api,item_id)['active']['isometric']
    original=api.get(drawing['download_url']).content
    assert len(PdfReader(io.BytesIO(original)).pages)==3
    physical_release(api,item_id)
    ready=complete_packet(api,item_id)
    assert ready['status']=='ready_for_issue',ready['blockers']
    signed(issue_item(api,item_id))
    issued=packet(api,item_id)['latest_issue']
    route='/api/dossier/issues/'+str(issued['id'])+'/download'
    first=api.get(route)
    assert first.status_code==200,first.text
    with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
        snapshot=json.loads(archive.read('snapshot.json'))
        metadata=next(row for row in snapshot['spool_documents'] if row['kind']=='isometric')
        path='spool-files/'+metadata['document_id']+'_'+metadata['filename']
        assert archive.read(path)==original
        assert hashlib.sha256(original).hexdigest()==metadata['sha256']
        assert path.encode() in archive.read('job-packet.html')
    ok(api.post('/api/items/'+item_id+'/reopen'))
    current_version=ok(api.get(ROOT+'/spools/'+item_id))['version']
    newer=upload_drawing(api,item_id,version=current_version,pages=5)['active']['isometric']
    assert newer['id']!=drawing['id']
    assert packet(api,item_id)['latest_issue']['current'] is False
    retained=api.get(route)
    assert retained.status_code==200
    with zipfile.ZipFile(io.BytesIO(retained.content)) as archive:
        assert archive.read(path)==original
        assert len(PdfReader(io.BytesIO(archive.read(path))).pages)==3
        assert newer['id'] not in archive.read('snapshot.json').decode()


def test_uploaded_reference_metadata_and_grid_are_in_excel_without_binary_bytes(api):
    item_id=make_project(api,'DOC-EXPORT')
    ok(api.patch('/api/items/'+item_id+'/part-number',{'google_part_number':'DOC-SPOOL-NUMBER'}))
    path=ROOT+'/spools/'+item_id
    uploaded=ok(request_upload(api,path,files=[('BOM.csv',bom_csv('DOC-SPOOL-NUMBER'),'text/csv')]))
    drawing=upload_drawing(api,item_id,version=1)['active']['isometric']
    _,workbook=download(api)
    scopes=workbook.records('Spool document scopes')
    assert len(scopes)==1 and scopes[0]['spool_id'].value==item_id
    documents=workbook.records('Spool uploaded documents')
    by_kind={r['kind'].value:r for r in documents}
    assert by_kind['isometric']['sha256'].value==drawing['sha256']
    assert by_kind['isometric']['page_count'].value==3
    assert json.loads(by_kind['bom']['bom'].value)['lines'][0]['part_number']=='000123'
    assert by_kind['bom']['id'].value==uploaded['active']['bom']['id']
    assert all('content' not in r for r in documents)


def test_upload_revision_stales_quality_production_evidence_only_in_that_spool(api):
    first=make_project(api,'DOC-QA-FIRST')
    second='DOC-QA-SECOND'
    create_item(api,second,kind='Spool',project=PROJECT)
    upload_drawing(api,first)
    upload_drawing(api,second)
    workspace_id=workspace(api,project_id=PROJECT)['workspace']['id']
    evidence_ids={}
    for item_id in (first,second):
        requirement_id=create_requirement(api,workspace_id,item_number=item_id,
            title='Drawing basis '+item_id,required_evidence_types=['production'])
        confirm_source(api,workspace_id,requirement_id)
        evidence_ids[item_id]=accepted_evidence(api,workspace_id,requirement_id,type='production',item_id=item_id)
        review_ok(quality_review(api,workspace_id,'requirement',requirement_id,'verified'))
    before=current(api,workspace_id)
    upload_drawing(api,first,version=1,pages=4)
    after=current(api,workspace_id)
    evidence={row['id']:row for row in after['evidence']}
    assert evidence[evidence_ids[first]]['stale'] is True
    assert evidence[evidence_ids[second]]['stale'] is False
    assert before['reviews']==after['reviews']
