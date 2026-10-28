# Deploy or update FabTrace Cloud on Render

## Update the existing FabTrace service first

**Use the existing web service and its existing PostgreSQL database.** Adding project, spool, and individual-weld tracking does not require creating a second service, a second database, or a new Blueprint.

1. Identify the current service's connected repository/branch and keep its existing `DATABASE_URL`, `JWT_SECRET`, public URL, and employee accounts. Make the normal database recovery point for the rollout.
2. Update the service with the complete reviewed source. Include `main.py`, **`tracking.py`**, `init_db.py`, `requirements.txt`, **`static/index.html`**, **`static/tracking.js`**, **`static/tracking.css`**, and the existing static assets. The root `index.html` is a distribution copy; the application serves `static/index.html`.
3. Confirm the service's initialization step is **`python init_db.py`**. The supplied `render.yaml` sets this as `preDeployCommand`, but uploading a YAML file alone does not change an independently configured existing service.
4. Run initialization before the new version accepts requests. Use the configured pre-deploy command, or a controlled manual step running the new `init_db.py` with the existing database settings. Keep the previous application serving until initialization succeeds, or use the service's maintenance procedure. Do not start the new app against an uninitialized schema.
5. Deploy with the existing start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
6. Check `/healthz`. It must return `status: "ok"`, the tracking application version, and the deployment commit when Render supplies it. Health checks now confirm the tracking plan table is available as well as the database connection.
7. Sign in with an existing employee account. Confirm existing item, QR, custody, and inspection records are still available. The navigation should include **Projects & welds**.
8. Follow [TRACKING_GUIDE.md](TRACKING_GUIDE.md) to create a project and explicitly enroll an intended spool. New projects and accepted welds are not seeded by deployment.

### What initialization changes

`init_db.py` adds absent tables, installs PostgreSQL protection against updates/deletes on six history tables, and creates a bootstrap administrator only when the employee table is empty. PostgreSQL setup is transactional and serialized with an advisory lock. Existing employee and item records are retained; no automatic spool enrollment occurs.

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

This release stores evidence references/URLs, not uploaded reports. Qualification applicability and job-specific acceptance criteria remain reviewed decisions. Assembly links organize records; shipment, pressure-test packages, and collective release of linked children are separate future features. Use the workflow and developer guides to configure and extend those boundaries deliberately.
