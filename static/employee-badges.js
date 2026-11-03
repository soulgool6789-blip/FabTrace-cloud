/* Administrator badge sheets reuse the current employee roster and issued QR endpoint. */
(() => {
  'use strict';
  const node = id => document.getElementById(id);
  const dialog = node('employeeBadgeDialog');
  const state = {employees: [], selected: new Set(), sequence: 0, loading: false, printing: false, job: null};
  const plural = count => count === 1 ? 'badge' : 'badges';

  function status(message, error = false) {
    const target = node('employeeBadgeStatus');
    target.textContent = message;
    target.classList.toggle('feb-error', error);
  }

  function controls() {
    const busy = state.loading || state.printing;
    ['employeeBadgeSearch', 'employeeBadgeSelectAll', 'employeeBadgeClear', 'employeeBadgeRefresh'].forEach(id => {node(id).disabled = busy;});
    node('employeeBadgeSelectAll').disabled = busy || !state.employees.length;
    node('employeeBadgeClear').disabled = busy || !state.selected.size;
    node('employeeBadgePrint').disabled = busy || !state.selected.size;
    node('employeeBadgePrint').textContent = state.printing ? 'Preparing badge sheets…' : `Print ${state.selected.size} ${plural(state.selected.size)}`;
    node('employeeBadgeCount').textContent = `${state.selected.size} of ${state.employees.length} active employees selected`;
    node('employeeBadgeRows').querySelectorAll('[data-employee-badge]').forEach(input => {input.disabled = busy;});
  }

  function renderRows() {
    const query = node('employeeBadgeSearch').value.trim().toLocaleLowerCase();
    const visible = state.employees.filter(employee => !query || [employee.name, employee.badge, employee.role_label].some(value => value.toLocaleLowerCase().includes(query)));
    node('employeeBadgeRows').innerHTML = state.loading ? '<p class="muted">Loading current employees…</p>' : visible.length ? visible.map(employee => `<label class="feb-choice"><input type="checkbox" data-employee-badge="${esc(employee.badge)}"${state.selected.has(employee.badge) ? ' checked' : ''}><span><strong>${esc(employee.name)}</strong><span>${esc(employee.role_label)}</span><small>Badge ID: ${esc(employee.badge)}</small></span></label>`).join('') : `<p class="muted">${state.employees.length ? 'No employees match this search. Your other selections are kept.' : 'There are no active employees to print.'}</p>`;
    node('employeeBadgeRows').querySelectorAll('[data-employee-badge]').forEach(input => {
      input.onchange = () => {
        if (state.loading || state.printing) return;
        if (input.checked) state.selected.add(input.dataset.employeeBadge);
        else state.selected.delete(input.dataset.employeeBadge);
        controls();
      };
    });
    controls();
  }

  async function roster() {
    const employees = await api('/api/employees', {cache: 'no-store'});
    if (!Array.isArray(employees)) throw Error('The employee roster could not be verified. Refresh employees and try again.');
    const active = employees.filter(employee => employee && employee.active === true && employee.removed !== true);
    const seen = new Set();
    for (const employee of active) {
      if (typeof employee.badge !== 'string' || !/^[A-Za-z0-9_-]{2,80}$/.test(employee.badge) || seen.has(employee.badge) || typeof employee.name !== 'string' || !employee.name.trim() || typeof employee.role_label !== 'string' || !employee.role_label.trim()) {
        throw Error('An active employee has incomplete badge details. Refresh employees or correct the account before printing.');
      }
      seen.add(employee.badge);
    }
    return active;
  }

  async function refresh(selectAll = false) {
    if (!requireJob('admin') || state.printing) return;
    const sequence = ++state.sequence;
    state.loading = true;
    status('');
    renderRows();
    try {
      const employees = await roster();
      if (sequence !== state.sequence || !dialog.open) return;
      state.employees = employees;
      state.selected = new Set(employees.filter(employee => selectAll || state.selected.has(employee.badge)).map(employee => employee.badge));
    } catch (error) {
      if (sequence !== state.sequence || !dialog.open) return;
      state.employees = [];
      state.selected.clear();
      status(error.message || 'The employee roster could not be loaded.', true);
    } finally {
      if (sequence === state.sequence) {
        state.loading = false;
        renderRows();
      }
    }
  }

  async function open() {
    if (!requireJob('admin')) return;
    if (!qrStatus.ready) return notify('Employee QR disabled until PUBLIC_BASE_URL is a public HTTPS URL.');
    if (dialog.open) return node('employeeBadgeSearch').focus();
    state.employees = [];
    state.selected.clear();
    node('employeeBadgeSearch').value = '';
    dialog.showModal();
    return refresh(true);
  }

  function cancelPending() {
    ++state.sequence;
    if (state.job) {
      state.job.cancelled = true;
      state.job.aborters.forEach(abort => abort());
      if (!state.job.popup.closed) state.job.popup.close();
      state.job = null;
    }
    state.loading = false;
    state.printing = false;
    state.employees = [];
    state.selected.clear();
  }

  function close() {
    cancelPending();
    if (dialog.open) dialog.close();
  }

  function sheetHtml(employees) {
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FabTrace · ${employees.length} employee ${plural(employees.length)}</title><style>
      *{box-sizing:border-box}body{margin:0;color:#111;background:#edf1f4;font:14px Arial,sans-serif}.feb-toolbar{max-width:8.5in;margin:0 auto;padding:18px;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}.feb-toolbar h1{font-size:21px;margin:0 0 5px}.feb-toolbar p{margin:5px 0;max-width:520px}.feb-toolbar button{padding:10px 14px;font:inherit;border:1px solid #52718a;border-radius:6px;background:white;cursor:pointer}.feb-toolbar button:disabled{opacity:.5;cursor:wait}.feb-toolbar .feb-print{background:#1261a0;color:white}.feb-toolbar-actions{display:flex;gap:8px}.feb-sheet{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.1in;width:8.5in;max-width:100%;margin:0 auto;padding:.4in;background:white}.feb-badge{min-width:0;min-height:2.65in;border:1px dashed #666;padding:.13in;text-align:center;break-inside:avoid;page-break-inside:avoid;overflow-wrap:anywhere}.feb-brand{font-size:9pt;font-weight:bold;letter-spacing:.5pt;margin:0 0 .07in}.feb-badge img{display:block;width:1.15in;height:1.15in;object-fit:contain;margin:0 auto .07in}.feb-name{font-size:12pt;line-height:1.2;margin:.06in 0;font-weight:bold}.feb-position{font-size:10pt;line-height:1.2;margin:.06in 0}.feb-id{font-size:9pt;line-height:1.2;margin:.08in 0 0}.feb-print-block{display:none}@page{size:letter;margin:.4in}@media print{body{background:white}.feb-toolbar{display:none}.feb-sheet{width:auto;max-width:none;margin:0;padding:0}.feb-badge{break-inside:avoid-page;page-break-inside:avoid}body:not(.feb-ready) .feb-sheet{display:none}body:not(.feb-ready) .feb-print-block{display:block;font-size:16pt}}
      </style></head><body><header class="feb-toolbar"><div><h1>Employee badge sheets</h1><p>${employees.length} ${plural(employees.length)} · Letter paper · Print at 100% / Actual size. Turn off browser headers and footers.</p><p id="badgeSheetStatus" role="status" aria-live="polite">Loading employee QR codes…</p><p>Employee QR codes identify the employee; they do not sign in to an account.</p></div><div class="feb-toolbar-actions"><button id="badgeSheetPrint" class="feb-print" disabled>Print / Save as PDF</button><button id="badgeSheetClose">Close</button></div></header><p class="feb-print-block">Badge sheets are still loading. Close this print preview and wait for every employee QR code to load.</p><main class="feb-sheet">${employees.map(employee => `<article class="feb-badge"><p class="feb-brand">FABTRACE EMPLOYEE</p><img data-qr-src="/api/employees/${encodeURIComponent(employee.badge)}/qr.png" alt="QR badge for ${esc(employee.name)}" width="110" height="110"><h2 class="feb-name">${esc(employee.name)}</h2><p class="feb-position">${esc(employee.role_label)}</p><p class="feb-id"><strong>Badge ID:</strong> ${esc(employee.badge)}</p></article>`).join('')}</main></body></html>`;
  }

  async function loadImages(job) {
    const popup = job.popup;
    const images = Array.from(popup.document.querySelectorAll('img[data-qr-src]'));
    let next = 0, loaded = 0, failed = 0;
    const progress = popup.document.getElementById('badgeSheetStatus');
    const loadOne = image => new Promise(resolve => {
      let settled = false, timer;
      const finish = ok => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        image.onload = null;
        image.onerror = null;
        job.aborters.delete(abort);
        resolve(ok);
      };
      const abort = () => finish(false);
      job.aborters.add(abort);
      image.onload = () => finish(image.naturalWidth > 0);
      image.onerror = () => finish(false);
      // Each timeout begins when its request starts, not while queued behind a large roster.
      timer = setTimeout(() => finish(false), 20000);
      image.src = image.dataset.qrSrc;
      if (image.complete && image.naturalWidth > 0) finish(true);
    });
    const worker = async () => {
      while (!job.cancelled && !popup.closed && next < images.length) {
        const ok = await loadOne(images[next++]);
        if (job.cancelled || popup.closed) return;
        if (ok) loaded++; else failed++;
        progress.textContent = `${loaded} of ${images.length} QR badges ready${failed ? ` · ${failed} could not load` : ''}…`;
      }
    };
    await Promise.all(Array.from({length: Math.min(6, images.length)}, () => worker()));
    if (job.cancelled || popup.closed) return false;
    if (!images.length || failed || loaded !== images.length) throw Error('Some employee QR codes could not be loaded. Refresh employees and try printing again.');
    return true;
  }

  async function printSelected() {
    if (!requireJob('admin') || state.loading || state.printing) return;
    if (!qrStatus.ready) return notify('Employee QR disabled until PUBLIC_BASE_URL is a public HTTPS URL.');
    const selected = new Set(state.selected);
    if (!selected.size) return status('Select at least one employee to print.', true);
    // Open during the click, before any await, so the browser can allow the print window.
    const popup = window.open('', '_blank');
    if (!popup) return notify('Allow pop-ups to print employee badge sheets.');
    const job = {popup, cancelled: false, aborters: new Set()};
    state.job = job;
    state.printing = true;
    status('Preparing the selected badges in a print window…');
    controls();
    try {
      popup.document.write('<!doctype html><html lang="en"><head><title>Preparing employee badge sheets</title></head><body><p>Checking the current employee roster…</p></body></html>');
      popup.document.close();
      const employees = await roster();
      if (job.cancelled || popup.closed) return;
      if (!requireJob('admin')) throw Error('Administrator access is required to print employee badges.');
      const chosen = employees.filter(employee => selected.has(employee.badge));
      if (chosen.length !== selected.size) throw Error('A selected employee is no longer active or available. Refresh employees and select the current badges again.');
      popup.document.open();
      popup.document.write(sheetHtml(chosen));
      popup.document.close();
      const printButton = popup.document.getElementById('badgeSheetPrint');
      popup.document.getElementById('badgeSheetClose').onclick = () => popup.close();
      printButton.onclick = () => {if (!printButton.disabled && !popup.closed) popup.print();};
      if (!await loadImages(job)) return;
      popup.document.body.classList.add('feb-ready');
      popup.document.getElementById('badgeSheetStatus').textContent = `All ${chosen.length} ${plural(chosen.length)} are ready to print.`;
      printButton.disabled = false;
      state.job = null;
      state.printing = false;
      close();
    } catch (error) {
      if (!job.cancelled && !popup.closed) {
        popup.close();
        const message = error.message || 'The employee badge sheets could not be prepared. Refresh employees and try again.';
        status(message, true);
        notify(message);
      }
    } finally {
      if (state.job === job) {
        state.job = null;
        state.printing = false;
        controls();
        if (popup.closed && !job.cancelled && !node('employeeBadgeStatus').classList.contains('feb-error')) status('Print window closed. You can print the selected badges again.');
      }
    }
  }

  node('printEmployeeBadges').onclick = open;
  node('employeeBadgeClose').onclick = close;
  node('employeeBadgeRefresh').onclick = () => refresh(false);
  node('employeeBadgePrint').onclick = printSelected;
  node('employeeBadgeSearch').oninput = renderRows;
  node('employeeBadgeSelectAll').onclick = () => {if (!state.loading && !state.printing) {state.selected = new Set(state.employees.map(employee => employee.badge)); renderRows();}};
  node('employeeBadgeClear').onclick = () => {if (!state.loading && !state.printing) {state.selected.clear(); renderRows();}};
  dialog.addEventListener('cancel', event => {event.preventDefault(); close();});
  dialog.addEventListener('close', cancelPending);
  window.FabEmployeeBadges = {open, close, printSelected, refresh};
})();
