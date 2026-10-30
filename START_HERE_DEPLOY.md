# Deploy or update FabTrace Cloud on Render

### Expandable production progress: `2026.10.30-progress.1`

Include `production_progress.py`, `static/production-progress.js`, `static/production-progress.css` and the synchronized shells. The new read-only endpoint displays active P.O. scope and recorded traveler events. No schema change or automatic production record creation is required. Keep the existing initialization, health check, service and database settings. Verify the deployed version and static assets, then compare retained record counts through read-only checks.

### Record removal release: `2026.10.30-removal.1`

Include `removals.py`, `static/removals.js`, `static/removals.css`, the synchronized HTML shells and the reviewed active-scope integration changes. The existing `python init_db.py` pre-deploy step adds one absent table, `record_removals`; no existing rows are removed or enrolled. Health checks now verify that table too. Keep the existing service/database and all nineteen immutable history protections. The release adds administrator-only removal previews and restoration, with explicit scope confirmation and reasons. Do not test by removing real customer work: validate release health/assets and read-only retained-record counts after deployment, then let an administrator choose the actual entries to remove.

## Update the existing FabTrace service first

**Use the existing web service and its existing PostgreSQL database.** Adding project, spool, and individual-weld tracking does not require creating a second service, a second database, or a new Blueprint.

1. Identify the current service's connected repository/branch and keep its existing `DATABASE_URL`, `JWT_SECRET`, public URL, and employee accounts. Make the normal database recovery point for the rollout.
2. Update the service with the complete reviewed source. Include `main.py`, **`tracking.py`**, **`production.py`**, **`flow.py`**, **`quality.py`**, **`quality_templates.py`**, **`dossier.py`**, **`dossier_templates.py`**, **`progress.py`**, **`exports.py`**, `init_db.py`, `requirements.txt`, **`static/index.html`**, the **tracking, flow, quality, progress and dossier JavaScript/CSS** under `static/`, and the existing static assets. The root `index.html` is a distribution copy; the application serves `static/index.html`.
3. Confirm the service's initialization step is **`python init_db.py`**. The supplied `render.yaml` sets this as `preDeployCommand`, but uploading a YAML file alone does not change an independently configured existing service.
4. Run initialization before the new version accepts requests. Use the configured pre-deploy command, or a controlled manual step running the new `init_db.py` with the existing database settings. Keep the previous application serving until initialization succeeds, or use the service's maintenance procedure. Do not start the new app against an uninitialized schema.
5. Deploy with the existing start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
6. Check `/healthz`. It must return `status: "ok"`, the current application version, and the deployment commit when Render supplies it. Health checks confirm the weld tracking plan, production process event, numbered flow plan, quality workspace, dossier project/issue, spool parts, transfer-state/location and purchase-order/GPN/assembly tables are available as well as the database connection.
7. Sign in with an existing employee account. Confirm existing item, QR, custody, and inspection records are still available. The navigation should include **Projects & welds**, **Process flow**, **Audit readiness**, **Production progress** and **Job Packets**. Production progress includes a **Project detail / All project records** shortcut to the earlier project register.
8. Follow [ORDERS_GUIDE.md](ORDERS_GUIDE.md) to create a PO or explicitly connect an existing project, add GPNs and assemblies, and plan the intended spools. New orders, projects and accepted welds are not seeded by deployment.

### What initialization changes

`init_db.py` adds absent tables, installs PostgreSQL protection against updates/deletes on nineteen history/file tables, and creates a bootstrap administrator only when the employee table is empty. PostgreSQL setup is transactional and serialized with an advisory lock. Existing employee and item records are retained; no automatic spool/traveler enrollment or process-time history is invented. The audit-readiness release adds seven quality tables and protects immutable document revisions, evidence, reviews and events. It does not alter existing table columns. No audit workspace, approved source, evidence or completed activity is seeded during deployment; users explicitly create draft workspaces after sign-in.

`create_all()` does not add columns to tables that already exist. Future column changes require an explicit migration. If upgrading a substantially older installation, compare its actual schema with the source before deployment; the earlier Google part-number migration is separate from this tracking addition.

### If the update does not start

- Inspect the deployment's build, initialization, and application logs separately.
- A missing tracking-table error means initialization did not complete against the database the web service uses.
- An initialization lock timeout should be investigated for an overlapping deploy or database lock before retrying.
- Preserve the operational database and secrets while correcting the application. Do not create an empty replacement database to clear an error.
- Do not remove the new history tables as an application rollback step. Once spools are enrolled, rolling back to code that ignores their individual requirements can restore unsafe aggregate shortcuts; use a controlled forward fix or a reviewed rollback that preserves the tracking gates.

