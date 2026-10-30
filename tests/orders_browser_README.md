# Purchase-order browser smoke test

`orders_browser_smoke.cjs` exercises the actual website and API with synthetic
records: PO creation, GPN and assembly registration, spool linking, BOM editing,
scoped Excel downloads, leading-zero identifiers, mobile layout, conflicting
edits, assembly traveler counts, role restrictions, and item QR deep links.

## 1. Start the isolated fixture

From the repository root, in terminal 1:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python tests/orders_browser_server.py
```

Wait for `Synthetic orders fixture: http://127.0.0.1:8782`.

The fixture always creates a new database inside a temporary directory. It
overrides inherited `DATABASE_URL`, JWT secret, cookie setting, and public URL
before importing the application. It accepts no host or database arguments and
binds only to `127.0.0.1:8782`. Its synthetic QR target uses the reserved
`fabtrace-training.example` domain. Never configure a deployed service to run it.

It seeds the roles and badges from `tests/conftest.py`, including `TEST-ADMIN`,
`TEST-QA`, and `TEST-HANDLER`. Their shared synthetic PIN is
`only-for-local-tests-12345`, also used by the browser test. These are local test
accounts, not production credentials. Stop the fixture with Ctrl+C when done;
its temporary database is then deleted. If port 8782 is busy, stop the other
local fixture before starting this one.

## 2. Install a test browser and run

From the same repository root, in terminal 2, with Node.js/npm installed:

```bash
FABTRACE_BROWSER_TOOLS=$(mktemp -d /tmp/fabtrace-browser-tools.XXXXXX)
npm install --prefix "$FABTRACE_BROWSER_TOOLS" playwright@1.62.1
export PLAYWRIGHT_MODULE="$FABTRACE_BROWSER_TOOLS/node_modules/playwright"
export PLAYWRIGHT_BROWSERS_PATH="$FABTRACE_BROWSER_TOOLS/browsers"
node "$PLAYWRIGHT_MODULE/cli.js" install chromium --only-shell
PYTHON="$PWD/.venv/bin/python" \
  ORDERS_TEST_OUT=/tmp/fabtrace-orders-browser-review \
  node tests/orders_browser_smoke.cjs
```

If Playwright is already installed, set `PLAYWRIGHT_MODULE` to its installed
module directory instead. To use an existing compatible Chromium/headless-shell
binary, set `CHROMIUM_EXECUTABLE` to its absolute executable path and skip the
browser installation command. The browser also needs its usual system libraries.

The test defaults to `http://127.0.0.1:8782` and rejects remote hosts. It writes
synthetic records, so use only the fixture above. Successful output has
`"status": "passed"` and an empty `page_errors` list. Screenshots, downloaded BOM
workbooks, and `report.json` are saved in `ORDERS_TEST_OUT`; on failure the folder
also receives `failure.json` and `failure.png`. Use a new output directory for
each run when retaining historical results. No production browser account,
database, or credentials are needed.
