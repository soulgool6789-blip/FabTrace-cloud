/* Failed-inspection queue contracts with synthetic records. No service or account is contacted. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const clone=value=>structuredClone(value);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const inspectionNames={'001':'Material','002':'Isometric Dimensions Test','003':'Weld Inspection','004':'NDT Results','005':'Verify Pressure Testing','006':'Final Inspection'};
function failure(id,key,extra={}){
  return {id,inspection_key:key,qa_code:'QA-'+key,display_qa_code:'QA/QC-'+key,title:'QA/QC-'+key+' - '+inspectionNames[key],reason:'Recorded defect '+id,reference:'NCR-'+id,actor:'QA1',at:'2026-11-04T15:00:00Z',source_item_id:'SPOOL-A',source_kind:'Spool',scope:'spool',source_released:false,saved_qa_code:'QA-'+key,saved_title:'Historical review title',testing_phase:null,status:'needs_rework',return_step:10,return_title:'Fit-Up & Tack Weld',return_station:{id:'preparation',label:'Prep/Fabrication'},return_roles:['welder'],return_positions:['Fit-Up Welder'],return_employee:null,routing_known:true,correction:null,open_kind:'flow',open_item_id:'SPOOL-A',...extra};
}
function spool(item_id,alias,failures,extra={}){
  return {item_id,qr_alias:alias,spool_number:'643-777-PCW-03-01',description:'Physical spool '+alias,project_id:'P1',purchase_order:'PO-1',assembly_id:'ASM-TESTS',assembly_number:'ASSY-001',released:false,failures,...extra};
}
function fixtures(){
  const ndt=failure('FLOW-ASM-NDT','004',{reason:'NDT indication <root> & rejected',reference:'NCR-NDT-004',source_item_id:'ASM-TESTS',source_kind:'Assembly',scope:'assembly',testing_phase:'ndt_qa',status:'awaiting_reinspection',return_step:17,return_title:'NDT rework',return_station:{id:'testing',label:'Testing'},return_roles:['ndt'],return_positions:['NDT Technician'],return_employee:{badge:'NDT1',name:'NDT <Tech>',role:'ndt'},correction:{event_id:1001,description:'Ground out <indication> and completed repair',actor:'NDT1',at:'2026-11-04T16:00:00Z',reference:'REPAIR-NDT-1001'},open_item_id:'ASM-TESTS'});
  const pressure=failure('FLOW-ASM-PRESSURE','005',{reason:'Leak at weld <W7>',reference:'NCR-PRESSURE-005',source_item_id:'ASM-TESTS',source_kind:'Assembly',scope:'assembly',testing_phase:'pressure_qa',status:'return_required',return_step:17,return_title:'Pressure Testing rework',return_station:{id:'testing',label:'Testing'},return_roles:['pressure_testing_technician'],return_positions:['Pressure Testing Technician'],return_employee:{badge:'PRESS1',name:'Pressure Tech',role:'pressure_testing_technician'},open_item_id:'ASM-TESTS'});
  const material=failure('MATERIAL-1-PIECE-2','001',{reason:'Wrong material <grade> & damaged end',reference:'MTR-<A>',piece_key:'BOM-1:2',piece_identifier:'BOM item 1 · piece 2',return_step:1,return_title:'Receive Shipment',return_station:{id:'receiving',label:'Receiving / Inventory'},return_roles:['handler'],return_positions:['Material Coordinator'],open_kind:'material'});
  const fitup=failure('FLOW-SPOOL-FITUP','002',{reason:'Dimension out of tolerance',reference:'ISO-REV-B',return_employee:{badge:'FIT1',name:'Fit-Up Welder One',role:'welder'}});
  const legacy=failure('FLOW-LEGACY-UNKNOWN','legacy_testing',{qa_code:'QA-004',display_qa_code:'QA/QC-004',title:'QA/QC-004 - Test Results (retained)',saved_qa_code:'QA-004',saved_title:'QA/QC-004 - Verify Test Results',reason:'Old failed test has incomplete return provenance',source_item_id:'ASM-LEGACY',source_kind:'Assembly',scope:'assembly',return_step:null,return_title:'',return_station:null,return_roles:[],return_positions:[],routing_known:false,open_item_id:'ASM-LEGACY'});
  const final=failure('FLOW-LEGACY-FINAL','006',{saved_qa_code:'QA-005',saved_title:'QA/QC-005 - Final Inspection',source_item_id:'ASM-FINAL',source_kind:'Assembly',scope:'assembly',return_step:21,return_title:'Sandblast & Paint',return_station:{id:'paint',label:'Paint'},return_roles:['painter'],return_positions:['Painter'],open_item_id:'ASM-FINAL'});
  return {spools:[
    spool('SPOOL-A','643-777-PCW-03-01-[001]',[material,fitup,ndt,pressure]),
    spool('SPOOL-B','643-777-PCW-03-01-[002]',[clone(ndt)]),
    spool('SPOOL-LEGACY','643-777-PCW-03-01-[003]',[legacy],{project_id:'P2',purchase_order:'PO-2',assembly_id:'ASM-LEGACY',assembly_number:'ASSY-002'}),
    spool('SPOOL-FINAL','643-777-PCW-03-01-[004]',[final],{project_id:'P2',purchase_order:'PO-2',assembly_id:'ASM-FINAL',assembly_number:'ASSY-003'}),
  ],totals:{spools:4,failures:6,needs_rework:4,awaiting_reinspection:1,return_required:1}};
}
function elementHtml(source,opening){
  const match=opening.exec(source);if(!match)return '';
  const tag=match[0].match(/^<([a-z][\w:-]*)\b/i)[1],tags=new RegExp('<\\/?'+tag+'\\b[^>]*>','gi');tags.lastIndex=match.index;
  let depth=0,next;while((next=tags.exec(source))){depth+=next[0].startsWith('</')?-1:1;if(depth===0)return source.slice(match.index,tags.lastIndex);}
  assert.fail('Unclosed '+tag+' element in failed-inspection output');
}
function harness(role='inspector'){
  const nodes=new Map(),calls=[],opened=[],messages=[],timers=new Map();let timer=0,readHook=null;
  class Element{
    constructor(id){this.id=id;this.value='';this.textContent='';this.disabled=false;this.dataset={};this.attributes={};this.listeners={};this.children=[];this.classes=new Set();this.selectionStart=0;this.selectionEnd=0;this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),contains:x=>this.classes.has(x),toggle:(x,on)=>{if(on??!this.classes.has(x))this.classes.add(x);else this.classes.delete(x);}};}
    set innerHTML(value){
      for(const id of this.children)nodes.delete(id);this.children=[];this.html=value;
      for(const match of value.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const child=new Element(match[1]);child.value=match[0].match(/\bvalue="([^"]*)"/)?.[1]||'';child.disabled=/\sdisabled(?:\s|>)/.test(match[0]);nodes.set(child.id,child);this.children.push(child.id);}
      for(const match of value.matchAll(/<select[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){const opts=[...match[2].matchAll(/<option value="([^"]*)"([^>]*)>/g)];nodes.get(match[1]).value=(opts.find(row=>row[2].includes('selected'))||opts[0])?.[1]||'';}
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
  for(const id of ['inspectionFailuresContent','navInspectionFailures','inspectionFailuresPage','spoolBomDialog'])nodes.set(id,new Element(id));
  const data=fixtures();
  const ctx={console,URL,URLSearchParams,AbortController,encodeURIComponent,decodeURIComponent,esc,me:{role,badge:role==='inspector'?'QA1':'OTHER'},current:null,
    document:{getElementById:id=>nodes.get(id)||null},location:{origin:'https://example.test'},history:{replaceState(_d,_t,url){ctx.url=url;}},
    show(page){ctx.page=page;return true;},stopCloudCamera(){},notify:message=>messages.push(message),
    setTimeout(fn){const id=++timer;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},
    FabFlow:{async open(options){opened.push({kind:'flow',options:clone(options)});}},
    FabSpoolBom:{async open(options,opener){nodes.get('spoolBomDialog').open=true;opened.push({kind:'material',options:clone(options),opener});}},
    FabInspections:{async open(options){opened.push({kind:'inspections',options:clone(options)});}},
    FabFlowStatus:{spoolNumber:row=>row.qr_alias||row.spool_number||row.item_id,spoolText:(row,label)=>esc(label||row.qr_alias||row.spool_number||row.item_id)},
    async api(url,options={}){
      calls.push({url,method:options.method||'GET',signal:options.signal});
      if((options.method||'GET')!=='GET')throw Error('The failure queue must not write production state.');
      if(readHook){const special=readHook(url,options);if(special!==undefined)return special;}
      if(url==='/api/flow/inspection-failures')return clone(data);
      throw Error('Unexpected endpoint '+url);
    },
  };
  ctx.window=ctx;vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/inspection-failures.js'),'utf8'),ctx,{filename:'inspection-failures.js'});
  const html=()=>nodes.get('inspectionFailuresContent').innerHTML;
  const click=async(action,id='',spoolId='')=>{
    const button={disabled:false,dataset:{failureAction:action,failureId:id,failureSpool:spoolId},closest(selector){return selector==='[data-failure-action]'?button:null;}};
    await nodes.get('inspectionFailuresContent').listeners.click({target:button,preventDefault(){}});return button;
  };
  const change=async(id,value)=>{const el=nodes.get(id);assert.ok(el,id+' is present');el.value=value;await el.onchange?.({target:el});await el.listeners.change?.({target:el});};
  const byAttribute=(attr,id,content=html())=>elementHtml(content,new RegExp('<[a-z][\\w:-]*\\b[^>]*\\b'+attr+'="'+id+'"[^>]*>'));
  return {ctx,data,nodes,calls,opened,messages,timers,html,click,change,setReadHook(fn){readHook=fn;},spool:id=>byAttribute('data-failed-spool',id),failure:(id,spoolId)=>byAttribute('data-inspection-failure',id,spoolId?byAttribute('data-failed-spool',spoolId):html())};
}

(async()=>{
  const checks=[];
  {
    const h=harness();await h.ctx.FabInspectionFailures.open();
    assert.equal(h.ctx.page,'inspectionFailuresPage');assert.match(h.html(),/Failed Inspections/);
    assert.equal(h.calls.length,1);assert.equal(h.calls[0].url,'/api/flow/inspection-failures');
    assert.match(h.html(),/Affected physical spools<\/span><strong>4<\/strong>/);assert.match(h.html(),/Open failed inspections<\/span><strong>6<\/strong>/,'One assembly finding counts once despite appearing under multiple physical spools');
    for(const id of ['SPOOL-A','SPOOL-B','SPOOL-LEGACY','SPOOL-FINAL'])assert.ok(h.spool(id),id+' is a distinct physical spool');
    assert.match(h.spool('SPOOL-A'),/643-777-PCW-03-01-\[001\]/);assert.match(h.spool('SPOOL-B'),/643-777-PCW-03-01-\[002\]/);
    assert.ok(h.failure('FLOW-ASM-NDT','SPOOL-A'));assert.ok(h.failure('FLOW-ASM-NDT','SPOOL-B'));
    assert.equal(h.failure('FLOW-SPOOL-FITUP','SPOOL-B'),'','A spool-local finding never spreads to its sibling');
    assert.match(h.failure('MATERIAL-1-PIECE-2','SPOOL-A'),/QA\/QC-001 - Material/);
    assert.match(h.failure('MATERIAL-1-PIECE-2','SPOOL-A'),/Wrong material &lt;grade&gt; &amp; damaged end/);
    assert.match(h.failure('MATERIAL-1-PIECE-2','SPOOL-A'),/BOM item 1 · piece 2/);
    assert.match(h.failure('MATERIAL-1-PIECE-2','SPOOL-A'),/Material Coordinator/);
    assert.match(h.failure('MATERIAL-1-PIECE-2','SPOOL-A'),/Receiving \/ Inventory/);
    assert.match(h.failure('FLOW-SPOOL-FITUP','SPOOL-A'),/Isometric Dimensions Test|Fit-Up Welder/);
    assert.doesNotMatch(h.html(),/<grade>|<root>|<W7>|<Tech>|<indication>/);
    const button=await h.click('open-record','MATERIAL-1-PIECE-2','SPOOL-A');
    assert.deepEqual(h.opened.at(-1).options,{api_url:'/api/spool-boms/spools/SPOOL-A',item_id:'SPOOL-A',spool_number:'643-777-PCW-03-01-[001]'});assert.equal(h.opened.at(-1).kind,'material');assert.equal(h.opened.at(-1).opener,button);
    await h.click('open-record','FLOW-SPOOL-FITUP','SPOOL-A');assert.deepEqual(h.opened.at(-1),{kind:'flow',options:{item:'SPOOL-A',project:'P1'}});
    checks.push('The failed list shows separate physical spools, explicit failure type and defect, exact material piece, receiving destination and responsible job position');
  }
  {
    const h=harness();await h.ctx.FabInspectionFailures.open();
    const ndt=h.failure('FLOW-ASM-NDT','SPOOL-A'),pressure=h.failure('FLOW-ASM-PRESSURE','SPOOL-A');
    assert.match(ndt,/QA\/QC-004 - NDT Results/);assert.match(pressure,/QA\/QC-005 - Verify Pressure Testing/);
    assert.match(ndt,/Assembly|assembly/);assert.match(ndt,/ASM-TESTS/);assert.match(pressure,/ASM-TESTS/);
    assert.match(ndt,/NDT Technician/);assert.match(ndt,/NDT1/);assert.match(pressure,/Pressure Testing Technician/);assert.match(pressure,/PRESS1/);
    assert.match(ndt,/data-failure-status="awaiting_reinspection"/);assert.match(ndt,/Ground out &lt;indication&gt; and completed repair/);assert.match(ndt,/REPAIR-NDT-1001/);assert.match(ndt,/Awaiting QA\/QC reinspection/);
    assert.match(pressure,/data-failure-status="return_required"/);
    await h.click('open-record','FLOW-ASM-NDT','SPOOL-B');assert.deepEqual(h.opened.at(-1),{kind:'flow',options:{item:'ASM-TESTS',project:'P1'}});
    await h.click('open-record','FLOW-ASM-PRESSURE','SPOOL-A');assert.deepEqual(h.opened.at(-1),{kind:'flow',options:{item:'ASM-TESTS',project:'P1'}});
    assert.ok(h.spool('SPOOL-B'),'Completed correction stays listed until QA accepts reinspection');
    checks.push('Assembly failures identify inherited scope and open the source assembly; NDT and pressure remain distinct, and completed corrections remain awaiting signed QA reinspection');
  }
  {
    const h=harness(),legacy=h.data.spools.find(row=>row.item_id==='SPOOL-LEGACY').failures[0];
    legacy.reason='';legacy.return_station={id:'testing',label:'Unverified pressure station'};legacy.return_positions=['Unverified Technician'];legacy.return_title='Unverified pressure rework';
    await h.ctx.FabInspectionFailures.open({inspection:'QA-005'});
    assert.ok(h.failure('FLOW-ASM-PRESSURE','SPOOL-A'));assert.equal(h.failure('FLOW-ASM-NDT','SPOOL-A'),'');assert.equal(h.spool('SPOOL-FINAL'),'');assert.equal(h.spool('SPOOL-LEGACY'),'');
    await h.change('failureInspection','QA-006');assert.ok(h.failure('FLOW-LEGACY-FINAL','SPOOL-FINAL'));assert.equal(h.failure('FLOW-ASM-PRESSURE','SPOOL-A'),'');
    await h.change('failureInspection','legacy_testing');
    const unknown=h.failure('FLOW-LEGACY-UNKNOWN','SPOOL-LEGACY');assert.ok(unknown);assert.match(unknown,/Test Results \(retained\)/);assert.match(unknown,/routing|Routing|destination.*review/i);
    assert.match(unknown,/Failure description not recorded/,'A real historic FAIL remains visible even if its reason was not recorded');
    assert.match(unknown,/Return station needs review|Responsible position needs review/);assert.doesNotMatch(unknown,/Unverified pressure station|Unverified Technician|Unverified pressure rework/,'Partial routing hints are not displayed as verified destination instructions');
    assert.doesNotMatch(unknown,/NDT Technician|Pressure Testing Technician|Fit-Up Welder|Receiving \/ Inventory/,'Missing destination and position never get a guessed fallback');
    await h.click('open-record','FLOW-LEGACY-UNKNOWN','SPOOL-LEGACY');assert.deepEqual(h.opened.at(-1),{kind:'flow',options:{item:'ASM-LEGACY',project:'P2'}});
    checks.push('Filters use the explicit inspection identity: retained final stays final, and ambiguous retained test failures show neutral routing instead of an invented station or position');
  }
  {
    const h=harness();await h.ctx.FabInspectionFailures.open({inspection:'QA-004',project:'P1',query:'[002]',status:'awaiting_reinspection'});
    assert.ok(h.spool('SPOOL-B'));assert.equal(h.spool('SPOOL-A'),'');
    const state=h.ctx.FabInspectionFailures.navigationState(),q=new URL(h.ctx.url,'https://example.test').searchParams;
    for(const [key,value] of Object.entries({inspection:'QA-004',project:'P1',query:'[002]',status:'awaiting_reinspection'}))assert.equal(state[key],value);
    for(const [key,value] of Object.entries({'inspection-failures':'1',inspection:'QA-004',project:'P1',q:'[002]',status:'awaiting_reinspection'}))assert.equal(q.get(key),value);
    await h.click('inspections');assert.deepEqual(h.opened.at(-1),{kind:'inspections',options:{inspection:'QA-004',project:'P1',query:'[002]',status:''}},'All inspections retains useful scope and clears an unrelated current-review filter');
    await h.change('failureInspection','');await h.change('failureProject','P2');await h.change('failureStatus','needs_routing_review');
    const search=h.nodes.get('failureSearch');search.value='[003]';search.selectionStart=1;search.selectionEnd=3;await search.oninput();
    assert.ok(h.spool('SPOOL-LEGACY'));assert.equal(h.spool('SPOOL-FINAL'),'');assert.equal(h.nodes.get('failureSearch').focused,true);assert.equal(h.nodes.get('failureSearch').selectionStart,1);
    assert.equal(h.calls.length,1,'Filters reuse the loaded failure projection');
    await h.ctx.FabInspectionFailures.open({inspection:'invalid',project:'',query:'',status:'invalid'});
    assert.equal(h.ctx.FabInspectionFailures.navigationState().inspection,'');assert.equal(h.ctx.FabInspectionFailures.navigationState().status,'');
    const count=h.opened.length;await h.click('open-record','FLOW-SPOOL-FITUP','SPOOL-B');await h.click('open-record','MISSING','SPOOL-A');assert.equal(h.opened.length,count,'A failure must belong to the selected physical spool before navigation');
    checks.push('Inspection, project, text and correction-state filters keep shareable navigation state, preserve search focus and enforce the physical-spool/failure tuple for opening records');
  }
  {
    const h=harness();await h.ctx.FabInspectionFailures.open();assert.ok(h.spool('SPOOL-A'));
    h.data.spools=[];h.data.totals={spools:0,failures:0,needs_rework:0,awaiting_reinspection:0,return_required:0};
    await h.click('refresh');assert.equal(h.spool('SPOOL-A'),'');assert.equal(h.spool('SPOOL-B'),'');assert.match(h.html(),/No .*fail|No .*match|No open/i);
    checks.push('Refreshing after the backend resolves failures removes their physical-spool entries instead of retaining old defects');
  }
  {
    const h=harness();await h.ctx.FabInspectionFailures.open();
    const close=()=>{const dialog=h.nodes.get('spoolBomDialog');dialog.open=false;return dialog.listeners.close?.({type:'close'});};
    await close();assert.equal(h.calls.length,1,'An unrelated material-dialog close does not reload the queue');
    await h.click('open-record','MATERIAL-1-PIECE-2','SPOOL-A');
    const material=h.data.spools[0].failures.find(row=>row.id==='MATERIAL-1-PIECE-2');
    material.status='awaiting_reinspection';material.correction={event_id:1002,description:'Replaced incorrect piece and restored identification',actor:'HANDLER1',at:'2026-11-04T16:20:00Z',reference:'MATERIAL-REPAIR-1002'};
    await close();assert.equal(h.calls.length,2);assert.match(h.failure('MATERIAL-1-PIECE-2','SPOOL-A'),/MATERIAL-REPAIR-1002|Replaced incorrect piece/);assert.match(h.failure('MATERIAL-1-PIECE-2','SPOOL-A'),/data-failure-status="awaiting_reinspection"/);
    await close();assert.equal(h.calls.length,2,'The originating material-open flag clears after its close');
    await h.click('open-record','MATERIAL-1-PIECE-2','SPOOL-A');h.data.spools[0].failures=h.data.spools[0].failures.filter(row=>row.id!=='MATERIAL-1-PIECE-2');
    await close();assert.equal(h.calls.length,3);assert.equal(h.failure('MATERIAL-1-PIECE-2','SPOOL-A'),'');assert.ok(h.failure('FLOW-SPOOL-FITUP','SPOOL-A'),'Unresolved findings on the same spool remain');
    const left=harness();await left.ctx.FabInspectionFailures.open();await left.click('open-record','MATERIAL-1-PIECE-2','SPOOL-A');left.ctx.FabInspectionFailures.cancelPending();
    const before=left.html();await left.nodes.get('spoolBomDialog').listeners.close?.({type:'close'});assert.equal(left.calls.length,1);assert.equal(left.html(),before);
    checks.push('Closing a material inspection refreshes correction and acceptance changes on its originating failed list; unrelated or late closes after navigation do not reopen it');
  }
  {
    for(const role of ['inspector','admin','handler','welder','painter']){
      const h=harness(role);await h.ctx.FabInspectionFailures.open();
      assert.ok(h.spool('SPOOL-A'));assert.match(h.failure('FLOW-SPOOL-FITUP','SPOOL-A'),/Fit-Up Welder/);
      assert.doesNotMatch(h.html(),/<form|name="(?:result|check_)|data-failure-action="(?:pass|fail|approve|advance|return)"/,'The queue cannot independently approve or move production records');
      await h.click('open-record','FLOW-ASM-PRESSURE','SPOOL-A');assert.equal(h.opened.at(-1).options.item,'ASM-TESTS');assert.ok(h.calls.every(row=>row.method==='GET'));
    }
    checks.push('Responsible workers and QA can read the same real failures; every action opens an existing gated record and the queue makes no production writes');
  }
  {
    const h=harness();h.setReadHook(()=>Promise.reject(Error('Synthetic failed-record read <error>')));await h.ctx.FabInspectionFailures.open();
    assert.match(h.html(),/role="alert"/);assert.match(h.html(),/read &lt;error&gt;/);assert.doesNotMatch(h.html(),/<error>/);assert.equal(h.spool('SPOOL-A'),'');
    h.setReadHook(null);await h.click('refresh');assert.ok(h.spool('SPOOL-A'));
    const broken=harness();broken.setReadHook(()=>({spools:'invalid'}));await broken.ctx.FabInspectionFailures.open();assert.match(broken.html(),/role="alert"/);assert.equal(broken.spool('SPOOL-A'),'');
    checks.push('Failed or malformed reads display a retriable error rather than an empty or stale success state, and server text is escaped');
  }
  {
    const h=harness(),held=deferred();let hold=true;h.setReadHook(()=>hold?held.promise:undefined);
    const old=h.ctx.FabInspectionFailures.open({inspection:'QA-001',project:'P1'});await Promise.resolve();hold=false;
    await h.ctx.FabInspectionFailures.open({inspection:'QA-006',project:'P2'});const html=h.html(),url=h.ctx.url;
    held.resolve(fixtures());await old;assert.equal(h.html(),html);assert.equal(h.ctx.url,url);assert.ok(h.spool('SPOOL-FINAL'));
    const canceled=harness(),late=deferred();canceled.setReadHook(()=>late.promise);const pending=canceled.ctx.FabInspectionFailures.open();await Promise.resolve();canceled.ctx.FabInspectionFailures.cancelPending();
    const before=canceled.html(),route=canceled.ctx.url;late.resolve(fixtures());await pending;assert.equal(canceled.html(),before);assert.equal(canceled.ctx.url,route);assert.ok(canceled.calls.every(row=>!row.signal||row.signal.aborted));assert.equal(canceled.timers.size,0);
    checks.push('Late responses cannot replace a newer failure selection or restore an abandoned failed-inspection page');
  }
  console.log(JSON.stringify({status:'passed',contracts:checks.length,checks},null,2));
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
