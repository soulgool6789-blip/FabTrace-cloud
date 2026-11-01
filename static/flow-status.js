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
  function badge(value) {
    const stage = normalize(value);
    return stage ? `<span class="fst-stage ${className(stage)}" data-flow-stage="${stage.key}" title="${escape(title(stage))}">${escape(stage.label)}</span>` : '';
  }
  function legend() {
    return `<aside class="fst-legend" aria-label="Flow status color key"><strong>Part text colors</strong><ul>${catalog.filter(stage => !stage.qa).map(stage => `<li>${text(stage, stage.key === 'paint' ? 'Painting' : stage.label)}<small>${stage.color[0].toUpperCase() + stage.color.slice(1)}</small></li>`).join('')}</ul><p>QA/QC checkpoints keep the preceding work-stage color. The stage name and hold status are shown separately.</p></aside>`;
  }
  function strip(_serverCatalog, value) {
    const current = normalize(value);
    return `<section class="fst-flow" aria-label="Flow progress"><div class="fst-flow-heading"><h3>Flow progress</h3>${current ? `<span>Current stage ${badge(current)}</span>` : ''}</div><ol>${catalog.map((stage, index) => `<li data-flow-stage="${stage.key}"${current?.key === stage.key ? ' class="fst-current" aria-current="step"' : ''}><span class="fst-sequence">${index + 1}</span>${text(stage, stage.label, 'strong')}${stage.qa ? '<small>QA/QC checkpoint</small>' : ''}</li>`).join('')}</ol>${current?.inherited ? `<p class="fst-following">This part is following ${escape(current.source_item_id)} through ${escape(current.label)}.</p>` : ''}</section>`;
  }
  window.FabFlowStatus = Object.freeze({catalog: Object.freeze(catalog), normalize, className, text, badge, legend, strip});
})();
