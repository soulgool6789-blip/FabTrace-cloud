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
- Spool process timers with start, move, pause, resume and finish controls; current-process age, visit history, repeat-visit totals, and Excel timing reports.

Existing item registration, bulk CSV import, employee QR badges, item QR labels, and custody handoffs remain available. Item types include **Part**, **Spool**, and **Assembly**.

## Existing records and enrollment

Deploying this version does **not** convert existing items, invent individual welds, or turn aggregate weld counts into accepted weld records. Items retain their previous workflow until a supervisor or administrator creates a spool plan for that item.

Enrollment is explicit. It preserves historical records, establishes the planned joint count, and makes individual weld work and requirements authoritative. Old aggregate weld logging and blanket weld inspection are then rejected for that spool. Historical work remains in audit history; displayed completion is calculated from individual records. Prior green inspection flags cannot bypass the new requirements. Released items must be reopened by an administrator before enrollment or other changes.

See [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for the shop workflow and [DEVELOPMENT.md](DEVELOPMENT.md) for implementation details.

## Track time in each production process

Open **Projects & welds**, choose a spool in the **Spool register**, and use its **Production process** card. Select a process and start its timer. **Move to process** closes the current visit and starts the next one at the same time. **Pause** records a delay reason; **Resume** continues running time. **Finish process** closes the visit when no new process should start yet.

Choose material preparation, cutting/beveling, fit-up, welding, NDE/testing, PWHT, dimensional inspection, coating/painting, final QA, ready for dispatch, or a custom process. Repeated visits remain separate in history and are combined in totals for that process. Any active employee can record timing; the employee badge and server timestamp are retained for every change.

Elapsed time includes both running and paused time. These are calendar durations for a spool, not employee labor hours or shift-adjusted hours. Timers keep counting across logout and overnight. Timing starts when staff record the first start; earlier work and gaps after finishing are not inferred. Quality holds and timer pauses are separate actions. Finishing a process does not complete welds or grant quality approval. Final release automatically closes an open timer; reopening does not restart it.

## Export everything to Excel

Sign in as an **administrator** and click **Export Excel** in the top navigation. The button shows **Preparing Excel…** while the workbook is generated, then the browser downloads an `.xlsx` file.

The workbook includes the current business records and their histories on separate worksheets, plus export information. It excludes private PINs and PIN hashes. Evidence/report references are included; linked report files are not embedded. This is a snapshot for review and analysis: editing the workbook does not update FabTrace, and the workbook is not a database restore format. Keep database backups separately.

**Process events** contains every timing action. **Process visits** contains each visit's start/end, actor, and elapsed/running/paused time. **Process totals** combines repeated visits by spool and process. Both reports include project and subproject IDs and numeric seconds/decimal hours for Excel analysis. Open visits are calculated as of their report timestamp. Spools without a recorded start have no fabricated timing rows.

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

Deploy the complete source, including `tracking.py`, `production.py`, `exports.py`, `static/tracking.js`, and `static/tracking.css`. Run `python init_db.py` against the existing database before the new application receives traffic. The supplied `render.yaml` uses this as its `preDeployCommand`; an existing service must actually have that command configured, or initialization must run as a controlled manual rollout step.

Initialization creates missing tables, installs history-protection triggers, and skips account bootstrap when employees already exist. PostgreSQL initialization runs in one transaction under an advisory lock. It does not seed production projects or alter existing item rows. `create_all()` does not add future columns to existing tables; later schema changes need explicit migrations.

Use [START_HERE_DEPLOY.md](START_HERE_DEPLOY.md) for the rollout sequence. Keep existing database and secret settings. Confirm `/healthz` reports the new application version and that original records and sign-in still work.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
node tests/tracking_ui_smoke.cjs
node tests/export_ui_smoke.cjs
node tests/process_ui_smoke.cjs
```

The API suite creates isolated temporary databases and does not use a deployed `DATABASE_URL`. It covers the legacy workflow and individual-weld gates. The Node smoke harness uses synthetic fixtures to check routing, metrics, role controls, evidence rendering, and write payloads without contacting a service.

PostgreSQL verification covers additive initialization, history triggers, and concurrent writes. Its explicit local-test DSN guard rejects operational and remote database targets:

```bash
python tests/verify_postgres.py --help
```

See the developer guide before running that local check.

## Scope and limits

Evidence is a controlled report/reference or HTTP(S) link with notes; this version does not upload or store report files. Procedure and qualification applicability are reviewed by an authorized inspector using that evidence. The application does not calculate qualification ranges or choose governing acceptance criteria.

Add project-specific NDE, PMI, PWHT, hardness, coating, or other requirements from approved job documents. No universal NDE percentage is assumed. Pressure-test packages and shipment/delivery records are not modeled. Optional assembly links organize spools; releasing an assembly record checks its own welds and requirements, not the release of every linked child spool.

Badge/PIN sign-in and audit records are the current controls. PostgreSQL history triggers reject routine updates and deletes, but do not protect against a database owner deliberately removing those controls. Validate configured work and acceptance rules with the people responsible for the job before using them for fabrication release. This application is not a certification of compliance.
