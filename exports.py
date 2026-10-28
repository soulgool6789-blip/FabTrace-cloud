"""Read-only, allowlisted business-data export to a standard XLSX workbook.

Uses streaming SQL results and Python's standard ZIP/XML libraries. No secret
columns are selected and no export audit row or other database mutation occurs.
Import this extension after main's shared models and tracking registration.
"""

import datetime as dt
import json
import math
import re
import tempfile
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby
from types import SimpleNamespace
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import JSON, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from main import APP_VERSION, Audit, Employee, Inspection, Item, Rework, auth, db, permit, utcnow
from tracking import (
    Project, RequirementEvidence, RequirementReview, RequirementTemplate,
    SpoolPlan, Subproject, TrackingHold, Weld, WeldRepair, WeldRequirement, WeldWork,
)
from production import SpoolProcessEvent, process_snapshot
from flow import FlowPlan, FlowEvent, FlowException, ComponentLink, STEPS as FLOW_STEPS, VERSION as FLOW_VERSION


router = APIRouter(prefix='/api/exports', tags=['exports'])
EXCEL_MAX_ROWS = 1_048_576
EXCEL_MAX_CELL_CHARS = 32_767  # UTF-16 code units, not Python code points.
TEMP_MEMORY_BYTES = 8 * 1024 * 1024
XLSX_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
SHEET_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


@dataclass(frozen=True)
class TableSpec:
    model: type
    sheet: str
    columns: tuple[str, ...]
    keys: tuple[str, ...]

    @property
    def table(self):
        return self.model.__tablename__


@dataclass(frozen=True)
class ExporterIdentity:
    badge: str
    name: str
    role: str


def _spec(model, sheet, columns, keys='id'):
    return TableSpec(model, sheet, tuple(columns.split()), tuple(keys.split()))


# Deliberately explicit: adding a model column in the future does not silently
# add it to an export. The employee secret field is never selected.
TABLE_SPECS = (
    _spec(Employee, 'Employees', 'badge name role active created_at', 'badge'),
    _spec(Item, 'Items', 'id description kind project google_part_number drawing location handler welds_required welds_done dimensional weld dimension_at weld_at last_work_at reinspection_due on_hold released released_at released_by created_at updated_at'),
    _spec(Inspection, 'Inspections', 'id item_id kind result inspector report measurements at'),
    _spec(Rework, 'Reworks', 'id item_id kind reason assigned opened_at closed_at closed_by close_notes'),
    _spec(Audit, 'Audit events', 'id item_id actor event details at'),
    _spec(Project, 'Projects', 'id name client description created_by created_at'),
    _spec(Subproject, 'Subprojects', 'id project_id name description created_by created_at'),
    _spec(SpoolPlan, 'Spool plans', 'item_id project_id subproject_id assembly_id planned_welds drawing_revision due_date notes zero_weld_reason version created_by created_at updated_at', 'item_id'),
    _spec(RequirementTemplate, 'Weld templates', 'id code name revision source requirements required_operations created_by created_at'),
    _spec(Weld, 'Welds', 'id item_id number description joint_type size wall_thickness drawing_revision component_a heat_a mtr_a component_b heat_b mtr_b wps wps_revision template_id required_operations version cycle completed_at completed_by created_by created_at updated_at'),
    _spec(WeldRequirement, 'Requirements', 'id item_id weld_id code label stage allow_na evidence_required source owner_role check_kind status version cycle template_id created_by created_at updated_at'),
    _spec(RequirementEvidence, 'Evidence', 'id requirement_id cycle reference notes result actor at'),
    _spec(RequirementReview, 'Reviews', 'id requirement_id evidence_id cycle decision notes actor at'),
    _spec(WeldWork, 'Weld work', 'id weld_id cycle operation notes actor at'),
    _spec(WeldRepair, 'Weld repairs', 'id weld_id cycle reason opened_by opened_at'),
    _spec(TrackingHold, 'Holds', 'id item_id weld_id reason opened_by opened_at closed_by closed_at close_notes'),
    _spec(SpoolProcessEvent, 'Process events', 'id item_id sequence event process_key process_name actor at notes'),
    _spec(FlowPlan, 'Flow plans', 'item_id route current_step status version expected_children baseline_step baseline_reference baseline_reason material_reference started_by started_at step_entered_at updated_at completed_at shipped_at carrier shipment_reference destination delivered_at receipt_reference recipient', 'item_id'),
    _spec(FlowEvent, 'Flow events', 'id item_id sequence action step actor at reference notes data'),
    _spec(FlowException, 'Flow exceptions', 'id item_id step return_step reason reference opened_by opened_at closed_by closed_at resolution'),
    _spec(ComponentLink, 'Component links', 'component_id spool_id assigned_by assigned_at', 'component_id'),
)

