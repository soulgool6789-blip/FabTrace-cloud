"""Read-only, evidence-preserving spool workbooks in CLM's seven-sheet format.

The runtime exporter uses the application's standard ZIP/XML writer. A report
does not create production facts, infer missing work dates, or issue a Job Packet.
Each selected spool gets a separate workbook so the requested tabs stay intact.
"""
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
import datetime as dt
import json
import re
import tempfile
from urllib.parse import quote
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from main import APP_VERSION, Audit, Employee, Inspection, Item, Rework, auth, db, utcnow
from exports import (WorkbookWriter, SheetRecord, TEMP_MEMORY_BYTES, XLSX_MEDIA_TYPE,
                     SHEET_NS, _column_name, _date_serial, _stream_file, _utc, _xml_text)
from flow import (FlowPlan, FlowEvent, FlowException, ComponentLink, VERSION, ROUTE_BY_ID,
                  catalog_version, route_definition, step_definition, flow_stage_for_item)
from flow_testing import FlowTestingState, PROTOCOL as TESTING_PROTOCOL
from production import SpoolProcessEvent, summarize_process_events
from tracking import (SpoolPlan, Weld, WeldWork, WeldRepair, WeldRequirement,
                      RequirementEvidence, RequirementReview, TrackingHold)
from orders import PurchaseOrder, OrderAssembly, OrderGpn, business_gpn
from order_spools import OrderSpool, SpoolQrIdentity, effective_parent_id
from spool_boms import SpoolBomMaterial, SpoolBomEvent, physical_bom_state
from spool_receiving import (SpoolMaterialInspection, SpoolArrivalInspection,
                             SpoolMtrDocument, material_qa_states, is_physical_spool)
from spool_documents import SpoolDocumentSet, SpoolDocument, _assembly_identity
from dossier import DossierProject, DossierDocument, DossierIssue, DossierReview
from removals import item_not_removed, item_is_removed


router = APIRouter(prefix='/api/spool-records', tags=['spool record exports'])
SHEET_NAMES = ('Spool Record', '24-step Route', 'Weld Register', 'Material Traceability',
               'Inspection History', 'Work and Rework', 'Kelvion Requirements')
CURRENT_SHEET_NAMES = (SHEET_NAMES[0], '25-step Route', *SHEET_NAMES[2:])
MAX_SELECTED_SPOOLS = 100
ROUTE_HEADERS = ('Step', 'Activity', 'Record scope', 'Visit / cycle', 'Performed by',
    'Employee badge', 'Entered (UTC)', 'Departed (UTC)', 'Elapsed HH:MM:SS', 'Status',
    'QA / report reference', 'Work / exception notes')
MATERIAL_HEADERS = ('Piece key', 'Heat number', 'MTR reference', 'Supplier',
    'Supplier piece ID', 'Last updated (UTC)', 'Updated by name', 'Updated by badge', 'Saved notes')
INSPECTION_HEADERS = ('Record ID', 'Piece key', 'Check', 'Saved result', 'Recorded (UTC)',
    'Current directory name', 'Recorded badge', 'Saved reference', 'Saved notes', 'Current validity')
WORK_HEADERS = ('Event ID', 'Weld', 'Cycle', 'Operation', 'Performed by', 'Worker badge',
    'Recorded by', 'Started (UTC)', 'Finished (UTC)', 'Elapsed HH:MM:SS', 'Root visual result',
    'QA/QC name', 'QA/QC badge', 'QA time (UTC)', 'Evidence reference', 'Work accomplished')
REWORK_HEADERS = ('Rework ID', 'Weld', 'Cycle', 'Failed checkpoint', 'Defect / reason',
    'Failure report', 'Opened by', 'Opened (UTC)', 'Work started (UTC)', 'Work ended (UTC)',
    'Worker name', 'Worker badge', 'Corrective work', 'QA/QC reviewer',
    'Reinspection result', 'Resolution / evidence')


class ExportSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_ids: list[str] = Field(min_length=1, max_length=MAX_SELECTED_SPOOLS)

    @field_validator('item_ids')
    @classmethod
    def valid_ids(cls, values):
        if len(values) != len(set(values)):
            raise ValueError('Select each physical spool only once')
        if any(not value or len(value) > 60 or '\x00' in value for value in values):
            raise ValueError('Select valid permanent spool IDs')
        return values


def _stamp(value):
    if value is None or value == '':
        return None
    return _utc(value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value).replace('Z', '+00:00')))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=lambda x: _utc(x).isoformat() if isinstance(x, dt.datetime) else str(x))


def _scope(identity, spool, parent):
    if identity == spool:
        return 'This spool'
    if identity == parent:
        return 'Shared parent assembly: ' + identity
    return 'Linked component: ' + identity


def _safe_filename(label, item_id):
    # Keep archive names flat, unique by permanent ID, and independent of paths.
    clean = re.sub(r'[^A-Za-z0-9_\-\[\]]+', '_', label).strip('_')[:90] or 'spool'
    identity = re.sub(r'[^A-Za-z0-9_-]+', '_', item_id).strip('_')[:60]
    return clean + ('__' + identity if clean != identity else '') + '.xlsx'


@dataclass(frozen=True)
class Elapsed:
    seconds: float
    start_column: int | None = None
    end_column: int | None = None
    open_visit: bool = False


@dataclass
class Layout:
    name: str
    title: str
    note: str
    widths: tuple
    freeze: int = 6

    def __post_init__(self):
        self.rows = [(2, [self.title], 'title'), (4, [self.note], 'note')]
        self.cursor = 6

    def table(self, headers, rows, *, title=None):
        if title:
            self.rows.append((self.cursor, [title], 'section'))
            self.cursor += 2
        self.rows.append((self.cursor, list(headers), 'header'))
        self.cursor += 1
        data = list(rows)
        if not data:
            self.rows.append((self.cursor, ['Not recorded'], 'empty'))
            self.cursor += 1
        else:
            for row in data:
                self.rows.append((self.cursor, list(row), 'body'))
                self.cursor += 1
        self.cursor += 3

    def note_row(self, content):
        self.rows.append((self.cursor, [content], 'note'))
        self.cursor += 3


