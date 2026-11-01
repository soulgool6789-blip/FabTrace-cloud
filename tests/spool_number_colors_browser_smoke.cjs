/* Focused correction check: real physical spool numbers own flow colors.
 * Run only against tests/orders_browser_server.py's disposable loopback DB.
 * No deployed host is accepted and no synthetic data leaves the fixture. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const BASE = process.env.ORDERS_TEST_BASE || 'http://127.0.0.1:8782';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(BASE).hostname), 'Disposable loopback fixture only');
const OUT = process.env.SPOOL_NUMBER_COLORS_TEST_OUT || '/tmp/fabtrace-spool-number-colors-review';
fs.mkdirSync(OUT, {recursive: true});
const NUMBER = '643-777-PCW-03-01';
const BLUE = 'rgb(29, 78, 216)', BLACK = 'rgb(0, 0, 0)';
const checks = [], errors = [], writes = [];
let browser, page, stage = 'launch', seedComplete = false;

(async () => {
  browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  await context.route('**/*', route => new URL(route.request().url()).origin === new URL(BASE).origin
    ? route.continue() : route.fulfill({status: 200, contentType: 'application/javascript', body: ''}));
  const json = async response => { assert.ok(response.ok(), await response.text()); return response.json(); };
  const api = async (method, url, data) => json(await context.request[method](BASE + url, data ? {data} : undefined));
  await api('post', '/api/login', {badge: 'TEST-ADMIN', pin: 'only-for-local-tests-12345'});
  page = await context.newPage(); page.setDefaultTimeout(18000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    const url = new URL(request.url());
    if (seedComplete && url.pathname.startsWith('/api/') && !['GET', 'HEAD'].includes(request.method()))
      writes.push({method: request.method(), path: url.pathname});
  });
  const panel = async (id, query) => {
    await page.goto(BASE + '/?' + query);
    await page.locator('#' + id + '[aria-busy="false"]').waitFor();
  };
  const color = async (scope, id, expected, description) => {
    const selected = scope.locator('[data-spool-number="' + NUMBER + '"][data-spool-id="' + id + '"]:visible');
    await selected.first().waitFor();
    const values = await selected.evaluateAll(elements => elements.map(element => {
      const target = element.matches('.fst-text') ? element : element.querySelector('.fst-text');
      return {text: element.textContent, color: target ? getComputedStyle(target).color : null,
        stage: target?.dataset.flowStage || element.dataset.flowStage};
    }));
    assert.ok(values.length, description + ': visible physical spool number required');
    for (const value of values) {
      assert.ok(value.text.includes(NUMBER), description + ': color must belong to the actual spool number');
      assert.equal(value.color, expected, description + ': ' + JSON.stringify(value));
      assert.equal(value.stage, expected === BLUE ? 'welding' : 'qa_001', description + ': stage');
    }
    return values;
  };
  const noOverflow = async () => assert.equal(await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth + 1), false, 'No horizontal page overflow');

  stage = 'create two physical copies of the real-format spool number';
  const setup = await api('post', '/api/order-setup', {expected_version: 0,
    purchase_order: 'SPOOL-COLORS-' + Date.now(),
    assemblies: [{gpn: 'COLOR-CHECK-ASSEMBLY', assembly_quantity: 1,
      spools: [{spool_number: NUMBER, quantity_per_assembly: 2, welds_per_spool: 0}]}]});
  const project = setup.order.project_id, requirement = setup.assemblies[0].spools[0].id;
  const documentBase = '/api/spool-documents/requirements/' + requirement;
  const source = await api('get', documentBase);
  const file = {name: 'synthetic-spool-color-pieces.csv', mimeType: 'text/csv', buffer: Buffer.from(
    'spool_number,item,quantity,unit,part_number,description,material\r\n'
    + NUMBER + ',1,2,EA,100708,Synthetic flange description,A105\r\n')};
  const preview = await json(await context.request.post(BASE + documentBase + '/preview',
    {multipart: {kind: 'bom', files: file}}));
  await json(await context.request.post(BASE + documentBase + '/upload', {multipart: {
    kind: 'bom', files: file, expected_version: String(source.version), expected_sha256: preview.selection_sha256,
    reason: 'Synthetic spool-number color correction verification'}}));
  await api('post', '/api/order-labels/' + project + '/generate', {expected_version: setup.order.version,
    kind: 'Spool', location: 'Receiving', handler: 'TEST-HANDLER'});
  const labels = await api('get', '/api/order-labels/' + project + '/labels');
  assert.equal(labels.items.length, 2);
  const [first, second] = labels.items.slice().sort((a, b) => a.display_code.localeCompare(b.display_code));
  assert.notEqual(first.id, second.id); assert.notEqual(first.display_code, second.display_code);
  const materialBase = '/api/spool-boms/spools/' + first.id;
  let material = await api('get', materialBase);
  material = await api('put', materialBase + '/traceability', {
    expected_version: material.traceability.version, expected_bom_sha256: material.source_status.expected_bom_sha256,
    reason: 'Synthetic trace evidence for one physical spool copy',
    materials: material.traceability.materials.map(piece => ({piece_key: piece.piece_key,
      supplier: 'Synthetic supplier', supplier_piece_id: '', heat_number: 'LOCAL-HEAT',
      mtr_reference: 'LOCAL-MTR', mtr_url: '', notes: ''}))});
  material = await api('post', materialBase + '/materials/qa-001/pass-all', {
    expected_trace_version: material.traceability.version,
    expected_bom_sha256: material.source_status.expected_bom_sha256,
    pieces: material.traceability.materials.map(piece => ({piece_key: piece.piece_key,
      expected_version: piece.qa001.version, basis_sha256: piece.qa001.basis_sha256})),
    reference: 'LOCAL-PIECE-QA', notes: 'Synthetic incoming inspection'});
  await api('post', materialBase + '/arrival-inspections', {expected_version: material.arrival.version,
    basis_sha256: material.arrival.basis_sha256, result: 'Pass', reference: 'LOCAL-ARRIVAL',
    notes: 'Synthetic arrival verification',
    checks: Object.fromEntries(['identity', 'bom', 'heat_numbers', 'mtrs', 'condition'].map(key => [key, true]))});
  await api('post', '/api/flow/items/' + first.id + '/start', {route: 'spool', expected_children: 0,
    material_reference: 'LOCAL-KITTED-MATERIALS', start_step: 13,
    baseline_reference: 'LOCAL-CONTROLLED-BASELINE',
    baseline_reason: 'Synthetic existing spool at process welding, prior history remains unrecorded'});
  assert.equal((await api('get', '/api/flow/items/' + first.id)).flow_stage.key, 'welding');
  assert.equal((await api('get', '/api/flow/items/' + second.id)).flow_stage.key, 'qa_001');
  seedComplete = true;

  stage = 'core inventory and exact physical spool navigation';
  await page.goto(BASE + '/?items=1');
  await page.locator('#itemsRows [data-id="' + first.id + '"]').waitFor();
  await color(page.locator('#itemsRows'), first.id, BLUE, 'Items first copy');
  await color(page.locator('#itemsRows'), second.id, BLACK, 'Items second copy');
  await page.locator('#itemsRows [data-id="' + first.id + '"]').click();
  await page.locator('#itemPage:not(.hidden)').waitFor();
  assert.equal(await page.evaluate(() => current.id), first.id);
  assert.equal(new URL(page.url()).searchParams.get('spool'), first.display_code);
  await color(page.locator('#itemPage'), first.id, BLUE, 'Item title and QR identity');
  assert.ok((await page.locator('#qrImage').getAttribute('src')).includes(encodeURIComponent(first.id)));
  checks.push('Core items show the real spool numbers in blue and black independently; clicking the readable number and QR image retain the exact internal record ID');

  stage = 'process flow, parts and progress use the same spool number';
  for (const [host, query] of [
    ['flowContent', 'flow=1&item=' + first.id],
    ['partsContent', 'parts=1&spool=' + first.id],
    ['flowContent', 'flow=1&project=' + project],
    ['partsContent', 'parts=1&project=' + project],
    ['trackingContent', 'tracking=1&spool=' + first.id],
    ['progressContent', 'progress=1&project=' + project],
  ]) {
    await panel(host, query);
    await color(page.locator('#' + host), first.id, BLUE, query);
  }
  await page.goto(BASE + '/?handoff=1&item=' + first.id);
  await color(page.locator('#handoffItemInfo'), first.id, BLUE, 'Scan and transfer identity');
  await panel('productionProgressContent', 'production-progress=1&project=' + project);
  await page.locator('[data-pp-action="expand"]').click();
  await color(page.locator('#productionProgressContent'), first.id, BLUE, 'Production progress first copy');
  await color(page.locator('#productionProgressContent'), second.id, BLACK, 'Production progress second copy');
  const firstRow = page.locator('[data-pp-item="' + first.id + '"]');
  assert.ok((await firstRow.locator('> summary').innerText()).includes(first.display_code));
  await firstRow.locator('[data-pp-action="flow"][data-pp-id="' + first.id + '"]').click();
  await page.locator('#flowContent[aria-busy="false"]').waitFor();
  await color(page.locator('#flowContent'), first.id, BLUE, 'Progress to exact process record');
  checks.push('Process flow, parts, weld tracking, both progress views and scan/transfer agree on the actual spool number and blue stage, preserving ID navigation');

  stage = 'mixed-copy purchase order views and online labels';
  for (const [host, query] of [
    ['orderSetupContent', 'order-setup=1&po=' + project],
    ['ordersContent', 'orders=1&po=' + project + '&assembly=' + first.assembly_id],
    ['orderLabelsContent', 'order-labels=1&po=' + project],
  ]) {
    await panel(host, query);
    if (host === 'orderSetupContent') {
      for (const toggle of await page.locator('#orderSetupContent details.os-copy-flow:not([open]) > summary').all())
        await toggle.click();
    }
    await color(page.locator('#' + host), first.id, BLUE, query + ' first copy');
    await color(page.locator('#' + host), second.id, BLACK, query + ' second copy');
    if (host === 'orderSetupContent') {
      const common = page.locator('#orderSetupContent [data-spool-number="' + NUMBER + '"][data-spool-id=""]');
      assert.ok(await common.count(), 'Mixed requirement retains its base spool number');
      assert.ok((await common.evaluateAll(elements => elements.every(el =>
        !el.matches('.fst-text') && !el.querySelector('.fst-text')))),
      'A mixed-copy requirement must not advertise a single color');
      await common.first().scrollIntoViewIfNeeded();
      await page.screenshot({path: path.join(OUT, 'mixed-copies-po-desktop.png'), fullPage: false});
      await page.locator('[data-os-action="physical-spool"][data-os-id="' + second.id + '"]').click();
      await page.locator('#itemPage:not(.hidden)').waitFor();
      assert.equal(await page.evaluate(() => current.id), second.id);
      await color(page.locator('#itemPage'), second.id, BLACK, 'Mixed requirement opens the selected physical copy');
    }
  }
  checks.push('Saved P.O. setup, production-order spool rows and online QR labels keep same-number copies at separate blue and black stages');

  stage = 'physical BOM headings own colors and material descriptions remain normal';
  await page.goto(BASE + '/?items=1');
  await page.locator('#itemsRows [data-id="' + first.id + '"]').click();
  await page.locator('#itemPage:not(.hidden)').waitFor();
  await page.locator('#itemPage [data-spool-bom-url]').click();
  await page.locator('#spoolBomContent[aria-busy="false"]').waitFor();
  await color(page.locator('#spoolBomDialog'), first.id, BLUE, 'Materials dialog spool headings');
  assert.equal(await page.locator('.fbom-piece-description .fst-text').count(), 0,
    'Material descriptions must not carry spool-stage text classes');
  assert.ok((await page.locator('.fbom-piece-description').first().innerText()).includes('Synthetic flange description'));
  await page.screenshot({path: path.join(OUT, 'materials-spool-heading-desktop.png'), fullPage: false});
  await page.keyboard.press('Escape');
  await page.locator('#itemPage [data-sdoc-kind="spools"]').click();
  await page.locator('#spoolDocumentsContent[aria-busy="false"]').waitFor();
  await page.locator('#sdoc-tab-bom').click();
  await page.locator('#documentPieceQa[data-state="ready"]').waitFor();
  await color(page.locator('#spoolDocumentsDialog'), first.id, BLUE, 'BOM/drawings physical spool headings');
  assert.equal(await page.locator('.dpqa-description .fst-text').count(), 0,
    'Saved BOM material descriptions must retain normal text');
  assert.equal(await page.locator('#dpqaPhysicalName').innerText(), first.display_code);
  await page.setViewportSize({width: 390, height: 844});
  await noOverflow();
  assert.ok(await page.locator('#spoolDocumentsDialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await page.screenshot({path: path.join(OUT, 'bom-spool-heading-mobile.png'), fullPage: false});
  checks.push('Materials and saved BOM headers color the actual physical spool number; material descriptions remain normal and mobile layout fits 390px');

  assert.deepEqual(errors, [], 'No browser page errors');
  assert.deepEqual(writes, [], 'Opening and navigating color views must not write production or QA data');
  const report = {status: 'passed', checks, project_id: project,
    spools: [first, second].map(item => ({id: item.id, display_code: item.display_code})),
    page_errors: errors, artifacts: OUT};
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch(async error => {
  console.error('FAILED', stage, error.stack || error);
  if (page) await page.screenshot({path: path.join(OUT, 'failure.png'), fullPage: false}).catch(() => {});
  fs.writeFileSync(path.join(OUT, 'failure.json'), JSON.stringify({stage, error: error.message, page_errors: errors}, null, 2));
  if (browser) await browser.close();
  process.exitCode = 1;
});
