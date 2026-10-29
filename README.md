# FabTrace Cloud

FabTrace Cloud is a FastAPI and PostgreSQL application for shared fabrication records, employee badge sign-in, QR labels, custody handoffs, and project-to-weld traceability. The browser interface uses plain HTML, CSS, and JavaScript.

## What this version adds

The **Projects & welds** workspace organizes **project → subproject / work package → spool → individual weld**. A spool plan attaches to an existing item, keeping its item ID, QR link, custody, and inspection history.

- Project/subproject rollups, a spool register, a weld requirement matrix, and an outstanding-requirements queue.
- Both material sides, component identifiers, heat numbers, MTR references, WPS/revision, joint type, size, and drawing revision for every weld.
- Configurable work operations: root and fill/cap by default, or a single-pass fill/cap workflow. Multiple operations still count as one completed joint.
- Separate requirement definitions, submitted evidence, inspector reviews, holds, repairs, and audit history.
- Immutable requirement-template revisions for newly created welds. Core material, procedure/qualification, fit-up, visual, NDE-plan, and final-QA controls remain present.
- Separate production-complete, weld-QA-accepted, ready-for-release, and final-release counters. Final release is not shipment.
- Audit-readiness workspaces with the five-prompt Kelvion matrix, controlled document revisions, actual evidence, signed reviews, corrective actions and current-state Excel reports.
- Spool process timers with start, move, pause, resume and finish controls; current-process age, visit history, repeat-visit totals, and Excel timing reports.
- A numbered **Process flow** workspace following CLM's 24-step material-to-shipment chart, with linked components/spools/assemblies, scanned or entered identity checks, custody handoffs, QA gates, exception/rework returns, and separate shipment and delivery confirmation.
- **Project progress** with progress bars for registered parts, WIP/finished/shipped/delivered filters, work-package and part-type filters, and links to each physical record.
- **Job Packets / CLM Final Dossiers** organized into ten sections and 25 detailed checks, based on Kelvion QF-QAS-100 Rev B page 8. Current fabrication records, uploaded controlled files, signed QA reviews, immutable issued revisions, printable packets, ZIP downloads and separately recorded physical/digital handovers are linked by project and item.

Existing item registration, bulk CSV import, employee QR badges, item QR labels, and custody handoffs remain available. Item types include **Part**, **Spool**, and **Assembly**.

## Existing records and enrollment

Deploying this version does **not** convert existing items, invent individual welds, or turn aggregate weld counts into accepted weld records. Items retain their previous workflow until a supervisor or administrator creates a spool plan for that item.

Enrollment is explicit. It preserves historical records, establishes the planned joint count, and makes individual weld work and requirements authoritative. Old aggregate weld logging and blanket weld inspection are then rejected for that spool. Historical work remains in audit history; displayed completion is calculated from individual records. Prior green inspection flags cannot bypass the new requirements. Released items must be reopened by an administrator before enrollment or other changes.