FLOW_STEP_COLUMNS = ('definition_version', 'number', 'title', 'route', 'section', 'roles', 'checks',
                     'requires_scan', 'requires_handoff', 'requires_reference', 'qa', 'return_steps')

PROCESS_CONTEXT_COLUMNS = ('project_id', 'subproject_id', 'item_id', 'description')
PROCESS_TIME_COLUMNS = ('elapsed_seconds', 'active_seconds', 'paused_seconds',
                        'elapsed_hours', 'active_hours', 'paused_hours')
PROCESS_VISIT_COLUMNS = PROCESS_CONTEXT_COLUMNS + (
    'visit_id', 'process_key', 'process_name', 'group_key', 'status', 'started_at', 'ended_at',
    'started_by', 'ended_by', 'end_reason',
) + PROCESS_TIME_COLUMNS + ('as_of',)
PROCESS_TOTAL_COLUMNS = PROCESS_CONTEXT_COLUMNS + (
    'process_key', 'process_name', 'group_key', 'visits',
) + PROCESS_TIME_COLUMNS + ('as_of',)

OVERFLOW_COLUMNS = (
    'overflow_id', 'source_table', 'source_sheet', 'row_number', 'row_id',
    'column', 'chunk_index', 'chunk_count', 'value_type', 'text',
)

RELATIONSHIPS = (
    'items.handler -> employees.badge; items.id is the original physical item identity.',
    'inspections.item_id / reworks.item_id / audit_events.item_id -> items.id. Audit item_id may be blank for account or project events.',
    'inspections.inspector -> employees.badge; rework assigned / closed_by and audit actor retain employee badge identities.',
    'tracking_subprojects.project_id -> tracking_projects.id.',
    'tracking_spool_plans.item_id -> items.id; one plan enrolls one existing physical item.',
    'tracking_spool_plans.project_id -> tracking_projects.id; subproject_id -> tracking_subprojects.id.',
    'tracking_spool_plans.assembly_id -> items.id (optional Assembly). Assembly links organize records; they do not certify child-spool release.',
    'tracking_welds.item_id -> items.id; number is unique within its spool. id is the permanent weld identity.',
    'tracking_welds.template_id -> tracking_requirement_templates.id. Each template row is an immutable revision.',
    'tracking_requirements.item_id -> items.id; weld_id -> tracking_welds.id. Blank weld_id identifies a spool-level requirement.',
    'tracking_requirements.template_id -> tracking_requirement_templates.id.',
    'tracking_requirement_evidence.requirement_id -> tracking_requirements.id.',
    'tracking_requirement_reviews.requirement_id -> tracking_requirements.id; evidence_id -> tracking_requirement_evidence.id.',
    'Requirement evidence and reviews carry their verification cycle. Earlier cycles remain historical; they are not current acceptance.',
    'tracking_weld_work.weld_id / tracking_weld_repairs.weld_id -> tracking_welds.id. Their cycle identifies physical work/repair history.',
    'tracking_holds.item_id -> items.id; optional weld_id -> tracking_welds.id.',
    'tracking_process_events.item_id -> items.id; actor -> employees.badge. sequence is the immutable per-spool order and concurrency version.',
    'Process visits and Process totals are calculated reports from Process events, grouped by item_id and process. visit_id is the sequence that started that visit, not a separate database row.',
    'flow_plans.item_id / flow_events.item_id / flow_exceptions.item_id -> items.id. Flow event sequence is the per-item traveler revision; it differs from the separate process-timer sequence.',
    'flow_component_links.component_id -> individual component items.id; spool_id -> the parent spool items.id. SpoolPlan.assembly_id remains the spool-to-assembly relationship.',
    'Process reports use the current SpoolPlan project/subproject, or the assigned parent spool plan for a component. Unassigned component project/subproject cells remain blank; past project assignments are not frozen in timing events.',
    'Flow steps contains the current numbered CLM process definitions. Recorded event data retains its own definition version and step/checklist snapshot.',
    'Flow plans stores shipment and receipt details. shipped_at confirms dispatch; delivered_at exists only after a separately recorded delivery receipt.',
    'created_by, actor, completed_by, opened_by and closed_by badge fields retain the recorded employee identities.',
    'Audit details, template requirements and required_operations are JSON text. Preserve the JSON when using these records elsewhere.',
)


