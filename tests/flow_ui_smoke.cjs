/* Synthetic CLM traveler client tests. No account or service is contacted.
 * Run: node tests/flow_ui_smoke.cjs
 */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const elements=new Map();
class Element {
  constructor(id){this.id=id;this.listeners={};this.classes=new Set();this.attributes={};this.value='';this.disabled=false;this.checked=false;this.textContent='';this.dataset={};this.children=[];this.clocks=[];this.open=false;this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),contains:x=>this.classes.has(x),toggle:(x,force)=>{if(force===undefined?!this.classes.has(x):force)this.classes.add(x);else this.classes.delete(x)}};}
  set innerHTML(html){
    for(const id of this.children)elements.delete(id);this.children=[];this.clocks=[];this.html=html;
    for(const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){
      const child=new Element(match[1]);child.value=match[0].match(/\bvalue="([^"]*)"/)?.[1]||'';child.disabled=/\sdisabled(?:\s|>)/.test(match[0]);
      for(const cls of (match[0].match(/\bclass="([^"]*)"/)?.[1]||'').split(' '))child.classes.add(cls);
      elements.set(child.id,child);this.children.push(child.id);
    }
    for(const match of html.matchAll(/<select[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){
      const options=[...match[2].matchAll(/<option value="([^"]*)"([^>]*)>/g)];elements.get(match[1]).value=(options.find(row=>row[2].includes('selected'))||options[0])?.[1]||'';
    }
    for(const match of html.matchAll(/<span[^>]+data-flow-clock="([^"]+)"[^>]*>/g)){const c=new Element('clock');c.dataset.flowClock=match[1];c.dataset.flowAnchor=match[0].match(/data-flow-anchor="([^"]+)"/)[1];this.clocks.push(c)}
  }
  get innerHTML(){return this.html||''}
  addEventListener(name,fn){this.listeners[name]=fn}
  setAttribute(name,value){this.attributes[name]=value}
  querySelectorAll(selector){return selector==='[data-flow-clock]'?this.clocks:[]}
  showModal(){this.open=true}close(){this.open=false}focus(){}setSelectionRange(){}scrollIntoView(){}
}
for(const id of ['flowContent','flowDialog','flowDialogTitle','flowDialogFields','flowDialogForm','flowDialogSubmit','flowDialogError','flowDialogClose','flowDialogCancel','navFlow','itemFlowBtn'])elements.set(id,new Element(id));
const titles=['Receive Shipment','QA/QC-001 · Check Dimensions','Capture Location','Material in Inventory','Select Components for Spool','Release to Fabrication Prep Technician','Prep Components','Return to Floor','Release to Fit-Up Welder','Fit-Up & Tack Weld','QA/QC-002 · Check Dimensions','Return to Floor','Release to Process Welder','Complete Welds','QA/QC-003 · Inspect Welds','Return to Floor','Release to Testing (Hydro/UT)','QA/QC-004 - Verify Test Results','Return to Floor','Release to Sandblast and Paint','Sandblast & Paint','QA/QC-005 - Final Inspection','Release to Ready to Ship','Ship to Customer'];
const catalog={version:'CLM-24-v5',routes:[{id:'component',label:'Component',first_step:1,last_step:8},{id:'spool',label:'Spool',first_step:9,last_step:16},{id:'assembly',label:'Assembly',first_step:17,last_step:24}],steps:titles.map((title,index)=>{const n=index+1,qa=[2,11,15,18,22].includes(n);return {number:n,title,qa_code:({2:'QA-001',11:'QA-002',15:'QA-003',18:'QA-004',22:'QA-005'})[n]||null,route:n<9?'component':n<17?'spool':'assembly',section:'Fixture section',checks:[{id:'s'+n+'_1',label:'Verify physical item & records'}],roles:qa?['admin','inspector']:['admin','supervisor','handler'],requires_scan:[1,3,5,6,8,9,12,13,16,17,18,19,20,23,24].includes(n),requires_handoff:[6,8,9,12,13,16,19,20,23].includes(n),requires_location:[3,6,8,9,12,13,16,19,20,23].includes(n),requires_reference:[1,2,5,11,15,18,22].includes(n),qa,return_steps:({2:[2],11:[10],15:[14],18:[17,18],22:[17,18,19,20,21]})[n]||[]}})};
const handoffOptions={locations:[{id:'welding',label:'Weld Bay 2',kind:'builtin',active:true,version:1},{id:'custom_rack',label:'Rack A',kind:'custom',active:true,version:1},{id:'testing',label:'Testing',kind:'builtin',active:true,version:1},{id:'qa_test_results',label:'QA/QC-004',kind:'builtin',active:true,version:1},{id:'floor',label:'Floor',kind:'builtin',active:true,version:1}],statuses:[{id:'queued',label:'Queued'},{id:'in_progress',label:'In progress'}],keep_current_location_id:'current',can_manage_locations:true};
const baseProcess=()=>({item_id:'ITM-001',version:11,as_of:'2026-10-28T12:05:00Z',status:'running',current:{id:1,process_name:'Fixture step',started_at:'2026-10-28T12:00:00Z',elapsed_seconds:300,active_seconds:240,paused_seconds:60},totals:{elapsed_seconds:300,active_seconds:240,paused_seconds:60,visits:1},by_process:[{process_name:'Fixture step',visits:1,elapsed_seconds:300,active_seconds:240,paused_seconds:60}],events:[]});
function detailAt(number,extra={}){
  const step=catalog.steps[number-1],r=catalog.routes.find(row=>row.id===step.route);
  const transfer={item_id:'ITM-001',version:4,handler:'SHOP1',handler_name:'Sender One',handler_active:true,location:'Shop',location_id:null,operational_status:'queued',status_label:'Queued',can_transfer:![16,23,24].includes(number)};
  const identity=step.route==='spool'?{spool_number:'643-777-PCW-03-01',google_part_number:'643-777-PCW-03-01',qr_alias:'643-777-PCW-03-01-[001]',display_code:'643-777-PCW-03-01-[001]'}:{};
  return {flow_stage:{key:({1:'inventory',2:'qa_001',3:'qa_001',4:'qa_001',5:'preparation',6:'preparation',7:'preparation',8:'floor',9:'preparation',10:'preparation',11:'qa_002',12:'floor',13:'welding',14:'welding',15:'qa_003',16:'floor',17:'testing',18:'qa_test_results',19:'floor',20:'paint',21:'paint',22:'qa_004',23:'ready_to_ship',24:'ready_to_ship'})[number],source_item_id:'ITM-001',inherited:false},transfer,item:{...identity,id:'ITM-001',kind:step.route==='component'?'Part':step.route==='spool'?'Spool':'Assembly',description:'Test <item>',project:'P1',location:'Shop',handler:'SHOP1',released:[16,23,24].includes(number)},flow:{item_id:'ITM-001',route:step.route,current_step:number,current:structuredClone(step),version:7,status:'active',expected_children:step.route==='component'?0:1,step_entered_at:'2026-10-28T12:00:00Z',steps:catalog.steps.filter(x=>x.route===step.route).map(x=>({...x,status:x.number<number?'completed':x.number===number?'current':'pending'})),blockers:[],baseline_reference:'',baseline_reason:''},production_process:baseProcess(),components:[],spools:[],parent:null,events:[],exceptions:[],...extra};
}
function testingAt(phase,action,extra={}){
  const kind=phase.startsWith('pressure')||phase==='floor_before_paint'?'pressure':'ndt',qa=action==='review',work=action==='start'||action==='complete',number=qa?18:action==='handoff'?19:['complete','not_required'].includes(phase)?20:17;
  const d=detailAt(number),tester=kind==='ndt'?'NDT1':'PRESS1',title=phase==='decision'?'Determine if Spool Needs to Be Sent to Testing':qa?'QA/QC-004 - Verify '+(kind==='ndt'?'NDT':'Pressure Test')+' Results':action==='correct'?'Mandatory '+kind+' rework':(kind==='ndt'?'NDT':'Pressure Test')+' · '+action;
  const roles=qa?['admin','inspector']:work||action==='correct'?['admin',kind==='ndt'?'ndt':'pressure_testing_technician']:['admin','supervisor','handler'];
  d.flow.testing={protocol:'CLM-TEST-v1',phase,decision:phase==='decision'?null:phase==='not_required'?'NO':'YES',test_kind:kind,attempt:2,cycle:1,action:action||null,active:Boolean(action),requires_decision:phase==='decision',requires_result:action==='complete'||qa,requires_child_scans:phase==='decision',review_exception_ids:[],test_started_by:action==='complete'||qa?tester:null,return_to:{sender_badge:tester,sender_name:kind==='ndt'?'NDT <Technician>':'Pressure technician',location_id:'testing',location_label:'Testing & inspection bay'},report:qa||action==='handoff'?{test_kind:kind,attempt:2,cycle:1,result:'PASS',reference:'REPORT-002',notes:'Actual test evidence',actor:tester,at:'2026-10-28T12:00:00Z',event_id:42}:null,qa:action==='handoff'?{result:'PASS',reference:'QA-002',actor:'QA1',at:'2026-10-28T12:04:00Z'}:null,rework_required:action==='correct',...extra};
  d.flow.current={...d.flow.current,title,roles,qa,requires_scan:true,requires_reference:['complete','review','correct'].includes(action),requires_handoff:work||action==='handoff',requires_location:work||action==='handoff',requires_child_scans:phase==='decision',requires_resolution:action==='correct',return_steps:[],handoff_target_role:action==='start'?kind==='ndt'?'ndt':'pressure_testing_technician':action==='complete'?'inspector':action==='handoff'?'handler':null,handoff_location_id:action==='start'?'testing':action==='complete'?'qa_test_results':action==='handoff'?'floor':null,checks:[{id:'testing_'+phase+'_'+action+'_1',label:'Verify the physical testing phase'}]};
  d.flow.steps=d.flow.steps.map(s=>s.number===number?{...d.flow.current,status:'current'}:s);
  if(phase==='not_required')d.flow.steps=d.flow.steps.map(s=>[18,19].includes(s.number)?{...s,status:'not_required'}:s);
  const handler=qa||action==='handoff'?'QA1':action==='complete'||action==='correct'?tester:'SHOP1';d.item.handler=handler;d.transfer={...d.transfer,handler,handler_name:handler,location:qa||action==='handoff'?'QA/QC-004':handler==='SHOP1'?'Floor':'Testing',location_id:qa||action==='handoff'?'qa_test_results':handler==='SHOP1'?'floor':'testing'};
  return d;
}
let record=detailAt(6),physicalCopies=[],allowedOverride=null,fail=null,hold=null,readHook=null,now=10000,timerId=0,timeoutId=0;
const calls=[],messages=[],timers=new Map(),readTimeouts=new Map();
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function allowed(){
  if(allowedOverride!==null)return allowedOverride;
  if(!record.flow)return ['admin','supervisor'].includes(context.me.role)?['start']:[];
  if(record.flow.status==='shipped')return ['deliver'];
  if(record.flow.status!=='active')return [];
  const actions=['pause'];if(record.flow.current.roles.includes(context.me.role)){actions.push('advance');if(record.flow.current.qa)actions.push('fail')}
  if(record.flow.route==='component')actions.push('assign-component');if(record.flow.route==='assembly'&&record.flow.current_step===17)actions.push('link-spool');return actions;
}
function detail(){return {...structuredClone(record),allowed_actions:[...allowed()]}}
let aliasHold=null;
const context={location:{origin:'https://fabtrace-cloud.onrender.com'},qrStatus:{public_base_url:'https://fabtrace-cloud.onrender.com'},document:{getElementById:id=>elements.get(id)||null},me:{role:'admin',badge:'ADMIN'},current:null,URL,URLSearchParams,Date,console,esc,AbortController,
  setTimeout:(fn,delay)=>{readTimeouts.set(++timeoutId,{fn,delay});return timeoutId},clearTimeout:id=>readTimeouts.delete(id),
  performance:{now:()=>now},setInterval:fn=>{timers.set(++timerId,fn);return timerId},clearInterval:id=>timers.delete(id),
  history:{replaceState(_a,_b,url){context.url=url}},show(page){context.page=page},stopCloudCamera(){},notify:message=>messages.push(message),async openItem(id){context.openedItem=id},FabTracking:{async open(value){context.openedWelds=value}},FabParts:{async open(value){context.openedParts=value}},FabAdmin:{async open(value){context.openedAdmin=value}},FabPermissions:{label:role=>({ndt:'NDT',pressure_testing_technician:'Pressure Testing Technician',inspector:'QA/QC',handler:'Material Coordinator'})[role]||role},
  qrId(value,kind){const text=String(value||'').trim();if(kind==='badge')return text.startsWith('FABTRACE:EMP:')?text.slice(13):text;try{return new URL(text).searchParams.get('item')||''}catch(_){}return text.startsWith('FABTRACE:ITEM:')?text.slice(14):/^[A-Za-z0-9_-]{3,60}$/.test(text)?text:''},
  FormData:class{constructor(form){this.values=Object.entries(form.values||{})}[Symbol.iterator](){return this.values[Symbol.iterator]()}},
  api:async(url,options={})=>{
    calls.push({url,...options});if(options.method){if(hold)await hold;if(fail)throw fail;return detail()}
    if(readHook){const pending=readHook(url,options);if(pending!==undefined)return pending;}
    if(url.startsWith('/api/spool-qr/resolve?')){if(aliasHold)await aliasHold;const alias=new URL(url,context.location.origin).searchParams.get('code');const item_id=({'643-777-PCW-03-01-[001]':'ITM-001','643-777-PCW-03-01-[002]':'SPL-002','643-777-PCW-03-01-[003]':'SPL-003'})[alias];if(!item_id)throw Error('Unknown spool label');return {item_id,qr_alias:alias}}
    if(url==='/api/transfers/options')return structuredClone(handoffOptions);
    if(url==='/api/employees/directory')return [{badge:'SHOP1',name:'Sender One',role:'welder',active:true},{badge:'SHOP2',name:'Receiver Two',role:'handler',active:true},{badge:'OLD1',name:'Former worker',role:'handler',active:false},{badge:'NDT1',name:'NDT technician',role:'ndt',active:true},{badge:'NDT2',name:'Other NDT technician',role:'ndt',active:true},{badge:'PRESS1',name:'Pressure technician',role:'pressure_testing_technician',active:true},{badge:'QA1',name:'QA reviewer',role:'inspector',active:true}];
    if(url==='/api/flow/catalog')return structuredClone(catalog);
    if(url==='/api/flow/board')return {items:structuredClone(physicalCopies.length?physicalCopies:record.flow?.route==='spool'?[{...record.item,item_id:record.item.id,route:'spool',flow_stage:record.flow_stage,status:record.flow.status,current_step:record.flow.current_step,project_id:'P1',subproject_id:'SUB1'}]:[])};
    if(url==='/api/flow/items')return {items:[{item_id:'ITM-001',spool_number:record.item.spool_number,google_part_number:record.item.google_part_number,qr_alias:record.item.qr_alias,display_code:record.item.display_code,flow_stage:record.flow_stage,description:'Test item',route:record.flow?.route||'component',status:record.flow?.status||'active',current_step:record.flow?.current_step||6,current_title:record.flow?.current?.title||'Prep',project_id:'P1',subproject_id:'SUB1',open_exceptions:record.exceptions?.filter(x=>!x.closed_at).length||0,blockers:[],production_process:baseProcess()},{item_id:'OTHER-002',description:'Other project item',route:'assembly',status:'delivered',current_step:null,current_title:'',project_id:'P2',subproject_id:null,open_exceptions:0,blockers:[],production_process:null}]};
    if(url.startsWith('/api/flow/items/'))return detail();throw Error('Unexpected endpoint '+url);
  },
};context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/flow-status.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/spool-qr.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/handoff.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/flow.js'),'utf8'),context);
const html=()=>elements.get('flowContent').innerHTML,posts=()=>calls.filter(row=>row.method==='POST');
const click=(name,id='')=>elements.get('flowContent').listeners.click({target:{closest:()=>({disabled:false,dataset:{flowAction:name,flowId:id}})}});
const clickSpool=id=>elements.get('flowContent').listeners.click({target:{closest:selector=>selector==='[data-flow-spool]'?{disabled:false,dataset:{flowSpool:id}}:null}});
const processBoard=()=>html().slice(html().indexOf('<section class="fst-process-board"'),html().indexOf('<aside class="fst-legend"'));
const processGroup=key=>processBoard().split('data-spool-process="'+key+'"')[1]?.split('data-spool-process=')[0]||'';
const submitStep=async values=>{const form=elements.get('flowStepForm');assert.ok(form,'current-step form exists');form.values=values;await form.onsubmit({preventDefault(){},target:form})};
const submitDialog=async values=>{const form=elements.get('flowDialogForm');form.values=values;await form.listeners.submit({preventDefault(){},target:form})};
const check=number=>({['check_s'+number+'_1']:'on'});
const currentChecks=()=>Object.fromEntries(record.flow.current.checks.map(c=>['check_'+c.id,'on']));
const chooseTesting=(name,value)=>{for(const choice of name==='testing_decision'?['YES','NO']:['PASS','FAIL']){const el=elements.get('ff-'+name+'-'+choice);assert.ok(el);el.checked=choice===value;}elements.get('ff-'+name+'-'+value).onchange();};

(async()=>{
  await context.FabFlow.open();assert.equal(context.page,'flowPage');
  assert.match(html(),/24-step fabrication flow/);assert.equal((html().match(/class="ff-map-step /g)||[]).length,24);
  assert.equal((html().match(/data-spool-process=/g)||[]).length,12);assert.match(html(),/Individual spools by process/);assert.match(html(),/data-flow-id="ITM-001">ITM-001<\/button>/);assert.doesNotMatch(html(),/fst-color-[^"]+"[^>]*>ITM-001<\/span>/);assert.match(html(),/QA\/QC-004/);
  for(const station of html().matchAll(/<(?:h3|span|strong)\b[^>]*data-station-stage="[^"]+"[^>]*>/g))assert.doesNotMatch(station[0],/fst-color-|fst-text/);
  assert.doesNotMatch(context.FabFlowStatus.strip(null,{key:'floor'}),/fst-color-|fst-text/);assert.doesNotMatch(context.FabFlowStatus.legend(),/class="fst-text/);
  const inventoryCopy=(id,suffix)=>({item_id:id,route:'spool',spool_number:'643-777-PCW-03-01',qr_alias:'643-777-PCW-03-01-['+suffix+']',flow_stage:{key:'inventory',label:'Inventory'},project_id:'INVENTORY-PROJECT',subproject_id:'RECEIVING',status:'not_started',current_step:null,purchase_order:'PO-INDIVIDUAL',assembly_number:'ASM-PLAN'});
  physicalCopies=[inventoryCopy('COPY-10','10'),inventoryCopy('COPY-2','2'),inventoryCopy('COPY-001','001'),{...inventoryCopy('COPY-WELD','011'),flow_stage:{key:'welding',label:'Process Welder'},project_id:'P1',subproject_id:'SUB1',status:'active',current_step:13}];
  await context.FabFlow.open({project:'',resetFilters:true});
  assert.deepEqual([...processBoard().matchAll(/data-spool-process="([^"]+)"/g)].map(m=>m[1]),['inventory','qa_001','preparation','qa_002','floor','welding','qa_003','testing','qa_test_results','paint','qa_004','ready_to_ship']);
  assert.deepEqual([...processGroup('inventory').matchAll(/data-process-spool="([^"]+)"/g)].map(m=>m[1]),['COPY-001','COPY-2','COPY-10']);
  assert.deepEqual([...processGroup('welding').matchAll(/data-process-spool="([^"]+)"/g)].map(m=>m[1]),['COPY-WELD']);
  assert.equal((processBoard().match(/data-flow-spool=/g)||[]).length,4);assert.doesNotMatch(processBoard(),/<details|data-flow-spool="ITM-001"/);
  assert.match(processGroup('inventory'),/data-spool-id="COPY-001" class="fst-text fst-color-black"[^>]*>643-777-PCW-03-01-\[001\]/);
  assert.match(html(),/<details class="ff-fold"><summary>Traveler records/);assert.match(html(),/<details class="ff-fold"><summary>The 24-step fabrication flow/);assert.match(html(),/<option value="INVENTORY-PROJECT"/);
  elements.get('flowProject').value='INVENTORY-PROJECT';elements.get('flowProject').onchange();assert.equal((processBoard().match(/data-flow-spool=/g)||[]).length,3);
  elements.get('flowSearch').value='[2]';elements.get('flowSearch').oninput();assert.equal((processBoard().match(/data-flow-spool=/g)||[]).length,1);assert.match(processBoard(),/data-flow-spool="COPY-2"/);
  await context.FabFlow.open({project:'',resetFilters:true});elements.get('flowStatus').value='not_started';elements.get('flowStatus').onchange();assert.equal((processBoard().match(/data-flow-spool=/g)||[]).length,3);
  await context.FabFlow.open({project:'',resetFilters:true});elements.get('flowSearch').value='Process Welder';elements.get('flowSearch').oninput();assert.equal((processBoard().match(/data-flow-spool=/g)||[]).length,1);assert.match(processBoard(),/data-flow-spool="COPY-WELD"/);
  physicalCopies[2].flow_stage={key:'inventory',label:'Inventory',needs_station_selection:true,recorded_location_label:'Legacy <Rack> & Bay'};physicalCopies[2].current_step=13;physicalCopies[2].status='active';physicalCopies[3].flow_stage={key:'ready_to_ship',label:'Ready To Ship',blocked:true};
  await context.FabFlow.open({project:'',resetFilters:true});assert.match(processGroup('inventory'),/data-spool-id="COPY-001"[^>]*fst-color-black/);assert.match(processGroup('inventory'),/Recorded location: Legacy &lt;Rack&gt; &amp; Bay\. Select a flow station on the next transfer\./);assert.doesNotMatch(processGroup('welding'),/data-process-spool="COPY-001"/);
  assert.match(processGroup('ready_to_ship'),/data-spool-id="COPY-WELD"[^>]*fst-color-green/);assert.match(processGroup('ready_to_ship'),/Release blocked/);assert.doesNotMatch(processGroup('ready_to_ship'),/Work blocked/);assert.equal(posts().length,0,'station rendering never changes a route or records a transfer');
  record={...detailAt(9),item:{...detailAt(9).item,id:'COPY-001'},flow:null,flow_stage:{key:'inventory'},suggested_route:'spool'};await clickSpool('COPY-001');assert.match(context.url,/item=COPY-001/);assert.ok(calls.some(c=>c.url==='/api/flow/items/COPY-001'));assert.match(html(),/Start a numbered process route/);
  physicalCopies=[];record=detailAt(6);await context.FabFlow.open({project:'',resetFilters:true});
  record=detailAt(12);await context.FabFlow.open({resetFilters:true});assert.match(html(),/data-flow-id="ITM-001"><span data-spool-number="643-777-PCW-03-01" data-spool-id="ITM-001" class="fst-text fst-color-yellow"[^>]*>643-777-PCW-03-01-\[001\]<\/span>/);elements.get('flowSearch').value='643-777-PCW-03-01-[001]';elements.get('flowSearch').oninput();assert.match(html(),/1 matching records/);await click('item','ITM-001');assert.match(context.url,/item=ITM-001/);assert.match(html(),/<h1><span data-spool-number="643-777-PCW-03-01"[^>]*fst-color-yellow[^>]*>643-777-PCW-03-01-\[001\]<\/span><\/h1>/);record=detailAt(6);await context.FabFlow.open({resetFilters:true});
  elements.get('flowProject').value='P1';elements.get('flowProject').onchange();assert.doesNotMatch(html(),/Other project item/);
  await click('filter-step','6');assert.match(html(),/Showing step 6/);await click('clear-step');
  elements.get('flowSubproject').value='SUB1';elements.get('flowSubproject').onchange();
  elements.get('flowStatus').value='delivered';elements.get('flowStatus').onchange();
  elements.get('flowSearch').value='unrelated search';elements.get('flowSearch').oninput();await click('filter-step','24');
  await context.FabFlow.open({project:'P2'});assert.match(html(),/value="unrelated search"/,'ordinary navigation preserves flow filters');
  await context.FabFlow.open({project:'P2',resetFilters:true});
  assert.match(html(),/OTHER-002/,'guide shortcut clears previous subproject, status, step and search');assert.doesNotMatch(html(),/Other project item/,'physical descriptions are hidden');
  assert.doesNotMatch(html(),/Showing step 24|unrelated search/);assert.equal(elements.get('flowSubproject').value,'');assert.equal(elements.get('flowStatus').value,'');
  assert.match(context.url,/project=P2/);await context.FabFlow.open({project:'P1',resetFilters:true});
  await context.FabFlow.open({item:'ITM-001'});assert.match(context.url,/flow=1/);assert.match(context.url,/item=ITM-001/);
  assert.equal((html().match(/class="ff-route-step /g)||[]).length,8,'selected item only has its own route');assert.match(html(),/<li data-flow-stage="preparation" class="fst-current" aria-current="step">/);
  assert.match(html(),/ITM-001/);assert.doesNotMatch(html(),/Test &lt;item&gt;/);assert.match(html(),/Receiving employee badge QR \/ ID/);assert.match(html(),/Destination location/);
  assert.equal(timers.size,1);now+=65000;for(const tick of timers.values())tick();assert.ok(elements.get('flowContent').clocks.some(clock=>clock.textContent==='06m 05s'));
  const before=posts().length;await submitStep({sender_badge:'SHOP1',receiver_badge:'SHOP2',location_id:'welding',operational_status:'in_progress',scanned_item_id:'ITM-001'});assert.equal(posts().length,before,'all checks required');
  await submitStep({...check(6),sender_badge:'FABTRACE:EMP:SHOP1',receiver_badge:'FABTRACE:EMP:SHOP2',location_id:'welding',operational_status:'in_progress',scanned_item_id:'https://fabtrace-cloud.onrender.com/?item=ITM-001',notes:'  Handoff  '});
  assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,confirmations:['s6_1'],notes:'Handoff',scanned_item_id:'ITM-001',sender_badge:'SHOP1',receiver_badge:'SHOP2',location_id:'welding',operational_status:'in_progress',expected_transfer_version:4});
  assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/advance');

  const beforeInvalidHandoff=posts().length;
  await submitStep({...check(6),sender_badge:'SHOP2',receiver_badge:'SHOP1',location_id:'welding',operational_status:'in_progress',scanned_item_id:'ITM-001'});
  assert.equal(posts().length,beforeInvalidHandoff,'wrong sender cannot complete a numbered handoff');assert.match(elements.get('flowHandoffSenderInfo').textContent,/recorded custodian/);
  await submitStep({...check(6),sender_badge:'SHOP1',receiver_badge:'OLD1',location_id:'welding',operational_status:'in_progress',scanned_item_id:'ITM-001'});
  assert.equal(posts().length,beforeInvalidHandoff,'inactive receiving employee is blocked');
  record=detailAt(16);await context.FabFlow.open({item:'ITM-001'});assert.equal(record.transfer.can_transfer,false);
  await submitStep({...check(16),sender_badge:'SHOP1',receiver_badge:'SHOP1',location_id:'current',operational_status:'queued',scanned_item_id:'ITM-001'});
  assert.equal(posts().length,beforeInvalidHandoff+1,'permitted numbered release handoff is not blocked by generic can_transfer');assert.equal(JSON.parse(posts().at(-1).body).sender_badge,'SHOP1');assert.equal(JSON.parse(posts().at(-1).body).receiver_badge,'SHOP1');assert.equal(elements.get('flowHandoffSender').value,'');assert.equal(elements.get('flowHandoffReceiver').value,'','each numbered handoff starts with two blank badge fields');

  record=detailAt(3);await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Storage location/);assert.doesNotMatch(html(),/Receiving employee badge QR \/ ID/);
  await submitStep({...check(3),scanned_item_id:'ITM-001',location_id:'custom_rack'});assert.equal(JSON.parse(posts().at(-1).body).location_id,'custom_rack');assert.equal(JSON.parse(posts().at(-1).body).expected_transfer_version,4);assert.equal(JSON.parse(posts().at(-1).body).sender_badge,undefined);

  record=detailAt(11);context.me.role='handler';await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"/);assert.doesNotMatch(html(),/data-flow-action="fail"/);
  context.me.role='inspector';await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Pass inspection & continue/);
  assert.doesNotMatch(html(),/data-flow-action="(?:advance-12|advance-15|skip)"/,'no arbitrary later-step controls');
  await click('fail');await submitDialog({reason:'Alignment out of tolerance',reference:'NCR-007',return_step:'10'});
  assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,reason:'Alignment out of tolerance',reference:'NCR-007',return_step:10});
  assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/fail');

  record.exceptions=[{id:1,step:11,return_step:10,reason:'Bad <alignment>',reference:'NCR-007',opened_by:'QA<one>',opened_at:'2026-10-28T11:00:00Z',closed_at:null}];
  await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Rework resolution and reinspection findings/);assert.match(html(),/Bad &lt;alignment&gt;/);assert.match(html(),/Needs reinspection/);
  await submitStep({...check(11),reference:'REPORT-008',resolution:'Alignment corrected and verified'});assert.equal(JSON.parse(posts().at(-1).body).resolution,'Alignment corrected and verified');
  allowedOverride=[];context.me.role='admin';await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"/,'server allowed_actions override local administrator status');allowedOverride=null;

  record=detailAt(17);record.spools=[{item_id:'SPL-001',description:'Completed spool',route:'spool',status:'completed',open_exceptions:0}];context.me.role='admin';await context.FabFlow.open({item:'ITM-001'});
  assert.match(html(),/Scan or enter each linked spool ID/);await submitStep({...check(17),scanned_item_id:'ITM-001',scanned_child_ids:'SPL-001\nhttps://fabtrace-cloud.onrender.com/?item=SPL-002'});
  assert.deepEqual(JSON.parse(posts().at(-1).body).scanned_child_ids,['SPL-001','SPL-002']);
  await click('link-spool');await submitDialog({spool_id:'SPL-003',reference:'ISO-A',notes:'Assembly member'});assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/link-spool');
  assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,spool_id:'SPL-003',reference:'ISO-A',notes:'Assembly member'});
  allowedOverride=['scope'];await context.FabFlow.open({item:'ITM-001'});await click('scope');
  await submitDialog({expected_children:'3',reference:'ISO-REV-B',reason:'Additional spool added'});
  assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/scope');
  assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,expected_children:3,material_reference:'',reason:'Additional spool added',reference:'ISO-REV-B'});
  allowedOverride=null;

  record=detailAt(5);record.parent={item_id:'SPL-001',description:'Parent spool',route:'spool'};await context.FabFlow.open({item:'ITM-001'});
  await click('assign-component');await submitDialog({spool_id:'SPL-002',reference:'BOM-A',notes:''});assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/assign-component');
  await submitStep({...check(5),scanned_item_id:'ITM-001',target_spool_id:'SPL-001',reference:'BOM-A'});assert.equal(JSON.parse(posts().at(-1).body).target_spool_id,'SPL-001');

  record=detailAt(24);await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Record shipment/);
  await submitStep({...check(24),scanned_item_id:'ITM-001',carrier:'Test carrier',shipment_reference:'BOL-24',destination:'Customer yard'});
  assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,confirmations:['s24_1'],notes:'',scanned_item_id:'ITM-001',carrier:'Test carrier',shipment_reference:'BOL-24',destination:'Customer yard'});
  record.flow.status='shipped';record.flow.current=null;record.flow.current_step=null;record.production_process.current=null;record.production_process.status='finished';
  await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Record delivery receipt/);assert.equal(timers.size,0);
  await click('deliver');await submitDialog({receipt_reference:'POD-25',recipient:'Receiving clerk',notes:'Received'});
  assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,receipt_reference:'POD-25',recipient:'Receiving clerk',notes:'Received'});

  record=detailAt(6);record.flow.status='admin_released';record.flow.current=null;record.flow.current_step=null;record.item.released=true;record.item.release_control={mode:'admin_override',label:'Administrative release'};
  await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/<h2>Administrative release<\/h2>/);assert.match(html(),/retain their actual status/);assert.doesNotMatch(html(),/<h2>Route complete<\/h2>|This component is ready/);assert.doesNotMatch(html(),/id="flowStepForm"/);
  await click('admin-controls','ITM-001');assert.equal(context.openedAdmin.item,'ITM-001');
  context.me.role='handler';await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/data-flow-action="admin-controls"/);context.me.role='admin';
  await context.FabFlow.open();assert.match(html(),/value="admin_released"/);

  record=detailAt(1);record.flow=null;await context.FabFlow.open({item:'ITM-001'});await click('start');
  elements.get('ff-field-start_step').value='5';elements.get('ff-field-start_step').onchange();assert.equal(elements.get('ff-field-baseline_reference').required,true);
  await submitDialog({route:'component',expected_children:'0',start_step:'5',baseline_reference:'TRAVELER-OLD',baseline_reason:'Material already received and verified',notes:'Adopted work'});
  assert.deepEqual(JSON.parse(posts().at(-1).body),{route:'component',expected_children:0,start_step:5,notes:'Adopted work',baseline_reference:'TRAVELER-OLD',baseline_reason:'Material already received and verified'});

  record=detailAt(9,{parts:{configured:true,reference:'BOM-REQ',totals:{required_qty:6}}});record.flow=null;await context.FabFlow.open({item:'ITM-001'});await click('start');
  assert.equal(elements.get('ff-field-expected_children').value,'6','configured BOM sets the required child count');assert.equal(elements.get('ff-field-expected_children').readOnly,true);assert.match(elements.get('flowDialogFields').innerHTML,/from Spool parts/);
  const beforeWrongCount=posts().length;await submitDialog({route:'spool',start_step:'9',expected_children:'1',notes:'Setup'});assert.equal(posts().length,beforeWrongCount,'linked count cannot replace the required BOM count');
  await submitDialog({route:'spool',start_step:'9',expected_children:'6',notes:'Approved parts list'});assert.equal(JSON.parse(posts().at(-1).body).expected_children,6);
  record=detailAt(9,{parts:{configured:true,totals:{required_qty:6}}});allowedOverride=['scope'];await context.FabFlow.open({item:'ITM-001',project:'P1'});await click('scope');assert.equal(context.openedParts.spool,'ITM-001');assert.equal(context.openedParts.project,'P1');allowedOverride=null;

  record=detailAt(6);await context.FabFlow.open({item:'ITM-001'});await click('pause');
  let finish;hold=new Promise(resolve=>{finish=resolve});const beforeDuplicate=posts().length;
  const first=submitDialog({notes:'Waiting for equipment'});await submitDialog({notes:'Duplicate'});assert.equal(posts().length,beforeDuplicate+1);finish();await first;hold=null;
  assert.deepEqual(JSON.parse(posts().at(-1).body),{action:'pause',expected_version:11,notes:'Waiting for equipment'});
  assert.equal(posts().at(-1).url,'/api/tracking/spools/ITM-001/process');

  await click('pause');fail=Object.assign(Error(JSON.stringify({message:'Flow changed; refresh and retry',current_version:8})),{status:409});
  const readCount=calls.filter(row=>row.url==='/api/flow/items/ITM-001'&&!row.method).length,notifications=messages.length;
  await submitDialog({notes:'Delay record'});assert.ok(calls.filter(row=>row.url==='/api/flow/items/ITM-001'&&!row.method).length>readCount);
  assert.equal(elements.get('flowDialogSubmit').disabled,true);assert.match(elements.get('flowDialogError').textContent,/Close this dialog/);assert.equal(messages.length,notifications);
  fail=null;elements.get('flowDialog').close();await click('pause');assert.equal(elements.get('flowDialogSubmit').disabled,false);
  record=detailAt(9,{parts:{configured:true,totals:{required_qty:6,prepared_qty:2,assigned_qty:4,received_qty:3,short_qty:2}}});await context.FabFlow.open({item:'ITM-001',project:'P1'});assert.match(html(),/2 of 6 required pieces prepared/);await click('spool-parts','ITM-001');assert.equal(context.openedParts.spool,'ITM-001');assert.equal(context.openedParts.project,'P1');
  record=detailAt(17);await context.FabFlow.open({item:'ITM-001'});
  await submitStep({...check(17),scanned_item_id:'643-777-PCW-03-01-[001]',scanned_child_ids:'643-777-PCW-03-01-[002]\nhttps://fabtrace-cloud.onrender.com/?spool=643-777-PCW-03-01-%5B003%5D'});
  assert.deepEqual(JSON.parse(posts().at(-1).body).scanned_child_ids,['SPL-002','SPL-003']);
  assert.equal(JSON.parse(posts().at(-1).body).scanned_item_id,'ITM-001');
  await click('link-spool');await submitDialog({spool_id:'643-777-PCW-03-01-[002]',reference:'ISO-A',notes:''});
  assert.equal(JSON.parse(posts().at(-1).body).spool_id,'SPL-002','link actions save the immutable ID behind the printed label');
  record=detailAt(5);await context.FabFlow.open({item:'ITM-001'});
  await submitStep({...check(5),scanned_item_id:'ITM-001',target_spool_id:'643-777-PCW-03-01-[003]',reference:'BOM-A'});
  assert.equal(JSON.parse(posts().at(-1).body).target_spool_id,'SPL-003');
  record=detailAt(1);await context.FabFlow.open({item:'ITM-001'});
  let releaseAlias;aliasHold=new Promise(resolve=>{releaseAlias=resolve});const beforeLate=posts().length;
  const lateSubmit=submitStep({...check(1),scanned_item_id:'643-777-PCW-03-01-[001]',reference:'PO-A'});
  context.FabFlow.cancelPending();releaseAlias();await lateSubmit;aliasHold=null;
  assert.equal(posts().length,beforeLate,'navigation during alias resolution cannot submit a stale step');
  await context.FabFlow.open({item:'ITM-001'});
  aliasHold=new Promise(resolve=>{releaseAlias=resolve});elements.get('flowLookup').value='643-777-PCW-03-01-[001]';
  const lateLookup=elements.get('flowLookupForm').onsubmit({preventDefault(){}});context.FabFlow.cancelPending();
  const beforeLateRead=calls.length;releaseAlias();await lateLookup;aliasHold=null;
  assert.equal(calls.length,beforeLateRead,'a late resolved lookup cannot reopen a departed flow screen');
  context.FabFlow.cancelPending();assert.equal(timers.size,0);

  // A selected record must not recalculate every route or physical spool.
  record=detailAt(9);record.project_id='P1';record.subproject_id='SUB1';
  const focusedStart=calls.length;await context.FabFlow.open({item:'ITM-001',project:'P1'});
  const focusedCalls=calls.slice(focusedStart);
  assert.ok(focusedCalls.some(row=>row.url==='/api/flow/items/ITM-001'));
  assert.ok(focusedCalls.some(row=>row.url==='/api/transfers/options'));
  assert.ok(!focusedCalls.some(row=>['/api/flow/items','/api/flow/board'].includes(row.url)),'detail omits both broad lists');
  assert.match(html(),/fst-color-red[^>]*>643-777-PCW-03-01-\[001\]/);
  assert.match(html(),/<dt>Subproject<\/dt><dd>SUB1<\/dd>/);
  assert.equal((html().match(/class="ff-map-step /g)||[]).length,24);
  const boardStart=calls.length;await click('board');
  assert.ok(calls.slice(boardStart).some(row=>row.url==='/api/flow/items'));
  assert.ok(calls.slice(boardStart).some(row=>row.url==='/api/flow/board'));
  assert.match(html(),/<option value="P2"/,'returning to the board retains all project options');
  assert.match(context.url,/project=P1/,'the selected project survives detail-to-board navigation');

  // Navigation aborts GETs and their timers; a late read cannot overwrite a destination.
  let signal;
  readHook=(url,options)=>url==='/api/flow/items/ITM-001'?new Promise((_resolve,reject)=>{
    signal=options.signal;signal.addEventListener('abort',()=>reject(Object.assign(Error('Read aborted'),{name:'AbortError'})),{once:true});
  }):undefined;
  const cancelledOpen=context.FabFlow.open({item:'ITM-001'});
  assert.ok(signal&&!signal.aborted);assert.equal(readTimeouts.size,1);
  context.FabFlow.cancelPending();elements.get('flowContent').innerHTML='<p>Destination screen</p>';
  await cancelledOpen;assert.equal(signal.aborted,true);assert.equal(html(),'<p>Destination screen</p>');assert.equal(readTimeouts.size,0);

  // A stalled GET exits the spinner and offers a safe read retry; no write is retried.
  const writesBefore=posts().length,timedOpen=context.FabFlow.open({item:'ITM-001'});
  assert.equal(readTimeouts.size,1);const timeout=[...readTimeouts.values()][0];assert.equal(timeout.delay,30000);timeout.fn();
  await timedOpen;assert.match(html(),/request took too long/);assert.match(html(),/Try again/);assert.equal(elements.get('flowContent').attributes['aria-busy'],'false');assert.equal(readTimeouts.size,0);assert.equal(posts().length,writesBefore);
  readHook=null;await click('refresh');assert.match(html(),/Spool route/);

  readHook=(url)=>url==='/api/flow/items/ITM-001'?Promise.resolve({...detail(),item:{...record.item,id:'OTHER-COPY'}}):undefined;
  await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/does not match the selected item/);assert.doesNotMatch(html(),/id="flowStepForm"/);
  readHook=null;context.FabFlow.cancelPending();assert.equal(readTimeouts.size,0);assert.equal(timers.size,0);
  // Required testing decisions never default either route or a QA outcome.
  record=testingAt('decision','decision');context.me={role:'handler',badge:'SHOP1'};await context.FabFlow.open({item:'ITM-001'});
  assert.match(html(),/Determine if Spool Needs to Be Sent to Testing/);assert.match(html(),/Scan or enter each linked spool ID/);
  for(const choice of ['YES','NO'])assert.equal(elements.get('ff-testing_decision-'+choice).checked,false);
  assert.equal(elements.get('flowAdvance').disabled,true);let testingWrites=posts().length;
  const decisionValues={...currentChecks(),scanned_item_id:'ITM-001',scanned_child_ids:'SPL-001\nSPL-002'};
  await submitStep(decisionValues);assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/Choose YES or NO/);
  chooseTesting('testing_decision','YES');assert.match(elements.get('flowAdvance').textContent,/Save YES.*Send to NDT/);
  await submitStep({...decisionValues,testing_decision:'YES'});let testingBody=JSON.parse(posts().at(-1).body);
  assert.equal(posts().length,testingWrites+1);assert.deepEqual(testingBody,{expected_version:7,testing_phase:'decision',testing_attempt:2,testing_action:'decision',confirmations:['testing_decision_decision_1'],notes:'',testing_decision:'YES',scanned_item_id:'ITM-001',scanned_child_ids:['SPL-001','SPL-002']});
  chooseTesting('testing_decision','NO');assert.match(elements.get('flowAdvance').textContent,/Save NO.*Paint\/finishing/);await submitStep({...decisionValues,testing_decision:'NO'});assert.equal(JSON.parse(posts().at(-1).body).testing_decision,'NO');
  record=testingAt('not_required',null);await context.FabFlow.open({item:'ITM-001'});
  for(const step of [18,19])assert.match(html(),new RegExp('class="ff-route-step not_required"><span class="ff-num">'+step+'<'));
  assert.match(html(),/Testing required: NO/);assert.match(html(),/Testing decision: NO/);assert.doesNotMatch(html(),/name="testing_decision"|name="test_result"/);

  // Testing employees record test evidence; QA alone decides acceptance.
  record=testingAt('ndt','start');await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"/);assert.match(html(),/Recorded by: admin · NDT/);
  context.me={role:'ndt',badge:'NDT1'};await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/Scan or enter each linked spool ID|name="testing_decision"|name="test_result"/);
  assert.equal(elements.get('flowHandoffLocation').value,'testing');assert.equal(elements.get('flowHandoffReceiver').value,'');assert.match(html(),/Time in current phase/);
  testingWrites=posts().length;await submitStep({...currentChecks(),scanned_item_id:'ITM-001',sender_badge:'SHOP1',receiver_badge:'NDT2',location_id:'testing',operational_status:'in_progress'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/signed-in testing employee/);
  await submitStep({...currentChecks(),scanned_item_id:'ITM-001',sender_badge:'SHOP1',receiver_badge:'NDT1',location_id:'testing',operational_status:'in_progress'});testingBody=JSON.parse(posts().at(-1).body);assert.equal(testingBody.testing_action,'start');assert.equal(testingBody.testing_phase,'ndt');assert.equal(testingBody.receiver_badge,'NDT1');assert.equal(testingBody.scanned_child_ids,undefined);
  context.me={role:'admin',badge:'ADMIN'};await context.FabFlow.open({item:'ITM-001'});testingWrites=posts().length;await submitStep({...currentChecks(),scanned_item_id:'ITM-001',sender_badge:'SHOP1',receiver_badge:'NDT1',location_id:'testing',operational_status:'in_progress'});assert.equal(posts().length,testingWrites+1,'administrator may record receipt for the qualified actual testing custodian');context.me={role:'ndt',badge:'NDT1'};
  record=testingAt('ndt','complete');await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Result recorded in the technician’s test report/);assert.match(elements.get('flowAdvance').textContent,/Submit NDT report to QA\/QC/);assert.equal(elements.get('flowAdvance').disabled,true);
  const ndtReport={...currentChecks(),scanned_item_id:'ITM-001',reference:'NDT-REPORT-002',sender_badge:'NDT1',receiver_badge:'QA1',location_id:'qa_test_results',operational_status:'queued'};
  testingWrites=posts().length;await submitStep(ndtReport);assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/Choose PASS or FAIL/);
  chooseTesting('test_result','FAIL');await submitStep({...ndtReport,test_result:'FAIL',reference:''});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/required record or inspection reference/);
  await submitStep({...ndtReport,test_result:'FAIL'});assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/advance');testingBody=JSON.parse(posts().at(-1).body);assert.equal(testingBody.testing_action,'complete');assert.equal(testingBody.test_result,'FAIL');assert.equal(testingBody.reference,'NDT-REPORT-002');assert.equal(testingBody.receiver_badge,'QA1');assert.equal(testingBody.reason,undefined);
  context.me={role:'ndt',badge:'NDT2'};await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"/);assert.match(html(),/recorded testing employee \(NDT1\).*submit this test report/);context.me={role:'admin',badge:'ADMIN'};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/id="flowStepForm"/);context.me={role:'ndt',badge:'NDT1'};

  record=testingAt('ndt_qa','review');await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"/,'NDT report ownership does not grant QA acceptance');
  context.me={role:'inspector',badge:'QA1'};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/QA\/QC result for this test attempt/);assert.match(html(),/Technician test report/);assert.match(html(),/REPORT-002/);assert.match(html(),/QA\/QC acceptance is recorded separately/);assert.match(html(),/NDT &lt;Technician&gt; \(NDT1\)/);assert.match(html(),/Testing &amp; inspection bay/);assert.doesNotMatch(html(),/name="return_step"/);
  assert.equal(elements.get('flowTestingFailure').disabled,true);assert.equal(elements.get('flowTestingFailure').classes.has('hidden'),true);assert.equal(elements.get('flowAdvance').disabled,true);
  chooseTesting('test_result','PASS');assert.match(elements.get('flowAdvance').textContent,/Record PASS.*Return to Floor/);assert.equal(elements.get('flowTestingFailure').disabled,true);
  await submitStep({...currentChecks(),test_result:'PASS',scanned_item_id:'ITM-001',reference:'QA-ACCEPT-002'});testingBody=JSON.parse(posts().at(-1).body);assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/advance');assert.equal(testingBody.testing_phase,'ndt_qa');assert.equal(testingBody.testing_action,'review');assert.equal(testingBody.test_result,'PASS');assert.equal(testingBody.sender_badge,undefined);assert.equal(testingBody.receiver_badge,undefined);

  // FAIL requires its own details and the exact frozen return custody, even when passing is blocked.
  record.flow.blockers=['A passing dimensional inspection is required'];await context.FabFlow.open({item:'ITM-001'});chooseTesting('test_result','PASS');assert.equal(elements.get('flowAdvance').disabled,true);
  chooseTesting('test_result','FAIL');assert.equal(elements.get('flowAdvance').disabled,false);assert.equal(elements.get('flowTestingPassChecks').disabled,true);assert.equal(elements.get('flowTestingFailure').disabled,false);assert.equal(elements.get('flowTestingFailure').classes.has('hidden'),false);assert.match(elements.get('flowAdvance').textContent,/Record FAIL.*Return for rework/);
  const qaFailure={test_result:'FAIL',scanned_item_id:'ITM-001',reason:'Repair the rejected indication before a fresh test',reference:'NCR-002',sender_badge:'QA1',receiver_badge:'NDT1',location_id:'testing',operational_status:'in_progress'};
  testingWrites=posts().length;await submitStep({...qaFailure,reason:''});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/failure, required repair/);
  await submitStep({...qaFailure,reference:'X'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/at least two characters/);
  await submitStep({...qaFailure,receiver_badge:'NDT2'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/recorded employee who sent this test/);
  await submitStep({...qaFailure,location_id:'floor'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/destination required by this testing phase/);
  await submitStep({...qaFailure,return_step:'20',testing_decision:'NO'});assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/fail');testingBody=JSON.parse(posts().at(-1).body);assert.deepEqual(testingBody,{expected_version:7,testing_phase:'ndt_qa',testing_attempt:2,testing_action:'review',test_result:'FAIL',scanned_item_id:'ITM-001',sender_badge:'QA1',receiver_badge:'NDT1',location_id:'testing',operational_status:'in_progress',expected_transfer_version:4,reference:'NCR-002',reason:'Repair the rejected indication before a fresh test'});
  chooseTesting('test_result','PASS');assert.equal(elements.get('flowTestingFailure').disabled,true);assert.equal(elements.get('flowTestingPassChecks').disabled,false);

  // A failed technician report cannot be accepted as QA PASS, including a forged form value.
  record=testingAt('ndt_qa','review');record.flow.testing.report.result='FAIL';await context.FabFlow.open({item:'ITM-001'});assert.equal(elements.get('ff-test_result-PASS').disabled,true);assert.equal(elements.get('ff-test_result-FAIL').checked,false);assert.match(html(),/The technician’s report records FAIL/);assert.match(elements.get('flowTestingHint').textContent,/Select FAIL/);
  chooseTesting('test_result','PASS');assert.equal(elements.get('flowAdvance').disabled,true);testingWrites=posts().length;await submitStep({...currentChecks(),test_result:'PASS',scanned_item_id:'ITM-001',reference:'INVALID-PASS'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/fresh test before QA\/QC PASS/);
  chooseTesting('test_result','FAIL');assert.equal(elements.get('flowAdvance').disabled,false);await submitStep(qaFailure);assert.equal(posts().length,testingWrites+1);assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/fail');
  record=testingAt('ndt_qa','review');record.flow.testing.return_to.location_id=null;await context.FabFlow.open({item:'ITM-001'});chooseTesting('test_result','FAIL');testingWrites=posts().length;await submitStep(qaFailure);assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/recorded return station and sending employee/);

  // Corrective work is a recorded action followed by a fresh attempt, without a new NO shortcut.
  record=testingAt('ndt_rework','correct');context.me={role:'ndt',badge:'NDT1'};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Completed rework and corrective action/);assert.match(html(),/fresh test report/);assert.doesNotMatch(html(),/name="testing_decision"|name="test_result"|name="return_step"/);
  testingWrites=posts().length;await submitStep({...currentChecks(),scanned_item_id:'ITM-001',reference:'REPAIR-002'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/completed rework/);
  await submitStep({...currentChecks(),scanned_item_id:'ITM-001',reference:'REPAIR-002',resolution:'Rejected indication repaired and verified ready for retest',testing_decision:'NO'});testingBody=JSON.parse(posts().at(-1).body);assert.equal(testingBody.testing_action,'correct');assert.equal(testingBody.testing_phase,'ndt_rework');assert.match(testingBody.resolution,/repaired/);assert.equal(testingBody.testing_decision,undefined);
  context.me={role:'ndt',badge:'NDT2'};await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"/);assert.match(html(),/recorded testing employee \(NDT1\).*record the completed rework/);context.me={role:'ndt',badge:'NDT1'};
  record=testingAt('ndt','start',{attempt:3});await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Attempt 3/);assert.equal(elements.get('flowHandoffReceiver').value,'');assert.doesNotMatch(html(),/Technician test report|QA-ACCEPT-002/);

  for(const phase of ['floor_before_pressure','floor_before_paint']){
    record=testingAt(phase,'handoff');context.me={role:'handler',badge:'SHOP2'};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Recorded QA\/QC decision/);assert.equal(elements.get('flowHandoffLocation').value,'floor');assert.match(elements.get('flowAdvance').textContent,phase==='floor_before_pressure'?/Pressure testing next/:/Paint\/finishing next/);
    await submitStep({...currentChecks(),scanned_item_id:'ITM-001',sender_badge:'QA1',receiver_badge:'SHOP2',location_id:'floor',operational_status:'queued'});testingBody=JSON.parse(posts().at(-1).body);assert.equal(testingBody.testing_phase,phase);assert.equal(testingBody.testing_action,'handoff');assert.equal(testingBody.testing_attempt,2);assert.equal(testingBody.location_id,'floor');
  }
  record=testingAt('pressure_test','start');context.me={role:'ndt',badge:'NDT1'};await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"/);assert.match(html(),/Pressure Testing Technician/);
  context.me={role:'pressure_testing_technician',badge:'PRESS1'};await context.FabFlow.open({item:'ITM-001'});await submitStep({...currentChecks(),scanned_item_id:'ITM-001',sender_badge:'SHOP1',receiver_badge:'PRESS1',location_id:'testing',operational_status:'in_progress'});assert.equal(JSON.parse(posts().at(-1).body).testing_phase,'pressure_test');
  record=testingAt('pressure_test','complete');await context.FabFlow.open({item:'ITM-001'});chooseTesting('test_result','PASS');assert.match(elements.get('flowAdvance').textContent,/Submit Pressure test report to QA\/QC/);await submitStep({...currentChecks(),test_result:'PASS',scanned_item_id:'ITM-001',reference:'PRESSURE-REPORT-002',sender_badge:'PRESS1',receiver_badge:'QA1',location_id:'qa_test_results',operational_status:'queued'});assert.equal(JSON.parse(posts().at(-1).body).testing_action,'complete');
  record=testingAt('pressure_qa','review');await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"/);context.me={role:'inspector',badge:'QA1'};await context.FabFlow.open({item:'ITM-001'});chooseTesting('test_result','FAIL');await submitStep({...qaFailure,receiver_badge:'PRESS1',reference:'PRESSURE-NCR-002'});testingBody=JSON.parse(posts().at(-1).body);assert.equal(testingBody.testing_phase,'pressure_qa');assert.equal(testingBody.receiver_badge,'PRESS1');assert.equal(testingBody.return_step,undefined);

  // A carried pressure failure stays visible during fresh NDT QA without demanding the wrong resolution.
  const carriedPressure={id:901,step:18,return_step:17,reason:'Pressure failure remains open until pressure QA',reference:'PRESSURE-NCR-002',opened_by:'QA1',opened_at:'2026-10-28T12:00:00Z',closed_at:null};
  record=testingAt('ndt_qa','review',{cycle:2,pending_exception_ids:[901],review_exception_ids:[]});record.exceptions=[carriedPressure];await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Pressure failure remains open until pressure QA/);assert.doesNotMatch(html(),/id="ff-field-resolution"/);chooseTesting('test_result','PASS');await submitStep({...currentChecks(),test_result:'PASS',scanned_item_id:'ITM-001',reference:'NDT-NEW-CYCLE'});assert.equal(JSON.parse(posts().at(-1).body).resolution,undefined);
  record=testingAt('pressure_qa','review',{cycle:2,pending_exception_ids:[901],review_exception_ids:[901]});record.exceptions=[carriedPressure];await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/id="ff-field-resolution"/);chooseTesting('test_result','PASS');testingWrites=posts().length;await submitStep({...currentChecks(),test_result:'PASS',scanned_item_id:'ITM-001',reference:'PRESSURE-NEW-CYCLE'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/reinspection findings/);await submitStep({...currentChecks(),test_result:'PASS',scanned_item_id:'ITM-001',reference:'PRESSURE-NEW-CYCLE',resolution:'Corrected pressure failure verified against the fresh pressure test'});assert.equal(JSON.parse(posts().at(-1).body).resolution,'Corrected pressure failure verified against the fresh pressure test');

  // Frozen scope and an inherited child view keep operators on the actual assembly route.
  record=testingAt('ndt','start');context.me={role:'admin',badge:'ADMIN'};allowedOverride=['advance','scope','link-spool'];await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/data-flow-action="scope"|data-flow-action="link-spool"/);assert.match(html(),/linked spool scope is fixed/);elements.get('flowDialog').close();await click('scope');await click('link-spool');assert.equal(elements.get('flowDialog').open,false);allowedOverride=null;
  record=testingAt('decision','decision',{decision:'YES',cycle:2,attempt:1});await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Cycle 2 · Attempt 1/);assert.equal(elements.get('ff-testing_decision-NO').disabled,true);assert.equal(elements.get('ff-testing_decision-YES').checked,false);testingWrites=posts().length;await submitStep({...currentChecks(),testing_decision:'NO',scanned_item_id:'ITM-001',scanned_child_ids:'SPL-001'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/Testing remains required/);
  record=detailAt(16);Object.assign(record.flow,{current:null,current_step:null,status:'completed'});record.flow.steps=record.flow.steps.map(step=>({...step,status:'completed'}));record.parent={item_id:'ASM-TESTING',route:'assembly'};record.flow_stage={key:'testing',label:'Testing',inherited:true,source_item_id:'ASM-TESTING'};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/where testing and finishing are recorded for the linked spools/);assert.match(html(),/data-flow-action="item" data-flow-id="ASM-TESTING">Open assembly process/);assert.doesNotMatch(html(),/id="flowStepForm"/);
  record=testingAt('ndt','start');record.item.id='ASM-TESTING';record.flow.item_id='ASM-TESTING';record.transfer.item_id='ASM-TESTING';record.production_process.item_id='ASM-TESTING';await click('item','ASM-TESTING');assert.match(context.url,/item=ASM-TESTING/);assert.match(html(),/data-testing-phase="ndt"/);

  // Saved testing history is not an active phase after an administrative move or after testing completes.
  const savedTesting=testingAt('ndt_qa','review').flow.testing;record=detailAt(23);record.flow.blockers=['Complete the pending testing phase and required QA results before coating or final release'];record.flow.testing={...savedTesting,active:false,action:null,requires_result:false};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/saved testing phase is not active/);assert.match(html(),/REPORT-002/);assert.match(html(),/Time at current step/);assert.doesNotMatch(html(),/name="test_result"|name="testing_decision"|flowTestingFailure|Time in current phase/);assert.equal(elements.get('flowAdvance').disabled,true);
  record=detailAt(21);record.flow.testing={...savedTesting,phase:'complete',active:false,action:null,requires_result:false};await context.FabFlow.open({item:'ITM-001'});await submitStep({...currentChecks(),test_result:'FAIL',testing_decision:'NO'});testingBody=JSON.parse(posts().at(-1).body);assert.deepEqual(testingBody,{expected_version:7,confirmations:['s21_1'],notes:''});
  record=detailAt(23);record.flow.blockers=['Complete the pending testing phase'];record.flow.testing={...savedTesting,active:false};await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/name="test_result"|flowTestingFailure|Time in current phase/,'inactive wins over a stale action flag');

  // Server-authorized supervisors and admins can restart testing with an audited reason and reference.
  const restartValues={reason:'Source material changed after the accepted test',reference:'BOM-REV-C'};
  for(const [number,phase,decision] of [[20,'complete','YES'],[21,'not_required','NO']]){
    record=detailAt(number);record.flow.testing={...savedTesting,phase,decision,active:false,action:null,requires_result:false};allowedOverride=['advance','restart-testing'];context.me={role:'supervisor',badge:'SUP1'};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/data-flow-action="restart-testing">Return to testing/);await click('restart-testing');assert.equal(elements.get('flowDialog').open,true);assert.match(elements.get('flowDialogFields').innerHTML,/new testing cycle/);if(decision==='YES')assert.match(elements.get('flowDialogFields').innerHTML,/Testing remains required/);
    testingWrites=posts().length;await submitDialog({...restartValues,reason:'Why'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowDialogError').textContent,/at least four characters/);await submitDialog({...restartValues,reference:'X'});assert.equal(posts().length,testingWrites);
    await submitDialog(restartValues);assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/restart-testing');assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,...restartValues});assert.equal(elements.get('flowDialog').open,false);
  }
  for(const role of ['handler','inspector']){context.me={role,badge:'SHOP1'};await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/data-flow-action="restart-testing"/);await click('restart-testing');assert.equal(elements.get('flowDialog').open,false,'server actions cannot widen the restart role boundary');}
  context.me={role:'admin',badge:'ADMIN'};allowedOverride=[];await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/data-flow-action="restart-testing"/);await click('restart-testing');assert.equal(elements.get('flowDialog').open,false);
  record=testingAt('pressure_test','complete');record.flow.blockers=['The earlier NDT proof no longer matches the changed material or construction scope. Return to testing for a fresh NDT cycle.'];allowedOverride=['advance','restart-testing'];await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/data-flow-action="restart-testing">Return to testing/,'server restart action is available during active pressure testing');assert.equal(record.flow.testing.active,true);assert.equal(elements.get('flowAdvance').disabled,true);await click('restart-testing');assert.match(elements.get('flowDialogFields').innerHTML,/Open failure requirements must still be resolved/);testingWrites=posts().length;await submitDialog({...restartValues,test_result:'PASS',testing_decision:'NO',testing_action:'complete'});assert.equal(posts().length,testingWrites+1);assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/restart-testing');assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,...restartValues});
  allowedOverride=null;context.me={role:'inspector',badge:'QA1'};record=testingAt('pressure_qa','review');record.flow.blockers=['The earlier NDT proof no longer matches the changed material or construction scope. Return to testing for a fresh NDT cycle.'];await context.FabFlow.open({item:'ITM-001'});assert.equal(elements.get('ff-test_result-PASS').disabled,true);assert.equal(elements.get('ff-test_result-FAIL').checked,false);assert.match(html(),/QA\/QC PASS is blocked/);assert.match(elements.get('flowTestingHint').textContent,/earlier NDT proof no longer matches/);chooseTesting('test_result','PASS');assert.equal(elements.get('flowAdvance').disabled,true);testingWrites=posts().length;await submitStep({...currentChecks(),test_result:'PASS',scanned_item_id:'ITM-001',reference:'QA-STALE-NDT'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/earlier NDT proof no longer matches/);chooseTesting('test_result','FAIL');assert.equal(elements.get('flowAdvance').disabled,false,'the failed disposition remains available while passing is blocked');
  context.me={role:'admin',badge:'ADMIN'};allowedOverride=['restart-testing'];
  record=detailAt(20);record.flow.testing={...savedTesting,phase:'complete',active:false,action:null,requires_result:false};await context.FabFlow.open({item:'ITM-001'});await click('restart-testing');testingWrites=posts().length;fail=Object.assign(Error('The route changed. Refresh before starting a new testing cycle.'),{status:409});await submitDialog(restartValues);assert.equal(posts().length,testingWrites+1);assert.equal(elements.get('flowDialogSubmit').disabled,true);await submitDialog(restartValues);assert.equal(posts().length,testingWrites+1,'a stale testing restart is not retried');fail=null;elements.get('flowDialog').close();allowedOverride=null;

  // Recorded phase history is legible and a stale review is never retried automatically.
  record=testingAt('ndt_qa','review');record.events=[{action:'advance',step:17,actor:'SHOP1',at:'2026-10-28T11:00:00Z',data:{testing_protocol:'CLM-TEST-v1',testing_phase:'decision',testing_action:'decision',testing_attempt:2,testing_decision:'YES'}},{action:'advance',step:17,actor:'NDT1',reference:'NDT-REPORT-002',at:'2026-10-28T11:30:00Z',data:{testing_protocol:'CLM-TEST-v1',testing_phase:'ndt',testing_action:'complete',testing_cycle:2,testing_attempt:1,test_result:'PASS'}}];
  record.events.push({action:'reopen',step:20,actor:'SUP1',reference:'BOM-REV-C',notes:'Source material changed',at:'2026-10-28T11:40:00Z',data:{testing_protocol:'CLM-TEST-v1',testing_phase:'complete',testing_action:'restart',testing_cycle:1,testing_attempt:4,next_phase:'decision',next_cycle:2,testing_required_preserved:true}});
  await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Testing decision recorded/);assert.match(html(),/Technician test report recorded/);assert.match(html(),/Testing required: YES/);assert.match(html(),/Result: PASS/);assert.match(html(),/NDT · Cycle 2 · Attempt 1/);assert.match(html(),/Returned to testing/);assert.match(html(),/Testing decision · Cycle 2 · Testing required: YES/);
  chooseTesting('test_result','PASS');testingWrites=posts().length;fail=Object.assign(Error(JSON.stringify({message:'The testing phase or attempt changed. Refresh the traveler.'})),{status:409});await submitStep({...currentChecks(),test_result:'PASS',scanned_item_id:'ITM-001',reference:'STALE-QA'});assert.equal(posts().length,testingWrites+1);assert.match(html(),/testing phase or attempt changed/);assert.equal(elements.get('ff-test_result-PASS').checked,false);assert.equal(elements.get('ff-test_result-FAIL').checked,false);assert.equal(elements.get('flowAdvance').disabled,true);fail=null;
  allowedOverride=[];context.me={role:'admin',badge:'ADMIN'};await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"|name="test_result"/);testingWrites=posts().length;await click('fail');assert.equal(posts().length,testingWrites);allowedOverride=null;
  record.removal={removed:true};await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/id="flowStepForm"|name="test_result"/);await click('fail');assert.equal(posts().length,testingWrites);context.FabFlow.cancelPending();assert.equal(readTimeouts.size,0);assert.equal(timers.size,0);
  const index=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
  assert.match(index,/params\.has\('flow'\)[\s\S]*FabFlow\.open/);assert.match(index,/id="itemFlowBtn"/);assert.match(index,/id="navFlow"/);assert.match(index,/FabFlow\.cancelPending/);
  assert.equal(index,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'));
  console.log('PASS: neutral station labels, colored physical spool numbers, escaped unknown-station notices, retained blocked Ready To Ship, 24-step map, entity-specific routes, filters, QR/manual IDs, location/handoff payloads, catalog checks and roles, QA failure/reinspection, hierarchy links, child verification, shipment/delivery, documented baselines, clocks, duplicate writes, conflicts, focused record reads, cancellation, bounded loading, navigation, required YES/NO testing, separate technician and QA results, fixed failure custody, mandatory rework/retest phases, Floor handoffs, pressure testing permissions, Not required bypasses, original testing custodian, inactive testing history, controlled restarts, cycle/attempt history and stale testing decisions.');
})().catch(error=>{console.error(error);process.exitCode=1});


