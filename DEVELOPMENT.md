# FabTrace Cloud development guide

This guide describes the implemented tracking extension and the constraints that future changes must preserve. Start with [README.md](README.md) for setup and [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for the user workflow.

## Code map

| File | Responsibility |
| --- | --- |
| `main.py` | Shared SQLAlchemy models, sessions, authentication, employee/item/QR/custody APIs, legacy inspections and release, middleware, `/healthz`, and tracking-router integration. |
| `orders.py` | Explicit PO/project enrollment, GPN groups, physical assembly part numbers and spool-count scope, versioned audited changes and existing-plan/traveler guards. |
| `order_setup.py`, `static/order-setup.js`, `static/order-setup.css` | Simple P.O./assembly/spool quantity planning, atomic three-step setup, shared physical quantity guards, and primary Purchase orders navigation. |
| `order_spools.py`, `order_labels.py`, `static/order-labels.js`, `static/spool-qr.js` | Permanent readable physical-spool aliases, global per-number allocation, P.O. quantity generation, authenticated alias resolution and read-only reprinting. |
| `order_spools.py` | Physical spool registration before weld planning, fixed assembly/requirement scope, and deduplicated registered/planned child relationships. |
| `spool_documents.py`, `isometric_import.py` | Immutable spool documents, shared full drawings, signed extraction review, atomic per-spool Excel BOM creation, and authenticated downloads. |
| `static/document-piece-qa.js`, `static/document-piece-qa.css` | Individual material rows and existing per-piece QA-001 controls embedded in the active saved BOM page. |
| `spool_receiving.py`, `spool_boms.py` | Physical-spool BOM pinning/adoption, saved per-piece heat/MTR registers and QA-001 decisions, immutable MTR revisions, basis-bound arrival Pass/Fail, and production gating. |
| `isometric_bom.py`, `isometric_ocr.py` | Spatial extraction of per-spool drawing tables and bounded local OCR for scanned pages. |
| `removals.py`, `static/removals.js`, `static/removals.css` | Administrator removal previews, reversible batch state, active-scope guards, affected-record confirmation and restoration. |
| `orders_excel.py` | Scoped read-only BOM snapshots and editable planning templates using the existing standard-library XLSX writer. |
| `static/orders.js`, `static/orders.css`, `ORDERS_GUIDE.md` | PO-first navigation, GPN/assembly planning, required/linked/ready counts, existing work shortcuts and Excel downloads. |
| `tracking.py` | Tracking tables, validated request models, project/spool/weld APIs, authoritative work and acceptance checks, versions, holds, repairs, and rollups. |
| `production.py` | Immutable spool process events, transition validation, visit/time projections, and automatic timer closure at final release. |
| `flow.py` | CLM 24-step catalog, component/spool/assembly travelers, hierarchy gates, checklists, custody, exception loops, and shipment/delivery records. |
| `transfers.py` | Shared sender/receiver validation, versioned custody/location/status state, managed location catalog and ordinary transfer API. |
| `administration.py` | Explicit admin release/return/custody decisions, current release provenance, versioned employee access and session revocation. |
| `permissions.py`, `PERMISSIONS_GUIDE.md` | Shared job-position policy, permission catalog and operating matrix; no database writes or automatic employee assignments. |
| `static/admin.js`, `static/admin.css`, `ADMIN_GUIDE.md` | Administrator workspace, employee controls, role-aware navigation and operating instructions. |
| `static/handoff.js`, `static/handoff.css`, `HANDOFF_GUIDE.md` | Shared badge/location/status controls, camera lifecycle, ordinary handoff page and operating instructions. |
| `parts.py` | Optional spool parts plans, whole-piece requirement lines, unique physical allocations, quantity projections and audited scope controls. |
| `static/parts.js`, `static/parts.css`, `PARTS_GUIDE.md` | Parts-list editor, QR allocation, current quantity progress and operating instructions. |
| `quality.py`, `quality_templates.py` | Audit workspaces, draft customer matrix, controlled document revisions, actual evidence, corrective actions, signed reviews and optional project gates. |
| `QUALITY_API.md` | Quality endpoint contracts, payloads, state meanings, review permissions and dependency rules. |
| `dossier.py`, `dossier_templates.py` | Project-scoped Job Packet checklist, immutable uploaded files/reviews/issues, physical/digital handovers, currentness and coating/shipment gates. |
| `progress.py` | Read-only project/part scope, recorded progress, physical completion, filters and sorting. |
| `production_progress.py`, `static/production-progress.js`, `static/production-progress.css` | Read-only P.O. production trees, unique-item stage totals, and expandable P.O./GPN/assembly/spool/part progress. |
| `DOSSIER_API.md`, `DOSSIER_GUIDE.md` | Packet/progress contracts and the operating guide for preparation, issue and transfer. |
| `exports.py` | Administrator-only Excel snapshot of business records/history and calculated timing/readiness reports, excluding authentication secrets. |
| `init_db.py` | Additive schema initialization, first-account bootstrap, PostgreSQL transaction/advisory lock, and immutable-history triggers. |
| `static/index.html` | Canonical application shell and existing login, inventory, custody, and QR interface; tracking workspace/dialog hooks. |
| `static/navigation.js`, `static/navigation.css` | Compact main menu, app-only contextual Back history, same-app deep-link parents, in-memory draft restoration and save-navigation guards. |
| `static/tracking.js` | Framework-free tracking UI, forms, role-aware actions, API requests, and direct-link routing. |
| `static/tracking.css` | Styles scoped to the tracking workspace and dialog. |
| `static/flow.js`, `static/flow.css` | Numbered process map, production board, route forms, hierarchy links, timer controls and mobile layout. |
| `static/quality.js`, `static/quality.css` | Five-prompt audit workspace, role-aware forms, evidence and document registers, corrective actions, printable audit view and Excel shortcut. |
| `static/progress.js`, `static/progress.css`, `static/dossier.js`, `static/dossier.css` | Registered-parts dashboard and Job Packet preparation, review, upload, issue, print/download and handover forms. |
| `static/guide.js`, `static/guide.css` | Searchable/printable operating instructions and read-only project setup checklist using the existing progress/dossier APIs. |
| `index.html` | Distribution copy of the shell. Keep synchronized with `static/index.html`; the server serves the latter. |
| `migrate_google_part_numbers.py` | Earlier explicit migration for the Google part-number column. Review the actual schema before using an older migration. |
| `render.yaml`, `Procfile` | Deployment configuration. The Blueprint includes initialization before startup. |
| `tests/` | API regression tests, a Node client smoke harness, and guarded local PostgreSQL verification. |

`main.py` defines shared models and dependencies before importing the tracking, production, flow, parts, quality, dossier, progress, transfers, administration, orders, removals, order_setup, production_progress, exports and orders_excel routers, in that order, at the end of the module. Extensions import those shared definitions and use lazy imports for reciprocal helpers. Preserve this registration order so `init_db.py` sees every table in `Base.metadata` and the shared XLSX writer is registered before its scoped consumer.

## Individual material approvals on the saved BOM page

Version `2026.10.31-bom-table-qa.1` displays the physical piece register directly in **BOM & drawings → BOM**. A two-flange line and one-pipe line become three quantity-one rows, with a separate heat/MTR editor and QA-001 Pass/Fail fieldset at the right of each row. The existing Materials & QA/QC workspace and this table use the same records, versions, inspection history and write endpoints. This correction adds no schema, migration, approval backfill or duplicate material model.

Authenticated `GET /api/spool-documents/{scope}/{identity}/material-records?spool_id=...` resolves the exact physical scope in a read-only snapshot. A physical entry selects itself; a requirement entry lists only its active registered copies and requires selection when more than one exists. The response includes the selected register, readable spool identities, current document ID and explicit source-match metadata. Never show a physical copy's approval on another copy, an individual override's approval on its shared requirement BOM, or a pinned old revision's approval on a new drawing. The client checks both the viewed file ID and the register's effective/pinned source before enabling row actions. Historical file previews remain reference-only.

The table reuses the existing traceability PUT and piece QA-001 POST/GET routes. A row material save overlays only that row's heat/MTR fields onto the last saved full register, preserving other rows' unsaved drafts without committing them. QA saves use the selected piece's current version and evidence hash; conflicts retain entered findings and require reloading/review. A permitted employee can explicitly adopt the displayed current replacement through **Use this BOM for this spool**, using the existing version/hash-bound adoption endpoint and a reason. It starts new blank pending pieces only for that copy and retains earlier records in history. Existing role, release, evidence, reinspection and overall arrival gates remain authoritative. The source table's notes and drawing page are joined by line position, never by possibly repeated item text. Read-only quantity expansion follows the same whole-piece unit rules and 500-piece cap as the material register.

`FabDocumentPieceQa` mounts only in the active saved BOM panel. It integrates with document-modal Back, tab changes, draft snapshots and global navigation guards. Saves block navigation until their response is handled; view changes invalidate pending reads. Desktop rows become stacked piece cards on narrow screens. The focused API and real-browser tests are `tests/test_spool_document_material_records.py` and `tests/document_piece_qa_browser_smoke.cjs`; browser runs use the isolated loopback fixture, never production records.

## Simple P.O. quantity setup

Version `2026.10.30-setup.1` makes `FabOrderSetup.open({po})` and `/?order-setup=1&po=PROJECT_ID` the primary Purchase orders experience and the administrator/supervisor landing page. The three steps ask only for P.O. number, repeated Google part number / assembly numbers with assembly quantities, and spool-number quantities **per assembly**. The final save is atomic. `FabOrders.open` and `/?orders=1` remain the secondary **Production records** workspace; existing physical item and process deep links are retained.

### Schema and quantities

`order_assembly_requirements` stores one current `assembly_quantity` for an existing `OrderGpn`. `order_spool_requirements` stores its named spool requirements, each with `quantity_per_assembly`, a normalized number, active state, actor and timestamps. These are requirements for future physical units. They do not create `Item`, `OrderAssembly`, `SpoolPlan`, custody, traveler, work, QA or dossier records. The initializer adds these two absent tables (50 tables in release `2026.10.30-setup.1`; the later spool registry adds one), changes no existing columns and performs no quantity backfill. The existing nineteen immutable history/file protections remain; current planning revisions are evidenced by immutable Audit events.

A new setup accepts 1–100 assembly rows. Each row has 1–200 distinct spool-number rows. Both quantity fields are strict integers from 1 to 10,000, and the sum of spool quantities for one assembly must be at most 10,000. P.O. numbers are 2–200 characters; GPN and spool numbers are 1–160 characters. Identifiers remain text, preserving leading zeros. `orders._key` normalizes whitespace and case for duplicate checks. The same spool number may belong to different GPNs; it appears only once per GPN with its quantity.

For one spool line, `total_quantity = assembly_quantity * quantity_per_assembly`; branch `total_spools` is assembly quantity times the sum of its per-assembly spool quantities. `_totals` leaves overall quantities null when scope is undeclared or empty and also returns `known_assembly_quantity`/`known_total_spools` subtotals. Legacy physical counts never substitute for an ordered quantity. `requirements_by_gpn` provides grouped current requirement rows to order detail, progress, Excel and registration guards.

### Endpoints and authority

| Endpoint | Behavior |
| --- | --- |
| `GET /api/order-setup` | Active P.O. register, quantity totals and permissions. |
| `GET /api/order-setup/{project_id}` | Saved GPN quantities, spool lines, current order version, edit eligibility and legacy/physical-scope status. |
| `POST /api/order-setup` | `expected_version: 0`, `purchase_order`, and `assemblies: [{gpn, assembly_quantity, spools: [{spool_number, quantity_per_assembly}]}]`; creates the project, P.O., groups and requirements together. |
| `POST /api/order-setup/{project_id}/assemblies` | Add one assembly-number requirement at the current order version without replacing other branches. |
| `PATCH /api/order-setup/{project_id}/assemblies/{gpn_id}` | Correct one eligible branch or complete an empty legacy GPN at the current version, with a 4–3,000-character reason. |

All supported active employees can read. Writes require administrator/supervisor authority, refreshed after the topology lock, and the expected order version. Simple P.O. creation rejects any existing matching normalized number, even under a different legacy customer, because this form deliberately asks for no customer. Removed identities remain reserved. Mutations append `ORDER_SETUP_CREATED`, `ORDER_SETUP_ASSEMBLY_ADDED` or `ORDER_SETUP_ASSEMBLY_UPDATED`, including exact before/after requirements, actor and order revision. `_save_requirements` reuses a spool line's identity by normalized number; omitted lines become inactive and may later be reactivated under the same ID. No full-order replacement or implicit deletion of other saved GPNs is provided.

A branch becomes ineligible for initial-setup edits once any physical `OrderAssembly` mapping exists, including retained removed mappings. An editable empty legacy GPN keeps its existing ID when quantities are entered. Removal/restore retains requirement rows and their identifiers; active views omit removed P.O./GPN scope. Both GET endpoints release the authentication connection before using the existing read snapshot (PostgreSQL REPEATABLE READ READ ONLY or an explicit SQLite read transaction). `editable` describes scope eligibility and must be combined with the server's `permissions.can_manage` and current role capabilities in the UI.

`guard_assembly_registration` enforces the saved physical assembly count, exact per-assembly spool count, matching assembly part number and already-linked spool type quantities. `guard_spool_requirement` checks an actual spool's part number against an active planned spool number and its quantity limit for that one physical parent assembly. Existing order, spool-plan, flow linking and explicit part-number correction paths call these guards under their normal locks. Initial setup never rewrites old physical identities or supplies a zero-weld justification or QA release.

### Progress and Excel integration

The active P.O. progress projection exposes `quantity_plan`, `registered_assemblies` and `registration_needed` for a GPN and adds `missing_assemblies` to summaries. Missing unregistered assemblies contribute their expected spool shortfall once; registered assemblies contribute their own existing linked-spool shortfall. Requirements create no placeholder physical nodes or recorded-step denominator. Planned-only P.O.s therefore retain unknown physical progress and explicit registration gaps. Current traveler events, rework resets, holds and quality finish remain authoritative.

The administrator raw backend workbook includes **Assembly quantity plans** and **Spool quantity plans**, including retained inactive lines. The scoped BOM and template add **Setup quantities** when declared requirements exist in the selected scope. Its columns include assembly quantity, spool number, quantity per assembly, total quantity, physical Assembly ID and quantity scope. An unfiltered P.O. or GPN export uses the full saved assembly quantity. Selecting one physical assembly uses a multiplier of **1**, labels that scope explicitly and excludes other branches. The material BOM still counts each actual physical spool's materials once; it is not multiplied by the planned assembly or spool quantity again. No Excel import or automatic synchronization is introduced.

## Expandable P.O. production progress

Version `2026.10.30-progress.1` adds `GET /api/progress/orders?project_id=` for active authenticated employees. An omitted/blank project ID returns all active enrolled P.O.s; a supplied ID selects one active P.O. while keeping the complete P.O. selector available. An unknown, removed or unenrolled ID returns 404. The endpoint releases the authentication connection before opening the existing consistent read snapshot (PostgreSQL REPEATABLE READ READ ONLY, or an explicit SQLite read transaction). It makes no business writes, holds no row/advisory locks and adds no tables.

The response includes `as_of`, `selected_project_id`, `choices`, `definitions`, `stage_catalog`, full-scope `summary` and `stages`, and `orders`. Each order contains its GPN groups and unassigned physical records. A GPN group contains its actual assembly instances; physical nodes contain `children`, their own `progress`, `steps`, `stages`, current step/location/custodian, and explicit scope/readiness warnings. Parent summaries aggregate unique physical identities. Removed branches are excluded from this active view, while existing historical progress, exports and issued Job Packets keep their retained identities.

The six fabrication phases are Inventory (1–4), Prep (5–8), Fit-up (9–12), Welding (13–16), Assembly (17–19) and Finish (20–22). Components contribute eight applicable fabrication steps, spools contribute eight, and assemblies contribute six. Shipping steps 23–24 and delivery remain separate facts. Only actual current-pass `advance` events count as recorded completion; fail/reopen/administrative-return events reset affected downstream steps. Historical baseline steps remain `not_recorded`. A parent reaching Finish never completes a child's own route, and an administrator's release never supplies missing work or ordinary QA evidence.

Percentages describe the registered physical scope. Missing required spools/parts, undeclared scope and draft GPNs remain explicit; unknown quantities do not become invented denominator values. Empty scope has no percentage. A recorded 100% is displayed with incomplete-scope warnings unless the required scope is satisfied. Physical finish/preparation, holds, recorded-step progress, shipping and delivery are separate fields. Aggregate phases without declared scope use `scope_unknown`; phases outside an individual item's route may use `not_applicable`.

The projection calls the existing `progress.project_rows` once per request and preloads additional current flow/custody/hold facts. That historical helper retains its existing per-item parts/readiness queries; this feature does not change dossier fingerprints or claim a constant database-query count. The browser renders detail bodies when expanded, retains ancestors for filtered matches, and keeps full-scope totals while filters narrow the displayed rows. It cancels stale navigation/refresh requests. The new deep link is `/?production-progress=1&project=PROJECT_ID`; the old `/?progress=1&project=PROJECT_ID` and `FabProgress.open` remain available as Project detail for legacy projects.

## Purchase-order hierarchy and API

### Reversible record removal

Version `2026.10.30-removal.1` adds `record_removals`, a current-state sidecar keyed by `kind` (`order`, `gpn`, `item`) and `record_id`. Initialization adds the absent table without rewriting existing business rows. Historical identities and all nineteen immutable history protections remain. Removal/restore appends `RECORD_REMOVED` / `RECORD_RESTORED` Audit events and one order revision per affected P.O.; the administrator, reason, affected identities and original removal group are recorded.

`GET /api/removals` lists current removed roots. `GET /api/removals/{kind}/{record_id}?action=remove|restore` returns the title, exact confirmation value, affected scope, blockers, current removal version and a SHA-256 preview token. `POST /api/removals/{kind}/{record_id}/remove` or `/restore` accepts `expected_version`, `preview_token`, `confirmation` and a reason of at least four characters. All endpoints require an administrator. The writer takes the existing topology lock, refreshes authority, recomputes the preview and rejects stale scope before writing. The preview token is a currentness check, not a credential.

A P.O. removal marks its GPNs and canonical project/physical descendant scope in one batch; a GPN or assembly marks its corresponding branch. Restoring the root changes only still-removed states belonging to that exact batch. Earlier independent removals stay removed, and a removed ancestor blocks child restoration. Identifiers stay reserved. Independently linked child removal and open process timers are blocked instead of changing production scope or certifying work. No Item, link, required quantity, evidence, issued snapshot, approval or work event is deleted.

Operational queries use explicit active predicates. Historical queries, raw exports and `progress.project_rows` preserve the retained scope needed by issued packets. Item/project write paths, including legacy flow, transfer, administration, evidence and scope APIs, validate active scope after topology locking. New packet issue/handover cannot treat removed retained parts as complete. Removed direct views expose removal metadata and disable operational controls. `exports.TABLE_SPECS` includes the new state table; active scoped BOM downloads omit removed branches and removed unassigned items.

The retained physical-registration interface introduced in version `2026.10.30-orders.3` uses a single GPN/Assembly number and three UI levels: P.O, GPN / Assembly, Spools. The backing tables and old endpoint contracts remain available, preserving all existing identities and history. Physical registration uses one atomic `POST /api/orders/{project_id}/gpn-assemblies` with `expected_version`, `gpn`, `required_spools`, optional notes, and either `create_item` (actual location/handler, optional custom ID/drawing) or an existing `item_id`. Optional `gpn_id` explicitly completes an existing matching draft. Omitting a new physical ID generates an `ASM-…` ID server-side. Creation sets the new mapping's assembly part number and new physical item's part number to the canonical GPN, supplies a blank description, and creates no weld plan, traveler or approval. An unplanned already-mapped GPN retains its legacy duplicate guard. A GPN with saved quantity requirements permits further distinct physical instances up to that quantity, subject to `guard_assembly_registration`; older multiple-instance groups remain readable through their actual physical IDs.

`PATCH /api/orders/{project_id}/gpn-assemblies/{item_id}` takes the current version, combined number, required spool count, notes and a correction reason. An eligible number correction updates the GPN and mapping together, and updates a physical part number only if it was blank or matched the previous GPN. Unchanged-number edits preserve differing legacy mapping numbers. Shared GPNs with multiple assemblies cannot be renumbered through a single row; traveler/release/count guards remain authoritative. Responses include `selected_gpn_id` and `selected_assembly_id`; detail adds `number_editable` and `combined_number_matches` hints. The UI must still enforce all server errors and stale request protection.

Scoped Excel workbooks use one `GPN / Assembly number` plus the distinct physical `Assembly ID`. A `Retained assembly part number` column is included only when the selected scope contains differing old numbers, populated only where relevant. Raw backend/history exports and issued dossier snapshots are unchanged. No schema migration or automatic enrollment is performed.

The preceding `2026.10.30-orders.2` release removed physical item descriptions from current forms, labels and lists, and assembly/spool description columns from scoped Excel workbooks. `ItemIn`, `BulkItemRow` and `AssemblyItemIn` accept omitted/blank descriptions with an empty-string default while retaining the maximum length and compatibility with old supplied values. The existing database column, raw history/export fields and issued snapshots remain; no schema migration or data rewrite occurs. Material requirement descriptions and technical work/QA explanations remain intact.

`purchase_orders.project_id` references the unchanged structured Project. Creating a PO atomically creates that project or explicitly attaches an existing one with a reason. `order_gpns` groups assemblies within the PO. `order_assemblies.item_id` references the existing physical Assembly Item and stores its distinct assembly part number and required spool count. Spools retain their existing `SpoolPlan.project_id` and `assembly_id`; component BOMs retain the existing parts-plan/line/allocation tables. No existing data is automatically enrolled or renamed.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/orders` | Order register, counts, unassigned structured projects and management permissions. |
| `POST /api/orders` | Create PO/project together or explicitly attach an existing project. Initial expected version is zero. |
| `GET /api/orders/{project_id}` | PO/GPN/assembly detail, current spool readiness, eligible assembly links and change history. |
| `PATCH /api/orders/{project_id}` | Correct PO details using expected version and reason; an existing Job Packet PO must agree. |
| `POST /api/orders/{project_id}/gpns` | Add a GPN group at the current order version. |
| `PATCH /api/orders/{project_id}/gpns/{gpn_id}` | Correct group metadata with a reason; controlled production prevents GPN renumbering. |
| `POST /api/orders/{project_id}/assemblies` | Attach an eligible physical Assembly or atomically create it, with its part number and required spool count. |
| `PATCH /api/orders/{project_id}/assemblies/{item_id}` | Versioned assembly metadata/count correction; active traveler or release locks count and part number. |
| `GET /api/orders/{project_id}/bom.xlsx` | Read-only material/progress workbook; optional validated `gpn_id` and `assembly_id` filters. |
| `GET /api/orders/{project_id}/bom-template.xlsx` | Editable offline planning template for the same validated scope. No import/write occurs. |

All writes require administrator/supervisor authority, the current order version and the existing topology lock. Changes append immutable `ORDER_*` Audit events with before/after scope. Duplicate normalized customer/PO and per-order GPN identities are constrained in the database. Failed duplicate creation rolls back its new project. Required spool counts are strict integers from 1 to 10,000; matching guards in legacy planning, spool linking and traveler setup prevent alternate endpoints from overfilling or moving enrolled assemblies across scope. Assembly registration does not manufacture a zero-weld plan, a traveler or QA acceptance.

Read endpoints release the authentication connection before opening their separate consistent snapshot. PostgreSQL uses REPEATABLE READ READ ONLY; SQLite uses an explicit read transaction. Ready counts require current ordinary QA readiness and the completed spool route; administrative release does not silently satisfy that measure. PO detail includes missing/planning blockers and a lightweight `order_scope` is exposed in flow detail. Existing issued dossier snapshots are never rewritten by order enrollment or read views.

The two scoped workbooks reuse `exports.WorkbookWriter`, preserving text identifiers and literal formula-like input, numeric quantities and long-text continuation handling. They include assembly summary, material/template, spool register and export information, plus Setup quantities when declared requirements are in scope. Quantities are taken once from each actual physical spool's parts plan. Missing spool/BOM scope is explicit; unknown quantities stay blank. Unfiltered exports include unmapped legacy project items with a planning warning. All active supported roles can read these workbooks; the full backend workbook remains administrator-only and includes the three order hierarchy tables plus both quantity-requirement tables. No runtime dependency, upload endpoint or Excel synchronization is added.

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

`permissions.py` defines ten application positions: `admin`, `supervisor`, `handler` (Material coordinator), `welder`, `fitup_welder`, `process_welder`, `inspector` (QA/QC), `painter`, `finisher` and `misc`. An employee has one position. Existing assignments remain unchanged, including full authority for existing administrators. Unknown positions receive no capabilities. See [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for the full work, timing and documentation matrix.

| Action | Roles |
| --- | --- |
| Read shared tracking; record ordinary dual-badge custody transfers | Any active employee in a supported position; custody does not grant work authority |
| Submit requirement evidence | Exact `owner_role`; general welder also covers fit-up/process-welder ownership; admin, supervisor and inspector have submission oversight |
| Record production process timing | Assigned process scope; admin/supervisor may coordinate all timers; move requires authority over both current and destination process |
| Create projects, subprojects, plans, welds, requirements, templates; correct metadata | Supervisor, admin |
| Record fit-up or complete step 10 | Welder, fit-up welder, admin |
| Record root, fill/cap, completion or legacy weld quantities; complete step 14 | Welder, process welder, admin |
| Complete preparation step 7 / sandblast-paint step 21 | Finisher/admin / painter/admin, respectively |
| Perform QA steps 2, 11, 15, 19 and 22 | Inspector, admin |
| Open tracking holds or repair cycles | Inspector, supervisor, admin |
| Review requirements, close holds, inspect dimensions, approve release | Inspector, admin |
| Close a free-text legacy rework ticket | Supervisor, admin; actual scoped work and fresh QA remain separate |
| Reopen a released item; manage employees | Admin |

`owner_role` is enforced for evidence submission and never grants approval permission. Existing default inspector-owned requirements therefore require QA/QC or management submission. Specialists do not inherit general-welder requirements. Supervisors retain planning and coordination without physical welding/painting completion. Frontend visibility follows server permission hints; every mutation independently enforces its permission and state checks.

### Permission response contracts

`GET /api/permissions` returns `{version, roles, current}`. Catalog rows contain `id`, `label`, `description` and the position's policy lists. `POST /api/login` and `GET /api/me` return `badge`, `name`, `role`, `role_label` and `permissions`. The permission lists are `capabilities`, `weld_operations`, `process_keys`, `dossier_check_codes` and `dossier_upload_sections`. Admin employee responses include the same label/lists; `GET /api/admin/employees` also includes the role catalog.

Authenticated Item detail adds `permissions` with `can_weld`, `can_inspect`, `can_open_rework`, `can_release` and `can_reopen`; each rework adds `can_close`. Welds expose `allowed_operations`; requirements expose `permissions.can_submit_evidence` and `can_review`. Process responses expose `permissions.allowed_actions` and `allowed_processes` (`{key,label}` rows). Flow retains its `allowed_actions` and role-bearing step catalog; its pause/resume choices use current process permissions.

Job Packet permissions include `manage`, `write`, `review`, `editable_check_codes`, `upload_sections` and separate `can_handover`. Trades may prepare only their allowed checks/sections; admin/supervisor/inspector may prepare all. Handler, supervisor, inspector and admin may record dispatch/receipt; only inspector/admin may review or issue. Upload authorization checks every prior section for the same project, scope and document code, preventing a new revision from bypassing restrictions by changing its section.

These fields are presentation hints, not evidence or a promise that a workflow is ready. Tracking/process serializers accept an optional user and leave internal `user=None` projections unchanged. Keep user-dependent permission data out of actual-record, construction and checklist fingerprint bases, including the physical/quality records retained inside issued snapshots. Packet-level presentation metadata may retain the issuer's view, but does not enter the acceptance fingerprint or grant a later viewer authority. Opening a view under another position must not invalidate existing approvals.

## Invariants to preserve

1. **Explicit enrollment.** Installing tables leaves legacy items and histories unchanged. A spool plan opts an item into individual tracking. Never infer accepted welds from aggregate counts or old green flags.
2. **One joint counts once.** Required operations are a nonempty subset of `root` and `fill_cap`. Root precedes fill/cap when required; completion follows every configured operation. Separate pass events are not additional joints.
3. **Evidence is not acceptance.** A reference, pass result, or work event cannot accept a requirement. New evidence invalidates prior acceptance. Failed evidence cannot be accepted or hidden by N/A.
4. **Current work needs current verification.** Physical work invalidates affected post-work evidence and approvals. Fit-up performed after approval needs new verification. Repairs preserve history and require the new cycle's work and reviews.
5. **Templates retain core gates.** Material, procedure/qualification, fit-up, visual, NDE-plan, and final-QA controls remain. Templates add requirements or permitted core labels/source/assignment; they cannot weaken core checks. Saved revisions affect newly created welds only.
6. **Ordinary QA release is derived.** Defined weld count must match the controlled plan; zero-weld scope needs a basis. Current requirements, physical completion, dimensions, holds, rework, and hierarchy are checked. Legacy summaries cannot override those checks. The separately authorized administrative release records an explicit exception and its outstanding conditions; it does not create QA acceptance or passing work records.
7. **Identity and history persist.** Corrections use versions and audit records. Never overwrite evidence, reviews, work, repairs, or a saved template revision to conceal a change.
8. **Release scope is explicit.** Plain assembly links do not implement child-spool acceptance. Numbered assembly travelers additionally verify their declared children and descendant component readiness at their gates. Final release is not shipment or delivery.

## Concurrency and history

Tracking mutations take the shared topology advisory lock before the owning `Item` row and related state locks. `flow.lock_topology` then calls `administration.refresh_session_authority`, refreshing the employee and stored session version against `s.info['authenticated_session']`. A queued writer whose role, active access or PIN was changed receives `401` before mutation. The refresh takes no Employee row lock, preserving the established Item-before-history/foreign-key lock order. Reload controlled records under their locks before checking versions; stale SQLAlchemy identity-map values must not bypass a conflict. Pure reads take neither advisory nor write locks and create no access-state rows.

Keep validation, inserts, invalidation, counter synchronization, and audit creation in one transaction. Read-snapshot helpers preload records for one spool calculation; they are not a durable cache and must not be reused after writes.

`init_db.py` initializes PostgreSQL under an advisory lock in one transaction. It creates missing tables and installs `BEFORE UPDATE OR DELETE` protection on nineteen history/file tables:

- `audit_events`
- `tracking_requirement_evidence`
- `tracking_requirement_reviews`
- `tracking_weld_work`
- `tracking_weld_repairs`
- `tracking_requirement_templates`
- `tracking_process_events`
- `flow_events`
- `spool_parts_events`
- `quality_documents`
- `quality_evidence`
- `quality_reviews`
- `quality_events`
- `dossier_documents`
- `dossier_files`
- `dossier_reviews`
- `dossier_issues`
- `dossier_handovers`
- `dossier_events`

These triggers prevent ordinary mutation, not deliberate removal by a database owner. Requirements, holds, plans, and weld metadata are current-state records and remain mutable through controlled APIs.

## Required component quantities per spool

See the separate handoff contract below when a quantity-tracked component changes custody. Allocation alone never supplies a badge scan, location change or work-status record.

The optional `parts.py` extension adds four tables: `spool_parts_plans`, `spool_part_lines`, `spool_part_allocations` and immutable `spool_parts_events`. A plan belongs to one existing individual spool plan; a Part allocation belongs to one active line, and its component ID is globally unique. `flow_component_links` remains the physical component-to-spool relationship. No existing columns are changed and no plan is created by a read.

| Route | Behavior |
| --- | --- |
| `GET /api/parts/spools?project_id=...` | Read planned spools and optional quantity totals. |
| `GET /api/parts/spools/{id}` | Read required lines, allocated component facts, candidates, blockers and history. |
| `PUT /api/parts/spools/{id}/plan` | Supervisor/admin replaces the current required list with expected version, source reference and reason. Version zero creates it; IDs preserve existing lines. |
| `POST /api/parts/spools/{id}/allocations` | Handler/supervisor/admin atomically assigns one or several existing `component_ids` to a `line_id`, with expected version, reference and notes. |
| `POST /api/parts/spools/{id}/allocations/{component_id}/remove` | Versioned unassignment removes the allocation and component link while preserving the item, traveler and audit history. |

Required quantities are strict positive integers representing physical pieces: up to 500 lines, 10,000 pieces per spool and 1,000 unique IDs in one allocation request. Nonempty line part numbers must match the actual recorded part number. Existing linked components remain unallocated until deliberately classified. A tracked legacy item whose kind is still `Part` is not an eligible preparation component.

Receipt counts actual current step-1 completion. Preparation requires current-pass steps 7 and 8, a completed component route and no current identity, hold, rework or exception blockers. Baselines never backfill missing events. Required quantities are the denominator; no zero-scope percentage implies completion. Assignment creates no receipt, work, timer or custody record.

Writes take the existing topology advisory lock before item locks, refresh the parts version and keep validation, component links, flow-version changes and audit records atomic. Scope edits reconcile `FlowPlan.expected_children`; old traveler start/scope/assignment endpoints cannot bypass a configured parts list. The scope locks after spool step 9, real weld work, release or applicable parent progression. Generic final release locks configured child components before testing current readiness.

Configured lists expose a compact `parts` summary in tracking, flow and progress. Dossier fingerprints include stable recorded plan/line/allocation facts and actual component identity; no permissions, candidates or elapsed clocks enter the fingerprint. The parts key is omitted entirely for an unconfigured spool, preserving legacy issue fingerprints. Frozen issues retain the original snapshot and printable evidence. Four raw Excel sheets and `Spool parts progress` share the existing read-only export snapshot.

## Badge handoff, location and work-status contract

`transfers.py` adds two current-state tables: `item_transfer_states` (one row per item after the first explicit update) and `transfer_locations` (managed custom choices). There is no existing-column migration and no initialization/read-time seeding. An item with no transfer-state row projects `version: 0`, `operational_status: null` and its actual existing custodian/location. Built-in location/status choices are code definitions. Immutable `Audit` and existing `FlowEvent` rows retain historical snapshots; earlier records are not backfilled with missing sender or status data.

| Method and route | Contract |
| --- | --- |
| `GET /api/transfers/options` | Authenticated location/status catalog with built-in/custom kind, active flag, version and `can_manage_locations`. Inactive custom records remain visible for management; destination selectors filter them. |
| `GET /api/transfers/items/{id}` | Read-only current custodian/name/active state, recorded location, operational status, transfer version, update metadata and role/release-derived `can_transfer`. |
| `POST /api/items/{id}/transfer` | An active employee in any supported position submits `sender_badge`, receiving `handler`, `location_id`, `operational_status`, strict integer `expected_transfer_version`, and optional notes/scan method. |
| `POST /api/transfers/locations` | Supervisor/admin creates a custom location with `label`; returns 201. |
| `PATCH /api/transfers/locations/{id}` | Supervisor/admin supplies `label`, `active` and current `expected_version`. Rename/deactivate/reactivate retains historical labels. There is no delete route. |

Item detail and flow detail embed the same snapshot as `transfer`. The `current` location ID retains the item's actual recorded label, including a legacy value or a now-deactivated custom location. Other IDs must select an active built-in/custom destination. Labels are normalized for duplicate detection; built-in names are reserved. Catalog edits do not rename current item locations or prior audit history.

Operational statuses are `queued`, `in_progress`, `awaiting_inspection`, `waiting_material`, `paused` and `ready_next_operation`. They cannot approve QA, release holds, complete physical work, advance a numbered step, change a process timer or issue/dispatch a packet. In particular, operational `paused` and the process clock's paused state have separate explicit actions.

Every transfer locks topology before the refreshed Item row, then validates transfer version, destination and both active employees. The sending badge must equal the locked current `Item.handler`; it need not equal the authenticated recorder. Both badge identities identify records, not login sessions or independent signatures. The audit retains sender, receiver, recorder, before/after location/status, change flags, timestamp, versions and `recipient_acknowledged: false`. Same-custodian updates are permitted when the location or status changes. A complete no-op ordinary transfer is rejected. Optimistic versions catch same-custodian races and A-to-B-to-A changes, not just a different handler.

Numbered handoff steps 6/8/9/12/13/16/20/23 share this validation and record within the same transaction as their checks and step/timer transition. They add `sender_badge`, `receiver_badge`, `location_id`, `operational_status` and `expected_transfer_version` to the ordinary flow form. Step 3 uses only `location_id` and transfer version for its location capture. Other steps reject supplied transfer fields. An ordinary handoff on a routed item appends `custody_transfer` and increments `FlowPlan.version` without changing its current step, status, entry time or process history. This invalidates stale traveler forms without claiming physical progress. Generic transfers remain prohibited after QA release; permitted numbered post-QA movements keep their existing controls.

`static/handoff.js` supplies shared badge confirmation/location/status controls and camera cleanup for both ordinary and flow forms. Displaying the current custodian never preconfirms a sender scan. Item changes, successful saves and stale-state recovery clear both badge confirmations. Existing item/badge QR labels remain valid, and badge-link continuation retains the explicitly selected role. Read-only projections take no write/advisory locks. The two raw transfer sheets share the existing read-only Excel snapshot.

## Administrator decisions and account access

All `/api/admin` routes require a current active administrator. The shared topology lock serializes writes, then the actor's role, active state and authenticated session version are rechecked before a decision is applied. Employee authority is refreshed without taking an Employee write lock ahead of Item locks; target-account edits take their own lock. This preserves the existing item-before-history lock order.

| Route | Request / response |
| --- | --- |
| `GET /api/admin/overview` | Application version, item/release/hold/account counts and administrative capabilities. |
| `GET /api/admin/items?search=&limit=&offset=` | Paginated item identity, current custody, release mode/label and flow position. |
| `GET /api/admin/items/{id}` | `{item, version, release, blockers, allowed_actions, history}`. `version` is an opaque 64-character SHA-256 decision token. |
| `POST /api/admin/items/{id}/release` | `{expected_version, reason, reference?}` explicitly releases an unreleased item despite its blockers. |
| `POST /api/admin/items/{id}/return-to-work` | Same decision fields; restores a current override's saved prior route or performs the guarded ordinary-QA reopen. |
| `POST /api/admin/items/{id}/custody` | Same decision fields plus `handler`, `location_id` and `operational_status`; records an administrative correction without claimed badge scans. |
| `GET /api/admin/employees` | `{employees, roles, active_admins, removed_count}`. Normal roster excludes removed accounts; `?include_removed=true` includes them. Rows include permanent badge, role/label, permissions, active flag, removal/restoration metadata, assigned-item count, integer version and allowed controls. |
| `PATCH /api/admin/employees/{badge}` | `{expected_version, name, role, active, reason}`. No badge replacement or arbitrary field edits. |
| `POST /api/admin/employees/{badge}/pin` | `{expected_version, pin, reason}`; resets the private PIN and revokes existing sessions. |
| `POST /api/admin/employees/{badge}/remove` | `{expected_version, reason}`; removes the account from normal rosters, sets inactive and revokes sessions while retaining the employee identity and history. |
| `POST /api/admin/employees/{badge}/restore` | `{expected_version, reason}`; returns a removed employee to the roster as inactive. Access requires a separate explicit account edit. |

Item actions return the refreshed admin detail. Employee actions return the updated employee snapshot plus `reauthenticate` when the caller changed their own access/PIN. Reasons are trimmed, 4–3,000 characters; optional references are at most 500. PINs retain their exact entered characters, require 8–128 characters and cannot be entirely whitespace. Unknown request fields and stale versions are rejected. PIN-bearing validation responses omit submitted values.

No item-override table is added. `release_summary(s,item)` derives current release provenance from the released flag and latest relevant immutable `Audit` event. It returns `mode` (`not_released`, `qa`, `admin_override`), `label`, `qa_released`, `active_override` and optional `override` with audit ID, actor, time, reason, reference, bypassed blockers and prior flow. Item, tracking, flow and packet views expose this as `release_control`; progress rows carry explicit release mode/label and an administrative-release flag. An active override never qualifies as current ordinary QA release or a QA-issued packet.

The decision token hashes the current item, flow, release blockers, transfer version and latest item audit ID. Writes recompute it under the topology/item/descendant locks. GET projections are pure and acquire no write/advisory locks. A duplicate release or a stale decision after an away-and-back change is rejected. Release uses `ADMIN_RELEASE_OVERRIDE`; return uses `ADMIN_RETURN_TO_WORK`; custody correction uses `ADMIN_CUSTODY_CORRECTION`. Historical events remain unchanged.

Administrative release sets Item release fields but preserves actual inspections, holds, weld work, requirements and exception records. A distinct `admin_release` FlowEvent moves a spool to step 16 or assembly to step 23; a component becomes `admin_released` with no completion timestamp. No skipped `advance` events are created. Process timing follows that explicit disposition. Returning an override restores its original position with a new visit where applicable. `admin_return_to_work` resets current completion projections from the return step, retaining all prior events. It does not claim physical rework. Actual shipped/delivered state cannot be undone by this action. Ordinary QA return keeps its existing parent/review rules; the legacy `/reopen` rejects active overrides with instructions to use Admin controls.

Custody corrections share selected-location validation and transfer versioning, but require no substitute sender badge and create no ordinary `TRANSFER` event. They explicitly set `badge_scans_recorded: false`. They remain available for released/blocked items and inactive previous custodians. An active receiving employee is required. Flow versions change to invalidate stale forms, while process steps/timing and QA remain unchanged.

The `employee_access_states` table stores `badge`, `version`, `session_version`, `updated_by`, `updated_at`. Absent rows mean versions zero; initialization and reads create none. A name edit increments the account revision. Role/active changes, PIN resets, removal and restoration also increment session version. JWT claim `sv` defaults to zero for compatible existing sessions; authentication compares it with current stored access. Login locks the employee while checking its PIN and issuing the current version, serializing against PIN reset. Last-active-admin protection runs under the topology lock so simultaneous demotions or removals cannot remove every administrator.

The additive `employee_removal_states` table retains current removal state and removal/restoration provenance, keyed to the permanent employee badge. No existing columns change and initialization creates no removal records. Removal leaves the Employee row and all business references intact. The default admin roster and `/api/employees` omit removed accounts; the active staff directory also excludes them because removal sets `active=false`. Removed accounts reject ordinary profile/PIN changes until explicitly restored. Restore leaves the account inactive and invalidates prior sessions again. Immutable `EMPLOYEE_REMOVED` / `EMPLOYEE_RESTORED` Audit events retain reasons, actor and snapshots. Assigned item custodians are not silently replaced, and original dossier fingerprints do not depend on removal metadata. Failed/stale/repeated decisions create no partial state.

Ordinary historical dossier fingerprints retain their original fields. Only an active administrator override adds its release basis; administrator metadata never enters physical construction fingerprints merely because a new software version was installed. Excel includes `Employee access states` and `Employee removal states`, retains all employee identities and immutable administrative audit events, and adds release-mode columns to `Part progress`; PINs, hashes and session tokens remain excluded.

## Production process timing

`SpoolProcessEvent` is additive and append-only. Its `(item_id, sequence)` pair is unique. `sequence` is also the spool's optimistic concurrency version, starting at zero before the first event. Every write takes the existing item row lock, re-reads the event history, checks the requested version and legal transition, and appends the event and audit record in one transaction. Only the server supplies timestamps and actors. Extra fields, unknown stages, backdating, stale versions and invalid transitions are rejected. A server clock earlier than the last event is rejected for writes; read projections clamp to recorded time.

POST bodies contain `action`, `expected_version`, optional `notes`, and—for start/move only—`process_key` plus `process_name` when the key is `custom`. A pause requires a reason. Start needs no open visit. Move closes the current visit and starts a different process at the same timestamp; it also works while paused. Resume needs a paused visit. Finish closes a visit without starting another. A custom process name is trimmed, whitespace-normalized and grouped without case sensitivity. The ten catalog keys remain stable even if labels are changed in a later release.

The pure `summarize_process_events` projection returns `item_id`, `version`, UTC `as_of`, `status`, `current`, `totals`, `by_process`, `visits` and `events`. Status is `not_started`, `running`, `paused` or `finished`; a closed visit has status `finished`. Numeric `elapsed_seconds = active_seconds + paused_seconds`. Durations use integer microseconds internally. Visit IDs are the sequence numbers of start/move events. Events and visits are oldest first. The spool detail embeds this full object as `production_process`; overview summaries include its current state and overall totals.

Timing starts only from explicit events. It measures calendar station/process duration, includes overnight time, and is not person-hours. Unstarted time and gaps after Finish are excluded. Manual timing does not modify weld work, requirements, custody, inspections or quality holds. `finish_on_release` closes an open visit inside the locked final-release transaction. For manually timed records, administrative reopen leaves timing stopped until a new Start. Numbered travelers own their stage transitions through `sync_flow_process`, including post-QA handoffs and a return to QA on a permitted reopen of an ordinary QA release. Returning an administrative override restores its saved prior route position instead.

The Excel allowlist includes the raw process-event table. Two additional reports, `Process visits` and `Process totals`, derive from those events on the same read-only snapshot connection, one spool at a time. They include current project/subproject identifiers, numeric seconds and decimal hours, and an `as_of` timestamp for open visits. Historical events do not freeze earlier project assignments. Report rows use temporary spooled files and the existing sheet-continuation rules; no new runtime package is required.

## Numbered CLM process flow

`flow.py` transcribes the supplied chart into `STEPS` / `STEP_BY_NUMBER`, version `CLM-24-v2`. QA titles are 2=`QA-001-Check Dimensions`, 11=`QA-002-Check Dimensions`, 15=`QA-003-Inspect Welds`, 19=`QA-004-Assembly Inspection`, and 22=`QA-005-Final Inspection`. Step IDs, check IDs and role mappings stay fixed; prior immutable event titles/definitions remain unchanged. Routes retain the original numbering: component 1–8, spool 9–16, assembly 17–24. The catalog supplies role lists from `permissions.flow_step_roles`, checklist identifiers/text, scan/location/handoff/reference requirements and allowed rework destinations. Frontend forms consume those definitions and the authenticated `allowed_actions` response. Keep role enforcement and release gates on the server; the separate job-policy version comes from `/api/permissions`.

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

`shipped` requires the current step 24, item verification, checklist, carrier, shipment reference and destination; it stores `shipped_at`. Only a later delivery action sets `delivered_at`, `receipt_reference`, `recipient` and status `delivered`. Document references do not imply generated/archived PDFs or carrier-system integration. A recorded handoff identifies the scanned sender and receiver separately from the signed-in recorder. It does not fabricate either employee's independent acknowledgment.

Excel exports explicitly allowlist all four flow tables, plus a `Flow steps` definition sheet. Flow event JSON retains its captured checklist definition. The process reports join a component through `ComponentLink` to its parent's current project/subproject; unassigned component report project IDs are blank and the original free-text Item project remains in the Items sheet. Definition/report rows are distinguished from raw database records in Export info.

## Audit-readiness extension

The quality extension adds seven tables: `quality_workspaces`, `quality_requirements`, `quality_documents`, `quality_evidence`, `quality_actions`, `quality_reviews` and `quality_events`. The protected immutable tables are **documents, evidence, reviews and events**; actions remain editable through controlled APIs until closure. Workspace creation is explicit and may copy draft `CLM-KELVION-AUDIT-2026-10-29-v1` prompts; initialization and GET requests never seed actual activities or accepted records.

The prompts preserve the known audit item groupings and priority items from CLM's supplied summary. Additional K-01–K-07 labels identify local preparation prompts, not customer clause numbers. Source document names/revisions are provisional references; source confirmation requires the actual clause, revision, reference and resolved project applicability. No technical percentage, pressure, coating system, retention period or customer deadline is activated by the template.

See [QUALITY_API.md](QUALITY_API.md) for full payloads. Every quality mutation after workspace creation requires the current **workspace** `expected_version`, not the requirement's independent version. Writes acquire the shared flow topology advisory lock, then the workspace row lock; the workspace event sequence equals the resulting version. All signed actors and recording timestamps come from the authenticated session/server. Request bodies forbid extra fields.

Quality source, evidence, requirement and action decisions are separate immutable reviews. Current status is projected from data and the latest relevant review fingerprint. Source fingerprints include source text, revision, section, reference, applicability and the workspace customer/project/PO. Requirement fingerprints include the current linked revisions, related training, actual evidence/reviews and action state. Changing an unrelated requirement does not invalidate another requirement's verification.

Document approvals refer to immutable exact revision entries. Later effective approved revisions supersede older revisions; rejecting/superseding a newer revision must not silently resurrect an old approved revision. Training references an exact document ID or an actual issued alert. Document approval and alert acceptance are dependencies of relevant evidence, including documents referenced only indirectly through the evidence. Dependency changes stale acceptance without modifying the original record or review. Actual inspection/effectiveness evidence with fail/recorded results cannot be accepted as satisfactory evidence.

Physical evidence stores a snapshot of relevant item/weld state. It includes project membership, material-component parent assignment where applicable, drawing revision, physical work/inspection timestamps, reinspection/hold state, open rework/holds and current weld requirement cycle/version/status. Routine custody/location and process-timer changes are excluded. Component project membership resolves through `ComponentLink` to its parent's `SpoolPlan`; legacy free-text `Item.project` is not a project key. A changed physical basis requires a new current evidence record and review.

Signed review and real production gate validation lock the relevant physical Item rows after the topology lock because some existing tracking writes serialize on those Item rows. **Read-only views never acquire these locks.** `production_gate_errors(..., for_update=False)` defaults to a read projection; only `flow.advance` calls `_step_errors(..., quality_for_update=True)` while the topology and traveler locks are already held. Keep this separation to avoid a GET holding a workspace lock while waiting on a traveler held by a writer.

Verification blocks on an unconfirmed source, unresolved conditional applicability, draft response, nonempty remaining gap, missing required accepted evidence, a newer required record that remains submitted/rejected, unapproved/superseded/not-yet-effective linked documents, missing training, open actions or stale closure evidence. Items 3–6 and 8 additionally require an approved linked document. NA requires a reviewed rationale and source confirmation; it cannot hide open actions. Closing an action requires implementation details, accepted implementation and passing effectiveness evidence, valid chronology, and accepted customer disposition when configured. A closed action must be explicitly reopened before edits.

Optional project-level gates default to `none`. Enabling/changing/removing them requires an inspector or administrator, and the workspace must have a real project ID. `pre_coating` is checked at flow steps 20 and 21; `shipment` at steps 23 and 24. Every bound requirement must currently be verified or reviewed NA. Gate failure leaves traveler/timing/history unchanged. The gates do not compute per-spool inspection coverage, NDE sample selection, technical acceptance limits or automatic customer approval. Existing per-item welding/inspection/hold requirements continue to apply.

The full Excel workbook contains seven raw quality sheets and a calculated **Audit readiness** report in the same PostgreSQL `REPEATABLE READ READ ONLY` transaction as all other exports. The report calls the grouped `workspace_detail(..., as_of=created_at)` projection through an ORM session bound to the existing connection, with no commit or autoflush. It processes one workspace at a time, spools report rows, and uses the same row-continuation and long-text overflow rules. The report includes the five prompts, status, blockers, source fields, actual record references, action owners/dates and snapshot timestamp. Raw rows do not contain derived acceptance flags; consumers must use the projected report or the documented review logic.


## P.O. spool QR generation and permanent readable identities

`order_spools` fixes each generated physical spool to its exact assembly and saved spool requirement. `spool_qr_identities` adds one immutable alias per physical item without replacing `Item.id`. The alias stores the original spool number, normalized number, positive sequence, display/normalized code, actor, source and creation time. Unique constraints protect the item, complete code, and normalized-number/sequence pair. Sequences are global across purchase orders and include removed identities; they are never based on a current list rank.

`ensure_spool_qr_identity` allocates within the caller's transaction under the shared topology lock. Creation, bulk import, order-label generation and legacy non-Assembly weld-plan enrollment call it. A blank spool number creates no invented alias; assigning its first actual number allocates one. `guard_spool_qr_number` prevents later changes to the normalized number. Case/spacing-equivalent edits retain the same code.

`GET /api/order-labels/{project_id}` and `/labels` use the existing repeatable-read, read-only snapshot. They accept an optional `gpn_id` and `kind=Spool`; assemblies have no printable QR labels. Pages contain at most 100 physical spools. Each row exposes `qr_alias`, `display_code` and an encoded HTTPS `/?spool=ALIAS` link when an alias exists. `GET /api/spool-qr/resolve?code=...` requires authentication and resolves only the complete stored alias to the original `item_id`. Legacy `/?item=ID` links and internal-ID API writes remain valid. Alias decoration is excluded from signed material and receiving bases.

`POST /api/order-labels/{project_id}/generate` requires administrator/supervisor authority, the current order version, actual location and an active handler. Under topology/PO locks it validates the entire selected scope, then creates at most 500 missing items including parent assemblies. Only children already linked to the exact assembly reduce its deficit. Existing/removed IDs are retained, and a complete current scope is a no-op. Declared weld counts initialize pending numbered joints; valid inherited uploaded BOMs initialize blank material-piece records. No physical work, heat/MTR facts or QA decisions are inferred.

Label cards and print sheets use the saved readable alias. The technical internal ID remains available on demand. Async scan resolution preserves per-screen stale-response guards before opening or mutating a record; badge scans stay separate. Read calls never allocate aliases. Printing refreshes its selected page and waits for every QR image; missing images prevent printing. Both HTML shells stay identical.

Verification uses `pytest tests/test_spool_qr_identities.py tests/test_order_labels.py tests/test_order_spool_labels.py`, the isolated `tests/order_labels_browser_smoke.cjs`, and `tests/verify_order_labels_postgres.py --dsn LOCAL_TEST_DSN`. The PostgreSQL verifier exercises same-order and different-order allocation races, globally unique numbers, immutable aliases, current-version no-ops, read-only views and queued authority changes. Its local-database guard and disposable schema must remain intact.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
node tests/tracking_ui_smoke.cjs
node tests/export_ui_smoke.cjs
node tests/process_ui_smoke.cjs
node tests/flow_ui_smoke.cjs
node tests/quality_ui_smoke.cjs
node tests/progress_ui_smoke.cjs
node tests/dossier_ui_smoke.cjs
node tests/guide_ui_smoke.cjs
node tests/parts_ui_smoke.cjs
node tests/handoff_ui_smoke.cjs
node tests/admin_ui_smoke.cjs
node tests/order_setup_ui_smoke.cjs
```

API fixtures use temporary SQLite databases, override imported database settings, and create synthetic employees and authenticated sessions. They cover legacy behavior, roles, stale decisions, evidence, scope, operations, repairs, holds, hierarchy, and release. SQLite tests do not establish PostgreSQL locking or trigger behavior.

The Node harness runs without a framework or network. It checks route/render contracts, role controls, sequencing, escaped evidence, safe links, versions, and failed-write recovery. It is not a full browser layout/accessibility test. `tests/order_setup_browser_smoke.cjs` uses the existing isolated `orders_browser_server.py` fixture to verify the real three-step save, quantity calculations, desktop/mobile layout, stale edits, legacy scope and read-only roles; it rejects remote hosts. See `tests/orders_browser_README.md` for browser environment setup.

For PostgreSQL behavior, provision a separate local test database with a name beginning `fabtrace_test_`, then inspect the guard and options:

```bash
python tests/verify_postgres.py --help
python tests/verify_postgres.py --dsn 'postgresql+psycopg://USER@localhost/fabtrace_test_upgrade'
```

Replace `USER` with the local test user and supply the local connection settings. The script requires an explicit local loopback or Unix-socket DSN, rejects remote/service overrides and operational database names, and does not inherit a production `DATABASE_URL`. Each run creates a UUID-named schema and removes that schema afterward. It verifies legacy-row preservation, repeated initialization, all nineteen history/file triggers, competing weld-evidence/process/flow/quality/dossier/parts/transfer writes, lock-free GET projections, and the read-only Excel snapshot. Do not loosen its guard to use the operational database.

## Adding the next feature

Choose the record's scope first: project, spool, weld, or a new cross-spool package. Extend validated server models and release rules before adding controls. Add regression coverage for the changed acceptance/invalidation rule and retain legacy-item behavior. Keep ordinary scans and form entry short.

Future schema changes require versioned migrations. `Base.metadata.create_all()` creates absent tables; it does not alter existing columns, constraints, or indexes. Do not change a model and assume deployment will migrate existing data. Plan an explicit migration, ordering, representative-data verification, and rollback implications. Preserve history.

Features that need deliberate additional models:

- **Report uploads:** file storage, authorization, retention, and links to immutable evidence. Current evidence stores references/URLs only.
- **Automatic qualification applicability:** structured ranges, continuity, governing rules, and revisions. Current acceptance is an inspector's evidence-backed review.
- **NDE sampling, pressure-test packages, cross-spool field tie-ins, carrier/document integrations and richer field-return workflows:** each needs explicit scope and lifecycle rules. Basic child assembly readiness and shipment/delivery confirmation are already implemented in the numbered traveler.

Project-specific NDE, PMI, PWHT, hardness, and other requirements can already be configured. Approved project documents supply their technical criteria and extent; this release infers no universal code rule or NDE percentage.


## Job Packet model and release controls

`dossier.py` adds `dossier_projects`, `dossier_entries`, `dossier_documents`, `dossier_files`, `dossier_reviews`, `dossier_issues`, `dossier_handovers` and `dossier_events`. Project configuration and saved checklist entries are mutable current state; the other six tables are protected history. File content and issue snapshots/print content are deferred ORM columns so normal metadata reads do not load binary documents or large retained packets. See [DOSSIER_API.md](DOSSIER_API.md) for exact payloads and permission rules.

Every write takes the shared flow topology lock, then the project configuration row lock and relevant sorted Item locks, and checks the project `expected_version`. The event sequence equals the new configuration version. GET projections, previews, immutable downloads and exports acquire no write locks and append no history. Never silently enroll a project, seed signed evidence or backfill an unrecorded production step.

Checklist fingerprints use the relevant record basis, exact selected document revisions and actual project/PO applicability. Structural work in an assembly includes its child scope and relevant physical changes. Pressure approval must become stale after a repair, but normal coating completion or shipping custody alone must not make a pre-coating pressure approval stale. A full packet also depends on current physical release, relevant requirements and current child packets. Issued data and print content remain fixed; later currentness is derived separately.

When a project explicitly enables its dossier gate, `flow._step_errors` calls `dossier_gate_errors` at 20/21 for pre-coating pressure/customer hold/source checks and at 23/24 for current complete issued packets. Actual advance passes `for_update=True` inside the existing locked transaction; board/detail reads leave it false. Pre-coating must not require final coating or final physical release, which would create a circular workflow. Existing tracking, flow and audit gates continue to apply.

Uploads read at most 8 MiB + 1 byte, check extension/content signature, sanitize filenames, retain SHA-256 and cap project file revisions at 256 MiB. Office ZIPs reject unsafe/encrypted/macro content or excessive declared expansion. Files are downloaded as attachments with no-sniff headers and are never executed or rendered in application HTML. Exact issued ZIPs contain selected original documents; linked external references are never fetched.

Handover records are declarations of actual dispatch and separate receipt, not integrations that send messages. A dispatch must reference a current completed-project issue. A later receipt can acknowledge an older dispatched issue and does not grant new release. Printed acknowledgement blanks remain blank until an actual event.

Excel explicitly allowlists seven dossier metadata tables, including immutable JSON issue/review snapshots and print hashes. It excludes `dossier_files` and retained HTML content. `Project progress`, `Part progress` and `Job Packet readiness` are calculated inside the same PostgreSQL REPEATABLE READ READ ONLY snapshot as the raw tables. Long snapshots use the existing lossless Text overflow mechanism; continuation/overflow worksheets can extend the current base workbook of 43 raw sheets, eight report/definition sheets and Export info.

## Read-only project progress

`GET /api/progress/projects` returns `{as_of,definitions,projects}`. Project rows contain actual registered counts, WIP/current-finished/shipped/delivered/blocked counts, finished percentage, recorded step totals and percentage, planning-needed count, and whether dossier configuration exists.

`GET /api/progress/projects/{project_id}` accepts `status=all|wip|finished|shipped|delivered`, `subproject_id`, `kind=all|component|spool|assembly|unplanned`, `search` and `sort=status|progress_asc|progress_desc|id`. It returns `{project,as_of,definitions,counts,subprojects,items,total}`. `counts` is full project scope; `items` and `total` follow the filters. Finished includes current finished items whose traveler subsequently shipped/delivered.

`project_rows(session, project_id=None)` is the shared no-write helper used by the dashboard, completed-project eligibility and Excel. Membership precedence is SpoolPlan, linked component's parent plan, then exact Item.project project ID. Never fuzzy-match a project label or invent BOM entries. Components, spools and assemblies count as separate physical records.

A row records `id`, `kind`, scope/source IDs, `status`, `fabrication_finished`, `blockers`, `progress_percent`, `progress_basis`, actual step counters, planned/completed/accepted weld counters, current route step and custody details. Recorded-route percentages replay successful advances and controlled failure/reopen returns. Earlier baseline steps remain `not_recorded`. Unrouted planned welds use actual current-cycle completion; a zero-weld plan uses current QA release. The percentage alone never issues a packet or creates shipment evidence.


## In-app guide and project setup

`static/guide.js` renders authenticated operating instructions and a read-only project setup checklist. It reuses the progress and dossier GET endpoints; it adds no database tables, accepted statuses, background writes or approval rules. Zero registered plans cannot imply completed scope, an uploaded file cannot imply acceptance, and an older transfer cannot imply completion of a newer or stale project issue. The existing server projections remain authoritative.

Project-planning shortcuts pass explicit project/subproject scope and `resetFilters:true` to `FabTracking.open`. This clears old search/status/process filters only when requested by those shortcuts; ordinary tracking navigation preserves existing behavior. Dossier tab links retain a whitelisted `tab` query parameter across reload/login. Main-shell startup routing and cancellation include the guide workspace, while `index.html` remains identical to `static/index.html`.

Static instructions remain readable when an API read fails; the setup state must show the error rather than present stale or invented completion. Dynamic identifiers, descriptions and API messages are escaped. Read-only item shortcuts call `openItem(id)` rather than the QR landing route, which deliberately records a scan. The guide's print output is operating guidance, not an issued customer Job Packet.

## Spool BOM and isometric uploads — 2026.10.31-spool-documents.1

`spool_documents.py` adds `spool_document_sets`, `spool_documents`, and `spool_document_files`. A set belongs to exactly one requirement or physical spool. Its `scope_snapshot` binds the original physical identity; changing a documented spool number, P.O., or parent assembly is blocked. Document metadata and bytes are immutable PostgreSQL history; only the set's concurrency version changes. The migration creates these absent tables and history triggers, with no alterations to existing rows or columns.

`GET /api/spool-documents/{requirements|spools}/{id}` returns the exact scope, version, active documents, permissions and history. `POST .../preview` parses multipart `kind`, `files`, and optional `sheet` without writing. `POST .../upload` requires the preview's `selection_sha256` as `expected_sha256`, the current set `expected_version`, optional `revision`, and `reason`. Parsing happens before the topology lock; scope, authority, release status, identity and version are rechecked after it. `GET /api/spool-documents/files/{document_id}` requires sign-in; PDFs display inline and `?download=1` downloads them. Tabular BOM bytes remain exact. Scanned/PDF content is normalized into a complete PDF with active actions removed and source file hashes retained.

BOM headers are `spool_number,item,quantity,unit,part_number,description,size,material,length,notes,drawing,revision,source_page`. Quantity and description are required; optional explicit spool and assembly fields must match the selected scope. Multiworksheet workbooks require a sheet choice. Whole or decimal source quantities are reference values and do not create or replace inventory allocation lines. Saved heat/MTR, weld, receipt and QA records remain separate.

`spool_document_scope_basis` supplies effective exact document IDs and hashes to quality and Job Packet fingerprints. New uploads can stale affected reviews but never rewrite them. Issued snapshots include the associated metadata; ZIP downloads use `spool_document_retained_file` with the frozen ID and verify content hashes. Newer uploads do not replace old issued attachments. Excel adds `Spool document scopes` and `Spool uploaded documents` metadata sheets while excluding binary bytes.

The UI saves the order once before showing the optional fourth document step. Upload failures retain the saved order and can be retried without resubmitting setup. Existing spool heat/MTR UI remains available beside the new BOM/drawing actions. Local browser coverage exercises complete PDF page retention, scan ordering, setup inheritance, individual overrides, read-only positions, and mobile layout.

## Spool PDF viewing correction — 2026.10.31-spool-pdf-viewer.1

Uploaded PDFs previously received `Content-Security-Policy: sandbox; default-src 'none'; frame-ancestors 'self'`. Those document restrictions can block the browser's PDF viewer, leaving a gray page despite a valid, authenticated PDF response. PDF responses now retain `frame-ancestors 'self'` without the viewer-blocking sandbox and default source restrictions. Other download formats retain the existing restrictive policy.

WebKit documents this native-plugin interaction in [its PDF sandbox correction](https://github.com/WebKit/WebKit/commit/cf8519d4c46735412bfd7e9b52b8208810c6d3be): the exception for full-page PDFs does not apply to embedded PDFs. Chromium's native PDF behavior differs, so a successful Chrome file fetch alone cannot rule out this Safari failure.

This is a response-only change for current and historical PDF BOMs and isometrics. Authentication, active-scope checks, SHA-256 and size verification, PDF action sanitization, same-origin frame protection, download behavior and immutable stored bytes remain in place. Existing documents need no migration or re-upload. Browser verification must use visible PDF content and confirm rendered pages; an HTTP 200, PDF signature, page count, or iframe element alone does not verify the viewer.

`tests/pdf_viewer_browser_smoke.cjs` uses the isolated `tests/orders_browser_server.py` fixture and full Chromium (set `PDF_VIEWER_BROWSER_PATH` to the full browser binary, not the headless shell). It uploads a visible two-page PDF through both BOM and isometric routes, checks authenticated access and the response policy, and verifies first- and second-page pixels in both the dialog and the new-tab viewer. Set `PYTHON` to a Python interpreter with Pillow for screenshot inspection. The release passed all four rendering cases without JavaScript or console errors, plus 44 document API checks.

## Isometric extraction and individual Excel BOMs — 2026.10.31-isometric-boms.1

The isometric upload preview now identifies the spool label and material grid in each sheet's lower-right area. It retains the complete PDF, excludes assembly-only hardware from spool candidates, and creates a separate reviewed Excel BOM for each selected spool. The default assembly-setup selection contains only exact spool-number matches within that P.O. and GPN. Physical copies inherit their exact requirement's documents; individual document revisions remain effective. A physical-spool review offers **Use for all assembly spools**, carrying the selected files or saved drawing and reviewed material corrections into the assembly-setup review.

| Endpoint | Contract |
| --- | --- |
| `POST /api/spool-documents/{scope}/{identity}/isometric-preview` | Multipart `files` or one saved `document_id`. Returns the complete source, detected candidates, eligible targets and a signed 30-minute review token; writes no records. |
| `POST /api/spool-documents/{scope}/{identity}/isometric-import` | Multipart `review` JSON plus the original files for a new upload. Review contains the token, `reviewed: true`, revision, reason and selected candidate-to-target mappings with target versions and corrected material rows. |
| `GET /api/spool-documents/files/{document_id}/bom.xlsx` | Authenticated unique-spool workbook. Generated BOMs return their immutable original XLSX bytes; an existing tabular BOM can be exported without a database mutation. |

The token binds the original extraction, source hash, actor, exact P.O./assembly scope and target identities. Save does not repeat OCR or trust editable cells for source attribution. Under the topology lock it rechecks authority, scope, release status and every target version; one conflict rolls back the whole package. Missing item numbers, descriptions or positive quantities and duplicate item numbers or target assignments block save. Preserve original source strings, identifiers and fractions alongside reviewed corrections. Quantities describe one spool and are never multiplied by assembly quantities.

`spool_document_file_links` is the only new table. Its immutable `document_id` to `source_document_id` link lets many spool revisions retain one verified complete PDF byte owner. Both current viewing and historical Job Packet downloads resolve and verify those bytes, even if the original owner's operational scope is later removed. Initialization adds the table and its immutable-history trigger without backfilling documents or rewriting existing data. Administrator Excel exports include the link metadata.

Native extraction uses `pdfplumber`; scanned pages use bundled RapidOCR/ONNX models locally. No external OCR upload is performed. Heavy OCR libraries load only in a disposable worker. Limits include 50 automatic-extraction pages, 500 material lines per spool, eight OCR pages, 20 seconds per OCR page and 50 seconds per review. One worker runs at a time, with network access disabled, temporary-file cleanup, and a memory watchdog reserving headroom on a 512 MiB host. Insufficient memory or unreadable pages produce review warnings rather than fabricated values. OCR mixed fractions remain raw and receive explicit warnings when their spacing is uncertain.

The existing 42 MiB request-body guard covers both new multipart routes. Review tokens are limited to 400 KiB and review JSON to 900 KiB, below the multipart parser's 1 MiB non-file-part limit. Preview estimates the full review payload and rejects an oversized drawing set with instructions to split it. It never returns a default review that cannot pass the save parser.

Each workbook has an import-compatible **BOM** table and a **Source and review** sheet. Item/part numbers and formula-like source strings are literal text; quantities are numeric. Source identity, pages, revision, review actor, warnings and corrections remain traceable. PDF response headers retain the preceding native-viewer correction.

Release verification covered 90 document/package/extraction/packet tests and 37 export/request-limit tests. Native extraction was checked against all four spool tables in the actual 777 and 712-A drawings; image-only versions verified OCR without a hidden text layer. The new package browser runner covers distinct Excel contents, retained full drawing pages, reviewed edits, exact scope, history, overrides and the share-all switch on desktop and mobile. Existing upload and visible two-page PDF browser regressions also passed.

## Simplified navigation and automatic uploads — 2026.10.31-simple-uploads.1

The ordinary signed-in landing is **Orders** for all supported positions; existing permissions still control creation and edits. The primary menu has Orders, Production progress, Scan & transfer, Process flow and Guide. A collapsed **More tools** menu retains specialist, administrative and export actions under their existing IDs and role gates. Contextual spool links still open their actual weld/material/quality records. No feature records or quality controls are removed.

`FabNavigation` observes the existing `show()` and `history.replaceState()` routes and maintains a bounded in-memory app route stack. Back restores known same-app screens, selected P.O./assembly/spool context, tabs, filters and scroll position. Deep links have semantic parent routes and never call browser `history.back()` to leave the application. Audit readiness now includes its nondefault tab in the URL. Passwords and file-input values are excluded from generic field snapshots. The order and document modules retain their own opaque drafts and selected File objects only in the current page's memory; this is not persistent draft storage. A pending save blocks navigation until its result is handled.

`FabOrderSetup.navigationState()`, `restoreNavigation()`, `back()` and `canNavigateAway()` preserve the setup wizard. Back moves through previous steps, pauses the first step with a Resume setup action, and returns from the optional file step to the saved order. Read-only order views fetch fresh data when restored. Each assembly has one **Upload drawing or BOM** entry and each spool has one **BOM & drawings** entry. `requirements_by_gpn` adds a lightweight `documents: {bom, isometric}` presence projection using only document kinds under the exact requirement IDs, never file bytes or historical material JSON. File-ready status therefore survives reloads.

PDF and image selections use the same automatic analysis from either document entry path. CSV/XLSX selections keep the existing validated BOM importer. The review preserves the complete source, supports ordered scan pages and generates distinct Excel lists. Saved BOM/drawing/history views remain available, with Back inside the document flow and a return-to-spool action.

The isometric preview accepts `source_mode` of `auto` (default), `bom` or `isometric`. Auto classification requires positive layout/table evidence; unknown files ask for an explicit document choice. The signed source binds `classification`, `classification_reason`, `document_kind` and `source_mode`. Native extraction and bounded OCR can read a standalone BOM grid across the page as well as the lower-right grid on a full isometric. An unlabeled standalone table remains unassigned when several destination spools exist. A single-target/physical context can be selected with a review warning; source identity and quantities are never fabricated.

A BOM-only source is retained as a viewable BOM PDF revision followed by the generated Excel BOM. It does not write an isometric revision. Generated BOM metadata exposes an authenticated `source_view_url`, and package results include `saved_kinds` so the UI reports only document types actually saved. The source PDF remains available from the BOM view and History. Full isometrics retain the preceding shared-drawing behavior. No table or column migration is added in this release; normalization, immutable file history, exact scope, release/version guards, OCR limits and the PDF-viewer policy remain in force.

Automatic drawing classification also requires positive drawing geometry outside the material table. A lower-right BOM on an otherwise blank template stays a BOM source; a drawing/title page followed by a separate BOM page can establish a complete drawing package. The native parser keeps its focused raster-area check for hybrid CAD PDFs before attempting bounded whole-page OCR.

Image-to-PDF encoding runs in a short-lived local Pillow worker before the existing parent PDF sanitization and source-signing path. It shares the OCR process semaphore and host file lock, so an encoder and OCR worker cannot run concurrently. Input is limited to 20 MiB, images to 20 megapixels, output to 40 MiB, and encoding to 20 seconds. Private temporary files and child processes are cleaned up on success, timeout, memory rejection and errors. The worker loads no OCR models. This boundary releases native pixel arenas after every image instead of retaining fragmented memory in long-lived web request threads.

Inside the encoder, normalization applies EXIF rotation in place and reuses already-RGB buffers. Opened image cores and separate conversion buffers are explicitly closed even when PDF encoding fails. JPEG quality 95 with chroma subsampling disabled retains thin quantity marks when scans become PDFs. The OCR worker supplies local ONNX sessions using `ORT_ENABLE_EXTENDED` through RapidOCR's supplied-session interface and pinned-version lazy model-load hooks. It retains the existing detector resolution, models, single-thread settings, CPU-arena setting, page/time bounds, offline execution and dynamic RSS watchdog. The measured admission floor is 288 MiB; the service ceiling remains 512 MiB, with 64 MiB reserved and the worker capped at 350 MiB. No allocator-trimming or garbage-collection override is used.

The authenticated Uvicorn regression sequence covers a first image, appending and reordering a second page, a shared drawing/BOM save, Excel and PDF downloads, three standalone BOM-photo revisions, then two more complete two-page previews. All passed with the configured runtime budgets. The parent stabilized at approximately 136.6 MiB; the observed child high-water mark was approximately 276.5 MiB, with the parent plus that mark and the 64 MiB reserve below 478 MiB. Repeated authenticated uploads are required verification for this path; a successful fresh-process OCR probe alone is insufficient.

The loopback browser fixture imports synthetic identities from `tests/fixture_accounts.py`. It deliberately avoids importing pytest/TestClient into the Uvicorn app process so test-runner overhead cannot distort the production OCR memory gate. No memory limits are bypassed by the browser tests.

Release verification passed 124 document, extraction, image-worker, import and retained-packet tests, plus 56 order setup/integration/weld tests. The normalized-source running total is capped before adding more pages to the PDF writer, with the final 40 MiB serialized-output check retained. Image cases cover RGB, RGBA, grayscale, camera EXIF rotation and encoder failures. The actual 777 and 712-A native tables retain their 2, 2, 15 and 13 material rows; measured OCR model optimization preserved all 32 real rows.

Browser verification passed seven navigation groups, ten order-setup checks, six automatic image-upload groups, five drawing-package groups, six existing-document groups and four native PDF rendering cases, with no JavaScript errors. The automatic-upload runner uses real OCR, checks appended/reordered images and retained edits through Back, saves separate spool workbooks with the full shared drawing, then uploads a standalone BOM image after the Excel download. It verifies the original isometric ID and other spool BOM remain unchanged, the source PDF is viewable, only BOM status events are emitted, and an unlabeled table remains unassigned across multiple eligible spools. Desktop and 390-pixel phone screenshots were reviewed. Existing guide and setup UI contracts, syntax checks and synchronized/versioned shell assets also passed.


## Physical spool arrival QA/QC — 2026.10.31-spool-arrival.1

`spool_receiving.py` adds three tables: `spool_arrival_inspections`, `spool_mtr_documents` and `spool_mtr_files`. All are append-only PostgreSQL history protected by the initializer's immutable UPDATE/DELETE trigger. No existing columns are changed, and no legacy acceptance or arrival timestamps are backfilled. `/healthz` checks each table. Administrator Excel export includes inspection evidence and MTR metadata but excludes binary files; derived part progress includes the current arrival status and inspector.

A physical spool is a Spool item or a non-Assembly legacy item with a spool plan/registration. Its own effective uploaded BOM takes precedence; otherwise it inherits only the exact registered order requirement. Catalog 777 registers remain valid until an effective source changes. Generalized whole-piece definitions use bounded, collision-resistant piece keys. Non-piece, fractional or oversized quantities remain viewable but cannot silently produce physical material rows. A saved trace pins the full definition. Explicit adoption retains the previous definition and complete material register in an immutable event, replaces current material entries with blank new-source rows and requires fresh QA acceptance.

Arrival decisions require the current inspection version and a SHA-256 basis over physical identity, effective source documents, pinned BOM/material rows and current MTR versions. QA capability, active topology and released-scope locks apply. Pass requires all five explicit checks, a current structured BOM, and heat/MTR references on every piece. Fail can record missing evidence. Each decision retains its full evidence basis, actor, time, reference and notes. Material, source and MTR changes make earlier acceptance stale; affected active timers pause. Prior timestamps and work are not rewritten.

The existing controlled assembly collection can attach an originally unparented, released spool to its first assembly in the same project while retaining its original receipt context. This requires the single immutable `assembly_link` event with preserved quality release and excludes registered order spools. Declared-parent changes, ordinary plan reassignment and cross-project moves remain blocked; original source and inspection snapshots are never rewritten.

The shared arrival guard covers all physical-spool weld operations including fit-up, aggregate welding, traveler starts/advances and late baselines, standalone timer start/move/resume, rework completion, ordinary/admin release, child readiness and downstream assembly scope. Planning, registration, QR viewing and corrections remain available. Corrective route transitions do not silently open timers while arrival is blocked. A new Pass can enable the normal Resume control at the current step; no intervening production time is inferred.

MTR upload uses the existing bounded PDF/image normalization and isolated image worker. The 42 MiB pre-parser body guard covers both `/mtr-preview` and `/mtr-documents`. Each exact physical spool/reference series uses a preview selection hash and optimistic version. The authenticated PDF route retains the same-origin viewing policy that fixed the earlier gray viewer page. MTR contents are deferred binary fields with size/hash verification on download. Issued Job Packets capture immutable MTR IDs/hashes and resolve the retained bytes when downloading an older issue.

Saved order requirements expose `weld_progress`: declared quantity includes unregistered physical copies, and only complete current-cycle individual work counts. Exact registration, order, assembly and normalized spool identity must agree. Missing plans or individual weld counts produce a scope warning with no percentage. Explicit zero and undeclared counts remain distinct. The projection streams operation rows without loading source files or changing records.

The focused local PostgreSQL verifier is `tests/verify_spool_receiving_postgres.py --dsn <local fabtrace_test_* DSN>`. It permits only an explicit loopback host or local Unix socket, uses a generated disposable schema and cleans it in finally. PostgreSQL 16.15 verification passed additive/idempotent initialization, unchanged old columns/legacy records, immutable evidence triggers, same-version concurrent inspection rejection (201/409), a material edit committing ahead of a queued stale QA approval (200/409), independent same-number spools and retained earlier MTR bytes. API and browser tests separately exercise real role checks and user workflows.

Release checks passed 132 receiving/catalog/document API regressions and 68 export, weld-progress and bounded-upload checks. The operating-guide contract passed 13 groups. The finalized PostgreSQL verifier was repeated after the assembly-collection and response-cache changes; both concurrent approval and queued stale-evidence rejection remained correct. The core focused rerun also verifies that material/MTR query counts remain constant as individual weld count grows, and that arrival approval cannot be bypassed through alternate work or release paths.

Actual Chromium verification passed 11 receiving/MTR groups and 10 existing order-setup groups with zero page errors. It checks same-number spool isolation, missing-document Fail, per-piece materials, Pass and changed-evidence reinspection, explicit adoption/archive history, stale-save protection, Back/draft/save guards, roles, two rendered MTR PDF pages, and image normalization/upload. Desktop and 390-pixel phone screenshots were visually reviewed. UI contracts also passed 11 material/arrival, 20 setup, 14 order and 8 spool-label groups. The QR boot flow now refreshes only its still-active audit area after the single scan event, preserving a rapidly opened Materials dialog; long audit hashes wrap on mobile.


## Saved material pieces, QA-001 and readable labels — 2026.10.31-piece-qa-labels.1

### Material records and inspection basis

`spool_boms.ensure_material_piece_records(s, item_or_id, actor, reason, uploaded_only=True)` pins a valid effective uploaded structured BOM and saves one blank `SpoolBomMaterial` row per whole piece. A quantity-2 line creates two records scoped by physical spool, source/line and piece identity. Existing pins and saved material facts are left intact. Document-save propagation uses exact order requirement membership; new physical copies initialize after their registration is flushed. Unsupported/non-piece or oversized definitions remain explicit blockers. No source is assigned by a matching number in another P.O.

`piece_identifier` combines the unchanged physical Item ID with the BOM source stamp, line number and piece number. It is independent of the readable QR alias. Blank row initialization records provenance through `SpoolBomEvent` and `Audit`, without heat/MTR values, receipts or approvals. Catalog-only references keep their existing workflow; automatic backfill is limited to valid uploaded structured sources.

The additive `spool_material_inspections` table stores immutable `SpoolMaterialInspection` decisions: physical spool, piece key, version, fixed `QA-001` code, Pass/Fail, inspector, time, reference, findings and full signed basis. `POST /api/spool-boms/spools/{id}/materials/{piece_key}/qa-001` requires QA authority, the expected piece decision version and current `basis_sha256`; the corresponding GET returns retained history. Pass requires the saved piece, current source, heat number and MTR reference. Fail can record incomplete evidence. The basis includes the exact physical context, piece values, source/drawing documents and the MTR revision matching that piece's reference. An unrelated sibling material edit does not change the piece's basis.

Overall arrival Pass now requires every current piece's QA-001 Pass plus the existing five checks. Its basis includes the piece inspection metadata, so a later decision or relevant source/material change requires a new overall decision. All existing receiving guards and timer-pause behavior continue to apply. Current packet review fingerprints include the expanded arrival basis; previously issued snapshots and attachments retain their exact content.

### Additive deployment and legacy records

`init_db.initialize` creates missing tables and protects `spool_qr_identities` and `spool_material_inspections` with the existing PostgreSQL immutable-history trigger. It takes the initialization advisory lock and then the shared topology lock **before DDL**, keeping the same lock order through both backfills. No existing columns or immutable work/inspection rows are rewritten.

QR backfill visits physical Spool items and non-Assembly legacy plan/registration items in `(created_at, item_id)` order, in bounded batches. Existing aliases are skipped. Removed items participate so their sequence numbers stay reserved. Every assigned alias has an audit event; missing spool numbers are counted and left unchanged. Material backfill initializes only missing valid uploaded-BOM registers, in batches, and attributes automatic creation to the disabled `system:material-piece-backfill` account. It never copies a heat number or Pass from another physical spool.

Existing current material entries remain in place. Missing piece QA stays pending; an earlier overall arrival Pass may need reinspection under the expanded current basis. Historic release flags, accepted records and issued packets are retained, and no historical QA-001 decisions or traveler completions are fabricated. `/healthz` checks the new tables. Administrator exports include readable identities and material QA metadata; retained binary files remain in their controlled download/packet paths.

The current process catalog is `CLM-24-v2` with the five QA titles listed above. New events snapshot the new definition; old events preserve their original definition/version/label. The numbered route, individual piece QA and overall spool arrival approval remain separate recorded actions.