## First deployment only

For a genuinely new installation, the supplied `render.yaml` describes a Python web service and a PostgreSQL database. Review the proposed resources and costs in Render before creating them.

1. Put the source in a private repository without `.env`, credentials, or database exports.
2. Connect that repository to Render using your chosen deployment workflow. If using the supplied Blueprint, it provides the database connection and generated JWT secret, runs `python init_db.py`, and starts FastAPI.
3. Supply a unique `BOOTSTRAP_BADGE` and a private `BOOTSTRAP_PIN` of at least 12 characters. Keep the PIN out of QR labels, source control, and shared documents.
4. After deployment, open the actual service URL, check `/healthz`, sign in, and create individual employee accounts.
5. Register an item, print a sample item QR and employee badge QR, and check them on the phone/browser used in the shop before printing a batch.

For environment setup outside a Blueprint, see [README.md](README.md). The included example is named `env.example`.

## QR URLs and existing labels

Item labels encode `https://YOUR-SERVICE/?item=ITEM-ID`; employee badges encode `https://YOUR-SERVICE/?badge=BADGE-ID`. These are patterns, not actual service addresses. QR codes identify a record or employee; they never contain the private PIN and do not authenticate the employee.

The application uses `PUBLIC_BASE_URL`, or Render's `RENDER_EXTERNAL_URL` when unset. Public QR generation requires a valid HTTPS origin. `/api/qr/status` checks the configured URL shape, not phone connectivity or record accessibility.

Keeping the same service origin and item IDs preserves existing item links. An employee must still sign in to see or change a record. Changing the public hostname requires a plan for already printed labels.

## Local prototypes and scope

Browser-local prototype data is not automatically copied into PostgreSQL. Use the cloud item/employee workflows and supported CSV import; a prototype JSON backup is not a database restore.

Tracking and Audit readiness retain evidence references. Job Packets additionally store controlled uploaded files, exact issued snapshots and physical/digital handover records. Qualification applicability and technical acceptance remain reviewed decisions. Current pressure-test/customer hold decisions gate the configured pre-coating stages; current item/child packets gate configured shipment stages. ZIP and print outputs support manual transfer through approved channels; no email, carrier or customer portal integration is configured. See DOSSIER_GUIDE.md for the operating sequence.

## Audit readiness configuration

The new routes reuse badge sessions and existing roles. No environment variables, secrets, external storage services or paid resources are added. All staff can read; administrators and supervisors create workspaces; administrators, supervisors and inspectors maintain the matrix and submit records; inspectors and administrators perform signed source/evidence/document/requirement reviews and corrective-action closure. Project gates default to none and must be deliberately selected by a reviewer. Once enabled, use a forward fix if a problem occurs: older code does not know these optional gate rules.

## Job Packet and progress update

Version `2026.10.29-dossier.1` adds eight dossier tables and two read-only progress endpoints. It needs no new environment variable, paid resource or persistent disk. Uploaded originals are stored in the existing PostgreSQL database, with limits of 8 MiB per file and 256 MiB per project. Include their storage in normal database capacity and backup planning.

Initialization creates the tables and six new immutable-history/file triggers without altering existing table columns or seeding real packet approvals, files or handovers. The existing main service remains the deployment target. A project administrator/supervisor must explicitly configure each intended Job Packet project, and QA must confirm its actual PO/source applicability. Do not enable gates by writing invented approvals into existing jobs.

After deployment, verify the new navigation/assets, `/healthz` version/commit and database trigger coverage. Run workflow acceptance with synthetic local fixtures; do not fabricate production inspection, issuance or transfer records as a smoke test. Once gates are used, a rollback to older code would ignore them; prefer a controlled forward fix preserving all issued history.


## Guide and setup navigation update

Version `2026.10.29-guide.1` adds the authenticated **Guide & setup** screen, project-scoped setup shortcuts, explicit planning-filter reset and persistent Job Packet tab links. Deploy `static/guide.js`, `static/guide.css` and the synchronized HTML shells with the rest of the source. There are no schema, infrastructure, credential or production-data changes. The existing pre-deploy initializer remains safe and idempotent. Verify `/?guide=1`, login/deep-link routing, mobile guide layout, empty-project states and the existing workflow screens after the update.

