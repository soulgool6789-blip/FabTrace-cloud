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
  const flowDefaults = {view: 'board', workScope: 'position', project: '', subproject: '', query: '', status: '', step: ''};
  const state = {flow: {...flowDefaults}, item: '', blocked: false};
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
      node('flowPage').title.textContent = state.item ? 'Requirements · ' + state.item : state.flow.view === 'work' ? 'My work' : 'Fabrication process flow';
      const query = new URLSearchParams({flow: '1'});
      if (state.flow.project) query.set('project', state.flow.project);
      if (state.item) query.set('item', state.item);
      if (state.flow.view === 'work') {query.set('view', 'work');query.set('work_scope', state.flow.workScope);}
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
    await h.context.FabFlow.open({view: 'work', workScope: 'custody', project: 'PO-1', subproject: 'AREA-2', query: 'SPOOL-3', status: 'active', step: '14'});
    assert.equal(h.node('navMyWork').classList.contains('primary'), true);
    assert.equal(h.node('navFlow').classList.contains('primary'), false);
    await h.context.FabGuide.open();
    await h.context.FabNavigation.back();
    const restored = h.calls.at(-1).options;
    for (const [key, value] of Object.entries({view: 'work', workScope: 'custody', project: 'PO-1', subproject: 'AREA-2', query: 'SPOOL-3', status: 'active', step: '14'})) assert.equal(restored[key], value, 'Restore ' + key);
    assert.equal(restored.resetFilters, false);
    assert.equal(h.query().get('view'), 'work');
    assert.equal(h.query().get('work_scope'), 'custody');
    await h.context.FabFlow.open({item: 'ASM-1'});
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('item'), null);
    assert.equal(h.query().get('work_scope'), 'custody');
    assert.equal(h.state.flow.query, 'SPOOL-3');
    await h.context.FabFlow.open({view: 'board', resetFilters: true});
    assert.equal(h.node('navMyWork').classList.contains('primary'), false);
    assert.equal(h.node('navFlow').classList.contains('primary'), true);
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('view'), 'work');
    assert.equal(h.query().get('work_scope'), 'custody');
    assert.equal(h.state.flow.query, 'SPOOL-3');
    checks.push('My work retains scope and all module filters across other pages, item detail, and the separate process board');
  }
  {
    const h = harness('painter', 'https://example.test/?flow=1&view=work&work_scope=custody&project=PO-1&item=ASM-1');
    await h.context.FabFlow.open({view: 'work', workScope: 'custody', project: 'PO-1', item: 'ASM-1'});
    assert.match(h.node('navBack').textContent, /Back to My work/);
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('item'), null);
    assert.equal(h.query().get('project'), 'PO-1');
    assert.equal(h.query().get('view'), 'work');
    assert.equal(h.query().get('work_scope'), 'custody');
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('project'), null);
    assert.equal(h.query().get('work_scope'), 'custody');
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('work_scope'), 'position');
    for (let index = 0; index < 3; index++) await h.context.FabNavigation.back();
    assert.equal(h.context.FabNavigation.state().depth, 0);
    assert.equal(h.query().get('view'), 'work');
    assert.equal(h.query().get('work_scope'), 'position');
    checks.push('Direct work-item links preserve scope through parent views and return floor employees to My work without a Back loop');
  }
  for (const role of ['admin', 'supervisor']) {
    const h = harness(role, 'https://example.test/?flow=1&item=ASM-1');
    await h.context.FabFlow.open({item: 'ASM-1'});
    await h.context.FabNavigation.back();
    assert.equal(h.calls.at(-1).options.view, 'board');
    assert.equal(h.node('navFlow').classList.contains('primary'), true);
    await h.context.FabNavigation.back();
    assert.equal(h.query().get('order-setup'), '1');
  }
  checks.push('Existing process-flow deep links use the board, and administrator/Shop Foreman home remains Orders');
  {
    const h = harness('painter');
    await h.context.FabFlow.open({view: 'work', workScope: 'position'});
    h.state.blocked = true;
    const before = h.calls.length;
    assert.equal(await h.context.FabGuide.open(), false);
    assert.equal(h.calls.length, before);
    assert.equal(h.query().get('view'), 'work');
    checks.push('The existing save/navigation guard still protects the work screen');
  }
  console.log(JSON.stringify({status: 'passed', contracts: checks.length, checks}, null, 2));
})().catch(error => {console.error(error);process.exitCode = 1;});