def _utf16_len(value):
    return sum(2 if ord(char) > 0xFFFF else 1 for char in value)


def _text_chunks(value, limit=None):
    limit = EXCEL_MAX_CELL_CHARS if limit is None else limit
    if limit < 2:
        raise ValueError('Excel text chunk limit must allow at least two UTF-16 units')
    start = 0
    units = 0
    for index, char in enumerate(value):
        width = 2 if ord(char) > 0xFFFF else 1
        if units + width > limit:
            yield value[start:index]
            start = index
            units = 0
        units += width
    yield value[start:]


def _xml_text(value):
    # OOXML escape syntax is itself escaped when it was literal source text.
    # Unsupported XML characters are preserved using the OOXML string escape,
    # rather than silently removed from reports or audit details.
    value = re.sub(r'_x[0-9A-Fa-f]{4}_', lambda match: '_x005F_' + match.group(0)[1:], value)
    chars = []
    for char in value:
        code = ord(char)
        valid = code in (9, 10, 13) or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF
        chars.append(char if valid else f'_x{code:04X}_')
    # Literal CR would be normalized to LF by an XML reader; a character
    # reference preserves the original CR and CRLF sequences.
    return escape(''.join(chars)).replace('\r', '&#13;')


def _column_name(index):
    name = ''
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _utc(value):
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def _date_serial(value):
    if isinstance(value, dt.datetime):
        naive = _utc(value).replace(tzinfo=None)
    else:
        naive = dt.datetime.combine(value, dt.time.min)
    return (naive - dt.datetime(1899, 12, 30)).total_seconds() / 86400


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _width(header):
    if header in ('details', 'requirements', 'notes', 'measurements', 'reason', 'close_notes', 'text', 'value'):
        return 64
    if header in ('description', 'source', 'reference', 'label'):
        return 44
    if header.endswith('_at') or header == 'at':
        return 27
    if header.endswith('_id') or header in ('id', 'number', 'item_id', 'badge', 'column'):
        return 28
    return min(32, max(16, len(header) + 3))


@dataclass
class SheetRecord:
    id: int
    name: str
    table: str
    rows: int
    columns: int
    group: str


