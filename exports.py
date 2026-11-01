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
from quality import (QualityWorkspace, QualityRequirement, QualityDocument, QualityEvidence,
                     QualityAction, QualityReview, QualityEvent, workspace_detail)
from dossier import (DossierProject, DossierEntry, DossierDocument, DossierReview,
                     DossierIssue, DossierHandover, DossierEvent, item_detail)
from progress import project_rows, summarize as progress_summary
from parts import SpoolPartsPlan, PartLine, PartAllocation, PartEvent, parts_snapshot
from transfers import ItemTransferState, TransferLocation
from administration import EmployeeAccessState, EmployeeRemovalState
from orders import PurchaseOrder, OrderGpn, OrderAssembly
from order_setup import OrderAssemblyRequirement, OrderSpoolRequirement
from order_spools import OrderSpool, SpoolQrIdentity
from spool_boms import SpoolBomTrace, SpoolBomMaterial, SpoolBomEvent
from spool_receiving import SpoolArrivalInspection, SpoolMaterialInspection, SpoolMtrDocument
from spool_documents import SpoolDocumentSet, SpoolDocument, SpoolDocumentFileLink
from removals import RecordRemoval


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
    _spec(EmployeeAccessState, 'Employee access states', 'badge version session_version updated_by updated_at', 'badge'),
    _spec(EmployeeRemovalState, 'Employee removal states', 'badge removed removed_at removed_by removal_reason restored_at restored_by restoration_reason', 'badge'),
    _spec(RecordRemoval, 'Removed record states', 'kind record_id removed version batch_id root_kind root_id reason changed_by changed_at', 'kind record_id'),
    _spec(Item, 'Items', 'id description kind project google_part_number drawing location handler welds_required welds_done dimensional weld dimension_at weld_at last_work_at reinspection_due on_hold released released_at released_by created_at updated_at'),
    _spec(Inspection, 'Inspections', 'id item_id kind result inspector report measurements at'),
    _spec(Rework, 'Reworks', 'id item_id kind reason assigned opened_at closed_at closed_by close_notes'),
    _spec(Audit, 'Audit events', 'id item_id actor event details at'),
    _spec(ItemTransferState, 'Item transfer states', 'item_id version location_id operational_status created_at updated_by updated_at', 'item_id'),
    _spec(TransferLocation, 'Transfer locations', 'id label normalized_label active version created_by created_at updated_by updated_at'),
    _spec(Project, 'Projects', 'id name client description created_by created_at'),
    _spec(PurchaseOrder, 'Purchase orders', 'project_id purchase_order normalized_number customer normalized_customer notes version created_by created_at updated_at', 'project_id'),
    _spec(OrderGpn, 'Order GPNs', 'id project_id gpn normalized_gpn description created_by created_at updated_at'),
    _spec(OrderAssembly, 'Order assemblies', 'item_id gpn_id assembly_part_number required_spools notes created_by created_at updated_at', 'item_id'),
    _spec(OrderAssemblyRequirement, 'Assembly quantity plans', 'gpn_id assembly_quantity created_by created_at updated_at', 'gpn_id'),
    _spec(OrderSpool, 'Registered order spools', 'item_id assembly_id requirement_id created_by created_at', 'item_id'),
    _spec(SpoolQrIdentity, 'Spool QR labels', 'item_id spool_number normalized_number sequence display_code normalized_code created_by created_at source', 'item_id'),
    _spec(OrderSpoolRequirement, 'Spool quantity plans', 'id gpn_id spool_number normalized_number quantity_per_assembly active created_by created_at updated_at'),
    _spec(SpoolBomTrace, 'Spool BOM trace configs', 'spool_id catalog_id spool_number source_sha256 definition version created_by created_at updated_by updated_at', 'spool_id'),
    _spec(SpoolBomMaterial, 'Spool BOM material pieces', 'spool_id piece_key supplier supplier_piece_id heat_number mtr_reference mtr_url notes updated_by updated_at', 'spool_id piece_key'),
    _spec(SpoolBomEvent, 'Spool BOM trace events', 'spool_id version actor at reason changes', 'spool_id version'),
    _spec(SpoolArrivalInspection, 'Spool arrival inspections', 'id spool_id version result actor at reference notes checks basis_sha256 basis'),
    _spec(SpoolMaterialInspection, 'Material QA-001 inspections', 'id spool_id piece_key version check_code result actor at reference notes basis_sha256 basis'),
    _spec(SpoolMtrDocument, 'Spool MTR documents', 'id spool_id reference reference_key version revision filename media_type size_bytes sha256 selection_sha256 page_count source_files scope_snapshot uploaded_by uploaded_at reason'),
    _spec(SpoolDocumentSet, 'Spool document scopes', 'id requirement_id spool_id scope_snapshot version created_by created_at'),
    _spec(SpoolDocument, 'Spool uploaded documents', 'id set_id kind version filename media_type size_bytes sha256 selection_sha256 page_count revision uploaded_by uploaded_at reason source_files bom'),
    _spec(SpoolDocumentFileLink, 'Spool shared drawing links', 'document_id source_document_id', 'document_id'),
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
    _spec(SpoolPartsPlan, 'Spool parts plans', 'spool_id version reference created_by created_at updated_at', 'spool_id'),
    _spec(PartLine, 'Spool part lines', 'id spool_id part_number description required_qty notes active created_by created_at updated_at'),
    _spec(PartAllocation, 'Part allocations', 'component_id line_id assigned_by assigned_at', 'component_id'),
    _spec(PartEvent, 'Spool parts events', 'id spool_id sequence action actor at reference reason data'),
    _spec(QualityWorkspace, 'Quality workspaces', 'id name customer project_id purchase_order audit_date owner_badge template_version version created_by created_at updated_at'),
    _spec(QualityRequirement, 'Quality requirements', 'id workspace_id item_number title requirement_text response_text source_document source_revision source_section source_reference supporting_documents required_evidence gaps priority owner_badge due_date applicability applicability_reason required_evidence_types document_ids requires_closed_action requires_approved_document gate version created_by created_at updated_at'),
    _spec(QualityDocument, 'Quality documents', 'id workspace_id code title revision reference effective_date requires_training required_badges notes created_by created_at'),
    _spec(QualityEvidence, 'Quality evidence', 'id workspace_id requirement_id type title reference occurred_on notes document_id related_evidence_id item_id weld_id participants performed_by data production_snapshot created_by created_at'),
    _spec(QualityAction, 'Quality actions', 'id workspace_id requirement_id title owner_badge due_date problem containment root_cause correction corrective_action status closure_evidence_ids effectiveness_evidence_id customer_approval_required customer_approval_evidence_id version closed_by closed_at created_by created_at updated_at'),
    _spec(QualityReview, 'Quality reviews', 'id workspace_id target_type target_id decision reference notes fingerprint snapshot actor at'),
    _spec(QualityEvent, 'Quality events', 'id workspace_id sequence event target_type target_id details actor at'),
    _spec(DossierProject, 'Packet projects', 'project_id manufacturer_name manufacturer_contact purchase_order work_order advisements source_reference expected_packets shipping_gate customer_approval_required notes version created_by created_at updated_at', 'project_id'),
    _spec(DossierEntry, 'Packet checklist', 'id project_id item_id code applicability reference notes document_ids values version updated_by updated_at'),
    _spec(DossierDocument, 'Packet documents', 'id project_id item_id scope_key code title revision section reference filename media_type size_bytes sha256 actor at'),
    _spec(DossierReview, 'Packet reviews', 'id project_id item_id code decision reference notes fingerprint snapshot actor at'),
    _spec(DossierIssue, 'Packet issues', 'id project_id item_id scope_key kind revision fingerprint sha256 snapshot print_sha256 reference notes actor at'),
    _spec(DossierHandover, 'Packet handovers', 'id project_id issue_id channel event dispatch_id recipient organization reference notes occurred_on actor at'),
    _spec(DossierEvent, 'Packet events', 'id project_id sequence event item_id details actor at'),
)

