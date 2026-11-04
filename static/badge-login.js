/* Employee sign-in credentials are used only by the sign-in screen, never handoff controls. */
(() => {
  'use strict';
  const node = id => document.getElementById(id);
  const invalidBadge = 'Scan an employee sign-in badge printed by FabTrace.';
  const oldBadge = 'This is an older identification badge. Ask an administrator to print a new sign-in badge.';
  const state = {busy: false, leaving: false, bootstrapped: false, request: 0, controller: null, inputTimer: null};
  let camera = null, cameraRequest = 0, initialLink = null;

  function status(message, error = false) {
    const target = node('badgeLoginStatus');
    target.textContent = message;
    target.classList.toggle('fbl-error', error);
  }

  function controls() {
    node('badgeLoginScan').disabled = state.busy || Boolean(camera);
    node('badgeLoginSubmit').disabled = state.busy;
    node('badgeLoginInput').disabled = state.busy;
    node('badgeLoginStop').disabled = state.busy;
    node('badge').disabled = state.busy;
    node('pin').disabled = state.busy;
    node('loginForm').querySelector('button[type="submit"]').disabled = state.busy;
    node('badgeLoginForm').setAttribute('aria-busy', String(state.busy));
  }

  function parseBadge(value) {
    const raw = String(value || '').trim();
    if (!raw || raw.length > 4096) throw Error(invalidBadge);
    let link;
    try { link = new URL(raw); } catch (_) { throw Error(/^(?:FABTRACE:EMP:)?[A-Za-z0-9_-]{2,80}$/.test(raw) ? oldBadge : invalidBadge); }
    if (link.protocol !== 'https:' || link.origin !== location.origin || link.username || link.password || !['/', '/index.html'].includes(link.pathname)) throw Error(invalidBadge);
    const badge = link.searchParams.get('badge');
    if (!badge || !/^[A-Za-z0-9_-]{2,80}$/.test(badge) || link.searchParams.getAll('badge').length !== 1 || [...link.searchParams.keys()].some(key => key !== 'badge')) throw Error(invalidBadge);
    const fragment = new URLSearchParams(link.hash.slice(1));
    if (!fragment.has('badge_login')) throw Error(oldBadge);
    if (fragment.getAll('badge_login').length !== 1 || [...fragment.keys()].some(key => key !== 'badge_login')) throw Error(invalidBadge);
    const token = fragment.get('badge_login');
    if (!token || token.length > 1024 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/.test(token)) throw Error(invalidBadge);
    try {
      const encoded = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const claims = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, '=')));
      if (claims.sub !== badge || claims.p !== 'badge-login-v1' || !Number.isSafeInteger(claims.bv) || claims.bv < 0) throw Error();
    } catch (_) { throw Error(invalidBadge); }
    // This checks the scanned format only. The server verifies the signature and current account.
    return {badge, token};
  }

  function destination(direct = false) {
    if (direct) return '/?order-setup=1';
    const route = new URL(location.href);
    route.hash = '';
    route.searchParams.delete('badge');
    route.searchParams.delete('badge_login');
    return ['/', '/index.html'].includes(route.pathname) && route.search ? '/' + route.search : '/?order-setup=1';
  }

  // Consume credentials before navigation can snapshot a URL or start authenticated routing.
  try {
    const route = new URL(location.href);
    if (new URLSearchParams(route.hash.slice(1)).has('badge_login')) {
      initialLink = route.href;
      route.hash = '';
      route.searchParams.delete('badge');
      if (typeof params !== 'undefined') params.delete('badge');
      history.replaceState(null, '', '/' + route.search);
    }
  } catch (_) { /* The browser supplies a valid page URL; manual scanning still works. */ }

  async function cleanupCamera(active) {
    if (active.cleaned || !active.reader) return;
    active.cleaned = true;
    try { if (active.started) await active.reader.stop(); } catch (_) {}
    try { await active.reader.clear(); } catch (_) {}
  }

  async function stopCamera() {
    const request = ++cameraRequest, active = camera;
    camera = null;
    if (active) active.cancelled = true;
    node('badgeLoginCameraPanel').classList.add('hidden');
    node('badgeLoginCameraStatus').textContent = '';
    controls();
    if (active?.started) await cleanupCamera(active);
    return request;
  }

  function loginError(error, method) {
    if (error?.name === 'AbortError') return 'Sign-in took too long. Scan your badge again or retry sign-in.';
    if (error?.status === 429) return 'Too many sign-in attempts. Wait a few minutes before trying again.';
    if ([401, 403].includes(error?.status)) return method === 'badge'
      ? 'This sign-in badge is invalid or disabled. Ask an administrator to check the account or replace the badge.'
      : 'The badge ID or PIN is incorrect, or this account is inactive.';
    return 'Could not sign in. Check your connection and try again.';
  }

  async function signIn(payload, method, expectedBadge, direct = false) {
    if (state.busy || state.leaving) return false;
    state.busy = true;
    const request = ++state.request, target = destination(direct);
    clearTimeout(state.inputTimer);
    node('badgeLoginInput').value = '';
    node('pin').value = '';
    controls();
    status('Signing in…');
    await stopCamera();
    if (request !== state.request) return false;
    const controller = new AbortController();
    state.controller = controller;
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const user = await api(method === 'badge' ? '/api/login/badge' : '/api/login', {
        method: 'POST', body: JSON.stringify(payload), signal: controller.signal,
      });
      if (request !== state.request) return false;
      if (!user || user.badge !== expectedBadge || typeof user.role !== 'string') throw Error('Invalid sign-in response');
      state.leaving = true;
      status('Signed in. Opening FabTrace…');
      // A fresh page discards the former employee's views and pending client operations.
      location.replace(target);
      return true;
    } catch (error) {
      if (request === state.request) status(loginError(error, method), true);
      return false;
    } finally {
      clearTimeout(timeout);
      if (state.controller === controller) state.controller = null;
      if (!state.leaving && request === state.request) { state.busy = false; controls(); node('badgeLoginInput').focus(); }
    }
  }

  async function submit(value = node('badgeLoginInput').value, options = {}) {
    if (state.busy || state.leaving) return false;
    clearTimeout(state.inputTimer);
    node('badgeLoginInput').value = '';
    let credential;
    try { credential = parseBadge(value); }
    catch (error) { status(error.message === oldBadge ? oldBadge : invalidBadge, true); return false; }
    return signIn({token: credential.token}, 'badge', credential.badge, options.direct === true);
  }

  async function signInWithPin() {
    if (state.busy || state.leaving) return false;
    const badge = node('badge').value.trim(), pin = node('pin').value;
    if (!badge || pin.length < 6) { status('Enter your badge ID and private PIN.', true); return false; }
    return signIn({badge, pin}, 'pin', badge);
  }

  async function startCamera() {
    if (state.busy || state.leaving || node('login').classList.contains('hidden')) return;
    const request = await stopCamera();
    if (request !== cameraRequest || state.busy || state.leaving) return;
    const active = {request, reader: null, started: false, cancelled: false, cleaned: false, handling: false};
    camera = active;
    controls();
    node('badgeLoginCameraPanel').classList.remove('hidden');
    node('badgeLoginCameraStatus').textContent = 'Opening camera… Allow camera access when asked.';
    status('');
    try {
      const Reader = await window.FabHandoff.loadScanner();
      if (camera !== active || active.cancelled || request !== cameraRequest || state.busy || state.leaving) return;
      active.reader = new Reader('badgeLoginCamera');
      await active.reader.start({facingMode: 'environment'}, {fps: 10, qrbox: {width: 210, height: 210}}, async decoded => {
        if (camera !== active || active.cancelled || active.handling || request !== cameraRequest || state.busy || state.leaving) return;
        try { parseBadge(decoded); }
        catch (error) { status(error.message === oldBadge ? oldBadge : invalidBadge, true); return; }
        active.handling = true;
        await submit(decoded);
      }, () => {});
      active.started = true;
      if (camera !== active || active.cancelled || request !== cameraRequest || state.busy || state.leaving) await cleanupCamera(active);
      else node('badgeLoginCameraStatus').textContent = 'Hold your employee badge QR inside the camera frame.';
    } catch (_) {
      if (camera === active) {
        camera = null;
        node('badgeLoginCameraPanel').classList.add('hidden');
        status('Camera unavailable. Allow camera access and try again, use a handheld QR scanner, or open the badge link with your phone camera.', true);
        controls();
      }
      await cleanupCamera(active);
    }
  }

  async function bootstrap() {
    if (state.bootstrapped) return;
    state.bootstrapped = true;
    const incoming = initialLink;
    initialLink = null;
    if (incoming) return submit(incoming, {direct: true});
    await refreshAuth();
    if (node('login').classList.contains('hidden')) return;
    if (typeof params !== 'undefined' && params.has('badge')) {
      const badge = params.get('badge');
      if (/^[A-Za-z0-9_-]{2,80}$/.test(badge || '')) node('badge').value = badge;
      status(oldBadge, true);
    }
    node('badgeLoginInput').focus();
  }

  function cancelPending() {
    ++state.request;
    state.controller?.abort();
    state.controller = null;
    clearTimeout(state.inputTimer);
    initialLink = null;
    node('badgeLoginInput').value = '';
    node('pin').value = '';
    state.busy = false;
    return stopCamera();
  }

  node('badgeLoginScan').onclick = startCamera;
  node('badgeLoginStop').onclick = () => { status('Camera stopped. You can scan again when ready.'); return stopCamera(); };
  node('badgeLoginForm').onsubmit = event => { event.preventDefault(); return submit(); };
  node('badgeLoginInput').oninput = () => {
    clearTimeout(state.inputTimer);
    if (state.busy) return;
    state.inputTimer = setTimeout(() => {
      const value = node('badgeLoginInput').value;
      try { parseBadge(value); } catch (_) { return; }
      submit(value);
    }, 300);
  };
  node('loginPinFallback').ontoggle = () => { if (node('loginPinFallback').open) stopCamera(); };
  window.addEventListener('pagehide', cancelPending);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopCamera(); });
  window.FabBadgeLogin = {bootstrap, submit, signInWithPin, startCamera, stopCamera, cancelPending};
})();
