/* Focused Materials & QA/QC counterpart to the saved BOM Pass/PASS ALL tests. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.ORDERS_TEST_BASE || 'http://127.0.0.1:8782';
const OUT = process.env.MATERIAL_PASS_ALL_TEST_OUT || '/tmp/fabtrace-material-pass-all-review';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(BASE).hostname), 'Disposable loopback fixture only');
fs.mkdirSync(OUT, {recursive: true});
const checks = [], errors = [], writes = [];
let browser, page, stage = 'launch';

(async () => {
  browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  const admin = await browser.newContext(), context = await browser.newContext({viewport: {width: 1440, height: 1050}});
  await context.route('https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js',
    route => route.fulfill({status: 200, contentType: 'application/javascript', body: ''}));
  const json = async response => { assert.ok(response.ok(), await response.text()); return response.json(); };
  const login = async (ctx, badge) => json(await ctx.request.post(BASE + '/api/login', {
    data: {badge, pin: 'only-for-local-tests-12345'}
  }));
  await login(admin, 'TEST-ADMIN'); await login(context, 'TEST-QA');
  const api = async (method, url, data) => json(await admin.request[method](BASE + url, data ? {data} : undefined));
  const physical = id => api('get', '/api/spool-boms/spools/' + id);
  const editable = ['piece_key', 'supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes'];
  const setMaterials = async (id, change) => {
    const current = await physical(id);
    return api('put', '/api/spool-boms/spools/' + id + '/traceability', {
      expected_version: current.traceability.version, expected_bom_sha256: current.source_status.expected_bom_sha256,
      reason: 'Synthetic Materials dialog evidence verification',
      materials: current.traceability.materials.map((piece, index) => ({
        ...Object.fromEntries(editable.map(field => [field, piece[field] || ''])), ...change(piece, index)
      }))
    });
  };
  page = await context.newPage(); page.setDefaultTimeout(18000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (['PUT', 'POST'].includes(request.method()) && /\/api\/spool-boms\/spools\//.test(request.url()))
      writes.push({url: request.url(), method: request.method(), data: request.postDataJSON()});
  });
  const row = key => page.locator('[data-fbom-record="' + key + '"]');
  const action = name => page.locator('#spoolBomDialog [data-fbom-action="' + name + '"]');
  const settle = () => page.locator('#spoolBomContent[aria-busy="false"]').waitFor();
  const open = async id => {
    await page.goto(BASE + '/?item=' + id);
    await page.locator('#itemPage:not(.hidden)').waitFor();
    await page.locator('#itemPage [data-spool-bom-url]').click(); await settle();
  };
  const chooseQa = async (key, result, reference, notes) => {
    await row(key).getByRole('radio', {name: result, exact: true}).check();
    await row(key).locator('[data-fbom-qa-field="reference"]').fill(reference);
    await row(key).locator('[data-fbom-qa-field="notes"]').fill(notes);
  };
  const write = async (suffix, click, status) => {
    const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith(suffix)
      && ['POST', 'PUT'].includes(r.request().method()));
    await click(); const response = await pending;
    assert.equal(response.status(), status, await response.text()); await settle(); return response.json();
  };
  const bulk = async (reference, notes) => {
    await action('qa-pass-all').click(); await page.locator('#fbomPassAllReference').fill(reference);
    await page.locator('#fbomPassAllNotes').fill(notes);
  };
  const saveBulk = (status = 200) => write('/materials/qa-001/pass-all', () => action('qa-confirm-pass-all').click(), status);
  const align = async target => target.evaluate(el => {
    const dialog = el.closest('dialog'), head = dialog.querySelector('.fbom-head');
    dialog.scrollTop += el.getBoundingClientRect().top - head.getBoundingClientRect().bottom - 10;
  });

  stage = 'synthetic shared BOM and two physical copies';
  const setup = await api('post', '/api/order-setup', {expected_version: 0, purchase_order: 'MATERIAL-PASS-' + Date.now(),
    assemblies: [{gpn: 'MATERIAL-PASS-ASM', assembly_quantity: 1,
      spools: [{spool_number: '643-777-PCW-03-01', quantity_per_assembly: 2, welds_per_spool: 1}]}]});
  const project = setup.order.project_id, requirement = setup.assemblies[0].spools[0].id;
  await api('post', '/api/order-labels/' + project + '/generate', {expected_version: setup.order.version,
    kind: 'Spool', location: 'Receiving', handler: 'TEST-HANDLER'});
  const labels = await api('get', '/api/order-labels/' + project + '/labels'), [first, second] = labels.items.map(item => item.id);
  const documentUrl = BASE + '/api/spool-documents/requirements/' + requirement;
  const current = await json(await admin.request.get(documentUrl));
  const file = {name: 'material-dialog-pieces.csv', mimeType: 'text/csv', buffer: Buffer.from(
    'item,quantity,unit,part_number,description,material,length\r\n1,2,EA,100708,FLANGE,A105,\r\n2,1,EA,102391,PIPE,A53B,16 3/4 in\r\n')};
  const preview = await json(await admin.request.post(documentUrl + '/preview', {multipart: {kind: 'bom', files: file}}));
  await json(await admin.request.post(documentUrl + '/upload', {multipart: {kind: 'bom', files: file,
    expected_version: String(current.version), expected_sha256: preview.selection_sha256,
    reason: 'Synthetic same-state Materials dialog QA source'}}));
  const initial = await physical(first), keys = initial.traceability.materials.map(piece => piece.piece_key);

  stage = 'actionable Pass and guarded combined save';
  await open(first);
  assert.equal(await row(keys[0]).getByRole('radio', {name: 'Pass', exact: true}).isDisabled(), false);
  await chooseQa(keys[0], 'Pass', '', '');
  assert.equal(await row(keys[0]).getByLabel('Inspection reference (optional)', {exact: true}).count(), 1);
  assert.equal(await row(keys[0]).getByLabel('Inspection notes (optional)', {exact: true}).count(), 1);
  assert.doesNotMatch(await row(keys[0]).innerText(), /failure reason/i);
  await chooseQa(keys[0], 'Fail', 'MATERIAL-FAIL-DRAFT', '');
  assert.equal(await row(keys[0]).getByLabel('Failure reason (required)', {exact: true}).count(), 1);
  const beforeInvalidFail = writes.length;
  await row(keys[0]).locator('[data-fbom-action="qa-save"]').click();
  assert.equal(writes.length, beforeInvalidFail);
  assert.match(await row(keys[0]).locator('[role="alert"]').innerText(), /failure reason/i);
  await chooseQa(keys[0], 'Pass', '', '');
  assert.equal(await row(keys[0]).getByLabel('Inspection notes (optional)', {exact: true}).count(), 1);
  assert.doesNotMatch(await row(keys[0]).innerText(), /failure reason/i);
  checks.push('Materials Pass uses optional inspection fields; selecting Fail exposes and enforces a failure reason, and switching back removes failure wording');
  assert.match(await row(keys[0]).locator('.fbom-piece-pass-blockers').innerText(), /heat/i);
  assert.match(await row(keys[0]).locator('.fbom-piece-pass-blockers').innerText(), /MTR/i);
  const beforeMissing = writes.length;
  await row(keys[0]).locator('[data-fbom-action="qa-save"]').click();
  assert.equal(writes.length, beforeMissing);
  await row(keys[1]).locator('[data-fbom-field="heat_number"]').fill('SIBLING-DRAFT-ONLY');
  await row(keys[0]).locator('[data-fbom-field="heat_number"]').fill('HEAT-MATERIAL-001');
  await row(keys[0]).locator('[data-fbom-field="mtr_reference"]').fill('MTR-MATERIAL-001');
  assert.match(await row(keys[0]).locator('[data-fbom-action="qa-save"]').innerText(), /Save material.*Pass/);
  const beforeCombined = writes.length;
  await write('/materials/' + keys[0] + '/qa-001', () => row(keys[0]).locator('[data-fbom-action="qa-save"]').click(), 201);
  const afterCombined = await physical(first);
  assert.deepEqual(afterCombined.traceability.materials.map(piece => piece.qa001.status), ['passed', 'pending', 'pending']);
  assert.equal(afterCombined.traceability.materials[0].heat_number, 'HEAT-MATERIAL-001');
  assert.equal(afterCombined.traceability.materials[0].qa001.latest.reference, '');
  assert.equal(afterCombined.traceability.materials[0].qa001.latest.notes, '');
  assert.equal(afterCombined.traceability.materials[0].qa001.latest.actor, 'TEST-QA');
  assert.ok(afterCombined.traceability.materials[0].qa001.latest.at);
  assert.equal(afterCombined.traceability.materials[1].heat_number, '');
  assert.equal(await row(keys[1]).locator('[data-fbom-field="heat_number"]').inputValue(), 'SIBLING-DRAFT-ONLY');
  assert.deepEqual(writes.slice(beforeCombined).map(write => write.method), ['PUT', 'POST']);
  assert.equal(writes[beforeCombined].data.qa001_guard.piece_key, keys[0]);
  assert.equal(writes[beforeCombined].data.qa001_guard.basis_sha256, initial.traceability.materials[0].qa001.basis_sha256);
  assert.ok((await physical(second)).traceability.materials.every(piece => piece.qa001.version === 0));
  checks.push('Materials & QA/QC offers actionable missing-evidence guidance and a guarded one-row material+Pass action that preserves sibling drafts and approvals');

  stage = 'the BOM page reads the same saved decision';
  await page.locator('#spoolBomClose').click();
  await page.locator('#itemPage [data-sdoc-kind="spools"]').click();
  await page.locator('#sdoc-tab-bom').click();
  await page.locator('#documentPieceQa[data-state="ready"]').waitFor();
  assert.equal(await page.locator('[data-dpqa-piece="' + keys[0] + '"] [data-dpqa-status]').getAttribute('data-dpqa-status'), 'passed');
  assert.equal(await page.locator('[data-dpqa-piece="' + keys[0] + '"] [data-dpqa-material="heat_number"]').inputValue(), 'HEAT-MATERIAL-001');
  await page.locator('#spoolDocumentsClose').click();
  await page.locator('#itemPage [data-spool-bom-url]').click(); await settle();
  assert.equal(await row(keys[1]).locator('[data-fbom-field="heat_number"]').inputValue(), 'SIBLING-DRAFT-ONLY');
  checks.push('Both entry points show the same persisted material and QA decision, while reopening Materials retains an unrelated unsaved draft');

  stage = 'batch missing evidence is explicit and blocks all writes';
  await row(keys[1]).locator('[data-fbom-field="heat_number"]').fill('');
  await bulk('MATERIAL-MISSING-BATCH', 'Missing rows must all be completed before a bulk decision.');
  assert.match(await page.locator('#fbomPassAll .fbom-bulk-blockers').innerText(), /002.*002|002 of 002/);
  assert.match(await page.locator('#fbomPassAll .fbom-bulk-blockers').innerText(), /Item 2/);
  assert.equal(await action('qa-confirm-pass-all').isDisabled(), true);
  assert.deepEqual((await physical(first)).traceability.materials.map(piece => piece.qa001.version), [1, 0, 0]);
  checks.push('Materials PASS ALL names each incomplete piece and blocks the whole batch, retaining the already-saved first-piece decision');

  stage = 'stale bulk reload and pending save protections';
  await setMaterials(first, (piece, index) => ({heat_number: piece.heat_number || 'HEAT-MATERIAL-' + (index + 1),
    mtr_reference: piece.mtr_reference || 'MTR-MATERIAL-' + (index + 1)}));
  await open(first);
  await bulk('MATERIAL-ALL-REVIEW', 'All three material pieces checked; preserve this review through conflicts.');
  await setMaterials(first, (piece, index) => ({heat_number: index === 2 ? 'HEAT-MATERIAL-CONCURRENT' : piece.heat_number}));
  await saveBulk(409);
  assert.equal(await page.locator('#fbomPassAllReference').inputValue(), 'MATERIAL-ALL-REVIEW');
  assert.equal(await page.locator('#fbomPassAllNotes').inputValue(), 'All three material pieces checked; preserve this review through conflicts.');
  assert.equal(await action('qa-confirm-pass-all').isDisabled(), true);
  assert.deepEqual((await physical(first)).traceability.materials.map(piece => piece.qa001.version), [1, 0, 0]);
  const reload = page.waitForResponse(r => new URL(r.url()).pathname === '/api/spool-boms/spools/' + first && r.request().method() === 'GET');
  await action('qa-reload-pass-all').click(); assert.equal((await reload).status(), 200); await settle();
  assert.equal(await page.locator('#fbomPassAllReference').inputValue(), 'MATERIAL-ALL-REVIEW');
  await align(page.locator('#fbomPassAll'));
  await page.screenshot({path: path.join(OUT, 'materials-pass-all-desktop.png')});
  await page.setViewportSize({width: 390, height: 844}); await align(page.locator('#fbomPassAll'));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  assert.ok(await page.locator('#spoolBomDialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await page.screenshot({path: path.join(OUT, 'materials-pass-all-mobile.png')});
  const bulkUrl = BASE + '/api/spool-boms/spools/' + first + '/materials/qa-001/pass-all';
  let release, seen;
  const held = new Promise(resolve => { release = resolve; }), requested = new Promise(resolve => { seen = resolve; });
  await page.route(bulkUrl, async route => { const response = await route.fetch(); seen(); await held; await route.fulfill({response}); });
  const pending = saveBulk(); await requested;
  try {
    for (const id of ['spoolBomClose', 'spoolBomDone', 'spoolBomBack']) assert.equal(await page.locator('#' + id).isDisabled(), true);
    assert.equal(await page.evaluate(() => window.FabSpoolBom.canNavigateAway()), false);
    assert.equal(await action('qa-confirm-pass-all').isDisabled(), true);
  } finally { release(); }
  const passed = await pending; await page.unroute(bulkUrl);
  assert.equal(passed.qa001_bulk_result.passed_count, 2);
  assert.equal(passed.qa001_bulk_result.already_passed_count, 1);
  assert.equal(new Set(passed.traceability.materials.map(piece => piece.qa001.latest.id)).size, 3);
  assert.equal(passed.arrival.can_proceed, false);
  assert.ok((await physical(second)).traceability.materials.every(piece => piece.qa001.version === 0));
  checks.push('A stale Materials batch rejects every new decision, retains findings through reload, then saves only outstanding pieces while blocking navigation and leaving sibling/arrival approvals unchanged');

  stage = 'concurrent QA blocks combined material write before partial changes';
  await page.setViewportSize({width: 1440, height: 1050}); await open(second);
  const other = await physical(second), otherKey = other.traceability.materials[0].piece_key;
  await chooseQa(otherKey, 'Pass', 'MATERIAL-STALE-SINGLE', 'Preserve these findings after a concurrent inspector decision.');
  await row(otherKey).locator('[data-fbom-field="heat_number"]').fill('HEAT-STALE-DRAFT');
  await row(otherKey).locator('[data-fbom-field="mtr_reference"]').fill('MTR-STALE-DRAFT');
  const piece = other.traceability.materials[0];
  await api('post', '/api/spool-boms/spools/' + second + '/materials/' + otherKey + '/qa-001', {
    expected_version: piece.qa001.version, basis_sha256: piece.qa001.basis_sha256, result: 'Fail',
    reference: 'MATERIAL-CONCURRENT-FAIL', notes: 'A second inspector found missing evidence before the draft was saved.'
  });
  const beforeConflict = writes.length;
  await write('/traceability', () => row(otherKey).locator('[data-fbom-action="qa-save"]').click(), 409);
  const untouched = await physical(second);
  assert.equal(untouched.traceability.version, other.traceability.version);
  assert.equal(untouched.traceability.materials[0].heat_number, '');
  assert.equal(untouched.traceability.materials[0].mtr_reference, '');
  assert.equal(untouched.traceability.materials[0].qa001.status, 'failed');
  assert.deepEqual(writes.slice(beforeConflict).map(write => write.method), ['PUT']);
  assert.equal(await row(otherKey).locator('[data-fbom-qa-field="reference"]').inputValue(), 'MATERIAL-STALE-SINGLE');
  assert.equal(await row(otherKey).locator('[data-fbom-qa-field="notes"]').inputValue(), 'Preserve these findings after a concurrent inspector decision.');
  assert.equal(await row(otherKey).locator('[data-fbom-field="heat_number"]').inputValue(), 'HEAT-STALE-DRAFT');
  assert.equal(await row(otherKey).locator('[data-fbom-action="qa-save"]').isDisabled(), true);
  checks.push('A concurrent inspector decision makes the combined action fail before any material write; the prior Fail stays current and the user’s material and inspection drafts survive');

  stage = 'Materials PASS ALL accepts blank supplementary details';
  await setMaterials(second, (_piece, index) => ({heat_number: 'HEAT-BLANK-ALL-' + index,
    mtr_reference: 'MTR-BLANK-ALL-' + index}));
  await open(second); await bulk('', '');
  assert.match(await page.locator('#fbomPassAll').innerText(), /optional/i);
  assert.doesNotMatch(await page.locator('#fbomPassAll').innerText(), /failure reason/i);
  const blankBatch = await saveBulk();
  assert.equal(blankBatch.qa001_bulk_result.passed_count, 3);
  assert.ok(blankBatch.traceability.materials.every(piece => piece.qa001.latest.reference === ''
    && piece.qa001.latest.notes === '' && piece.qa001.latest.actor === 'TEST-QA' && piece.qa001.latest.at));
  assert.equal(new Set(blankBatch.traceability.materials.map(piece => piece.qa001.latest.id)).size, 3);
  checks.push('Materials PASS ALL accepts blank optional notes/reference and saves a separate attributable decision for every piece');

  stage = 'arrival Pass optional fields retain checklist gate';
  await action('inspection-panel').click();
  await page.locator('#spoolArrivalResult').selectOption('Pass');
  assert.equal(await page.getByLabel('Inspection reference (optional)', {exact: true}).count(), 1);
  assert.equal(await page.getByLabel('Inspection notes (optional)', {exact: true}).count(), 1);
  assert.doesNotMatch(await page.locator('#spoolArrivalForm').innerText(), /failure reason/i);
  const beforeChecklist = writes.length;
  await page.locator('#spoolArrivalSave').click();
  assert.equal(writes.length, beforeChecklist);
  assert.match(await page.locator('#spoolBomContent [role="alert"]').innerText(), /every arrival check/i);
  await page.locator('#spoolArrivalResult').selectOption('Fail');
  assert.equal(await page.getByLabel('Failure reason (required)', {exact: true}).count(), 1);
  await page.locator('#spoolArrivalReference').fill('ARRIVAL-FAIL-DRAFT');
  await page.locator('#spoolArrivalSave').click();
  assert.equal(writes.length, beforeChecklist);
  assert.match(await page.locator('#spoolBomContent [role="alert"]').innerText(), /failure reason/i);
  await page.locator('#spoolArrivalResult').selectOption('Pass');
  await page.locator('#spoolArrivalReference').fill('');
  for (const box of await page.locator('[data-fbom-check]').all()) await box.check();
  const arrived = await write('/arrival-inspections', () => page.locator('#spoolArrivalSave').click(), 201);
  assert.equal(arrived.arrival.status, 'passed');
  assert.equal(arrived.arrival.latest.reference, '');
  assert.equal(arrived.arrival.latest.notes, '');
  assert.equal(arrived.arrival.latest.actor, 'TEST-QA');
  assert.ok(arrived.arrival.latest.at);
  checks.push('Arrival Pass accepts blank supplementary fields only after all checks; Fail still requires a failure reason and each result shows the matching labels');

  stage = 'read-only Materials controls';
  await login(context, 'TEST-WELDER'); await open(first);
  assert.equal(await page.locator('#spoolBomDialog input[data-fbom-qa-result]:enabled').count(), 0);
  for (const control of await action('qa-pass-all').all()) assert.equal(await control.isDisabled(), true);
  checks.push('Read-only Materials access exposes neither an enabled single-piece approval nor an enabled PASS ALL action');
  assert.deepEqual(errors, []);
  const report = {status: 'passed', groups: checks.length, checks, page_errors: errors, spool_ids: [first, second], artifacts: OUT};
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  fs.rmSync(path.join(OUT, 'failure.json'), {force: true}); console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch(async error => {
  console.error('FAILED', stage, error.stack || error);
  if (page) await page.screenshot({path: path.join(OUT, 'failure.png'), fullPage: true}).catch(() => {});
  fs.writeFileSync(path.join(OUT, 'failure.json'), JSON.stringify({stage, error: error.message, page_errors: errors}, null, 2));
  if (browser) await browser.close(); process.exitCode = 1;
});