PROJECT_PROGRESS_COLUMNS = (
    'project_id', 'name', 'client', 'total_parts', 'wip', 'finished', 'shipped', 'delivered',
    'blocked', 'finished_percent', 'recorded_steps_completed', 'recorded_steps_total',
    'recorded_percent', 'planning_needed', 'has_dossier', 'as_of',
)
PART_PROGRESS_COLUMNS = (
    'project_id', 'subproject_id', 'item_id', 'description', 'google_part_number',
    'kind', 'item_kind', 'parent_id', 'scope_source', 'status', 'fabrication_finished',
    'blocked', 'blockers', 'progress_percent', 'progress_basis', 'completed_steps',
    'total_steps', 'not_recorded_steps', 'planned_welds', 'completed_welds', 'qa_accepted',
    'flow_status', 'current_step', 'current_title', 'released', 'release_mode', 'release_label',
    'administrative_release', 'location', 'handler',
    'arrival_qa_required', 'arrival_qa_status', 'arrival_qa_current_pass',
    'arrival_qa_version', 'arrival_qa_inspector', 'arrival_qa_at',
    'updated_at', 'as_of',
)
SPOOL_PARTS_PROGRESS_COLUMNS = (
    'project_id', 'subproject_id', 'spool_id', 'line_id', 'part_number', 'description',
    'required_qty', 'assigned_qty', 'received_qty', 'prepared_qty', 'short_qty', 'remaining_qty',
    'assigned_percent', 'received_percent', 'prepared_percent', 'component_ids', 'blockers', 'as_of',
)
PACKET_READINESS_COLUMNS = (
    'project_id', 'item_id', 'purchase_order', 'packet_status', 'source_status',
    'packet_percent', 'section', 'code', 'title', 'applicability', 'check_status',
    'reference', 'notes', 'document_ids', 'values', 'blockers', 'packet_blockers', 'last_review_decision',
    'last_reviewer', 'last_review_at', 'last_review_reference', 'latest_issue_id',
    'latest_issue_revision', 'issue_current', 'as_of',
)