REPORT_STYLES = '''<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="mm/dd/yy hh:mm:ss"/><numFmt numFmtId="165" formatCode="[h]:mm:ss"/></numFmts>
<fonts count="4"><font><sz val="11"/><color rgb="FF203D5B"/><name val="Arial"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Arial"/></font><font><b/><sz val="16"/><color rgb="FF203D5B"/><name val="Arial"/></font><font><b/><sz val="11"/><color rgb="FF203D5B"/><name val="Arial"/></font></fonts>
<fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF234866"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF1F5F8"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFFF1C1"/></patternFill></fill></fills>
<borders count="2"><border/><border><bottom style="thin"><color rgb="FF9FB9CC"/></bottom></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="13">
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="4" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
<xf numFmtId="49" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
<xf numFmtId="164" fontId="0" fillId="3" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''


def _write_layout(writer, layout):
    sheet_id = writer.next_sheet_id
    writer.next_sheet_id += 1
    columns = max(len(layout.widths), *(len(row[1]) for row in layout.rows))
    last = max(row[0] for row in layout.rows)
    if last > 1_048_576:
        raise HTTPException(422, 'This spool exceeds Excel’s sheet row limit. Export the full business-data workbook for its complete history.')
    writer.sheets.append(SheetRecord(sheet_id, layout.name, 'spool_record', last, columns, 'report'))
    with writer.archive.open(f'xl/worksheets/sheet{sheet_id}.xml', 'w', force_zip64=True) as output:
        def write(value):
            output.write(value.encode('utf-8'))
        write(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{SHEET_NS}"><dimension ref="A1:{_column_name(columns)}{last}"/><sheetViews><sheetView showGridLines="0" workbookViewId="0">')
        if layout.freeze:
            write(f'<pane ySplit="{layout.freeze}" topLeftCell="A{layout.freeze+1}" activePane="bottomLeft" state="frozen"/>')
        write('</sheetView></sheetViews><sheetFormatPr defaultRowHeight="22"/><cols>')
        for col in range(1, columns+1):
            width = layout.widths[col-1] if col <= len(layout.widths) else 28
            write(f'<col min="{col}" max="{col}" width="{width}" customWidth="1"/>')
        write('</cols><sheetData>')
        merges = []
        for number, values, kind in sorted(layout.rows):
            height = 34 if kind == 'title' else 42 if kind in ('note', 'header') else 30
            if kind == 'body':
                # Long evidence remains intact and readable without shrinking text.
                lines = max((max(len(str(v)) // max(12, int(layout.widths[i] if i < len(layout.widths) else 28)), str(v).count('\n')) for i,v in enumerate(values) if isinstance(v,str)), default=1)
                height = min(180, max(30, 15 * (lines + 1)))
            write(f'<row r="{number}" ht="{height}" customHeight="1">')
            if kind in ('title', 'note', 'section', 'empty') and len(values) == 1:
                merges.append(f'A{number}:{_column_name(columns)}{number}')
            for col, value in enumerate(values, 1):
                ref = f'{_column_name(col)}{number}'
                if isinstance(value, Elapsed):
                    seconds = max(0, value.seconds)
                    formula = ''
                    if value.start_column:
                        start = f'{_column_name(value.start_column)}{number}'
                        end = "'Spool Record'!$B$13" if value.open_visit else f'{_column_name(value.end_column)}{number}'
                        formula = f'<f>IF(OR({start}="",{end}=""),"",MAX(0,{end}-{start}))</f>'
                    write(f'<c r="{ref}" s="4">{formula}<v>{seconds / 86400:.17g}</v></c>')
                    continue
                context = {'table':'spool_record', 'sheet':layout.name, 'row':number, 'row_id':str(number), 'column':_column_name(col)}
                cell = writer.cell(ref, value, context)
                style = 2 if isinstance(value, (dt.datetime,dt.date)) else {'title':3, 'header':1, 'note':8, 'section':7, 'empty':6}.get(kind, 5 if number % 2 == 0 else 0)
                if kind=='body' and isinstance(value,str):
                    style=10 if number % 2 == 0 else 9
                if layout.name=='Spool Record' and 6<=number<=16:
                    if col==1:
                        style=7
                    elif col==2:
                        style=11 if isinstance(value,(dt.datetime,dt.date)) else 10 if isinstance(value,str) else 12
                    elif col==3:
                        style=8
                    elif number==6:
                        style=1
                    else:
                        style=6 if number==14 and col==5 else 8
                cell = re.sub(r' s="\d+"', '', cell, count=1)
                cell = cell.replace(f'<c r="{ref}"', f'<c r="{ref}" s="{style}"', 1)
                write(cell)
            write('</row>')
        write('</sheetData>')
        if merges:
            write(f'<mergeCells count="{len(merges)}">'+''.join(f'<mergeCell ref="{value}"/>' for value in merges)+'</mergeCells>')
        write('<pageMargins left="0.25" right="0.25" top="0.4" bottom="0.4" header="0.2" footer="0.2"/><pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>')


def _load_record(s, item_id, created_at):
    item = s.get(Item, item_id)
    if item is None or not is_physical_spool(s, item) or item_is_removed(s, item.id):
        raise HTTPException(404, 'Active physical spool not found: ' + item_id)
    state = physical_bom_state(s, item.id)
    context = state['context']
    identity = _assembly_identity(s, context)
    parent = effective_parent_id(s, item.id)
    components = list(s.scalars(select(ComponentLink.component_id).where(ComponentLink.spool_id == item.id).order_by(ComponentLink.component_id)))
    related = list(dict.fromkeys([item.id, *components, *([parent] if parent else [])]))
    def rows(model, criterion, *ordering):
        return list(s.scalars(select(model).where(criterion).order_by(*ordering)))
    names = dict(s.execute(select(Employee.badge, Employee.name)).all())
    plan = s.get(SpoolPlan, item.id)
    order = s.get(PurchaseOrder, context['project_id']) if context.get('project_id') else None
    qr = s.get(SpoolQrIdentity, item.id)
    welds = rows(Weld, Weld.item_id.in_(related), Weld.item_id, Weld.number, Weld.id)
    weld_ids = [weld.id for weld in welds]
    requirements = rows(WeldRequirement, WeldRequirement.item_id.in_(related), WeldRequirement.id)
    requirement_ids = [req.id for req in requirements]
    events = rows(FlowEvent, FlowEvent.item_id.in_(related), FlowEvent.item_id, FlowEvent.sequence)
    process = rows(SpoolProcessEvent, SpoolProcessEvent.item_id.in_(related), SpoolProcessEvent.item_id, SpoolProcessEvent.sequence)
    process_by_item = defaultdict(list)
    for row in process:
        process_by_item[row.item_id].append(row)
    return dict(item=item, state=state, context=context, identity=identity, parent=parent,
        components=components, related=related, names=names, plan=plan, order=order,
        display=qr.display_code if qr else item.id, created_at=created_at,
        welds=welds, requirements=requirements,
        evidence=rows(RequirementEvidence, RequirementEvidence.requirement_id.in_(requirement_ids), RequirementEvidence.at, RequirementEvidence.id),
        reviews=rows(RequirementReview, RequirementReview.requirement_id.in_(requirement_ids), RequirementReview.at, RequirementReview.id),
        work=rows(WeldWork, WeldWork.weld_id.in_(weld_ids), WeldWork.at, WeldWork.id),
        repairs=rows(WeldRepair, WeldRepair.weld_id.in_(weld_ids), WeldRepair.opened_at, WeldRepair.id),
        holds=rows(TrackingHold, TrackingHold.item_id.in_(related), TrackingHold.opened_at, TrackingHold.id),
        flow=events, process=process,
        timers={key:summarize_process_events(key,process_by_item[key],created_at) for key in related},
        flow_plans={key:s.get(FlowPlan,key) for key in related},
        testing_states={key:row for key in related if (row:=s.get(FlowTestingState,key)) is not None},
        exceptions=rows(FlowException, FlowException.item_id.in_(related), FlowException.opened_at, FlowException.id),
        reworks=rows(Rework, Rework.item_id.in_(related), Rework.opened_at, Rework.id),
        inspections=rows(Inspection, Inspection.item_id.in_(related), Inspection.at, Inspection.id),
        material_qa=rows(SpoolMaterialInspection, SpoolMaterialInspection.spool_id==item.id, SpoolMaterialInspection.at, SpoolMaterialInspection.id),
        arrival_qa=rows(SpoolArrivalInspection, SpoolArrivalInspection.spool_id==item.id, SpoolArrivalInspection.at, SpoolArrivalInspection.id),
        material_states=material_qa_states(s,state),
        materials=rows(SpoolBomMaterial, SpoolBomMaterial.spool_id==item.id, SpoolBomMaterial.piece_key),
        material_events=rows(SpoolBomEvent, SpoolBomEvent.spool_id==item.id, SpoolBomEvent.version),
        mtrs=rows(SpoolMtrDocument, SpoolMtrDocument.spool_id==item.id, SpoolMtrDocument.uploaded_at, SpoolMtrDocument.id),
        packet_reviews=rows(DossierReview, (DossierReview.project_id==context.get('project_id')) &
            or_(DossierReview.item_id.in_(related),DossierReview.item_id.is_(None)),DossierReview.at,DossierReview.id),
        audit=rows(Audit, Audit.item_id.in_(related), Audit.at, Audit.id),
        station=flow_stage_for_item(s,item))


def _testing_data(event):
    data = event.data or {}
    return data if data.get('testing_protocol') == TESTING_PROTOCOL else {}


def _testing_events(r):
    return [event for event in r['flow'] if _testing_data(event)]


def _test_label(kind):
    return {'ndt':'NDT','pressure':'Pressure test'}.get(kind,kind or '')


def _testing_context(data):
    if not data:
        return ''
    return (f'Testing cycle {data.get("testing_cycle", "")}; '
            f'{_test_label(data.get("test_kind")) or "Testing decision"}; '
            f'phase {data.get("testing_phase", "")}; '
            f'attempt {data.get("testing_attempt", "")}; '
            f'action {data.get("testing_action", "")}. ')


def _testing_transition_notes(data,notes):
    transitions=[]
    if data.get('next_cycle') is not None:
        transitions.append(f'Next testing cycle: {data["next_cycle"]}.')
    if data.get('return_step') is not None:
        transitions.append(f'Return step: {data["return_step"]}.')
    if data.get('testing_required_preserved'):
        transitions.append('Required testing remains YES.')
    if data.get('carried_exception_ids'):
        transitions.append('Carried open exception IDs: '+', '.join(map(str,data['carried_exception_ids']))+'.')
    return ' '.join([*transitions,notes or '']).strip()


def _exception_kinds(values):
    return '; '.join(f'{key}: {_test_label(kind)}' for key,kind in (values or {}).items())


def _route_status(event):
    data = _testing_data(event)
    if data:
        action = data.get('testing_action')
        if action == 'decision':
            return 'Testing decision: ' + (data.get('testing_decision') or 'Not recorded')
        if action == 'start':
            return 'Test started'
        if action == 'complete':
            return 'Test report: ' + (data.get('test_result') or 'Not recorded')
        if action == 'review':
            return 'QA ' + (data.get('test_result') or ('FAIL' if event.action == 'fail' else 'Not recorded'))
        if action == 'correct':
            return 'Correction recorded; retest required'
        if action == 'handoff':
            return 'Floor handoff recorded'
        if action == 'restart':
            return 'Failed; testing restart required' if event.action == 'fail' else 'Testing restart recorded'
        return 'Phase action recorded'
    if (event.data or {}).get('phase_only'):
        return 'Phase action recorded'
    return 'Failed' if event.action == 'fail' else 'Completed'


def _testing_not_required(r, identity, number):
    state = r.get('testing_states',{}).get(identity)
    if not state or state.protocol != TESTING_PROTOCOL or state.decision != 'NO':
        return None
    return next((event for event in reversed(_testing_events(r))
        if event.item_id == identity and event.data.get('testing_cycle') == state.cycle
        and event.data.get('testing_action') == 'decision'
        and event.data.get('testing_decision') == 'NO'
        and number in (event.data.get('not_required_steps') or [])),None)


def _parent_route(r):
    plan = r.get('flow_plans', {}).get(r.get('parent'))
    return route_definition(plan) if plan and plan.route == 'assembly' else ROUTE_BY_ID['assembly']


def _route_sheet_name(r):
    return f'{_parent_route(r)["last_step"]}-step Route'


def _owner_step(r, identity, number):
    plan = r.get('flow_plans', {}).get(identity)
    definition = step_definition(plan, number)
    # Retain a recorded out-of-catalog event rather than silently dropping
    # it or giving it the meaning of a different numbered route.
    return definition or {'number': number, 'title': f'Recorded step {number} (definition unavailable)'}


def _route_rows(r):
    result = []
    numbers = set(range(1, _parent_route(r)['last_step'] + 1))
    numbers.update(event.step for event in r['flow'] if type(event.step) is int and event.step > 0)
    for timer in r['timers'].values():
        for visit in timer['visits']:
            match = re.fullmatch(r'clm_(\d+)', visit['process_key'])
            if match:
                numbers.add(int(match.group(1)))
    flow = defaultdict(list)
    for event in r['flow']:
        flow[(event.item_id,event.step)].append(event)
    for number in sorted(numbers):
        ids = r['components'] if number <= 8 else [r['item'].id] if number <= 16 else ([r['parent']] if r['parent'] else [])
        wrote = False
        for identity in ids:
            step = _owner_step(r, identity, number)
            scope = _scope(identity,r['item'].id,r['parent'])
            identity_wrote = False
            visits = [v for v in r['timers'][identity]['visits'] if v['process_key'] == f'clm_{number:02d}']
            used = set()
            for visit_index, visit in enumerate(visits,1):
                start, end = _stamp(visit['started_at']), _stamp(visit['ended_at'])
                # Completion belongs only to the same item, step and recorded visit.
                candidates = [e for e in flow[(identity,number)] if e.id not in used and e.action in ('advance','fail') and _utc(e.at)>=start and (end is None or _utc(e.at)<=end)]
                event = candidates[0] if candidates else None
                if event:
                    used.add(event.id)
                status = _route_status(event) if event else ('In progress' if end is None and visit['status']=='running' else 'Paused' if end is None else 'Timer finished; step acceptance not recorded')
                actor = event.actor if event else visit['started_by']
                notes = (_testing_context(_testing_data(event)) + event.notes) if event else ''
                notes += ('\n' if notes else '') + f'Item {identity}; process visit {visit["id"]}; active {visit["active_seconds"]:g}s; paused {visit["paused_seconds"]:g}s.'
                if end is None:
                    notes += ' Elapsed to export timestamp; departure not recorded.'
                title=((event.data or {}).get('step_definition') or {}).get('title') if event else None
                result.append([number,title or visit.get('process_name') or step['title'],scope,visit_index,r['names'].get(actor,''),actor,start,end,
                    Elapsed(visit['elapsed_seconds'],7,8,end is None),status,event.reference if event else '',notes])
                wrote = True
                identity_wrote = True
            for event in flow[(identity,number)]:
                if event.action not in ('advance','fail') or event.id in used:
                    continue
                title=((event.data or {}).get('step_definition') or {}).get('title')
                result.append([number,title or step['title'],scope,None,r['names'].get(event.actor,''),event.actor,
                    None,_utc(event.at),None,_route_status(event),event.reference,
                    f'Flow event {event.id}; entry/duration not recorded. '+_testing_context(_testing_data(event))+event.notes])
                wrote = True
                identity_wrote = True
            if not identity_wrote:
                skipped = _testing_not_required(r,identity,number)
                result.append([number,step['title'],scope,None,None,None,None,None,None,
                    'Not required — recorded NO' if skipped else 'Not recorded',
                    skipped.reference if skipped else None,
                    f'Testing decision event {skipped.id}; no test, QA pass, station visit or duration is inferred.' if skipped else None])
                wrote = True
        if not wrote:
            step = _owner_step(r, None, number)
            scope = 'Linked component' if number<=8 else 'This spool' if number<=16 else 'Shared parent assembly'
            result.append([number,step['title'],scope,None,None,None,None,None,None,'Not recorded',None,None])
    return result


def _append_testing_summary(layout,r):
    rows=[]
    for identity,state in r.get('testing_states',{}).items():
        if state.protocol != TESTING_PROTOCOL:
            continue
        rows.extend([
            ['Source item ID',identity,None,None,None],
            ['Testing protocol',state.protocol,None,None,None],
            ['Testing cycle',state.cycle,None,None,None],
            ['Testing required',state.decision or 'Not recorded',None,state.decision_by,_stamp(state.decision_at)],
            ['Current testing phase',state.phase,None,None,_stamp(state.phase_entered_at)],
            ['Current test / attempt',f'{_test_label(state.test_kind)} / {state.attempt}' if state.test_kind else 'Not recorded',None,None,None],
            ['Current report result',state.report_result,None,state.reported_by,_stamp(state.reported_at)],
            ['Current test report reference',state.report_reference,None,state.reported_by,_stamp(state.reported_at)],
            ['Current test report basis SHA-256',state.report_basis,None,None,None],
            ['Current QA result',state.qa_result,None,state.reviewed_by,_stamp(state.reviewed_at)],
            ['Current QA reference',state.qa_reference,None,state.reviewed_by,_stamp(state.reviewed_at)],
            ['NDT construction basis SHA-256',state.ndt_basis,None,None,None],
            ['NDT test report event ID',str(state.ndt_report_event_id) if state.ndt_report_event_id is not None else None,None,None,None],
            ['NDT QA review event ID',str(state.ndt_review_event_id) if state.ndt_review_event_id is not None else None,None,None,None],
            ['Open testing exception IDs',', '.join(map(str,state.pending_exception_ids or [])),None,None,None],
            ['Open testing exception types','; '.join(f'{key}: {_test_label((state.pending_exception_kinds or {}).get(str(key)))}'
                for key in state.pending_exception_ids or []),None,None,None],
        ])
    if rows:
        layout.table(('Testing state field','Saved value',None,'Recorded badge','Recorded (UTC)'),rows,
            title='Current shared assembly testing state')
        layout.note_row('This is the saved current cursor. Every prior decision, test attempt, failure, return and correction is listed in the route, inspection and rework histories. A test report and QA acceptance are separate records.')


def _append_testing_route(layout,r):
    events=_testing_events(r)
    if not events:
        return
    scope=lambda key:_scope(key,r['item'].id,r['parent'])
    layout.table(('Testing event ID','Source item ID','Record scope','Traveler step','Testing cycle','Test / phase','Attempt',
        'Testing action','Decision / result','Recorded (UTC)','Employee name','Employee badge','Reference','Next phase','Notes'),[
        [str(e.id),e.item_id,scope(e.item_id),e.step,e.data.get('testing_cycle'),
            (_test_label(e.data.get('test_kind'))+' / '+e.data.get('testing_phase','')).strip(' /'),
            e.data.get('testing_attempt'),e.data.get('testing_action'),e.data.get('testing_decision') or e.data.get('test_result') or ('FAIL' if e.action=='fail' else None),
            _utc(e.at),r['names'].get(e.actor,''),e.actor,e.reference,e.data.get('next_phase'),
            _testing_transition_notes(e.data,e.notes)]
        for e in events],title='Assembly testing decisions and phase history')
    layout.note_row('Testing phases repeat numeric Steps 17–19. A start, report, correction or intermediate QA pass does not by itself complete all testing. NO marks only testing Steps 18–19 not required; it does not create a test result or QA approval or skip the current route’s shipment Floor return at 23. Current QA/QC-004 is NDT, QA/QC-005 is pressure testing and QA/QC-006 is final inspection. Historical events retain their saved checkpoint codes and definitions.')
    moves=[]
    for event in events:
        handoff=event.data.get('handoff') or {}
        if not handoff:
            continue
        before,after=handoff.get('from') or {},handoff.get('to') or {}
        sender,receiver=handoff.get('sender') or {},handoff.get('receiver') or {}
        moves.append([str(event.id),event.item_id,event.data.get('testing_cycle'),_test_label(event.data.get('test_kind')),
            event.data.get('testing_attempt'),event.data.get('testing_action'),_utc(event.at),
            sender.get('badge') or handoff.get('sender_badge'),sender.get('name'),
            before.get('location_id'),before.get('location'),
            receiver.get('badge') or handoff.get('receiver_badge'),receiver.get('name'),
            after.get('location_id'),after.get('location'),handoff.get('handoff_recorded_by')])
    layout.table(('Testing handoff event ID','Source item ID','Testing cycle','Test','Attempt','Testing action','Recorded (UTC)',
        'Sender badge','Saved sender name','From station ID','From station label','Receiver badge','Saved receiver name',
        'To station ID','To station label','Handoff recorded by badge'),moves,title='Recorded testing custody handoffs')


def _append_testing_inspections(layout,r):
    events=_testing_events(r)
    if not events:
        return
    scope=lambda key:_scope(key,r['item'].id,r['parent'])
    layout.table(('Test report event ID','Source item ID','Record scope','Testing cycle','Test','Attempt','Test result',
        'Reported (UTC)','Report recorded by name','Report recorded by badge','Test report reference','Report notes',
        'Testing sender badge','Saved testing sender name','Report basis SHA-256'),[
        [str(e.id),e.item_id,scope(e.item_id),e.data.get('testing_cycle'),_test_label(e.data.get('test_kind')),
            e.data.get('testing_attempt'),e.data.get('test_result'),_utc(e.at),r['names'].get(e.actor,''),e.actor,e.reference,e.notes,
            ((e.data.get('handoff') or {}).get('sender') or {}).get('badge') or (e.data.get('handoff') or {}).get('sender_badge'),
            ((e.data.get('handoff') or {}).get('sender') or {}).get('name'),(e.data.get('report') or {}).get('basis_sha256')]
        for e in events if e.data.get('testing_action')=='complete'],title='Assembly NDT and pressure-test reports')
    reviews=[]
    for event in events:
        if event.data.get('testing_action') != 'review':
            continue
        report=event.data.get('report') or {}
        reviews.append([str(event.id),event.item_id,scope(event.item_id),event.data.get('testing_cycle'),
            _test_label(event.data.get('test_kind')),event.data.get('testing_attempt'),event.data.get('test_result'),
            _utc(event.at),r['names'].get(event.actor,''),event.actor,event.reference,
            str(report['event_id']) if report.get('event_id') is not None else None,report.get('result'),
            report.get('reference'),', '.join(map(str,event.data.get('closed_exception_ids') or [])),event.notes,report.get('basis_sha256'),
            (event.data.get('step_definition') or {}).get('display_qa_code'),event.data.get('definition_version')])
    layout.table(('Test QA event ID','Source item ID','Record scope','Testing cycle','Test','Attempt','QA result',
        'Reviewed (UTC)','QA name','QA badge','QA reference','Linked test report event ID','Linked test result',
        'Linked test report reference','Closed exception IDs','Review notes','Linked report basis SHA-256',
        'Saved QA checkpoint','Saved catalog version'),reviews,title='Assembly test QA decisions')
    layout.table(('NDT acceptance event ID','Source item ID','Testing cycle','Attempt','Construction basis SHA-256',
        'Bound NDT report event ID','QA badge','Accepted (UTC)','QA reference'),[
        [str(e.id),e.item_id,e.data.get('testing_cycle'),e.data.get('testing_attempt'),
            e.data['ndt_accepted_basis'].get('basis_sha256'),
            str(e.data['ndt_accepted_basis']['report_event_id']) if e.data['ndt_accepted_basis'].get('report_event_id') is not None else None,
            e.actor,_utc(e.at),e.reference]
        for e in events if e.data.get('ndt_accepted_basis')],title='Recorded NDT construction acceptance')
    layout.note_row('Test reports retain the saved result, recording employee and actual sending custodian separately. QA decisions retain their explicit linked report snapshot and review identity. A failed attempt remains after correction or a later PASS. Current acceptance also depends on live readiness and the controlled evidence basis.')


def _append_testing_rework(layout,r):
    failures=[]
    corrections=[]
    carryovers=[]
    scope=lambda key:_scope(key,r['item'].id,r['parent'])
    for event in _testing_events(r):
        data=event.data
        if event.action=='fail' and data.get('testing_action')=='review':
            origin=data.get('return_to') or {}
            handoff=data.get('handoff') or {}
            receiver=handoff.get('receiver') or {}
            failures.append([str(event.id),event.item_id,scope(event.item_id),data.get('testing_cycle'),
                _test_label(data.get('test_kind')),data.get('testing_attempt'),
                str(data['exception_id']) if data.get('exception_id') is not None else None,event.reference,
                origin.get('location_id'),origin.get('location_label'),origin.get('sender_badge'),origin.get('sender_name'),
                receiver.get('badge') or handoff.get('receiver_badge'),_utc(event.at),event.notes])
        elif data.get('testing_action')=='correct':
            correction=data.get('correction') or {}
            corrections.append([str(event.id),event.item_id,scope(event.item_id),data.get('testing_cycle'),
                _test_label(data.get('test_kind')),data.get('testing_attempt'),
                str(correction['exception_id']) if correction.get('exception_id') is not None else None,
                _utc(event.at),r['names'].get(event.actor,''),event.actor,
                correction.get('reference') or event.reference,correction.get('resolution') or data.get('resolution'),
                data.get('next_phase'),event.notes])
        if any(key in data for key in ('carried_exception_ids','remaining_exception_ids')):
            carryovers.append([str(event.id),event.item_id,scope(event.item_id),data.get('testing_cycle'),
                _test_label(data.get('test_kind')),data.get('testing_action'),_utc(event.at),data.get('next_cycle'),
                ', '.join(map(str,data.get('closed_exception_ids') or [])),
                ', '.join(map(str,data.get('carried_exception_ids') or [])),
                ', '.join(map(str,data.get('remaining_exception_ids') or [])),
                _exception_kinds(data.get('carried_exception_kinds') or data.get('remaining_exception_kinds')),
                event.actor,event.notes])
    if not failures and not corrections and not carryovers:
        return
    layout.table(('Failed test event ID','Source item ID','Record scope','Testing cycle','Test','Attempt','Exception ID',
        'Failure reference','Return station ID','Return station label','Required return badge','Saved return employee name',
        'Recorded receiving badge','Returned (UTC)','Failure / reason'),failures,title='Failed test returns to the recorded sender and station')
    layout.table(('Testing correction event ID','Source item ID','Record scope','Testing cycle','Test','Attempt corrected',
        'Exception ID','Correction recorded (UTC)','Recorded by name','Recorded by badge','Correction reference','Corrective work',
        'Next phase','Saved notes'),corrections,title='Mandatory testing corrections')
    layout.table(('Testing carryover event ID','Source item ID','Record scope','Testing cycle','Test','Testing action',
        'Recorded (UTC)','Next testing cycle','Closed exception IDs','Carried exception IDs','Remaining exception IDs',
        'Recorded exception types','Recorded badge','Notes'),carryovers,title='Testing exceptions carried or resolved across phases')
    layout.note_row('A recorded correction requires a new test attempt and a separate QA decision. Correction timestamps record completion/recording only; no unrecorded work start or duration is inferred. Exception closure remains separately identified by the accepting QA event.')


def _is_root(req):
    code=re.sub(r'[^A-Z0-9]+','_',req.code.upper()).strip('_')
    if code in {'ROOT_VISUAL','ROOT_VT','ROOT_VISUAL_INSPECTION','ROOT_VT_INSPECTION',
                'ROOT_PASS_VT','ROOT_PASS_VISUAL','ROOT_PASS_VISUAL_INSPECTION'}:
        return True
    label=' '.join(req.label.lower().replace('-',' ').split())
    return bool(re.fullmatch(r'(?:weld )?root(?: weld| pass)? (?:visual|vt)(?: inspection| examination| check)?',label)
        or re.fullmatch(r'(?:visual|vt) (?:inspection|examination) (?:of )?(?:the )?root(?: weld| pass)?',label))


def _weld_name(weld, r):
    return weld.number if weld.item_id==r['item'].id else weld.number+' ('+_scope(weld.item_id,r['item'].id,r['parent'])+')'


def _weld_mapping(weld, materials, r):
    fields, statuses = [], []
    for side in ('a','b'):
        component, heat, mtr = (getattr(weld,name+'_'+side) for name in ('component','heat','mtr'))
        matches = [m for m in materials if component and component in (m.get('piece_key'),m.get('piece_identifier'))]
        if not matches:
            matches = [m for m in materials if component and component==m.get('supplier_piece_id')]
        # Materials in this workbook belong to this spool. A parent weld must
        # not inherit a child's equal-looking piece key.
        if weld.item_id != r['item'].id:
            matches = []
        if len(matches)==1:
            material = matches[0]
            mismatch = (heat and heat!=material.get('heat_number','')) or (mtr and mtr!=material.get('mtr_reference',''))
            statuses.append(side.upper()+(': saved weld value differs from current piece' if mismatch else ': exact piece link'))
            heat, mtr = heat or material.get('heat_number',''), mtr or material.get('mtr_reference','')
        else:
            statuses.append(side.upper()+(': ambiguous piece link' if len(matches)>1 else ': piece link not verified' if component else ': not mapped'))
        fields.extend([component,heat,mtr])
    if r.get('state',{}).get('source_status',{}).get('changed'):
        statuses.append('BOM source changed; review mapping')
    return fields, '; '.join(statuses)


def _document_rows(s,r):
    context = r['context']
    conditions = [SpoolDocumentSet.spool_id==r['item'].id]
    if context.get('requirement_id'):
        conditions.append(SpoolDocumentSet.requirement_id==context['requirement_id'])
    sets = {row.id:row for row in s.scalars(select(SpoolDocumentSet).where(or_(*conditions)))}
    docs = []
    for row in s.scalars(select(SpoolDocument).where(SpoolDocument.set_id.in_(sets)).order_by(SpoolDocument.uploaded_at,SpoolDocument.id)):
        scope = sets[row.set_id]
        docs.append([row.id,row.kind,'Shared spool definition' if scope.requirement_id else 'This spool',row.filename,
            row.revision,row.version,row.sha256,_utc(row.uploaded_at),r['names'].get(row.uploaded_by,''),row.uploaded_by,
            '/api/spool-documents/files/'+quote(row.id,safe='')+'?download=1'])
    for row in r['mtrs']:
        docs.append([row.id,'MTR: '+row.reference,'This spool',row.filename,row.revision,row.version,row.sha256,
            _utc(row.uploaded_at),r['names'].get(row.uploaded_by,''),row.uploaded_by,'/api/spool-boms/mtr-files/'+quote(row.id,safe='')])
    if context.get('project_id'):
        for row in s.scalars(select(DossierDocument).where(DossierDocument.project_id==context['project_id'],
                or_(DossierDocument.item_id.in_(r['related']), DossierDocument.item_id.is_(None))).order_by(DossierDocument.at,DossierDocument.id)):
            docs.append([str(row.id),row.code,_scope(row.item_id,r['item'].id,r['parent']) if row.item_id else 'Shared project document',
                row.filename or row.title,row.revision,None,row.sha256,_utc(row.at),r['names'].get(row.actor,''),row.actor,
                '/api/dossier/documents/'+quote(str(row.id),safe='')+'/download' if row.filename else None,row.reference])
    return docs


def report_layouts(s,r):
    item, state, identity = r['item'],r['state'],r['identity']
    names = r['names']
    plan = r['plan']
    scope = lambda key:_scope(key,item.id,r['parent'])
    parent_plan = r['flow_plans'].get(r['parent'])
    route_last = _parent_route(r)['last_step']
    route_sheet = _route_sheet_name(r)
    book = []
    intro = Layout('Spool Record','CLM Fabrication Spool Record',
        'Production record export. Missing records remain blank or Not recorded. This export does not issue a Job Packet.',
        (32,54,5,36,56),freeze=0)
    evidence = [('Material pieces',len(state['materials'])),('Historical QA-001 decisions',len(r['material_qa'])),
        ('Overall arrival inspections',len(r['arrival_qa'])),('Numbered flow events',len(r['flow'])),
        ('Process timer events',len(r['process'])),('Weld work events',len(r['work']))]
    values = [('Spool',r['display']),('Purchase order',r['order'].purchase_order if r['order'] else None),
        ('Customer',r['order'].customer if r['order'] else None),('GPN',identity.get('gpn')),
        ('Assembly number',identity.get('assembly_number')),('Permanent spool ID',item.id),
        ('Permanent assembly ID',r['parent']),('Data captured (UTC)',r['created_at']),
        ('Flow definition',catalog_version(parent_plan) if parent_plan else 'Parent traveler not started'),
        ('Planned welds',plan.planned_welds if plan else item.welds_required)]
    for index,(label,value) in enumerate(values,6):
        row = [label,value,None]
        if index==6:
            row += ['Recorded evidence','Count']
        elif 7<=index<=12:
            row += list(evidence[index-7])
        elif index==14:
            fp = r['flow_plans'][item.id]
            row += ['Spool traveler status',fp.status if fp else 'Not recorded']
        intro.rows.append((index,row,'body'))
    # Current GPN identity is separate from immutable legacy document scopes.
    canonical = None
    try:
        from orders import AssemblyGpnLink
        linked = s.get(AssemblyGpnLink,r['context'].get('gpn_id')) if r['context'].get('gpn_id') else None
        canonical = linked.gpn_record_id if linked else None
    except ImportError:
        pass
    intro.rows.append((16,['Permanent GPN record ID',canonical,None,'Application version',APP_VERSION],'body'))
    intro.cursor = 19
    intro.table(('Data meaning','Recorded scope'),[
        ['Names and badges','Names are current directory names. Saved badges and event timestamps are retained; historical roles are not inferred.'],
        ['Route scope',f'Steps 1–8: linked components. Steps 9–16: this spool. Steps 17–{route_last}: shared parent assembly. Shared work is not additional spool labor. Each recorded traveler retains its own catalog.'],
        ['Timing','Elapsed station and process time includes calendar waiting time. Active/paused process clock time is listed separately. These are not employee labor hours.'],
        ['Missing events','Earlier baseline steps and work dates have not been reconstructed. Open visits are measured to the captured export timestamp.'],
        ['Weld work','Existing work events record completion/recording time only. Missing start times, independent recorder identities and per-operation durations stay blank.'],
        ['Inspection cycles','Work cycles and requirement cycles are separate counters. Approval events are not joined to work solely because their cycle numbers match.'],
        ['Assembly testing','Explicit NDT and pressure-test phases are shown only when the phased protocol is recorded. Legacy Hydro/UT history is not reclassified.'],
        ['Material source','BOM source changed; adoption/review required.' if state['source_status']['changed'] else 'Current material values and retained history are exported as stored.'],
        ['Original documents','The document index lists references and stored file hashes. Download the listed files or an issued Job Packet for the original documents.'],
        ['QA release',('Recorded release at '+_utc(item.released_at).isoformat()) if item.released and item.released_at else 'Not recorded'],
    ])
    intro.table(('Source item ID','Record scope','Traveler route','Recorded catalog','Traveler status'),[
        [key,scope(key),flow.route if flow else None,catalog_version(flow) if flow else None,
            flow.status if flow else 'Not started']
        for key in r['related'] for flow in [r['flow_plans'].get(key)]],title='Traveler catalog identities')
    intro.note_row('Missing traveler records are not assigned a historical route. Their blank template positions use the current catalog; saved event definitions and process names remain authoritative for recorded work.')
    _append_testing_summary(intro,r)
    book.append(intro)

    route = Layout(route_sheet,f'{route_last}-step production history',
        'Each recorded visit is retained. Performed by identifies the saved route/timer actor; handoff badges remain in the event detail below.',
        (9,42,38,16,26,34,24,24,24,32,40,66))
    route.table(ROUTE_HEADERS,_route_rows(r))
    _append_testing_route(route,r)
    station_rows = []
    for visit in r['station'].get('station_visits',[]):
        start,end = _stamp(visit.get('entered_at')),_stamp(visit.get('departed_at'))
        source = visit.get('source_item_id') or item.id
        elapsed = Elapsed(max(0,((end or r['created_at'])-start).total_seconds()),5,6,end is None) if start else None
        station_rows.append([visit.get('label') or visit.get('stage_key'),scope(source),visit.get('visit'),source,start,end,elapsed,
            'In progress' if start and not end else 'Departed' if start else 'Not recorded',
            str(visit.get('entry_event_id') or ''),str(visit.get('exit_event_id') or ''),
            visit.get('entered_by'),visit.get('departed_by'),visit.get('handler_badge'),visit.get('entry_notes')])
    route.table(('Station','Record scope','Visit','Source item ID','Entered (UTC)','Departed (UTC)',
        'Elapsed HH:MM:SS','Timing status','Entry event ID','Exit event ID','Entered by badge','Departed by badge','Handler badge','Entry notes'),station_rows,title='Physical station visits')
    route.note_row('Physical station time is based on recorded movements. A default Inventory label without an entry event has no inferred duration. Shared parent time is labeled and is not additional labor.')
    route.table(('Source item ID','Record scope','Visit','Process','Status','Started (UTC)','Ended (UTC)',
        'Elapsed HH:MM:SS','Active HH:MM:SS','Paused HH:MM:SS','Started by badge','Ended by badge'),[
        [key,scope(key),v['id'],v['process_name'],v['status'],_stamp(v['started_at']),_stamp(v['ended_at']),
         Elapsed(v['elapsed_seconds'],6,7,v['ended_at'] is None),Elapsed(v['active_seconds']),Elapsed(v['paused_seconds']),v['started_by'],v['ended_by']]
        for key in r['related'] for v in r['timers'][key]['visits']],title='All process timer visits')
    route.table(('Event ID','Source item ID','Sequence','Action','Step','Recorded (UTC)','Current directory name','Recorded badge','Reference','Notes','Saved catalog version','Saved event detail'),[
        [str(e.id),e.item_id,e.sequence,e.action,e.step,_utc(e.at),names.get(e.actor,''),e.actor,e.reference,e.notes,(e.data or {}).get('definition_version'),_json(e.data)] for e in r['flow']],title='Numbered flow event history')
    route.table(('Event ID','Source item ID','Sequence','Event','Process key','Process name','Recorded (UTC)','Current directory name','Recorded badge','Notes'),[
        [str(e.id),e.item_id,e.sequence,e.event,e.process_key,e.process_name,_utc(e.at),names.get(e.actor,''),e.actor,e.notes] for e in r['process']],title='Process timer event history')
    book.append(route)

    register = Layout('Weld Register','Individual weld register',
        'Saved weld and procedure identities. Current piece links are matched exactly within this spool; missing or conflicting links remain visible.',
        (28,36,14,30,22,22,24,34,30,34,38))
    req_by_weld = defaultdict(list)
    for req in r['requirements']:
        req_by_weld[req.weld_id].append(req)
    register.table(('Weld','Permanent weld ID','Cycle','WPS','WPS revision','Drawing revision','Completed (UTC)','Completed by badge','Work status','Root visual status','Record scope'),[
        [_weld_name(w,r),w.id,w.cycle,w.wps,w.wps_revision,w.drawing_revision,_stamp(w.completed_at),w.completed_by,
         'Completed' if w.completed_at else 'Not recorded',
         '; '.join(req.code+': '+req.status for req in req_by_weld[w.id] if _is_root(req)) or 'Not recorded',scope(w.item_id)] for w in r['welds']])
    mappings=[]
    for weld in r['welds']:
        fields,status = _weld_mapping(weld,state['materials'],r)
        mappings.append([_weld_name(weld,r),*fields,status,weld.wps+(' Rev '+weld.wps_revision if weld.wps_revision else ''),scope(weld.item_id)])
    register.table(('Weld','Component A','Heat A','MTR A','Component B','Heat B','MTR B','Material mapping','WPS basis','Record scope'),mappings,title='Weld material mapping')
    register.note_row('A nonblank saved heat or MTR is not proof of a physical piece link. Exact current piece matches may supply missing display values. Conflicting saved weld values are retained and flagged. Root visual acceptance appears only for an explicitly defined root visual requirement.')
    book.append(register)

    materials = Layout('Material Traceability','Material heat and MTR traceability',
        'Each physical piece remains distinct. Heat and MTR identifiers are literal text, including leading zeros.',
        (34,24,34,28,34,24,26,34,60))
    saved = {m.piece_key:m for m in r['materials']}
    material_rows=[]
    current_keys=set()
    for m in state['materials']:
        current_keys.add(m['piece_key'])
        material_rows.append([m['piece_key'],m.get('heat_number'),m.get('mtr_reference'),m.get('supplier'),m.get('supplier_piece_id'),
            _stamp(m.get('updated_at')),names.get(m.get('updated_by'),''),m.get('updated_by'),m.get('notes')])
    for key,m in saved.items():
        if key not in current_keys:
            material_rows.append([key,m.heat_number,m.mtr_reference,m.supplier,m.supplier_piece_id,_utc(m.updated_at),names.get(m.updated_by,''),m.updated_by,
                'Retained outside current BOM. '+(m.notes or '')])
    materials.table(MATERIAL_HEADERS,material_rows)
    materials.table(('Piece key','Piece identifier','BOM item','Piece number','BOM line quantity','Part number','Description','Size','Material','Unit','Record status','MTR URL','Length','Length (inches)'),[
        [m['piece_key'],m.get('piece_identifier'),m.get('item'),m.get('piece_number'),m.get('pieces_on_line'),m.get('part_number'),m.get('description'),
            m.get('size'),m.get('material'),m.get('unit'),'Saved' if m.get('persisted') else 'Not saved',m.get('mtr_url'),m.get('length_display'),m.get('length_inches')]
        for m in state['materials']],title='Piece and BOM identity')
    materials.table(('Version','Recorded (UTC)','Current directory name','Recorded badge','Reason','Saved changes'),[
        [e.version,_utc(e.at),names.get(e.actor,''),e.actor,e.reason,_json(e.changes)] for e in r['material_events']],title='Material traceability revision history')
    materials.table(('Revision','Source status','Current source','Pinned source','Saved BOM definition'),[[
        (state['definition'] or {}).get('revision'), 'BOM changed; review required' if state['source_status']['changed'] else 'Source retained',
        _json(state['source_status']['current']),_json(state['source_status']['pinned']),_json(state['definition'])]],title='BOM source record')
    book.append(materials)

    inspections = Layout('Inspection History','Inspection decisions and evidence',
        'Every failed, repeated and later accepted decision is retained. A historical Pass does not establish current acceptance.',
        (28,36,34,22,24,28,34,40,60,38))
    decisions=[]
    for e in r['material_qa']:
        current = r['material_states'].get(e.piece_key)
        validity = 'Piece outside current BOM' if current is None else ('Current '+current['status'].replace('_',' ') if (current.get('latest') or {}).get('id')==e.id else 'Historical; superseded')
        decisions.append([str(e.id),e.piece_key,e.check_code,e.result,_utc(e.at),names.get(e.actor,''),e.actor,e.reference,e.notes,validity])
    inspections.table(INSPECTION_HEADERS,decisions)
    inspections.table(('Record ID','Result','Recorded (UTC)','Current directory name','Recorded badge','Reference','Notes','Basis SHA-256','Saved checks','Saved basis'),[
        [str(e.id),e.result,_utc(e.at),names.get(e.actor,''),e.actor,e.reference,e.notes,e.basis_sha256,_json(e.checks),_json(e.basis)] for e in r['arrival_qa']],title='Overall arrival inspection history')
    inspections.table(('Record ID','Piece key','Version','Basis SHA-256','Saved evidence basis'),[
        [str(e.id),e.piece_key,e.version,e.basis_sha256,_json(e.basis)] for e in r['material_qa']],title='Material inspection evidence snapshots')
    inspections.table(('Record ID','Source item ID','Record scope','Check','Result','Recorded (UTC)','Current directory name','Recorded badge','Report','Measurements'),[
        [str(e.id),e.item_id,scope(e.item_id),e.kind,e.result,_utc(e.at),names.get(e.inspector,''),e.inspector,e.report,_json(e.measurements)] for e in r['inspections']],title='Item inspection history')
    requirements={e.id:e for e in r['requirements']}
    weld_by_id={w.id:w for w in r['welds']}
    inspections.table(('Requirement ID','Weld','Record scope','Code','Label','Stage','Current status','Requirement cycle','Source','Check type'),[
        [str(e.id),_weld_name(weld_by_id[e.weld_id],r) if e.weld_id in weld_by_id else '',scope(e.item_id),e.code,e.label,e.stage,e.status,e.cycle,e.source,e.check_kind] for e in r['requirements']],title='Current requirement register')
    inspections.table(('Evidence ID','Requirement ID','Weld','Check','Requirement cycle','Result','Recorded (UTC)','Current directory name','Recorded badge','Reference','Notes'),[
        [str(e.id),str(e.requirement_id),_weld_name(weld_by_id[requirements[e.requirement_id].weld_id],r) if requirements[e.requirement_id].weld_id in weld_by_id else '',
         requirements[e.requirement_id].code,e.cycle,e.result,_utc(e.at),names.get(e.actor,''),e.actor,e.reference,e.notes] for e in r['evidence']],title='Requirement evidence history')
    inspections.table(('Review ID','Requirement ID','Evidence ID','Requirement cycle','Decision','Recorded (UTC)','Current directory name','Recorded badge','Notes'),[
        [str(e.id),str(e.requirement_id),str(e.evidence_id) if e.evidence_id else None,e.cycle,e.decision,_utc(e.at),names.get(e.actor,''),e.actor,e.notes] for e in r['reviews']],title='Requirement review history')
    inspections.table(('Review ID','Source item ID','Record scope','Packet check','Decision','Recorded (UTC)','Current directory name',
        'Recorded badge','Reference','Notes','Evidence fingerprint','Saved review snapshot'),[
        [str(e.id),e.item_id,scope(e.item_id) if e.item_id else 'Shared project review',e.code,e.decision,_utc(e.at),names.get(e.actor,''),e.actor,
            e.reference,e.notes,e.fingerprint,_json(e.snapshot)] for e in r['packet_reviews']],title='Job Packet review history')
    _append_testing_inspections(inspections,r)
    book.append(inspections)

    work = Layout('Work and Rework','Weld work and rework detail',
        'Work event times are retained as saved. No unrecorded work start, duration or repair completion is inferred.',
        (25,30,20,28,26,34,26,24,24,24,28,26,34,24,42,62),freeze=7)
    work.cursor=7
    work_rows=[]
    for e in r['work']:
        work_rows.append([str(e.id),_weld_name(weld_by_id[e.weld_id],r),e.cycle,e.operation,names.get(e.actor,''),e.actor,
            None,None,_utc(e.at),None,None,None,None,None,None,e.notes])
    for e in r['evidence']:
        req=requirements[e.requirement_id]
        if _is_root(req):
            work_rows.append(['QA-'+str(e.id),_weld_name(weld_by_id[req.weld_id],r) if req.weld_id in weld_by_id else 'Spool requirement',
                'Requirement cycle '+str(e.cycle),'Root visual evidence',None,None,None,None,None,None,e.result,names.get(e.actor,''),e.actor,_utc(e.at),e.reference,e.notes])
    work.table(WORK_HEADERS,work_rows)
    rework_rows=[]
    for e in r['repairs']:
        rework_rows.append(['WELD-'+str(e.id),_weld_name(weld_by_id[e.weld_id],r),e.cycle,None,e.reason,None,names.get(e.opened_by,''),_utc(e.opened_at),
            None,None,None,None,None,None,None,'Repair cycle opened; subsequent work and QA decisions are listed separately.'])
    for e in r['exceptions']:
        rework_rows.append(['FLOW-'+str(e.id),scope(e.item_id),None,'Step '+str(e.step),e.reason,e.reference,names.get(e.opened_by,''),_utc(e.opened_at),
            None,None,None,None,e.resolution,names.get(e.closed_by,''),'Passed reinspection' if e.closed_at else None,
            f'Return step {e.return_step}; source item {e.item_id}; '+('see typed closure record' if e.closed_at else 'open flow exception')])
    for e in r['reworks']:
        rework_rows.append(['REWORK-'+str(e.id),scope(e.item_id),None,e.kind,e.reason,None,None,_utc(e.opened_at),
            None,None,None,None,None,None,None,
            (e.close_notes or '')+(' Assigned badge: '+e.assigned if e.assigned else '')+
            (' Physical correction closed; reinspection is separate. See closure table.' if e.closed_at else ' Open physical correction.')])
    for e in r['holds']:
        rework_rows.append(['HOLD-'+str(e.id),_weld_name(weld_by_id[e.weld_id],r) if e.weld_id in weld_by_id else scope(e.item_id),None,'Quality hold',e.reason,None,
            names.get(e.opened_by,''),_utc(e.opened_at),None,None,None,None,None,None,None,
            (e.close_notes or '')+(' Hold closed; this is not an inspection result. See closure table.' if e.closed_at else ' Open hold.')])
    work.table(REWORK_HEADERS,rework_rows,title='Failures, repairs and holds')
    work.note_row('A repair opening is not a repair completion. QA requirement cycles are independent of weld-work cycles. Root visual evidence and all signed reviews remain in Inspection History.')
    work.table(('Record ID','Source item ID','Closure type','Closed (UTC)','Closed by name','Closed by badge','Status','Saved closure notes','Reference'),[
        ['REWORK-'+str(e.id),e.item_id,'Physical correction',_stamp(e.closed_at),names.get(e.closed_by,''),e.closed_by,
            'Closed; reinspection separate' if e.closed_at else 'Open',e.close_notes,None] for e in r['reworks']]+[
        ['HOLD-'+str(e.id),e.item_id,'Quality hold',_stamp(e.closed_at),names.get(e.closed_by,''),e.closed_by,
            'Closed hold' if e.closed_at else 'Open',e.close_notes,None] for e in r['holds']]+[
        ['FLOW-'+str(e.id),e.item_id,'QA flow exception',_stamp(e.closed_at),names.get(e.closed_by,''),e.closed_by,
            'Passed reinspection' if e.closed_at else 'Open',e.resolution,e.reference] for e in r['exceptions']],title='Correction and hold closures')
    _append_testing_rework(work,r)
    work.table(('Event ID','Source item ID','Record scope','Recorded (UTC)','Current directory name','Recorded badge','Event','Saved details'),[
        [str(e.id),e.item_id,scope(e.item_id),_utc(e.at),names.get(e.actor,''),e.actor,e.event,_json(e.details)] for e in r['audit']],title='Saved production and correction audit events')
    book.append(work)

    docs=_document_rows(s,r)
    dossier=s.get(DossierProject,r['context']['project_id']) if r['context'].get('project_id') else None
    coverage = Layout('Kelvion Requirements','Kelvion Job Packet crosswalk',
        'Requirement locations follow the supplied CLM design reference. Applicability, source revisions, original files and final QA approval require the controlled Job Packet.',
        (34,52,58,52,40,42,32,26,28,34,68))
    coverage.table(('Source / location','Requirement','Evidence needed','Recorded coverage','Report location','Coverage status'),[
        ['QF-QAS-100 Rev B, p8','Manufacturer contact, PO and advisements','Order identity and packet cover',
            'Manufacturer/contact configured' if dossier and dossier.manufacturer_name and dossier.manufacturer_contact else 'Manufacturer/contact not established',
            'Spool Record + controlled packet cover','QA review required'],
        ['QF-QAS-100 Rev B, p8','Table of contents; drawings and revisions; product data','Indexed original files and revisions',
            f'{len(docs)} document revision(s) indexed','Document index below','Originals and applicability require review'],
        ['QF-QAS-100 Rev B, p8','MTRs and material traceability','Each piece, both weld sides, heat and MTR file',
            f'{len(state["materials"])} current pieces; {len(r["mtrs"])} MTR document revisions','Material Traceability + Weld Register','Review exact links and missing values'],
        ['QF-QAS-100 Rev B, p8','ITP and examination / welding records','WPS, weld forms and QC reports',
            f'{len(r["welds"])} weld records; {len(r["work"])} work events','Weld Register + Work and Rework','Recorded evidence; QA review required'],
        ['QF-QAS-100 Rev B, p2','Visual examination and inspector certification','Per-weld results, identity, date and qualification',
            f'{len(r["evidence"])} requirement evidence events; {len(r["reviews"])} reviews','Inspection History','Acceptance and qualifications require review'],
        ['QF-QAS-100 Rev B, pp3–4','NDE sampling per approved scope','Approved sampling plan, weld map and reports',
            'No sampling compliance inferred from counts','Requirement register and document index','Apply approved plan'],
        ['CLM user requirement','Root visual inspection before fill/cap','Explicit root visual result, QA identity and time',
            str(sum(1 for req in r['requirements'] if _is_root(req)))+' explicit root visual requirements','Weld Register + Inspection History','Not established' if not any(_is_root(req) for req in r['requirements']) else 'Review current requirement status'],
        ['QF-QAS-100 Rev B, p7','Applicable torque records and coating sequence','Required sequence, results and references',
            'Recorded route history retained',route_sheet,'Applicability and evidence require review'],
        ['CAT024 §§6.1–6.4, pp6–8','Packing slip, CoC, MTRs and calibration','Indexed original documents',
            f'{len(docs)} document revisions indexed','Document index below','Originals require review'],
        ['QF-QAS001 C01/C02/K04/K05','Measurements, NDT qualifications, maps and reports','Measured values and qualified personnel',
            'Saved measurements and evidence retained','Inspection History + document index','QA review required'],
        ['QF-QAS001 H01','Nonconformity cause, correction, signatures and dates','Every failure, correction and reviewed closure',
            f'{len(rework_rows)} repair, exception, rework or hold records','Work and Rework','Open status and closure evidence retained'],
        ['QF-QAS001 D04','Pre-shipment approval when invoked','Applicable written approval and released packet',
            'No approval inferred from this spreadsheet','Controlled Job Packet','Applicability and approval require review'],
    ])
    coverage.table(('Document ID','Kind / reference','Record scope','Filename / title','Revision','Version','SHA-256','Recorded (UTC)',
        'Current directory name','Recorded badge','File path','Saved reference'),docs,title='Document index')
    coverage.note_row('Application file paths require an authenticated FabTrace session. References alone do not supply file contents. All retained revisions are listed; older documents are not automatically current acceptance evidence.')
    book.append(coverage)
    return book


def _write_record(s,item_id,created_at):
    r=_load_record(s,item_id,created_at)
    output=tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES,mode='w+b')
    try:
        with tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES,mode='w+b') as overflow:
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
                writer=WorkbookWriter(archive,overflow)
                writer.next_sheet_id=1
                for layout in report_layouts(s,r):
                    _write_layout(writer,layout)
                # Exceptionally long saved evidence remains lossless in the
                # standard overflow sheet rather than being silently cut off.
                writer.write_overflow()
                writer.finish(created_at,styles_xml=REPORT_STYLES,title='CLM Fabrication Spool Record')
        output.seek(0)
        return output,_safe_filename(r['display'],item_id)
    except BaseException:
        output.close()
        raise


@contextmanager
def _snapshot(bind):
    engine=bind.engine if isinstance(bind,Connection) else bind
    with engine.connect() as raw:
        kind=raw.dialect.name
        connection=raw.execution_options(isolation_level='REPEATABLE READ') if kind=='postgresql' else raw
        with connection.begin():
            if kind=='postgresql':
                connection.execute(text('SET TRANSACTION READ ONLY'))
            elif kind=='sqlite':
                connection.exec_driver_sql('BEGIN')
            else:
                raise RuntimeError('Consistent spool exports support PostgreSQL and SQLite')
            with Session(bind=connection,autoflush=False) as session:
                yield session


def build_export(bind,item_ids,created_at=None):
    created_at=_utc(created_at or utcnow())
    with _snapshot(bind) as session:
        # Fail a foreign/missing selection before returning any partial archive.
        for identity in item_ids:
            item=session.get(Item,identity)
            if not item or not is_physical_spool(session,item) or item_is_removed(session,identity):
                raise HTTPException(404,'Active physical spool not found: '+identity)
        if len(item_ids)==1:
            file,name=_write_record(session,item_ids[0],created_at)
            return file,name,XLSX_MEDIA_TYPE
        output=tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES,mode='w+b')
        try:
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
                for identity in item_ids:
                    file,name=_write_record(session,identity,created_at)
                    try:
                        with archive.open(name,'w',force_zip64=True) as destination:
                            while chunk:=file.read(256*1024):
                                destination.write(chunk)
                    finally:
                        file.close()
            output.seek(0)
            return output,'fabtrace-spool-records-'+created_at.strftime('%Y%m%dT%H%M%SZ')+'.zip','application/zip'
        except BaseException:
            output.close()
            raise


def _download(item_ids,s):
    bind=s.get_bind()
    s.rollback()  # Release the authentication connection before the snapshot.
    file,name,media_type=build_export(bind,item_ids)
    file.seek(0,2)
    size=file.tell()
    file.seek(0)
    return StreamingResponse(_stream_file(file),media_type=media_type,
        headers={'Content-Disposition':f'attachment; filename="{name}"','Content-Length':str(size),'Cache-Control':'no-store'},
        background=BackgroundTask(file.close))


@router.post('/export')
def export_records(data:ExportSelection,u:Employee=Depends(auth),s:Session=Depends(db)):
    return _download(data.item_ids,s)


@router.get('/spools/{item_id}/record.xlsx')
def export_record(item_id:str,u:Employee=Depends(auth),s:Session=Depends(db)):
    return _download([item_id],s)


@router.get('/spools')
def spool_choices(project_id:str|None=Query(default=None,max_length=80),u:Employee=Depends(auth),s:Session=Depends(db)):
    plans={row.item_id:row for row in s.scalars(select(SpoolPlan))}
    registered={row.item_id:row for row in s.scalars(select(OrderSpool))}
    assemblies={row.item_id:row for row in s.scalars(select(OrderAssembly))}
    groups={row.id:row for row in s.scalars(select(OrderGpn))}
    orders={row.project_id:row for row in s.scalars(select(PurchaseOrder))}
    qr={row.item_id:row.display_code for row in s.scalars(select(SpoolQrIdentity))}
    result=[]
    for item in s.scalars(select(Item).where(Item.kind!='Assembly',item_not_removed(Item.id)).order_by(Item.id)):
        if item.id not in plans and item.id not in registered and item.kind!='Spool':
            continue
        plan=plans.get(item.id)
        physical=registered.get(item.id)
        parent=physical.assembly_id if physical else plan.assembly_id if plan else None
        assembly=assemblies.get(parent)
        group=groups.get(assembly.gpn_id) if assembly else None
        project=group.project_id if group else plan.project_id if plan else None
        if project_id is not None and project!=project_id:
            continue
        order=orders.get(project)
        result.append({'item_id':item.id,'display_code':qr.get(item.id,item.id),'project_id':project,
            'purchase_order':order.purchase_order if order else '', 'customer':order.customer if order else '',
            'gpn':business_gpn(group) if group else '', 'assembly_number':group.assembly_number if group else '', 'assembly_id':parent})
    result.sort(key=lambda row:(row['purchase_order'].casefold(),row['gpn'].casefold(),row['assembly_number'].casefold(),row['display_code'].casefold()))
    return {'spools':result,'max_selection':MAX_SELECTED_SPOOLS}
