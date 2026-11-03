/* Bulk employee badge selection and printing contracts. No network or browser. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/employee-badges.js'), 'utf8');
new vm.Script(source, {filename: 'employee-badges.js'});
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const unescape = value => String(value ?? '').replace(/&(amp|lt|gt|quot|#39);/g, (_, c) => ({amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"}[c]));
const employee = (badge, fields = {}) => ({badge, name: `Employee ${badge}`, role: 'supervisor', role_label: 'Shop Foreman', active: true, ...fields});
const attributes = html => {
  const result = {};
  for (const match of html.matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) result[match[1]] = unescape(match[2] ?? match[3] ?? match[4] ?? '');
  return result;
};

function element(id = '', attrs = {}) {
  const listeners = new Map(), classes = new Set();
  const node = {id, attrs, dataset: {}, children: [], value: attrs.value || '', checked: 'checked' in attrs,
    disabled: 'disabled' in attrs, hidden: false, open: false, textContent: '', style: {}, parentElement: null,
    classList: {add: (...names) => names.forEach(n => classes.add(n)), remove: (...names) => names.forEach(n => classes.delete(n)),
      contains: name => classes.has(name), toggle(name, force) {const on = force ?? !classes.has(name); on ? classes.add(name) : classes.delete(name); return on;}},
    getAttribute: name => attrs[name] ?? null,
    setAttribute(name, value) {attrs[name] = String(value); if (name === 'disabled') node.disabled = true;},
    removeAttribute(name) {delete attrs[name]; if (name === 'disabled') node.disabled = false;},
    addEventListener(name, fn) {if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(fn);},
    removeEventListener(name, fn) {listeners.set(name, (listeners.get(name) || []).filter(x => x !== fn));},
    emit(name) {const event = {target: node, currentTarget: node, preventDefault(){}, stopPropagation(){}};
      const returns = []; if (typeof node['on' + name] === 'function') returns.push(node['on' + name](event));
      for (const fn of listeners.get(name) || []) returns.push(fn(event)); return Promise.all(returns);},
    click() {return node.disabled ? Promise.resolve() : node.emit('click');},
    focus(){}, showModal() {node.open = true;}, close() {node.open = false;},
    contains(other) {return other === node || node.children.includes(other);},
    matches(selector) {return selector.includes('[data-employee-badge]') ? 'employeeBadge' in node.dataset : false;},
    closest(selector) {return node.matches(selector) ? node : null;},
    querySelectorAll(selector) {return node.children.filter(child =>
      (!selector.includes('[data-employee-badge]') || 'employeeBadge' in child.dataset) &&
      (!selector.includes(':checked') || child.checked));},
    querySelector(selector) {return node.querySelectorAll(selector)[0] || null;}
  };
  for (const [name, value] of Object.entries(attrs)) if (name.startsWith('data-')) node.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
  let html = '';
  Object.defineProperty(node, 'innerHTML', {get: () => html, set(value) {
    html = String(value); node.children = [];
    for (const match of html.matchAll(/<input\b([^>]*)>/g)) {
      const child = element('', attributes(match[1])); child.parentElement = node; node.children.push(child);
    }
  }});
  return node;
}

function harness(roster = [employee('EMP-A'), employee('EMP-B')]) {
  const ids = ['employeeBadgeDialog','employeeBadgeRows','employeeBadgeSearch','employeeBadgeCount','employeeBadgeStatus',
    'employeeBadgePrint','employeeBadgeSelectAll','employeeBadgeClear','employeeBadgeRefresh','employeeBadgeClose','printEmployeeBadges'];
  const nodes = Object.fromEntries(ids.map(id => [id, element(id)]));
  const calls = [], sheets = [], messages = [], events = [], timers = new Map();
  let timerId = 0;
  const state = {roster, admin: true, blocked: false, mode: 'ok', pending: null, activeRequests: 0, maxRequests: 0, imageRequests: 0};
  const document = {readyState: 'complete', body: element('body'), getElementById: id => nodes[id] || null,
    querySelector: selector => selector.startsWith('#') ? nodes[selector.slice(1)] || null : null,
    querySelectorAll: selector => nodes.employeeBadgeRows.querySelectorAll(selector), addEventListener(){}};
  const context = {console, document, esc: escape, encodeURIComponent, qrStatus: {ready: true},
    requireJob: role => role === 'admin' && state.admin,
    notify: message => messages.push(message),
    setTimeout(fn, delay) {const id = ++timerId; timers.set(id, {fn, delay}); return id;},
    clearTimeout: id => timers.delete(id),
    api: async (url, options = {}) => {
      calls.push({url, ...options}); events.push('fetch');
      assert.equal(url, '/api/employees'); assert.equal(options.method, undefined, 'Printing must be read-only');
      assert.equal(options.cache, 'no-store', 'Refresh identity/access rather than trusting a cached roster');
      if (state.mode === 'error') throw Error('Employee roster unavailable');
      if (state.mode === 'pending') return new Promise(resolve => {state.pending = rows => resolve(structuredClone(rows));});
      return structuredClone(state.roster);
    },
    open() {
      events.push('open'); if (state.blocked) return null;
      const sheet = {closed: false, html: '', images: [], printCount: 0, finalWrites: 0,
        close() {sheet.closed = true;}, focus(){}, print() {sheet.printCount++;}, addEventListener(){}, removeEventListener(){}};
      const popupNodes = {};
      const popupDocument = {body: element('body'),
        open() {sheet.html = ''; sheet.finalWrites++;}, write(html) {sheet.html += html;},
        close() {
          for (const match of sheet.html.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
            const attrs = attributes(match[2]); popupNodes[match[3]] = element(match[3], attrs);
          }
          sheet.images = [...sheet.html.matchAll(/<img\b([^>]*)>/g)].map(match => {
            const image = element('', attributes(match[1])); image.complete = false; image.naturalWidth = 0;
            image.loading = false; image.loaded = false; image.failed = false;
            Object.defineProperty(image, 'src', {get: () => image.source || '', set(value) {
              assert.equal(image.loading, false, 'An image must have only one pending request');
              image.source = value; image.loading = true; state.activeRequests++; state.imageRequests++;
              state.maxRequests = Math.max(state.maxRequests, state.activeRequests);
            }});
            image.release = async (success = true) => {
              assert.equal(image.loading, true, 'Only a requested image can finish');
              image.loading = false; state.activeRequests--; image.complete = true; image.naturalWidth = success ? 256 : 0;
              image.loaded = success; image.failed = !success; await image.emit(success ? 'load' : 'error');
            };
            return image;
          });
        },
        getElementById: id => popupNodes[id] || null,
        querySelectorAll: selector => selector.includes('img') ? sheet.images.filter(image => !selector.includes('[data-qr-src]') || 'qrSrc' in image.dataset) : [],
        querySelector: selector => selector.startsWith('#') ? popupNodes[selector.slice(1)] || null : null
      };
      sheet.document = popupDocument; sheet.nodes = popupNodes; sheets.push(sheet); return sheet;
    }
  };
  context.window = context; context.$ = id => document.getElementById(id);
  vm.createContext(context); vm.runInContext(source, context, {filename: 'employee-badges.js'});
  const app = context.FabEmployeeBadges;
  assert.ok(app && typeof app.open === 'function' && typeof app.printSelected === 'function');
  return {state, nodes, calls, sheets, messages, events, timers, context, app,
    checkboxes: () => nodes.employeeBadgeRows.querySelectorAll('[data-employee-badge]'),
    selected: () => nodes.employeeBadgeRows.querySelectorAll('[data-employee-badge]').filter(n => n.checked).map(n => n.dataset.employeeBadge).sort()};
}

const settle = async () => {for (let i = 0; i < 12; i++) await Promise.resolve(); await new Promise(resolve => setImmediate(resolve));};
async function changeSelection(h, badge, checked) {
  const checkbox = h.checkboxes().find(row => row.dataset.employeeBadge === badge);
  assert.ok(checkbox, `Employee ${badge} must be selectable`); checkbox.checked = checked; await checkbox.emit('change'); await settle();
}
async function finishImages(h, sheet) {
  for (let wave = 0; wave <= sheet.images.length; wave++) {
    const loading = sheet.images.filter(image => image.loading);
    if (!loading.length) {await settle(); if (!sheet.images.some(image => image.loading)) break; continue;}
    for (const image of loading) await image.release(); await settle();
  }
  assert.equal(sheet.images.every(image => image.loaded), true, 'Every selected employee must have a loaded QR');
  assert.equal(h.state.activeRequests, 0);
}

const watchdog = setTimeout(() => {console.error('Badge sheet smoke test stalled with an unresolved print job.'); process.exitCode = 1;}, 5000);
(async () => {
  const checks = [];
  for (const guard of ['admin', 'qr']) {
    const h = harness(); if (guard === 'admin') h.state.admin = false; else h.context.qrStatus.ready = false;
    await h.app.open(); await h.app.printSelected();
    assert.equal(h.calls.length, 0); assert.equal(h.sheets.length, 0);
  }
  checks.push('Only administrators with configured public QR links can open or print employee badge sheets');

  {
    const h = harness([employee('EMP-A', {name: 'Alice Initial'}), employee('EMP-B', {name: 'Bob Initial'}),
      employee('EMP-INACTIVE', {active: false}), employee('EMP-REMOVED', {removed: true})]);
    await h.app.open(); await settle();
    assert.deepEqual(h.selected(), ['EMP-A','EMP-B']);
    h.nodes.employeeBadgeSearch.value = 'Alice'; await h.nodes.employeeBadgeSearch.emit('input');
    await changeSelection(h, 'EMP-A', false);
    h.nodes.employeeBadgeSearch.value = ''; await h.nodes.employeeBadgeSearch.emit('input');
    assert.deepEqual(h.selected(), ['EMP-B'], 'Searching must preserve the selection of hidden employees');
    h.state.roster = [employee('EMP-A'), employee('EMP-B', {name: 'Bob <Lead> & "QA"', role_label: 'NDT <Inspector> & "Team"'}), employee('EMP-C')];
    const before = h.events.length, pending = h.app.printSelected();
    assert.equal(h.events[before], 'open', 'Open the popup inside the click before awaiting the roster');
    await settle(); const sheet = h.sheets.at(-1);
    assert.equal(sheet.images.length, 1, 'Refetching must not add employees outside the exact selection');
    assert.equal(sheet.images[0].dataset.qrSrc, '/api/employees/EMP-B/qr.png');
    assert.ok(sheet.html.includes('Bob &lt;Lead&gt; &amp; &quot;QA&quot;'));
    assert.ok(sheet.html.includes('NDT &lt;Inspector&gt; &amp; &quot;Team&quot;'));
    assert.doesNotMatch(sheet.html, /Bob Initial|<Lead>|<Inspector>|EMP-INACTIVE|EMP-REMOVED|EMP-C/);
    assert.equal(sheet.nodes.badgeSheetPrint.disabled, true);
    await finishImages(h, sheet); await pending;
    assert.equal(sheet.closed, false); assert.equal(sheet.nodes.badgeSheetPrint.disabled, false);
    assert.equal(sheet.document.body.classList.contains('feb-ready'), true);
    assert.equal(sheet.printCount, 0, 'Preparation must not trigger an unsolicited print dialog');
    await sheet.nodes.badgeSheetPrint.click(); assert.equal(sheet.printCount, 1);
    assert.equal(h.calls.length, 2); assert.equal(h.timers.size, 0);
  }
  checks.push('Active nonremoved employees start selected; search preserves selections and printing uses only exact selected IDs with fresh escaped server labels');

  {
    const h = harness(Array.from({length: 137}, (_, i) => employee('EMP-' + String(i + 1).padStart(3, '0'))));
    await h.app.open(); assert.equal(h.selected().length, 137);
    const pending = h.app.printSelected(); await settle(); const sheet = h.sheets.at(-1);
    assert.equal(sheet.images.length, 137, 'Print all must not truncate at the spool 100-label batch limit');
    assert.equal(h.state.maxRequests, 6); assert.equal(h.state.activeRequests, 6);
    assert.equal(sheet.nodes.badgeSheetPrint.disabled, true);
    const first = sheet.images.find(image => image.loading); await first.release(); await settle();
    assert.equal(sheet.nodes.badgeSheetPrint.disabled, true, 'One loaded image cannot enable a partial sheet');
    await finishImages(h, sheet); await pending;
    assert.equal(h.state.maxRequests, 6, 'Mass printing must bound simultaneous QR requests');
    assert.equal(h.state.imageRequests, 137); assert.equal(sheet.nodes.badgeSheetPrint.disabled, false);
    assert.equal(sheet.printCount, 0); assert.equal(h.timers.size, 0);
  }
  checks.push('A roster larger than 100 prints completely with at most six concurrent QR loads and remains unprintable until every QR is ready');

  {
    const h = harness(); await h.app.open(); await h.nodes.employeeBadgeClear.click();
    assert.deepEqual(h.selected(), []); await h.app.printSelected(); assert.equal(h.sheets.length, 0);
    await h.nodes.employeeBadgeSelectAll.click(); assert.deepEqual(h.selected(), ['EMP-A','EMP-B']);
    h.state.blocked = true; const before = h.calls.length; await h.app.printSelected();
    assert.equal(h.calls.length, before); assert.equal(h.sheets.length, 0); assert.ok(h.messages.length);
  }
  checks.push('Select all and clear selection work; empty selections and blocked popups cannot start a badge job');

  for (const invalid of ['missing','inactive','removed','name','position','fetch-error']) {
    const h = harness(); await h.app.open();
    if (invalid === 'fetch-error') h.state.mode = 'error';
    else if (invalid === 'missing') h.state.roster = [employee('EMP-A')];
    else h.state.roster = [employee('EMP-A'), employee('EMP-B', invalid === 'inactive' ? {active: false} : invalid === 'removed' ? {removed: true} : invalid === 'name' ? {name: ''} : {role_label: ''})];
    await h.app.printSelected(); const sheet = h.sheets.at(-1);
    assert.equal(sheet.closed, true, `${invalid} must reject the whole selected job`);
    assert.equal(h.state.imageRequests, 0, 'Never start a partial badge sheet after invalid roster data');
  }
  checks.push('Missing, inactive, removed or incomplete selected employees and failed refreshes reject the entire job without printing stale badges');

  {
    const h = harness(); await h.app.open(); h.state.mode = 'pending';
    const pending = h.app.printSelected(), sheet = h.sheets.at(-1); sheet.close();
    h.state.pending(h.state.roster); await pending; await settle();
    assert.equal(sheet.finalWrites, 0); assert.equal(h.state.imageRequests, 0);
  }
  checks.push('Closing the popup during a pending roster refresh does not populate or reopen the closed window');

  {
    const h = harness(); await h.app.open(); const pending = h.app.printSelected(); await settle();
    const sheet = h.sheets.at(-1), images = sheet.images.filter(image => image.loading);
    await images[0].release(false); await settle();
    for (const image of images.slice(1).filter(image => image.loading)) await image.release();
    await pending; assert.equal(sheet.closed, true); assert.equal(sheet.printCount, 0);
    assert.equal(h.timers.size, 0); assert.ok(h.messages.length);
  }
  checks.push('An unavailable QR rejects and closes the partial sheet, cleans up timers, and never opens the print dialog');

  {
    const h = harness(); await h.app.open(); const pending = h.app.printSelected(); await settle();
    const sheet = h.sheets.at(-1); h.app.close(); await pending; await settle();
    assert.equal(sheet.closed, true); assert.equal(sheet.printCount, 0); assert.equal(h.timers.size, 0);
  }
  checks.push('Closing the picker cancels a pending print job and clears all in-flight image timers');
  console.log(JSON.stringify({status: 'passed', contracts: checks.length, checks}, null, 2));
})().catch(error => {console.error(error.stack || error); process.exitCode = 1;}).finally(() => clearTimeout(watchdog));
