# FabTrace Job Packet API and data contract

The `/api/dossier` router implements **Kelvion Job Packet / CLM Final Dossier** records. QF-QAS-100 Revision B, page 8 of 9, is the master content reference. CLM's ten sections organize that content; they are not a ten-section format mandated by Kelvion. The catalog cross-references the other five source documents. Source text and project/PO applicability remain subject to an identifiable inspector/admin review.

## Workflow and roles

1. Set up the actual project, spool/assembly plans, drawing IDs and separate drawing revisions in Projects & welds. Register component preparation and parent relationships where applicable.
2. An admin or supervisor explicitly configures Job Packets for the project, including manufacturer contact, PO, sources and the declared expected number of spool/assembly packets. Existing uninvolved projects are not silently enrolled.
3. An inspector or admin records a source/applicability review. This confirms the project's actual source and PO basis, rather than declaring that every manufacturing or test record exists.
4. Employees prepare only the checklist entries and upload sections allowed for their assigned job. Admins, supervisors and inspectors may prepare the full packet. Record actual observations/measurements or justified non-applicability; draft saves can be incomplete.
5. An inspector/admin reviews each current entry. An upload or a saved narrative alone is not acceptance. Superseded files, changed relevant evidence, repaired welds or changed scope make affected prior reviews stale.
6. After current physical release and all applicable current checklist reviews, QA issues an immutable item revision. Assemblies require current released child spool packets.
7. After **all** declared packets and all registered project parts are finished, QA issues an immutable project package. The declared packet count must equal the number of registered spool/assembly plans. Unplanned items and unfinished component routes are blockers.
8. Download the ZIP or print the issued revision. Independently record actual physical and/or digital dispatch, and subsequently confirmed receipt, against that project issue. The application does not email, send, deliver, or acknowledge a package when it is downloaded.

All authenticated employees can read and download. The shared `permissions.py` policy determines exact writable checklist codes and upload sections:

| Position | Checklist codes | Upload sections |
| --- | --- | --- |
| `admin`, `supervisor`, `inspector` | All catalog entries | `01`–`10` |
| `handler` | `materials`, `packaging`, `packing_slip` | `02`, `09` |
| `welder`, `fitup_welder`, `process_welder` | `procedures`, `brazing_bonding` | `03` |
| `painter` | `surface`, `coating` | `08` |
| `finisher` | `surface`, `packaging` | `08`, `09` |
| `misc` | None | None |

