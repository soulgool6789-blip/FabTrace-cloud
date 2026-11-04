/* Badge-only login contracts with synthetic credentials and fake camera/network. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const ORIGIN = 'https://fabtrace-cloud.onrender.com';
const badge = 'TEST-BADGE-001';
// Deliberately synthetic syntax: no deployed identity, secret or signature is used.
const token = [
  Buffer.from(JSON.stringify({alg: 'HS256', typ: 'JWT'})).toString('base64url'),
  Buffer.from(JSON.stringify({sub: badge, p: 'badge-login-v1', bv: 0})).toString('base64url'),
  Buffer.alloc(32, 7).toString('base64url'),
].join('.');
const badgeUrl = `${ORIGIN}/?badge=${badge}#badge_login=${token}`;
const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes;reject = no;});
  return {promise, resolve, reject};
}

function harness({url = ORIGIN + '/', signedIn = false, scanner = true} = {}) {
  let currentUrl = new URL(url), nextTimer = 0;
  const elements = new Map(), events = new Map(), scripts = [], cameras = [];
  const calls = [], messages = [], redirects = [], replacements = [], timers = new Map();
  const storage = new Map(), consoleOutput = [];
  const control = {response: null, failure: null, scannerLoad: null, scannerFailure: null,
    cameraStart: null, cameraFailure: null, refreshes: 0, loaderCalls: 0};
  class Element {
    constructor(id) {
      this.id = id;this.value = '';this.textContent = '';this.disabled = false;
      this.hidden = false;this.dataset = {};this.attributes = {};this.style = {};
      this.classes = new Set();this.listeners = new Map();this.focused = false;
      this.classList = {
        add: (...names) => names.forEach(name => this.classes.add(name)),
        remove: (...names) => names.forEach(name => this.classes.delete(name)),
        contains: name => this.classes.has(name),
        toggle: (name, on) => {
          if (on ?? !this.classes.has(name)) this.classes.add(name);
          else this.classes.delete(name);
        },
      };
    }
    addEventListener(type, callback) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(callback);
    }
    removeEventListener(type, callback) {
      this.listeners.set(type, (this.listeners.get(type) || []).filter(value => value !== callback));
    }
    setAttribute(name, value) {this.attributes[name] = String(value);}
    removeAttribute(name) {delete this.attributes[name];}
    getAttribute(name) {return this.attributes[name] ?? null;}
    focus() {this.focused = true;document.activeElement = this;}
    select() {this.selected = true;}
    remove() {this.removed = true;}
    setCustomValidity(value) {this.validityMessage = value;}
    reportValidity() {return !this.validityMessage;}
    get innerHTML() {return this._html || '';}
    set innerHTML(value) {this._html = value;}
    querySelectorAll() {return [];}
    querySelector(selector) {
      if (this.id === 'loginForm' && selector === 'button[type="submit"]') return elements.get('pinSubmit');
      return null;
    }
    async emit(type, extra = {}) {
      const event = {type, target: this, currentTarget: this, key: '', defaultPrevented: false,
        preventDefault() {this.defaultPrevented = true;}, stopPropagation() {}, ...extra};
      const handlers = [...(this.listeners.get(type) || [])];
      if (typeof this['on' + type] === 'function') handlers.push(this['on' + type]);
      for (const handler of handlers) await handler(event);
      return event;
    }
    click() {return this.emit('click');}
  }
  for (const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
    const el = new Element(match[1]);
    for (const name of (match[0].match(/\bclass="([^"]*)"/)?.[1] || '').split(' ').filter(Boolean)) el.classes.add(name);
    el.hidden = /\shidden(?:\s|>)/.test(match[0]);
    elements.set(el.id, el);
  }
  assert.match(html, /<form id="loginForm">[\s\S]*?<button type="submit"/);
  elements.set('pinSubmit', new Element('pinSubmit'));
  const document = {
    hidden: false, visibilityState: 'visible', activeElement: null,
    getElementById: id => elements.get(id) || null,
    createElement: tag => new Element(tag),
    head: {appendChild(script) {scripts.push(script);}},
    addEventListener(type, callback) {
      const key = 'document:' + type;
      if (!events.has(key)) events.set(key, []);
      events.get(key).push(callback);
    },
  };
  class Scanner {
    constructor(id) {this.id = id;this.stops = 0;this.clears = 0;cameras.push(this);}
    async start(camera, config, decode) {
      this.camera = camera;this.config = config;this.decode = decode;
      if (control.cameraStart) await control.cameraStart.promise;
      if (control.cameraFailure) throw control.cameraFailure;
    }
    async stop() {this.stops++;}
    async clear() {this.clears++;}
  }
  const location = {
    get href() {return currentUrl.href;},
    get origin() {return currentUrl.origin;},
    get protocol() {return currentUrl.protocol;},
    get pathname() {return currentUrl.pathname;},
    get search() {return currentUrl.search;},
    get hash() {return currentUrl.hash;},
    replace(value) {redirects.push(String(value));currentUrl = new URL(value, currentUrl);},
    assign(value) {redirects.push(String(value));currentUrl = new URL(value, currentUrl);},
    reload() {redirects.push(currentUrl.pathname + currentUrl.search);},
  };
  const context = {
    URL, URLSearchParams, Date, Promise, AbortController, atob, btoa, queueMicrotask,
    document, location, isSecureContext: true,
    navigator: {mediaDevices: {getUserMedia() {throw Error('The scanner fixture owns the camera');}}},
    params: new URLSearchParams(currentUrl.search),
    me: signedIn ? {badge: 'PREVIOUS-USER', name: 'Previous employee', role: 'admin'} : null,
    current: signedIn ? {id: 'PREVIOUS-ITEM'} : null,
    history: {replaceState(_state, _title, value) {
      replacements.push(String(value));currentUrl = new URL(value, currentUrl);
    }},
    console: Object.fromEntries(['log', 'error', 'warn', 'info'].map(name => [name, (...values) => consoleOutput.push(values.join(' '))])),
    setTimeout(callback, delay) {timers.set(++nextTimer, {callback, delay});return nextTimer;},
    clearTimeout(id) {timers.delete(id);},
    addEventListener(type, callback) {
      if (!events.has(type)) events.set(type, []);
      events.get(type).push(callback);
    },
    notify(message) {messages.push(message);},
    async refreshAuth() {control.refreshes++;if (signedIn) elements.get('login').classList.add('hidden');},
    async stopCloudCamera() {},
    async api(url, options = {}) {
      calls.push({url, ...options});
      if (control.response) {
        return await new Promise((resolve, reject) => {
          const onAbort = () => reject(Object.assign(Error('Synthetic request aborted'), {name: 'AbortError'}));
          options.signal?.addEventListener('abort', onAbort, {once: true});
          if (options.signal?.aborted) onAbort();
          control.response.promise.then(resolve, reject).finally(() => options.signal?.removeEventListener('abort', onAbort));
        });
      }
      if (control.failure) throw control.failure;
      return {badge, name: 'Synthetic Employee', role: 'painter', permissions: {}};
    },
    FabHandoff: {async loadScanner() {
      control.loaderCalls++;
      if (control.scannerLoad) return await control.scannerLoad.promise;
      if (control.scannerFailure || !scanner) throw control.scannerFailure || Error('Synthetic scanner unavailable');
      return Scanner;
    }},
    localStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
  };
  context.sessionStorage = context.localStorage;
  context.window = context;
  if (scanner) context.Html5Qrcode = Scanner;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'static/badge-login.js'), 'utf8'), context, {filename: 'badge-login.js'});
  return {
    context, control, elements, scripts, cameras, calls, messages, redirects, replacements, timers, storage, consoleOutput, Scanner,
    el(id) {const result = elements.get(id);assert.ok(result, id + ' exists in the real HTML shell');return result;},
    async emit(type, extra = {}) {for (const callback of events.get(type) || []) await callback(extra);},
    async fireTimer(delay) {
      const found = [...timers.entries()].find(([, timer]) => timer.delay === delay);
      assert.ok(found, 'Expected pending timer of ' + delay + 'ms');
      timers.delete(found[0]);await found[1].callback();await flush();
    },
    visibleText() {return [...elements.values()].map(el => el.textContent + ' ' + el.innerHTML).join('\n');},
  };
}

function privateCredential(h) {
  assert.doesNotMatch(h.visibleText(), new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), 'Credential never appears in visible status or HTML');
  assert.equal(h.storage.size, 0, 'Credentials are not stored in browser storage');
  assert.ok(h.consoleOutput.every(value => !value.includes(token)), 'Credentials are never logged');
  assert.ok(h.replacements.every(value => !value.includes(token)), 'URL replacement never retains the credential');
}
function signInCall(h) {
  assert.equal(h.calls.length, 1, 'Exactly one authentication request');
  const call = h.calls[0];
  assert.equal(call.url, '/api/login/badge');assert.equal(call.method, 'POST');
  assert.deepEqual(JSON.parse(call.body), {token}, 'Badge scan submits only its credential, with no PIN');
  assert.equal(h.el('badgeLoginInput').value, '', 'The scanned credential is cleared from the input');
  assert.equal(h.el('pin').value, '', 'Any stale fallback PIN is cleared');
  assert.equal(h.control.refreshes, 0, 'Badge login never relies on a previous authenticated identity');
  privateCredential(h);
}
function changedToken(claims) {
  const parts = token.split('.');parts[1] = Buffer.from(JSON.stringify(claims)).toString('base64url');return parts.join('.');
}

(async () => {
  const checks = [];
  assert.equal(html, fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8'), 'Both HTML entrypoints match');
  assert.match(html, /Scan your badge to sign in/);assert.match(html, /No PIN is needed/);
  assert.match(html, /id="badgeLoginInput" type="password" autocomplete="off"/);
  const scanForm = html.match(/<form id="badgeLoginForm"[\s\S]*?<\/form>/)?.[0];
  assert.ok(scanForm);assert.doesNotMatch(scanForm, /id="pin"|Private PIN/);
  assert.match(html, /DOMContentLoaded',\(\)=>window\.FabBadgeLogin\?window\.FabBadgeLogin\.bootstrap\(\):refreshAuth\(\)/);
  assert.ok(html.indexOf('/static/badge-login.js') < html.indexOf('/static/navigation.js'), 'Credential cleanup precedes navigation snapshots');
  assert.match(html, /FabBadgeLogin\.signInWithPin\(\)/);

  {
    const h = harness();
    h.el('pin').value = 'stale-private-PIN';h.el('badgeLoginInput').value = badgeUrl;
    const event = await h.el('badgeLoginForm').emit('submit');
    assert.equal(event.defaultPrevented, true);signInCall(h);
    assert.deepEqual(h.redirects, ['/?order-setup=1']);
    assert.match(h.el('badgeLoginStatus').textContent, /Signed in/);
    assert.equal(h.control.loaderCalls, 0, 'Keyboard sign-in never downloads or starts a camera');
    checks.push('A handheld badge scan signs in with one credential POST, no PIN, and a fresh Orders page');
  }
  {
    const h = harness();
    h.el('badgeLoginInput').value = badgeUrl;
    await h.el('badgeLoginInput').emit('input');
    assert.equal(h.calls.length, 0);await h.fireTimer(300);signInCall(h);
    checks.push('A complete handheld scan starts sign-in automatically without an Enter key or extra button');
  }
  {
    const invalid = [
      '', badge, 'FABTRACE:EMP:' + badge, `${ORIGIN}/?badge=${badge}`,
      `${ORIGIN}/?item=SPOOL-001#badge_login=${token}`,
      badgeUrl.replace(ORIGIN, 'https://foreign.example'), badgeUrl.replace('https:', 'http:'),
      badgeUrl.replace('/?badge=', '/not-a-badge?badge='),
      badgeUrl.replace('https://', 'https://user:password@'),
      badgeUrl.replace('#', '&badge=' + badge + '#'),
      badgeUrl.replace('#', '&item=SPOOL-001#'),
      badgeUrl + '&badge_login=' + token, badgeUrl + '&other=1',
      badgeUrl.replace(token, 'not-a-signed-token'),
      badgeUrl.replace(token, changedToken({sub: 'OTHER-EMPLOYEE', p: 'badge-login-v1', bv: 0})),
      badgeUrl.replace(token, changedToken({sub: badge, p: 'session', bv: 0})),
      badgeUrl.replace(token, changedToken({sub: badge, p: 'badge-login-v1', bv: -1})),
      badgeUrl.replace(token, changedToken({sub: badge, p: 'badge-login-v1', bv: 1.5})),
      badgeUrl.replace(token, changedToken({sub: badge, p: 'badge-login-v1', bv: Number.MAX_SAFE_INTEGER + 1})),
      badgeUrl.replace(token, changedToken({sub: badge, p: 'badge-login-v1', bv: 0, extra: 'x'.repeat(1500)})),
    ];
    for (const value of invalid) {
      const h = harness();h.el('badgeLoginInput').value = value;
      assert.equal(await h.context.FabBadgeLogin.submit(), false);
      assert.equal(h.calls.length, 0);assert.equal(h.redirects.length, 0);
      assert.ok(h.el('badgeLoginStatus').textContent.length > 0);assert.equal(h.el('badgeLoginInput').value, '');
      privateCredential(h);
    }
    checks.push('Legacy identity badges, item labels, foreign links, ambiguous URLs and invalid credential formats cannot log in');
  }
  {
    const h = harness({url: badgeUrl, signedIn: true});
    assert.equal(h.context.location.hash, '', 'Secret fragment is removed as soon as the module loads');
    assert.equal(h.context.params.has('badge'), false, 'Captured badge routing is removed as well');
    assert.equal(h.calls.length, 0, 'URL cleanup happens before authentication');
    await h.context.FabBadgeLogin.bootstrap();await h.context.FabBadgeLogin.bootstrap();signInCall(h);
    assert.deepEqual(h.redirects, ['/?order-setup=1']);
    const indexed = harness({url: badgeUrl.replace('/?', '/index.html?')});
    await indexed.context.FabBadgeLogin.bootstrap();signInCall(indexed);
    checks.push('Direct badge links remove the credential before routing, sign in once, and discard the former employee view');
  }
  {
    const h = harness({url: ORIGIN + '/?flow=1&item=SPOOL-001&project=PO-001'});
    await h.context.FabBadgeLogin.submit(badgeUrl);signInCall(h);
    assert.deepEqual(h.redirects, ['/?flow=1&item=SPOOL-001&project=PO-001']);
    const normal = harness({url: ORIGIN + '/?item=SPOOL-001'});
    await normal.context.FabBadgeLogin.bootstrap();await normal.context.FabBadgeLogin.bootstrap();
    assert.equal(normal.control.refreshes, 1);assert.equal(normal.calls.length, 0);
    assert.equal(normal.el('badgeLoginInput').focused, true);
    const legacy = harness({url: ORIGIN + '/?badge=' + badge});
    await legacy.context.FabBadgeLogin.bootstrap();
    assert.equal(legacy.control.refreshes, 1);assert.equal(legacy.calls.length, 0);
    assert.equal(legacy.el('badge').value, badge);assert.match(legacy.el('badgeLoginStatus').textContent, /older identification badge/);
    checks.push('Scanning at an item login preserves that record, while ordinary and legacy links keep their existing startup path');
  }
  {
    for (const failure of [401, 403, 429, 500]) {
      const h = harness({url: badgeUrl, signedIn: true});
      h.control.failure = Object.assign(Error('Never display credential ' + token), {status: failure});
      assert.equal(await h.context.FabBadgeLogin.bootstrap(), false);signInCall(h);
      assert.equal(h.redirects.length, 0);assert.equal(h.el('badgeLoginInput').disabled, false);
      assert.equal(h.el('badgeLoginSubmit').disabled, false);assert.equal(h.el('badgeLoginInput').focused, true);
      assert.match(h.el('badgeLoginStatus').textContent, failure === 429 ? /Too many/ : failure === 500 ? /connection/ : /invalid or disabled/);
    }
    const malformed = harness({url: badgeUrl.replace(token, 'invalid'), signedIn: true});
    await malformed.context.FabBadgeLogin.bootstrap();assert.equal(malformed.control.refreshes, 0);
    assert.equal(malformed.calls.length, 0);assert.equal(malformed.redirects.length, 0);privateCredential(malformed);
    checks.push('Invalid, disabled, rate-limited and failed badge sign-ins stay closed without reopening a prior session or exposing the credential');
  }
  {
    const h = harness();h.control.response = deferred();
    const first = h.context.FabBadgeLogin.submit(badgeUrl);await flush();
    assert.equal(h.el('badgeLoginInput').disabled, true);assert.equal(h.el('pin').disabled, true);
    assert.equal(h.el('pinSubmit').disabled, true);assert.equal(h.el('badgeLoginScan').disabled, true);
    assert.equal(await h.context.FabBadgeLogin.submit(badgeUrl), false);
    assert.equal(await h.context.FabBadgeLogin.signInWithPin(), false);assert.equal(h.calls.length, 1);
    h.control.response.resolve({badge, role: 'painter'});await first;signInCall(h);
    assert.equal(await h.context.FabBadgeLogin.submit(badgeUrl), false);assert.equal(h.calls.length, 1);
    assert.equal(h.timers.size, 0);
    checks.push('Repeated scans, fallback PIN clicks and late submits cannot race the active sign-in request');
  }
  {
    const h = harness();h.control.response = deferred();
    const pending = h.context.FabBadgeLogin.submit(badgeUrl);await flush();await h.fireTimer(20000);await pending;
    assert.equal(h.calls[0].signal.aborted, true);assert.equal(h.redirects.length, 0);
    assert.match(h.el('badgeLoginStatus').textContent, /took too long/);assert.equal(h.el('badgeLoginInput').disabled, false);
    h.control.response.resolve({badge, role: 'painter'});await flush();assert.equal(h.redirects.length, 0);
    const mismatched = harness();mismatched.control.response = deferred();
    const wrong = mismatched.context.FabBadgeLogin.submit(badgeUrl);await flush();
    mismatched.control.response.resolve({badge: 'WRONG-EMPLOYEE', role: 'admin'});await wrong;
    assert.equal(mismatched.redirects.length, 0);assert.match(mismatched.el('badgeLoginStatus').textContent, /Could not sign in/);
    privateCredential(h);privateCredential(mismatched);
    checks.push('A timed-out or mismatched authentication response cannot navigate into an unverified account');
  }
  {
    const h = harness();await h.el('badgeLoginScan').click();
    assert.equal(h.control.loaderCalls, 1);assert.equal(h.cameras.length, 1);
    const camera = h.cameras[0];assert.equal(camera.camera.facingMode, 'environment');
    await camera.decode(ORIGIN + '/?item=SPOOL-001');assert.equal(h.calls.length, 0);
    assert.match(h.el('badgeLoginStatus').textContent, /employee sign-in badge/);
    await camera.decode(badgeUrl);signInCall(h);
    assert.equal(camera.stops, 1);assert.equal(camera.clears, 1);
    assert.equal(h.el('badgeLoginCameraPanel').classList.contains('hidden'), true);
    await camera.decode(badgeUrl);assert.equal(h.calls.length, 1);
    checks.push('Camera decoding accepts the full badge credential, stops and clears after sign-in, and ignores later frames');
  }
  {
    for (const mode of ['loader', 'camera']) {
      const h = harness();h.control[mode === 'loader' ? 'scannerFailure' : 'cameraFailure'] = Error('Synthetic camera unavailable');
      await h.context.FabBadgeLogin.startCamera();
      assert.match(h.el('badgeLoginStatus').textContent, /Camera unavailable/);
      assert.match(h.el('badgeLoginStatus').textContent, /handheld QR scanner/);
      assert.equal(h.el('badgeLoginScan').disabled, false);assert.equal(h.el('badgeLoginInput').disabled, false);
      await h.context.FabBadgeLogin.submit(badgeUrl);signInCall(h);
    }
    const stopped = harness();await stopped.context.FabBadgeLogin.startCamera();await stopped.el('badgeLoginStop').click();
    assert.match(stopped.el('badgeLoginStatus').textContent, /Camera stopped/);
    assert.equal(stopped.cameras[0].stops, 1);assert.equal(stopped.cameras[0].clears, 1);
    assert.equal(stopped.el('badgeLoginScan').disabled, false);
    const fallback = harness();await fallback.context.FabBadgeLogin.startCamera();
    fallback.el('loginPinFallback').open = true;await fallback.el('loginPinFallback').emit('toggle');await flush();
    assert.equal(fallback.cameras[0].stops, 1);assert.equal(fallback.cameras[0].clears, 1);
    checks.push('Camera or decoder failures and manual cancellation leave handheld sign-in and the existing PIN fallback usable');
  }
  {
    const delayed = harness();delayed.control.scannerLoad = deferred();
    const starting = delayed.context.FabBadgeLogin.startCamera();await flush();
    await delayed.context.FabBadgeLogin.stopCamera();delayed.control.scannerLoad.resolve(delayed.Scanner);await starting;
    assert.equal(delayed.cameras.length, 0);assert.equal(delayed.calls.length, 0);
    const late = harness();late.control.cameraStart = deferred();
    const startup = late.context.FabBadgeLogin.startCamera();await flush();assert.equal(late.cameras.length, 1);
    await late.context.FabBadgeLogin.stopCamera();late.control.cameraStart.resolve();await startup;
    assert.equal(late.cameras[0].stops, 1);assert.equal(late.cameras[0].clears, 1);
    await late.cameras[0].decode(badgeUrl);assert.equal(late.calls.length, 0);
    const hidden = harness();await hidden.context.FabBadgeLogin.startCamera();hidden.context.document.hidden = true;
    await hidden.emit('document:visibilitychange');await flush();assert.equal(hidden.cameras[0].stops, 1);
    const leaving = harness();leaving.control.response = deferred();
    const authenticating = leaving.context.FabBadgeLogin.submit(badgeUrl);await flush();await leaving.emit('pagehide');
    leaving.control.response.resolve({badge, role: 'painter'});await authenticating;
    assert.equal(leaving.redirects.length, 0);assert.equal(leaving.calls[0].signal.aborted, true);
    privateCredential(delayed);privateCredential(late);privateCredential(leaving);
    checks.push('Stopped, hidden or abandoned camera/login work cannot start later, authenticate from an old frame, or redirect after navigation');
  }
  {
    const h = harness({url: ORIGIN + '/?item=SPOOL-001'});
    h.el('badge').value = badge;h.el('pin').value = 'synthetic-fallback-pin';
    await h.context.FabBadgeLogin.signInWithPin();
    assert.equal(h.calls.length, 1);assert.equal(h.calls[0].url, '/api/login');
    assert.deepEqual(JSON.parse(h.calls[0].body), {badge, pin: 'synthetic-fallback-pin'});
    assert.equal(h.el('pin').value, '');assert.deepEqual(h.redirects, ['/?item=SPOOL-001']);
    privateCredential(h);
    checks.push('Explicit PIN fallback keeps the existing endpoint and requested record without making PIN part of badge-only sign-in');
  }
  console.log(JSON.stringify({status: 'passed', contracts: checks.length, checks}, null, 2));
})().catch(error => {console.error(error.stack || error);process.exitCode = 1;});
