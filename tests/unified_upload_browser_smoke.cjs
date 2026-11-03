/* Real image OCR, automatic upload review, retained drafts and BOM-only revisions.
 * Uses invented fixtures and the isolated loopback app; never production. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.ORDERS_TEST_BASE || 'http://127.0.0.1:8782';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(BASE).hostname), 'Loopback fixture only.');
const OUT = process.env.UNIFIED_UPLOAD_TEST_OUT || '/tmp/fabtrace-unified-upload-review';
const PYTHON = process.env.PYTHON || 'python3';
const FIRST = 'TEST-100-SPOOL-01', SECOND = 'TEST-100-SPOOL-02';
const checks = [], errors = [], events = [];
let browser, page, stage = 'fixtures';

(async () => {
  fs.mkdirSync(OUT, {recursive: true});
  execFileSync(PYTHON, ['-c', [
    'import sys, pathlib, pypdfium2 as pdfium', 'sys.path.insert(0,"tests")',
    'from isometric_fixtures import make_isometric_pdf, make_bom_pdf',
    'out=pathlib.Path(sys.argv[1])',
    'drawing=pdfium.PdfDocument(make_isometric_pdf(include_assembly=False))',
    'for index,page in enumerate(drawing):',
    '    page.render(scale=2).to_pil().save(str(out/f"scan-{index+1}.png"))',
    `source=pdfium.PdfDocument(make_bom_pdf(spool_number="${FIRST}"))`,
    'source[0].render(scale=2).to_pil().save(str(out/"bom-only.png"))',
    'unlabeled=make_bom_pdf()', '(out/"unlabeled-bom.pdf").write_bytes(unlabeled)',
  ].join('\n'), OUT]);
  browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  const context = await browser.newContext({viewport: {width: 1440, height: 1050}, acceptDownloads: true});
  await context.route('https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js',
    route => route.fulfill({status: 200, contentType: 'application/javascript', body: ''}));
  page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  await page.exposeFunction('captureDocumentEvent', data => events.push(data));
  await page.addInitScript(() => document.addEventListener('fabtrace:spool-documents-saved',
    event => window.captureDocumentEvent({kind: event.detail.kind, id: event.detail.id, document_kind: event.detail.document_kind})));
  const json = async response => {assert.ok(response.ok(), await response.text()); return response.json();};
  const api = async (method, url, data) => json(await context.request[method](BASE + url, data ? {data} : undefined));
  const action = name => page.locator('[data-sdoc-action="' + name + '"]');
  const settle = () => page.locator('#spoolDocumentsContent[aria-busy="false"]').waitFor();
  const auto = async change => {
    await page.evaluate(() => {
      window.uploadReadingObserved = false;
      window.uploadReadingObserver?.disconnect();
      window.uploadReadingObserver = new MutationObserver(() => {
        if (document.querySelector('.sdoc-processing')) window.uploadReadingObserved = true;
      });
      window.uploadReadingObserver.observe(document.getElementById('spoolDocumentsContent'), {childList: true, subtree: true});
    });
    const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/isometric-preview'), {timeout: 180000});
    await change();
    const result = await json(await pending); await settle();
    assert.equal(await page.evaluate(() => {window.uploadReadingObserver.disconnect();return window.uploadReadingObserved;}), true);
    assert.equal(await page.locator('#spoolDocumentsBack').isEnabled(), true);
    return result;
  };
  const open = async (id, tab = 'upload') => {
    await page.evaluate(target => window.FabSpoolDocuments.open(target), {kind: 'requirements', id, tab, fresh: true}); await settle();
  };
  const expand = async index => {
    const toggle = page.locator('[data-sdoc-action="toggle-materials"][data-sdoc-candidate="' + index + '"]');
    if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  };
  const acknowledge = async () => {
    for (const checkbox of await page.locator('[data-sdoc-reviewed]').all()) if (!(await checkbox.isChecked())) await checkbox.check();
  };
  const save = async () => {
    await acknowledge();
    const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/isometric-import'));
    await action('save-package').click(); const result = await json(await pending); await settle(); return result;
  };
  await api('post', '/api/login', {badge: 'TEST-ADMIN', pin: 'only-for-local-tests-12345'});
  const setup = await api('post', '/api/order-setup', {expected_version: 0, purchase_order: 'AUTO-IMAGE-' + Date.now(),
    assemblies: [{gpn: 'TEST-100', assembly_number: 'TEST-UPLOAD-ASM-100', assembly_quantity: 1,
      spools: [FIRST, SECOND].map(spool_number => ({spool_number, quantity_per_assembly: 1, welds_per_spool: 1}))}]});
  const firstId = setup.assemblies[0].spools.find(row => row.spool_number === FIRST).id;
  const secondId = setup.assemblies[0].spools.find(row => row.spool_number === SECOND).id;
  const endpoint = id => '/api/spool-documents/requirements/' + id;
  await page.goto(BASE + '/'); await page.locator('#workspace').waitFor({state: 'visible'});

  stage = 'image from legacy BOM entry automatically scans';
  await open(firstId);
  assert.equal(await page.locator('.sdoc-upload-start').count(), 1);
  assert.equal(await page.locator('[role="tablist"]').filter({has: page.locator('#sdoc-tab-bom')}).count(), 0);
  assert.equal(await page.locator('#sdocReason').count(), 0);
  await page.screenshot({path: path.join(OUT, 'simple-upload-entry.png'), fullPage: true});
  await open(firstId, 'bom');
  let preview = await auto(() => page.locator('#sdocFileInput').setInputFiles(path.join(OUT, 'scan-1.png')));
  assert.equal(preview.source.classification, 'isometric', JSON.stringify(preview.warnings));
  assert.equal(preview.source.document_kind, 'isometric');
  assert.equal(preview.candidates.length, 1);
  assert.equal(preview.candidates[0].matched_requirement_id, firstId);
  assert.equal(await page.locator('#sdocReason').isVisible(), false, 'Initial audit note is optional and collapsed.');
  assert.ok((await page.locator('#sdocReason').inputValue()).length >= 4);
  checks.push('Choosing a PNG from the old BOM screen starts real OCR automatically and identifies the drawing without a Preview click');

  stage = 'camera append and reordered pages invalidate prior analysis';
  const onePageSha = preview.source.selection_sha256;
  await page.locator('#spoolDocumentsBack').click();
  assert.equal(await page.locator('.sdoc-files li').count(), 1);
  assert.equal(await page.locator('#sdocCameraInput').getAttribute('capture'), 'environment');
  preview = await auto(() => page.locator('#sdocCameraInput').setInputFiles(path.join(OUT, 'scan-2.png')));
  assert.equal(preview.source.page_count, 2); assert.equal(preview.candidates.length, 2);
  assert.notEqual(preview.source.selection_sha256, onePageSha);
  const twoPageSha = preview.source.selection_sha256;
  await page.locator('#spoolDocumentsBack').click();
  preview = await auto(() => action('move-up').nth(1).click());
  assert.notEqual(preview.source.selection_sha256, twoPageSha);
  assert.equal(preview.source.page_count, 2);
  assert.deepEqual(preview.candidates.find(row => row.spool_number === FIRST).source_pages, [2]);
  checks.push('Adding a camera page and reordering scans each trigger fresh analysis; both pages remain in the source and old source hashes are invalidated');

  stage = 'Back and navigation preserve selected File objects and reviewed cells';
  const firstIndex = preview.candidates.findIndex(row => row.spool_number === FIRST);
  await expand(firstIndex);
  const part = () => page.locator('[data-sdoc-card="' + firstIndex + '"] [data-sdoc-field="part_number"]').first();
  await part().fill('000REVIEW');
  await page.locator('#spoolDocumentsBack').click();
  assert.equal(await page.locator('.sdoc-files li').count(), 2);
  await action('continue-review').click(); assert.equal(await part().inputValue(), '000REVIEW');
  await page.evaluate(() => {
    window.documentDraftForTest = window.FabSpoolDocuments.navigationState();
    window.FabSpoolDocuments.cancelPending();
  });
  assert.equal(await page.locator('#spoolDocumentsDialog').evaluate(el => el.open), false);
  assert.equal(await page.evaluate(() => window.documentDraftForTest.drafts.isometric.files.every(entry => entry.file instanceof File)), true);
  await page.evaluate(() => window.FabSpoolDocuments.restoreNavigation(window.documentDraftForTest)); await settle();
  assert.equal(await part().inputValue(), '000REVIEW');
  assert.equal(await page.locator('[data-sdoc-select]:checked').count(), 2);
  await page.locator('#spoolDocumentsClose').click();
  await page.evaluate(id => window.FabSpoolDocuments.open({kind: 'requirements', id, tab: 'bom'}), firstId); await settle();
  assert.equal(await page.locator('#sdoc-tab-bom').getAttribute('aria-selected'), 'true', 'Direct BOM link honors its requested saved tab.');
  await page.locator('#sdoc-tab-upload').click();
  assert.equal(await part().inputValue(), '000REVIEW', 'Explicit saved tab preserves the pending upload review.');
  await page.setViewportSize({width: 390, height: 844});
  await page.locator('#sdocPackageTitle').scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  assert.ok(await page.locator('#spoolDocumentsDialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await page.screenshot({path: path.join(OUT, 'image-review-mobile.png'), fullPage: true});
  await page.setViewportSize({width: 1440, height: 1050});
  await page.screenshot({path: path.join(OUT, 'image-review-desktop.png'), fullPage: true});
  checks.push('Back and app navigation preserve selected image Files, mappings and material corrections; direct saved-tab links honor their tab without losing the draft; review fits a 390px phone');

  stage = 'save full shared source with separate Excel BOMs';
  let result = await save(); assert.equal(result.package_result.count, 2);
  let first = await api('get', endpoint(firstId)), second = await api('get', endpoint(secondId));
  assert.equal(first.active.isometric.page_count, 2); assert.equal(second.active.isometric.page_count, 2);
  assert.equal(first.active.isometric.sha256, second.active.isometric.sha256);
  assert.ok(first.active.bom.bom.lines.some(line => line.part_number === '000REVIEW'));
  assert.ok(!second.active.bom.bom.lines.some(line => line.part_number === '000REVIEW'));
  const originalDrawing = first.active.isometric.id, originalOtherBom = second.active.bom.id;
  await page.locator('#sdoc-tab-bom').click();
  const downloadEvent = page.waitForEvent('download');
  await page.locator('.sdoc-saved').getByRole('link', {name: 'Download Excel BOM', exact: true}).click();
  const download = await downloadEvent, workbook = path.join(OUT, 'reviewed-spool-bom.xlsx'); await download.saveAs(workbook);
  execFileSync(PYTHON, ['-c', 'import sys,openpyxl; b=openpyxl.load_workbook(sys.argv[1],read_only=True); assert "000REVIEW" in [c.value for s in b for r in s for c in r]', workbook]);
  await page.locator('#sdoc-tab-isometric').click();
  const view = page.locator('.sdoc-saved').getByRole('link', {name: 'View full isometric'});
  assert.equal(await view.getAttribute('target'), '_blank');
  assert.equal((await context.request.get(BASE + await view.getAttribute('href'))).status(), 200);
  checks.push('One save creates two separate Excel BOMs and shares all drawing pages with both corresponding spools; Excel download keeps the reviewed code');

  stage = 'standalone BOM photo updates BOM without replacing drawing';
  await page.locator('#sdoc-tab-bom').click();
  await page.locator('.sdoc-upload > summary').click();
  preview = await auto(() => page.locator('#sdocFileInput').setInputFiles(path.join(OUT, 'bom-only.png')));
  assert.equal(preview.source.classification, 'bom', JSON.stringify(preview.warnings)); assert.equal(preview.source.document_kind, 'bom');
  assert.equal(preview.candidates.length, 1); assert.equal(preview.candidates[0].matched_requirement_id, firstId);
  assert.match(await page.locator('.sdoc-package').innerText(), /existing isometric drawing stays available/);
  assert.equal(await page.locator('label[for="sdocTarget-0"]').innerText(), 'Spool receiving this BOM');
  assert.equal(await page.locator('#sdocReason').isVisible(), true); assert.equal(await page.locator('#sdocReason').inputValue(), '');
  await acknowledge(); await action('save-package').click();
  assert.match(await page.locator('.sdoc-package .sdoc-error').innerText(), /reason/);
  await page.locator('#sdocReason').fill('Replace the material list with the reviewed BOM scan');
  const beforeEvents = events.length;
  result = await save(); assert.equal(result.package_result.source_document_kind, 'bom');
  first = await api('get', endpoint(firstId)); second = await api('get', endpoint(secondId));
  assert.equal(first.active.isometric.id, originalDrawing); assert.equal(second.active.bom.id, originalOtherBom);
  assert.equal(first.active.bom.source_document_kind, 'bom');
  assert.ok(first.history.some(doc => doc.id === first.active.bom.source_document_id && doc.kind === 'bom'));
  await page.locator('#sdoc-tab-bom').click();
  const sourceLink = page.locator('.sdoc-saved').getByRole('link', {name: 'View uploaded BOM image / PDF'});
  assert.equal((await context.request.get(BASE + await sourceLink.getAttribute('href'))).status(), 200);
  assert.ok(events.slice(beforeEvents).length > 0); assert.ok(events.slice(beforeEvents).every(event => event.document_kind === 'bom'));
  await page.screenshot({path: path.join(OUT, 'bom-source-and-excel.png'), fullPage: true});
  checks.push('A standalone BOM image is classified as BOM, requires a revision reason, preserves the full drawing and other spool, and retains the viewable source beside Excel; saved events report only BOM');

  stage = 'unlabeled BOM remains unassigned across multiple spools';
  await page.locator('#sdoc-tab-upload').click();
  preview = await auto(() => page.locator('#sdocFileInput').setInputFiles(path.join(OUT, 'unlabeled-bom.pdf')));
  assert.equal(preview.source.document_kind, 'bom'); assert.equal(preview.candidates.length, 1);
  assert.equal(preview.candidates[0].spool_number, ''); assert.equal(preview.candidates[0].selected, false);
  assert.equal(await page.locator('#sdocTarget-0').inputValue(), ''); assert.equal(await action('save-package').isDisabled(), true);
  await page.locator('#spoolDocumentsDone').click();
  assert.equal(await page.locator('#spoolDocumentsDialog').evaluate(el => el.open), false);
  checks.push('An unlabeled BOM is not assigned to the first assembly spool; the user must choose its destination, and Return to setup closes the document flow');
  assert.deepEqual(errors, []);
  const report = {status: 'passed', checks, page_errors: errors, saved_events: events, artifacts: OUT};
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2)); fs.rmSync(path.join(OUT, 'failure.json'), {force: true});
  console.log(JSON.stringify(report, null, 2)); await browser.close(); browser = null;
})().catch(async error => {
  console.error('FAILED', stage, error.stack || error);
  if (page) await page.screenshot({path: path.join(OUT, 'failure.png'), fullPage: true}).catch(() => {});
  fs.writeFileSync(path.join(OUT, 'failure.json'), JSON.stringify({stage, error: error.message, checks, page_errors: errors}, null, 2));
  if (browser) await browser.close(); process.exitCode = 1;
});

