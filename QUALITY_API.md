# Quality API integration contract

All endpoints require existing badge authentication. Readers: all roles. Writers: admin, supervisor, inspector. Reviewers: admin, inspector. Workspace creation: admin/supervisor. No writes on page load/deploy. Every mutation after workspace creation takes `expected_version` = `workspace.version` and returns the full workspace detail below. A stale version is HTTP 409. IDs are integer database IDs except project/item/weld/badges, which retain existing string IDs. All datetimes are server UTC; `*_on`, `audit_date`, `due_date` are ISO date strings. Future activity dates are rejected; planned audit dates may be future.

## Read / create

- GET `/api/quality/catalog`: `{template_version, source_note, source_documents, templates, evidence_types:[{value,label,fields:[{name,label,type,required,options?}]}]}`. Optional evidence detail fields come from this metadata; `type` is text/textarea/date/checkbox. Required checkboxes mean an explicit boolean value. No technical thresholds are approved by the template.
- GET `/api/quality/workspaces`: `{workspaces:[{...workspace,metrics}]}`.
- POST `/api/quality/workspaces`: `{name,customer:'Kelvion',project_id:null,purchase_order:'',audit_date:null,owner_badge:null,template:'kelvion'|'blank'}` -> 201 full detail. Template creates draft requirements and no evidence, documents, reviews, actions, or completed activities.
- GET `/api/quality/workspaces/{id}` full detail.
- PUT `/api/quality/workspaces/{id}`: same metadata fields except template plus `expected_version`.

Detail: `{workspace,requirements,documents,evidence,actions,reviews,events,metrics,permissions}`. `workspace` has id/name/customer/project_id/purchase_order/audit_date/owner_badge/version/created_by/created_at/updated_at. `permissions:{manage,write,review}` booleans. Metrics: total,verified,not_applicable,needs_attention,ready_for_review,priority_open,open_actions,overdue_actions. Requirement rows add `status,blockers,source_status,document_ids,latest_review,overdue`; statuses draft/in_progress/needs_attention/ready_for_review/verified/not_applicable. Documents add `status,training_gaps,latest_review`; statuses draft/approved/superseded. Evidence adds `status,latest_review`; statuses submitted/accepted/rejected. Actions add `overdue`. Review/event lists preserve history.

## Requirements

POST `/api/quality/workspaces/{id}/requirements`; PUT `.../requirements/{requirement_id}`. Full editable body:

```
{expected_version,item_number,title,requirement_text,response_text:'',
 source_document:'',source_revision:'',source_section:'',source_reference:'',
 supporting_documents:'',required_evidence:'',gaps:'',priority:'high'|'normal'|'critical',
 owner_badge:null,due_date:null,applicability:'applicable'|'conditional'|'not_applicable',
 applicability_reason:'',required_evidence_types:[],document_ids:[],
 requires_closed_action:false,requires_approved_document:false,gate:'none'|'pre_coating'|'shipment'}
```

All narrative fields are explicit draft text until human review. `gate` other than none requires project scope and reviewer role. Conditional applicability blocks verification. Source confirmation is a separate review and is invalidated if requirement/source/applicability wording changes. Linking documents uses numeric IDs of exact revisions from this workspace. Approved newer revisions supersede older revisions; old links require updating and re-verification.

## Controlled documents

POST `/api/quality/workspaces/{id}/documents`:
`{expected_version,code,title,revision,reference,effective_date,requires_training:false,required_badges:[],notes:''}`.
Immutable revision entries, unique code+revision within workspace. Add a new revision instead of editing. Require real active employee badges when training is required. Approval uses generic reviews; reference is the actual approval record, notes describe basis. Approving a later entry with the same code makes older approved entries superseded. Training evidence must reference the exact document ID. No file upload/storage; use document reference/location or HTTPS URL.

## Actual evidence

POST `/api/quality/workspaces/{id}/evidence`:
`{expected_version,requirement_id,type,title,reference,occurred_on,notes:'',document_id:null,related_evidence_id:null,item_id:null,weld_id:null,participants:[],performed_by:'',data:{}}`.
Immutable; corrections are another evidence entry and the mistaken record is rejected by review. All submissions start submitted. Accepted evidence means a reviewer checked that record; it does not mark the requirement verified or advance production.

