/* Synthetic CLM traveler client tests. No account or service is contacted.
 * Run: node tests/flow_ui_smoke.cjs
 */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const elements=new Map();
class Element {
  constructor(id){this.id=id;this.listeners={};this.classes=new Set();this.attributes={};this.value='';this.disabled=false;this.dataset={};this.children=[];this.clocks=[];this.open=false;this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),contains:x=>this.classes.has(x),toggle:(x,force)=>{if(force===undefined?!this.classes.has(x):force)this.classes.add(x);else this.classes.delete(x)}};}
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
const titles=['Receive Shipment','Check Dimensions','Capture Location','Material in Inventory','Select Components for Spool','Release to Fabrication Prep Technician','Prep Components','Return to Production','Release to Fit-Up Welder','Fit-Up & Tack Weld','QA/QC – Check Dimensions','Return to Production','Release to Process Welder','Complete Welds','QA/QC – Inspect Welds','Scan Completed Spool','Collect Spools for Assembly','Create Assembly ID','QA/QC – Assembly Inspection','Release to Sandblast & Paint','Sandblast & Paint','QA/QC – Final Inspection','Release to Ready to Ship','Ship to Customer'];
const catalog={version:'CLM-24-v1',routes:[{id:'component',label:'Component',first_step:1,last_step:8},{id:'spool',label:'Spool',first_step:9,last_step:16},{id:'assembly',label:'Assembly',first_step:17,last_step:24}],steps:titles.map((title,index)=>{const n=index+1,qa=[2,11,15,19,22].includes(n);return {number:n,title,route:n<9?'component':n<17?'spool':'assembly',section:'Fixture section',checks:[{id:'s'+n+'_1',label:'Verify physical item & records'}],roles:qa?['admin','inspector']:['admin','supervisor','handler'],requires_scan:[1,3,5,6,8,9,12,13,16,17,18,20,23,24].includes(n),requires_handoff:[6,8,9,12,13,16,20,23].includes(n),requires_location:[3,6,8,9,12,13,16,20,23].includes(n),requires_reference:[1,2,5,11,15,19,22].includes(n),qa,return_steps:({2:[2],11:[10],15:[14],19:[17,18],22:[17,18,19,20,21]})[n]||[]}})};
const handoffOptions={locations:[{id:'welding',label:'Weld Bay 2',kind:'builtin',active:true,version:1},{id:'custom_rack',label:'Rack A',kind:'custom',active:true,version:1}],statuses:[{id:'queued',label:'Queued'},{id:'in_progress',label:'In progress'}],keep_current_location_id:'current',can_manage_locations:true};
const baseProcess=()=>({item_id:'ITM-001',version:11,as_of:'2026-10-28T12:05:00Z',status:'running',current:{id:1,process_name:'Fixture step',started_at:'2026-10-28T12:00:00Z',elapsed_seconds:300,active_seconds:240,paused_seconds:60},totals:{elapsed_seconds:300,active_seconds:240,paused_seconds:60,visits:1},by_process:[{process_name:'Fixture step',visits:1,elapsed_seconds:300,active_seconds:240,paused_seconds:60}],events:[]});
function detailAt(number,extra={}){
  const step=catalog.steps[number-1],r=catalog.routes.find(row=>row.id===step.route);
  const transfer={item_id:'ITM-001',version:4,handler:'SHOP1',handler_name:'Sender One',handler_active:true,location:'Shop',location_id:null,operational_status:'queued',status_label:'Queued',can_transfer:![16,23,24].includes(number)};
  return {transfer,item:{id:'ITM-001',kind:step.route==='component'?'Part':step.route==='spool'?'Spool':'Assembly',description:'Test <item>',project:'P1',location:'Shop',handler:'SHOP1',released:[16,23,24].includes(number)},flow:{item_id:'ITM-001',route:step.route,current_step:number,current:structuredClone(step),version:7,status:'active',expected_children:step.route==='component'?0:1,step_entered_at:'2026-10-28T12:00:00Z',steps:catalog.steps.filter(x=>x.route===step.route).map(x=>({...x,status:x.number<number?'completed':x.number===number?'current':'pending'})),blockers:[],baseline_reference:'',baseline_reason:''},production_process:baseProcess(),components:[],spools:[],parent:null,events:[],exceptions:[],...extra};
}
let record=detailAt(6),allowedOverride=null,fail=null,hold=null,now=10000,timerId=0;
const calls=[],messages=[],timers=new Map();
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function allowed(){
  if(allowedOverride!==null)return allowedOverride;
  if(!record.flow)return ['admin','supervisor'].includes(context.me.role)?['start']:[];
  if(record.flow.status==='shipped')return ['deliver'];
  if(record.flow.status!=='active')return [];
  const actions=['pause'];if(record.flow.current.roles.includes(context.me.role)){actions.push('advance');if(record.flow.current.qa)actions.push('fail')}
  if(record.flow.route==='component')actions.push('assign-component');if(record.flow.route==='assembly'&&record.flow.current_step<=18)actions.push('link-spool');return actions;
}
function detail(){return {...structuredClone(record),allowed_actions:[...allowed()]}}
const context={document:{getElementById:id=>elements.get(id)||null},me:{role:'admin',badge:'ADMIN'},current:null,URL,URLSearchParams,Date,console,esc,
  performance:{now:()=>now},setInterval:fn=>{timers.set(++timerId,fn);return timerId},clearInterval:id=>timers.delete(id),
  history:{replaceState(_a,_b,url){context.url=url}},show(page){context.page=page},stopCloudCamera(){},notify:message=>messages.push(message),async openItem(id){context.openedItem=id},FabTracking:{async open(value){context.openedWelds=value}},FabParts:{async open(value){context.openedParts=value}},FabAdmin:{async open(value){context.openedAdmin=value}},
  qrId(value,kind){const text=String(value||'').trim();if(kind==='badge')return text.startsWith('FABTRACE:EMP:')?text.slice(13):text;try{return new URL(text).searchParams.get('item')||''}catch(_){}return text.startsWith('FABTRACE:ITEM:')?text.slice(14):/^[A-Za-z0-9_-]{3,60}$/.test(text)?text:''},
  FormData:class{constructor(form){this.values=Object.entries(form.values||{})}[Symbol.iterator](){return this.values[Symbol.iterator]()}},
  api:async(url,options={})=>{
    calls.push({url,...options});if(options.method){if(hold)await hold;if(fail)throw fail;return detail()}
    if(url==='/api/transfers/options')return structuredClone(handoffOptions);
    if(url==='/api/employees/directory')return [{badge:'SHOP1',name:'Sender One',role:'welder',active:true},{badge:'SHOP2',name:'Receiver Two',role:'handler',active:true},{badge:'OLD1',name:'Former worker',role:'handler',active:false}];
    if(url==='/api/flow/catalog')return structuredClone(catalog);
    if(url==='/api/flow/items')return {items:[{item_id:'ITM-001',description:'Test item',route:record.flow?.route||'component',status:record.flow?.status||'active',current_step:record.flow?.current_step||6,current_title:record.flow?.current?.title||'Prep',project_id:'P1',subproject_id:'SUB1',open_exceptions:record.exceptions?.filter(x=>!x.closed_at).length||0,blockers:[],production_process:baseProcess()},{item_id:'OTHER-002',description:'Other project item',route:'assembly',status:'delivered',current_step:null,current_title:'',project_id:'P2',subproject_id:null,open_exceptions:0,blockers:[],production_process:null}]};
    if(url.startsWith('/api/flow/items/'))return detail();throw Error('Unexpected endpoint '+url);
  },
};context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/handoff.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/flow.js'),'utf8'),context);
const html=()=>elements.get('flowContent').innerHTML,posts=()=>calls.filter(row=>row.method==='POST');
const click=(name,id='')=>elements.get('flowContent').listeners.click({target:{closest:()=>({disabled:false,dataset:{flowAction:name,flowId:id}})}});
const submitStep=async values=>{const form=elements.get('flowStepForm');assert.ok(form,'current-step form exists');form.values=values;await form.onsubmit({preventDefault(){},target:form})};
const submitDialog=async values=>{const form=elements.get('flowDialogForm');form.values=values;await form.listeners.submit({preventDefault(){},target:form})};
const check=number=>({['check_s'+number+'_1']:'on'});