QUALITY_REPORT_COLUMNS = (
    'workspace_id', 'workspace_name', 'customer', 'project_id', 'purchase_order', 'audit_date',
    'requirement_id', 'item_number', 'title', 'priority', 'owner_badge', 'due_date',
    'applicability', 'applicability_reason', 'production_gate',
    'customer_requirement', 'clm_response', 'supporting_documentation',
    'required_evidence', 'collected_evidence', 'gaps_and_corrective_actions',
    'verification_status', 'source_status', 'source_document', 'source_revision',
    'source_section', 'source_reference', 'blockers', 'last_review_decision',
    'last_reviewer', 'last_review_at', 'last_review_reference', 'as_of',
)

FLOW_STEP_COLUMNS = ('definition_version', 'number', 'title', 'qa_code', 'display_qa_code', 'flow_stage_key', 'route', 'section', 'roles', 'checks',
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
    'item_transfer_states.item_id -> items.id; version is the current handoff/location edit revision. An absent row means no new-format transfer has been recorded; historical badges and statuses are not invented.',
    'transfer_locations stores managed custom destination choices; built-in work centers are application definitions. location_id may reference a built-in or custom choice, or be blank for a preserved legacy location. items.location retains the actual last recorded label, so renaming a catalog choice does not rewrite history.',
    'Audit TRANSFER details retain both scanned badge identities, before/after location and operational status, custody_changed and the authenticated recorder. Badge identification is not independent sender or recipient acknowledgement.',
    'Operational transfer status does not change numbered process steps, timers, holds, inspection acceptance or release. A custody_transfer Flow event invalidates stale traveler forms without advancing their step.',
    'Items.released includes an explicit administrative release as well as ordinary QA release. Part progress release_mode and immutable ADMIN_RELEASE_OVERRIDE audit details identify that distinction. An override does not record passing inspections, completed welds or a QA-issued Job Packet.',
    'Employee access states records account-edit and session-revocation versions. Private PINs, PIN hashes and session tokens are excluded. Administrative custody corrections are separately identified; they do not claim employee badge scans.',
    'Employee removal states records removal/restoration metadata keyed to Employees.badge. Employees retains all identities, including removed accounts, so historical work and custody references remain traceable. Removal disables access without reassigning items; restoration leaves the account inactive until explicitly enabled. Immutable EMPLOYEE_REMOVED and EMPLOYEE_RESTORED audit events retain each decision.',
    'Employees.role stores the assigned job position. Current supported roles are admin (Administrator), supervisor, handler (Material coordinator), welder, fitup_welder, process_welder, inspector (QA/QC), painter, finisher and misc (Miscellaneous). Position changes revoke existing sessions; historical actors and badge identities are not rewritten.',
    'Job permissions restrict actual work separately from visibility and custody. Shared badge handoffs do not grant fabrication or QA authority. Supervisors may coordinate process timing but cannot record specialized physical welding, painting or QA acceptance. Tracking requirement owner_role controls evidence submission, with administrator/supervisor/QA coordination access; QA acceptance remains separate.',
    'spool_parts_plans.spool_id -> the tracked spool items.id; spool_part_lines.spool_id -> its optional controlled parts plan. Quantities are whole physical pieces, not weld counts or length.',
    'spool_part_allocations.component_id -> one individual Part items.id and line_id -> spool_part_lines.id. Each allocation must also match the existing flow_component_links parent; a QR identity is counted once.',
    'spool_parts_events preserves versioned parts-list edits, allocations and removals. Spool parts progress derives actual receipt step1 and current prepared steps7+8; historical baselines are not invented.',
    'spool_document_sets belongs to exactly one order_spool_requirements.id or physical items.id. Registered spools inherit only the documents on their exact requirement; individual uploads override that kind for that physical spool. File upload is not material receipt or QA approval.',
    'spool_documents retains immutable BOM/drawing revisions, source-file hashes, page counts, uploader and parsed BOM values. Binary spool_document_files.content is excluded from Excel; retrieve full files from the spool or an issued Job Packet ZIP, which retains exact document IDs.',
    'spool_document_file_links.document_id references a shared drawing revision; source_document_id identifies the immutable revision retaining its PDF bytes. Generated spool BOMs retain the drawing hash, source pages, extracted values and reviewed corrections.',
    'items.handler -> employees.badge; items.id is the original physical item identity.',
    'spool_qr_identities.item_id -> items.id. The permanent display_code is the spool number plus a numbered suffix, e.g. 643-777-PCW-03-01-[001]. Sequence is unique per normalized spool number across purchase orders, is never recycled, and does not replace internal item identities or invalidate older QR labels.',
    'spool_material_inspections stores immutable QA-001 Pass/Fail decisions for each physical BOM piece. basis_sha256 binds the decision to its exact material, BOM, drawing and MTR evidence. A changed piece requires reinspection; every current piece must pass before overall arrival acceptance.',
    'inspections.item_id / reworks.item_id / audit_events.item_id -> items.id. Audit item_id may be blank for account or project events.',
    'inspections.inspector -> employees.badge; rework assigned / closed_by and audit actor retain employee badge identities.',
    'tracking_subprojects.project_id -> tracking_projects.id.',
    'tracking_spool_plans.item_id -> items.id; one plan enrolls one existing physical item.',
    'tracking_spool_plans.project_id -> tracking_projects.id; subproject_id -> tracking_subprojects.id.',
    'tracking_spool_plans.assembly_id -> items.id (optional Assembly). Assembly links organize records; they do not certify child-spool release.',
    'order_spools.item_id -> items.id; assembly_id -> order_assemblies.item_id; requirement_id -> order_spool_requirements.id. This registers a physical spool against an exact assembly before its weld plan exists. It is not fabrication, receipt or QA evidence.',
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
    'flow_component_links.component_id -> individual component items.id; spool_id -> the parent spool items.id. Registered order_spools and tracking_spool_plans identify spool-to-assembly scope; a spool with both is counted once.',
    'Process reports use the current SpoolPlan project/subproject, or the assigned parent spool plan for a component. Unassigned component project/subproject cells remain blank; past project assignments are not frozen in timing events.',
    'Flow steps contains the current numbered CLM process definitions. Recorded event data retains its own definition version and step/checklist snapshot.',
    'Flow plans stores shipment and receipt details. shipped_at confirms dispatch; delivered_at exists only after a separately recorded delivery receipt.',
    'quality_workspaces.project_id -> tracking_projects.id when project-scoped; blank means organizational audit preparation. Templates create draft requirements only.',
    'quality_requirements.workspace_id -> quality_workspaces.id. document_ids links exact quality_documents revisions; the named source still requires a signed source review.',
    'quality_evidence.requirement_id -> quality_requirements.id; document_id -> quality_documents.id; related_evidence_id -> quality_evidence.id (for training against an issued alert). Optional item_id and weld_id link actual production records.',
    'quality_actions.requirement_id -> quality_requirements.id; closure/effectiveness/customer approval IDs reference quality_evidence. An action row marked closed can still have stale evidence; use Audit readiness for current verification.',
    'quality_reviews.target_type and target_id identify a source/requirement, document, evidence or action within the same workspace. Reviews retain the signed snapshot and fingerprint; later reviews never rewrite earlier ones.',
    'quality_events.workspace_id and sequence retain each workspace change. Document revisions, evidence, reviews and events are immutable; their current statuses are derived, not stored acceptance flags.',
    'Audit readiness is a calculated report from the same snapshot as raw Quality tables. Verified requires a current signed review and current prerequisites. It does not certify compliance or establish that a referenced external file exists.',
    'dossier_projects.project_id -> tracking_projects.id. expected_packets is the declared number of spool/assembly packets, excluding individual preparation components. The progress denominator remains actual registered parts.',
    'dossier_entries.item_id -> items.id; document_ids reference exact dossier_documents revisions. Documents can be shared at project level or scoped to one item. Superseded files and reviews remain historical.',
    'dossier_documents retains file size, SHA-256 and upload identity. Binary dossier_files.content is deliberately excluded; use an issued Job Packet ZIP to retrieve its selected original files.',
    'dossier_reviews and dossier_issues retain signed immutable snapshots and fingerprints. Packet readiness recalculates current applicability and blockers; an old issued snapshot is never rewritten.',
    'dossier_handovers.issue_id -> dossier_issues.id; dispatch_id identifies the dispatch acknowledged by a receipt. Download, recorded dispatch and recorded receipt are separate events. dossier_events.sequence is the project edit version.',
    'Project progress and Part progress are calculated from registered records, real route events and current physical quality checks. Historical baseline steps stay not recorded. Fabrication completion is separate from packet approval or handover.',
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
    # Human-readable headers used by the focused purchase-order BOM workbook.
    if header in ('Value', 'Notes', 'Line notes', 'Blockers'):
        return 64
    if header in ('Assembly description', 'Spool description', 'Material description', 'Planning status'):
        return 44
    if header in ('PO number', 'GPN', 'Assembly ID', 'Assembly part number', 'Spool ID',
                  'Spool part number', 'Material part number', 'Assigned component IDs', 'BOM reference'):
        return 28
    if header == 'Entry':
        return 28
    if header in ('details', 'requirements', 'notes', 'measurements', 'reason', 'close_notes', 'text', 'value',
                  'customer_requirement', 'clm_response', 'supporting_documentation', 'required_evidence',
                  'collected_evidence', 'gaps_and_corrective_actions', 'blockers'):
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
    add('Export', 'Scope', f'All rows from the {len(TABLE_SPECS)} explicitly allowlisted business tables, including inactive employees, prior evidence/reviews, completed repairs, closed holds, production process events, numbered travelers, audit-readiness records and Job Packet metadata/snapshots. Calculated reports cover process time, audit readiness, project and part progress, and current Job Packet checks. Flow steps supplies the current 24-step definition lookup. No screen pagination limits.')
    add('Export', 'Database writes', 'None. This export does not append audit records or alter application data.')
    add('Exclusions', 'Authentication', 'Employee PIN hashes, PINs, passwords, session tokens, JWT secrets, database credentials and environment variables are excluded. Employee roster includes badge, name, role, active and created_at only.')
    add('Exclusions', 'External documents', 'References and URLs are exported as stored. External report/MTR contents and linked files are not fetched or embedded.')
    add('Exclusions', 'Uploaded file bytes', 'The dossier_files binary table and retained dossier_issues.print_html are excluded. Packet documents includes file identity, scope, size and SHA-256; Packet issues retains structured snapshots and print hashes. Download an issued packet ZIP for its frozen HTML and selected original files. An Excel export is not a replacement for the issued Job Packet.')
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
    add('Audit readiness', 'Evidence and verification', 'Quality tables preserve the five audit prompts, document revisions, submitted records, corrective actions and signed review history. The Audit readiness report recalculates current verification against those records at the snapshot time. Draft wording, a planned audit and an issued/approved blank template do not prove that an activity occurred.')
    add('Audit readiness', 'Sources and scope', 'Kelvion starter prompts are based on the supplied planning summary. Original documents, PO applicability, technical criteria and revisions require human source confirmation. No universal NDE, pressure, coating or customer-deadline rule is inferred. Optional project gates require deliberate configuration.')
    add('Audit readiness', 'Dates', 'Actual activity dates, due dates and audit dates are stored as ISO calendar dates. Review and recording timestamps are UTC. A future planned audit date is different from a completed audit date. The report as_of timestamp matches the export snapshot timestamp.')
    add('Job Packets', 'Structure and source', 'Kelvion QF-QAS-100 Rev B p8 defines eight Job Packet contents. CLM organizes them into ten sections. Project/PO applicability and source confirmation remain explicit QA reviews; no default test pressure, NDE sampling rate or acceptance value is inferred.')
    add('Job Packets', 'Issue and transfer', 'Packet issues are immutable issued snapshots. Packet readiness reports the current checks, so it may show a blocker after a later edit or repair. Physical and digital dispatch and receipt are recorded against an exact project issue. Downloading or printing does not record delivery.')
    add('Project progress', 'Denominators', 'Project percentages describe registered parts only, not an unregistered BOM. Components, spools and assemblies are counted as their own traceable records. Per-part recorded-step percentages exclude unrecorded baseline steps and roll back affected steps after rework. Finished is determined separately from current physical release checks.')
    add('Format', 'Continuation sheets', f'Each sheet holds at most {EXCEL_MAX_ROWS:,} rows including its repeated header. Additional data continues on sheets named with a numeric suffix.')
    add('Format', 'Long text', f'Values exceeding {EXCEL_MAX_CELL_CHARS:,} UTF-16 units are replaced by an OVF reference. Reconstruct the full original value by concatenating Text overflow chunks for that overflow_id in chunk_index order.')
    add('Format', 'Long-text cells', writer.overflow_cells)
    add('Format', 'Overflow chunk rows', writer.overflow_rows)
    for index, relationship in enumerate(RELATIONSHIPS, start=1):
        add('Relationships', f'R{index:02}', relationship)
    add('Counts', 'How to read counts', 'Data-row counts exclude headers. Continuation-sheet counts are separate. Process, audit, progress and packet-readiness reports are calculated rows and Flow steps is definition data; none adds database records. Manifest sheets are descriptive metadata.')
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


def _write_quality_report(connection, writer, created_at, exporter):
    """Project the five audit prompts using the existing read-only snapshot.

    The quality module batches dependencies once per workspace. Hold only one
    workspace at a time and spool report rows so the XLSX row/long-text limits
    remain identical to the raw export. The joined session never commits and
    cannot write through PostgreSQL's READ ONLY transaction.
    """
    count = 0
    with tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b') as report:
        with Session(bind=connection, autoflush=False, expire_on_commit=False,
                     join_transaction_mode='rollback_only') as session:
            workspace_ids = connection.scalars(select(QualityWorkspace.id).order_by(QualityWorkspace.id))
            for workspace_id in workspace_ids:
                workspace = session.get(QualityWorkspace, workspace_id)
                detail = workspace_detail(session, workspace, exporter, as_of=created_at)
                documents = {doc['id']: doc for doc in detail['documents']}
                evidence_by_requirement = {}
                training_by_document = {}
                training_by_alert = {}
                actions_by_requirement = {}
                for evidence in detail['evidence']:
                    evidence_by_requirement.setdefault(evidence['requirement_id'], []).append(evidence)
                    if evidence['type'] == 'training':
                        if evidence['document_id']:
                            training_by_document.setdefault(evidence['document_id'], []).append(evidence)
                        if evidence['related_evidence_id']:
                            training_by_alert.setdefault(evidence['related_evidence_id'], []).append(evidence)
                for action in detail['actions']:
                    actions_by_requirement.setdefault(action['requirement_id'], []).append(action)
                for requirement in detail['requirements']:
                    direct = evidence_by_requirement.get(requirement['id'], [])
                    relevant = {record['id']: record for record in direct}
                    for identifier in requirement['document_ids']:
                        relevant.update((record['id'], record) for record in training_by_document.get(identifier, []))
                    for record in direct:
                        relevant.update((training['id'], training) for training in training_by_alert.get(record['id'], []))
                    linked_documents = set(requirement['document_ids']) | {
                        record['document_id'] for record in relevant.values() if record['document_id']}
                    supporting = [requirement['supporting_documents']] if requirement['supporting_documents'] else []
                    for identifier in sorted(linked_documents):
                        doc = documents.get(identifier)
                        if doc is None:
                            supporting.append(f'Document {identifier}: missing from workspace')
                            continue
                        supporting.append(f"{doc['code']} Rev {doc['revision']} — {doc['title']} | {doc['status']} | "
                                          f"effective {doc['effective_date'] or 'not recorded'} | {doc['reference']}")
                        if doc['training_gaps']:
                            supporting.append('Training missing: ' + ', '.join(doc['training_gaps']))
                    collected = []
                    for record in sorted(relevant.values(), key=lambda value: value['id']):
                        collected.append(f"#{record['id']} {record['type']} | {record['occurred_on']} | "
                                         f"{record['status']}{' (stale)' if record.get('stale') else ''} | "
                                         f"{record['title']} | {record['reference']}")
                        if record['requirement_id'] != requirement['id']:
                            collected.append('Supporting training recorded under requirement ID ' + str(record['requirement_id']))
                        if record['participants']:
                            collected.append('Participants: ' + ', '.join(record['participants']))
                        if record['performed_by']:
                            collected.append('Performed by: ' + record['performed_by'])
                        if record['document_id']:
                            collected.append('Exact document revision ID: ' + str(record['document_id']))
                        if record['related_evidence_id']:
                            collected.append('Related evidence ID: ' + str(record['related_evidence_id']))
                        if record['notes']:
                            collected.append(record['notes'])
                    gaps = [requirement['gaps']] if requirement['gaps'] else []
                    for action in actions_by_requirement.get(requirement['id'], []):
                        gaps.append(f"Action #{action['id']}: {action['title']} | {action['status']}"
                                    f"{' (closure evidence stale)' if action.get('closure_stale') else ''} | "
                                    f"owner {action['owner_badge']} | due {action['due_date']}")
                        for key, label in (('problem', 'Problem'), ('containment', 'Containment'),
                                           ('root_cause', 'Root cause'), ('correction', 'Correction'),
                                           ('corrective_action', 'Corrective action')):
                            if action[key]:
                                gaps.append(label + ': ' + action[key])
                        if action['customer_approval_required']:
                            gaps.append('Customer approval required; evidence ID: ' + str(action['customer_approval_evidence_id'] or 'missing'))
                    review = requirement['latest_review'] or {}
                    row = {
                        'workspace_id': workspace.id, 'workspace_name': workspace.name,
                        'customer': workspace.customer, 'project_id': workspace.project_id,
                        'purchase_order': workspace.purchase_order, 'audit_date': workspace.audit_date,
                        'requirement_id': requirement['id'], 'item_number': requirement['item_number'],
                        'title': requirement['title'], 'priority': requirement['priority'],
                        'owner_badge': requirement['owner_badge'], 'due_date': requirement['due_date'],
                        'applicability': requirement['applicability'], 'applicability_reason': requirement['applicability_reason'],
                        'production_gate': requirement['gate'], 'customer_requirement': requirement['requirement_text'],
                        'clm_response': requirement['response_text'], 'supporting_documentation': '\n'.join(supporting),
                        'required_evidence': requirement['required_evidence'], 'collected_evidence': '\n'.join(collected),
                        'gaps_and_corrective_actions': '\n'.join(gaps), 'verification_status': requirement['status'],
                        'source_status': requirement['source_status'], 'source_document': requirement['source_document'],
                        'source_revision': requirement['source_revision'], 'source_section': requirement['source_section'],
                        'source_reference': requirement['source_reference'], 'blockers': '\n'.join(requirement['blockers']),
                        'last_review_decision': review.get('decision'), 'last_reviewer': review.get('actor'),
                        'last_review_at': review.get('at'), 'last_review_reference': review.get('reference'),
                        'as_of': _utc(created_at).isoformat(),
                    }
                    report.write((json.dumps([row[key] for key in QUALITY_REPORT_COLUMNS], ensure_ascii=True) + '\n').encode())
                    count += 1
                # Detach completed workspace objects so report memory does not
                # grow with all workspaces. The outer transaction stays open.
                session.expunge_all()
        report.seek(0)

        def rows():
            for line in report:
                values = json.loads(line)
                for key in ('last_review_at', 'as_of'):
                    index = QUALITY_REPORT_COLUMNS.index(key)
                    if values[index]:
                        values[index] = dt.datetime.fromisoformat(values[index].replace('Z', '+00:00'))
                yield values, _json_text({'workspace_id': values[0], 'requirement_id': values[6]})

        writer.write_rows('Audit readiness', 'derived:quality_readiness', QUALITY_REPORT_COLUMNS,
                          rows(), count, group='report')


def _write_delivery_reports(connection, writer, created_at, exporter):
    """Progress and packet checks share the raw workbook's read-only snapshot.

    Keep one project in the ORM identity map and spool the derived rows, so
    large report text uses the normal continuation/overflow path. File bytes
    are never loaded by these metadata projections.
    """
    as_of = _utc(created_at).isoformat()
    with tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b') as projects_file, \
            tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b') as parts_file, \
            tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b') as packets_file:
        counts = [0, 0, 0]
        with Session(bind=connection, autoflush=False, expire_on_commit=False,
                     join_transaction_mode='rollback_only') as session:
            configured = set(connection.scalars(select(DossierProject.project_id)))
            project_ids = connection.scalars(select(Project.id).order_by(Project.id))
            for project_id in project_ids:
                project = session.get(Project, project_id)
                parts = project_rows(session, project_id)
                summary = progress_summary(project, parts, project_id in configured)
                summary.update(project_id=project_id, as_of=as_of)
                projects_file.write((json.dumps([summary[k] for k in PROJECT_PROGRESS_COLUMNS], ensure_ascii=True) + '\n').encode())
                counts[0] += 1
                for part in parts:
                    part.update(item_id=part['id'], as_of=as_of)
                    arrival = part.get('receiving') or {}
                    inspection = arrival.get('latest') or {}
                    part.update(arrival_qa_required=bool(arrival.get('required')),
                        arrival_qa_status=arrival.get('status', 'not_applicable'),
                        arrival_qa_current_pass=bool(arrival.get('required') and arrival.get('can_proceed')),
                        arrival_qa_version=arrival.get('version', 0),
                        arrival_qa_inspector=inspection.get('actor', ''),
                        arrival_qa_at=inspection.get('at', ''))
                    part['blockers'] = '\n'.join(part['blockers'])
                    parts_file.write((json.dumps([part[k] for k in PART_PROGRESS_COLUMNS], ensure_ascii=True) + '\n').encode())
                    counts[1] += 1
                    if project_id not in configured or part['kind'] not in ('spool', 'assembly'):
                        continue
                    packet = item_detail(session, session.get(Item, part['item_id']), exporter)
                    issue = packet['latest_issue'] or {}
                    for section in packet['sections']:
                        for check in section['checks']:
                            review = check['latest_review'] or {}
                            record = {
                                'project_id': project_id, 'item_id': part['item_id'],
                                'purchase_order': packet['config']['purchase_order'],
                                'packet_status': packet['status'], 'source_status': packet['source_status'],
                                'packet_percent': packet['percent'], 'section': section['code'],
                                'code': check['code'], 'title': check['title'],
                                'applicability': check['applicability'], 'check_status': check['status'],
                                'reference': check['reference'], 'notes': check['notes'],
                                'document_ids': check['document_ids'], 'values': check['values'],
                                'blockers': '\n'.join(check['blockers']), 'packet_blockers': '\n'.join(packet['blockers']),
                                'last_review_decision': review.get('decision'), 'last_reviewer': review.get('actor'),
                                'last_review_at': review.get('at'), 'last_review_reference': review.get('reference'),
                                'latest_issue_id': issue.get('id'), 'latest_issue_revision': issue.get('revision'),
                                'issue_current': issue.get('current', False), 'as_of': as_of,
                            }
                            packets_file.write((json.dumps([record[k] for k in PACKET_READINESS_COLUMNS], ensure_ascii=True) + '\n').encode())
                            counts[2] += 1
                session.expunge_all()

        for report, name, table, columns, count, dates, json_columns in (
            (projects_file, 'Project progress', 'derived:project_progress', PROJECT_PROGRESS_COLUMNS, counts[0], ('as_of',), set()),
            (parts_file, 'Part progress', 'derived:part_progress', PART_PROGRESS_COLUMNS, counts[1], ('updated_at', 'as_of'), set()),
            (packets_file, 'Job Packet readiness', 'derived:packet_readiness', PACKET_READINESS_COLUMNS, counts[2], ('last_review_at', 'as_of'), {'document_ids', 'values'}),
        ):
            report.seek(0)
            def rows(report=report, columns=columns, dates=dates):
                for line in report:
                    values = json.loads(line)
                    for key in dates:
                        index = columns.index(key)
                        if values[index]:
                            values[index] = dt.datetime.fromisoformat(values[index].replace('Z', '+00:00'))
                    identity = {key: values[columns.index(key)] for key in ('project_id', 'item_id', 'code') if key in columns}
                    yield values, _json_text(identity)
            writer.write_rows(name, table, columns, rows(), count, json_columns=json_columns, group='report')