Packet dispatch/receipt is a separate capability for `handler`, `supervisor`, `inspector` and `admin`. Only `admin` and `inspector` (displayed as QA/QC) can sign source/check reviews and issue packets. Project configuration remains managed by `admin` and `supervisor`; only an admin can change an existing production gate or customer-approval rule, or initially disable the gate. An evidence-writing permission never grants review, issue or handover authority by implication. See [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for employee assignments and the full application matrix.

Uploads must use an allowed section. Revising an existing document identity also requires authority over **every prior section** recorded for its project, scope and document code. A later revision cannot bypass that restriction by declaring an allowed section; original revisions remain immutable.

## Versioning and concurrency

Every mutation requires `expected_version`, the current **project Job Packet configuration version**. An unconfigured project has version `0`; its first configuration has version `1`. Each successful mutation increments once and appends a corresponding audit and dossier event. A mismatched version returns HTTP `409` with `current_version`. Refresh and review the latest records before resubmission. JSON integer inputs are strict; boolean values are not integers.

Writes follow the existing topology advisory lock, project row lock and sorted physical item locks. After the topology lock is acquired, current employee/session authority is refreshed; a request queued behind an access or PIN change is rejected before mutation. This serializes packet decisions and physical mutations against the production gates. Reads do not create rows, update history, acquire `FOR UPDATE`, or take advisory locks. Existing append-only protection covers document bytes/metadata, reviews, issues, handovers and event history.

## Endpoints

| Method | Path after `/api/dossier` | Request / result |
|---|---|---|
| GET | `/catalog` | Template version, ten sections, 25 checklist definitions, structured evidence fields, sources and file limits |
| GET | `/projects` | `{projects:[{id,name,client,configured,config,summary,latest_project_issue,transfer_status,...}]}` |
| GET | `/projects/{project_id}` | Project detail below; an existing unconfigured project returns version 0 |
| PUT | `/projects/{project_id}/config` | `ConfigIn`; returns project detail |
| POST | `/projects/{project_id}/source-review` | `SignedIn`; returns project detail |
| GET | `/items/{item_id}` | Live item detail; a structured spool/assembly plan and project configuration are required |
| PUT | `/items/{item_id}/checks/{code}` | `EntryIn`; saves a draft, returns live item detail |
| POST | `/items/{item_id}/checks/{code}/review` | `ReviewIn`; returns live item detail |
| POST | `/projects/{project_id}/documents` | Multipart upload; HTTP 201 project detail |
| GET | `/documents/{document_id}/download` | Exact authenticated file download; SHA-256 and size verified |
| POST | `/items/{item_id}/issue` | `SignedIn`; HTTP 201 item detail containing the new retained issue |
| POST | `/projects/{project_id}/issue` | `SignedIn`; HTTP 201 project detail containing the retained project revision |
| GET | `/issues/{issue_id}` | Exact `{issue,snapshot}`; no mutable current-validity fields |
| GET | `/issues/{issue_id}/print` | Escaped printable HTML from the retained snapshot |
| GET | `/issues/{issue_id}/download` | ZIP of the retained snapshot, generated records and exact selected original files |
| GET | `/items/{item_id}/preview` | Live printable draft, prominently marked **DRAFT — NOT ISSUED** |
| POST | `/projects/{project_id}/handovers` | `HandoverIn`; records a real dispatch, HTTP 201 project detail |
| POST | `/projects/{project_id}/handovers/{handover_id}/receipt` | `ReceiptIn`; records actual receipt, HTTP 201 project detail |
| POST | `/handovers/{handover_id}/receipt` | Equivalent receipt alias using the dispatch's recorded project |

### Inputs

All JSON inputs reject extra fields and strip surrounding whitespace.

```json
{
  "expected_version": 0,
  "manufacturer_name": "Actual manufacturer name",
  "manufacturer_contact": "Actual contact name/address/contact details",
  "purchase_order": "Actual PO identifier",
  "work_order": "Actual work order",
  "advisements": "Applicable manufacturer recommendations",
  "source_reference": "Controlled ITP and applicable purchase order review reference",
  "expected_packets": 1,
  "shipping_gate": true,
  "customer_approval_required": false,
  "notes": "Scope and applicability notes"
}
```

This is the shape of `ConfigIn`, not seed business evidence. `expected_packets` is 1–100,000 and counts spool/assembly packets, including both parent assemblies and child spools. Individual preparation components are separately included in physical completion scope, but do not each require an additional spool packet.

`EntryIn`:

```json
{
  "expected_version": 1,
  "applicability": "required",
  "reference": "Actual report/record identifier",
  "notes": "Actual observations or documented applicability basis",
  "document_ids": [],
  "values": {}
}
```

`applicability` is `required` or `not_applicable`. `values` contains only the named text fields from this check's catalog definition; at most 30 fields with at most 5,000 characters each. Selected document IDs must identify files shared by this project or scoped to this exact item. Documents from a sibling item or other project are rejected. The reference is at most 1,000 characters and notes at most 10,000.

`SignedIn` is `{expected_version,reference,notes}`. It requires an identifiable reference of at least 3 characters and review notes of at least 4. `ReviewIn` adds `decision`, one of `accepted`, `not_applicable`, or `rejected`. Acceptance requires the saved evidence, fields, applicability, relevant automatic checks and source review to be current. The review decision must match the saved applicability. A non-applicability reason needs at least 8 characters and a source/authorization reference. Mandatory controls cannot be waived. The baseline VT, weld-log and procedures checks cannot be marked N/A when actual welds exist. Required customer pre-shipment authorization cannot be marked N/A.

`HandoverIn`:

```json
{
  "expected_version": 20,
  "issue_id": 3,
  "channel": "digital",
  "recipient": "Actual receiving person",
  "organization": "Actual receiving organization",
  "reference": "Actual transmission, delivery or signed handover reference",
  "notes": "What actually occurred",
  "occurred_on": "2026-10-29"
}
```

`channel` is `digital` or `physical`. The issue must be a current complete **project** package belonging to this project. Record the actual date, no earlier than issue and not in the future. `ReceiptIn` is `{expected_version,recipient,reference,notes,occurred_on}`. It inherits channel, organization and issue from the dispatch, must not predate that dispatch, and requires a distinct confirmation reference. A dispatch may have one immutable receipt. Historical receipt can be recorded even if that issued package has subsequently become stale; it remains a record of what was actually received, not a new release.

### Catalog and statuses

Each catalog check has `{code,section,title,source,kind,allow_na,fields}`. Each structured field has `{name,label,type,required,options?}`. `type` is `text` or `select` and the select options are literal strings.

| Check | Evidence fields |
|---|---|
| `nde` | `method`, `coverage`, `result` |
| `torque` | `scope`, `values`, `basis` |
| `pressure` | `test_id`, `pressure`, `duration`, `basis`, `result`, `approval` |
| `surface` | `preparation`, `conditions` |
| `coating` | `system`, `dft`, `holiday`, `result` |
| `packaging` | `protection`, `handling`, `inspection` |
| `customer_hold`, `customer_shipping` | `scope`, `authority` |

`result` accepts `pass`, `fail`, or `recorded`; only `pass` can support acceptance. Values capture actual units, results, scope and approved basis. No universal pressure, duration, DFT, holiday-test threshold, welding standard or sampled NDE percentage is invented. The 100% VT control explicitly checks each actual weld's current accepted baseline `VT` requirement. The 10% ITP lot-sampling basis is a separate source requirement subject to actual approved project extent and evidence review.

Checklist status: `missing`, `in_progress`, `accepted`, `not_applicable`, `stale`, or `rejected`. Source status: `needs_confirmation` or `confirmed`. Live item status: `in_progress`, `ready_for_issue`, `issued`, or `stale`; project summaries can also show `not_configured`. Checklist percentage counts current accepted or justified N/A entries out of the catalog; it does not by itself certify fabrication completion or shipment authorization.

### Live response shapes

Project detail:

```text
project, configured, config|null, version,
documents:[document metadata], items:[item summary], scope:[physical progress row],
issues:[project issue metadata], latest_project_issue|null, latest_issue|null,
handovers:[event], transfer_status:{digital:{status,dispatch,receipt},physical:{...}},
events:[audit event], permissions:{manage,write,review,editable_check_codes,upload_sections,can_handover},
source_status, source_review|null, completion_blockers:[string], fingerprint,
summary:{items,approved_packets,stale_packets,checklist_percent}
```

`latest_issue` aliases `latest_project_issue`. Transfer statuses are `not_dispatched`, `dispatched`, and `received`, referring to the latest project revision. Older revision transfer records remain visible in `handovers`.

Item summary is `{item_id,description,kind,status,percent,blockers,latest_issue,fingerprint}`. Live item detail:

```text
project, config, version, item,
sections:[{code,title,checks:[check view]}], records:{...}, documents:[metadata],
issues:[metadata], latest_issue|null, blockers:[string], status, percent,
permissions:{manage,write,review,editable_check_codes,upload_sections,can_handover}, source_status, source_review|null, fingerprint
```

`manage`, `write`, `review` and `can_handover` are booleans. `editable_check_codes` and `upload_sections` are exact string allowlists. `write=true` means some preparation is permitted, not that every check or section is writable. These authenticated-view hints do not enter physical evidence, checklist fingerprints or frozen issued records; changing the viewer's position does not change an issued revision's validity.

Check view includes its catalog definition and `{applicability,reference,notes,document_ids,values,status,blockers,latest_review,fingerprint}`. `records` groups actual data as `tracking`, `inspections`, `reworks`, `component_links`, `child_spools`, `flow`, `flow_events`, `flow_exceptions`, and `quality_records`. Tracking retains the actual weld register, individual requirement evidence/reviews, operations, repairs, holds and production timing. Linked quality/audit evidence and actions are included where they identify this item or its welds.

Document metadata:

```text
id, project_id, item_id|null, scope_key, code, title, revision, section,
reference, filename, media_type, size_bytes, sha256, actor, at, current
```

Issue metadata:

```text
id, project_id, item_id|null, scope_key, kind, revision, fingerprint,
sha256, print_sha256, reference, notes, actor, at, current
```

`current` is computed in live views and excluded from the exact historical issue endpoint. `kind` is `item` or `project`.

Handover event:

```text
id, project_id, issue_id, channel, event, dispatch_id|null,
recipient, organization, reference, notes, occurred_on, actor, at
```

`event` is `dispatch` or `receipt`. Receipt events reference their original dispatch; downloading does not create either event.

## Attachments and retained packages

Upload fields are `expected_version`, `code`, `title`, `revision`, `section`, optional `item_id` and `reference`, plus `file`. A missing item ID denotes a shared project document. File bytes are stored in PostgreSQL's `dossier_files` table, independently of metadata. Render filesystem persistence is not required.

Limits are 8 MiB per file, 256 MiB total historical attachment bytes per project, and 12 MiB per issued JSON snapshot. Allowed extensions are PDF, PNG, JPEG/JPG, UTF-8 TXT/CSV, XLSX and DOCX. The server validates type signatures, rejects empty files and unsupported MIME/content combinations, bounds Office archive metadata, makes filenames safe, and computes the SHA-256 itself. Downloads are authenticated attachments with `nosniff`, and validate the retained bytes against their recorded length/hash.

A document revision is immutable. A new revision of the same project/scope/code supersedes the prior revision for current reviews; it does not overwrite prior bytes. Each checklist selects exact document IDs. Review fingerprints include selected-document currentness, so supersession requires deliberate selection/review of the replacement. No unreviewed revision is silently substituted into an issued package.

An issued item snapshot freezes the actual generated records, checklist decisions, QA identities, references and selected file metadata. The rendered printable HTML is also retained and hashed separately, so a later renderer/template change cannot rewrite a previously issued printable artifact. Assemblies retain exact `child_issues`; their standalone ZIP includes those child packets and files. Project snapshots reference exact item issue IDs and hashes. A deterministic ZIP contains `manifest.json`, `snapshot.json`, printable HTML, generated-record JSON, and `files/{document_id}_{safe_filename}`. The manifest identifies related retained issues and every included document. A project ZIP includes retained item revisions beneath `items/` and a printable `project-handover.html` sheet. The sheet links to each exact issued item print/download and its included offline HTML. A complete paper set consists of the project cover, exact included item packets and their original file appendices. Related packets and selected shared files are deduplicated. External report identifiers and source citations are explicitly identified as references; they are not fetched or represented as embedded PDFs.

Issue hashes cover canonical UTF-8 JSON with sorted keys and compact separators. Individual attachment SHA-256 hashes cover the exact stored file bytes. These are integrity identifiers, not a cryptographic external digital-signature service. Authenticated QA identity, date, reference and audit history record who issued the revision. The package's historical contents stay exact after later evidence, custody, transfer or source changes; live views separately show whether that revision remains valid.

## Currentness and production gates

Checklist fingerprints follow relevant evidence. Pressure-test approval includes actual weld cycles, material identities, drawing/scope changes, construction operations, repairs/rework, component relationships and recursively relevant child-spool construction. It excludes routine custody, production timers, ordinary coating progression and dispatch milestones. Final packet validity also includes later coating/final QA evidence, current release and current child issues. Repaired construction must be reviewed against current test proof; ordinary logistics does not require reissuing the same unchanged quality package.

`dossier_gate_errors(s,item,phase='shipment',for_update=False)` is invoked by the existing process traveler. Its `for_update=True` caller holds the shared topology lock; it locks the configured project and applicable physical scope. No configured project, or an explicitly disabled gate, preserves previous routing behavior.

At coating steps 20/21, `phase='pre_coating'` requires current project source review plus current accepted pressure-test and applicable written customer hold-point release checks for the assembly and child spools. A justified, QA-reviewed N/A is permitted only where the approved scope supports it. This gate intentionally does not demand final release or a complete finished packet before coating.

At Ready to Ship/shipping steps 23/24, `phase='shipment'` requires complete current QA-issued packets for the assembly and child spools. All applicable checks, including separate written customer hold-point releases and D04 pre-shipment authorization, must be current. CLM review of a selected customer approval document records review of the actual authorization; it is not a substitute customer authorization. Existing weld, material, inspection, hold, audit and process gates continue to apply.

## Additive tables and exports

| Model | Table | Purpose |
|---|---|---|
| `DossierProject` | `dossier_projects` | Explicit enrollment, project metadata/rules, expected scope and edit version |
| `DossierEntry` | `dossier_entries` | Current saved checklist evidence/applicability, versioned in event history |
| `DossierDocument` | `dossier_documents` | Immutable scoped file metadata and revision identity |
| `DossierFile` | `dossier_files` | Immutable deferred binary bytes, one row per document |
| `DossierReview` | `dossier_reviews` | Immutable source/check decisions and their evidence snapshots |
| `DossierIssue` | `dossier_issues` | Immutable item/project issue, deferred exact JSON snapshot and deferred frozen printable HTML; separate snapshot/print hashes |
| `DossierHandover` | `dossier_handovers` | Immutable distinct dispatch and receipt events |
| `DossierEvent` | `dossier_events` | Append-only project edit history, unique project/version sequence |

The six history tables from documents through events are append-only. Binary `dossier_files` is intentionally excluded from the business Excel allowlist; document metadata/hashes and packet snapshots remain exportable. The issued ZIP is the complete selected-file deliverable. There is no destructive migration, automatic customer acceptance, production seed record, background email, or implicit download acknowledgment.
