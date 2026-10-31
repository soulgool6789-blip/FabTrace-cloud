/* Actual authenticated PDF upload and native-viewer pixel regression.
 * Start tests/orders_browser_server.py; only that isolated loopback fixture is allowed.
 * Use full Chromium (not chromium-headless-shell) and Python with Pillow:
 *   PDF_VIEWER_BROWSER_PATH=/path/to/chrome PYTHON=/path/to/python node ...
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const OUT = process.env.PDF_VIEWER_TEST_OUT || '/tmp/fabtrace-pdf-viewer-review';
const BASE = process.env.ORDERS_TEST_BASE || 'http://127.0.0.1:8782';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(BASE).hostname), 'Synthetic loopback server only.');

function fixturePdf() {
  const first = 'q 0.08 0.72 0.22 rg 55 290 500 340 re f Q\nBT /F1 26 Tf 65 720 Td (FABTRACE VISIBLE PAGE 1) Tj ET\n';
  const second = 'q 0.05 0.25 0.85 rg 55 290 500 340 re f Q\nBT /F1 26 Tf 65 720 Td (FABTRACE VISIBLE PAGE 2) Tj ET\n';
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(first)} >>\nstream\n${first}endstream`,
    `<< /Length ${Buffer.byteLength(second)} >>\nstream\n${second}endstream`,
  ];
  let text = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(text));
    text += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const start = Buffer.byteLength(text);
  text += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  text += offsets.slice(1).map(n => `${String(n).padStart(10, '0')} 00000 n \n`).join('');
  text += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;
  return Buffer.from(text);
}

function pixels(png) {
  const result = spawnSync(process.env.PYTHON || 'python3', ['-c', [
    'import io, json, sys',
    'from PIL import Image',
    'image = Image.open(io.BytesIO(sys.stdin.buffer.read())).convert("RGB")',
    '# Exclude PDF page thumbnails and toolbar so only the actual page can pass.',
    'image = image.crop((int(image.width * .32), 60, image.width, image.height))',
    'green = blue = 0',
    'for red, g, b in image.getdata():',
    '    green += g > 120 and g > red * 2 and g > b * 1.5',
    '    blue += b > 130 and b > red * 2 and b > g * 1.5',
    'print(json.dumps({"green": green, "blue": blue, "pixels": image.width * image.height}))',
  ].join('\n')], {input: png, maxBuffer: 1024 * 1024});
  assert.equal(result.status, 0, result.stderr.toString());
  return JSON.parse(result.stdout.toString());
}

let browser, page, stage = 'launch';
const results = [], errors = [], consoleErrors = [];
(async () => {
  fs.mkdirSync(OUT, {recursive: true});
  const pdf = fixturePdf();
  fs.writeFileSync(path.join(OUT, 'visible-two-page-fixture.pdf'), pdf);
  browser = await chromium.launch({
    executablePath: process.env.PDF_VIEWER_BROWSER_PATH || chromium.executablePath(),
    headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({viewport: {width: 1440, height: 1050}});
  // Stub only the unrelated external QR script. Do not intercept PDF plugin resources.
  await context.route('https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js',
    route => route.fulfill({status: 200, contentType: 'application/javascript', body: ''}));
  context.on('page', entry => {
    entry.on('pageerror', error => errors.push(error.message));
    entry.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  });
  page = await context.newPage();
  page.setDefaultTimeout(15000);
  const json = async response => { assert.ok(response.ok(), await response.text()); return response.json(); };
  stage = 'authenticate and create isolated requirement';
  await json(await context.request.post(BASE + '/api/login', {
    data: {badge: 'TEST-ADMIN', pin: 'only-for-local-tests-12345'},
  }));
  const saved = await json(await context.request.post(BASE + '/api/order-setup', {data: {
    expected_version: 0, purchase_order: 'PDF-VIEW-TEST-' + Date.now(),
    assemblies: [{gpn: 'PDF-VIEW-ASSEMBLY', assembly_quantity: 1,
      spools: [{spool_number: 'PDF-VIEW-SPOOL', quantity_per_assembly: 1, welds_per_spool: 1}]}],
  }}));
  const requirement = saved.assemblies[0].spools[0].id;
  const documentPath = BASE + '/api/spool-documents/requirements/' + requirement;
  let version = 0;
  for (const kind of ['bom', 'isometric']) {
    stage = kind + ' PDF upload';
    const file = {name: 'VISIBLE-' + kind + '.pdf', mimeType: 'application/pdf', buffer: pdf};
    const preview = await json(await context.request.post(documentPath + '/preview', {multipart: {kind, files: file}}));
    assert.equal(preview.page_count, 2);
    const uploaded = await json(await context.request.post(documentPath + '/upload', {multipart: {
      kind, files: file, expected_version: String(version), expected_sha256: preview.selection_sha256,
      reason: 'Synthetic visible two-page browser regression', revision: 'TEST',
    }}));
    version = uploaded.version;
    const doc = uploaded.active[kind];
    assert.equal(doc.page_count, 2);
    const response = await context.request.get(BASE + doc.view_url);
    assert.equal(response.status(), 200);
    assert.equal(response.headers()['content-type'], 'application/pdf');
    assert.equal(response.headers()['content-security-policy'], "frame-ancestors 'self'");
    assert.equal(response.headers()['x-frame-options'], 'SAMEORIGIN');
    const anonymous = await browser.newContext();
    assert.equal((await anonymous.request.get(BASE + doc.view_url)).status(), 401);
    await anonymous.close();
  }
  await page.goto(BASE + '/');
  await page.locator('#workspace').waitFor({state: 'visible'});

  async function capture(targetPage, locator, filename, color) {
    let png, colors;
    for (let attempt = 0; attempt < 20; attempt++) {
      png = locator ? await locator.screenshot() : await targetPage.screenshot();
      colors = pixels(png);
      if (colors[color] > 10000) break;
      await targetPage.waitForTimeout(300);
    }
    fs.writeFileSync(path.join(OUT, filename), png);
    assert.ok(colors[color] > 10000, filename + ': expected actual ' + color + ' PDF page pixels, got ' + JSON.stringify(colors));
    return colors;
  }
  async function renderedPages(targetPage, locator, name) {
    if (locator) await locator.scrollIntoViewIfNeeded();
    const first = await capture(targetPage, locator, name + '-page-1.png', 'green');
    // Scroll inside the real native PDF viewer, until the second page marker appears.
    const bounds = locator ? await locator.boundingBox() : {x: 0, y: 0, ...targetPage.viewportSize()};
    await targetPage.mouse.move(bounds.x + bounds.width * .7, bounds.y + bounds.height * .5);
    let second, png;
    for (let step = 0; step < 8; step++) {
      await targetPage.mouse.wheel(0, 350);
      await targetPage.waitForTimeout(250);
      png = locator ? await locator.screenshot() : await targetPage.screenshot();
      second = pixels(png);
      if (second.blue > 10000) break;
    }
    fs.writeFileSync(path.join(OUT, name + '-page-2.png'), png);
    assert.ok(second.blue > 10000, name + ': second PDF page must visibly render, got ' + JSON.stringify(second));
    results.push({name, page_1: first, page_2: second});
    console.log(JSON.stringify(results.at(-1)));
  }

  for (const kind of ['bom', 'isometric']) {
    stage = kind + ' embedded viewer';
    if (kind === 'bom') {
      await page.evaluate(id => window.FabSpoolDocuments.open({kind: 'requirements', id, tab: 'bom'}), requirement);
    } else {
      await page.locator('#sdoc-tab-isometric').click();
    }
    await page.locator('#spoolDocumentsContent[aria-busy="false"]').waitFor();
    await page.locator('[data-sdoc-action="preview-saved"]').click();
    const iframe = page.locator('#spoolDocumentsDialog iframe');
    await renderedPages(page, iframe, kind + '-embedded');
    stage = kind + ' new tab viewer';
    const popupEvent = context.waitForEvent('page');
    await page.getByRole('link', {name: kind === 'bom' ? 'View BOM' : 'View full isometric', exact: true}).click();
    const popup = await popupEvent;
    await popup.waitForLoadState('load');
    await renderedPages(popup, null, kind + '-new-tab');
    await popup.close();
  }
  await page.locator('#spoolDocumentsClose').click();
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify({status: 'passed', browser: browser.version(),
    checks: ['Authenticated upload/preview for PDF BOM and isometric', 'Anonymous file requests rejected',
      'Both visible pages render inside the actual dialog and in the View link new tab'], results, page_errors: errors, console_errors: consoleErrors}, null, 2));
  fs.rmSync(path.join(OUT, 'failure.json'), {force: true});
  await browser.close(); browser = null;
})().catch(async error => {
  console.error('FAILED', stage, error.stack || error);
  fs.writeFileSync(path.join(OUT, 'failure.json'), JSON.stringify({stage, error: error.message, results, errors, consoleErrors}, null, 2));
  if (browser) await browser.close();
  process.exitCode = 1;
});