class WorkbookWriter:
    def __init__(self, archive, overflow_file):
        self.archive = archive
        self.overflow_file = overflow_file
        self.sheets = []
        self.next_sheet_id = 2  # Export info is always sheet1.xml.
        self.overflow_cells = 0
        self.overflow_rows = 0

    def overflow(self, value, context, value_type):
        self.overflow_cells += 1
        identifier = f'OVF-{self.overflow_cells:09d}'
        # At most one source value is held at a time, already supplied by SQL.
        chunks = list(_text_chunks(value))
        for index, chunk in enumerate(chunks, start=1):
            row = [identifier, context['table'], context['sheet'], context['row'],
                   context['row_id'], context['column'], index, len(chunks), value_type, chunk]
            self.overflow_file.write((json.dumps(row, ensure_ascii=True) + '\n').encode('utf-8'))
            self.overflow_rows += 1
        return f'[Text overflow {identifier}; {len(chunks)} chunks]'

    def cell(self, reference, value, context, header=False, overflow_allowed=True, is_json=False):
        if is_json:
            value = _json_text(value)
            value_type = 'json'
        else:
            value_type = 'text'
        if value is None:
            return f'<c r="{reference}"/>'
        if isinstance(value, bool):
            return f'<c r="{reference}" t="b"><v>{int(value)}</v></c>'
        if isinstance(value, (dt.datetime, dt.date)):
            return f'<c r="{reference}" s="2"><v>{_date_serial(value):.17g}</v></c>'
        if isinstance(value, (int, float, Decimal)):
            if not isinstance(value, int) and not math.isfinite(value):
                value = str(value)
            else:
                return f'<c r="{reference}" t="n"><v>{value}</v></c>'
        if not isinstance(value, str):
            value = str(value)
        if _utf16_len(value) > EXCEL_MAX_CELL_CHARS:
            if not overflow_allowed:
                raise ValueError('Generated export metadata exceeded the configured Excel cell limit')
            value = self.overflow(value, context, value_type)
        style = ' s="1"' if header else ''
        # No formula element or shared-string guessing: IDs, leading zeros,
        # URLs and strings beginning =,+,-,@ remain literal inline strings.
        return f'<c r="{reference}" t="inlineStr"{style}><is><t xml:space="preserve">{_xml_text(value)}</t></is></c>'

    def write_rows(self, base_name, table, headers, rows, row_count, *, json_columns=(), group='data', first_id=None, overflow_allowed=True):
        if EXCEL_MAX_ROWS < 2:
            raise ValueError('Excel sheet limit must leave room for a header and data')
        capacity = EXCEL_MAX_ROWS - 1
        parts = max(1, math.ceil(row_count / capacity))
        iterator = iter(rows)
        remaining = row_count
        for part in range(1, parts + 1):
            count = min(remaining, capacity)
            name = base_name if part == 1 else f'{base_name} {part}'
            if len(name) > 31:
                name = base_name[:31 - len(str(part)) - 1] + ' ' + str(part)
            sheet_id = first_id if part == 1 and first_id is not None else self.next_sheet_id
            if sheet_id == self.next_sheet_id:
                self.next_sheet_id += 1
            self.sheets.append(SheetRecord(sheet_id, name, table, count, len(headers), group))
            end_column = _column_name(len(headers))
            with self.archive.open(f'xl/worksheets/sheet{sheet_id}.xml', 'w', force_zip64=True) as output:
                def write(value):
                    output.write(value.encode('utf-8'))
                write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
                write(f'<worksheet xmlns="{SHEET_NS}"><dimension ref="A1:{end_column}{count + 1}"/>')
                write('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/><cols>')
                for index, header in enumerate(headers, start=1):
                    write(f'<col min="{index}" max="{index}" width="{_width(header)}" customWidth="1"/>')
                write('</cols><sheetData><row r="1" ht="27" customHeight="1">')
                for index, header in enumerate(headers, start=1):
                    write(self.cell(f'{_column_name(index)}1', header, {}, header=True, overflow_allowed=False))
                write('</row>')
                for row_number in range(2, count + 2):
                    try:
                        values, row_id = next(iterator)
                    except StopIteration:
                        raise RuntimeError('Snapshot row count changed during export') from None
                    write(f'<row r="{row_number}">')
                    for index, (header, value) in enumerate(zip(headers, values), start=1):
                        context = {'table': table, 'sheet': name, 'row': row_number, 'row_id': row_id, 'column': header}
                        if value is not None and (header == 'id' or header.endswith('_id')):
                            value = str(value)
                        write(self.cell(f'{_column_name(index)}{row_number}', value, context,
                                        is_json=header in json_columns, overflow_allowed=overflow_allowed))
                    write('</row>')
                write(f'</sheetData><autoFilter ref="A1:{end_column}{count + 1}"/><pageMargins left="0.25" right="0.25" top="0.4" bottom="0.4" header="0.2" footer="0.2"/></worksheet>')
            remaining -= count
        sentinel = object()
        if next(iterator, sentinel) is not sentinel:
            raise RuntimeError('Snapshot produced more rows than its count')

    def write_overflow(self):
        if not self.overflow_rows:
            return
        self.overflow_file.seek(0)
        def rows():
            for line in self.overflow_file:
                values = json.loads(line)
                yield values, _json_text({'overflow_id': values[0], 'chunk_index': values[6]})
        self.write_rows('Text overflow', 'overflow_chunks', OVERFLOW_COLUMNS, rows(),
                        self.overflow_rows, group='overflow', overflow_allowed=False)

    def finish(self, created_at):
        ordered = sorted(self.sheets, key=lambda row: (0 if row.group == 'manifest' else 1, row.id))
        sheets_xml = ''.join(f'<sheet name={quoteattr(row.name)} sheetId="{row.id}" r:id="rId{row.id}"/>' for row in ordered)
        self.archive.writestr('xl/workbook.xml', f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{SHEET_NS}" xmlns:r="{REL_NS}"><bookViews><workbookView/></bookViews><sheets>{sheets_xml}</sheets></workbook>')
        relationships = ''.join(f'<Relationship Id="rId{row.id}" Type="{REL_NS}/worksheet" Target="worksheets/sheet{row.id}.xml"/>' for row in self.sheets)
        relationships += f'<Relationship Id="rIdStyles" Type="{REL_NS}/styles" Target="styles.xml"/>'
        self.archive.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + relationships + '</Relationships>')
        overrides = ''.join(f'<Override PartName="/xl/worksheets/sheet{row.id}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for row in self.sheets)
        self.archive.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>' + overrides + '</Types>')
        self.archive.writestr('_rels/.rels', f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL_NS}/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="{REL_NS}/extended-properties" Target="docProps/app.xml"/></Relationships>')
        self.archive.writestr('xl/styles.xml', STYLES_XML)
        stamp = _utc(created_at).isoformat().replace('+00:00', 'Z')
        self.archive.writestr('docProps/core.xml', f'<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>FabTrace Cloud</dc:creator><dc:title>FabTrace business data export</dc:title><dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created></cp:coreProperties>')
        self.archive.writestr('docProps/app.xml', '<?xml version="1.0" encoding="UTF-8"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>FabTrace Cloud</Application></Properties>')


STYLES_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd hh:mm:ss.000 &quot;UTC&quot;"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF243F50"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def _manifest_rows(created_at, exporter, writer, database_kind):
    rows = []
    def add(section, entry, value):
        # Metadata also respects cell limits without generating a second-order
        # overflow sheet. Part identifies successive pieces of the same entry.
        chunks = _text_chunks(value) if isinstance(value, str) else [value]
        for part, chunk in enumerate(chunks, start=1):
            rows.append(([section, entry, part, chunk], _json_text({'section': section, 'entry': entry, 'part': part})))
    add('Export', 'Product', 'FabTrace Cloud business data')
    add('Export', 'Version', APP_VERSION)
    add('Export', 'Snapshot UTC', created_at)
    add('Export', 'UTC ISO timestamp', _utc(created_at).isoformat())
    add('Export', 'Exporter badge', exporter.badge)
    add('Export', 'Exporter name', exporter.name)
    add('Export', 'Exporter role', exporter.role)
    add('Export', 'Snapshot method', 'PostgreSQL REPEATABLE READ READ ONLY, separate connection' if database_kind == 'postgresql' else 'SQLite explicit read transaction, separate connection')
    add('Export', 'Scope', f'All rows from the {len(TABLE_SPECS)} explicitly allowlisted business tables, including inactive employees, prior evidence/reviews, completed repairs, closed holds, production process events and numbered travelers. Two process reports summarize recorded visits and totals; Flow steps supplies the current 24-step definition lookup. No screen pagination limits.')
    add('Export', 'Database writes', 'None. This export does not append audit records or alter application data.')
    add('Exclusions', 'Authentication', 'Employee PIN hashes, PINs, passwords, session tokens, JWT secrets, database credentials and environment variables are excluded. Employee roster includes badge, name, role, active and created_at only.')
    add('Exclusions', 'External documents', 'References and URLs are exported as stored. External report/MTR contents and linked files are not fetched or embedded.')
    add('Exclusions', 'Unknown tables', 'Future or unlisted tables/columns are not exported automatically. This is a business-data workbook, not a complete database restore backup.')
    add('Format', 'Literal text', 'Text and identifiers, including integer primary/foreign keys, are literal Excel strings. This preserves identifiers beyond Excel numeric precision and leading zeros. Values beginning with =,+,-,@ remain text. No formulas, macros or external-link objects are generated.')
    add('Format', 'Date/time', 'Date/time cells are native Excel numeric date/time values normalized to UTC. Naive database timestamps are interpreted as UTC; Excel display uses milliseconds.')
    add('Format', 'JSON', 'JSON data is retained as compact JSON text. Array order and all object keys/values are preserved.')
    add('Format', 'Empty values', 'SQL NULL is an empty cell. Empty strings remain explicit text cells.')
    add('Process timing', 'Meaning', 'Elapsed time is calendar clock time in a recorded process visit. Active time is time while its timer was running; paused time is time explicitly marked paused. These are spool durations, not labor/person-hours or working-shift hours.')
    add('Process timing', 'Coverage', 'Timing begins with the first recorded start, with no inferred earlier history. Idle gaps after Finish and before the next Start are not assigned to a process. Repeated visits are kept separately and summed in Process totals. Unstarted spools have no process report rows.')
    add('Process timing', 'Open visits', 'Open visits are calculated as of the report as_of timestamp, using the same read-only database snapshot as the raw events. Paused time remains part of elapsed time. Final release closes an open visit. Finished visits do not keep accumulating time.')
    add('Process timing', 'Analysis', 'Process visits has one row per recorded visit; Process totals has one row per spool/process. Seconds and decimal hours are numeric and may be summed or used in Excel PivotTables by project_id, subproject_id, item_id and process_name. Do not add report totals to raw business-row counts.')
    add('Process flow', 'Route scopes', 'Components use steps 1-8; spools use 9-16; assemblies use 17-24. Parent/child IDs link the routes. Advancing a traveler records a checklist, handoff or review; underlying weld and quality gates remain authoritative.')
    add('Process flow', 'History and baselines', 'Earlier steps before an explicitly documented baseline are not recorded completions. Failed inspections append exceptions and return to a recorded rework step; earlier attempts remain in Flow events and Process visits. Generic quality release cannot bypass the required traveler inspection.')
    add('Process flow', 'References and receipts', 'References identify external purchase orders, BOMs, reports, shipping documents and delivery receipts. Files are not embedded. A shipment confirmation does not infer delivery; receipt confirmation records its own time, recipient and reference.')
    add('Format', 'Continuation sheets', f'Each sheet holds at most {EXCEL_MAX_ROWS:,} rows including its repeated header. Additional data continues on sheets named with a numeric suffix.')
    add('Format', 'Long text', f'Values exceeding {EXCEL_MAX_CELL_CHARS:,} UTF-16 units are replaced by an OVF reference. Reconstruct the full original value by concatenating Text overflow chunks for that overflow_id in chunk_index order.')
    add('Format', 'Long-text cells', writer.overflow_cells)
    add('Format', 'Overflow chunk rows', writer.overflow_rows)
    for index, relationship in enumerate(RELATIONSHIPS, start=1):
        add('Relationships', f'R{index:02}', relationship)
    add('Counts', 'How to read counts', 'Data-row counts exclude headers. Continuation-sheet counts are separate. Process reports are calculated rows and Flow steps is definition data; neither adds database records. Manifest sheets are descriptive metadata.')
    for sheet in writer.sheets:
        add('Sheet rows', sheet.name, sheet.rows)
        add('Source table', sheet.name, sheet.table)
    return rows


def _write_process_reports(connection, writer, created_at):
    """Calculate reports within the raw export's snapshot, one spool at a time."""
    events_table = SpoolProcessEvent.__table__
    event_columns = tuple(events_table.columns.keys())
    component_plan = SpoolPlan.__table__.alias('component_spool_plan')
    query = (
        select(*events_table.c, Item.description,
               func.coalesce(SpoolPlan.project_id, component_plan.c.project_id).label('project_id'),
               func.coalesce(SpoolPlan.subproject_id, component_plan.c.subproject_id).label('subproject_id'))
        .select_from(events_table.join(Item.__table__, events_table.c.item_id == Item.id)
                     .outerjoin(SpoolPlan.__table__, events_table.c.item_id == SpoolPlan.item_id)
                     .outerjoin(ComponentLink.__table__, events_table.c.item_id == ComponentLink.component_id)
                     .outerjoin(component_plan, ComponentLink.spool_id == component_plan.c.item_id))
        .order_by(events_table.c.item_id, events_table.c.sequence)
    )
    with tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b') as visits_file, \
            tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b') as totals_file:
        visit_count = total_count = 0
        result = connection.execution_options(stream_results=True, yield_per=1000).execute(query)
        try:
            for item_id, spool_rows in groupby(result.mappings(), key=lambda row: row['item_id']):
                rows = list(spool_rows)
                events = [SimpleNamespace(**{key: row[key] for key in event_columns}) for row in rows]
                snapshot = process_snapshot(None, item_id, as_of=created_at, events=events)
                context = {key: rows[0][key] for key in PROCESS_CONTEXT_COLUMNS}
                for source, target, columns, is_visit in (
                    (snapshot['visits'], visits_file, PROCESS_VISIT_COLUMNS, True),
                    (snapshot['by_process'], totals_file, PROCESS_TOTAL_COLUMNS, False),
                ):
                    for record in source:
                        values = {**record, **context, 'as_of': snapshot['as_of']}
                        if is_visit:
                            values['visit_id'] = record['id']
                        for measure in ('elapsed', 'active', 'paused'):
                            values[measure + '_hours'] = record[measure + '_seconds'] / 3600
                        target.write((json.dumps([values.get(key) for key in columns],
                                                 ensure_ascii=True) + '\n').encode('utf-8'))
                        if is_visit:
                            visit_count += 1
                        else:
                            total_count += 1
        finally:
            result.close()

        for name, source, columns, count in (
            ('Process visits', visits_file, PROCESS_VISIT_COLUMNS, visit_count),
            ('Process totals', totals_file, PROCESS_TOTAL_COLUMNS, total_count),
        ):
            source.seek(0)
            def report_rows(source=source, columns=columns):
                for line in source:
                    values = json.loads(line)
                    record = dict(zip(columns, values))
                    for index, key in enumerate(columns):
                        if values[index] is not None and key in ('started_at', 'ended_at', 'as_of'):
                            values[index] = dt.datetime.fromisoformat(values[index].replace('Z', '+00:00'))
                    keys = ('item_id', 'visit_id') if 'visit_id' in record else ('item_id', 'process_key', 'process_name')
                    yield values, _json_text({key: record[key] for key in keys})
            writer.write_rows(name, 'derived:tracking_process_events', columns, report_rows(), count, group='report')


