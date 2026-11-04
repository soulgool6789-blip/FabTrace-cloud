/* Contextual navigation contracts without a browser or network. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/navigation.js'), 'utf8');

function harness(role = 'admin', url = 'https://example.test/') {
  const elements = new Map(), calls = [], messages = [];
  function node(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {id, textContent: '', disabled: false, title: {textContent: ''},
        classList: {add: value => classes.add(value), contains: value => classes.has(value),
          toggle(value, on) {if (on ?? !classes.has(value)) classes.add(value); else classes.delete(value);}},
        querySelector: selector => selector === 'h1' ? elements.get(id).title : null,
        querySelectorAll: () => [], contains: () => false, removeAttribute(){}, focus(){}});
    }
    return elements.get(id);
  }
  const location = {href: url, origin: new URL(url).origin};
  const flowDefaults = {project: '', subproject: '', query: '', status: '', step: ''};
  const inspectionDefaults = {inspection: 'QA-001', project: '', query: '', status: ''};
  const failureDefaults = {inspection: '', project: '', query: '', status: ''};
  const state = {flow: {...flowDefaults}, inspections: {...inspectionDefaults}, failures: {...failureDefaults}, item: '', blocked: false};
  const context = {URL, URLSearchParams, console, location, me: {role}, document: {getElementById: node, addEventListener(){}},
    history: {replaceState(data, title, next) {if (next != null) location.href = new URL(next, location.href).href;}},
    MutationObserver: class {observe(){}}, queueMicrotask, scrollY: 0, scrollTo(){},
    notify: message => messages.push(message)};
  context.window = context;
  function show(page) {
    if (context.FabNavigation.beforeShow(page) === false) return false;
    context.FabNavigation.afterShow(page);
    return true;
  }
  context.FabOrderSetup = {navigationState: () => null, async open(options = {}) {
    if (!show('orderSetupPage')) return;
    calls.push({name: 'orders', options: {...options}});node('orderSetupPage').title.textContent = 'Orders';
    context.history.replaceState(null, '', '/?order-setup=1');
  }};
  context.FabGuide = {async open(options = {}) {
    if (!show('guidePage')) return;
    calls.push({name: 'guide', options: {...options}});node('guidePage').title.textContent = 'Guide & setup';
    context.history.replaceState(null, '', '/?guide=1');
  }};
  context.FabFlow = {navigationState: () => ({...state.flow}), canNavigateAway: () => !state.blocked,
    async open(options = {}) {
      if (!show('flowPage')) return;
      calls.push({name: 'flow', options: {...options}});
      state.flow = {...(options.resetFilters ? flowDefaults : state.flow), ...Object.fromEntries(Object.entries(options).filter(([key]) => key in flowDefaults))};
      state.item = options.item || '';
      node('flowPage').title.textContent = state.item ? 'Requirements · ' + state.item : 'Fabrication process flow';
      const query = new URLSearchParams({flow: '1'});
      if (state.flow.project) query.set('project', state.flow.project);
      if (state.item) query.set('item', state.item);
      context.history.replaceState(null, '', '/?' + query);
    }};
  context.FabInspections = {navigationState: () => ({...state.inspections}), async open(options = {}) {
    if (!show('inspectionsPage')) return;
    calls.push({name: 'inspections', options: {...options}});
    state.inspections = {...inspectionDefaults, ...Object.fromEntries(Object.entries(options).filter(([key]) => key in inspectionDefaults))};
    node('inspectionsPage').title.textContent = 'Inspections';
    const query = new URLSearchParams({inspections: '1', inspection: state.inspections.inspection});
    if (state.inspections.project) query.set('project', state.inspections.project);
    if (state.inspections.query) query.set('q', state.inspections.query);
    if (state.inspections.status) query.set('status', state.inspections.status);
    context.history.replaceState(null, '', '/?' + query);
  }};
  context.FabInspectionFailures = {navigationState: () => ({...state.failures}), async open(options = {}) {
    if (!show('inspectionFailuresPage')) return;
    calls.push({name: 'inspection-failures', options: {...options}});
    state.failures = {...failureDefaults, ...Object.fromEntries(Object.entries(options).filter(([key]) => key in failureDefaults))};
    node('inspectionFailuresPage').title.textContent = 'Failed Inspections';
    const query = new URLSearchParams({'inspection-failures': '1'});
    if (state.failures.inspection) query.set('inspection', state.failures.inspection);
    if (state.failures.project) query.set('project', state.failures.project);
    if (state.failures.query) query.set('q', state.failures.query);
    if (state.failures.status) query.set('status', state.failures.status);
    context.history.replaceState(null, '', '/?' + query);
  }};
  node('navOrders').onclick = () => context.FabOrderSetup.open();
  vm.createContext(context);vm.runInContext(source, context, {filename: 'navigation.js'});
  return {context, node, calls, messages, state, query: () => new URL(location.href).searchParams};
}

(async () => {
  const checks = [];
  {
    const h = harness();
    await h.context.FabOrderSetup.open();
    await h.context.FabFlow.open({project: 'PO-1', subproject: 'AREA-2', query: 'SPOOL-3', status: 'active', step: '14'});
    assert.equal(h.node('navFlow').classList.contains('primary'), true);
    await h.context.FabGuide.open();
    await h.context.FabNavigation.back();
    const restored = h.calls.at(-1).options;
    for (const [key, value] of Object.entries({project: 'PO-1', subproject: 'AREA-2', query: 'SPOOL-3', status: 'active', step: '14'})) assert.equal(restored[key], value, 'Restore ' + key);
    assert.equal(restored.resetFilters, false);
    for (const key of ['view', 'workScope', 'workPage']) assert.equal(Object.hasOwn(restored, key), false, 'Do not restore removed ' + key);
    assert.equal(h.query().get('view'), null);
    assert.equal(h.query().get('work_scope'), null);
    await h.context.FabFlow.open({item: 'ASM-1'});
    assert.equal(h.node('navFlow').classList.contains('primary'), true, 'Item process details keep Process flow selected');
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('item'), null);
    assert.equal(h.state.flow.query, 'SPOOL-3');
    await h.context.FabFlow.open({project: 'PO-2', resetFilters: true});
    assert.equal(h.node('navFlow').classList.contains('primary'), true);
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('project'), 'PO-1');
    assert.equal(h.state.flow.query, 'SPOOL-3');
    checks.push('Process flow retains project, subproject, search, status and step filters across other pages, item details and project changes');
  }
  {
    const h = harness('painter', 'https://example.test/?flow=1&view=work&work_scope=custody&project=PO-1&item=ASM-1');
    await h.context.FabFlow.open({view: 'work', workScope: 'custody', project: 'PO-1', item: 'ASM-1'});
    assert.match(h.node('navBack').textContent, /Back to Process flow/);
    assert.equal(h.query().get('view'), null);
    assert.equal(h.query().get('work_scope'), null);
    assert.equal(h.node('navFlow').classList.contains('primary'), true);
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('item'), null);
    assert.equal(h.query().get('project'), 'PO-1');
    assert.equal(h.query().get('view'), null);
    assert.equal(h.query().get('work_scope'), null);
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('project'), null);
    assert.equal(h.query().get('flow'), '1');
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('order-setup'), '1');
    for (let index = 0; index < 3; index++) await h.context.FabNavigation.back();
    assert.equal(h.context.FabNavigation.state().depth, 0);
    assert.equal(h.query().get('order-setup'), '1');
    assert.equal(h.query().get('view'), null);
    assert.equal(h.query().get('work_scope'), null);
    checks.push('Former work-item links open ordinary Process flow, retain item/project parents and return employees to Orders without a Back loop');
  }
  for (const role of ['admin', 'supervisor', 'handler', 'painter', 'inspector', 'ndt']) {
    const h = harness(role, 'https://example.test/?flow=1&item=ASM-1');
    await h.context.FabFlow.open({item: 'ASM-1'});
    await h.context.FabNavigation.back();
    assert.equal(h.calls.at(-1).options.view, undefined);
    assert.equal(h.node('navFlow').classList.contains('primary'), true);
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('order-setup'), '1');
  }
  checks.push('All flow pages highlight Process flow, and Orders is the home destination for management and floor roles');
  {
    const h = harness('inspector');
    await h.context.FabOrderSetup.open();
    await h.context.FabInspections.open({inspection: 'QA-005', project: 'PO-1', query: 'SPOOL-[002]', status: 'current'});
    assert.equal(h.node('navInspections').classList.contains('primary'), true);
    assert.equal(h.node('navFlow').classList.contains('primary'), false);
    assert.equal(h.node('moreTools').classList.contains('fn-selected'), false);
    await h.context.FabFlow.open({item: 'ASM-PRESSURE', project: 'PO-1'});
    assert.equal(h.node('navInspections').classList.contains('primary'), false);
    await h.context.FabNavigation.back();
    assert.equal(h.calls.at(-1).name, 'inspections');
    for (const [key, value] of Object.entries({inspection: 'QA-005', project: 'PO-1', query: 'SPOOL-[002]', status: 'current'})) assert.equal(h.state.inspections[key], value, 'Restore inspection ' + key);
    assert.equal(h.query().get('q'), 'SPOOL-[002]');
    assert.equal(h.query().get('inspection'), 'QA-005');
    assert.equal(h.node('navInspections').classList.contains('primary'), true);
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('order-setup'), '1');
    const linked = harness('inspector', 'https://example.test/?inspections=1&inspection=QA-006&project=PO-2&q=FINAL&status=attention');
    await linked.context.FabInspections.open({inspection: 'QA-006', project: 'PO-2', query: 'FINAL', status: 'attention'});
    await linked.context.FabNavigation.back();
    assert.equal(linked.query().get('inspections'), '1');
    assert.equal(linked.state.inspections.project, '');
    assert.equal(linked.state.inspections.query, '');
    assert.equal(linked.state.inspections.status, '');
    await linked.context.FabNavigation.back();
    assert.equal(linked.query().get('order-setup'), '1');
    checks.push('Inspections is a primary screen; Back from an exact assembly restores its inspection category, project, search and status, while direct links have a safe unfiltered parent');
  }
  {
    const h = harness('handler');
    await h.context.FabOrderSetup.open();
    await h.context.FabInspectionFailures.open({inspection: 'QA-005', project: 'PO-1', query: 'SPOOL-[002]', status: 'awaiting_reinspection'});
    assert.equal(h.node('navInspectionFailures').classList.contains('primary'), true);
    assert.equal(h.node('navInspections').classList.contains('primary'), false);
    assert.equal(h.node('moreTools').classList.contains('fn-selected'), false);
    await h.context.FabFlow.open({item: 'ASM-FAILED-PRESSURE', project: 'PO-1'});
    assert.equal(h.node('navInspectionFailures').classList.contains('primary'), false);
    await h.context.FabNavigation.back();
    assert.equal(h.calls.at(-1).name, 'inspection-failures');
    for (const [key, value] of Object.entries({inspection: 'QA-005', project: 'PO-1', query: 'SPOOL-[002]', status: 'awaiting_reinspection'})) assert.equal(h.state.failures[key], value, 'Restore failed-inspection ' + key);
    assert.equal(h.query().get('inspection-failures'), '1');
    assert.equal(h.node('navInspectionFailures').classList.contains('primary'), true);
    await h.context.FabNavigation.back();assert.equal(h.query().get('order-setup'), '1');
    const linked = harness('inspector', 'https://example.test/?inspection-failures=1&inspection=QA-006&project=PO-2&q=COATING&status=needs_rework');
    await linked.context.FabInspectionFailures.open({inspection: 'QA-006', project: 'PO-2', query: 'COATING', status: 'needs_rework'});
    await linked.context.FabNavigation.back();
    assert.equal(linked.query().get('inspection-failures'), '1');
    for (const key of ['project', 'query', 'status']) assert.equal(linked.state.failures[key], '');
    await linked.context.FabNavigation.back();assert.equal(linked.query().get('order-setup'), '1');
    checks.push('Failed Inspections is a separate primary screen; opening the responsible assembly and returning preserves failure filters, with a safe direct-link parent');
  }
  {
    const h = harness('painter');
    await h.context.FabFlow.open({project: 'PO-1'});
    h.state.blocked = true;
    const before = h.calls.length;
    assert.equal(await h.context.FabGuide.open(), false);
    assert.equal(h.calls.length, before);
    assert.equal(h.query().get('flow'), '1');
    assert.equal(h.query().get('project'), 'PO-1');
    checks.push('The existing save/navigation guard still protects the process screen');
  }
  console.log(JSON.stringify({status: 'passed', contracts: checks.length, checks}, null, 2));
})().catch(error => {console.error(error);process.exitCode = 1;});

