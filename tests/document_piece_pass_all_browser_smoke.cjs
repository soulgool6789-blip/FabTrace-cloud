/* Actionable Pass, naturally sorted physical copies and atomic PASS ALL.
 * Requires only tests/orders_browser_server.py's disposable loopback fixture. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.ORDERS_TEST_BASE || 'http://127.0.0.1:8782';
const OUT = process.env.DOCUMENT_PASS_ALL_TEST_OUT || '/tmp/fabtrace-pass-all-review';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(BASE).hostname), 'Fresh loopback fixture only');
fs.mkdirSync(OUT, {recursive: true});
const checks = [], errors = [], writes = [];
const number = '643-777-PCW-03-01', run = Date.now().toString(36);
let browser, page, stage = 'launch';

(async () => {
  browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  const admin = await browser.newContext();
  const context = await browser.newContext({viewport: {width: 1440, height: 1050}});
  await context.route('https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js',
    route => route.fulfill({status: 200, contentType: 'application/javascript', body: ''}));
  const json = async response => { assert.ok(response.ok(), await response.text()); return response.json(); };
  const login = async (ctx, badge) => json(await ctx.request.post(BASE + '/api/login', {
    data: {badge, pin: 'only-for-local-tests-12345'}
  }));
  await login(admin, 'TEST-ADMIN');
  await login(context, 'TEST-QA');
  const api = async (method, url, data) => json(await admin.request[method](BASE + url, data ? {data} : undefined));
  const physical = id => api('get', '/api/spool-boms/spools/' + id);
  const summary = detail => detail.traceability.materials.map(piece => ({
    key: piece.piece_key, status: piece.qa001.status, version: piece.qa001.version,
    event: piece.qa001.latest?.id || null, heat: piece.heat_number, mtr: piece.mtr_reference
  }));
  const bulkBody = (detail, reference, notes) => ({
    expected_trace_version: detail.traceability.version,
    expected_bom_sha256: detail.source_status.expected_bom_sha256,
    reference, notes,
    pieces: detail.traceability.materials.map(piece => ({piece_key: piece.piece_key,
      expected_version: piece.qa001.version, basis_sha256: piece.qa001.basis_sha256}))
  });
  const materialFields = ['piece_key', 'supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes'];
  const setMaterials = async (id, change) => {
    const detail = await physical(id);
    return api('put', '/api/spool-boms/spools/' + id + '/traceability', {
      expected_version: detail.traceability.version,
      expected_bom_sha256: detail.source_status.expected_bom_sha256,
      reason: 'Synthetic exact physical material setup for PASS ALL verification',
      materials: detail.traceability.materials.map((piece, index) => ({
        ...Object.fromEntries(materialFields.map(field => [field, piece[field] || ''])), ...change(piece, index)
      }))
    });
  };
  page = await context.newPage();
  page.setDefaultTimeout(18000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (['POST', 'PUT'].includes(request.method()) && /\/api\/spool-boms\/spools\//.test(request.url()))
      writes.push({url: request.url(), method: request.method(), data: request.postDataJSON()});
  });
  const panel = () => page.locator('#documentPieceQa');
  const row = key => page.locator('[data-dpqa-piece="' + key + '"]');
  const settle = async () => {
    await page.locator('#spoolDocumentsContent[aria-busy="false"]').waitFor();
    await page.locator('#documentPieceQa[data-state="ready"][aria-busy="false"]').waitFor();
  };
  const chooseCopy = async id => {
    const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/material-records')
      && new URL(r.url()).searchParams.get('spool_id') === id);
    await page.locator('#dpqaSpoolSelect').selectOption(id);
    assert.equal((await pending).status(), 200);
    await settle();
  };
  const openShared = async (project, requirement) => {
    await page.goto(BASE + '/?order-setup=1&po=' + project);
    await page.locator('#orderSetupContent[aria-busy="false"]').waitFor();
    await page.locator('[data-sdoc-kind="requirements"][data-sdoc-id="' + requirement + '"]').click();
    await page.locator('#sdoc-tab-bom').click();
    await settle();
  };
  const openBulk = async (reference, notes) => {
    await panel().locator('[data-dpqa-action="pass-all"]').click();
    await page.locator('#dpqaPassAll').waitFor();
    await page.locator('#dpqaPassAllReference').fill(reference);
    await page.locator('#dpqaPassAllNotes').fill(notes);
  };
  const saveBulk = async (status = 200) => {
    const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/materials/qa-001/pass-all')
      && r.request().method() === 'POST');
    await page.locator('[data-dpqa-action="confirm-pass-all"]').click();
    const response = await pending;
    assert.equal(response.status(), status, await response.text());
    await settle();
    return response.json();
  };
  const align = async target => target.evaluate(el => {
    const dialog = el.closest('dialog'), head = dialog.querySelector('.sdoc-head');
    dialog.scrollTop += el.getBoundingClientRect().top - head.getBoundingClientRect().bottom - 12;
  });

  stage = '18 physical copies with random internal IDs';
  const setup = await api('post', '/api/order-setup', {
    expected_version: 0, purchase_order: 'PASS-ALL-UI-' + run,
    assemblies: [{gpn: 'PASS-ALL-ASM', assembly_number: 'TEST-PASS-ALL-001', assembly_quantity: 1,
      spools: [{spool_number: number, quantity_per_assembly: 18, welds_per_spool: 1}]}]
  });
  const project = setup.order.project_id, requirement = setup.assemblies[0].spools[0].id;
  await api('post', '/api/order-labels/' + project + '/generate', {
    expected_version: setup.order.version, kind: 'Spool', location: 'Receiving', handler: 'TEST-HANDLER'
  });
  const documentUrl = BASE + '/api/spool-documents/requirements/' + requirement;
  const currentDocument = await json(await admin.request.get(documentUrl));
  const file = {name: 'two-flanges-one-pipe.csv', mimeType: 'text/csv', buffer: Buffer.from(
    'item,quantity,unit,part_number,description,material,length\r\n'
    + '1,2,EA,100708,FLANGE,A105,\r\n2,1,EA,102391,PIPE,A53B,16 3/4 in\r\n')};
  const preview = await json(await admin.request.post(documentUrl + '/preview', {multipart: {kind: 'bom', files: file}}));
  await json(await admin.request.post(documentUrl + '/upload', {multipart: {
    kind: 'bom', files: file, expected_version: String(currentDocument.version),
    expected_sha256: preview.selection_sha256, reason: 'Synthetic PASS ALL source for this exact physical-copy test'
  }}));
  const labelResult = await api('get', '/api/order-labels/' + project + '/labels');
  const ordered = labelResult.items.slice().sort((a, b) => a.display_code.localeCompare(b.display_code, undefined, {numeric: true}));
  assert.equal(ordered.length, 18);
  assert.notDeepEqual(ordered.map(item => item.id), ordered.map(item => item.id).sort(), 'Fixture IDs must not accidentally match readable sequence order');
  const [first, second, third, fourth] = ordered.map(item => item.id);
  await openShared(project, requirement);
  const options = await page.locator('#dpqaSpoolSelect option').evaluateAll(elements => elements.filter(el => el.value).map(el => ({id: el.value, label: el.textContent.trim()})));
  assert.deepEqual(options.map(option => option.id), ordered.map(item => item.id));
  assert.deepEqual(options.map(option => option.label.match(/\[(\d+)\]$/)[1]), Array.from({length: 18}, (_, i) => String(i + 1).padStart(3, '0')));
  checks.push('All 18 physical choices show readable aliases in 001–018 order with their exact IDs, independently of random internal-ID order');

  stage = 'actionable Pass with missing material evidence';
  await chooseCopy(first);
  const firstInitial = await physical(first), keys = firstInitial.traceability.materials.map(piece => piece.piece_key);
  assert.equal(keys.length, 3);
  assert.equal(await row(keys[0]).getByRole('radio', {name: 'Pass', exact: true}).isDisabled(), false);
  await row(keys[0]).getByRole('radio', {name: 'Pass', exact: true}).check();
  assert.equal(await row(keys[0]).locator('[data-dpqa-missing="heat_number"]').count(), 1);
  assert.equal(await row(keys[0]).locator('[data-dpqa-missing="mtr_reference"]').count(), 1);
  assert.equal(await row(keys[0]).getByLabel('Inspection reference (optional)', {exact: true}).count(), 1);
  assert.equal(await row(keys[0]).getByLabel('Inspection notes (optional)', {exact: true}).count(), 1);
  assert.doesNotMatch(await row(keys[0]).innerText(), /failure reason/i);
  await row(keys[0]).getByRole('radio', {name: 'Fail', exact: true}).check();
  assert.equal(await row(keys[0]).getByLabel('Failure reason (required)', {exact: true}).count(), 1);
  const beforeInvalidFail = writes.length;
  await row(keys[0]).locator('[data-dpqa-field="reference"]').fill('QA-FAIL-DRAFT');
  await row(keys[0]).locator('[data-dpqa-action="save-qa"]').click();
  assert.equal(writes.length, beforeInvalidFail);
  assert.match(await row(keys[0]).locator('[role="alert"]').innerText(), /failure reason/i);
  await align(row(keys[0]).locator('.dpqa-qa'));
  await page.screenshot({path: path.join(OUT, 'fail-required-reason-desktop.png')});
  await row(keys[0]).locator('[data-dpqa-field="reference"]').fill('');
  await row(keys[0]).locator('[data-dpqa-field="notes"]').fill('A draft failure explanation');
  await row(keys[0]).locator('[data-dpqa-action="save-qa"]').click();
  assert.equal(writes.length, beforeInvalidFail);
  assert.match(await row(keys[0]).locator('[role="alert"]').innerText(), /reference/i);
  await row(keys[0]).getByRole('radio', {name: 'Pass', exact: true}).check();
  assert.equal(await row(keys[0]).getByLabel('Inspection notes (optional)', {exact: true}).count(), 1);
  assert.doesNotMatch(await row(keys[0]).innerText(), /failure reason/i);
  await row(keys[0]).locator('[data-dpqa-field="notes"]').fill('');
  checks.push('BOM Pass shows optional inspection reference/notes; toggling Fail requires its reference and failure reason without saving an invalid decision, then toggling back restores Pass labels');
  const beforeMissingWrites = writes.length;
  const initialSave = row(keys[0]).locator('[data-dpqa-action="save-qa"]');
  if (await initialSave.isEnabled()) await initialSave.click();
  assert.equal(writes.length, beforeMissingWrites);
  assert.equal((await physical(first)).traceability.materials[0].qa001.status, 'pending');
  assert.match(await row(keys[0]).locator('.dpqa-pass-blockers').innerText(), /heat/i);
  assert.match(await row(keys[0]).locator('.dpqa-pass-blockers').innerText(), /MTR/i);
  checks.push('Pass is selectable with missing evidence and exposes specific heat/MTR actions; it never records an approval while either required value is missing');

  stage = 'combined material save and one-piece Pass';
  await row(keys[1]).locator('[data-dpqa-material="heat_number"]').fill('UNSAVED-SIBLING-DRAFT');
  await row(keys[0]).locator('[data-dpqa-material="heat_number"]').fill('HEAT-FIRST-001');
  await row(keys[0]).locator('[data-dpqa-material="mtr_reference"]').fill('MTR-FIRST-001');
  assert.equal(await row(keys[0]).getByRole('radio', {name: 'Pass', exact: true}).isDisabled(), false);
  assert.match(await row(keys[0]).locator('[data-dpqa-action="save-qa"]').innerText(), /Save heat.*MTR.*Pass/);
  await align(row(keys[0]).locator('.dpqa-qa'));
  await page.screenshot({path: path.join(OUT, 'pass-optional-fields-desktop.png')});
  const beforeCombined = writes.length;
  const singleResponse = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/materials/' + keys[0] + '/qa-001')
    && r.request().method() === 'POST');
  await row(keys[0]).locator('[data-dpqa-action="save-qa"]').click();
  const single = await singleResponse;
  assert.equal(single.status(), 201, await single.text());
  await settle();
  const firstPassed = await physical(first);
  assert.deepEqual(firstPassed.traceability.materials.map(piece => piece.qa001.status), ['passed', 'pending', 'pending']);
  assert.equal(firstPassed.traceability.materials[0].heat_number, 'HEAT-FIRST-001');
  assert.equal(firstPassed.traceability.materials[0].qa001.latest.reference, '');
  assert.equal(firstPassed.traceability.materials[0].qa001.latest.notes, '');
  assert.equal(firstPassed.traceability.materials[0].qa001.latest.actor, 'TEST-QA');
  assert.ok(firstPassed.traceability.materials[0].qa001.latest.at);
  assert.equal(firstPassed.traceability.materials[1].heat_number, '');
  assert.equal(await row(keys[1]).locator('[data-dpqa-material="heat_number"]').inputValue(), 'UNSAVED-SIBLING-DRAFT');
  assert.deepEqual(writes.slice(beforeCombined).map(write => write.method), ['PUT', 'POST']);
  assert.equal(writes.at(-1).data.basis_sha256, firstPassed.traceability.materials[0].qa001.latest.basis_sha256);
  assert.equal(firstPassed.arrival.can_proceed, false);
  assert.ok((await physical(second)).traceability.materials.every(piece => piece.qa001.version === 0));
  checks.push('Save heat / MTR & Pass saves only the clicked row and then its fresh-basis QA decision, preserving an unsaved sibling draft and leaving all other approvals pending');

  stage = 'missing evidence blocks the entire batch';
  await row(keys[1]).locator('[data-dpqa-material="heat_number"]').fill('');
  await openBulk('QA-BATCH-MISSING', 'Attempt intentionally lacks the other two pieces’ evidence.');
  const blockers = page.locator('#dpqaPassAll .dpqa-bulk-blockers');
  assert.match(await blockers.innerText(), /002.*002|002 of 002/);
  assert.match(await blockers.innerText(), /Item 2/);
  assert.match(await blockers.innerText(), /heat/i);
  assert.match(await blockers.innerText(), /MTR/i);
  const firstBeforeBlocked = await physical(first), beforeBlockedWrites = writes.length;
  const blockedConfirm = page.locator('[data-dpqa-action="confirm-pass-all"]');
  if (await blockedConfirm.isEnabled()) await blockedConfirm.click();
  assert.equal(writes.length, beforeBlockedWrites);
  const blockedResponse = await context.request.post(BASE + '/api/spool-boms/spools/' + first + '/materials/qa-001/pass-all', {
    data: bulkBody(firstBeforeBlocked, 'QA-SERVER-BLOCK', 'Verify all-or-nothing rejection of incomplete material evidence.')
  });
  assert.equal(blockedResponse.status(), 409, await blockedResponse.text());
  const blockedData = await blockedResponse.json();
  assert.ok(blockedData.detail.piece_blockers.some(piece => piece.piece_key === keys[1]));
  assert.ok(blockedData.detail.piece_blockers.some(piece => piece.piece_key === keys[2]));
  assert.deepEqual(summary(await physical(first)), summary(firstBeforeBlocked));
  await align(page.locator('#dpqaPassAll'));
  await page.screenshot({path: path.join(OUT, 'pass-all-missing-evidence-desktop.png')});
  checks.push('PASS ALL lists the exact incomplete rows; both the UI and atomic API reject the whole batch with no new decisions or duplicated existing Pass');

  stage = 'atomic PASS ALL for one selected physical copy';
  await setMaterials(second, (_piece, index) => ({heat_number: 'HEAT-SECOND-' + (index + 1), mtr_reference: 'MTR-SECOND-' + (index + 1)}));
  await chooseCopy(second);
  const secondBefore = await physical(second), thirdBefore = await physical(third);
  await openBulk('', '');
  assert.match(await page.locator('#dpqaPassAll').innerText(), /optional/i);
  assert.doesNotMatch(await page.locator('#dpqaPassAll').innerText(), /failure reason/i);
  assert.equal(await page.locator('#dpqaPassAll .dpqa-bulk-blockers li').count(), 0);
  await align(page.locator('#dpqaPassAll'));
  await page.screenshot({path: path.join(OUT, 'pass-all-ready-desktop.png')});
  await page.setViewportSize({width: 390, height: 844});
  await align(page.locator('#dpqaPassAll'));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  assert.ok(await page.locator('#spoolDocumentsDialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await page.screenshot({path: path.join(OUT, 'pass-all-ready-mobile.png')});
  await page.setViewportSize({width: 1440, height: 1050});
  const batchUrl = BASE + '/api/spool-boms/spools/' + second + '/materials/qa-001/pass-all';
  let releaseResponse, seenResponse, heldPosts = 0;
  const held = new Promise(resolve => { releaseResponse = resolve; });
  const seen = new Promise(resolve => { seenResponse = resolve; });
  await page.route(batchUrl, async route => {
    heldPosts++;
    const actual = await route.fetch();
    seenResponse();
    await held;
    await route.fulfill({response: actual});
  });
  const batchPending = saveBulk();
  await seen;
  try {
    for (const id of ['spoolDocumentsClose', 'spoolDocumentsDone', 'spoolDocumentsBack'])
      assert.equal(await page.locator('#' + id).isDisabled(), true);
    for (const tab of await page.locator('#spoolDocumentsDialog [role="tab"]').all()) assert.equal(await tab.isDisabled(), true);
    assert.equal(await page.locator('#dpqaSpoolSelect').isDisabled(), true);
    assert.equal(await page.evaluate(() => window.FabSpoolDocuments.canNavigateAway()), false);
    const confirmation = page.locator('[data-dpqa-action="confirm-pass-all"]');
    assert.equal(await confirmation.isDisabled(), true);
    await confirmation.evaluate(button => button.click());
    assert.equal(heldPosts, 1);
  } finally { releaseResponse(); }
  const batch = await batchPending;
  await page.unroute(batchUrl);
  assert.equal(batch.qa001_bulk_result.spool_id, second);
  assert.equal(batch.qa001_bulk_result.passed_count, 3);
  assert.equal(batch.qa001_bulk_result.already_passed_count, 0);
  assert.equal(new Set(batch.traceability.materials.map(piece => piece.qa001.latest.id)).size, 3);
  assert.ok(batch.traceability.materials.every(piece => piece.qa001.status === 'passed' && piece.qa001.version === 1
    && piece.qa001.latest.reference === '' && piece.qa001.latest.notes === ''
    && piece.qa001.latest.actor === 'TEST-QA' && piece.qa001.latest.at && piece.qa001.latest.spool_id === second));
  assert.equal(batch.arrival.version, secondBefore.arrival.version);
  assert.equal(batch.arrival.can_proceed, false);
  assert.deepEqual(summary(await physical(first)), summary(firstBeforeBlocked));
  assert.deepEqual(summary(await physical(third)), summary(thirdBefore));
  checks.push('PASS ALL succeeds with blank optional notes/reference, records three distinct inspector/time-stamped decisions atomically on the selected copy, and leaves sibling copies and arrival unchanged');

  stage = 'already passed batch creates no duplicate history';
  const allPassed = await physical(second);
  const repeated = await json(await context.request.post(batchUrl, {
    data: bulkBody(allPassed, 'QA-NOOP-REVIEW', 'Current passing decisions must stay unchanged when already complete.')
  }));
  assert.equal(repeated.qa001_bulk_result.passed_count, 0);
  assert.equal(repeated.qa001_bulk_result.already_passed_count, 3);
  assert.deepEqual(summary(repeated), summary(allPassed));
  checks.push('Repeating PASS ALL on an already complete current register is a no-op and retains every original inspection record');

  stage = 'concurrent edit rejects all stale bulk decisions';
  await setMaterials(third, (_piece, index) => ({heat_number: 'HEAT-THIRD-' + (index + 1), mtr_reference: 'MTR-THIRD-' + (index + 1)}));
  await chooseCopy(third);
  await openBulk('QA-STALE-BATCH', 'Bulk findings retained while the changed evidence is reviewed.');
  const thirdLoaded = await physical(third);
  await setMaterials(third, (piece, index) => ({heat_number: index === 1 ? 'HEAT-THIRD-CONCURRENT' : piece.heat_number}));
  await saveBulk(409);
  const rejected = await physical(third);
  assert.ok(rejected.traceability.materials.every(piece => piece.qa001.version === 0 && piece.qa001.latest === null));
  assert.equal(await page.locator('#dpqaPassAllReference').inputValue(), 'QA-STALE-BATCH');
  assert.equal(await page.locator('#dpqaPassAllNotes').inputValue(), 'Bulk findings retained while the changed evidence is reviewed.');
  assert.equal(await page.locator('[data-dpqa-action="confirm-pass-all"]').isDisabled(), true);
  const reloaded = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/material-records')
    && new URL(r.url()).searchParams.get('spool_id') === third);
  await page.locator('[data-dpqa-action="reload-pass-all"]').click();
  assert.equal((await reloaded).status(), 200);
  await settle();
  assert.equal(await page.locator('#dpqaPassAllReference').inputValue(), 'QA-STALE-BATCH');
  assert.equal(await page.locator('#dpqaPassAllNotes').inputValue(), 'Bulk findings retained while the changed evidence is reviewed.');
  assert.equal(await row(thirdLoaded.traceability.materials[1].piece_key).locator('[data-dpqa-material="heat_number"]').inputValue(), 'HEAT-THIRD-CONCURRENT');
  const refreshedBatch = await saveBulk();
  assert.equal(refreshedBatch.qa001_bulk_result.passed_count, 3);
  assert.deepEqual(summary(await physical(second)), summary(allPassed));
  assert.ok((await physical(fourth)).traceability.materials.every(piece => piece.qa001.version === 0));
  checks.push('A concurrent material correction rejects the entire stale batch without partial approvals, retains common findings and requires explicit reload before the reviewed fresh batch can pass');

  stage = 'natural sorting handles unpadded 2 before 10';
  const sortingUrl = documentUrl + '/material-records';
  await page.route(sortingUrl, async route => {
    const response = await route.fetch(), value = await response.json();
    value.spools = value.spools.map((spool, index) => ({...spool, display_code: 'SYNTHETIC-SPOOL-' + (index + 1)})).reverse();
    await route.fulfill({response, json: value});
  });
  const beforeSortingWrites = writes.length;
  await openShared(project, requirement);
  const natural = await page.locator('#dpqaSpoolSelect option').evaluateAll(elements => elements.filter(el => el.value).map(el => el.textContent.trim()));
  assert.deepEqual(natural, Array.from({length: 18}, (_, index) => 'SYNTHETIC-SPOOL-' + (index + 1)));
  assert.equal(writes.length, beforeSortingWrites, 'Sorting-only synthetic labels must not submit any material/QA writes');
  await page.unroute(sortingUrl);
  checks.push('The actual dropdown also sorts a read-only synthetic unpadded sequence naturally, placing 2 before 10 without changing or approving any record');

  stage = 'read-only role cannot approve one piece or a batch';
  await login(context, 'TEST-WELDER');
  await openShared(project, requirement);
  await chooseCopy(fourth);
  assert.equal(await panel().locator('input[data-dpqa-result]:enabled').count(), 0);
  assert.equal(await panel().locator('[data-dpqa-action="pass-all"]:enabled').count(), 0);
  const fourthBefore = await physical(fourth);
  const forbidden = await context.request.post(BASE + '/api/spool-boms/spools/' + fourth + '/materials/qa-001/pass-all', {
    data: bulkBody(fourthBefore, 'QA-FORBIDDEN', 'A read-only role must not record an inspection batch.')
  });
  assert.equal(forbidden.status(), 403, await forbidden.text());
  assert.deepEqual(summary(await physical(fourth)), summary(fourthBefore));
  checks.push('Read-only employees can inspect the ordered material table but cannot use single Pass or PASS ALL, and the server rejects a forged bulk request');

  assert.deepEqual(errors, []);
  const report = {status: 'passed', groups: checks.length, checks, page_errors: errors,
    project_id: project, physical_spools: ordered.map(item => ({id: item.id, display_code: item.display_code})), artifacts: OUT};
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  fs.rmSync(path.join(OUT, 'failure.json'), {force: true});
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch(async error => {
  console.error('FAILED', stage, error.stack || error);
  if (page) await page.screenshot({path: path.join(OUT, 'failure.png'), fullPage: true}).catch(() => {});
  fs.writeFileSync(path.join(OUT, 'failure.json'), JSON.stringify({stage, error: error.message, page_errors: errors}, null, 2));
  if (browser) await browser.close();
  process.exitCode = 1;
});