def _write_spool_parts_report(connection, writer, created_at):
    """Required quantities and recorded part preparation in the export snapshot."""
    as_of = _utc(created_at).isoformat()
    count = 0
    with tempfile.SpooledTemporaryFile(max_size=TEMP_MEMORY_BYTES, mode='w+b') as report:
        with Session(bind=connection, autoflush=False, expire_on_commit=False,
                     join_transaction_mode='rollback_only') as session:
            for spool_id in connection.scalars(select(SpoolPartsPlan.spool_id).order_by(SpoolPartsPlan.spool_id)):
                plan = session.get(SpoolPlan, spool_id)
                snapshot = parts_snapshot(session, spool_id)
                for line in snapshot['lines']:
                    values = {**line, 'project_id': plan.project_id, 'subproject_id': plan.subproject_id,
                              'spool_id': spool_id, 'line_id': line['id'],
                              'component_ids': [component['id'] for component in line['components']],
                              'blockers': '\n'.join(snapshot['blockers']), 'as_of': as_of}
                    report.write((json.dumps([values[key] for key in SPOOL_PARTS_PROGRESS_COLUMNS], ensure_ascii=True) + '\n').encode())
                    count += 1
                session.expunge_all()
        report.seek(0)

        def rows():
            for line in report:
                values = json.loads(line)
                values[-1] = dt.datetime.fromisoformat(values[-1])
                identity = {key: values[SPOOL_PARTS_PROGRESS_COLUMNS.index(key)] for key in ('spool_id', 'line_id')}
                yield values, _json_text(identity)

        writer.write_rows('Spool parts progress', 'derived:spool_parts_progress', SPOOL_PARTS_PROGRESS_COLUMNS,
                          rows(), count, json_columns={'component_ids'}, group='report')


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
                        _write_quality_report(connection, writer, created_at, exporter)
                        _write_delivery_reports(connection, writer, created_at, exporter)
                        _write_spool_parts_report(connection, writer, created_at)
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