## Spool parts quantity update

Version `2026.10.29-parts.1` adds four parts-plan/requirement/allocation/history tables and the **Spool parts** workspace. Deploy `parts.py`, its backend integrations, `static/parts.js`, `static/parts.css` and both synchronized HTML entrypoints. The existing `python init_db.py` pre-deploy command creates the tables and protects the new parts history; no existing column migration or new infrastructure is required.

Initialization does not create parts lists, physical items, allocations, receipts or preparation records. Existing spools are enrolled only by an authorized user. Verify health, new-table/history coverage, authenticated parts navigation, a synthetic local quantity/QR workflow and current Excel/Job Packet behavior. Retain all existing database and secret settings.

## Both-badge handoff update

Version `2026.10.29-transfer.1` adds `item_transfer_states` and `transfer_locations`. Deploy `transfers.py`, its backend integrations, `static/handoff.js`, `static/handoff.css`, the updated flow/guide scripts and both synchronized HTML entrypoints. The existing pre-deploy initializer creates the two absent tables; no existing column migration, new environment setting or new infrastructure is required. The nineteen protected history/file tables remain protected; transfer records use the existing immutable audit/flow histories.

Existing item locations, custodians and history remain unchanged. Initialization creates no transfer state, custom location, employee acknowledgment or new production activity. Built-in dropdown choices are definitions only. New transfers require both active badges, the recorded current custodian as sender, selected location/status and the current transfer version. Update browser assets together with the API; older cached single-badge submissions are intentionally rejected. Refresh open sessions after deployment.

Verify synthetic local handoffs, same-custodian moves, step-3 location capture, numbered handoff checks, stale-version conflicts, role controls and both camera callback paths before deploying. Check live health/version/assets and additive schema coverage without creating operational test transfers. Do not roll back to a single-badge write path that would ignore the new transfer versions; prefer a controlled forward fix.

## Administrator release and access controls

Version `2026.10.29-admin.1` adds the administrator workspace, explicit release/return/custody decisions and employee account/PIN controls. Deploy `administration.py`, `static/admin.js`, `static/admin.css`, the updated integrations and both identical HTML shells. The existing `python init_db.py` pre-deploy command adds only `employee_access_states`; all nineteen immutable history/file protections remain. No existing column migration, infrastructure, secret or credential replacement is needed.

Initialization creates no employee-access rows, release overrides or custody decisions. Existing sessions use access version zero until an explicit account change requires revocation. Profile access changes and PIN resets revoke the affected employee's sessions; an unchanged account keeps working after deployment. At least one active administrator must remain, including during concurrent account changes.

Verify admin-only navigation and APIs, release with actual outstanding blockers, honest QA/progress/packet labels, prior-route restoration, administrative custody correction, stale decisions, last-admin concurrency, PIN reset/session revocation and unchanged ordinary QA workflows using local synthetic data. Live verification must remain read-only. Do not manufacture a production override or account change as a smoke test. After access revocation or administrative release is used, older code would ignore the new semantics; use a forward fix preserving the history and session controls.

## Job positions and restricted controls

Version `2026.10.29-permissions.1` adds the ten-position policy in `permissions.py`, authenticated permission hints and matching job-specific controls. Deploy the policy, integrated API modules, updated browser assets and both identical HTML shells together. The existing `python init_db.py` pre-deploy step remains idempotent. This version adds no tables, columns, resources, environment settings or credentials; it creates no employee-access state, employee assignments or production records.

Existing accounts retain their position. An Administrator remains unrestricted until explicitly assigned another position through Admin controls. Ordinary badge handoffs remain available to all supported positions; welding, finishing, painting, QA, timers and evidence use their defined job permissions. Existing requirement ownership is now enforced for submission, with QA/management oversight; default inspector-owned requirements remain QA/QC responsibilities. Position/access/PIN changes revoke old sessions, including queued writes revalidated under the shared transaction lock. Update cached browser pages after deployment.

