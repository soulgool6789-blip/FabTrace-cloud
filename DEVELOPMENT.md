# FabTrace Cloud development guide

This guide describes the implemented tracking extension and the constraints that future changes must preserve. Start with [README.md](README.md) for setup and [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for the user workflow.

## Code map

| File | Responsibility |
| --- | --- |
| `main.py` | Shared SQLAlchemy models, sessions, authentication, employee/item/QR/custody APIs, legacy inspections and release, middleware, `/healthz`, and tracking-router integration. |
| `tracking.py` | Tracking tables, validated request models, project/spool/weld APIs, authoritative work and acceptance checks, versions, holds, repairs, and rollups. |
| `production.py` | Immutable spool process events, transition validation, visit/time projections, and automatic timer closure at final release. |
| `flow.py` | CLM 24-step catalog, component/spool/assembly travelers, hierarchy gates, checklists, custody, exception loops, and shipment/delivery records. |
| `exports.py` | Administrator-only Excel snapshot of business records and history, excluding authentication secrets. |
| `init_db.py` | Additive schema initialization, first-account bootstrap, PostgreSQL transaction/advisory lock, and immutable-history triggers. |
| `static/index.html` | Canonical application shell and existing login, inventory, custody, and QR interface; tracking workspace/dialog hooks. |
| `static/tracking.js` | Framework-free tracking UI, forms, role-aware actions, API requests, and direct-link routing. |
| `static/tracking.css` | Styles scoped to the tracking workspace and dialog. |
| `static/flow.js`, `static/flow.css` | Numbered process map, production board, route forms, hierarchy links, timer controls and mobile layout. |
| `index.html` | Distribution copy of the shell. Keep synchronized with `static/index.html`; the server serves the latter. |
| `migrate_google_part_numbers.py` | Earlier explicit migration for the Google part-number column. Review the actual schema before using an older migration. |
| `render.yaml`, `Procfile` | Deployment configuration. The Blueprint includes initialization before startup. |
| `tests/` | API regression tests, a Node client smoke harness, and guarded local PostgreSQL verification. |

`main.py` defines shared models and dependencies before importing the tracking, production, flow and export routers, in that order, at the end of the module. Extensions import those shared definitions and use lazy imports for reciprocal helpers. Preserve this registration order so `init_db.py` sees every table in `Base.metadata`.

## Data relationships

A `Project` has `Subproject` records. A `SpoolPlan` belongs to one existing `Item` and one project, with optional subproject and assembly links. The subproject must belong to the selected project. An assembly link references an existing item whose kind is `Assembly`; self-links, cycles, and contradictory project relationships are rejected.

Each `Weld` belongs to one spool item. Its generated ID is permanent; its joint `number` is unique within that spool. Metadata includes both material sides, heat/MTR references, WPS/revision, joint description, nominal size, wall thickness, drawing revision, and required physical operations.

`WeldRequirement` belongs either to a spool (`weld_id` is null) or a weld. Current-state rows reference separate evidence and review history. Evidence identifies a report/reference, result, notes, actor, timestamp, and verification cycle. Reviews identify the exact evidence revision reviewed. Work and repair events have their own physical-work cycle.

Verification cycles and physical-work cycles are distinct. A metadata correction or administrative reopen can invalidate verification without claiming that physical work must be performed again. An actual repair, or a changed physical-operation plan, starts a new work cycle.

## API overview

`GET /api/exports/excel` requires an administrator session and returns an XLSX attachment with MIME type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`. It does not return JSON on success. The **Export Excel** navigation action fetches with the authenticated cookie, shows a busy state, handles API errors, and downloads the response as a blob using the server filename. PIN hashes and private PINs are not exported. Evidence is exported as references/URLs, not report binaries. Workbook edits are not imported into the application.

All `/api/tracking` routes require an active authenticated employee. The existing HttpOnly cookie session supplies identity. Requests do not accept a substitute actor or reviewer.

| Method and route | Purpose |
| --- | --- |
| `GET /api/tracking/overview?project_id=&subproject_id=` | Projects, subprojects, templates, spool summaries, and separate progress metrics. |
| `GET /api/tracking/exceptions?project_id=&subproject_id=` | Outstanding scope, work, requirement, hold, dimensional, and rework records. |
| `GET`, `POST /api/tracking/projects` | List or create projects. |
| `GET`, `POST /api/tracking/subprojects` | List or create subprojects; list supports `project_id`. |
| `GET`, `POST /api/tracking/templates` | List or create immutable template revisions. |
| `GET /api/tracking/spools/{item_id}` | Item, optional plan, welds, spool requirements, holds, summary, and history. |
| `POST /api/tracking/spools/{item_id}/plan` | Explicitly enroll or update a controlled spool plan. |
| `POST /api/tracking/spools/{item_id}/welds` | Create a weld inside the planned scope. |
| `GET`, `PATCH /api/tracking/welds/{weld_id}` | Read or correct weld metadata; PATCH does not change its number. |
| `POST /api/tracking/welds/{weld_id}/work` | Record `fitup`, `root`, `fill_cap`, or `complete`. |
| `POST /api/tracking/spools/{item_id}/requirements` | Add a spool requirement. |
| `POST /api/tracking/welds/{weld_id}/requirements` | Add a weld requirement. |
| `POST /api/tracking/requirements/{id}/evidence` | Append evidence; never grants acceptance. |
| `POST /api/tracking/requirements/{id}/review` | Acceptance, rejection, or justified N/A by an authorized reviewer. |
| `POST /api/tracking/welds/{weld_id}/repairs` | Start a physical-work cycle without erasing prior records. |
| `POST /api/tracking/spools/{item_id}/holds` | Place a spool hold or a hold on one of its welds. |
| `POST /api/tracking/holds/{id}/close` | Record an authorized hold resolution. |
| `GET /api/tracking/processes` | Ordered starter process catalog; custom process names are also accepted when starting or moving. |
| `GET /api/tracking/spools/{item_id}/process` | Current process, per-process totals, every visit and immutable event history for an enrolled spool. |
| `POST /api/tracking/spools/{item_id}/process` | Append `start`, `move`, `pause`, `resume` or `finish`, using the current `expected_version`. |

Existing `/api/items/{id}/inspect`, `/release`, and `/reopen` remain the interfaces for dimensional inspection, final release, and administrative reopen. For an enrolled spool, aggregate `/weld` and `/inspect` with `kind: "Weld"` are rejected. Item detail exposes `tracking_enabled` and a tracking summary; item lists expose `tracking_enabled`.

### Request and response conventions

- Tracking inputs forbid extra fields and trim strings. Pydantic models in `tracking.py` define the authoritative limits and literals.
- Plan edits, weld corrections, evidence, and reviews require the current `expected_version`. Initial enrollment omits it. Reload after a conflict before submitting a new decision.
- Mutations return the relevant current record. Refresh the spool afterward because its counts, requirements, or readiness may have changed.
- Stages are `before_welding`, `after_welding`, and `release`. States are `pending`, `submitted`, `accepted`, `rejected`, and `not_applicable`.
- Requirement responses include `satisfied` and `check_errors`. Status text alone does not prove current satisfaction.
- Evidence, reviews, work, repair, and audit lists are newest first.
- Requirement and hold IDs are numeric; weld/template IDs are generated strings. Encode path parameters and retain their returned values.

## Authority and roles

| Action | Roles |
| --- | --- |
| Read tracking; submit evidence | Any active authenticated employee |
| Record production process timing | Any active authenticated employee; released items remain read-only |
| Create projects, subprojects, plans, welds, requirements, templates; correct metadata | Supervisor, admin |
| Record fit-up | Handler, welder, supervisor, admin |
| Record root, fill/cap, completion | Welder, supervisor, admin |
| Open tracking holds or repair cycles | Inspector, supervisor, admin |
| Review requirements, close holds, inspect dimensions, approve release | Inspector, admin |
| Reopen a released item; manage employees | Admin |

`owner_role` assigns responsibility; it does not grant approval permission. Frontend visibility helps usability, while the server enforces every permission and gate.

## Invariants to preserve

1. **Explicit enrollment.** Installing tables leaves legacy items and histories unchanged. A spool plan opts an item into individual tracking. Never infer accepted welds from aggregate counts or old green flags.
2. **One joint counts once.** Required operations are a nonempty subset of `root` and `fill_cap`. Root precedes fill/cap when required; completion follows every configured operation. Separate pass events are not additional joints.
3. **Evidence is not acceptance.** A reference, pass result, or work event cannot accept a requirement. New evidence invalidates prior acceptance. Failed evidence cannot be accepted or hidden by N/A.
4. **Current work needs current verification.** Physical work invalidates affected post-work evidence and approvals. Fit-up performed after approval needs new verification. Repairs preserve history and require the new cycle's work and reviews.
5. **Templates retain core gates.** Material, procedure/qualification, fit-up, visual, NDE-plan, and final-QA controls remain. Templates add requirements or permitted core labels/source/assignment; they cannot weaken core checks. Saved revisions affect newly created welds only.
6. **Release is derived.** Defined weld count must match the controlled plan; zero-weld scope needs a basis. Current requirements, physical completion, dimensions, holds, rework, and hierarchy are checked. Legacy summaries cannot override those checks.
7. **Identity and history persist.** Corrections use versions and audit records. Never overwrite evidence, reviews, work, repairs, or a saved template revision to conceal a change.
8. **Release scope is explicit.** Plain assembly links do not implement child-spool acceptance. Numbered assembly travelers additionally verify their declared children and descendant component readiness at their gates. Final release is not shipment or delivery.

## Concurrency and history

Tracking mutations lock the owning `Item` row before changing related state. Hierarchy-changing operations also take a PostgreSQL transaction advisory lock before the item lock. Reload the controlled record under the lock before checking its version; stale SQLAlchemy identity-map values must not bypass a conflict.

Keep validation, inserts, invalidation, counter synchronization, and audit creation in one transaction. Read-snapshot helpers preload records for one spool calculation; they are not a durable cache and must not be reused after writes.

`init_db.py` initializes PostgreSQL under an advisory lock in one transaction. It creates missing tables and installs `BEFORE UPDATE OR DELETE` protection on eight history tables:

- `audit_events`
- `tracking_requirement_evidence`
- `tracking_requirement_reviews`
- `tracking_weld_work`
- `tracking_weld_repairs`
- `tracking_requirement_templates`
- `tracking_process_events`
- `flow_events`

These triggers prevent ordinary mutation, not deliberate removal by a database owner. Requirements, holds, plans, and weld metadata are current-state records and remain mutable through controlled APIs.

## Production process timing

`SpoolProcessEvent` is additive and append-only. Its `(item_id, sequence)` pair is unique. `sequence` is also the spool's optimistic concurrency version, starting at zero before the first event. Every write takes the existing item row lock, re-reads the event history, checks the requested version and legal transition, and appends the event and audit record in one transaction. Only the server supplies timestamps and actors. Extra fields, unknown stages, backdating, stale versions and invalid transitions are rejected. A server clock earlier than the last event is rejected for writes; read projections clamp to recorded time.

POST bodies contain `action`, `expected_version`, optional `notes`, and—for start/move only—`process_key` plus `process_name` when the key is `custom`. A pause requires a reason. Start needs no open visit. Move closes the current visit and starts a different process at the same timestamp; it also works while paused. Resume needs a paused visit. Finish closes a visit without starting another. A custom process name is trimmed, whitespace-normalized and grouped without case sensitivity. The ten catalog keys remain stable even if labels are changed in a later release.

The pure `summarize_process_events` projection returns `item_id`, `version`, UTC `as_of`, `status`, `current`, `totals`, `by_process`, `visits` and `events`. Status is `not_started`, `running`, `paused` or `finished`; a closed visit has status `finished`. Numeric `elapsed_seconds = active_seconds + paused_seconds`. Durations use integer microseconds internally. Visit IDs are the sequence numbers of start/move events. Events and visits are oldest first. The spool detail embeds this full object as `production_process`; overview summaries include its current state and overall totals.

Timing starts only from explicit events. It measures calendar station/process duration, includes overnight time, and is not person-hours. Unstarted time and gaps after Finish are excluded. Manual timing does not modify weld work, requirements, custody, inspections or quality holds. `finish_on_release` closes an open visit inside the locked final-release transaction. For manually timed records, administrative reopen leaves timing stopped until a new Start. Numbered travelers own their stage transitions through `sync_flow_process`, including post-QA handoffs and a return to QA on a permitted reopen.

The Excel allowlist includes the raw process-event table. Two additional reports, `Process visits` and `Process totals`, derive from those events on the same read-only snapshot connection, one spool at a time. They include current project/subproject identifiers, numeric seconds and decimal hours, and an `as_of` timestamp for open visits. Historical events do not freeze earlier project assignments. Report rows use temporary spooled files and the existing sheet-continuation rules; no new runtime package is required.

## Numbered CLM process flow

`flow.py` transcribes the supplied chart into `STEPS` / `STEP_BY_NUMBER`, version `CLM-24-v1`. Routes retain the original numbering: component 1–8, spool 9–16, assembly 17–24. The catalog supplies role lists, checklist identifiers/text, scan/location/handoff/reference requirements and allowed rework destinations. Frontend forms consume those definitions and the authenticated `allowed_actions` response. Keep role enforcement and release gates on the server.

Four additive tables model the flow: `FlowPlan` is the current route/version/scope and shipment state; `FlowEvent` is its immutable revision history; `FlowException` retains failed inspections and controlled resolution metadata; `ComponentLink` is the current physical component-to-spool assignment. Existing `SpoolPlan.assembly_id` remains authoritative for spool-to-assembly membership. Events snapshot the definition version and step/checklist text so later catalog edits cannot silently rewrite the meaning of recorded observations.

All routes below use the existing badge session. Reads are available to active staff. Start/scope/link permissions are enforced separately from step roles.

| Route | Purpose |
| --- | --- |
| `GET /api/flow/catalog` | Current definition version, 24 steps and route boundaries. |
| `GET /api/flow/items?project_id=&subproject_id=` | Enrolled item summaries, current stage, readiness and timing. |
| `GET /api/flow/items/{id}` | Item, traveler and projected step statuses, linked identities, process clock, exceptions/events and permitted actions. |
| `POST /api/flow/items/{id}/start` | Explicitly enroll a route; declare child scope and optional documented later starting point. |
| `POST /api/flow/items/{id}/advance` | Verify the exact current checklist, identity, documents and custody fields, then advance one step. |
| `POST /api/flow/items/{id}/fail` | Record a verification/QA exception and return to an allowed earlier step. |
| `POST /api/flow/items/{id}/scope` | Correct required-child scope at spool step 9 or assembly step 17/18, with version, reason and reference. |
| `POST /api/flow/items/{id}/assign-component` | Assign or correct a component's spool before material selection is fixed. |
| `POST /api/flow/items/{id}/link-spool` | Add a released child spool to the assembly's controlled collection scope. |
| `POST /api/flow/items/{id}/deliver` | Record actual receipt reference and recipient after shipment. |

Every update after start requires `expected_version`. `FlowEvent.sequence` matches the traveler version; the independent process clock has its own sequence. Inputs forbid extra fields and do not accept actors or timestamps. A later starting baseline requires its existing-work reference and reason, leaves earlier steps `not_recorded` and does not bypass weld/QA readiness. Expected-child scope cannot be reduced below actual links. Zero newly linked components requires an explicit legacy material basis; assemblies always need at least one declared spool.

Mutations acquire the topology advisory lock `0x4641425452414345` before any Item lock, then refresh the traveler version. Membership, release/reopen, physical weld operations and manual timing controls share the relevant serialization order. Assembly validation locks child spools and descendant components before checking readiness. Generic component rework writers still take the same component Item lock, so they cannot race a locked assembly release decision. Never introduce a barrier or wait after acquiring the advisory lock in concurrency tests: synchronize the competing requests before that first serialization point.

Each numbered step uses the existing `SpoolProcessEvent` clock under `clm_01` through `clm_24`; it does not create a competing clock. A rework return creates another visit even if it returns to the same number. `flow_managed`, `flow_step` and `flow_status` identify the owner in process responses. Any enrolled flow rejects manual start/move/finish; pause/resume is allowed while active, including the explicitly permitted post-QA steps 16/23/24. Completing component/spool routes or recording shipment closes the current clock.

`main.finalize_release` is a transaction helper with no internal commit. Its original weld/inspection checks plus `flow_release_errors` run when an authorized inspector advances step 15 or 22. Matching exception resolutions flush inside that transaction; a failed release rolls them back. The helper closes the quality-process visit, then the traveler starts its next post-QA step at the same timestamp. Generic final release cannot skip the traveler QA gate. Generic reopen is blocked for shipped/delivered assemblies and for child spools whose parent is past the permitted rework stage; permitted flow reopening returns to QA 15/22 and invalidates applicable verification.

Failures at 11 invalidate before-welding requirement approvals; failures at 15 invalidate post-weld/release approvals. Other QA failures require fresh dimensional verification where relevant. Physical repair cycles remain explicit individual-weld actions. Fit-up is allowed at spool 10 or 14, welding at spool 14, and assembly joining operations at 18. Completing assembly work at 18 and coating at 21 requires fresh dimensions afterward. Material holds/open rework are checked recursively through components, spools and assemblies through shipment.

`shipped` requires the current step 24, item verification, checklist, carrier, shipment reference and destination; it stores `shipped_at`. Only a later delivery action sets `delivered_at`, `receipt_reference`, `recipient` and status `delivered`. Document references do not imply generated/archived PDFs or carrier-system integration. The recorded handoff identifies the recorder and receiving badge but does not fabricate the recipient's independent acknowledgment.

Excel exports explicitly allowlist all four flow tables, plus a `Flow steps` definition sheet. Flow event JSON retains its captured checklist definition. The process reports join a component through `ComponentLink` to its parent's current project/subproject; unassigned component report project IDs are blank and the original free-text Item project remains in the Items sheet. Definition/report rows are distinguished from raw database records in Export info.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
node tests/tracking_ui_smoke.cjs
node tests/export_ui_smoke.cjs
node tests/process_ui_smoke.cjs
node tests/flow_ui_smoke.cjs
```

API fixtures use temporary SQLite databases, override imported database settings, and create synthetic employees and authenticated sessions. They cover legacy behavior, roles, stale decisions, evidence, scope, operations, repairs, holds, hierarchy, and release. SQLite tests do not establish PostgreSQL locking or trigger behavior.

The Node harness runs without a framework or network. It checks route/render contracts, role controls, sequencing, escaped evidence, safe links, versions, and failed-write recovery. It is not a full browser layout/accessibility test.

For PostgreSQL behavior, provision a separate local test database with a name beginning `fabtrace_test_`, then inspect the guard and options:

```bash
python tests/verify_postgres.py --help
python tests/verify_postgres.py --dsn 'postgresql+psycopg://USER@localhost/fabtrace_test_upgrade'
```

Replace `USER` with the local test user and supply the local connection settings. The script requires an explicit local loopback or Unix-socket DSN, rejects remote/service overrides and operational database names, and does not inherit a production `DATABASE_URL`. Each run creates a UUID-named schema and removes that schema afterward. It verifies legacy-row preservation, repeated initialization, all eight history triggers, competing evidence/process/flow writes, and the read-only Excel snapshot. Do not loosen its guard to use the operational database.

## Adding the next feature

Choose the record's scope first: project, spool, weld, or a new cross-spool package. Extend validated server models and release rules before adding controls. Add regression coverage for the changed acceptance/invalidation rule and retain legacy-item behavior. Keep ordinary scans and form entry short.

Future schema changes require versioned migrations. `Base.metadata.create_all()` creates absent tables; it does not alter existing columns, constraints, or indexes. Do not change a model and assume deployment will migrate existing data. Plan an explicit migration, ordering, representative-data verification, and rollback implications. Preserve history.

Features that need deliberate additional models:

- **Report uploads:** file storage, authorization, retention, and links to immutable evidence. Current evidence stores references/URLs only.
- **Automatic qualification applicability:** structured ranges, continuity, governing rules, and revisions. Current acceptance is an inspector's evidence-backed review.
- **NDE sampling, pressure-test packages, cross-spool field tie-ins, carrier/document integrations and richer field-return workflows:** each needs explicit scope and lifecycle rules. Basic child assembly readiness and shipment/delivery confirmation are already implemented in the numbered traveler.

Project-specific NDE, PMI, PWHT, hardness, and other requirements can already be configured. Approved project documents supply their technical criteria and extent; this release infers no universal code rule or NDE percentage.