Types and required data keys (catalog supplies labels):
- audit_schedule: `scope,auditor,scheduled_for,approval_reference` (scheduled_for date; occurred_on is schedule issue/approval date).
- internal_audit: `scope,auditor,findings,outcome`; occurred_on is actual completed audit date. Report in common reference.
- quality_alert: `issue,containment,training_required` (boolean); if true, `required_participants` is a list of employee badges. Actual issue date in occurred_on.
- training: `topic,assessment`; common `participants` nonempty and `performed_by` is an active trainer badge. Exact `document_id` or `related_evidence_id` pointing to a Quality Alert is required.
- investment: `asset,description`.
- capability: `scope,result`.
- inspection: `scope,result,measurements`; result is pass/fail/recorded (accepted review requires pass).
- production: `scope,result`.
- customer_approval: `scope,disposition,approved_by`; customer-issued reference in common reference.
- corrective_action: `scope,result`.
- effectiveness: `scope,result`; result must pass for acceptance.
- other: `scope,result`.

Common `performed_by` is a descriptive name for non-training records. Training requires active badge; participants always active badges. Related docs/evidence must belong to workspace. Optional item/weld must exist and match one another and selected workspace project; actual existing record links do not grant acceptance.

## Corrective actions

POST `/api/quality/workspaces/{id}/actions`; PUT `.../actions/{action_id}`:
`{expected_version,requirement_id,title,owner_badge,due_date,problem,containment:'',root_cause:'',correction:'',corrective_action:'',status:'open'|'implemented',closure_evidence_ids:[],effectiveness_evidence_id:null,customer_approval_required:false,customer_approval_evidence_id:null}`.
Owner active badge. Closing is a separate reviewer action; requires implemented status, containment/root cause/correction/corrective action, accepted closure evidence and accepted effectiveness record belonging to same requirement, and accepted customer_approval evidence if required. Closed rows cannot be edited until reopened by review. Reopening invalidates requirement verification. Closure needs actual evidence, not only planned text.

## Generic signed reviews

POST `/api/quality/workspaces/{id}/reviews`:
`{expected_version,target_type:'source'|'requirement'|'document'|'evidence'|'action',target_id,decision,reference,notes}`.
Reviewers admin/inspector only; reference and meaningful notes required. Actor/time are server-generated. Decisions:
- source: confirmed / unconfirmed. Confirmation requires source document, revision, section, reference and populated requirement text.
- requirement: verified / not_applicable / needs_work. Verified requires source confirmed, applicable, actual response, at least one linked approved current document or accepted evidence, all required evidence types, completed required training, no rejected current required evidence, no open actions, and any required closed action. NA requires applicability not_applicable + rationale + source confirmation + no open corrective actions. `needs_work` records reasons.
- document: approved / superseded. Approval requires effective_date and actual approval reference; a future effective date is allowed but document blocks readiness until effective.
- evidence: accepted / rejected. Acceptance checks typed details and references; no anonymous training or future performed dates.
- action: closed / reopened. Closure checks the gates above.

`blockers` is the authoritative explanation. Changes to a requirement or any linked document/evidence/action change its deterministic review fingerprint and make old verification stale, while preserving all review history. Unrelated requirement changes do not stale another requirement. Optional project gates block flow20/21 (pre_coating) and flow23/24 (shipment) unless every bound requirement is currently verified or approved NA. Requirements default to gate none.

Integration helpers: `production_gate_errors(s,item,gate,as_of=None,for_update=False)` -> list[str]; `workspace_detail(s,workspace,user,as_of=None)`; model classes QualityWorkspace, QualityRequirement, QualityDocument, QualityEvidence, QualityAction, QualityReview, QualityEvent. Immutable tables: quality_documents,quality_evidence,quality_reviews,quality_events. All writes lock flow topology then workspace row to match production order. Dates serialize deterministically.

Requirements with `requires_approved_document:true` require a linked current effective approved document (seeded items 3–6 and 8). Nonempty remaining `gaps` and a CLM response beginning with DRAFT block verification. Clear gaps only after resolution; history remains in events. The latest record of each required evidence type must be accepted; a newer submitted/rejected record blocks use of an older acceptance. Source fingerprints include workspace customer, project and PO. Effectiveness evidence cannot predate implementation. Linked production evidence stales on quality-changing item/weld state, not routine handoff/timer changes; status becomes submitted with stale:true and a new current record is required.

Document registration requires an actual or proposed effective_date; future effective dates remain blocked from readiness until effective. For real production gate mutations call production_gate_errors(..., for_update=True) while topology lock is already held; read-only flow detail uses the default false and takes no row locks.

Optional gates represent signed project-level requirements. They do not automatically calculate per-spool test coverage, NDE sample selection or technical limits. External documents remain references; no file retrieval/upload/archive is performed.