def _write_flow_steps(writer):
    def rows():
        for step in FLOW_STEPS:
            record = {'definition_version': FLOW_VERSION, **step}
            yield [record[key] for key in FLOW_STEP_COLUMNS], _json_text({'number': step['number'], 'version': FLOW_VERSION})
    writer.write_rows('Flow steps', 'definition:CLM-process-flow', FLOW_STEP_COLUMNS, rows(), len(FLOW_STEPS),
                      json_columns={'roles', 'checks', 'return_steps'}, group='definition')


def build_workbook(bind, exporter, created_at=None):
    """Return a rewound temporary XLSX; caller owns and must close the file."""
    created_at = created_at or utcnow()
    engine = bind.engine if isinstance(bind, Connection) else bind
    output = tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b')
    try:
        with tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b') as overflow_file:
            with engine.connect() as raw_connection:
                kind = raw_connection.dialect.name
                connection = raw_connection.execution_options(isolation_level='REPEATABLE READ') if kind == 'postgresql' else raw_connection
                with connection.begin():
                    if kind == 'postgresql':
                        connection.execute(text('SET TRANSACTION READ ONLY'))
                    elif kind == 'sqlite':
                        # SQLite's legacy transaction mode does not start a
                        # transaction for SELECT alone. Begin it explicitly.
                        connection.exec_driver_sql('BEGIN')
                    else:
                        raise RuntimeError('Consistent Excel export supports PostgreSQL and SQLite')
                    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
                        writer = WorkbookWriter(archive, overflow_file)
                        for spec in TABLE_SPECS:
                            table = spec.model.__table__
                            columns = [table.c[name] for name in spec.columns]
                            row_count = connection.scalar(select(func.count()).select_from(table))
                            query = select(*columns).order_by(*(table.c[name] for name in spec.keys))
                            result = connection.execution_options(stream_results=True, yield_per=1000).execute(query)
                            def rows(result=result, spec=spec):
                                for mapping in result.mappings():
                                    row_id = _json_text({key: mapping[key] for key in spec.keys})
                                    yield [mapping[name] for name in spec.columns], row_id
                            try:
                                writer.write_rows(spec.sheet, spec.table, spec.columns, rows(), row_count,
                                    json_columns={name for name in spec.columns if isinstance(table.c[name].type, JSON)})
                            finally:
                                result.close()
                        _write_process_reports(connection, writer, created_at)
                        _write_flow_steps(writer)
                        writer.write_overflow()
                        manifest = _manifest_rows(created_at, exporter, writer, kind)
                        writer.write_rows('Export info', 'export_manifest', ('section', 'entry', 'part', 'value'),
                            iter(manifest), len(manifest), group='manifest', first_id=1, overflow_allowed=False)
                        writer.finish(created_at)
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise


def _stream_file(file):
    try:
        while chunk := file.read(256 * 1024):
            yield chunk
    finally:
        file.close()


@router.get('/excel')
def export_excel(u: Employee = Depends(auth), s: Session = Depends(db)):
    permit(u, 'admin')
    created_at = utcnow()
    exporter = ExporterIdentity(badge=u.badge, name=u.name, role=u.role)
    bind = s.get_bind()
    # Authentication only read this session. Release that connection before
    # opening the independent snapshot so concurrent downloads cannot each
    # hold a pool slot while waiting for a second one.
    s.rollback()
    file = build_workbook(bind, exporter, created_at)
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    filename = 'fabtrace-export-' + created_at.strftime('%Y%m%dT%H%M%SZ') + '.xlsx'
    return StreamingResponse(_stream_file(file), media_type=XLSX_MEDIA_TYPE,
        headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Content-Length': str(size)},
        background=BackgroundTask(file.close))