Before deployment, verify allowed and rejected trade actions, unchanged state after denials, scoped evidence and document revisions, distinct packet issue/handover authority, timer source/destination checks, and queued role/PIN revocation using disposable local data. Verify historical packet fingerprints remain stable when viewed by different positions. Live checks must remain read-only: confirm health/version/assets, unchanged existing records and the existing 43-table/19-protection schema. Do not reassign production employees as a test. See [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for explicit administrator assignment instructions.

## Employee removal update

Version `2026.10.29-employees.1` adds **Remove employee** and **Restore employee** to the administrator account controls. Deploy `administration.py`, `main.py`, `exports.py`, the updated browser assets and both identical HTML shells together. The existing `python init_db.py` pre-deploy command adds only `employee_removal_states`; the resulting schema has 44 tables and the same 19 immutable history/file protections. No existing columns, infrastructure, secrets or credentials change, and deployment removes no employees.

Removal hides the account from the normal roster, makes it inactive and revokes sessions. The Employee row and historical references remain. Restoration returns it as inactive; profile edits and PIN reset require explicit restoration first. Repeated initialization creates no removal/access records and preserves all existing employee, production and packet data. Reuse of a retained badge remains blocked.

Before deployment, verify admin-only access, stale and duplicate decisions, last-active-admin races, queued employee removal, existing-session revocation, explicit inactive restoration, retained custody/history/packet fingerprints and read-only Excel removal metadata using disposable local data. Live verification is read-only: confirm the exact health version, served browser assets, 44-table/19-protection schema, empty new removal table and preserved existing records. Do not remove or restore a production employee as a test. See [ADMIN_GUIDE.md](ADMIN_GUIDE.md) for the operating steps.

## PO-first planning and scoped Excel BOM update

Version `2026.10.30-orders.1` adds `purchase_orders`, `order_gpns` and `order_assemblies`, producing 47 application tables with the same 19 protected history/file tables. Deploy `orders.py`, `orders_excel.py`, their tracking/flow/dossier/export integrations, the new orders assets, updated guide and both identical HTML shells. The existing `python init_db.py` pre-deploy command creates only the absent tables; no existing columns, credentials, paid resources or environment settings change.

Initialization enrolls no production project, creates no order/assembly/spool and changes no existing identity or approval. Management explicitly starts the PO-first workflow or attaches existing projects after reviewing their real PO/customer and Job Packet scope. Required spool-count validation is also enforced through the older planning/traveler APIs. Preserve these guards in future upgrades and rollbacks.

Before deploying, verify duplicate PO and stale-version races, shared assembly capacity, traveler-start versus count-edit concurrency, role restrictions, existing QA/QR flows, snapshot/export behavior and desktop/mobile planning with local synthetic data. After the existing service's deploy is live, verify `/healthz` reports `2026.10.30-orders.1` and the deployed commit, served orders/guide assets match, the schema has 47 tables and 19 protections, and new order tables are initially empty. Live checks remain read-only. Do not create a sample customer order or release a production item as a smoke test. See [ORDERS_GUIDE.md](ORDERS_GUIDE.md).

### Four-step order layout and item-description simplification

Version `2026.10.30-orders.2` separates the order workspace into **P.O → G.P.N → Assembly → Spools** and removes redundant physical item descriptions from current entry/display/QR-label workflows and scoped order workbooks. Deploy the updated input models, order export, browser scripts and identical HTML shells together. New individual, bulk and PO-assembly creation accepts omitted descriptions; old client/CSV values remain compatible and no stored description or issued history is deleted.

The schema remains at 47 tables with the existing 19 history protections. The pre-deploy initializer remains idempotent. No environment, resource, database column or account change is needed. Verify identifier-only item creation and CSV import, all four navigation levels and back links, scoped exports, roles, QR labels and mobile layout with synthetic local data. Confirm the live version/commit and source asset hashes using read-only requests after deployment.

### Combined GPN / Assembly workflow

Version `2026.10.30-orders.3` combines the middle order levels into **P.O → GPN / Assembly → Spools**. Deploy the new combined endpoints in `orders.py`, scoped workbook changes in `orders_excel.py`, orders assets, guide, version and identical HTML shells together. One atomic setup registers a combined number and physical assembly, generates a QR ID by default and reuses an existing unfinished GPN when applicable. One guarded correction updates the combined number and count. Old data and endpoints remain compatible.

The database still has 47 tables and 19 immutable history/file protections. Initialization creates no new production records and rewrites no existing GPN or assembly. No environment, infrastructure, dependency or column migration is needed. Verify atomic rollback, duplicate/concurrent setup, draft completion, generated/custom physical IDs, controlled renumbering, legacy differing numbers, traveler locks, scoped Excel and three-step desktop/mobile navigation using synthetic fixtures. Check live health/version/commit, asset hashes and existing records read-only after deployment.
