# Deploy or update FabTrace Cloud on Render

## Update the existing FabTrace service first

**Use the existing web service and its existing PostgreSQL database.** Adding project, spool, and individual-weld tracking does not require creating a second service, a second database, or a new Blueprint.

1. Identify the current service's connected repository/branch and keep its existing `DATABASE_URL`, `JWT_SECRET`, public URL, and employee accounts. Make the normal database recovery point for the rollout.
2. Update the service with the complete reviewed source. Include `main.py`, **`tracking.py`**, **`production.py`**, **`flow.py`**, **`quality.py`**, **`quality_templates.py`**, **`dossier.py`**, **`dossier_templates.py`**, **`progress.py`**, **`exports.py`**, `init_db.py`, `requirements.txt`, **`static/index.html`**, the **tracking, flow, quality, progress and dossier JavaScript/CSS** under `static/`, and the existing static assets. The root `index.html` is a distribution copy; the application serves `static/index.html`.
3. Confirm the service's initialization step is **`python init_db.py`**. The supplied `render.yaml` sets this as `preDeployCommand`, but uploading a YAML file alone does not change an independently configured existing service.
4. Run initialization before the new version accepts requests. Use the configured pre-deploy command, or a controlled manual step running the new `init_db.py` with the existing database settings. Keep the previous application serving until initialization succeeds, or use the service's maintenance procedure. Do not start the new app against an uninitialized schema.
5. Deploy with the existing start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
6. Check `/healthz`. It must return `status: "ok"`, the current application version, and the deployment commit when Render supplies it. Health checks confirm the weld tracking plan, production process event, numbered flow plan, quality workspace and dossier project/issue tables are available as well as the database connection.
7. Sign in with an existing employee account. Confirm existing item, QR, custody, and inspection records are still available. The navigation should include **Projects & welds**, **Process flow**, **Audit readiness**, **Project progress** and **Job Packets**.
8. Follow [TRACKING_GUIDE.md](TRACKING_GUIDE.md) to create a project and explicitly enroll an intended spool. New projects and accepted welds are not seeded by deployment.

### What initialization changes

`init_db.py` adds absent tables, installs PostgreSQL protection against updates/deletes on eighteen history/file tables, and creates a bootstrap administrator only when the employee table is empty. PostgreSQL setup is transactional and serialized with an advisory lock. Existing employee and item records are retained; no automatic spool/traveler enrollment or process-time history is invented. The audit-readiness release adds seven quality tables and protects immutable document revisions, evidence, reviews and events. It does not alter existing table columns. No audit workspace, approved source, evidence or completed activity is seeded during deployment; users explicitly create draft workspaces after sign-in.

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
