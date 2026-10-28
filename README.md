# FabTrace Cloud — deployable reference implementation

FastAPI + PostgreSQL web application for multi-user fabrication item traceability. No user or account is provisioned outside your own deployment.

## Features
- Shared SQL database for unlimited item IDs (subject to host resources), searchable UI and QR PNG labels.
- Badge + Argon2-hashed private PIN; authenticated HttpOnly cookie; supervisor/inspector/welder/handler/admin roles.
- Chain-of-custody transfers; completed and required weld counts; inspection measurements and reports; rework closeout requiring new inspection; final quality release checks.
- Transactional writes, server UTC timestamps, row-level item locking and append-only audit events with Postgres update/delete prevention triggers.
- Roles: admin creates employees; admin/supervisor creates parts; handler/welder/supervisor/admin transfers; welder/supervisor/admin logs welds; inspector/supervisor/admin records inspections; inspector/admin approves release (same person should not fabricate and release under shop policy).

## Local PostgreSQL setup
1. Create a PostgreSQL database/user, e.g. `fabtrace` with password.
2. `python -m venv .venv` and activate it.
3. `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and load its values in your shell or your process manager (Python does NOT auto-load `.env`). Set all secrets and your public URL.
5. `python init_db.py` — creates schema and a bootstrap admin badge/PIN **only on first run**.
6. `uvicorn main:app --reload` then visit `http://localhost:8000`.
7. Log in using the bootstrap admin badge/PIN, create individual employee accounts, and **rotate the bootstrap credentials** through the employees API or disable that account once other admins exist.

## Render deployment
1. Create a Render managed PostgreSQL database; copy its connection URL and convert protocol to `postgresql+psycopg://` if necessary.
2. Push this folder to a **private** Git repository. Create a Render Python web service from it. Build command: `pip install -r requirements.txt`; start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
3. Set `DATABASE_URL`, `JWT_SECRET`, `BOOTSTRAP_BADGE`, `BOOTSTRAP_PIN`, `COOKIE_SECURE=true`, and `PUBLIC_BASE_URL=https://your-service.onrender.com` in Render environment settings. **Never commit secrets.**
4. Run `python init_db.py` as a one-time deployment/job step **before accepting traffic**. The app deliberately does not auto-initialize production database tables on every request.
5. Check `/healthz`, open the web URL, log in as bootstrap admin and add employees. Print QR labels from the item record.
6. Enable database backups, restore drills, monitored logging, TLS, domain restrictions, and a tested migration process before operational use. Protect admin credentials using a secret manager. Use staging for testing.

## API endpoints
- `POST /api/login` badge + PIN; `POST /api/logout`; `GET /api/me`.
- `GET /api/items?search=...`, `POST /api/items`, `GET /api/items/{item_id}`.
- `POST /api/items/{item_id}/transfer`, `/weld`, `/inspect`, `/rework`, `/rework/{rework_id}/close`, `/release`, `/reopen`.
- `POST /api/items/{item_id}/scan` (audited), `GET /api/items/{item_id}/qr.png`; `GET /api/items/{item_id}/audit`.
- `GET /api/audit` restricted to inspector/admin/supervisor; `GET /api/employees` and `POST /api/employees` admin only.
- `GET /healthz` health endpoint.

## QR strategy
Each QR encodes `https://YOUR-DOMAIN.example/?item=FAB-000001`; no employee identity, PIN, customer info, private tokens or changeable location is embedded. Labels remain stable when the item moves. On scanning the URL, the app opens the record and requires authenticated login before revealing details. Server records are the single source of truth.

## Release quality gates (server enforced)
Required weld count must be met, latest dimensional and weld inspection must independently PASS **after the latest weld/rework action**, no rework may remain open, no pending reinspection, item must not be held, and an inspector/admin must perform release with an explicit reference. Weld/inspection modifications on a released item are refused; authorized admin reopening is audited.

## Security limitations / production hardening checklist
**Reference implementation, not yet validated for regulated or safety-critical production.** Badge + PIN provides basic user identity but does not meet strong MFA or nonrepudiation by itself. Implement organization SSO/MFA for privileged QC approvals; validate segregation-of-duties; enforce credential lockout/rate limits using shared Redis/reverse proxy (this sample uses simple in-process throttling), device/workstation checks, password rotation, operational access review and lost-badge response.

Add CSRF tokens or strict origin validation to cookie-auth mutations (this implementation enforces same-origin Origin header when present and SameSite=strict cookies), strict production CSP, secure deployment/monitoring, database role separation, WORM/offsite audit archive, encryption and retention policies, secrets rotation, automated DB migrations, backup restore tests, load tests and shop-specific acceptance criteria. The append-only Postgres trigger blocks ordinary UPDATE/DELETE to audit rows, **not** modification by DB superusers/owners; it is not cryptographic nonrepudiation. Validate quality rules against governing codes and contracts; add per-weld maps, calibrated instrument IDs, actual measured dimensions and tolerances, NDE reports and approval signatures before calling it a regulated quality record system.