(async()=>{
  await context.FabFlow.open();assert.equal(context.page,'flowPage');
  assert.match(html(),/24-step fabrication flow/);assert.equal((html().match(/class="ff-map-step /g)||[]).length,24);
  elements.get('flowProject').value='P1';elements.get('flowProject').onchange();assert.doesNotMatch(html(),/Other project item/);
  await click('filter-step','6');assert.match(html(),/Showing step 6/);await click('clear-step');
  elements.get('flowSubproject').value='SUB1';elements.get('flowSubproject').onchange();
  elements.get('flowStatus').value='delivered';elements.get('flowStatus').onchange();
  elements.get('flowSearch').value='unrelated search';elements.get('flowSearch').oninput();await click('filter-step','24');
  await context.FabFlow.open({project:'P2'});assert.match(html(),/value="unrelated search"/,'ordinary navigation preserves flow filters');
  await context.FabFlow.open({project:'P2',resetFilters:true});
  assert.match(html(),/Other project item/,'guide shortcut clears previous subproject, status, step and search');
  assert.doesNotMatch(html(),/Showing step 24|unrelated search/);assert.equal(elements.get('flowSubproject').value,'');assert.equal(elements.get('flowStatus').value,'');
  assert.match(context.url,/project=P2/);await context.FabFlow.open({project:'P1',resetFilters:true});
  await context.FabFlow.open({item:'ITM-001'});assert.match(context.url,/flow=1/);assert.match(context.url,/item=ITM-001/);
  assert.equal((html().match(/class="ff-route-step /g)||[]).length,8,'selected item only has its own route');
  assert.match(html(),/Test &lt;item&gt;/);assert.match(html(),/Receiving employee badge QR \/ ID/);assert.match(html(),/Destination location/);
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
  context.FabFlow.cancelPending();assert.equal(timers.size,0);
  const index=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
  assert.match(index,/params\.has\('flow'\)[\s\S]*FabFlow\.open/);assert.match(index,/id="itemFlowBtn"/);assert.match(index,/id="navFlow"/);assert.match(index,/FabFlow\.cancelPending/);
  assert.equal(index,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'));
  console.log('PASS: 24-step map, entity-specific routes, filters, QR/manual IDs, location/handoff payloads, catalog checks and roles, QA failure/reinspection, hierarchy links, child verification, shipment/delivery, documented baselines, clocks, duplicate writes, conflicts, and navigation.');
})().catch(error=>{console.error(error);process.exitCode=1});
