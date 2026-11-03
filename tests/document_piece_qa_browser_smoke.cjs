/* Saved BOM & drawings: each physical piece gets its own QA-001 decision.
 * Run only with tests/orders_browser_server.py's fresh loopback database. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const BASE = process.env.ORDERS_TEST_BASE || 'http://127.0.0.1:8782';
const OUT = process.env.DOCUMENT_PIECE_QA_TEST_OUT || '/tmp/fabtrace-document-piece-qa-review';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(BASE).hostname), 'Fresh loopback fixture only');
fs.mkdirSync(OUT, {recursive: true});
const checks = [], errors = [];
const run = Date.now().toString(36);
const number = '643-777-PCW-03-01';
let browser, page, stage = 'launch';

(async () => {
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),
    args: ['--no-sandbox', '--disable-dev-shm-usage']
  });
  const admin = await browser.newContext();
  const context = await browser.newContext({viewport: {width: 1440, height: 1050}});
  await context.route('https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js',
    route => route.fulfill({status: 200, contentType: 'application/javascript', body: ''}));
  const json = async response => {
    assert.ok(response.ok(), await response.text());
    return response.json();
  };
  const login = async (ctx, badge) => json(await ctx.request.post(BASE + '/api/login', {
    data: {badge, pin: 'only-for-local-tests-12345'}
  }));
  await login(admin, 'TEST-ADMIN');
  await login(context, 'TEST-QA');
  const api = async (method, url, data) => json(await admin.request[method](BASE + url, data ? {data} : undefined));
  const physical = id => api('get', '/api/spool-boms/spools/' + id);
  page = await context.newPage();
  page.setDefaultTimeout(18000);
  page.on('pageerror', error => errors.push(error.message));
  const panel = () => page.locator('#documentPieceQa');
  const row = key => page.locator('[data-dpqa-piece="' + key + '"]');
  const rows = () => page.locator('[data-dpqa-piece]');
  const status = key => row(key).locator('[data-dpqa-status]');
  const settle = async () => {
    await page.locator('#spoolDocumentsContent[aria-busy="false"]').waitFor();
    await page.locator('#documentPieceQa[data-state="ready"]').waitFor();
  };
  const chooseCopy = async id => {
    const response = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/material-records')
      && new URL(r.url()).searchParams.get('spool_id') === id);
    await page.locator('#dpqaSpoolSelect').selectOption(id);
    assert.equal((await response).status(), 200);
    await settle();
    assert.equal(await page.locator('#dpqaSpoolSelect').inputValue(), id);
  };
  const uploadBom = async (scope, id, revision) => {
    const base = BASE + '/api/spool-documents/' + scope + '/' + id;
    const current = await json(await admin.request.get(base));
    const csv = 'spool_number,item,quantity,unit,part_number,description,size,material,length,drawing,revision,source_page\r\n'
      + number + ',1,2,EA,100708,FLANGE ' + revision + ',3/4 in,A105,,643-777,' + revision + ',2\r\n'
      + number + ',2,1,EA,102391,PIPE,3/4 in,A53B,16 3/4 in,643-777,' + revision + ',2\r\n';
    const file = {name: '643-777-piece-example-' + revision + '.csv', mimeType: 'text/csv', buffer: Buffer.from(csv)};
    const preview = await json(await admin.request.post(base + '/preview', {multipart: {kind: 'bom', files: file}}));
    return json(await admin.request.post(base + '/upload', {multipart: {
      kind: 'bom', files: file, revision,
      expected_version: String(current.version), expected_sha256: preview.selection_sha256,
      reason: 'Synthetic exact-page QA browser verification ' + revision
    }}));
  };
  const openShared = async (project, requirement) => {
    await page.goto(BASE + '/?order-setup=1&po=' + encodeURIComponent(project));
    await page.locator('#orderSetupContent[aria-busy="false"]').waitFor();
    await page.locator('#orderSetupContent [data-sdoc-kind="requirements"][data-sdoc-id="' + requirement + '"]').click();
    await page.locator('#sdoc-tab-bom').click();
    await settle();
  };
  const openPhysical = async id => {
    await page.goto(BASE + '/?item=' + encodeURIComponent(id));
    await page.locator('#itemPage:not(.hidden)').waitFor();
    await page.locator('#itemPage [data-sdoc-kind="spools"]').click();
    await page.locator('#sdoc-tab-bom').click();
    await settle();
  };
  const write = async (suffix, click, expected = 200) => {
    const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith(suffix)
      && !['GET', 'HEAD'].includes(r.request().method()));
    await click();
    const response = await pending;
    assert.equal(response.status(), expected, await response.text());
    await settle();
    return response.json();
  };
  const saveMaterial = async (key, heat, reference) => {
    await row(key).locator('[data-dpqa-material="heat_number"]').fill(heat);
    await row(key).locator('[data-dpqa-material="mtr_reference"]').fill(reference);
    return write('/traceability', () => row(key).locator('[data-dpqa-action="save-material"]').click());
  };
  const chooseQa = async (key, result, reference, notes) => {
    await row(key).getByRole('radio', {name: result, exact: true}).check();
    await row(key).locator('[data-dpqa-field="reference"]').fill(reference);
    await row(key).locator('[data-dpqa-field="notes"]').fill(notes);
  };
  const saveQa = (key, expected = 201) => write('/qa-001',
    () => row(key).locator('[data-dpqa-action="save-qa"]').click(), expected);
  const showHistory = async key => {
    const response = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/materials/' + key + '/qa-001')
      && r.request().method() === 'GET');
    await row(key).locator('[data-dpqa-action="history"]').click();
    assert.equal((await response).status(), 200);
    await row(key).locator('.dpqa-history article').first().waitFor();
  };
  const assertStatuses = async (id, expected) => {
    const detail = await physical(id);
    assert.deepEqual(detail.traceability.materials.map(piece => piece.qa001.status), expected);
    return detail;
  };
  const noOverflow = async () => {
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
    assert.ok(await page.locator('#spoolDocumentsDialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1),
      'BOM & drawings dialog must fit the viewport');
  };

  stage = 'exact two-flange and one-pipe saved BOM';
  const setup = await api('post', '/api/order-setup', {
    expected_version: 0, purchase_order: 'BOM-PIECES-UI-' + run,
    assemblies: [{gpn: 'BOM-PIECES-ASM', assembly_number: 'TEST-BOM-PIECES-001', assembly_quantity: 1,
      spools: [{spool_number: number, quantity_per_assembly: 2, welds_per_spool: 1}]}]
  });
  const project = setup.order.project_id, requirement = setup.assemblies[0].spools[0].id;
  const sourceA = await uploadBom('requirements', requirement, 'A');
  await openShared(project, requirement);
  assert.equal(await page.locator('[data-dpqa-unbound]').count(), 3);
  assert.equal(await rows().count(), 0);
  assert.equal(await panel().locator('input[data-dpqa-result]:enabled').count(), 0);
  assert.match(await panel().innerText(), /100708/);
  assert.match(await panel().innerText(), /102391/);
  checks.push('The saved BOM tab expands quantity 2 flange 100708 and quantity 1 pipe 102391 into three quantity-one rows before physical generation, with no template approval');

  stage = 'choose exact physical copy for shared source';
  await api('post', '/api/order-labels/' + project + '/generate', {
    expected_version: setup.order.version, kind: 'Spool', location: 'Receiving', handler: 'TEST-HANDLER'
  });
  const labels = await api('get', '/api/order-labels/' + project + '/labels');
  assert.equal(labels.items.length, 2);
  const [first, second] = labels.items.map(item => item.id);
  const firstInitial = await physical(first), secondInitial = await physical(second);
  const keys = firstInitial.traceability.materials.map(piece => piece.piece_key);
  assert.equal(keys.length, 3);
  assert.equal(new Set(keys).size, 3);
  assert.ok(firstInitial.traceability.materials.every(piece => piece.persisted));
  await openShared(project, requirement);
  assert.equal(await page.locator('#dpqaSpoolSelect').inputValue(), '');
  assert.equal(await rows().count(), 0);
  await chooseCopy(first);
  assert.equal(await rows().count(), 3);
  assert.deepEqual(await page.locator('[data-dpqa-piece] .dpqa-quantity').allTextContents(), ['1', '1', '1']);
  assert.deepEqual((await page.locator('[data-dpqa-piece] .dpqa-part-number').allTextContents()).map(s => s.trim()), ['100708', '100708', '102391']);
  assert.match(await row(keys[0]).innerText(), /Drawing page:\s*2/);
  assert.match(await row(keys[2]).innerText(), /16 3\/4 in/);
  assert.ok((await page.locator('#dpqaPhysicalName').innerText()).includes(firstInitial.context.display_code));
  assert.equal(await row(keys[0]).getByRole('radio', {name: 'Pass', exact: true}).isDisabled(), false);
  assert.equal(await row(keys[0]).getByRole('radio', {name: 'Fail', exact: true}).isDisabled(), false);
  assert.equal(await panel().locator('input[type="radio"]:checked').count(), 0);
  checks.push('A shared BOM requires an explicit readable physical spool selection; each persisted piece has its own actionable QA controls while recording Pass still requires material evidence');

  stage = 'inline heat and MTR affect only the clicked row';
  await row(keys[1]).locator('[data-dpqa-material="heat_number"]').fill('UNSAVED-SECOND-FLANGE');
  let detail = await saveMaterial(keys[0], 'HEAT-FLANGE-001', 'MTR-FLANGE-001');
  assert.equal(detail.traceability.materials[0].heat_number, 'HEAT-FLANGE-001');
  assert.equal(detail.traceability.materials[1].heat_number, '');
  assert.equal(detail.traceability.materials[2].heat_number, '');
  assert.equal(await row(keys[1]).locator('[data-dpqa-material="heat_number"]').inputValue(), 'UNSAVED-SECOND-FLANGE');
  assert.equal(await row(keys[0]).getByRole('radio', {name: 'Pass', exact: true}).isDisabled(), false);
  assert.equal(await row(keys[1]).getByRole('radio', {name: 'Pass', exact: true}).isDisabled(), false);
  checks.push('Saving heat/MTR directly on one BOM row persists only that physical piece, retains the other row draft and leaves each piece’s Pass action available');

  stage = 'one flange Pass does not approve other pieces or copies';
  await chooseQa(keys[0], 'Pass', 'QA-FLANGE-001', 'First flange dimensions and material evidence verified.');
  const heldUrl = BASE + '/api/spool-boms/spools/' + first + '/materials/' + encodeURIComponent(keys[0]) + '/qa-001';
  let releaseResponse, requestSeen, heldWrites = 0;
  const held = new Promise(resolve => { releaseResponse = resolve; });
  const seen = new Promise(resolve => { requestSeen = resolve; });
  await page.route(heldUrl, async route => {
    heldWrites++;
    const actual = await route.fetch();
    requestSeen();
    await held;
    await route.fulfill({response: actual});
  });
  const savingDecision = saveQa(keys[0]);
  await seen;
  try {
    for (const id of ['spoolDocumentsClose', 'spoolDocumentsDone', 'spoolDocumentsBack'])
      assert.equal(await page.locator('#' + id).isDisabled(), true, id + ' is blocked during a piece save');
    for (const tab of await page.locator('#spoolDocumentsDialog [role="tab"]').all())
      assert.equal(await tab.isDisabled(), true, 'Document tabs are blocked during a piece save');
    assert.equal(await page.evaluate(() => window.FabSpoolDocuments.canNavigateAway()), false);
    assert.equal(await page.evaluate(() => window.FabDocumentPieceQa.canNavigateAway()), false);
    const saveButton = row(keys[0]).locator('[data-dpqa-action="save-qa"]');
    assert.equal(await saveButton.isDisabled(), true);
    await saveButton.evaluate(button => button.click());
    assert.equal(heldWrites, 1, 'A disabled duplicate save cannot emit a second request');
  } finally {
    releaseResponse();
  }
  detail = await savingDecision;
  await page.unroute(heldUrl);
  assert.equal(await page.evaluate(() => window.FabSpoolDocuments.canNavigateAway()), true);
  checks.push('A real pending piece QA save disables Close, Return, Back, every document tab and duplicate submission until its verified response completes');
  assert.deepEqual(detail.traceability.materials.map(piece => piece.qa001.status), ['passed', 'pending', 'pending']);
  assert.equal(detail.arrival.can_proceed, false);
  assert.equal(await status(keys[0]).getAttribute('data-dpqa-status'), 'passed');
  const unchangedSource = await api('get', '/api/spool-documents/requirements/' + requirement);
  assert.equal(unchangedSource.active.bom.id, sourceA.active.bom.id);
  assert.deepEqual(unchangedSource.active.bom.bom.lines.map(line => line.quantity), [2, 1]);
  const siblingBefore = await assertStatuses(second, ['pending', 'pending', 'pending']);
  assert.equal(siblingBefore.traceability.version, secondInitial.traceability.version);
  assert.ok(siblingBefore.traceability.materials.every(piece => !piece.heat_number && !piece.mtr_reference));
  checks.push('QA-001 Pass on flange 001 is saved on this BOM page and approves neither flange 002, the pipe, the second physical spool nor overall arrival');

  stage = 'explicit Fail and reinspection on the second flange';
  await row(keys[1]).locator('[data-dpqa-material="heat_number"]').fill('');
  await chooseQa(keys[1], 'Fail', 'QA-FLANGE-002-FAIL', 'Second flange dimensions require supplier correction.');
  detail = await saveQa(keys[1]);
  assert.deepEqual(detail.traceability.materials.map(piece => piece.qa001.status), ['passed', 'failed', 'pending']);
  await showHistory(keys[1]);
  await row(keys[1]).getByText('QA-FLANGE-002-FAIL', {exact: false}).last().waitFor();
  await row(keys[1]).scrollIntoViewIfNeeded();
  await page.screenshot({path: path.join(OUT, 'bom-piece-fail-desktop.png'), fullPage: true});
  await saveMaterial(keys[1], 'HEAT-FLANGE-002', 'MTR-FLANGE-002');
  await chooseQa(keys[1], 'Pass', 'QA-FLANGE-002-RECHECK', 'Corrected second flange dimensions and material verified.');
  detail = await saveQa(keys[1]);
  assert.deepEqual(detail.traceability.materials.map(piece => piece.qa001.status), ['passed', 'passed', 'pending']);
  await showHistory(keys[1]);
  await row(keys[1]).getByText('QA-FLANGE-002-FAIL', {exact: false}).last().waitFor();
  assert.match(await row(keys[1]).innerText(), /QA-FLANGE-002-RECHECK/);
  checks.push('The second flange records an explicit Fail even with missing evidence; corrected heat/MTR and a later Pass retain its prior Fail history without changing sibling decisions');

  stage = 'material correction stales only the affected piece';
  detail = await saveMaterial(keys[0], 'HEAT-FLANGE-001-CORRECTED', 'MTR-FLANGE-001');
  assert.deepEqual(detail.traceability.materials.map(piece => piece.qa001.status), ['needs_reinspection', 'passed', 'pending']);
  assert.equal(await status(keys[0]).getAttribute('data-dpqa-status'), 'needs_reinspection');
  await chooseQa(keys[0], 'Pass', 'QA-FLANGE-001-RECHECK', 'Corrected first flange heat marking checked against the report.');
  await saveQa(keys[0]);
  await saveMaterial(keys[2], 'HEAT-PIPE-001', 'MTR-PIPE-001');
  await assertStatuses(first, ['passed', 'passed', 'pending']);
  checks.push('A saved heat correction visibly requires reinspection only on its own flange; saving pipe material information does not invent a pipe approval');

  stage = 'copy selection never carries approval or material values';
  await chooseCopy(second);
  assert.equal(await rows().count(), 3);
  assert.ok((await page.locator('#dpqaPhysicalName').innerText()).includes(secondInitial.context.display_code));
  assert.deepEqual(await panel().locator('[data-dpqa-status]').evaluateAll(elements => elements.map(el => el.dataset.dpqaStatus)), ['pending', 'pending', 'pending']);
  for (const input of await panel().locator('[data-dpqa-material="heat_number"]').all()) assert.equal(await input.inputValue(), '');
  assert.equal(await panel().locator('input[type="radio"]:checked').count(), 0);
  await chooseCopy(first);
  assert.equal(await status(keys[0]).getAttribute('data-dpqa-status'), 'passed');
  assert.equal(await status(keys[2]).getAttribute('data-dpqa-status'), 'pending');
  await panel().scrollIntoViewIfNeeded();
  await page.screenshot({path: path.join(OUT, 'bom-piece-qa-desktop.png'), fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  await noOverflow();
  await page.locator('#spoolDocumentsDialog').evaluate(el => { el.scrollTop = 0; });
  await page.screenshot({path: path.join(OUT, 'bom-piece-overview-mobile.png'), fullPage: true});
  await row(keys[0]).scrollIntoViewIfNeeded();
  await page.screenshot({path: path.join(OUT, 'bom-piece-qa-mobile.png'), fullPage: true});
  checks.push('Changing the shared-source selection shows the other physical copy’s blank pending register, then restores only the selected copy’s saved decisions; desktop and 390px views fit');

  stage = 'inspection draft survives tab Back and stale save';
  await page.setViewportSize({width: 1440, height: 1050});
  await chooseQa(keys[2], 'Pass', 'QA-PIPE-STALE-DRAFT', 'Pipe inspection findings retained for evidence review.');
  await page.locator('#sdoc-tab-history').click();
  assert.equal(await panel().count(), 0);
  await page.locator('#spoolDocumentsBack').click();
  await settle();
  assert.equal(await page.locator('#dpqaSpoolSelect').inputValue(), first);
  assert.equal(await row(keys[2]).locator('[data-dpqa-field="reference"]').inputValue(), 'QA-PIPE-STALE-DRAFT');
  assert.equal(await row(keys[2]).locator('[data-dpqa-field="notes"]').inputValue(), 'Pipe inspection findings retained for evidence review.');
  const beforeConcurrent = await physical(first);
  const materialFields = ['piece_key', 'supplier', 'supplier_piece_id', 'heat_number', 'mtr_reference', 'mtr_url', 'notes'];
  await api('put', '/api/spool-boms/spools/' + first + '/traceability', {
    expected_version: beforeConcurrent.traceability.version,
    expected_bom_sha256: beforeConcurrent.source_status.expected_bom_sha256,
    reason: 'Synthetic concurrent correction to this pipe heat marking',
    materials: beforeConcurrent.traceability.materials.map(piece => ({
      ...Object.fromEntries(materialFields.map(field => [field, piece[field] || ''])),
      heat_number: piece.piece_key === keys[2] ? 'HEAT-PIPE-CONCURRENT' : piece.heat_number
    }))
  });
  await saveQa(keys[2], 409);
  assert.equal(await row(keys[2]).locator('[data-dpqa-field="reference"]').inputValue(), 'QA-PIPE-STALE-DRAFT');
  assert.equal(await row(keys[2]).locator('[data-dpqa-field="notes"]').inputValue(), 'Pipe inspection findings retained for evidence review.');
  assert.equal(await row(keys[2]).locator('[data-dpqa-action="save-qa"]').isDisabled(), true);
  const reloadResponse = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/material-records')
    && new URL(r.url()).searchParams.get('spool_id') === first);
  await row(keys[2]).locator('[data-dpqa-action="reload"]').click();
  assert.equal((await reloadResponse).status(), 200);
  await settle();
  assert.equal(await row(keys[2]).locator('input[data-dpqa-result]:checked').count(), 0);
  assert.equal(await row(keys[2]).locator('[data-dpqa-field="reference"]').inputValue(), 'QA-PIPE-STALE-DRAFT');
  assert.equal(await row(keys[2]).locator('[data-dpqa-field="notes"]').inputValue(), 'Pipe inspection findings retained for evidence review.');
  assert.equal(await row(keys[2]).locator('[data-dpqa-material="heat_number"]').inputValue(), 'HEAT-PIPE-CONCURRENT');
  await assertStatuses(first, ['passed', 'passed', 'pending']);
  checks.push('Inspection findings and exact copy survive History → Back; a concurrent material edit rejects the stale Pass, retains notes and requires explicit Reload plus a new choice');

  stage = 'direct physical entry and contextual Back';
  await page.setViewportSize({width: 1440, height: 1050});
  await openPhysical(first);
  assert.equal(await page.locator('#dpqaSpoolSelect').count(), 0);
  assert.equal(await rows().count(), 3);
  assert.equal(await status(keys[0]).getAttribute('data-dpqa-status'), 'passed');
  assert.ok((await page.locator('#dpqaPhysicalName').innerText()).includes(firstInitial.context.display_code));
  await page.locator('#spoolDocumentsBack').click();
  assert.equal(await page.locator('#sdoc-tab-upload').getAttribute('aria-selected'), 'true');
  await page.locator('#spoolDocumentsBack').click();
  assert.equal(await page.locator('#spoolDocumentsDialog').evaluate(el => el.open), false);
  assert.equal(await page.locator('#itemPage').isVisible(), true);
  assert.equal(await page.evaluate(() => current.id), first);
  checks.push('Opening BOM & drawings from the unique physical spool binds that spool automatically; Back follows BOM → Upload → the same physical record');

  stage = 'replacement BOM never borrows old approvals';
  const beforeRevision = await physical(first);
  const sourceB = await uploadBom('requirements', requirement, 'B');
  assert.notEqual(sourceB.active.bom.id, sourceA.active.bom.id);
  await openShared(project, requirement);
  await chooseCopy(first);
  assert.equal(await rows().count(), 0);
  assert.equal(await page.locator('[data-dpqa-unbound]').count(), 3);
  assert.equal(await panel().locator('.dpqa-source-warning').count(), 1);
  assert.match(await panel().innerText(), /replacement|different|changed|adopt|match|revision/i);
  assert.equal(await panel().locator('[data-dpqa-action="save-qa"]:not([disabled])').count(), 0);
  const mismatched = await api('get', '/api/spool-documents/requirements/' + requirement + '/material-records?spool_id=' + first);
  assert.equal(mismatched.record_matches_document, false);
  assert.equal(mismatched.source_match.viewed_document_id, sourceB.active.bom.id);
  assert.equal(mismatched.source_match.pinned_document_id, sourceA.active.bom.id);
  const currentDetail = await physical(first);
  assert.equal(currentDetail.traceability.materials[0].heat_number, beforeRevision.traceability.materials[0].heat_number);
  assert.equal(currentDetail.traceability.materials[0].qa001.status, 'needs_reinspection');
  await page.screenshot({path: path.join(OUT, 'bom-source-mismatch-desktop.png'), fullPage: true});
  await page.locator('#sdoc-tab-history').click();
  await page.locator('.sdoc-history article').first().waitFor();
  assert.equal(await panel().count(), 0);
  assert.equal(await page.locator('[data-dpqa-action="save-qa"]').count(), 0);
  checks.push('A replacement saved BOM shows a prominent source mismatch and no enabled approval actions against retained old material records; History exposes no current-piece QA controls');

  stage = 'explicit adoption starts blank current-revision pieces';
  await page.locator('#sdoc-tab-bom').click();
  await settle();
  if (await page.locator('#dpqaSpoolSelect').inputValue() !== first) await chooseCopy(first);
  await panel().locator('[data-dpqa-action="adopt-panel"]').click();
  await page.locator('#dpqaAdoptReason').fill('Synthetic explicit reviewed adoption of the replacement BOM');
  const adopted = await write('/adopt-bom', () => panel().locator('[data-dpqa-action="adopt-bom"]').click());
  assert.ok(adopted.traceability.materials.every(piece => !piece.heat_number && !piece.mtr_reference && piece.qa001.status === 'pending'));
  assert.ok(adopted.traceability.materials.every(piece => !keys.includes(piece.piece_key)));
  assert.equal(await rows().count(), 3);
  assert.equal(await panel().locator('.dpqa-source-warning').count(), 0);
  assert.deepEqual(await panel().locator('[data-dpqa-status]').evaluateAll(elements => elements.map(el => el.dataset.dpqaStatus)), ['pending', 'pending', 'pending']);
  assert.equal(await panel().locator('input[type="radio"]:checked').count(), 0);
  const otherMismatch = await api('get', '/api/spool-documents/requirements/' + requirement + '/material-records?spool_id=' + second);
  assert.equal(otherMismatch.record_matches_document, false);
  checks.push('Explicit adoption on this same BOM page displays new blank pending pieces for that physical spool only; the other copy still needs its own source review');

  stage = 'read-only role sees rows without inspection permissions';
  await login(context, 'TEST-WELDER');
  await openPhysical(first);
  assert.equal(await rows().count(), 3);
  assert.equal(await panel().locator('[data-dpqa-action="save-qa"]:not([disabled])').count(), 0);
  assert.equal(await panel().locator('input[data-dpqa-result]:enabled').count(), 0);
  checks.push('A welder can read the same piece table while QA-001 approval remains restricted to inspection roles');

  assert.deepEqual(errors, []);
  const report = {status: 'passed', groups: checks.length, checks, page_errors: errors,
    purchase_order: setup.order.purchase_order, project_id: project, spool_ids: [first, second], artifacts: OUT};
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

