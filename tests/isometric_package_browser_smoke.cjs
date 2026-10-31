/* Real parser/upload/review/Excel browser flow. Synthetic loopback fixture only.
 * Start tests/orders_browser_server.py and use full Chromium, as in the PDF test. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.ORDERS_TEST_BASE || 'http://127.0.0.1:8782';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(BASE).hostname), 'Synthetic loopback server only.');
const OUT = process.env.ISOMETRIC_PACKAGE_TEST_OUT || '/tmp/fabtrace-isometric-package-review';
const PYTHON = process.env.PYTHON || 'python3';
const FIRST = 'TEST-100-SPOOL-01', SECOND = 'TEST-100-SPOOL-02', UNMATCHED = 'TEST-100-SPOOL-99';
let browser, page, stage = 'launch';
const checks = [], errors = [], imports = [];

(async () => {
  fs.mkdirSync(OUT, {recursive: true});
  const pdf = execFileSync(PYTHON, ['-c', [
    'import sys', 'sys.path.insert(0, "tests")',
    'from isometric_fixtures import make_isometric_pdf',
    'spools = [',
    ` {"number": "${FIRST}", "rows": [["2", "1", "000456", "PIPE CARBON STEEL 4 IN SCH 40", "16 3/4"+chr(34), "A53B"], ["1", "2", "000123", "FLANGE WELDNECK 4 IN CLASS 150", "", "A105"]]},`,
    ` {"number": "${SECOND}", "rows": [["2", "3", "000888", "PIPE CARBON STEEL 6 IN SCH 40", "24"+chr(34), "A53B"], ["1", "4", "000777", "FLANGE WELDNECK 6 IN CLASS 150", "", "A105"]]},`,
    ` {"number": "${UNMATCHED}", "rows": [["1", "5", "000555", "ELBOW CARBON STEEL 4 IN", "", "A234"]]},`,
    ']', 'sys.stdout.buffer.write(make_isometric_pdf(spools))',
  ].join('\n')]);
  fs.writeFileSync(path.join(OUT, 'synthetic-full-isometric.pdf'), pdf);
  browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  const context = await browser.newContext({viewport: {width: 1440, height: 1050}, acceptDownloads: true});
  await context.route('https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js',
    route => route.fulfill({status: 200, contentType: 'application/javascript', body: ''}));
  page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/isometric-import')) imports.push(request.url());
  });
  const json = async response => { assert.ok(response.ok(), await response.text()); return response.json(); };
  const api = async (method, url, data) => json(await context.request[method](BASE + url, data ? {data} : undefined));
  const action = name => page.locator('[data-sdoc-action="' + name + '"]');
  const settle = () => page.locator('#spoolDocumentsContent[aria-busy="false"]').waitFor();
  const previewClick = async locator => {
    const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/isometric-preview'));
    await locator.click(); const data = await json(await pending); await settle(); return data;
  };
  const savePackage = async () => {
    for (const checkbox of await page.locator('[data-sdoc-reviewed]').all()) if (!(await checkbox.isChecked())) await checkbox.check();
    const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/isometric-import'));
    await action('save-package').click(); const data = await json(await pending); await settle(); return data;
  };
  const open = async (kind, id, tab = 'isometric') => {
    await page.evaluate(target => window.FabSpoolDocuments.open(target), {kind, id, tab}); await settle();
  };
  const file = {name: 'synthetic-full-isometric.pdf', mimeType: 'application/pdf', buffer: pdf};
  const create = number => api('post', '/api/order-setup', {expected_version: 0, purchase_order: number,
    assemblies: [{gpn: 'TEST-100', assembly_quantity: 2, spools: [FIRST, SECOND].map(spool_number => ({spool_number, quantity_per_assembly: 1, welds_per_spool: 2}))}]});
  await api('post', '/api/login', {badge: 'TEST-ADMIN', pin: 'only-for-local-tests-12345'});
  const setup = await create('ISO-UI-' + Date.now()), other = await create('ISO-OTHER-' + Date.now());
  const project = setup.order.project_id, firstRequirement = setup.assemblies[0].spools.find(s => s.spool_number === FIRST).id,
    secondRequirement = setup.assemblies[0].spools.find(s => s.spool_number === SECOND).id,
    otherRequirement = other.assemblies[0].spools.find(s => s.spool_number === FIRST).id;
  const endpoint = id => '/api/spool-documents/requirements/' + id;
  const oldCsv = {name: 'previous-bom.csv', mimeType: 'text/csv', buffer: Buffer.from('item,quantity,description,part_number\n1,1,Prior reviewed component,000111\n')};
  const oldPreview = await json(await context.request.post(BASE + endpoint(firstRequirement) + '/preview', {multipart: {kind: 'bom', files: oldCsv}}));
  const old = await json(await context.request.post(BASE + endpoint(firstRequirement) + '/upload', {multipart: {kind: 'bom', files: oldCsv,
    expected_version: '0', expected_sha256: oldPreview.selection_sha256, reason: 'Synthetic earlier BOM revision'}}));
  const oldBom = old.active.bom.id;
  await page.goto(BASE + '/'); await page.locator('#workspace').waitFor({state: 'visible'});

  stage = 'find exact spool matches and review material rows';
  await open('requirements', firstRequirement);
  await page.locator('#sdocFileInput').setInputFiles(file);
  let preview = await previewClick(action('preview'));
  assert.equal(preview.source.page_count, 4);
  assert.equal(preview.candidates.length, 3);
  assert.equal(preview.targets.length, 2);
  assert.ok(preview.targets.every(target => target.requirement_id !== otherRequirement));
  const firstIndex = preview.candidates.findIndex(candidate => candidate.spool_number === FIRST),
    secondIndex = preview.candidates.findIndex(candidate => candidate.spool_number === SECOND),
    unmatchedIndex = preview.candidates.findIndex(candidate => candidate.spool_number === UNMATCHED);
  assert.ok(firstIndex >= 0 && secondIndex >= 0 && unmatchedIndex >= 0);
  assert.equal(await page.locator('[data-sdoc-select="' + firstIndex + '"]').isChecked(), true);
  assert.equal(await page.locator('[data-sdoc-select="' + secondIndex + '"]').isChecked(), true);
  assert.equal(await page.locator('[data-sdoc-select="' + unmatchedIndex + '"]').isChecked(), false);
  assert.equal(await page.locator('#sdocTarget-' + unmatchedIndex).inputValue(), '');
  assert.match(await page.locator('.sdoc-package').innerText(), /earlier BOM stays in History/);
  assert.match(await page.locator('.sdoc-package').innerText(), /No exact match was found/);
  await page.screenshot({path: path.join(OUT, 'shared-review-desktop.png'), fullPage: true});
  const firstCard = page.locator('[data-sdoc-card="' + firstIndex + '"]');
  await firstCard.locator('[data-sdoc-field="part_number"]').first().fill('000999');
  await firstCard.locator('[data-sdoc-field="quantity"]').first().fill('');
  let rejectedAt = imports.length;
  await action('save-package').click();
  assert.equal(imports.length, rejectedAt);
  assert.match(await page.locator('.sdoc-package .sdoc-error').innerText(), /positive numeric quantity/);
  await firstCard.locator('[data-sdoc-field="quantity"]').first().fill('7');
  const sourceItem = await firstCard.locator('[data-sdoc-field="item"]').first().inputValue();
  await firstCard.locator('[data-sdoc-field="item"]').first().fill('');
  await action('save-package').click();
  assert.equal(imports.length, rejectedAt);
  assert.match(await page.locator('.sdoc-package .sdoc-error').innerText(), /item number/);
  await firstCard.locator('[data-sdoc-field="item"]').first().fill(sourceItem);
  await page.locator('#sdocTarget-' + unmatchedIndex).selectOption(secondRequirement);
  const before = imports.length;
  await action('save-package').click();
  assert.equal(imports.length, before);
  assert.match(await page.locator('.sdoc-package .sdoc-error').innerText(), /More than one table is assigned/);
  await page.locator('[data-sdoc-select="' + unmatchedIndex + '"]').uncheck();
  assert.equal(await firstCard.locator('[data-sdoc-field="part_number"]').first().inputValue(), '000999');
  await page.setViewportSize({width: 390, height: 844});
  await page.locator('#sdocPackageTitle').scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  assert.ok(await page.locator('#spoolDocumentsDialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await page.screenshot({path: path.join(OUT, 'shared-review-mobile.png'), fullPage: true});
  await page.setViewportSize({width: 1440, height: 1050});
  checks.push('Full drawing detects three spool tables; only two exact same-assembly targets are selected; unmatched and duplicate assignments require review; desktop/mobile review fits');

  stage = 'save shared full drawing and separate edited Excel BOMs';
  let saved = await savePackage();
  assert.equal(saved.package_result.count, 2);
  const first = await api('get', endpoint(firstRequirement)), second = await api('get', endpoint(secondRequirement));
  assert.equal(first.active.isometric.page_count, 4);
  assert.equal(second.active.isometric.page_count, 4);
  assert.equal(first.active.isometric.sha256, second.active.isometric.sha256);
  assert.equal(first.active.bom.bom.lines.find(line => line.part_number === '000999').quantity, 7);
  assert.ok(second.active.bom.bom.lines.some(line => line.part_number === '000888'));
  assert.ok(!second.active.bom.bom.lines.some(line => line.part_number === '000999'));
  assert.ok(first.history.some(doc => doc.id === oldBom));
  assert.equal((await api('get', endpoint(otherRequirement))).active.isometric, null);
  await page.locator('#sdoc-tab-bom').click();
  const downloadEvent = page.waitForEvent('download');
  await page.locator('.sdoc-saved').getByRole('link', {name: 'Download Excel BOM', exact: true}).click();
  const download = await downloadEvent;
  assert.match(download.suggestedFilename(), /\.xlsx$/i);
  const workbook = path.join(OUT, 'first-spool-BOM.xlsx'); await download.saveAs(workbook);
  execFileSync(PYTHON, ['-c', [
    'import sys, openpyxl', 'book=openpyxl.load_workbook(sys.argv[1],read_only=True,data_only=False)',
    'values=[cell.value for sheet in book for row in sheet for cell in row]',
    'assert "000999" in values, values', 'assert "000888" not in values, values',
    'assert 7 in values, values',
  ].join('\n'), workbook]);
  await page.screenshot({path: path.join(OUT, 'shared-saved-BOM.png'), fullPage: true});
  checks.push('One atomic package save gives both spools the complete four-page PDF and distinct Excel BOMs, keeps reviewed edits/leading zeros and earlier history, and leaves another PO untouched');

  stage = 'individual physical spool generation and inherited sibling';
  const current = await api('get', '/api/order-setup/' + project);
  await api('post', '/api/order-labels/' + project + '/generate', {expected_version: current.order.version, kind: 'Spool', location: 'Receiving', handler: 'TEST-HANDLER'});
  const labels = await api('get', '/api/order-labels/' + project + '/labels');
  const physical = labels.items.filter(item => item.spool_number === FIRST);
  assert.equal(physical.length, 2);
  const localId = physical[0].id, siblingId = physical[1].id;
  await page.goto(BASE + '/?item=' + localId);
  await page.waitForLoadState('networkidle');
  await page.locator('#itemPage [data-sdoc-kind="spools"]').click(); await settle();
  await page.locator('#sdoc-tab-isometric').click();
  preview = await previewClick(action('create-boms'));
  assert.equal(preview.source.kind, 'saved');
  assert.equal(preview.targets.length, 1);
  assert.equal(preview.targets[0].spool_id, localId);
  assert.equal(preview.candidates.filter(candidate => candidate.selected).length, 1);
  assert.equal(await page.locator('.sdoc-package [data-sdoc-action="use-assembly"]').isVisible(), true);
  assert.match(await page.locator('.sdoc-package').innerText(), /Other spool tables remain unselected/);
  const localIndex = preview.candidates.findIndex(candidate => candidate.spool_number === FIRST);
  await page.locator('[data-sdoc-card="' + localIndex + '"] [data-sdoc-field="part_number"]').first().fill('000LOCAL');
  await page.screenshot({path: path.join(OUT, 'physical-review-share-option.png'), fullPage: true});
  saved = await savePackage(); assert.equal(saved.package_result.count, 1);
  const local = await api('get', '/api/spool-documents/spools/' + localId), sibling = await api('get', '/api/spool-documents/spools/' + siblingId);
  assert.equal(local.active.bom.inherited, false);
  assert.ok(local.active.bom.bom.lines.some(line => line.part_number === '000LOCAL'));
  assert.equal(sibling.active.bom.inherited, true);
  assert.ok(sibling.active.bom.bom.lines.some(line => line.part_number === '000999'));
  checks.push('Saved full drawing creates a local Excel BOM without reuploading, shows a prominent all-spool switch, and preserves the sibling’s inherited setup BOM');

  stage = 'explicit assembly sharing from saved physical drawing';
  preview = await previewClick(action('create-boms'));
  preview = await previewClick(page.locator('.sdoc-package [data-sdoc-action="use-assembly"]'));
  assert.equal(preview.context.kind, 'requirement');
  assert.equal(preview.context.requirement_id, firstRequirement);
  assert.equal(preview.source.kind, 'saved');
  assert.equal(preview.candidates.filter(candidate => candidate.selected).length, 2);
  assert.match(await page.locator('.sdoc-package').innerText(), /own document revisions keep their individual versions/);
  saved = await savePackage(); assert.equal(saved.package_result.count, 2);
  assert.ok((await api('get', '/api/spool-documents/spools/' + localId)).active.bom.bom.lines.some(line => line.part_number === '000LOCAL'));
  assert.ok((await api('get', '/api/spool-documents/spools/' + siblingId)).active.bom.bom.lines.some(line => line.part_number === '000456'));
  checks.push('Explicit all-assembly sharing reuses the saved physical PDF, creates the two setup BOMs and keeps an existing individual override intact');

  stage = 'selected upload carries over to assembly setup';
  await page.goto(BASE + '/?item=' + siblingId);
  await page.waitForLoadState('networkidle');
  await page.locator('#itemPage [data-sdoc-kind="spools"]').click(); await settle();
  await page.locator('#sdoc-tab-isometric').click();
  await page.locator('.sdoc-upload > summary').click();
  await page.locator('#sdocFileInput').setInputFiles(file);
  preview = await previewClick(action('preview'));
  assert.equal(preview.source.kind, 'upload');
  const sha = preview.source.selection_sha256;
  const carriedIndex = preview.candidates.findIndex(candidate => candidate.spool_number === FIRST);
  await page.locator('[data-sdoc-card="' + carriedIndex + '"] [data-sdoc-field="part_number"]').first().fill('000CARRY');
  preview = await previewClick(page.locator('.sdoc-package [data-sdoc-action="use-assembly"]'));
  assert.equal(preview.source.kind, 'upload');
  assert.equal(preview.source.selection_sha256, sha);
  assert.equal(preview.context.requirement_id, firstRequirement);
  assert.equal(preview.candidates.filter(candidate => candidate.selected).length, 2);
  assert.equal(await page.locator('[data-sdoc-card="' + carriedIndex + '"] [data-sdoc-field="part_number"]').first().inputValue(), '000CARRY');
  checks.push('The explicit share-all switch carries selected upload bytes and reviewed material corrections into setup without choosing the file again');
  assert.deepEqual(errors, []);
  const report = {status: 'passed', checks, page_errors: errors, imports: imports.length, project_id: project, artifacts: OUT};
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  fs.rmSync(path.join(OUT, 'failure.json'), {force: true});
  console.log(JSON.stringify(report, null, 2));
  await browser.close(); browser = null;
})().catch(async error => {
  console.error('FAILED', stage, error.stack || error);
  if (page) await page.screenshot({path: path.join(OUT, 'failure.png'), fullPage: true}).catch(() => {});
  fs.writeFileSync(path.join(OUT, 'failure.json'), JSON.stringify({stage, error: error.message, checks, page_errors: errors}, null, 2));
  if (browser) await browser.close();
  process.exitCode = 1;
});