See [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for the shop workflow, [DOSSIER_GUIDE.md](DOSSIER_GUIDE.md) for progress and completed-project packets, and [DEVELOPMENT.md](DEVELOPMENT.md) for implementation details.

## Track project progress and assemble the final Job Packet

Open **Project progress** or `/?progress=1`. Each project shows registered parts finished, WIP and shipping milestones. Open a project to sort **WIP to finished**, filter by work package or type, and inspect each part's recorded route/weld progress and actual blockers. A documented late starting point leaves earlier steps **Not recorded**. A progress bar does not invent missing BOM items or certify a dossier.

Open **Job Packets** or `/?dossier=1`. Explicitly configure the project's manufacturer contact, PO, source/applicability reference and expected spool/assembly packet count. Upload shared approved project records once and item-specific reports under their own item IDs. Each check links the exact file revisions and relevant FabTrace weld, inspection, rework, release and traveler records. QA records a separate decision on evidence and non-applicability after submission.

The dossier catalog was cross-checked against the original ITP and the five supporting customer documents. Its ten sections are CLM's organization of the eight Job Packet contents; project/PO applicability still needs an authorized review. Conditional tests retain their actual measurements, units, approved basis and approval references. No universal pressure, duration, coating thickness or NDE method is imposed.

For projects with the Job Packet gate enabled, the numbered assembly workflow checks approved pressure-test/customer hold evidence before coating at steps 20/21, and current QA-issued packets before ready-to-ship/shipment at steps 23/24. Applicable written customer pre-shipment approval is a separate record. QA can issue an item packet after current release and complete checks; the completed-project package additionally requires the declared scope and current item packets. Changed evidence or physical work makes affected approvals stale while issued snapshots remain intact.

Download an issued **ZIP** for digital transfer or open its **Print** view for paper/PDF. The ZIP contains the issued manifest, readable packet and selected original files. Record the actual digital or physical dispatch against that exact project revision, then record the recipient's separate acknowledgement. Generating, downloading or printing a packet does not send it or record receipt. See [DOSSIER_GUIDE.md](DOSSIER_GUIDE.md) for the full sequence.

## Follow the CLM process chart

Open **Process flow** in the navigation or from an item's record. An administrator or supervisor starts its route: individual components use steps 1–8, tracked spools use 9–16, and tracked assemblies use 17–24. The full map retains all 24 numbered steps, while each physical item's traveler highlights its own current, completed, pending and unrecorded steps. Parent/child links let staff follow the work across those records.

Declare the required component or child-spool count, link the actual item IDs, and complete each current step's checklist and required scan/entered ID, receiving badge, location or document reference. The app records the employee and time. Spools and assemblies need their existing project/weld plans first. An assembly cannot advance with missing or unreleased child spools, or unresolved issues in their component records.

Incoming verification and the four QA checkpoints have controlled failure returns. A failed inspection creates an exception, sends the traveler to its selected rework step and preserves earlier attempts. Passing the failed checkpoint again requires current quality records and an explicit resolution. Individual weld operations and acceptance still belong to **Projects & welds**. Checkbox confirmations cannot substitute for them.

Numbered steps drive the existing process clock automatically. Staff can pause/resume for delays; moving to another numbered step requires completing the current one. Quality release occurs at spool QA step 15 or assembly final QA step 22; subsequent handoff and shipping steps remain available. Step 24 records shipment with a carrier, reference and destination. **Confirm delivery** separately records the receipt reference and recipient.

For work already underway, a supervisor can select the current starting step and record its existing-work reference and reason. Earlier steps remain **Not recorded**. A spool using existing controlled material records instead of newly linked component travelers needs an explicit material reference. No historical completion or timing is invented. Required-child counts can be corrected with a reference and reason while the traveler is still at its material-selection/collection stage.

## Prepare for the Kelvion audit

Open **Audit readiness** or `/?quality=1`. An administrator or supervisor creates a workspace for CLM generally or for a specific project and purchase order. The Kelvion starter matrix uses the supplied audit-preparation prompts, including the priority items **7, 9, 13 and 14**. It creates draft requirements only: no inspections, employee training, Quality Alerts, completed audits or corrective-action closures are invented.

Each item organizes the customer requirement, CLM's response, supporting controlled documents, evidence to produce, and gaps/corrective actions. Register exact document revisions, their approval references and any required employee training. Record actual approved schedules separately from completed audits; attach actual Quality Alerts and the corresponding training, inspection reports, investment records or other evidence. The app stores references and locations, not the external files themselves.

An inspector or administrator confirms the applicable source document/revision/clause and reviews the actual evidence. **Verified** requires current evidence and approved document revisions, satisfied training requirements, resolved applicability, and closed corrective actions where required. Corrective-action closure requires implementation evidence and an effectiveness check, plus customer approval when declared applicable. Changed requirements, document revisions, evidence or relevant linked production records require renewed verification while earlier reviews remain in history.

The supplied seven-document summary is a planning basis. Its draft controls do not approve universal NDE percentages, pressure-test values, coating systems or customer deadlines. Check the applicable original documents, PO and written approvals before confirming a requirement. Optional project-scoped **Pre-coating** and **Shipment** gates can then require selected audit items at numbered flow steps 20/21 and 23/24. Gates default to off; organizational audit preparation alone does not change production release rules.

See [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for setup and the evidence/review sequence.

## Track time in each production process

Open **Projects & welds**, choose a spool in the **Spool register**, and use its **Production process** card. Select a process and start its timer. **Move to process** closes the current visit and starts the next one at the same time. **Pause** records a delay reason; **Resume** continues running time. **Finish process** closes the visit when no new process should start yet.

Choose material preparation, cutting/beveling, fit-up, welding, NDE/testing, PWHT, dimensional inspection, coating/painting, final QA, ready for dispatch, or a custom process. Repeated visits remain separate in history and are combined in totals for that process. Any active employee can record timing; the employee badge and server timestamp are retained for every change.

Elapsed time includes both running and paused time. These are calendar durations for an item, not employee labor hours or shift-adjusted hours. Timers keep counting across logout and overnight. Timing starts when staff record the first start; earlier work and gaps after finishing are not inferred. Quality holds and timer pauses are separate actions. Finishing a manually selected process does not complete welds or grant quality approval.

For items using manual process timing, final release closes the timer and administrative reopening leaves it stopped. A numbered CLM traveler instead starts the next required post-QA handoff/shipping step after release, and a permitted administrative reopen returns it to the relevant QA checkpoint. Its numbered workflow owns stage transitions; manual pause/resume remains available.

## Export everything to Excel

Sign in as an **administrator** and click **Export Excel** in the top navigation. The button shows **Preparing Excel…** while the workbook is generated, then the browser downloads an `.xlsx` file.

The workbook includes the current business records and their histories on separate worksheets, plus export information. It excludes private PINs and PIN hashes. Evidence/report references are included; linked report files are not embedded. This is a snapshot for review and analysis: editing the workbook does not update FabTrace, and the workbook is not a database restore format. Keep database backups separately.

**Process events** contains every timing action. **Process visits** contains each visit's start/end, actor, and elapsed/running/paused time. **Process totals** combines repeated visits by spool and process. Both reports include project and subproject IDs and numeric seconds/decimal hours for Excel analysis. Open visits are calculated as of their report timestamp. Spools without a recorded start have no fabricated timing rows.

**Flow plans**, **Flow events**, **Flow exceptions**, and **Component links** preserve numbered travelers, checklists, custody details, rework, parent/child identities, and shipment/receipt records. **Flow steps** provides the current 24-step definition lookup. Historical flow events also retain the definition version and step/checklist text recorded at the time.

The **Audit readiness** report presents the five audit prompts, current source/verification status, evidence references and blockers in one row per requirement. Separate **Quality** worksheets preserve workspaces, requirements, document revisions, evidence, corrective actions, reviews and change history. They share the same read-only snapshot as the production data. Draft responses remain explicitly unverified; an exported matrix does not certify compliance.

Seven **Packet** worksheets retain dossier configuration, checklist entries, file metadata, signed reviews, issued snapshots, handovers and events. **Project progress**, **Part progress** and **Job Packet readiness** report their current states from the same snapshot. Uploaded binary files are excluded from Excel; use the issued packet ZIP for the selected original files.

## Run locally

Use Python 3.12 and an existing local PostgreSQL database/user.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp env.example .env
```

Edit `.env` with local values, then load it into the shell. The application does not read `.env` automatically.

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection URL. `postgres://` and `postgresql://` are normalized to the installed `psycopg` driver. |
| `JWT_SECRET` | A private random secret of at least 32 characters; use a longer generated value for deployment. |
| `BOOTSTRAP_BADGE` | Administrator badge for the first initialization of an empty employee table. |
| `BOOTSTRAP_PIN` | Private initial PIN/passphrase, at least 12 characters. Existing accounts are never replaced. |
| `COOKIE_SECURE` | Set `false` for local HTTP only; keep `true` on the deployed HTTPS service. |
| `PUBLIC_BASE_URL` | Public HTTPS origin used in phone QR links. On Render, an unset value falls back to `RENDER_EXTERNAL_URL`. |

For local HTTP, use `PUBLIC_BASE_URL=http://localhost:8000`; QR printing remains disabled because those labels would not be public phone links. Replace all example credentials. Keep `.env` out of version control.

```bash
set -a
. ./.env
set +a
python init_db.py
uvicorn main:app --reload
```

Open `http://localhost:8000`, sign in with the configured bootstrap account, and create the employees who will use the application. Work records use the authenticated employee rather than an operator-supplied actor name.

## Update the existing Render service

Use the current web service and its current PostgreSQL database. This feature update does not require a new service, database, or Blueprint.

Deploy the complete source, including `tracking.py`, `production.py`, `flow.py`, `quality.py`, `quality_templates.py`, `dossier.py`, `dossier_templates.py`, `progress.py`, `exports.py`, and all JavaScript/CSS under `static/`. Run `python init_db.py` against the existing database before the new application receives traffic. The supplied `render.yaml` uses this as its `preDeployCommand`; an existing service must actually have that command configured, or initialization must run as a controlled manual rollout step.

Initialization creates missing tables, installs history-protection triggers, and skips account bootstrap when employees already exist. PostgreSQL initialization runs in one transaction under an advisory lock. It does not seed production projects or alter existing item rows. `create_all()` does not add future columns to existing tables; later schema changes need explicit migrations.

Use [START_HERE_DEPLOY.md](START_HERE_DEPLOY.md) for the rollout sequence. Keep existing database and secret settings. Confirm `/healthz` reports the new application version and that original records and sign-in still work.

## Tests

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
```

The API suite creates isolated temporary databases and does not use a deployed `DATABASE_URL`. It covers the legacy workflow and individual-weld gates. The Node smoke harness uses synthetic fixtures to check routing, metrics, role controls, evidence rendering, and write payloads without contacting a service.

PostgreSQL verification covers additive initialization, history triggers, and concurrent writes. Its explicit local-test DSN guard rejects operational and remote database targets:

```bash
python tests/verify_postgres.py --help
```

See the developer guide before running that local check.

## Scope and limits

Tracking and Audit readiness retain controlled report references and notes. Job Packets additionally accept PDF, PNG/JPEG, TXT/CSV, DOCX and XLSX files, up to 8 MiB per file and 256 MiB of retained uploads per project. File bytes are stored in PostgreSQL with immutable metadata and SHA-256; no persistent Render disk or additional storage service is required. Procedure and qualification applicability remain authorized reviews. The application does not calculate qualification ranges or choose governing acceptance criteria.

Add project-specific NDE, PMI, PWHT, hardness, coating, or other requirements from approved job documents. Job Packet pressure, torque, NDE and coating checks retain actual result fields and supporting reports; technical acceptance remains the authorized reviewer's decision. Numbered assembly travelers check declared child-spool scope and readiness, and record shipment and delivery confirmations. Assemblies outside that workflow retain the original physical-release behavior; dossier issuance separately verifies current child packets. Carrier labels, automated emails, customer portal submission and cryptographic customer signatures are not generated. Use the print/ZIP output and record the actual transfer and receipt.

Badge/PIN sign-in and audit records are the current controls. PostgreSQL history triggers reject routine updates and deletes, but do not protect against a database owner deliberately removing those controls. Validate configured work and acceptance rules with the people responsible for the job before using them for fabrication release. This application is not a certification of compliance.
