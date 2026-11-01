/* Focused correction check: real physical spool numbers own flow colors.
 * Run only against tests/orders_browser_server.py's disposable loopback DB.
 * Pass --grouping-only for the focused station-transfer, process-board and P.O. check.
 * No deployed host is accepted and no synthetic data leaves the fixture. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const BASE = process.env.ORDERS_TEST_BASE || 'http://127.0.0.1:8782';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(BASE).hostname), 'Disposable loopback fixture only');
const GROUPING_ONLY = process.argv.includes('--grouping-only');
const OUT = process.env.SPOOL_NUMBER_COLORS_TEST_OUT || (GROUPING_ONLY
  ? '/tmp/fabtrace-station-transfer-review' : '/tmp/fabtrace-spool-number-colors-review');
fs.mkdirSync(OUT, {recursive: true});
const NUMBER = '643-777-PCW-03-01';
const BLUE = 'rgb(29, 78, 216)', BLACK = 'rgb(0, 0, 0)', RED = 'rgb(185, 28, 28)';
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
  const color = async (scope, id, expected, description, expectedStage = expected === BLUE ? 'welding' : 'qa_001') => {
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
      assert.equal(value.stage, expectedStage, description + ': stage');
    }
    return values;
  };
  const noOverflow = async () => assert.equal(await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth + 1), false, 'No horizontal page overflow');

  stage = 'create physical copies of the real-format spool number';
  const copyCount = GROUPING_ONLY ? 12 : 2;
  const setup = await api('post', '/api/order-setup', {expected_version: 0,
    purchase_order: 'SPOOL-COLORS-' + Date.now(),
    assemblies: [{gpn: 'COLOR-CHECK-ASSEMBLY', assembly_quantity: 1,
      spools: [{spool_number: NUMBER, quantity_per_assembly: copyCount, welds_per_spool: 0}]}]});
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
  assert.equal(labels.items.length, copyCount);
  const copies = labels.items.slice().sort((a, b) => a.display_code.localeCompare(b.display_code, undefined, {numeric: true}));
  const first = copies[GROUPING_ONLY ? 1 : 0], second = copies[GROUPING_ONLY ? 2 : 1];
  const inventory = GROUPING_ONLY ? copies.filter(copy => copy.id !== first.id) : [];
  assert.notEqual(first.id, second.id); assert.notEqual(first.display_code, second.display_code);
  const acceptArrival = async item => {
    const materialBase = '/api/spool-boms/spools/' + item.id;
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
  };
  if (GROUPING_ONLY) {
    seedComplete = true;
    const expectedTransfers = [];
    const expectedScanAudit = {method: 'POST', path: '/api/items/' + first.id + '/scan'};
    const expectedBrowserWrites = [expectedScanAudit];
    const states = async () => (await api('get', '/api/order-labels/' + project + '/labels')).items
      .map(item => ({id: item.id, stage: item.flow_stage.key, color: item.flow_stage.color}))
      .sort((a, b) => a.id.localeCompare(b.id));
    const expectedStates = currentStage => copies.map(copy => ({id: copy.id,
      stage: copy.id === first.id ? currentStage : 'inventory',
      color: copy.id === first.id && currentStage === 'preparation' ? 'red' : 'black'}))
      .sort((a, b) => a.id.localeCompare(b.id));

    stage = 'fresh pending physical copies remain Inventory and QR reads do not move them';
    assert.deepEqual(await states(), expectedStates('inventory'), 'New copies start Inventory even while arrival QA is pending');
    const untouched = await api('get', '/api/items/' + first.id);
    assert.equal(untouched.transfer.version, 0);
    assert.equal(untouched.released, false);
    const pending = await api('get', '/api/spool-boms/spools/' + first.id);
    assert.equal(pending.arrival.can_proceed, false, 'Fresh Inventory does not imply arrival QA approval');
    await panel('flowContent', 'flow=1&project=' + project);
    const freshBoard = page.locator('#flowContent .fst-process-board');
    assert.equal(await freshBoard.locator('section[data-spool-process="inventory"] li[data-process-spool]').count(), copies.length);
    assert.equal(await freshBoard.locator('section:not([data-spool-process="inventory"]) li[data-process-spool]').count(), 0,
      'Fresh physical copies must not be auto-assigned to QA/QC-001');
    assert.ok(await freshBoard.locator('.fst-text[data-spool-id]').evaluateAll(nodes => nodes.length === 12
      && nodes.every(node => node.dataset.flowStage === 'inventory' && getComputedStyle(node).color === 'rgb(0, 0, 0)')),
    'Every new physical alias is visibly black in Inventory');
    await page.goto(BASE + '/?spool=' + encodeURIComponent(first.display_code));
    await page.locator('#itemPage:not(.hidden)').waitFor();
    assert.equal(await page.evaluate(() => current.id), first.id, 'QR alias resolves the exact physical copy');
    await color(page.locator('#itemPage'), first.id, BLACK, 'Opening QR leaves Inventory number black', 'inventory');
    await page.goto(BASE + '/?handoff=1&item=' + encodeURIComponent(first.display_code));
    await color(page.locator('#handoffItemInfo'), first.id, BLACK, 'Reading scan and handoff leaves Inventory number black', 'inventory');
    assert.equal((await api('get', '/api/items/' + first.id)).transfer.version, 0,
      'Opening an item or QR never records a station transfer');
    assert.deepEqual(await states(), expectedStates('inventory'));
    assert.deepEqual(writes, expectedBrowserWrites,
      'Opening a QR may append its existing scan audit, but must not record a station transfer');
    checks.push('All 12 new pending copies stay Inventory black; opening an exact QR alias and handoff screen leaves their stations and transfer versions unchanged');

    const transferViaQr = async (location, workStatus, receiver, expectedStage) => {
      const before = await api('get', '/api/items/' + first.id);
      await page.goto(BASE + '/?handoff=1&item=' + encodeURIComponent(first.display_code));
      await page.locator('#handoffItemInfo .fst-text[data-spool-id="' + first.id + '"]').waitFor();
      for (const [role, badge] of [['Sender', before.transfer.handler], ['Receiver', receiver]]) {
        await page.locator('#handoff' + role).focus();
        await page.goto(BASE + '/?badge=' + encodeURIComponent(badge));
        await page.locator('#handoff' + role + 'Info[data-state="valid"]').waitFor();
      }
      await page.locator('#handoffLocation').selectOption(location);
      await page.locator('#handoffStatus').selectOption(workStatus);
      await page.locator('#handoffNotes').fill('Synthetic recorded station transfer for ' + first.display_code);
      assert.deepEqual(writes, expectedBrowserWrites, 'Scanning both employee QR badges does not move the spool');
      const responsePromise = page.waitForResponse(response => response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/api/items/' + first.id + '/transfer');
      const expectedTransfer = {method: 'POST', path: '/api/items/' + first.id + '/transfer'};
      expectedTransfers.push(expectedTransfer);
      expectedBrowserWrites.push(expectedTransfer);
      await page.locator('#handoffConfirm').click();
      const response = await responsePromise;
      assert.ok(response.ok(), await response.text());
      const payload = response.request().postDataJSON(), result = await response.json();
      assert.equal(payload.location_id, location);
      assert.equal(payload.scan_method, 'employee_qr', 'Actual badge QR route records the handoff');
      assert.equal(payload.expected_transfer_version, before.transfer.version);
      assert.equal(result.id, first.id);
      assert.equal(result.transfer.version, before.transfer.version + 1);
      assert.equal(result.flow_stage.key, expectedStage);
      assert.equal(result.released, false, 'Station movement never grants QA release');
      await page.getByText('Transfer recorded for ' + first.display_code + '. Scan the next item and both badges.', {exact: true}).waitFor();
      assert.deepEqual(await states(), expectedStates(expectedStage), 'Only the transferred physical copy changes station');
      assert.equal((await api('get', '/api/flow/items/' + first.id)).flow, null,
        'Station transfer never starts or advances a numbered traveler');
    };

    stage = 'actual QA/QC-001 station transfer changes only its exact physical copy';
    await transferViaQr('qa_001', 'awaiting_inspection', 'TEST-QA', 'qa_001');
    assert.equal((await api('get', '/api/spool-boms/spools/' + first.id)).arrival.can_proceed, false,
      'Moving to QA/QC-001 leaves pending receiving checks intact');
    checks.push('Recording the QR station handoff moves only [002] to QA/QC-001 black and preserves pending arrival QA and unreleased state');

    stage = 'arrival evidence does not move station; actual Prep/Fabrication transfer turns only [002] red';
    await acceptArrival(first);
    assert.deepEqual(await states(), expectedStates('qa_001'), 'Approval of arrival evidence alone does not move the recorded station');
    await transferViaQr('fabrication_prep', 'queued', 'TEST-HANDLER', 'preparation');
    assert.equal((await api('get', '/api/spool-boms/spools/' + first.id)).arrival.can_proceed, true,
      'A station handoff preserves the explicitly recorded arrival approval');
    checks.push('After explicitly recorded synthetic arrival approval, [002] stays QA/QC-001 until a second QR handoff moves it to Prep/Fabrication red; all other copies remain Inventory black');

    const stageKeys = ['inventory', 'qa_001', 'preparation', 'qa_002', 'floor', 'welding',
      'qa_003', 'testing', 'paint', 'qa_004', 'ready_to_ship'];
    const expected = copies.map(copy => ({id: copy.id, alias: copy.display_code,
      stage: copy.id === first.id ? 'preparation' : 'inventory',
      color: copy.id === first.id ? RED : BLACK}));
    const byId = new Map(expected.map(copy => [copy.id, copy]));
    const snapshots = {};
    const neutralStations = async (scope, description, minimum = 1) => {
      const labels = await scope.locator('.fst-station[data-station-stage]').evaluateAll(nodes =>
        nodes.map(node => ({label: node.textContent, stage: node.dataset.stationStage,
          color: getComputedStyle(node).color,
          semanticColor: node.matches('.fst-text,[class*="fst-color-"]')
            || Boolean(node.querySelector('.fst-text,[class*="fst-color-"]'))})));
      assert.ok(labels.length >= minimum, description + ': station labels are present');
      for (const label of labels) {
        assert.equal(label.color, 'rgb(51, 65, 85)', description + ': neutral station text ' + JSON.stringify(label));
        assert.equal(label.semanticColor, false, description + ': spool colors must not style station names');
      }
      return labels;
    };
    const readBoard = board => board.locator('section[data-spool-process]').evaluateAll(groups =>
      groups.map(group => ({stage: group.dataset.spoolProcess,
        items: [...group.querySelectorAll('li[data-process-spool]')].map(row => {
          const label = row.querySelector('.fst-text[data-spool-id]');
          return {id: row.dataset.processSpool, alias: label?.textContent,
            label_id: label?.dataset.spoolId, stage: label?.dataset.flowStage,
            number: label?.dataset.spoolNumber, color: label && getComputedStyle(label).color};
        })})));
    const verifyBoard = async (board, description, wanted = expected) => {
      const groups = await readBoard(board), rows = groups.flatMap(group => group.items);
      assert.deepEqual(groups.map(group => group.stage), stageKeys, description + ': eleven distinct process buckets in order');
      assert.equal(rows.length, wanted.length, description + ': one row for every physical copy');
      assert.equal(new Set(rows.map(row => row.id)).size, rows.length, description + ': no duplicate physical copies');
      assert.deepEqual(rows.map(row => row.id).sort(), wanted.map(copy => copy.id).sort(),
        description + ': no omitted or invented physical copies');
      for (const group of groups) {
        const aliases = group.items.map(row => row.alias);
        assert.deepEqual(aliases, aliases.slice().sort((a, b) => a.localeCompare(b, undefined, {numeric: true})),
          description + ': natural copy-number order within ' + group.stage);
        for (const row of group.items) {
          const copy = byId.get(row.id);
          assert.equal(group.stage, copy.stage, description + ': correct process bucket for ' + copy.alias);
          assert.equal(row.stage, copy.stage, description + ': spool-number stage agrees with its bucket');
          assert.equal(row.alias, copy.alias, description + ': immutable physical alias is shown in full');
          assert.equal(row.label_id, copy.id, description + ': readable label retains the actual Item ID');
          assert.equal(row.number, NUMBER, description + ': readable alias retains the base spool number');
          assert.equal(row.color, copy.color, description + ': computed text color for ' + copy.alias);
        }
      }
      return groups;
    };
    for (const surface of [
      {name: 'process', host: 'flowContent', query: 'flow=1&project=' + project,
        search: '#flowSearch', button: 'data-flow-spool', chosen: first},
      {name: 'production-progress', host: 'productionProgressContent',
        query: 'production-progress=1&project=' + project, search: '#ppSearch',
        button: 'data-pp-spool', chosen: inventory[0]},
    ]) {
      stage = surface.name + ': individual copies grouped by current process';
      await page.setViewportSize({width: 1440, height: 1000});
      await panel(surface.host, surface.query);
      const board = page.locator('#' + surface.host + ' .fst-process-board');
      await board.waitFor({state: 'visible'});
      assert.equal(await board.count(), 1, 'Exactly one current-process board per view');
      snapshots[surface.name] = await verifyBoard(board, surface.name);
      await neutralStations(board, surface.name + ' process headings', 11);
      await neutralStations(page.locator('#' + surface.host + ' .fst-legend'), surface.name + ' color key', 7);
      await noOverflow();
      await board.scrollIntoViewIfNeeded();
      await page.screenshot({path: path.join(OUT, surface.name + '-groups-desktop.png'), fullPage: false});
      checks.push(surface.name + ': all 12 physical aliases appear exactly once in their naturally sorted recorded station; [002] is Prep/Fabrication red and the other copies Inventory black, while station headings and color-key labels stay neutral');

      stage = surface.name + ': 390px process board fit';
      await page.setViewportSize({width: 390, height: 844});
      await noOverflow();
      assert.ok(await board.evaluate(el => el.scrollWidth <= el.clientWidth + 1),
        surface.name + ': process board must fit the mobile viewport');
      assert.ok(await board.locator('li[data-process-spool]').evaluateAll(rows => rows.every(row => {
        const rect = row.getBoundingClientRect();
        return rect.left >= -1 && rect.right <= innerWidth + 1 && row.scrollWidth <= row.clientWidth + 1;
      })), surface.name + ': every physical spool row fits without clipping');
      await verifyBoard(board, surface.name + ' mobile');
      await neutralStations(board, surface.name + ' mobile headings', 11);
      await board.locator('section[data-spool-process="inventory"]').scrollIntoViewIfNeeded();
      await page.screenshot({path: path.join(OUT, surface.name + '-inventory-mobile.png'), fullPage: false});
      checks.push(surface.name + ': all exact copy labels remain correctly colored and unclipped at 390px');

      stage = surface.name + ': exact physical alias search and navigation';
      await page.locator(surface.search).fill(surface.chosen.display_code);
      await page.waitForFunction(host => document.querySelectorAll('#' + host +
        ' .fst-process-board li[data-process-spool]').length === 1, surface.host);
      await verifyBoard(board, surface.name + ' exact-alias search', [byId.get(surface.chosen.id)]);
      await board.locator('button[' + surface.button + '="' + surface.chosen.id + '"]').click();
      await page.locator('#flowContent[aria-busy="false"]').waitFor();
      assert.equal(new URL(page.url()).searchParams.get('item'), surface.chosen.id,
        surface.name + ': readable physical alias opens its exact internal process record');
      assert.equal(await page.locator('#flowContent .ff-head h1 .fst-text[data-spool-id="' + surface.chosen.id + '"]').count(), 1,
        surface.name + ': selected process detail retains physical identity');
      await neutralStations(page.locator('#flowContent .fst-flow'), surface.name + ' detail flow catalog', 11);
      checks.push(surface.name + ': searching the full copy alias retains only that copy, and clicking opens its exact internal Item ID');
    }
    assert.deepEqual(snapshots.process, snapshots['production-progress'],
      'Process and Production Progress agree on every physical copy, bucket, order and computed color');

    stage = 'saved Purchase Order shows every physical copy and its own color without expanding copies';
    await page.setViewportSize({width: 1440, height: 1000});
    await panel('orderSetupContent', 'order-setup=1&po=' + project);
    const po = page.locator('#orderSetupContent');
    const verifyPO = async description => {
      const rows = await po.locator('[data-os-physical-spool]').evaluateAll(nodes => nodes.map(node => {
        const label = node.querySelector('.fst-text[data-spool-id]'), station = node.querySelector('.os-copy-status .fst-station'),
          colorName = node.querySelector('.os-copy-color');
        return {id: node.dataset.osPhysicalSpool, alias: label?.textContent, color: label && getComputedStyle(label).color,
          station: station?.dataset.stationStage, colorName: colorName?.textContent,
          colorNameColor: colorName && getComputedStyle(colorName).color,
          hidden: !node.getClientRects().length || Boolean(node.closest('details:not([open])'))};
      }));
      assert.equal(rows.length, copies.length, description + ': every physical copy is in the saved P.O.');
      assert.equal(new Set(rows.map(row => row.id)).size, copies.length, description + ': no duplicate physical copies');
      assert.deepEqual(rows.map(row => row.alias), expected.map(copy => copy.alias), description + ': natural copy order');
      for (const row of rows) {
        const copy = byId.get(row.id);
        assert.ok(copy, description + ': no invented copies');
        assert.equal(row.hidden, false, description + ': ' + row.alias + ' is visible without a copy toggle');
        assert.equal(row.alias, copy.alias);
        assert.equal(row.station, copy.stage);
        assert.equal(row.color, copy.color, description + ': computed number color for ' + copy.alias);
        assert.equal(row.colorName, 'Text color: ' + (copy.color === RED ? 'Red' : 'Black'));
        assert.ok(![RED, BLUE, 'rgb(253, 224, 71)', 'rgb(185, 75, 0)', 'rgb(190, 24, 93)', 'rgb(21, 128, 61)'].includes(row.colorNameColor),
          description + ': the descriptive color name remains neutral');
      }
      assert.equal(await po.locator('details.os-copy-flow').count(), 0, 'Copies are not hidden in a dropdown');
      assert.equal(await po.locator('[data-os-planned-number="' + NUMBER + '"].fst-text').count(), 0,
        'A planned shared spool number is not assigned one copy color');
      assert.notEqual(await po.locator('[data-os-planned-number="' + NUMBER + '"]').evaluate(node => getComputedStyle(node).color), RED,
        'The shared planned number does not inherit the transferred copy\'s red color');
      await neutralStations(po.locator('.os-copy-status'), description + ' per-copy station labels', copies.length);
      await neutralStations(po.locator('.fst-legend'), description + ' color key', 7);
      await noOverflow();
    };
    await verifyPO('Desktop Purchase Order');
    await po.locator('[data-os-physical-spool="' + copies[0].id + '"]').scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(OUT, 'purchase-order-copies-desktop.png'), fullPage: false});
    await page.setViewportSize({width: 390, height: 844});
    await verifyPO('390px Purchase Order');
    assert.ok(await po.locator('[data-os-physical-spool]').evaluateAll(nodes => nodes.every(node => {
      const rect = node.getBoundingClientRect();
      return rect.left >= -1 && rect.right <= innerWidth + 1 && node.scrollWidth <= node.clientWidth + 1;
    })), 'Mobile P.O. copy labels fit without horizontal clipping');
    await po.locator('[data-os-physical-spool="' + copies[0].id + '"]').scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(OUT, 'purchase-order-copies-mobile.png'), fullPage: false});
    checks.push('Saved Purchase Order shows all 12 individual aliases without copy toggles on desktop and 390px, with correct per-copy number colors, neutral station labels, explicit color names and a plain shared planned number');
    await po.locator('button[data-os-action="physical-spool"][data-os-id="' + first.id + '"]').click();
    await page.locator('#itemPage:not(.hidden)').waitFor();
    assert.equal(await page.evaluate(() => current.id), first.id, 'Purchase Order opens the exact selected physical copy');
    await color(page.locator('#itemPage'), first.id, RED, 'P.O. to selected red physical copy', 'preparation');
    checks.push('The visible P.O. copy button opens the exact physical record with its current red number color');

    assert.deepEqual(errors, [], 'No browser page errors');
    assert.deepEqual(writes, expectedBrowserWrites,
      'Only the existing QR scan audit and two explicitly recorded synthetic QR transfers may write during browser navigation');
    const report = {status: 'passed', mode: 'grouping-only', checks, project_id: project,
      spools: expected, page_errors: errors, recorded_transfers: expectedTransfers,
      qr_scan_audits: [expectedScanAudit], unexpected_writes: [], artifacts: OUT};
    fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    await browser.close();
    return;
  }

  // The broader color check retains its welding/QA pair, with actual recorded
  // station transfers; starting a numbered traveler alone no longer colors it.
  await acceptArrival(first);
  await api('post', '/api/flow/items/' + first.id + '/start', {route: 'spool', expected_children: 0,
    material_reference: 'LOCAL-KITTED-MATERIALS', start_step: 13,
    baseline_reference: 'LOCAL-CONTROLLED-BASELINE',
    baseline_reason: 'Synthetic existing spool at process welding, prior history remains unrecorded'});
  for (const [copy, location, status] of [[first, 'welding', 'in_progress'], [second, 'qa_001', 'awaiting_inspection']]) {
    const current = await api('get', '/api/items/' + copy.id);
    await api('post', '/api/items/' + copy.id + '/transfer', {sender_badge: current.handler,
      handler: current.handler, location_id: location, operational_status: status,
      expected_transfer_version: current.transfer.version, expected_handler: current.handler,
      scan_method: 'employee_qr', notes: 'Synthetic recorded physical station handoff'});
  }
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
      assert.equal(await page.locator('#orderSetupContent details.os-copy-flow').count(), 0,
        'Physical copies must be visible without a copy dropdown');
    }
    await color(page.locator('#' + host), first.id, BLUE, query + ' first copy');
    await color(page.locator('#' + host), second.id, BLACK, query + ' second copy');
    if (host === 'orderSetupContent') {
      const common = page.locator('#orderSetupContent [data-os-planned-number="' + NUMBER + '"]');
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
