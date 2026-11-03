/* Read-only production-progress UI contracts, including stale navigation.
 * All data is synthetic; this test performs no network requests. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const elements=new Map(),checks=[],calls=[],messages=[];
const decode=s=>String(s).replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
class Element{
  constructor(id){this.id=id;this.listeners={};this.attributes={};this.children=[];this.details=[];this.value='';this.disabled=false;this.isConnected=true;this.dataset={};}
  set innerHTML(html){
    this.details.forEach(d=>d.isConnected=false);for(const id of this.children)elements.delete(id);this.children=[];this.details=[];this.html=html;
    for(const m of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const e=new Element(m[1]);e.value=decode(m[0].match(/\bvalue="([^"]*)"/)?.[1]||'');elements.set(e.id,e);this.children.push(e.id);}
    for(const m of html.matchAll(/<select[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){const opts=[...m[2].matchAll(/<option value="([^"]*)"([^>]*)>/g)];elements.get(m[1]).value=decode((opts.find(v=>v[2].includes('selected'))||opts[0])?.[1]||'');}
    for(const m of html.matchAll(/<details\b[^>]*data-pp-expand="([^"]+)"[^>]*>/g)){const d=new Element('');d.dataset.ppExpand=decode(m[1]);d.open=/\sopen(?:\s|>)/.test(m[0]);this.details.push(d);}
  }
  get innerHTML(){return this.html||'';}
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this.attributes[name]=value;}
  querySelectorAll(){return this.details;}
  focus(){this.focused=true;}
  setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;}
}
for(const id of ['productionProgressContent','navProgress'])elements.set(id,new Element(id));
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const catalog=[
  ['inventory','Inventory',[1],'black'],['qa_001','QA/QC-001',[2,3,4],'black'],
  ['preparation','Prep/Fabrication',[5,6,7,9,10],'red'],['qa_002','QA/QC-002',[11],'red'],
  ['floor','Floor',[8,12,16,19],'yellow'],['welding','Process Welder',[13,14],'blue'],
  ['qa_003','QA/QC-003',[15],'blue'],['testing','Testing',[17],'orange'],
  ['qa_test_results','QA/QC-004',[18],'orange'],
  ['paint','Paint',[20,21],'pink'],['qa_004','QA/QC-005',[22],'pink'],
  ['ready_to_ship','Ready To Ship',[23,24],'green'],
].map(([key,label,steps,color])=>({key,label,steps,color,qa:key.startsWith('qa_'),separate:key==='ready_to_ship'}));
const sum=(items,completed,total,values={})=>({items,parts:0,spools:0,assemblies:0,finished:0,wip:items,on_hold:0,planning_needed:0,completed_steps:completed,total_steps:total,not_recorded_steps:0,missing_spools:0,missing_parts:0,undeclared_scope:0,scope_complete:true,complete:false,recorded_percent:total?completed/total*100:0,percent:total?completed/total*100:null,...values});
const stages=(numbers,states={},unknown=false)=>catalog.map(s=>{const own=s.steps.filter(x=>numbers.includes(x)),completed=own.filter(n=>states[n]==='completed').length,not_recorded=own.filter(n=>states[n]==='not_recorded').length,current=own.filter(n=>states[n]==='current').length;return {...s,total:own.length,completed,not_recorded,current,percent:own.length?completed/own.length*100:null,state:own.length?(current?'current':completed===own.length?'completed':not_recorded?'not_recorded':'pending'):(unknown?'scope_unknown':'not_applicable')};});
function item(id,route,states={},props={}){
  const range=route==='component'?[1,8]:route==='spool'?[9,16]:[17,24],numbers=Array.from({length:range[1]-range[0]+1},(_,i)=>range[0]+i),flow=numbers.filter(n=>n<=22),completed=flow.filter(n=>states[n]==='completed').length,not_recorded=flow.filter(n=>states[n]==='not_recorded').length;
  const stage=catalog.find(s=>s.steps.some(n=>states[n]==='current'));
  return {id,flow_stage:stage?{...stage,source_item_id:id,inherited:false}:null,item_kind:route==='component'?'Part':route==='spool'?'Spool':'Assembly',route,route_started:true,project_id:'P1',parent_id:'',part_number:'000-PN-'+id,current_step:numbers.find(n=>states[n]==='current')||null,current_title:'Synthetic current process',location:'Bay <1>',handler:'TEST-HANDLER',handler_name:'Training handler',status:'wip',fabrication_finished:false,on_hold:false,hold_reasons:[],blockers:[],warnings:[],progress:{completed,total:flow.length,not_recorded,percent:completed/flow.length*100},summary:sum(1,completed,flow.length,{not_recorded_steps:not_recorded}),stages:stages(numbers,states),steps:numbers.map(n=>({number:n,title:'Process step '+n,state:states[n]||'pending',stage:catalog.find(s=>s.steps.includes(n)).key,qa:[2,11,15,18,22].includes(n)})),parts:null,required_spools:null,linked_spools:0,missing_spools:0,children:[],...props};
}
const done=(start,end)=>Object.fromEntries(Array.from({length:end-start+1},(_,i)=>[start+i,'completed']));
const component=item('PART-A','component',{1:'not_recorded',2:'not_recorded',3:'not_recorded',4:'completed',5:'current'},{parent_id:'LEGACY-SPOOL',warnings:['Material traceability <unverified>']});
const prepared=item('PART-READY','component',done(1,8),{parent_id:'LEGACY-SPOOL',fabrication_finished:true,status:'finished',flow_stage:{key:'floor',source_item_id:'PART-READY',inherited:false}});
const spool=item('LEGACY-SPOOL','spool',{9:'completed',10:'completed',11:'completed',12:'completed',13:'current'},{item_kind:'Part',spool_number:'643-777-PCW-03-01',part_number:'643-777-PCW-03-01',qr_alias:'643-777-PCW-03-01-[001]',display_code:'643-777-PCW-03-01-[001]',parent_id:'ASM-A',children:[component,prepared],on_hold:true,hold_reasons:['Repair inspection remains open'],blockers:['Future QA <check>'],warnings:['1 required physical part still to assign'],parts:{configured:false,legacy_scope:true,reference:'LEGACY-REF',required_qty:3,assigned_qty:2,received_qty:2,prepared_qty:1,short_qty:1},summary:sum(3,13,24,{parts:2,spools:1,finished:1,on_hold:1,not_recorded_steps:3,missing_parts:1,scope_complete:false})});
const assembly=item('ASM-A','assembly',{}, {route_started:false,children:[spool],required_spools:2,linked_spools:1,missing_spools:1,summary:sum(4,13,30,{parts:2,spools:1,assemblies:1,finished:1,on_hold:1,missing_spools:1,missing_parts:1,scope_complete:false,not_recorded_steps:3})});
const branchStages=stages(Array.from({length:24},(_,i)=>i+1),{1:'completed',2:'current'});branchStages[2].missing_records=1;
const order1={project_id:'P1',purchase_order:'00045 <PO>',customer:'Customer & partners',version:1,summary:assembly.summary,stages:branchStages,gpns:[{id:'G1',gpn:'000-GPN-A',setup_needed:false,summary:assembly.summary,stages:branchStages,warnings:['Required scope is incomplete'],assemblies:[assembly]}],unassigned:[],warnings:[]};
const finishedAssembly=item('ASM-B','assembly',done(17,22),{project_id:'P2',fabrication_finished:true,status:'finished',required_spools:2,linked_spools:0,missing_spools:2});
const incomplete100=sum(1,6,6,{assemblies:1,finished:1,wip:0,missing_spools:2,scope_complete:false,complete:false});finishedAssembly.summary=incomplete100;
const order2={project_id:'P2',purchase_order:'00046',customer:'Second customer',version:1,summary:incomplete100,stages:stages([17,18,19,20,21,22],done(17,22),true),gpns:[{id:'G2',gpn:'000-GPN-B',setup_needed:false,summary:incomplete100,stages:stages([17,18,19,20,21,22],done(17,22),true),warnings:[],assemblies:[finishedAssembly]}],unassigned:[],warnings:[]};
const draft=sum(0,0,0,{scope_complete:false,undeclared_scope:1});
const order3={project_id:'P3',purchase_order:'00047',customer:'Draft customer',version:1,summary:draft,stages:stages([],{},true),gpns:[{id:'G3',gpn:'DRAFT-GPN',setup_needed:true,summary:draft,stages:stages([],{},true),warnings:['Assembly setup is required'],assemblies:[]}],unassigned:[],warnings:[]};
const orders=[order1,order2,order3],choices=orders.map(o=>({project_id:o.project_id,purchase_order:o.purchase_order,customer:o.customer}));
const response=(project='')=>({as_of:'2026-10-30T12:00:00Z',selected_project_id:project,choices,stage_catalog:catalog,stages:branchStages,summary:project?orders.find(o=>o.project_id===project).summary:sum(5,19,36,{parts:2,spools:1,assemblies:2,on_hold:1,missing_spools:3,missing_parts:1,scope_complete:false}),orders:project?orders.filter(o=>o.project_id===project):orders});
let hook=null;
const context={document:{getElementById:id=>elements.get(id)||null},me:{role:'handler'},current:null,URLSearchParams,Date,Set,esc,history:{replaceState(_a,_b,url){context.url=url;}},show(page){context.FabProductionProgress?.cancelPending();context.page=page;},stopCloudCamera(){},notify:x=>messages.push(x),openItem:id=>{context.openedItem=id;},FabFlow:{open:v=>{context.openedFlow=v;}},FabParts:{open:v=>{context.openedParts=v;}},FabTracking:{open:v=>{context.openedWeld=v;}},FabDossier:{open:v=>{context.openedDossier=v;}},FabOrders:{open:v=>{context.openedOrder=v||{};}},FabProgress:{open:v=>{context.openedLegacy=v;}},api:async(url,options={})=>{calls.push({url,...options});const project=new URL('https://example.test'+url).searchParams.get('project_id')||'';return hook?hook(project):response(project);}};
context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/flow-status.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/production-progress.js'),'utf8'),context);
const root=()=>elements.get('productionProgressContent'),html=()=>root().innerHTML;
const click=(action,id='',project='')=>root().listeners.click({target:{closest:()=>({disabled:false,dataset:{ppAction:action,ppId:id,ppProject:project}})}});
const select=async(id,value)=>{elements.get(id).value=value;await elements.get(id).onchange();};
const search=value=>{elements.get('ppSearch').value=value;elements.get('ppSearch').selectionStart=value.length;elements.get('ppSearch').oninput();};
const toggle=key=>{const d=root().details.find(d=>d.dataset.ppExpand===key);assert.ok(d,'Visible dropdown '+key);d.open=!d.open;d.ontoggle();};
const check=name=>checks.push(name);
(async()=>{
  context.me=null;await context.FabProductionProgress.open();assert.equal(calls.length,0);context.me={role:'handler'};check('Signed-out access makes no progress request');
  await context.FabProductionProgress.open();assert.equal(context.page,'productionProgressPage');assert.equal(elements.get('ppPo').value,'');assert.match(html(),/P.O 00045 &lt;PO&gt;/);assert.match(html(),/Customer &amp; partners/);assert.match(html(),/All P.O.s/);assert.equal(root().details.length,3);assert.doesNotMatch(html(),/data-pp-item=/);check('All P.O. overview is escaped, collapsed and lazy');
  const groupedOrder=[...html().matchAll(/data-spool-process="([^"]+)"/g)].map(m=>m[1]);assert.deepEqual(groupedOrder,catalog.map(stage=>stage.key));assert.equal([...html().matchAll(/data-process-spool="LEGACY-SPOOL"/g)].length,1);assert.match(html().split('data-spool-process="welding"')[1].split('data-spool-process="qa_003"')[0],/643-777-PCW-03-01-\[001\]/);assert.match(html(),/data-pp-spool="LEGACY-SPOOL"/);assert.doesNotMatch(html(),/data-process-spool="(?:ASM-A|PART-A|PART-READY)"/);await root().listeners.click({target:{closest:()=>({disabled:false,dataset:{ppSpool:'LEGACY-SPOOL',spoolProject:'P1'}})}});assert.equal(context.openedFlow.item,'LEGACY-SPOOL');assert.equal(context.openedFlow.project,'P1');check('Individual physical copies appear once under their current process before hierarchy expansion and open exact internal IDs');
  toggle('order:P1');toggle('gpn:G1');assert.match(html(),/Assembly flow/);assert.match(html(),/1 required item still to register/);assert.match(html(),/data-pp-item="ASM-A"/);assert.match(html(),/data-pp-item="LEGACY-SPOOL"/);assert.doesNotMatch(html(),/data-pp-item="PART-A"/);check('P.O. and GPN dropdowns expose independent physical route bars');
  toggle('item:LEGACY-SPOOL');assert.match(html(),/data-pp-item="PART-A"/);assert.match(html(),/Referenced material scope/);assert.match(html(),/2 \/ 3 assigned/);assert.match(html(),/Repair inspection remains open/);assert.match(html(),/Future QA &lt;check&gt;/);assert.match(html(),/Scope needs attention/);check('Legacy spools retain their route, component quantities and distinct hold/readiness evidence');
  const stageOrder=[...html().matchAll(/data-pp-stage="([^"]+)"/g)].slice(0,catalog.length).map(m=>m[1]);assert.deepEqual(stageOrder,catalog.map(s=>s.key));assert.match(html(),/data-spool-number="643-777-PCW-03-01" data-spool-id="LEGACY-SPOOL" class="fst-text fst-color-blue"[^>]*>643-777-PCW-03-01-\[001\]<\/strong>/);assert.match(html(),/<strong>PART-A<\/strong>/);assert.match(html(),/<strong>PART-READY<\/strong>/);assert.doesNotMatch(html(),/fst-color-[^"]+"[^>]*>(?:PART-A|PART-READY|ASM-A)<\/(?:strong|span)>/);assert.match(html(),/Spool number colors/);assert.match(html(),/QA\/QC-004/);check('Twelve flow stages stay ordered, with separate QA checkpoints and colored readable spool numbers and plain component identities');
  for(const stageGrid of html().matchAll(/<ol class="pp-stage-grid">([\s\S]*?)<\/ol>/g))assert.doesNotMatch(stageGrid[1],/fst-color-|fst-text/);for(const station of html().matchAll(/<(?:h3|span|strong)\b[^>]*data-station-stage="[^"]+"[^>]*>/g))assert.doesNotMatch(station[0],/fst-color-|fst-text/);check('Process headings, route-stage labels and badges remain neutral while physical spool numbers carry the color');
  toggle('item:PART-A');assert.match(html(),/Material traceability &lt;unverified&gt;/);assert.match(html(),/3 earlier steps not recorded/);assert.match(html(),/Outside this route/);toggle('steps:PART-A');assert.match(html(),/Earlier step not recorded/);check('Individual part history shows baseline gaps without inventing downstream steps');
  await click('collapse');assert.equal(root().details.filter(d=>d.open).length,0);await click('expand');assert.ok(root().details.find(d=>d.dataset.ppExpand==='steps:PART-A')?.open);assert.match(html(),/QA\/QC/);check('Expand all reaches nested lazy rows and numbered steps; collapse all closes them');
  search('643-777-PCW-03-01-[001]');assert.match(html(),/data-pp-item="LEGACY-SPOOL"/);assert.doesNotMatch(html(),/data-pp-order="P2"/);await click('clear');check('Readable spool numbers and copy aliases are searchable without changing internal record IDs');
  const originalPercent=(assembly.summary.percent).toFixed(1)+'%';search('PART-A');assert.match(html(),/Parent context/);assert.match(html(),/data-pp-order="P1"/);assert.match(html(),/data-pp-gpn="G1"/);assert.match(html(),/data-pp-item="LEGACY-SPOOL"/);assert.doesNotMatch(html(),/data-pp-item="PART-READY"/);assert.match(html(),new RegExp(originalPercent.replace('.','\\.')));assert.match(html(),/totals still describe the full selected scope/);assert.equal(elements.get('ppPo').value,'');check('Search opens matching ancestry and keeps full-scope progress');
  await click('clear');await select('ppKind','spool');assert.match(html(),/data-pp-item="LEGACY-SPOOL"/);assert.doesNotMatch(html(),/data-pp-item="PART-READY"/);check('Spools filter uses authoritative route even for historical Part-kind spools');
  await click('clear');await select('ppStatus','finished');assert.match(html(),/data-pp-item="PART-READY"/);assert.match(html(),/>Prepared</);assert.doesNotMatch(html(),/data-pp-item="PART-A"/);check('Finished filter includes prepared components with accurate milestone labels');
  await click('clear');await select('ppStatus','hold');assert.match(html(),/data-pp-item="LEGACY-SPOOL"/);assert.doesNotMatch(html(),/data-pp-item="PART-READY"/);check('On hold filter uses actual process holds');
  await click('clear');search('not-an-item');assert.match(html(),/No items match this view/);assert.equal(elements.get('ppPo').value,'');assert.match(html(),/value="P2"/);check('Empty filtered views retain the All P.O. selector and choices');
  await click('clear');await select('ppPo','P2');assert.equal(calls.at(-1).url,'/api/progress/orders?project_id=P2');assert.equal(elements.get('ppPo').value,'P2');assert.match(html(),/value="P1"/);assert.match(context.url,/production-progress=1&project=P2/);assert.match(html(),/100%/);assert.match(html(),/Scope incomplete/);assert.doesNotMatch(html(),/pp-meter-complete/);assert.match(html(),/Scope not declared/);check('Single-P.O. scope preserves all choices and never marks incomplete 100% as finished');
  await select('ppPo','P3');toggle('gpn:G3');assert.match(html(),/Setup needed/);assert.match(html(),/Progress is not yet known/);assert.doesNotMatch(html(),/pp-meter-complete/);check('Draft scope has unknown meters and explicit setup guidance');
  const planned=JSON.parse(JSON.stringify(response('P3')));Object.assign(planned.orders[0].gpns[0],{setup_needed:false,registration_needed:true,registered_assemblies:0,quantity_plan:{assembly_quantity:3,spools_per_assembly:3,total_spools:9}});planned.orders[0].summary.missing_assemblies=3;hook=()=>planned;await context.FabProductionProgress.open({project:'P3'});assert.match(html(),/data-pp-order="P3"/);toggle('gpn:G3');assert.match(html(),/Saved P.O. quantities/);assert.match(html(),/3 assemblies/);assert.match(html(),/9 total spools/);assert.match(html(),/Register physical assemblies/);await select('ppStatus','wip');assert.match(html(),/data-pp-gpn="G3"/);await select('ppStatus','finished');assert.match(html(),/No items match this view/);hook=null;await context.FabProductionProgress.open({project:'P3'});check('Saved quantity plans stay visible before physical registration and remain WIP');
  await click('flow','LEGACY-SPOOL','P1');assert.equal(context.openedFlow.item,'LEGACY-SPOOL');assert.equal(context.openedFlow.project,'P1');await click('item','PART-A','P1');assert.equal(context.openedItem,'PART-A');await click('welds','LEGACY-SPOOL','P1');assert.equal(context.openedWeld.spool,'LEGACY-SPOOL');await click('parts','LEGACY-SPOOL','P1');assert.equal(context.openedParts.project,'P1');await click('order','G1','P1');assert.equal(context.openedOrder.gpn,'G1');await click('dossier','','P1');assert.equal(context.openedDossier.project,'P1');await click('project-detail','','P1');assert.equal(context.openedLegacy.project,'P1');check('QR, flow, weld, BOM, order and dossier links preserve their exact physical context');
  await context.FabProductionProgress.open();await click('legacy-progress');assert.equal(context.openedLegacy.project,'');check('Legacy project records remain reachable from all-P.O. progress');
  hook=()=>{throw Error('Service <unavailable>');};await context.FabProductionProgress.refresh();assert.match(html(),/Service &lt;unavailable&gt;/);assert.match(html(),/Try again/);hook=null;await click('refresh');assert.match(html(),/data-pp-order="P1"/);check('Failed snapshots display escaped errors and recover on refresh');
  hook=()=>({...response(''),selected_project_id:'WRONG'});await context.FabProductionProgress.refresh();assert.match(html(),/could not be verified/);assert.doesNotMatch(html(),/data-pp-order=/);check('Mismatched snapshot scope fails closed');
  const dupe=JSON.parse(JSON.stringify(response('')));dupe.orders[0].unassigned.push(dupe.orders[0].gpns[0].assemblies[0].children[0]);hook=()=>dupe;await context.FabProductionProgress.refresh();assert.match(html(),/could not be verified/);hook=null;await click('refresh');check('Duplicate physical identities cannot create a falsely double-counted UI');
  let releaseFirst;hook=project=>project==='P1'?new Promise(resolve=>releaseFirst=()=>resolve(response('P1'))):response(project);const first=select('ppPo','P1');await select('ppPo','P2');releaseFirst();await first;assert.equal(elements.get('ppPo').value,'P2');assert.doesNotMatch(html(),/data-pp-order="P1"/);hook=null;check('Late earlier P.O. responses cannot replace a newer selection');
  let release;hook=project=>new Promise(resolve=>release=()=>resolve(response(project)));const pending=context.FabProductionProgress.refresh();context.FabProductionProgress.cancelPending();root().innerHTML='Another page owns navigation';release();await pending;assert.equal(html(),'Another page owns navigation');hook=null;check('Leaving the view cancels pending refresh rendering');
  const stationView=JSON.parse(JSON.stringify(response('P1'))),stationSpool=stationView.orders[0].gpns[0].assemblies[0].children[0];stationSpool.on_hold=false;stationSpool.hold_reasons=[];stationSpool.flow_stage={key:'inventory',needs_station_selection:true,recorded_location_label:'Legacy <Rack> & Bay'};hook=()=>stationView;await context.FabProductionProgress.open({project:'P1'});
  const inventoryGroup=html().split('data-spool-process="inventory"')[1].split('data-spool-process="qa_001"')[0];assert.equal(stationSpool.current_step,13);assert.match(inventoryGroup,/data-spool-id="LEGACY-SPOOL"[^>]*fst-color-black/);assert.match(inventoryGroup,/Recorded location: Legacy &lt;Rack&gt; &amp; Bay\. Select a flow station on the next transfer\./);assert.doesNotMatch(html().split('data-spool-process="welding"')[1].split('data-spool-process="qa_003"')[0],/data-process-spool="LEGACY-SPOOL"/);toggle('gpn:G1');assert.match(html(),/>Inventory · Confirm station<\/span>/);
  stationSpool.flow_stage={key:'ready_to_ship',blocked:true};await context.FabProductionProgress.refresh();const readyGroup=html().split('data-spool-process="ready_to_ship"')[1].split('<aside class="fst-legend"')[0];assert.match(readyGroup,/data-spool-id="LEGACY-SPOOL"[^>]*fst-color-green/);assert.match(readyGroup,/Release blocked/);assert.doesNotMatch(readyGroup,/Work blocked/);
  stationSpool.flow_stage={key:'unrecognized_station'};await context.FabProductionProgress.refresh();const unknownGroup=html().split('data-spool-process="unknown"')[1].split('<aside class="fst-legend"')[0];assert.match(unknownGroup,/Status unavailable/);assert.match(unknownGroup,/data-process-spool="LEGACY-SPOOL"/);assert.doesNotMatch(unknownGroup,/fst-color-|fst-text/);hook=null;await context.FabProductionProgress.open();check('Authoritative recorded stations override traveler-step guesses; unknown locations are explained and blocked Ready To Ship stays green without implying release');
  const clockView=JSON.parse(JSON.stringify(response('P1'))),clockSpool=clockView.orders[0].gpns[0].assemblies[0].children[0],realDate=context.Date;
  // A fixed browser clock deliberately differs from the saved server snapshot.
  context.Date=class extends Date{static now(){return Date.parse('2030-01-01T00:00:00Z');}};
  clockView.as_of='2026-10-30T12:34:56Z';clockSpool.step_entered_at='2026-10-30T11:30:00Z';
  clockSpool.flow_stage={key:'floor',source_item_id:'ASM-A',inherited:true,station_entered_at:'2026-10-29T08:00:00Z',station_visits:[
    {stage_key:'floor',label:'Floor',visit:1,entered_at:'2026-10-27T00:00:00Z',departed_at:'2026-10-27T02:00:00Z',source_item_id:'LEGACY-SPOOL',inherited:false},
    {stage_key:'welding',label:'Process Welder',visit:1,entered_at:'2026-10-27T02:00:00Z',departed_at:'2026-10-29T08:00:00Z',source_item_id:'LEGACY-SPOOL',inherited:false},
    {stage_key:'floor',label:'Floor',visit:2,entered_at:'2026-10-29T08:00:00Z',departed_at:'2026-10-29T09:00:00Z',source_item_id:'LEGACY-SPOOL',inherited:false},
    {stage_key:'floor',label:'Floor',visit:2,entered_at:'2026-10-29T09:00:00Z',departed_at:null,source_item_id:'ASM-A',inherited:true},
  ]};
  hook=()=>clockView;await context.FabProductionProgress.open({project:'P1'});
  const timedCard=()=>html().split('data-process-spool="LEGACY-SPOOL"')[1].split('</li>')[0];
  assert.match(timedCard(),/Time at station<\/span><strong[^>]*>28:34:56<\/strong>/);
  assert.match(timedCard(),/Shared assembly time/);
  toggle('gpn:G1');toggle('item:LEGACY-SPOOL');
  const timedDetail=()=>html().split('data-pp-item="LEGACY-SPOOL"')[1].split('<section class="pp-children">')[0];
  assert.match(timedDetail(),/Current process<\/span><strong>13 · Synthetic current process<\/strong>/);
  assert.match(timedDetail(),/Time in current numbered step<\/span><strong[^>]*>01:04:56<\/strong>/);
  assert.match(timedDetail(),/Time in step<\/span><strong[^>]*>01:04:56<\/strong>/);
  const timedStage=key=>timedDetail().split('data-pp-stage="'+key+'"')[1].split('</li>')[0];
  assert.match(timedStage('floor'),/Total time · 2 visits<\/span><strong[^>]*>30:34:56<\/strong>/);
  assert.match(timedStage('welding'),/Total time · 1 visit<\/span><strong[^>]*>54:00:00<\/strong>/);
  assert.match(timedStage('preparation'),/No recorded visit/);
  assert.match(timedDetail(),/Station visit history \(4 records\)/);
  assert.equal([...timedDetail().matchAll(/<td>Floor<\/td><td>2<\/td>/g)].length,2);
  assert.match(timedDetail(),/<td>This item<\/td>/);assert.match(timedDetail(),/<td>Shared · ASM-A<\/td>/);
  clockSpool.flow_stage={key:'floor',station_entered_at:null,station_visits:[],station_timing_status:'unrecorded'};
  await context.FabProductionProgress.refresh();
  assert.match(timedCard(),/Time at station<\/span><strong>Entry not recorded<\/strong>/);
  assert.doesNotMatch(timedCard(),/00:00:00|28:34:56/);
  assert.match(timedDetail(),/No station entry has been recorded for this item\./);
  assert.match(timedDetail(),/Time in current numbered step<\/span><strong[^>]*>01:04:56<\/strong>/);
  context.Date=realDate;hook=null;await context.FabProductionProgress.open();
  check('Saved station timing exceeds 24 hours, stays separate from numbered steps, counts physical returns across shared segments, and explains unrecorded entries');
  const identityView=JSON.parse(JSON.stringify(response('P1'))),sharedGpn='000-SHARED-GPN';
  identityView.orders[0].gpns=['000-ASM <A>','000-ASM-B',''].map((number,index)=>{
    const parentId='SAME-GPN-ASM-'+index,spoolId='SAME-GPN-SPOOL-'+index;
    const copy=item(spoolId,'spool',{13:'current'},{parent_id:parentId,spool_number:'SHARED-SPOOL',qr_alias:'SHARED-SPOOL-[00'+(index+1)+']'});
    const physical=item(parentId,'assembly',{}, {children:[copy],required_spools:1,linked_spools:1,summary:sum(2,0,14,{spools:1,assemblies:1})});
    return {...order1.gpns[0],id:'SAME-GPN-GROUP-'+index,gpn:sharedGpn,assembly_number:number,summary:physical.summary,assemblies:[physical]};
  });
  hook=()=>identityView;await context.FabProductionProgress.open({project:'P1'});
  assert.match(html(),/Assembly Number<\/span><strong>000-ASM &lt;A&gt;<\/strong><small>GPN: 000-SHARED-GPN/);
  assert.match(html(),/Assembly Number<\/span><strong>000-ASM-B<\/strong><small>GPN: 000-SHARED-GPN/);
  assert.match(html(),/Assembly Number<\/span><strong>Not entered<\/strong><small>GPN: 000-SHARED-GPN/);
  const cardFor=id=>html().split('data-process-spool="'+id+'"')[1].split('</li>')[0];
  assert.match(cardFor('SAME-GPN-SPOOL-0'),/Assembly Number: 000-ASM &lt;A&gt; · GPN: 000-SHARED-GPN/);
  assert.match(cardFor('SAME-GPN-SPOOL-2'),/Assembly Number: Not entered · GPN: 000-SHARED-GPN/);
  assert.doesNotMatch(cardFor('SAME-GPN-SPOOL-2'),/SAME-GPN-ASM-2/);
  search('000-ASM <A>');assert.match(html(),/data-pp-gpn="SAME-GPN-GROUP-0"/);assert.doesNotMatch(html(),/data-pp-gpn="SAME-GPN-GROUP-[12]"/);
  await click('order','SAME-GPN-GROUP-0','P1');assert.equal(context.openedOrder.gpn,'SAME-GPN-GROUP-0');
  search('000-ASM-B');assert.match(html(),/data-pp-gpn="SAME-GPN-GROUP-1"/);assert.doesNotMatch(html(),/data-pp-gpn="SAME-GPN-GROUP-[02]"/);
  await click('order','SAME-GPN-GROUP-1','P1');assert.equal(context.openedOrder.gpn,'SAME-GPN-GROUP-1');
  search(sharedGpn);for(let index=0;index<3;index++)assert.ok(html().includes('data-pp-gpn="SAME-GPN-GROUP-'+index+'"'));
  hook=null;await context.FabProductionProgress.open();check('Repeated GPNs show and search distinct actual assembly numbers, keep unknown values explicit, and route exact group IDs');
  const legacyBoard=context.FabFlowStatus.processBoard([{item_id:'LEGACY-CALLER',assembly_number:'KNOWN-LEGACY-LABEL',flow_stage:{key:'inventory'}}]);
  assert.match(legacyBoard,/KNOWN-LEGACY-LABEL/);assert.doesNotMatch(legacyBoard,/GPN:|Not entered/);check('Shared board retains older caller context when separate business identity fields are absent');
  assert.equal(calls.filter(c=>c.method).length,0);assert.equal(messages.length,0);check('Every progress request is read-only');
  const index=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');for(const phrase of ['id="productionProgressPage"','id="productionProgressContent"','/static/production-progress.js','/static/production-progress.css','FabProductionProgress.cancelPending','Production progress'])assert.ok(index.includes(phrase),phrase);assert.match(index,/params\.has\('production-progress'\)[\s\S]*FabProductionProgress\.open/);assert.match(index,/params\.has\('progress'\)[\s\S]*FabProgress\.open/);assert.equal(index,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'));check('Both shells expose the new production view and retain existing project deep links');
  console.log(JSON.stringify({status:'passed',contracts:checks.length,checks},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});

