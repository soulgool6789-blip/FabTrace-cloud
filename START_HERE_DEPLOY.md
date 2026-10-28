# FabTrace: put the real website online (Render)

This folder includes the **FabTrace Cloud Phone QR Fix** project plus an
updated `render.yaml` to create a web service and PostgreSQL database in
one Render Blueprint.

## Costs and production readiness

The Blueprint chooses paid starter-tier services by default so the database
does **not** expire after 30 days like Render Free PostgreSQL does. Review
Render's pricing in your own dashboard before you approve creation.
This is a PILOT/REFERENCE BUILD, NOT YET validated for production-quality
or safety-critical weld-release records. Quality criteria, access controls,
backups, electronic approvals and disaster recovery need validation.

## Shortest setup steps

1. Create or log into a GitHub account: https://github.com/
2. Create a **private** GitHub repository named `fabtrace-cloud`.
3. Upload the **contents** of this extracted deployment folder (including
   `render.yaml`, `main.py`, `static/index.html`, `init_db.py`,
   `requirements.txt`) to the root of the repository. Do not upload the ZIP
   itself, and never upload a `.env` file or credentials.
4. Create or log into Render: https://dashboard.render.com/
5. Choose **New > Blueprint**; connect GitHub and select the private repo.
6. Review the paid web+database services and charges. When prompted for
   environment variables, enter:
     BOOTSTRAP_BADGE = a unique admin badge ID, e.g. ADMIN-001
     BOOTSTRAP_PIN = a private random PIN/passphrase at least 12 characters.
   DO NOT SHARE THE PIN IN CHAT, QR CODES, OR YOUR GIT REPOSITORY.
7. Approve deployment. Render provisions a Postgres database, installs
   dependencies, initializes the schema in `preDeployCommand`, and starts
   FastAPI. A first deployment may fail if you enter a PIN shorter than
   12 characters; correct it in Render Environment and redeploy.
8. Render displays a live URL like `https://fabtrace-cloud-xxxx.onrender.com`.
   This is an EXAMPLE, not your URL. Open **your actual URL** from both
   computer and phone; visit `/healthz`, then log in with the bootstrap badge
   and PIN you created.
9. In FabTrace, add individual employee accounts, then parts/assemblies and
   Google part numbers. Generate an item QR and an employee badge QR. Scan
   them with your phone's regular camera and verify the destination.
10. Test one custody handoff from two separate devices. Inspect the item
    audit history. Only after validation, print labels for real production.

## QR code details

Part QR: `<YOUR_REAL_HTTPS_URL>/?item=FAB-00001`
Employee badge QR: `<YOUR_REAL_HTTPS_URL>/?badge=EMP-1042`

The application automatically uses Render's `RENDER_EXTERNAL_URL` if
`PUBLIC_BASE_URL` is unset. To use your own custom domain later, set
`PUBLIC_BASE_URL=https://your-domain.example` as a secret/environment
variable and redeploy, then replace any already printed QR labels if the
old hostname will stop working.

The QR never contains the employee PIN or confidential part data.
Employee badge scan identifies the recipient; actual account authentication
and signed acceptance are separate.

## Data from local desktop prototype

Local-browser storage is NOT automatically migrated to PostgreSQL.
Register employees and parts in the cloud or use the CSV bulk importer for
Google part numbers. A JSON backup from the HTML demo is NOT a direct
database restore format.

## What to do if deployment fails

- Check Render **Events** and **Logs** on the web service.
- `DATABASE_URL` comes from the Blueprint's linked Postgres database.
- `JWT_SECRET` is generated automatically; do not overwrite with a weak value.
- `BOOTSTRAP_PIN` must be at least 12 characters for first initialization.
- The web service needs a paid plan for `preDeployCommand`. Do not switch
  it to Free without also changing the initialization workflow.
- Verify `GET /healthz` returns a successful status.
- QR `/api/qr/status` should report `ready:true` after signing in; this
  checks URL configuration, not that the site is accessible from your phone.

## Required security and quality follow-up

Before using real customer's fabrication acceptance records: verify employer
access policies, backup/restore exercises, independent QC approvals,
approved dimensional tolerances and weld procedures, report attachments,
per-weld traceability, multifactor QC sign-off, incident response, offsite
audit archive, and retest of all release gates. App currently has simple
badge/PIN sessions and audit inserts, not a certified quality system.

Official hosting references:
- https://render.com/docs/blueprint-spec
- https://render.com/docs/deploy-fastapi
- https://render.com/docs/environment-variables
- https://render.com/docs/free