Do not expose a public production application until these controls have been evaluated.

## Scan-to-transfer and employee QR badges (updated October 28, 2026)

The cloud source now supports scanning an item's QR label and a receiving employee's badge QR to perform a controlled custody transfer.

**Set up employee badges**

1. An administrator signs in and opens **Employees**.
2. Register the employee with a unique badge ID, name, role, and *private* PIN (minimum 8 characters). Do not print the PIN.
3. Click **Print employee QR badge** next to that active employee. The QR payload is `FABTRACE:EMP:<badge-id>`. This is identity data only, **not** a credential or authenticated acceptance.

**Run a handoff**

1. A handler, welder, supervisor, or administrator signs into the hosted FabTrace app with their own employee badge ID and PIN.
2. Open **Scan & Handoff**. Scan or enter the item's QR/ID; the app retrieves the shared record and shows current holder and location.
3. Scan the receiving employee's QR badge (or enter their badge ID); the server confirms it maps to an active employee.
4. Set the new location, enter any handoff notes, and click **Confirm custody transfer**.
5. The backend records the previous handler and location, receiving handler and location, the authenticated operator, server timestamp, notes, and the stated scan method. See the **Custody handoffs** section in the item record.

On HTTPS/localhost the **Scan with camera** buttons use `html5-qrcode` loaded from a public CDN. USB/Bluetooth QR barcode readers work by focusing a text field and scanning, even without camera permission. For restrictive factory networks, self-host the camera-scanning dependency and test camera permissions on your selected devices.

The backend exposes `GET /api/employees/directory` to authenticated employees (active name/badge/role only), `GET /api/employees/{badge}/qr.png` to administrators, and `GET /api/items/{id}/custody` to authenticated employees. `POST /api/items/{id}/transfer` retains its `location`, `handler`, and `notes` inputs and now optionally supports `expected_handler` and `scan_method`. Handoffs fail if the item has been released, recipient is missing or inactive, or an `expected_handler` no longer matches the current record.

**Cautions:** A QR badge is not a login or proof the recipient physically accepted an item. The transfer records the authenticated user's statement. Add explicit receiving-person reauthentication or electronic acknowledgement if your quality procedure requires positive receipt acceptance. `scan_method` is supplied by the client and cannot cryptographically prove the physical scan occurred. The append-only audit database trigger described elsewhere is necessary but not sufficient for immutable retention; deploy off-site log archival, backups, RBAC reviews and routine restorations. This source is a deployable starting point, not a certified or tested production quality management system.

**Local demonstration alternative:** `fabtrace_qr_handoff.html` is a single-browser prototype for trying QR badge handoffs without a database. It shares its browser-local records with previous FabTrace prototype versions if opened from the same browser storage origin. It does not synchronize records between phones or computers.


## Phone camera QR fix (October 28, 2026)

**Why earlier QR labels showed “No usable data”:** they encoded bare item IDs or custom `FABTRACE:EMP:` badge IDs, which are not web links recognized by some default phone camera applications.

**Fix:** Both part and employee badge QR codes now encode full HTTPS URLs. For example:

- Part label: `https://YOUR-DEPLOYED-APP.example/?item=FAB-00001`
- Employee badge: `https://YOUR-DEPLOYED-APP.example/?badge=EMP-1042`

These are **examples, not real accessible addresses**. The login page is shown if the user is not signed in. After sign-in, part links open their record; badge links open Scan & Handoff and preselect the recipient. On the part page, the **Handoff with phone camera** action saves a short-lived part ID hint in that browser profile; scanning the badge with the normal camera subsequently selects the recipient. If the camera opens a different browser/profile, enter/scan the part in Scan & Handoff instead. An employee badge does not authenticate or prove acceptance.

**Critical configuration:** deploy first, populate your shared PostgreSQL data and employee accounts, and set `PUBLIC_BASE_URL` to the real **public HTTPS site URL** (no trailing paths, not localhost, e.g. `https://fabtrace-yourcompany.onrender.com`). Restart/redeploy. The app now **disables QR printing** until a valid public HTTPS URL is configured. Do not print QRs before deployment; make sure the URL actually resolves from a separate phone on cellular data, and test login and item lookup. QR images printed earlier must be regenerated and replaced.

Test: open `/api/qr/status` while logged in. `ready:true` only verifies the configured URL's shape, **not that your DNS, HTTPS certificate, firewall, and actual data are working**; always scan a sample on the target phone before bulk printing.
