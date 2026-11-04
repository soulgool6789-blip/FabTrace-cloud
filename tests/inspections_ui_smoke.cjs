/* Inspections navigation contracts with synthetic records. No service or account is contacted. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=()=>fs.readFileSync(path.join(__dirname,'../static/inspections.js'),'utf8');
const names=[
  ['QA-001','QA/QC-001','Material'],
  ['QA-002','QA/QC-002','Isometric Dimensions Test'],
  ['QA-003','QA/QC-003','Weld Inspection'],
  ['QA-004','QA/QC-004','NDT Results'],
  ['QA-005','QA/QC-005','Verify Pressure Testing'],
  ['QA-006','QA/QC-006','Final Inspection'],
];
const clone=value=>structuredClone(value);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const catalog={version:'CLM-25-v1',routes:[{id:'component',first_step:1,last_step:8},{id:'spool',first_step:9,last_step:16},{id:'assembly',first_step:17,last_step:25}],steps:[2,11,15,18,22].map((number,index)=>({number,qa:true,qa_code:['QA-001','QA-002','QA-003','QA-004','QA-006'][index],display_qa_code:['QA/QC-001','QA/QC-002','QA/QC-003','QA/QC-004','QA/QC-006'][index],title:['Material','Isometric Dimensions Test','Weld Inspection','NDT Results','Final Inspection'][index],checks:[{id:'s'+number+'_1',label:'Recorded checklist for step '+number}],route:number<9?'component':number<17?'spool':'assembly'}))};
function traveler(item_id,route,step,extra={}){
  const qa=({2:'QA-001',11:'QA-002',15:'QA-003',18:'QA-004',22:'QA-006'})[step]||null;
  const stage=({2:'qa_001',11:'qa_002',15:'qa_003',18:'qa_test_results',22:'qa_final'})[step]||'floor';
  return {item_id,kind:route==='spool'?'Spool':route==='assembly'?'Assembly':'Part',route,project_id:'P1',subproject_id:'AREA-1',purchase_order:'PO-1',description:item_id+' description',catalog_version:'CLM-25-v1',status:'active',current_step:step,current_display_step:step===18?19:step===22?26:step,current_qa_code:qa,current_testing_phase:step===18?'ndt_qa':null,current_title:(qa?.replace('QA-','QA/QC-')||'Step')+' - '+(names.find(row=>row[0]===qa)?.[2]||'Production'),flow_stage:{key:stage,source_item_id:item_id,inherited:false},open_exceptions:0,blockers:[],work:{pending:true,current_checks:[{id:'s'+step+'_1',label:'Recorded checklist for step '+step}],requirements:['Record the signed reference.']},...extra};
}
function physical(item_id,alias,extra={}){
  return {item_id,route:'spool',spool_number:'643-777-PCW-03-01',google_part_number:'643-777-PCW-03-01',qr_alias:alias,display_code:alias,project_id:'P1',subproject_id:'AREA-1',purchase_order:'PO-1',description:'Physical spool '+alias,assembly_id:'ASM-NDT',assembly_number:'ASSY-001',status:'not_started',catalog_version:'CLM-25-v1',current_step:null,current_title:'',open_exceptions:0,blockers:[],flow_stage:{key:'inventory',source_item_id:item_id,inherited:false},...extra};
}
function fixtures(){
  const spools=[
    physical('SPOOL-A','643-777-PCW-03-01-[001]',{status:'active',current_step:11,current_title:'QA/QC-002 - Isometric Dimensions Test',flow_stage:{key:'qa_002',source_item_id:'SPOOL-A',inherited:false}}),
    physical('SPOOL-B','643-777-PCW-03-01-[002]',{assembly_id:'ASM-NOT-STARTED',assembly_number:'ASSY-002',blockers:['Material identification <pending> & required']}),
    physical('SPOOL-C','643-777-PCW-03-01-[003]',{status:'active',current_step:15,project_id:'P2',purchase_order:'PO-2',assembly_id:'ASM-PRESSURE',flow_stage:{key:'qa_003',source_item_id:'SPOOL-C',inherited:false}}),
    physical('SPOOL-NDT-1','643-777-PCW-03-01-[004]',{status:'completed',flow_stage:{key:'qa_test_results',source_item_id:'ASM-NDT',inherited:true}}),
    physical('SPOOL-NDT-2','643-777-PCW-03-01-[005]',{status:'completed',flow_stage:{key:'qa_test_results',source_item_id:'ASM-NDT',inherited:true}}),
    physical('SPOOL-PRESSURE','643-777-PCW-03-01-[006]',{status:'completed',assembly_id:'ASM-PRESSURE',assembly_number:'ASSY-003',flow_stage:{key:'qa_pressure_results',source_item_id:'ASM-PRESSURE',inherited:true}}),
    physical('SPOOL-FINAL','643-777-PCW-03-01-[007]',{status:'completed',assembly_id:'ASM-FINAL',assembly_number:'ASSY-004',flow_stage:{key:'qa_final',source_item_id:'ASM-FINAL',inherited:true}}),
    physical('SPOOL-LEGACY','643-777-PCW-03-01-[008]',{status:'completed',assembly_id:'ASM-LEGACY-FINAL',assembly_number:'ASSY-005',catalog_version:'CLM-24-v6',flow_stage:{key:'qa_004',source_item_id:'ASM-LEGACY-FINAL',inherited:true}}),
  ];
  const items=[
    traveler('COMP-MATERIAL','component',2,{parent_item_id:'SPOOL-A',assembly_id:'ASM-NDT'}),
    traveler('SPOOL-A','spool',11,{...spools[0],current_qa_code:'QA-002',current_testing_phase:null}),
    traveler('SPOOL-C','spool',15,{...spools[2],current_qa_code:'QA-003',current_testing_phase:null}),
    traveler('ASM-NDT','assembly',18,{assembly_id:'ASM-NDT',assembly_number:'ASSY-001'}),
    traveler('ASM-PRESSURE','assembly',18,{current_display_step:22,current_qa_code:'QA-005',current_testing_phase:'pressure_qa',current_title:'QA/QC-005 - Verify Pressure Testing',flow_stage:{key:'qa_pressure_results',source_item_id:'ASM-PRESSURE',inherited:false}}),
    traveler('ASM-FINAL','assembly',22,{assembly_number:'ASSY-004'}),
    traveler('ASM-LEGACY-FINAL','assembly',22,{catalog_version:'CLM-24-v6',current_display_step:22,current_qa_code:'QA-005',current_title:'QA/QC-005 - Final Inspection',flow_stage:{key:'qa_004',source_item_id:'ASM-LEGACY-FINAL',inherited:false}}),
    traveler('ASM-LEGACY-PRESSURE','assembly',18,{catalog_version:'CLM-24-v6',current_display_step:18,current_qa_code:'QA-004',current_testing_phase:'pressure_qa',current_title:'QA/QC-004 - Verify Pressure Testing'}),
    traveler('ASM-AMBIGUOUS','assembly',18,{catalog_version:'CLM-24-v6',current_display_step:18,current_qa_code:'QA-004',current_testing_phase:null,current_title:'QA/QC-004 - Verify Test Results'}),
    traveler('ASM-RELEASED','assembly',22,{status:'admin_released',released:true,current_qa_code:'QA-006',open_exceptions:1,blockers:['Unresolved coating <defect>']}),
  ];
  return {items,spools,catalog:clone(catalog)};
}
function harness(role='inspector'){
  const nodes=new Map(),calls=[],opened=[],messages=[],pendingTimers=new Map();let timer=0,readHook=null;
  class Element{
    constructor(id){this.id=id;this.value='';this.textContent='';this.disabled=false;this.dataset={};this.attributes={};this.listeners={};this.children=[];this.classes=new Set();this.selectionStart=0;this.selectionEnd=0;this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),contains:x=>this.classes.has(x),toggle:(x,on)=>{if(on??!this.classes.has(x))this.classes.add(x);else this.classes.delete(x);}};}
    set innerHTML(value){
      for(const id of this.children)nodes.delete(id);this.children=[];this.html=value;
      for(const match of value.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){
        const child=new Element(match[1]);child.value=match[0].match(/\bvalue="([^"]*)"/)?.[1]||'';child.disabled=/\sdisabled(?:\s|>)/.test(match[0]);
        for(const cls of (match[0].match(/\bclass="([^"]*)"/)?.[1]||'').split(' '))child.classes.add(cls);
        nodes.set(child.id,child);this.children.push(child.id);
      }
      for(const match of value.matchAll(/<select[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){
        const opts=[...match[2].matchAll(/<option value="([^"]*)"([^>]*)>/g)];nodes.get(match[1]).value=(opts.find(row=>row[2].includes('selected'))||opts[0])?.[1]||'';
      }
    }
    get innerHTML(){return this.html||'';}
    addEventListener(name,fn){this.listeners[name]=fn;}
    setAttribute(name,value){this.attributes[name]=String(value);}
    removeAttribute(name){delete this.attributes[name];}
    querySelectorAll(){return [];}
    focus(){this.focused=true;}
    setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
    scrollIntoView(){}
  }
  for(const id of ['inspectionsContent','navInspections','inspectionsPage'])nodes.set(id,new Element(id));
  const data=fixtures();
  const ctx={console,URL,URLSearchParams,AbortController,encodeURIComponent,decodeURIComponent,esc,me:{role,badge:role==='inspector'?'QA1':'OTHER'},current:null,
    document:{getElementById:id=>nodes.get(id)||null},location:{origin:'https://example.test'},
    history:{replaceState(_d,_t,url){ctx.url=url;}},
    show(page){ctx.page=page;return true;},stopCloudCamera(){},notify:message=>messages.push(message),
    setTimeout(fn){const id=++timer;pendingTimers.set(id,fn);return id;},clearTimeout(id){pendingTimers.delete(id);},
    FabFlow:{async open(options){opened.push({kind:'flow',options:clone(options)});}},
    FabSpoolBom:{async open(options,opener){opened.push({kind:'material',options:clone(options),opener});}},
    FabFlowStatus:{spoolNumber:row=>row.qr_alias||row.spool_number||row.item_id,spoolText:(row,label)=>esc(label||row.qr_alias||row.spool_number||row.item_id),badge:row=>row?'<span>'+esc(row.label||row.key)+'</span>':''},
    async api(url,options={}){
      calls.push({url,method:options.method||'GET',signal:options.signal});
      if((options.method||'GET')!=='GET')throw Error('Inspections navigation must not write production state.');
      if(readHook){const special=readHook(url,options);if(special!==undefined)return special;}
      if(url==='/api/flow/catalog')return clone(data.catalog);
      if(url==='/api/flow/items')return {items:clone(data.items)};
      if(url==='/api/flow/board')return {items:clone(data.spools)};
      throw Error('Unexpected endpoint '+url);
    },
  };
  ctx.window=ctx;vm.createContext(ctx);vm.runInContext(source(),ctx,{filename:'inspections.js'});
  const html=()=>nodes.get('inspectionsContent').innerHTML;
  const click=async(action,id='')=>{
    const button={disabled:false,dataset:{inspectionAction:action,inspectionId:id},closest(selector){return selector==='[data-inspection-action]'?button:null;}};
    await nodes.get('inspectionsContent').listeners.click({target:button,preventDefault(){}});
    return button;
  };
  const change=async(id,value)=>{const el=nodes.get(id);assert.ok(el,id+' is present');el.value=value;await el.onchange?.({target:el});await el.listeners.change?.({target:el});};
  return {ctx,data,nodes,calls,opened,messages,pendingTimers,html,click,change,setReadHook(fn){readHook=fn;},row(id){return html().match(new RegExp('<tr\\b[^>]*data-inspection-record="'+id+'"[^>]*>[\\s\\S]*?<\\/tr>'))?.[0]||'';}};
}

(async()=>{
  const checks=[];
  {
    const h=harness();await h.ctx.FabInspections.open();
    assert.equal(h.ctx.page,'inspectionsPage');
    assert.deepEqual([...h.html().matchAll(/data-inspection-code="([^"]+)"/g)].map(row=>row[1]),names.map(row=>row[0]));
    for(const [,code,name] of names){assert.ok(h.html().includes(code),code+' is visible');assert.ok(h.html().includes(name),name+' is visible');}
    assert.equal(h.calls.length,3,'The menu reads its three shared projections, without a detail request per record');
    assert.deepEqual(h.calls.map(row=>row.url).sort(),['/api/flow/board','/api/flow/catalog','/api/flow/items']);
    assert.equal(new URL(h.ctx.url,'https://example.test').searchParams.get('inspection'),'QA-001');
    assert.ok(h.row('SPOOL-A'));assert.ok(h.row('SPOOL-B'));assert.ok(h.row('COMP-MATERIAL'));
    assert.match(h.row('COMP-MATERIAL'),/data-inspection-current="true"/);
    assert.match(h.row('SPOOL-B'),/data-inspection-current="false"/);
    assert.match(h.html(),/Material identification &lt;pending&gt; &amp; required/);assert.doesNotMatch(h.html(),/<pending>/);
    const button=await h.click('open-record','SPOOL-B');
    assert.equal(h.opened.at(-1).kind,'material');
    assert.deepEqual(h.opened.at(-1).options,{api_url:'/api/spool-boms/spools/SPOOL-B',item_id:'SPOOL-B',spool_number:'643-777-PCW-03-01-[002]'});
    assert.equal(h.opened.at(-1).opener,button);
    await h.click('open-record','COMP-MATERIAL');assert.deepEqual(h.opened.at(-1),{kind:'flow',options:{item:'COMP-MATERIAL',project:'P1'}});
    checks.push('All six named reviews are present; Material opens the exact spool receiving record or actual component traveler without changing production state');
  }
  {
    const h=harness();await h.ctx.FabInspections.open({inspection:'QA-002'});
    assert.match(h.row('SPOOL-A'),/data-inspection-current="true"/);assert.match(h.row('SPOOL-B'),/data-inspection-current="false"/);
    assert.match(h.row('SPOOL-A'),/643-777-PCW-03-01-\[001\]/);assert.match(h.row('SPOOL-B'),/643-777-PCW-03-01-\[002\]/);
    assert.equal((h.html().match(/data-inspection-record="SPOOL-A"/g)||[]).length,1,'Traveler and physical-board copies are deduplicated by item identity');
    assert.equal(h.row('ASM-NDT'),'');assert.equal(h.row('COMP-MATERIAL'),'');
    await h.click('open-record','SPOOL-A');assert.deepEqual(h.opened.at(-1),{kind:'flow',options:{item:'SPOOL-A',project:'P1'}});
    await h.click('select','QA-003');assert.match(h.row('SPOOL-A'),/data-inspection-current="false"/);assert.match(h.row('SPOOL-C'),/data-inspection-current="true"/);
    await h.click('open-record','SPOOL-C');assert.deepEqual(h.opened.at(-1),{kind:'flow',options:{item:'SPOOL-C',project:'P2'}});
    assert.equal(h.calls.length,3,'Changing review category uses loaded projection data');
    checks.push('Dimension and weld reviews preserve each physical spool identity, including no-traveler spools and same-number copies');
  }
  {
    const h=harness();await h.ctx.FabInspections.open({inspection:'QA-004'});
    assert.match(h.row('ASM-NDT'),/data-inspection-current="true"/);
    for(const id of ['ASM-PRESSURE','ASM-LEGACY-PRESSURE','ASM-AMBIGUOUS','ASM-LEGACY-FINAL'])assert.match(h.row(id),/data-inspection-current="false"/,id+' is not current NDT');
    assert.equal((h.html().match(/data-inspection-record="ASM-NDT"/g)||[]).length,1,'Multiple child spools share one assembly review record');
    assert.equal(h.row('SPOOL-NDT-1'),'');assert.equal(h.row('SPOOL-NDT-2'),'');
    await h.click('open-record','ASM-NDT');assert.deepEqual(h.opened.at(-1),{kind:'flow',options:{item:'ASM-NDT',project:'P1'}});
    await h.click('select','QA-005');
    for(const id of ['ASM-PRESSURE','ASM-LEGACY-PRESSURE'])assert.match(h.row(id),/data-inspection-current="true"/,id+' has a current pressure phase');
    for(const id of ['ASM-NDT','ASM-LEGACY-FINAL','ASM-AMBIGUOUS','ASM-RELEASED'])assert.match(h.row(id),/data-inspection-current="false"/,id+' is not current pressure');
    await h.click('select','QA-006');
    assert.match(h.row('ASM-FINAL'),/data-inspection-current="true"/);assert.match(h.row('ASM-LEGACY-FINAL'),/data-inspection-current="true"/);
    assert.match(h.row('ASM-PRESSURE'),/data-inspection-current="false"/);assert.match(h.row('ASM-RELEASED'),/data-inspection-current="false"/);
    assert.match(h.row('ASM-NOT-STARTED'),/data-inspection-current="false"/,'Known parent without a traveler remains available as an unstarted record');
    await h.click('open-record','ASM-LEGACY-FINAL');assert.equal(h.opened.at(-1).options.item,'ASM-LEGACY-FINAL');
    checks.push('NDT, pressure and final menus open exact assembly records; explicit phases separate legacy pressure from NDT, and retained QA005 final remains final');
  }
  {
    const h=harness();await h.ctx.FabInspections.open({inspection:'QA-002',project:'P1',query:'[001]',status:'current'});
    assert.ok(h.row('SPOOL-A'));assert.equal(h.row('SPOOL-B'),'');assert.equal(h.row('SPOOL-C'),'');
    const state=JSON.parse(JSON.stringify(h.ctx.FabInspections.navigationState()));
    for(const [key,value] of Object.entries({inspection:'QA-002',project:'P1',query:'[001]',status:'current'}))assert.equal(state[key],value);
    const q=new URL(h.ctx.url,'https://example.test').searchParams;
    for(const [key,value] of Object.entries({inspections:'1',inspection:'QA-002',project:'P1',q:'[001]',status:'current'}))assert.equal(q.get(key),value);
    await h.change('inspectionsStatus','');await h.change('inspectionsProject','P2');
    const search=h.nodes.get('inspectionsSearch');search.value='[003]';search.selectionStart=2;search.selectionEnd=4;await search.oninput();
    assert.ok(h.row('SPOOL-C'));assert.equal(h.row('SPOOL-A'),'');
    assert.equal(h.ctx.FabInspections.navigationState().query,'[003]');
    assert.equal(h.nodes.get('inspectionsSearch').focused,true);assert.equal(h.nodes.get('inspectionsSearch').selectionStart,2);assert.equal(h.nodes.get('inspectionsSearch').selectionEnd,4);
    await h.ctx.FabInspections.open({inspection:'QA-001',project:'',query:'',status:'attention'});
    assert.ok(h.row('SPOOL-B'));assert.equal(h.row('SPOOL-A'),'');
    await h.ctx.FabInspections.open({inspection:'QA-999',status:'fake'});
    assert.equal(h.ctx.FabInspections.navigationState().inspection,'QA-001','Unknown category is normalized to a supported menu entry');
    const before=h.opened.length;await h.click('open-record','MISSING-SPOOL');assert.equal(h.opened.length,before,'Unknown identities are never passed to a record writer');
    checks.push('Project, search and current/attention filters preserve shareable navigation state and cannot manufacture an unknown record target');
  }
  {
    for(const role of ['inspector','admin','supervisor','welder','painter']){
      const h=harness(role);await h.ctx.FabInspections.open({inspection:'QA-003'});await h.click('open-record','SPOOL-A');
      assert.equal(h.opened.at(-1).kind,'flow');assert.ok(h.calls.every(row=>row.method==='GET'));
      assert.doesNotMatch(h.html(),/<form|name="(?:result|reference|check_)|data-inspection-action="(?:pass|fail|approve)"/,'Menu never adds an independent signing path');
      if(role!=='inspector')assert.doesNotMatch(h.html(),/Recorded checklist for step|Confirm every checklist entry/,'QA task text is not assigned to another position');
    }
    checks.push('All roles can reach recorded inspection evidence; the menu has no approval form or mutation endpoint and does not assign QA task checklists to other roles');
  }
  {
    const h=harness();h.setReadHook(url=>url==='/api/flow/items'?Promise.reject(Error('Synthetic inspection read <failure>')):undefined);
    await h.ctx.FabInspections.open();assert.match(h.html(),/role="alert"/);assert.match(h.html(),/read &lt;failure&gt;/);assert.doesNotMatch(h.html(),/<failure>/);
    assert.equal(h.row('SPOOL-A'),'');h.setReadHook(null);await h.click('refresh');assert.ok(h.row('SPOOL-A'));
    checks.push('A failed projection read shows a retriable escaped error instead of presenting stale records as current');
  }
  {
    const h=harness(),held=deferred();let wait=true;
    h.setReadHook(url=>wait&&url==='/api/flow/items'?held.promise:undefined);
    const older=h.ctx.FabInspections.open({inspection:'QA-002',project:'P1'});
    await Promise.resolve();wait=false;
    await h.ctx.FabInspections.open({inspection:'QA-003',project:'P2'});
    const rendered=h.html(),url=h.ctx.url;
    held.resolve({items:[]});await older;
    assert.equal(h.html(),rendered);assert.equal(h.ctx.url,url);assert.ok(h.row('SPOOL-C'));
    const h2=harness(),late=deferred();h2.setReadHook(url=>url==='/api/flow/items'?late.promise:undefined);
    const pending=h2.ctx.FabInspections.open({inspection:'QA-002'});await Promise.resolve();h2.ctx.FabInspections.cancelPending();
    const stopped=h2.html(),oldUrl=h2.ctx.url;late.resolve({items:clone(h2.data.items)});await pending;
    assert.equal(h2.html(),stopped);assert.equal(h2.ctx.url,oldUrl);assert.ok(h2.calls.every(row=>!row.signal||row.signal.aborted));assert.equal(h2.pendingTimers.size,0);
    checks.push('Late responses cannot replace a newer inspection selection or restore an abandoned screen');
  }
  console.log(JSON.stringify({status:'passed',contracts:checks.length,checks},null,2));
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
