/* Shared, display-only flow labels and colors. The API owns each item's stage. */
(() => {
  'use strict';
  const rows = [
    ['inventory', 'Inventory', 'black'],
    ['qa_001', 'QA/QC-001', 'black', true],
    ['preparation', 'Prep/Fabrication', 'red'],
    ['qa_002', 'QA/QC-002', 'red', true],
    ['floor', 'Floor', 'yellow'],
    ['welding', 'Process Welder', 'blue'],
    ['qa_003', 'QA/QC-003', 'blue', true],
    ['testing', 'Testing', 'orange'],
    ['paint', 'Paint', 'pink'],
    ['qa_004', 'QA/QC-004', 'pink', true],
    ['ready_to_ship', 'Ready To Ship', 'green'],
  ];
  const catalog = rows.map(([key, label, color, qa = false]) => Object.freeze({key, label, color, qa}));
  const byKey = new Map(catalog.map(stage => [stage.key, stage]));
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function normalize(value) {
    const candidate = value?.flow_stage || value;
    const known = byKey.get(candidate?.key);
    return known ? {...known, source_item_id: String(candidate.source_item_id || ''), inherited: candidate.inherited === true} : null;
  }
  function className(value) {
    const stage = normalize(value);
    return stage ? 'fst-text fst-color-' + stage.color : '';
  }
  function title(stage) {
    return stage.label + (stage.inherited && stage.source_item_id ? ' · Following ' + stage.source_item_id : '');
  }
  function text(value, label, tag = 'span') {
    const stage = normalize(value), safeTag = ['span','strong','small'].includes(tag) ? tag : 'span';
    return `<${safeTag}${stage ? ` class="${className(stage)}" data-flow-stage="${stage.key}" title="${escape(title(stage))}"` : ''}>${escape(label)}</${safeTag}>`;
  }
  function spoolNumber(value) {
    const id = value?.item_id || value?.id || '';
    return String(value?.qr_alias || (value?.display_code !== id && value?.display_code) || value?.spool_number || value?.google_part_number || value?.part_number || value?.display_code || id);
  }
  function spoolText(value, label = spoolNumber(value), tag = 'span') {
    const number = value?.spool_number || value?.google_part_number || value?.part_number || label;
    const id = value?.item_id || value?.id || '';
    return text(value, label, tag).replace(/^<([a-z]+)/, (_, safeTag) => `<${safeTag} data-spool-number="${escape(number)}" data-spool-id="${escape(id)}"`);
  }
  function decorateSpool(element, value, label = spoolNumber(value)) {
    if (!element) return;
    const stage = normalize(value);
    element.textContent = String(label ?? '');
    element.classList.remove('fst-text', ...new Set(catalog.map(row => 'fst-color-' + row.color)));
    element.removeAttribute('data-flow-stage');
    element.removeAttribute('title');
    element.setAttribute('data-spool-number', value?.spool_number || value?.google_part_number || value?.part_number || String(label ?? ''));
    element.setAttribute('data-spool-id', value?.item_id || value?.id || '');
    if (stage) {
      element.classList.add(...className(stage).split(' '));
      element.setAttribute('data-flow-stage', stage.key);
      element.setAttribute('title', title(stage));
    }
  }
  function badge(value) {
    const stage = normalize(value);
    return stage ? `<span class="fst-stage ${className(stage)}" data-flow-stage="${stage.key}" title="${escape(title(stage))}">${escape(stage.label)}</span>` : '';
  }
  function legend() {
    return `<aside class="fst-legend" aria-label="Flow status color key"><strong>Spool number colors</strong><ul>${catalog.filter(stage => !stage.qa).map(stage => `<li>${text(stage, stage.key === 'paint' ? 'Painting' : stage.label)}<small>${stage.color[0].toUpperCase() + stage.color.slice(1)}</small></li>`).join('')}</ul><p>Each spool number uses its current Flow status color. QA/QC checkpoints keep the preceding work-stage color.</p></aside>`;
  }
  function processBoard(records, options = {}) {
    const attribute = ['data-flow-spool', 'data-pp-spool'].includes(options.attribute) ? options.attribute : 'data-flow-spool';
    const groups = new Map(catalog.map(stage => [stage.key, []])), seen = new Set(), unknown = [];
    const compare = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'}).compare;
    for (const row of Array.isArray(records) ? records : []) {
      const id = String(row?.item_id || row?.id || '');
      if (!id || seen.has(id)) continue;
      seen.add(id);
      const stage = normalize(row), entry = {...row, item_id: id};
      (stage ? groups.get(stage.key) : unknown).push(entry);
    }
    const card = row => {
      const context = [row.purchase_order ? 'P.O. ' + row.purchase_order : row.project_name || row.project_id,
        row.assembly_number || row.assembly_id].filter(Boolean);
      return `<li data-process-spool="${escape(row.item_id)}"><button type="button" class="fst-spool-link" ${attribute}="${escape(row.item_id)}" data-spool-project="${escape(row.project_id || '')}" aria-label="Open process flow for ${escape(spoolNumber(row))}">${spoolText(row, spoolNumber(row), 'strong')}</button>${context.length ? `<small class="fst-spool-context">${context.map(escape).join(' · ')}</small>` : ''}${row.flow_stage?.blocked || row.on_hold || Number(row.open_exceptions) > 0 ? '<span class="fst-spool-blocked">Work blocked</span>' : ''}</li>`;
    };
    const section = (stage, entries, index) => {
      entries.sort((a, b) => compare(spoolNumber(a), spoolNumber(b)) || compare(a.item_id, b.item_id));
      return `<section class="fst-process" data-spool-process="${stage.key}"><header class="fst-process-heading"><span class="fst-process-sequence">${index + 1}</span><h3>${escape(stage.label)}</h3><span class="fst-process-count" aria-label="${entries.length} individual spools">${entries.length}</span></header>${entries.length ? `<ul class="fst-process-spools">${entries.map(card).join('')}</ul>` : '<p class="fst-process-empty">No spools at this process</p>'}</section>`;
    };
    return `<section class="fst-process-board" aria-label="${escape(options.title || 'Individual spools by process')}"><div class="fst-process-board-heading"><h2>${escape(options.title || 'Individual spools by process')}</h2><span>${seen.size} individual spool${seen.size === 1 ? '' : 's'}</span></div><p class="fst-process-help">Each numbered copy appears under its current process. Select its colored number to open that spool.</p><div class="fst-process-grid">${catalog.map((stage, index) => section(stage, groups.get(stage.key), index)).join('')}${unknown.length ? section({key:'unknown', label:'Status unavailable'}, unknown, catalog.length) : ''}</div></section>`;
  }
  function strip(_serverCatalog, value) {
    const current = normalize(value);
    return `<section class="fst-flow" aria-label="Flow progress"><div class="fst-flow-heading"><h3>Flow progress</h3>${current ? `<span>Current stage ${badge(current)}</span>` : ''}</div><ol>${catalog.map((stage, index) => `<li data-flow-stage="${stage.key}"${current?.key === stage.key ? ' class="fst-current" aria-current="step"' : ''}><span class="fst-sequence">${index + 1}</span>${text(stage, stage.label, 'strong')}${stage.qa ? '<small>QA/QC checkpoint</small>' : ''}</li>`).join('')}</ol>${current?.inherited ? `<p class="fst-following">This part is following ${escape(current.source_item_id)} through ${escape(current.label)}.</p>` : ''}</section>`;
  }
  window.FabFlowStatus = Object.freeze({catalog: Object.freeze(catalog), normalize, className, text, spoolNumber, spoolText, decorateSpool, badge, legend, processBoard, strip});
})();
