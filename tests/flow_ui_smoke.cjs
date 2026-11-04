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
const catalog={version:'CLM-24-v6',routes:[{id:'component',label:'Component',first_step:1,last_step:8},{id:'spool',label:'Spool',first_step:9,last_step:16},{id:'assembly',label:'Assembly',first_step:17,last_step:24}],steps:titles.map((title,index)=>{const n=index+1,qa=[2,11,15,18,22].includes(n);return {number:n,title,qa_code:({2:'QA-001',11:'QA-002',15:'QA-003',18:'QA-004',22:'QA-005'})[n]||null,route:n<9?'component':n<17?'spool':'assembly',section:'Fixture section',checks:[{id:'s'+n+'_1',label:'Verify physical item & records'}],roles:qa?['admin','inspector']:['admin','supervisor','handler'],requires_scan:[1,3,5,6,8,9,12,13,16,17,18,19,20,23,24].includes(n),requires_handoff:[6,8,9,12,13,16,19,20,23].includes(n),requires_location:[3,6,8,9,12,13,16,19,20,23].includes(n),requires_reference:[1,2,5,11,15,18,22].includes(n),qa,return_steps:({2:[2],11:[10],15:[14],18:[17,18],22:[17,18,19,20,21]})[n]||[]}})};
const legacyStages=[['inventory','Inventory',[1],'black'],['qa_001','QA/QC-001',[2,3,4],'black'],['preparation','Prep/Fabrication',[5,6,7,9,10],'red'],['qa_002','QA/QC-002',[11],'red'],['floor','Floor',[8,12,16,19],'yellow'],['welding','Process Welder',[13,14],'blue'],['qa_003','QA/QC-003',[15],'blue'],['testing','Testing',[17],'orange'],['qa_test_results','QA/QC-004',[18],'orange'],['paint','Paint',[20,21],'pink'],['qa_004','QA/QC-005',[22],'pink'],['ready_to_ship','Ready To Ship',[23,24],'green']].map(([key,label,steps,color])=>({key,label,steps,color,qa:key.startsWith('qa_')}));
catalog.stage_catalog=legacyStages;for(const step of catalog.steps)Object.assign(step,{catalog_version:catalog.version,is_shipment:step.number===24,is_ready_to_ship:step.number===23,flow_stage_key:legacyStages.find(stage=>stage.steps.includes(step.number)).key,display_qa_code:step.qa_code?.replace('QA-','QA/QC-')||null});
const modernCatalog=structuredClone(catalog);modernCatalog.version='CLM-25-v1';modernCatalog.routes.find(row=>row.id==='assembly').last_step=25;
modernCatalog.steps=[...catalog.steps.filter(step=>step.number<=22).map(step=>({...step})),{...catalog.steps[22],title:'Return to Floor',requires_reference:false,handoff_location_id:'floor',handoff_target_role:'handler'},{...catalog.steps[22],number:24,requires_reference:true,handoff_location_id:'ready_to_ship',handoff_target_role:'handler',checks:[{id:'s24_1',label:'Verify Ready to Ship handoff'}]},{...catalog.steps[23],number:25,checks:[{id:'s25_1',label:'Verify shipment record'}]}];
modernCatalog.steps[16].title='Determine if Spool Needs to Be Sent to Testing';Object.assign(modernCatalog.steps[21],{title:'QA/QC-006 - Final Inspection',qa_code:'QA-006',display_qa_code:'QA/QC-006',flow_stage_key:'qa_final'});modernCatalog.steps[22].flow_stage_key='floor';
for(const step of modernCatalog.steps)Object.assign(step,{catalog_version:modernCatalog.version,is_shipment:step.number===25,is_ready_to_ship:step.number===24});
modernCatalog.stage_catalog=legacyStages.filter(stage=>stage.key!=='qa_004').map(stage=>({...stage,steps:stage.key==='floor'?[8,12,16,19,23]:stage.key==='ready_to_ship'?[24,25]:stage.steps}));modernCatalog.stage_catalog.splice(9,0,{key:'qa_pressure_results',label:'QA/QC-005',steps:[18],color:'orange',qa:true});modernCatalog.stage_catalog.splice(11,0,{key:'qa_final',label:'QA/QC-006',steps:[22],color:'pink',qa:true});
const handoffOptions={locations:[{id:'welding',label:'Weld Bay 2',kind:'builtin',active:true,version:1},{id:'custom_rack',label:'Rack A',kind:'custom',active:true,version:1},{id:'testing',label:'Testing',kind:'builtin',active:true,version:1},{id:'qa_test_results',label:'QA/QC-004',kind:'builtin',active:true,version:1},{id:'qa_pressure_results',label:'QA/QC-005',kind:'builtin',active:true,version:1},{id:'ready_to_ship',label:'Ready To Ship',kind:'builtin',active:true,version:1},{id:'floor',label:'Floor',kind:'builtin',active:true,version:1}],statuses:[{id:'queued',label:'Queued'},{id:'in_progress',label:'In progress'}],keep_current_location_id:'current',can_manage_locations:true};
const baseProcess=()=>({item_id:'ITM-001',version:11,as_of:'2026-10-28T12:05:00Z',status:'running',current:{id:1,process_name:'Fixture step',started_at:'2026-10-28T12:00:00Z',elapsed_seconds:300,active_seconds:240,paused_seconds:60},totals:{elapsed_seconds:300,active_seconds:240,paused_seconds:60,visits:1},by_process:[{process_name:'Fixture step',visits:1,elapsed_seconds:300,active_seconds:240,paused_seconds:60}],events:[]});
function detailAt(number,extra={},source=catalog){
  const step=source.steps[number-1],r=source.routes.find(row=>row.id===step.route),modern=source.version==='CLM-25-v1';
  const transfer={item_id:'ITM-001',version:4,handler:'SHOP1',handler_name:'Sender One',handler_active:true,location:'Shop',location_id:null,operational_status:'queued',status_label:'Queued',can_transfer:![16,23,24].includes(number)};
  const identity=step.route==='spool'?{spool_number:'643-777-PCW-03-01',google_part_number:'643-777-PCW-03-01',qr_alias:'643-777-PCW-03-01-[001]',display_code:'643-777-PCW-03-01-[001]'}:{};
  return {stage_catalog:structuredClone(source.stage_catalog),flow_stage:{key:step.flow_stage_key,source_item_id:'ITM-001',inherited:false},transfer,item:{...identity,id:'ITM-001',kind:step.route==='component'?'Part':step.route==='spool'?'Spool':'Assembly',description:'Test <item>',project:'P1',location:'Shop',handler:'SHOP1',released:[16,23,24,25].includes(number)},flow:{item_id:'ITM-001',catalog_version:source.version,route_definition:structuredClone(r),ready_to_ship_step:modern?24:23,shipment_step:modern?25:24,route:step.route,current_step:number,current_display_step:modern?({18:19,19:20}[number]||number+(number>=20?4:0)):number,current:{...structuredClone(step),return_steps:step.qa?[({2:1,11:10,15:14,18:17,22:21})[number]]:[]},version:7,status:'active',expected_children:step.route==='component'?0:1,step_entered_at:'2026-10-28T12:00:00Z',steps:source.steps.filter(x=>x.route===step.route).map(x=>({...x,status:x.number<number?'completed':x.number===number?'current':'pending'})),blockers:[],baseline_reference:'',baseline_reason:''},production_process:baseProcess(),components:[],spools:[],parent:null,events:[],exceptions:[],...extra};
}
function testingAt(phase,action,extra={},source=catalog){
  const kind=phase.startsWith('pressure')||phase==='floor_before_paint'?'pressure':'ndt',qa=action==='review',work=action==='start'||action==='complete',number=qa?18:action==='handoff'?19:['complete','not_required'].includes(phase)?20:17;
  const d=detailAt(number,{},source),qaCode=kind==='pressure'&&source.version==='CLM-25-v1'?'QA/QC-005':'QA/QC-004',qaLocation=kind==='pressure'&&source.version==='CLM-25-v1'?'qa_pressure_results':'qa_test_results',tester=kind==='ndt'?'NDT1':'PRESS1',title=phase==='decision'?'Determine if Spool Needs to Be Sent to Testing':qa?qaCode+' - Verify '+(kind==='ndt'?'NDT':'Pressure Test')+' Results':action==='correct'?'Mandatory '+kind+' rework':(kind==='ndt'?'NDT':'Pressure Test')+' · '+action;
  const roles=qa?['admin','inspector']:work||action==='correct'?['admin',kind==='ndt'?'ndt':'pressure_testing_technician']:['admin','supervisor','handler'];
  d.flow.testing={protocol:'CLM-TEST-v1',phase,decision:phase==='decision'?null:phase==='not_required'?'NO':'YES',test_kind:kind,attempt:2,cycle:1,action:action||null,active:Boolean(action),requires_decision:phase==='decision',requires_result:action==='complete'||qa,requires_child_scans:phase==='decision',review_exception_ids:[],test_started_by:action==='complete'||qa?tester:null,return_to:{sender_badge:tester,sender_name:kind==='ndt'?'NDT <Technician>':'Pressure technician',location_id:'testing',location_label:'Testing & inspection bay'},report:qa||action==='handoff'?{test_kind:kind,attempt:2,cycle:1,result:'PASS',reference:'REPORT-002',notes:'Actual test evidence',actor:tester,at:'2026-10-28T12:00:00Z',event_id:42}:null,qa:action==='handoff'?{result:'PASS',reference:'QA-002',actor:'QA1',at:'2026-10-28T12:04:00Z'}:null,rework_required:action==='correct',...extra};
  d.flow.current={...d.flow.current,title,roles,qa,testing_phase:phase,testing_action:action,qa_code:qa?qaCode.replace('QA/QC-','QA-'):null,display_qa_code:qa?qaCode:null,qa_stage:qa?qaLocation:null,requires_scan:true,requires_reference:['complete','review','correct'].includes(action),requires_handoff:work||action==='handoff',requires_location:work||action==='handoff',requires_child_scans:phase==='decision',requires_resolution:action==='correct',return_steps:[],handoff_target_role:action==='start'?kind==='ndt'?'ndt':'pressure_testing_technician':action==='complete'?'inspector':action==='handoff'?'handler':null,handoff_location_id:action==='start'?'testing':action==='complete'?qaLocation:action==='handoff'?'floor':null,checks:[{id:'testing_'+phase+'_'+action+'_1',label:'Verify the physical testing phase'}]};
  if(source.version==='CLM-25-v1')d.flow.current_display_step=({decision:17,ndt:18,ndt_rework:18,ndt_qa:19,floor_before_pressure:20,pressure_test:21,pressure_rework:21,pressure_qa:22,floor_before_paint:23,complete:24,not_required:24})[phase];
  d.flow.steps=d.flow.steps.map(s=>s.number===number?{...d.flow.current,status:'current'}:s);
  if(phase==='not_required')d.flow.steps=d.flow.steps.map(s=>[18,19].includes(s.number)?{...s,status:'not_required'}:s);
  const handler=qa||action==='handoff'?'QA1':action==='complete'||action==='correct'?tester:'SHOP1';d.item.handler=handler;d.transfer={...d.transfer,handler,handler_name:handler,location:qa||action==='handoff'?qaCode:handler==='SHOP1'?'Floor':'Testing',location_id:qa||action==='handoff'?qaLocation:handler==='SHOP1'?'floor':'testing'};
  d.flow_stage={...d.flow_stage,key:qa||action==='handoff'?qaLocation:handler==='SHOP1'?'floor':'testing'};
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
    if(url==='/api/flow/catalog')return structuredClone(modernCatalog);
    if(url==='/api/flow/board')return {items:structuredClone(physicalCopies.length?physicalCopies:record.flow?.route==='spool'?[{...record.item,item_id:record.item.id,route:'spool',flow_stage:record.flow_stage,status:record.flow.status,current_step:record.flow.current_step,current_display_step:record.flow.current_display_step,catalog_version:record.flow.catalog_version,project_id:'P1',subproject_id:'SUB1'}]:[])};
    if(url==='/api/flow/items')return {items:[{item_id:'ITM-001',spool_number:record.item.spool_number,google_part_number:record.item.google_part_number,qr_alias:record.item.qr_alias,display_code:record.item.display_code,flow_stage:record.flow_stage,description:'Test item',route:record.flow?.route||'component',status:record.flow?.status||'active',current_step:record.flow?.current_step||6,current_display_step:record.flow?.current_display_step,catalog_version:record.flow?.catalog_version,current_title:record.flow?.current?.title||'Prep',project_id:'P1',subproject_id:'SUB1',open_exceptions:record.exceptions?.filter(x=>!x.closed_at).length||0,blockers:[],production_process:baseProcess()},{item_id:'OTHER-002',description:'Other project item',route:'assembly',status:'delivered',current_step:null,current_title:'',project_id:'P2',subproject_id:null,open_exceptions:0,blockers:[],production_process:null}]};
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
// The testing branches belong inside the actual chart. Balance nested DIVs
// rather than accepting a detached panel or stopping at a child closing tag.
function elementHtml(source,opening){
  const match=opening.exec(source);if(!match)return '';
  const tag=match[0].match(/^<([a-z][\w:-]*)\b/i)[1],tags=new RegExp('<\\/?'+tag+'\\b[^>]*>','gi');
  tags.lastIndex=match.index;let depth=0,next;
  while((next=tags.exec(source))){depth+=next[0].startsWith('</')?-1:1;if(depth===0)return source.slice(match.index,tags.lastIndex);}
  assert.fail('Unclosed '+tag+' element in chart output');
}
const routeHtml=()=>elementHtml(html(),/<div\b[^>]*\bclass="ff-route(?: [^"]*)?"[^>]*>/);
const mapHtml=(source=html())=>elementHtml(source,/<div\b[^>]*\bclass="ff-map(?: [^"]*)?"[^>]*>/);
const branchHtml=(source=routeHtml()||html())=>elementHtml(source,/<div\b[^>]*\bdata-testing-chart="inline"[^>]*>/);
const phaseNode=(key,source=branchHtml())=>elementHtml(source,new RegExp('<[a-z][\\w:-]*\\b[^>]*\\bdata-testing-node="'+key+'"[^>]*>'));
const stepTag=(number,source=routeHtml())=>source.match(new RegExp('<[a-z][\\w:-]*\\b[^>]*\\bdata-flow-chart-step="'+number+'"[^>]*>'))?.[0]||'';
const numberedSteps=source=>[...new Set([...source.matchAll(/\bdata-flow-chart-step="(\d+)"/g)].map(match=>Number(match[1])))].sort((a,b)=>a-b);
const chartCount=source=>(source.match(/\bdata-testing-chart="inline"/g)||[]).length;
const selectedMap=()=>html().split('View this traveler’s numbered route')[1]?.split('</details>')[0]||'';
function assertInlineBranch(source){
  const branch=branchHtml(source);assert.ok(branch,'testing branches are contained in the chart');assert.equal(chartCount(source),1,'one testing branch group belongs to this chart');
  const modern=/\bdata-testing-catalog="CLM-25-v1"/.test(branch),merge=modern?24:20;
  assert.match(branch,new RegExp('\\bdata-testing-merge-step="'+merge+'"'));assert.doesNotMatch(branch,new RegExp('\\bdata-flow-chart-step="'+merge+'"|\\bdata-testing-node="paint"'),'the branches rejoin the existing Paint destination without a duplicate card');
  assert.match(phaseNode('decision',branch),/\bdata-flow-chart-step="17"/);
  const phases=modern?[['ndt',18],['ndt_qa',19],['floor_before_pressure',20],['pressure_test',21],['pressure_qa',22],['floor_before_paint',23]]:[['ndt',17],['ndt_qa',18],['floor_before_pressure',19],['pressure_test',17],['pressure_qa',18],['floor_before_paint',19]];
  for(const [key,number] of phases){
    const node=phaseNode(key,branch);assert.ok(node,key+' is a chart node');assert.match(node,new RegExp('data-flow-chart-step="'+number+'"'));assert.match(node,/\bff-branch-node\b/);
    assert.match(node,new RegExp('class="ff-num(?: ff-link)?"[^>]*>'+number+'<'),'branch nodes use the displayed sequence for their saved catalog');
  }
  assert.equal((source.match(new RegExp('\\bdata-flow-chart-step="'+merge+'"','g'))||[]).length,1,'the normal Paint destination appears once');
  assert.ok(source.indexOf('data-testing-merge-step="'+merge+'"')<source.indexOf('data-flow-chart-step="'+merge+'"'),'testing paths rejoin before the Paint release');
}
function assertInlineMap(source=mapHtml()){
  const assembly=elementHtml(source,/<section\b[^>]*\bdata-phase="assembly"[^>]*>/);
  assert.ok(branchHtml(assembly),'the branch is nested in the existing testing section of the numbered map');assertInlineBranch(source);
}
function assertNoDetachedBranch(){
  assert.doesNotMatch(html(),/\bff-testing-branch\b/,'there is no standalone testing panel');
  assert.equal(chartCount(html()),chartCount(routeHtml())+chartCount(mapHtml()),'every testing group belongs to a numbered route or map');
}
function assertTestingNotRequired(){
  const branch=branchHtml(),yes=elementHtml(branch,/<div\b[^>]*\bdata-testing-branch="YES"[^>]*>/);
  assert.match(yes,/\bff-branch-skipped\b/);assert.match(yes,/Not required by the recorded NO/);
  for(const key of ['ndt_qa','pressure_qa','floor_before_pressure','floor_before_paint']){
    assert.doesNotMatch(phaseNode(key,branch),/aria-current="step"|class="[^"]*\bcompleted\b/,'NO does not claim a testing review or Floor-return pass');
  }
}
const catalogContracts=[];
async function catalogContract(name,run){await run();catalogContracts.push(name);}

(async()=>{
  await context.FabFlow.open();assert.equal(context.page,'flowPage');
  assert.match(html(),/29-step fabrication flow/);assert.deepEqual([...mapHtml().matchAll(/\bdata-flow-chart-step="(\d+)"/g)].map(match=>Number(match[1])),Array.from({length:29},(_,i)=>i+1),"the current map presents every step 1–29 once in order");assertInlineMap();assertNoDetachedBranch();
  assert.equal((html().match(/data-spool-process=/g)||[]).length,13);assert.match(html(),/Individual spools by process/);assert.match(html(),/data-flow-id="ITM-001">ITM-001<\/button>/);assert.doesNotMatch(html(),/fst-color-[^"]+"[^>]*>ITM-001<\/span>/);assert.match(html(),/QA\/QC-004/);
  for(const station of html().matchAll(/<(?:h3|span|strong)\b[^>]*data-station-stage="[^"]+"[^>]*>/g))assert.doesNotMatch(station[0],/fst-color-|fst-text/);
  assert.doesNotMatch(context.FabFlowStatus.strip(null,{key:'floor'}),/fst-color-|fst-text/);assert.doesNotMatch(context.FabFlowStatus.legend(),/class="fst-text/);
  const inventoryCopy=(id,suffix)=>({item_id:id,route:'spool',spool_number:'643-777-PCW-03-01',qr_alias:'643-777-PCW-03-01-['+suffix+']',flow_stage:{key:'inventory',label:'Inventory'},project_id:'INVENTORY-PROJECT',subproject_id:'RECEIVING',status:'not_started',current_step:null,purchase_order:'PO-INDIVIDUAL',assembly_number:'ASM-PLAN'});
  physicalCopies=[inventoryCopy('COPY-10','10'),inventoryCopy('COPY-2','2'),inventoryCopy('COPY-001','001'),{...inventoryCopy('COPY-WELD','011'),flow_stage:{key:'welding',label:'Process Welder'},project_id:'P1',subproject_id:'SUB1',status:'active',current_step:13}];
  await context.FabFlow.open({project:'',resetFilters:true});
  assert.deepEqual([...processBoard().matchAll(/data-spool-process="([^"]+)"/g)].map(m=>m[1]),modernCatalog.stage_catalog.map(stage=>stage.key));
  assert.deepEqual([...processGroup('inventory').matchAll(/data-process-spool="([^"]+)"/g)].map(m=>m[1]),['COPY-001','COPY-2','COPY-10']);
  assert.deepEqual([...processGroup('welding').matchAll(/data-process-spool="([^"]+)"/g)].map(m=>m[1]),['COPY-WELD']);
  assert.equal((processBoard().match(/data-flow-spool=/g)||[]).length,4);assert.doesNotMatch(processBoard(),/<details|data-flow-spool="ITM-001"/);
  assert.match(processGroup('inventory'),/data-spool-id="COPY-001" class="fst-text fst-color-black"[^>]*>643-777-PCW-03-01-\[001\]/);
  assert.match(html(),/<details class="ff-fold"><summary>Traveler records/);assert.match(html(),/<details class="ff-fold"><summary>The 29-step fabrication flow/);assert.match(html(),/<option value="INVENTORY-PROJECT"/);
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
  assert.deepEqual(numberedSteps(routeHtml()),[1,2,3,4,5,6,7,8],'selected item only has its own route');assert.match(html(),/<li data-flow-stage="preparation" class="fst-current" aria-current="step">/);
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
  await click('fail');assert.doesNotMatch(elements.get('flowDialogFields').innerHTML,/name="return_step"/);assert.match(elements.get('flowDialogFields').innerHTML,/Return for rework:[\s\S]*Step 10/);
  let failures=posts().length;await submitDialog({reason:'  ',reference:'NCR-007',return_step:'17'});assert.equal(posts().length,failures);assert.match(elements.get('flowDialogError').textContent,/Describe the defect/);await submitDialog({reason:'Alignment out of tolerance',reference:'NCR-007',return_step:'17'});
  assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,reason:'Alignment out of tolerance',reference:'NCR-007',return_step:10});
  assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/fail');

  record.exceptions=[{id:1,step:11,return_step:10,reason:'Bad <alignment>',reference:'NCR-007',opened_by:'QA<one>',opened_at:'2026-10-28T11:00:00Z',closed_at:null}];
  await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/QA\/QC reinspection findings/);assert.match(html(),/Bad &lt;alignment&gt;/);assert.match(html(),/Needs reinspection/);
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
  assert.deepEqual(numberedSteps(mapHtml()),[9,10,11,12,13,14,15,16],'selected map uses only the saved traveler definitions');
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
  assertTestingNotRequired();
  assert.match(html(),/Testing required: NO/);assert.match(branchHtml(),/Recorded choice: NO/);assert.doesNotMatch(html(),/name="testing_decision"|name="test_result"/);

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
  await submitStep({...qaFailure,location_id:'floor'});assert.equal(posts().length,testingWrites);assert.match(elements.get('flowStepError').textContent,/destination required by this step/);
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

  await catalogContract('testing branches are inside the route and numbered map, with saved decisions and distinct QA checkpoints',async()=>{
    context.me={role:'admin',badge:'ADMIN'};record=testingAt('decision','decision',{},modernCatalog);await context.FabFlow.open({item:'ITM-001'});
    assertInlineBranch(routeHtml());assertInlineMap(mapHtml(selectedMap()));assertNoDetachedBranch();assert.equal(chartCount(html()),2,'the route and saved map each contain their own inline branch');
    assert.deepEqual(numberedSteps(routeHtml()),[17,18,19,20,21,22,23,24,25,26,27,28,29]);
    assert.match(branchHtml(),/data-testing-catalog="CLM-25-v1"/);assert.match(branchHtml(),/No testing decision has been recorded/);
    assert.match(branchHtml(),/data-testing-branch="YES"/);assert.match(branchHtml(),/data-testing-branch="NO"/);
    assert.match(branchHtml(),/data-testing-node="ndt_qa"[^>]*>[\s\S]*?<strong>QA\/QC-004<\/strong>/);assert.match(branchHtml(),/data-testing-node="pressure_qa"[^>]*>[\s\S]*?<strong>QA\/QC-005<\/strong>/);
    assert.equal((branchHtml().match(/class="ff-branch-node/g)||[]).length,6);assert.equal((branchHtml().match(/aria-current="step"/g)||[]).length,1);
    for(const choice of ['YES','NO'])assert.equal(elements.get('ff-testing_decision-'+choice).checked,false);
    chooseTesting('testing_decision','YES');assert.match(branchHtml(),/No testing decision has been recorded/,'an unsaved radio choice does not claim a recorded route');assert.doesNotMatch(branchHtml(),/ff-branch-chosen|class="[^"]*completed/);
  });
  await catalogContract('only the actual active phase is highlighted, including exact rework custody',async()=>{
    const phases=[['ndt','start','ndt',18],['ndt_qa','review','ndt_qa',19],['floor_before_pressure','handoff','floor_before_pressure',20],['pressure_test','complete','pressure_test',21],['pressure_qa','review','pressure_qa',22],['floor_before_paint','handoff','floor_before_paint',23],['ndt_rework','correct','ndt',18],['pressure_rework','correct','pressure_test',21]];
    for(const [phase,action,node,displayStep] of phases){
      record=testingAt(phase,action,{},modernCatalog);await context.FabFlow.open({item:'ITM-001'});
      assert.equal((branchHtml().match(/aria-current="step"/g)||[]).length,1,phase);assert.match(phaseNode(node),/aria-current="step"/);assert.match(html(),new RegExp('Current step '+displayStep+' · Assembly route'));assert.match(phaseNode(node),new RegExp('data-flow-chart-step="'+displayStep+'"'));
      for(const key of phases.map(row=>row[2]))assert.doesNotMatch(phaseNode(key),/class="[^"]*\bcompleted\b/,'advancing to a phase does not invent a test approval');
      assertInlineBranch(routeHtml());assertInlineMap(mapHtml(selectedMap()));assertNoDetachedBranch();
      if(phase.endsWith('_rework')){assert.match(branchHtml(),/Required rework/);assert.match(branchHtml(),/Testing &amp; inspection bay/);assert.match(branchHtml(),phase==='ndt_rework'?/NDT &lt;Technician&gt; \(NDT1\)/:/Pressure technician \(PRESS1\)/);assert.match(branchHtml(),/fresh test and QA\/QC review/);}
    }
    record=detailAt(23,{},modernCatalog);record.flow.testing={...testingAt('pressure_qa','review',{},modernCatalog).flow.testing,active:false,action:null};await context.FabFlow.open({item:'ITM-001'});
    assert.doesNotMatch(branchHtml(),/aria-current="step"/);assert.doesNotMatch(html(),/name="test_result"|name="testing_decision"/);
    record=testingAt('not_required',null,{},modernCatalog);await context.FabFlow.open({item:'ITM-001'});
    assert.match(branchHtml(),/Recorded choice: NO/);assertTestingNotRequired();assert.doesNotMatch(branchHtml(),/aria-current="step"/);assert.match(stepTag(24),/aria-current="step"/,'the displayed step24 is the current Paint destination');
    assert.doesNotMatch(stepTag(27),/\bnot_required\b/,'NO cannot bypass the later shipment Floor handoff');assertInlineBranch(routeHtml());assertInlineMap(mapHtml(selectedMap()));assertNoDetachedBranch();
  });
  await catalogContract('legacy testing labels and route boundaries remain distinct from the current catalog',async()=>{
    record=testingAt('pressure_qa','review');await context.FabFlow.open({item:'ITM-001'});
    assert.match(branchHtml(),/data-testing-catalog="CLM-24-v6"/);assert.match(branchHtml(),/data-testing-node="pressure_qa"[^>]*>[\s\S]*?<strong>QA\/QC-004<\/strong>/);assert.doesNotMatch(branchHtml(),/QA\/QC-005|QA\/QC-006/);
    assert.deepEqual(numberedSteps(selectedMap()),[17,18,19,20,21,22,23,24]);assert.match(selectedMap(),/QA\/QC-005 - Final Inspection/);assert.match(selectedMap(),/Release to Ready to Ship/);assert.doesNotMatch(selectedMap(),/QA\/QC-006|class="ff-num">25</);assertInlineBranch(routeHtml());assertInlineMap(mapHtml(selectedMap()));assertNoDetachedBranch();
    record=detailAt(22,{},modernCatalog);record.flow.baseline_step=22;record.flow.steps=record.flow.steps.map(step=>step.number<22?{...step,status:'not_recorded'}:step);await context.FabFlow.open({item:'ITM-001'});
    assert.deepEqual(numberedSteps(selectedMap()),[17,18,19,20,21,22,23,24,25,26,27,28,29]);assert.match(selectedMap(),/QA\/QC-006 - Final Inspection/);assert.match(selectedMap(),/class="ff-num">29</);assert.match(html(),/Assembly route · steps 17–29/);assert.match(html(),/Current step 26 · Assembly route/);
    assertInlineBranch(routeHtml());assertInlineMap(mapHtml(selectedMap()));assertNoDetachedBranch();assert.match(phaseNode('decision'),/\bnot_recorded\b/);assert.doesNotMatch(branchHtml(),/aria-current="step"|ff-branch-chosen|class="[^"]*\bcompleted\b/,'a later current-catalog baseline does not invent a testing decision or approvals');
    record=detailAt(22);await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Assembly route · steps 17–24/);assert.match(html(),/QA\/QC-005 - Final Inspection/);assert.doesNotMatch(selectedMap(),/QA\/QC-006/);assert.equal(chartCount(html()),0,'a retained unphased traveler keeps its saved linear test route');assert.deepEqual(numberedSteps(selectedMap()),[17,18,19,20,21,22,23,24]);
  });
  await catalogContract('board filters distinguish current testing phases and retain separate legacy numbering',async()=>{
    const phases=[['NDT-WORK',17,18,'NDT'],['NDT-REVIEW',18,19,'QA/QC-004'],['NDT-FLOOR',19,20,'Return to Floor'],['PRESSURE-WORK',17,21,'Pressure Testing'],['PRESSURE-REVIEW',18,22,'QA/QC-005'],['PRESSURE-FLOOR',19,23,'Return to Floor'],['CURRENT-PAINT',20,24,'Release to Sandblast and Paint']];
    const rows=phases.map(([item_id,current_step,current_display_step,current_title])=>({item_id,catalog_version:'CLM-25-v1',route:'assembly',status:'active',current_step,current_display_step,current_title,project_id:'P1',subproject_id:'SUB1',open_exceptions:0,blockers:[],production_process:null})),before=posts().length;
    rows.push({...rows[0],item_id:'LEGACY-FLOOR',catalog_version:'CLM-24-v6',current_step:19,current_display_step:19,current_title:'Legacy Floor'}, {...rows[0],item_id:'LEGACY-SHIPMENT',catalog_version:'CLM-24-v6',current_step:24,current_display_step:24,current_title:'Legacy shipment'}, {...rows[0],item_id:'CURRENT-SPOOL-FLOOR',route:'spool',current_step:16,current_display_step:16,current_title:'Return to Floor'}, {...rows[0],item_id:'LEGACY-SPOOL-FLOOR',route:'spool',catalog_version:'CLM-24-v6',current_step:16,current_display_step:16,current_title:'Return to Floor'});
    readHook=url=>url==='/api/flow/items'?{items:structuredClone(rows)}:undefined;
    try{
      await context.FabFlow.open({project:'',resetFilters:true});assert.match(html(),/11 matching records/);assert.match(html(),/<strong>24 · Legacy shipment<\/strong>/);assert.match(html(),/<strong>19 · Legacy Floor<\/strong>/);
      assert.match(elementHtml(mapHtml(),/<li\b[^>]*\bdata-flow-chart-step="24"[^>]*>/),/1 record at this step/,'the current Paint count excludes the retained shipment');
      assert.match(elementHtml(mapHtml(),/<li\b[^>]*\bdata-flow-chart-step="16"[^>]*>/),/2 records at this step/,'the unchanged spool steps count both catalogs');
      for(const [itemId,_storedStep,displayStep,title] of phases){
        await click('filter-step',String(displayStep));assert.match(html(),new RegExp('Showing step '+displayStep+' · '));assert.match(html(),/1 matching records/);
        const table=elementHtml(html(),/<table\b[^>]*\bclass="ff-table"[^>]*>/);
        assert.match(table,new RegExp('data-flow-id="'+itemId+'"'));assert.ok(table.includes('<strong>'+displayStep+' · '+title+'</strong>'),'the row shows its displayed current phase');assert.doesNotMatch(table,/data-flow-id="LEGACY-(?:FLOOR|SHIPMENT)"/,'retained steps must not be mistaken for current catalog steps with the same number');
        for(const [otherId] of phases)if(otherId!==itemId)assert.doesNotMatch(table,new RegExp('data-flow-id="'+otherId+'"'),'a shared stored step must not combine different displayed testing phases');
      }
      await click('filter-step','16');assert.match(html(),/2 matching records/);assert.match(html(),/data-flow-id="CURRENT-SPOOL-FLOOR"/);assert.match(html(),/data-flow-id="LEGACY-SPOOL-FLOOR"/);
      assert.equal(posts().length,before,'display filters never submit traveler changes');
    }finally{readHook=null;}
  });
  await catalogContract('displayed step 27 keeps the stored step 23 fixed Floor handoff and payload',async()=>{
    record=detailAt(23,{},modernCatalog);await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Current step 27 · Assembly route/);assert.equal(elements.get('flowHandoffLocation').value,'floor');assert.doesNotMatch(html(),/name="carrier"|name="shipment_reference"|name="destination"/);
    const values={...currentChecks(),scanned_item_id:'ITM-001',sender_badge:'SHOP1',receiver_badge:'SHOP2',location_id:'floor',operational_status:'queued'},before=posts().length;
    await submitStep({...values,location_id:'welding'});assert.equal(posts().length,before);assert.match(elements.get('flowStepError').textContent,/destination required by this step/);
    await submitStep({...values,testing_decision:'NO',test_result:'PASS',carrier:'Ignored carrier'});assert.equal(posts().length,before+1);
    assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,confirmations:['s23_1'],notes:'',scanned_item_id:'ITM-001',sender_badge:'SHOP1',receiver_badge:'SHOP2',location_id:'floor',operational_status:'queued',expected_transfer_version:4});
    record=detailAt(23);await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Release to Ready to Ship/);assert.equal(elements.get('flowHandoffLocation').value,'current','the retained old step 23 is not constrained to the newly inserted Floor step');
  });
  await catalogContract('displayed step 28 keeps the stored step 24 Ready to Ship handoff and reference',async()=>{
    record=detailAt(24,{},modernCatalog);await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Current step 28 · Assembly route/);assert.equal(elements.get('flowHandoffLocation').value,'ready_to_ship');assert.doesNotMatch(html(),/name="carrier"|name="shipment_reference"|name="destination"/);
    const values={...currentChecks(),scanned_item_id:'ITM-001',sender_badge:'SHOP1',receiver_badge:'SHOP2',location_id:'ready_to_ship',operational_status:'queued',reference:'RELEASE-024'},before=posts().length;
    await submitStep({...values,location_id:'floor'});assert.equal(posts().length,before);assert.match(elements.get('flowStepError').textContent,/destination required by this step/);
    await submitStep({...values,reference:''});assert.equal(posts().length,before);assert.match(elements.get('flowStepError').textContent,/required record or inspection reference/);
    await submitStep(values);assert.equal(posts().length,before+1);assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,confirmations:['s24_1'],notes:'',scanned_item_id:'ITM-001',sender_badge:'SHOP1',receiver_badge:'SHOP2',location_id:'ready_to_ship',operational_status:'queued',expected_transfer_version:4,reference:'RELEASE-024'});
  });
  await catalogContract('displayed step 29 and retained step 24 keep their saved shipment payloads',async()=>{
    for(const [number,source] of [[25,modernCatalog],[24,catalog]]){
      record=detailAt(number,{},source);if(number===24){delete record.flow.shipment_step;delete record.flow.catalog_version;delete record.flow.current.is_shipment;}
      await context.FabFlow.open({item:'ITM-001'});assert.match(html(),new RegExp('Current step '+(source===modernCatalog?29:24)+' · Assembly route'));assert.match(html(),/Record shipment/);assert.match(html(),/name="carrier"/);assert.doesNotMatch(html(),/id="flowHandoffReceiver"/);
      const before=posts().length;await submitStep({...currentChecks(),scanned_item_id:'ITM-001'});assert.equal(posts().length,before);assert.match(elements.get('flowStepError').textContent,/carrier, shipping reference, and destination/);
      await submitStep({...currentChecks(),scanned_item_id:'ITM-001',carrier:'Exact carrier',shipment_reference:'BOL-'+number,destination:'Customer yard'});
      assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7,confirmations:['s'+number+'_1'],notes:'',scanned_item_id:'ITM-001',carrier:'Exact carrier',shipment_reference:'BOL-'+number,destination:'Customer yard'});
    }
  });
  await catalogContract('new pressure reports go to QA/QC-005 without changing saved testing action fields',async()=>{
    record=testingAt('pressure_test','complete',{},modernCatalog);context.me={role:'pressure_testing_technician',badge:'PRESS1'};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Current step 21 · Assembly route/);assert.equal(record.flow.current_step,17);assert.equal(elements.get('flowHandoffLocation').value,'qa_pressure_results');chooseTesting('test_result','PASS');
    const values={...currentChecks(),test_result:'PASS',scanned_item_id:'ITM-001',reference:'PRESSURE-NEW-REPORT',sender_badge:'PRESS1',receiver_badge:'QA1',location_id:'qa_pressure_results',operational_status:'queued'},before=posts().length;
    await submitStep({...values,location_id:'qa_test_results'});assert.equal(posts().length,before);assert.match(elements.get('flowStepError').textContent,/destination required by this step/);
    await submitStep(values);const body=JSON.parse(posts().at(-1).body);assert.equal(body.location_id,'qa_pressure_results');assert.equal(body.testing_phase,'pressure_test');assert.equal(body.testing_action,'complete');assert.equal(body.testing_attempt,2);assert.equal(body.test_result,'PASS');assert.equal(body.catalog_version,undefined);
    record=testingAt('pressure_qa','review',{},modernCatalog);context.me={role:'inspector',badge:'QA1'};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/QA\/QC-005 · Pressure test result/);assert.match(html(),/data-station-stage="qa_pressure_results"/);
  });
  await catalogContract('exception headings and event history use the saved failure definitions',async()=>{
    record=testingAt('ndt_qa','review',{pending_exception_ids:[901],review_exception_ids:[]},modernCatalog);record.exceptions=[{...carriedPressure},{...carriedPressure,id:902,reason:'Older phase detail unavailable'}];
    record.events=[{action:'fail',step:18,actor:'QA1',at:'2026-10-28T11:00:00Z',data:{exception_id:901,definition_version:'CLM-25-v1',step_definition:{title:'QA/QC-005 - Pressure result <saved>',display_qa_code:'QA/QC-005'},testing_protocol:'CLM-TEST-v1',testing_phase:'pressure_qa',testing_action:'review',testing_attempt:2,test_result:'FAIL'}},{action:'advance',step:22,actor:'QA1',at:'2026-10-27T11:00:00Z',data:{definition_version:'CLM-24-v6',step_definition:{title:'QA/QC-005 - Final Inspection (retained)'}}},{action:'shipment',step:24,actor:'SHOP1',at:'2026-10-27T12:00:00Z',data:{definition_version:'CLM-24-v6',step_definition:{title:'Ship to Customer (retained step 24)'}}}];
    const before=posts().length;await context.FabFlow.open({item:'ITM-001'});
    assert.match(html(),/<article class="ff-exception "><strong>Step 18 · QA\/QC-005 - Pressure result &lt;saved&gt;<\/strong>/);assert.match(html(),/Step 18 · QA\/QC test-result review/);assert.match(html(),/class="ff-recorded-step">QA\/QC-005 - Final Inspection \(retained\)/);assert.match(html(),/class="ff-recorded-step">Ship to Customer \(retained step 24\)/);assert.match(html(),/QA\/QC-005 · Pressure test result · Attempt 2/);assert.doesNotMatch(html(),/Pressure result <saved>/);assert.equal(posts().length,before);
  });
  await catalogContract('shared stage displays honor supplied catalogs, labels, colors and legacy final QA identity',async()=>{
    const status=context.FabFlowStatus,legacyCopy=JSON.stringify(legacyStages),modernCopy=JSON.stringify(modernCatalog.stage_catalog),before=posts().length;
    const legacyStrip=status.strip(legacyStages,{key:'qa_004',label:'Historic <Final> & QA',inherited:false});
    assert.equal((legacyStrip.match(/<li data-flow-stage=/g)||[]).length,12);assert.match(legacyStrip,/Historic &lt;Final&gt; &amp; QA/);assert.doesNotMatch(legacyStrip,/data-flow-stage="qa_pressure_results"|data-flow-stage="qa_final"|<Final>/);
    const currentStrip=status.strip(modernCatalog.stage_catalog,{key:'qa_pressure_results',label:'Pressure acceptance <005>'});assert.equal((currentStrip.match(/<li data-flow-stage=/g)||[]).length,13);assert.match(currentStrip,/Pressure acceptance &lt;005&gt;/);assert.match(currentStrip,/data-flow-stage="qa_pressure_results" class="fst-current"/);
    const rows=[{item_id:'OLD-001',spool_number:'0001',flow_stage:{key:'qa_004',label:'Historic final QA/QC-005'}},{item_id:'PRESS-001',spool_number:'0002',flow_stage:{key:'qa_pressure_results',label:'Pressure QA/QC-005',color:'orange'}},{item_id:'FINAL-001',spool_number:'0003',flow_stage:{key:'qa_final',label:'Final QA/QC-006',color:'pink'}}],rowCopy=JSON.stringify(rows),board=status.processBoard(rows,{catalog:modernCatalog.stage_catalog});
    for(const key of ['qa_004','qa_pressure_results','qa_final'])assert.match(board,new RegExp('data-spool-process="'+key+'"'));
    assert.match(board,/fst-color-pink" data-flow-stage="qa_004"/);assert.match(board,/fst-color-orange" data-flow-stage="qa_pressure_results"/);assert.match(board,/fst-color-pink" data-flow-stage="qa_final"/);
    assert.match(board,/>Historic final QA\/QC-005<\/h3>/);assert.match(board,/>Pressure QA\/QC-005<\/h3>/);assert.match(board,/>Final QA\/QC-006<\/h3>/);
    const unsafe={key:'qa_pressure_results',label:'Pressure <img src=x> & "review"',color:'pink" onmouseover="bad'},safeBadge=status.badge(unsafe),safeText=status.spoolText({item_id:'P-001',spool_number:'00001',flow_stage:unsafe});
    assert.match(safeBadge,/Pressure &lt;img src=x&gt; &amp; &quot;review&quot;/);assert.doesNotMatch(safeBadge,/<img src=x>/);assert.match(safeText,/fst-color-orange/);assert.doesNotMatch(safeText,/onmouseover/);
    const specificCatalog=[{key:'qa_pressure_results',label:'Server pressure review',color:'orange',qa:true},{key:'floor',label:'Production <Floor>',color:'yellow'}],specificBoard=status.processBoard([{item_id:'P-001',spool_number:'00001',flow_stage:{key:'qa_pressure_results'}}],{catalog:specificCatalog});
    assert.ok(specificBoard.indexOf('data-spool-process="qa_pressure_results"')<specificBoard.indexOf('data-spool-process="floor"'));assert.match(specificBoard,/>Server pressure review<\/h3>/);assert.match(specificBoard,/Production &lt;Floor&gt;/);assert.match(status.legend(specificCatalog),/Production &lt;Floor&gt;/);
    const mixedLabels=status.processBoard([{item_id:'P-A',flow_stage:{key:'qa_test_results',label:'Saved NDT station A'}},{item_id:'P-B',flow_stage:{key:'qa_test_results',label:'Saved test station B'}}],{catalog:modernCatalog.stage_catalog});assert.match(mixedLabels,/Recorded station: Saved NDT station A/);assert.match(mixedLabels,/Recorded station: Saved test station B/);
    assert.equal(JSON.stringify(legacyStages),legacyCopy);assert.equal(JSON.stringify(modernCatalog.stage_catalog),modernCopy);assert.equal(JSON.stringify(rows),rowCopy);assert.equal(posts().length,before);
  });
  await catalogContract('new assembly starts require the decision or a documented later baseline, never an unrecorded test phase',async()=>{
    context.me={role:'admin',badge:'ADMIN'};record=detailAt(17,{},modernCatalog);record.flow=null;record.suggested_route='assembly';await context.FabFlow.open({item:'ITM-001'});assertInlineMap();assertNoDetachedBranch();assert.equal(chartCount(html()),1,'an unstarted record shows the testing decision only inside its full fabrication map');await click('start');
    const options=elements.get('flowDialogFields').innerHTML.match(/<select[^>]+name="start_step"[^>]*>([\s\S]*?)<\/select>/)?.[1]||'';
    assert.match(options,/value="17"/);assert.match(options,/value="20"[^>]*>24 · Release to Sandblast and Paint/);assert.match(options,/value="25"[^>]*>29 · Ship to Customer/);assert.doesNotMatch(options,/value="18"|value="19"/);
    const before=posts().length;for(const step of [18,19]){await submitDialog({route:'assembly',expected_children:'1',start_step:String(step)});assert.equal(posts().length,before);assert.match(elements.get('flowDialogError').textContent,/Start at Step 17/);}
    await submitDialog({route:'assembly',expected_children:'1',start_step:'20'});assert.equal(posts().length,before);assert.match(elements.get('flowDialogError').textContent,/existing-work reference/);
    await submitDialog({route:'assembly',expected_children:'1',start_step:'20',baseline_reference:'APPROVED-EXISTING-20',baseline_reason:'Documented fabrication and tests predate this traveler',notes:'Existing work'});
    assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/start');assert.deepEqual(JSON.parse(posts().at(-1).body),{route:'assembly',expected_children:1,start_step:20,notes:'Existing work',baseline_reference:'APPROVED-EXISTING-20',baseline_reason:'Documented fabrication and tests predate this traveler'});
  });
  await catalogContract('completed child routes retain their own steps while showing an inherited new pressure station',async()=>{
    record=detailAt(16);Object.assign(record.flow,{current:null,current_step:null,status:'completed'});record.flow.steps=record.flow.steps.map(step=>({...step,status:'completed'}));record.parent={item_id:'ASM-NEW-25',route:'assembly'};record.flow_stage={key:'qa_pressure_results',label:'QA/QC-005 · Pressure review',inherited:true,source_item_id:'ASM-NEW-25'};
    const before=posts().length;await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/data-flow-action="item" data-flow-id="ASM-NEW-25">Open assembly process/);assert.match(html(),/data-flow-stage="qa_pressure_results" class="fst-current"/);assert.match(html(),/following ASM-NEW-25 at QA\/QC-005 · Pressure review/);assert.deepEqual(numberedSteps(selectedMap()),[9,10,11,12,13,14,15,16]);assert.doesNotMatch(html(),/ff-chart-testing|ff-testing-branch|id="flowStepForm"/);assert.equal(posts().length,before);
  });
  context.FabFlow.cancelPending();assert.equal(readTimeouts.size,0);assert.equal(timers.size,0);
  // QA review visibility is separate from ordinary production work and administrator oversight.
  for(const role of ['handler','fitup_welder','process_welder','ndt','pressure_testing_technician','painter','supervisor']){
    record=detailAt(11);record.flow.blockers=['Inspection awaits recorded production correction'];context.me={role,badge:'WORKER'};
    await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/ff-position-work|ff-checklist|id="flowStepForm"|data-flow-action="fail"/);
    assert.match(html(),/QA\/QC completes the inspection checklist/);assert.match(html(),/Inspection awaits recorded production correction/);
  }
  record=detailAt(11);context.me={role:'admin',badge:'ADMIN'};await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/id="flowStepForm"/);assert.doesNotMatch(html(),/ff-position-work/);assert.match(html(),/data-flow-action="admin-controls"/);
  for(const [phase,code,display] of [['ndt_qa','QA/QC-004',19],['pressure_qa','QA/QC-005',22]]){
    record=testingAt(phase,'review',{},modernCatalog);context.me={role:'inspector',badge:'QA1'};await context.FabFlow.open({item:'ITM-001'});
    const panel=elementHtml(html(),/<section class="card ff-position-work">/);assert.ok(panel.includes(display+' · '+code));assert.doesNotMatch(panel,/Determine if Spool|Sandblast &amp; Paint/);
  }


  // NDT and pressure reviews share a stored step ID, but remain distinct QA tasks.
  const qaTaskPanel=()=>elementHtml(html(),/<section class="card ff-position-work">/);
  const qaTaskRow=key=>elementHtml(qaTaskPanel(),new RegExp('<li\\b[^>]*\\bdata-qa-review="'+key+'"[^>]*>'));
  const signedQaReview=(phase,result,{cycle=1,attempt=2,id=phase==='ndt_qa'?501:502,actor=phase==='ndt_qa'?'NDT-QA':'PRESSURE-QA',at=phase==='ndt_qa'?'2026-11-04T10:10:00Z':'2026-11-04T10:20:00Z'}={})=>({
    id,action:result==='PASS'?'advance':'fail',step:18,actor,at,reference:'SIGNED-'+phase+'-'+cycle+'-'+attempt,
    data:{testing_protocol:'CLM-TEST-v1',testing_phase:phase,testing_action:'review',test_kind:phase==='ndt_qa'?'ndt':'pressure',testing_cycle:cycle,testing_attempt:attempt,test_result:result,
      ...(result==='FAIL'?{exception_id:id+1000}:{}),
      step_definition:{number:18,title:(phase==='ndt_qa'?'QA/QC-004 - Verify NDT Results':'QA/QC-005 - Verify Pressure Test Results'),qa:true,qa_code:phase==='ndt_qa'?'QA-004':'QA-005',display_qa_code:phase==='ndt_qa'?'QA/QC-004':'QA/QC-005',testing_phase:phase,checks:[{id:'testing_'+phase+'_review_1',label:'Verify the physical testing phase'}]}}
  });
  const ndtTaskPass=signedQaReview('ndt_qa','PASS'),pressureTaskPass=signedQaReview('pressure_qa','PASS');
  const assertQaTasks=(ndtStatus,pressureStatus)=>{
    const panel=qaTaskPanel();assert.ok(panel,'QA reviewers have a hold-point task list');
    assert.deepEqual([...panel.matchAll(/<li\b[^>]*\bdata-qa-review="([^"]+)"/g)].map(match=>match[1]),['ndt_qa','pressure_qa','QA-006'],'both test reviews and final QA remain visible in sequence');
    assert.match(panel,/QA\/QC hold points on this assembly \(3\)/);
    for(const [key,number,code,status] of [['ndt_qa',19,'004',ndtStatus],['pressure_qa',22,'005',pressureStatus]]){
      const row=qaTaskRow(key);assert.match(row,new RegExp(number+' · QA/QC-'+code),'review labels retain their own display step');
      assert.match(row,new RegExp('<span class="ff-tag '+status+'">'),'each review retains its own status');
    }
    assert.match(qaTaskRow('QA-006'),/26 · QA\/QC-006/);
  };
  const taskReadWrites=posts().length;
  await catalogContract('QA task list keeps NDT, pressure and final reviews visible across every testing phase',async()=>{
    const states=[
      ['decision','decision',[], 'pending','pending'],
      ['ndt','start',[], 'pending','pending'],
      ['ndt_qa','review',[], 'current','pending'],
      ['floor_before_pressure','handoff',[ndtTaskPass], 'completed','pending'],
      ['pressure_test','start',[ndtTaskPass], 'completed','pending'],
      ['pressure_qa','review',[ndtTaskPass], 'completed','current'],
      ['floor_before_paint','handoff',[ndtTaskPass,pressureTaskPass], 'completed','completed'],
      ['complete',null,[ndtTaskPass,pressureTaskPass], 'completed','completed'],
    ];
    for(const [phase,action,events,ndtStatus,pressureStatus] of states){
      record=testingAt(phase,action,{},modernCatalog);record.events=structuredClone(events);context.me={role:'inspector',badge:'QA1'};
      await context.FabFlow.open({item:'ITM-001'});assertQaTasks(ndtStatus,pressureStatus);
      if(events.length)assert.match(qaTaskRow('ndt_qa'),/Last recorded by NDT-QA/,'accepted NDT evidence stays visible after the pressure phase starts');
      if(pressureStatus==='completed')assert.match(qaTaskRow('pressure_qa'),/Last recorded by PRESSURE-QA/);
    }
  });
  await catalogContract('QA tasks require signed review evidence instead of technician reports or combined-step completion',async()=>{
    record=testingAt('pressure_qa','review',{},modernCatalog);
    record.flow.steps=record.flow.steps.map(step=>step.number===18?{...step,status:'completed',last_actor:'COMBINED-STEP',completed_at:'2026-11-04T10:00:00Z'}:step);
    record.events=[{...structuredClone(ndtTaskPass),data:{...ndtTaskPass.data,testing_phase:'ndt',testing_action:'complete'}}];
    await context.FabFlow.open({item:'ITM-001'});assertQaTasks('pending','current');
    assert.doesNotMatch(qaTaskRow('ndt_qa'),/Last recorded by (NDT-QA|COMBINED-STEP)/,'a test report or reused step status cannot invent QA acceptance');
  });
  await catalogContract('each failed testing review keeps its own reinspection status during correction and retesting',async()=>{
    const ndtFailure=signedQaReview('ndt_qa','FAIL'),pressureFailure=signedQaReview('pressure_qa','FAIL');
    for(const [phase,action,events,ndtStatus,pressureStatus] of [
      ['ndt_rework','correct',[ndtFailure],'rework','pending'],
      ['ndt','start',[ndtFailure],'rework','pending'],
      ['pressure_rework','correct',[ndtTaskPass,pressureFailure],'completed','rework'],
      ['pressure_test','start',[ndtTaskPass,pressureFailure],'completed','rework'],
    ]){
      record=testingAt(phase,action,{attempt:3},modernCatalog);record.events=structuredClone(events);
      await context.FabFlow.open({item:'ITM-001'});assertQaTasks(ndtStatus,pressureStatus);
      assert.match(qaTaskRow(phase.startsWith('ndt')?'ndt_qa':'pressure_qa'),/Needs reinspection/);
    }
  });
  await catalogContract('fresh QA reinspection is current and its own later PASS replaces the earlier failure',async()=>{
    const pressureFailure=signedQaReview('pressure_qa','FAIL'),pressureRetestPass=signedQaReview('pressure_qa','PASS',{attempt:3,id:503,actor:'REINSPECT-QA',at:'2026-11-04T10:30:00Z'});
    record=testingAt('pressure_qa','review',{attempt:3},modernCatalog);record.events=[structuredClone(ndtTaskPass),pressureFailure];
    await context.FabFlow.open({item:'ITM-001'});assertQaTasks('completed','current');
    assert.doesNotMatch(qaTaskRow('pressure_qa'),/<span class="ff-tag (completed|rework)">/,'the new active inspection cannot be mistaken for its earlier disposition');
    record=testingAt('floor_before_paint','handoff',{attempt:3},modernCatalog);record.events=[structuredClone(ndtTaskPass),pressureFailure,pressureRetestPass];
    await context.FabFlow.open({item:'ITM-001'});assertQaTasks('completed','completed');assert.match(qaTaskRow('pressure_qa'),/Last recorded by REINSPECT-QA/);
  });
  await catalogContract('a restarted test cycle cannot reuse either QA PASS from the prior cycle',async()=>{
    record=testingAt('decision','decision',{cycle:2,attempt:1,decision:'YES'},modernCatalog);record.events=[structuredClone(ndtTaskPass),structuredClone(pressureTaskPass)];
    await context.FabFlow.open({item:'ITM-001'});assertQaTasks('pending','pending');assert.doesNotMatch(qaTaskPanel(),/Last recorded by (NDT-QA|PRESSURE-QA)/);
    record=testingAt('ndt_qa','review',{cycle:2,attempt:1},modernCatalog);record.events=[structuredClone(ndtTaskPass),structuredClone(pressureTaskPass)];
    await context.FabFlow.open({item:'ITM-001'});assertQaTasks('current','pending');
    record=testingAt('pressure_qa','review',{cycle:2,attempt:1},modernCatalog);record.events=[structuredClone(ndtTaskPass),structuredClone(pressureTaskPass),signedQaReview('ndt_qa','PASS',{cycle:2,attempt:1,id:504,actor:'CYCLE-TWO-QA',at:'2026-11-04T11:00:00Z'})];
    await context.FabFlow.open({item:'ITM-001'});assertQaTasks('completed','current');assert.match(qaTaskRow('ndt_qa'),/Last recorded by CYCLE-TWO-QA/);assert.doesNotMatch(qaTaskRow('pressure_qa'),/Last recorded by PRESSURE-QA/);
  });
  await catalogContract('testing NO keeps both review rows marked Not required while retaining final QA',async()=>{
    record=testingAt('not_required',null,{},modernCatalog);await context.FabFlow.open({item:'ITM-001'});assertQaTasks('not_required','not_required');
    assert.match(qaTaskRow('ndt_qa'),/>Not required<\/span>/);assert.match(qaTaskRow('pressure_qa'),/>Not required<\/span>/);assert.match(qaTaskRow('QA-006'),/<span class="ff-tag pending">/);
  });
  await catalogContract('retained combined testing and component or spool QA scopes are not expanded',async()=>{
    record=detailAt(18);await context.FabFlow.open({item:'ITM-001'});
    assert.match(qaTaskPanel(),/QA\/QC hold points on this assembly \(2\)/);assert.match(qaTaskPanel(),/QA\/QC-004 - Verify Test Results/);assert.match(qaTaskPanel(),/QA\/QC-005 - Final Inspection/);assert.doesNotMatch(qaTaskPanel(),/data-qa-review="(?:ndt_qa|pressure_qa)"|QA\/QC-006/);
    record=detailAt(2,{},modernCatalog);await context.FabFlow.open({item:'ITM-001'});assert.match(qaTaskPanel(),/QA\/QC hold points on this component \(1\)/);assert.match(qaTaskPanel(),/QA\/QC-001/);assert.doesNotMatch(qaTaskPanel(),/QA\/QC-00[2-6]/);
    record=detailAt(11,{},modernCatalog);await context.FabFlow.open({item:'ITM-001'});assert.match(qaTaskPanel(),/QA\/QC hold points on this spool \(2\)/);assert.match(qaTaskPanel(),/QA\/QC-002/);assert.match(qaTaskPanel(),/QA\/QC-003/);assert.doesNotMatch(qaTaskPanel(),/QA\/QC-00[1456]/);
  });
  await catalogContract('modern late baselines retain both unrecorded test reviews without inventing testing history',async()=>{
    for(const baseline of [20,22]){
      record=detailAt(baseline,{},modernCatalog);record.flow.baseline_step=baseline;
      record.flow.steps=record.flow.steps.map(step=>step.number<baseline?{...step,status:'not_recorded',last_actor:null,completed_at:null}:step);
      assert.equal(record.flow.testing,undefined,'late adopted routes have no explicit testing state');
      await context.FabFlow.open({item:'ITM-001'});assertQaTasks('not_recorded','not_recorded');
      assert.match(qaTaskRow('QA-006'),new RegExp('<span class="ff-tag '+(baseline===22?'current':'pending')+'">'));
      assert.doesNotMatch(qaTaskRow('ndt_qa')+qaTaskRow('pressure_qa'),/Latest recorded review:|Last recorded by|<span class="ff-tag completed">/);
    }
    // Even a generic combined-step status cannot establish two distinct approvals.
    record.flow.steps=record.flow.steps.map(step=>step.number===18?{...step,status:'completed',last_actor:'COMBINED-QA',completed_at:'2026-11-04T09:00:00Z'}:step);
    await context.FabFlow.open({item:'ITM-001'});assertQaTasks('not_recorded','not_recorded');assert.doesNotMatch(qaTaskRow('ndt_qa')+qaTaskRow('pressure_qa'),/COMBINED-QA/);
  });
  await catalogContract('open failures carried into a new cycle retain only their matching phase reinspection requirement',async()=>{
    for(const phase of ['ndt_qa','pressure_qa']){
      const failure=signedQaReview(phase,'FAIL'),exceptionId=failure.data.exception_id;
      const finding={id:exceptionId,step:18,return_step:17,reason:'Carried '+phase+' failure requires fresh acceptance',reference:failure.reference,opened_by:failure.actor,opened_at:failure.at,closed_at:null};
      const priorEvents=phase==='pressure_qa'?[structuredClone(ndtTaskPass),failure]:[failure];
      record=testingAt('decision','decision',{cycle:2,attempt:1,decision:'YES',pending_exception_ids:[exceptionId],review_exception_ids:[]},modernCatalog);record.events=structuredClone(priorEvents);record.exceptions=[structuredClone(finding)];
      await context.FabFlow.open({item:'ITM-001'});assertQaTasks(phase==='ndt_qa'?'rework':'pending',phase==='pressure_qa'?'rework':'pending');
      assert.match(qaTaskRow(phase),/Needs reinspection/);assert.doesNotMatch(qaTaskPanel(),/<span class="ff-tag completed">/,'prior-cycle acceptance is not reused while the carried defect stays open');
      const newNdtPass=signedQaReview('ndt_qa','PASS',{cycle:2,attempt:1,id:505,actor:'NEW-CYCLE-NDT-QA',at:'2026-11-04T11:00:00Z'});
      const reviewEvents=phase==='pressure_qa'?[...structuredClone(priorEvents),newNdtPass]:structuredClone(priorEvents);
      record=testingAt(phase,'review',{cycle:2,attempt:1,pending_exception_ids:[exceptionId],review_exception_ids:[exceptionId]},modernCatalog);record.events=reviewEvents;record.exceptions=[structuredClone(finding)];
      await context.FabFlow.open({item:'ITM-001'});assertQaTasks(phase==='ndt_qa'?'current':'completed',phase==='pressure_qa'?'current':'pending');
      const freshPass=signedQaReview(phase,'PASS',{cycle:2,attempt:1,id:506,actor:'FRESH-ACCEPTANCE-QA',at:'2026-11-04T11:10:00Z'});
      record=testingAt(phase==='ndt_qa'?'floor_before_pressure':'floor_before_paint','handoff',{cycle:2,attempt:1,pending_exception_ids:[],review_exception_ids:[]},modernCatalog);record.events=[...reviewEvents,freshPass];record.exceptions=[{...finding,closed_at:freshPass.at}];
      await context.FabFlow.open({item:'ITM-001'});assertQaTasks('completed',phase==='pressure_qa'?'completed':'pending');assert.match(qaTaskRow(phase),/Last recorded by FRESH-ACCEPTANCE-QA/);
    }
  });

  // Spool fit-up and weld reviews travel with their physical spool into related views.
  const spoolReviewRow=(source,code)=>elementHtml(source,new RegExp('<[a-z][\\w:-]*\\b[^>]*\\bdata-qa-review="'+code+'"[^>]*>'));
  const linkedQaPanel=()=>elementHtml(html(),/<section\b[^>]*\bclass="[^"]*\bff-linked-qa\b[^"]*"[^>]*>/);
  const linkedQaSpool=id=>elementHtml(linkedQaPanel(),new RegExp('<[a-z][\\w:-]*\\b[^>]*\\bdata-qa-spool="'+id+'"[^>]*>'));
  const spoolQaSummary=()=>elementHtml(html(),/<section\b[^>]*\bclass="[^"]*\bff-spool-qa-summary\b[^"]*"[^>]*>/);
  const spoolQaResult=(number,result,extra={})=>({result,actor:'SPOOL-QA-'+number,at:'2026-11-04T11:'+String(number).padStart(2,'0')+':00Z',reference:'SPOOL-INSPECTION-'+number,notes:'Verified the physical spool and controlled records',event_id:800+number,...extra});
  const spoolQaRow=(number,extra={})=>({
    ...structuredClone(modernCatalog.steps[number-1]),review_key:number===11?'QA-002':'QA-003',number,qa:true,
    checks:(number===11?['Check spool fit-up and alignment','Check spool lengths, angles and dimensions']:['Check each weld visual examination record','Check approved WPS and release evidence']).map((label,index)=>({id:'s'+number+'_'+(index+1),label})),
    status:'pending',is_current:false,latest_review:null,defects:[],completed_at:null,last_actor:null,...extra,
  });
  const spoolQaGroup=(id,alias,reviews,extra={})=>({
    item_id:id,spool_number:'643-777-PCW-03-01',qr_alias:alias,description:'Individual spool '+id,
    catalog_version:modernCatalog.version,flow_stage:{key:'qa_002',source_item_id:id,inherited:false},removed:false,
    has_flow:true,route_status:'active',current_step:11,reviews:structuredClone(reviews),...extra,
  });
  const fitupPass=spoolQaResult(11,'PASS',{actor:'FITUP-QA <one>',reference:'FITUP-REPORT <signed> & checked'});
  const weldFailure=spoolQaResult(15,'FAIL',{actor:'WELD-QA <two>',reference:'WELD-NCR-15'});
  const weldFinding={id:915,step:15,display_step:15,return_step:14,return_display_step:14,reason:'Undersized <weld> & incomplete cap',reference:'WELD-NCR-15',opened_by:weldFailure.actor,opened_at:weldFailure.at,needs_completion:true,completion:null};
  const weldCorrection={event_id:916,step:14,actor:'PROCESS-WELDER',at:'2026-11-04T12:00:00Z',description:'Rebuilt <cap> & checked the weld profile',reference:'WELD-REPAIR-916'};
  await catalogContract('spool QA002 and QA003 show their own signed results, references and inspection tasks',async()=>{
    record=detailAt(14,{},modernCatalog);record.qa_reviews=[
      spoolQaRow(11,{status:'completed',latest_review:structuredClone(fitupPass),last_actor:fitupPass.actor,completed_at:fitupPass.at}),
      spoolQaRow(15,{status:'rework',latest_review:structuredClone(weldFailure),defects:[structuredClone(weldFinding)]}),
    ];record.spool_reviews=[];context.me={role:'inspector',badge:'QA1'};
    await context.FabFlow.open({item:'ITM-001'});
    const panel=qaTaskPanel(),fitup=spoolReviewRow(panel,'QA-002'),weld=spoolReviewRow(panel,'QA-003');
    assert.match(fitup,/11 · QA\/QC-002/);assert.match(weld,/15 · QA\/QC-003/);
    assert.match(fitup,/<span class="ff-tag completed">/);assert.match(weld,/<span class="ff-tag rework">/);
    assert.match(fitup,/Latest recorded review: <strong>PASS<\/strong>/);assert.match(weld,/Latest recorded review: <strong>FAIL<\/strong>/);
    assert.match(fitup,/FITUP-QA &lt;one&gt;/);assert.match(fitup,/FITUP-REPORT &lt;signed&gt; &amp; checked/);assert.ok(fitup.includes(esc(new Date(fitupPass.at).toLocaleString())));
    assert.match(weld,/WELD-QA &lt;two&gt;/);assert.match(weld,/WELD-NCR-15/);assert.match(weld,/Undersized &lt;weld&gt; &amp; incomplete cap/);
    assert.match(fitup,/Check spool fit-up and alignment/);assert.match(weld,/Check each weld visual examination record/);
    assert.doesNotMatch(fitup,/WELD-NCR-15|Undersized/);assert.doesNotMatch(weld,/FITUP-REPORT/,'one checkpoint cannot inherit the other inspection reference');
    assert.doesNotMatch(panel,/<one>|<two>|<signed>|<weld>/,'free-text review evidence is escaped');
  });
  await catalogContract('ordinary spool reinspection preserves failures and corrective work without crediting stale downstream acceptance',async()=>{
    const fitupFailure=spoolQaResult(11,'FAIL',{reference:'FITUP-NCR-11'}),oldWeldPass=spoolQaResult(15,'PASS',{actor:'OLDER-WELD-QA',reference:'PREVIOUS-WELD-PASS'});
    const fitupFinding={...structuredClone(weldFinding),id:911,step:11,display_step:11,return_step:10,return_display_step:10,reason:'Fit-up alignment must be corrected',reference:fitupFailure.reference,opened_by:fitupFailure.actor,opened_at:fitupFailure.at};
    record=detailAt(10,{},modernCatalog);record.qa_reviews=[
      spoolQaRow(11,{status:'rework',latest_review:fitupFailure,defects:[fitupFinding]}),
      spoolQaRow(15,{status:'pending',latest_review:oldWeldPass}),
    ];await context.FabFlow.open({item:'ITM-001'});
    assert.match(qaTaskRow('QA-002'),/<span class="ff-tag rework">/);assert.match(qaTaskRow('QA-003'),/<span class="ff-tag pending">/);
    assert.match(qaTaskRow('QA-003'),/PREVIOUS-WELD-PASS/);assert.doesNotMatch(qaTaskRow('QA-003'),/<span class="ff-tag completed">/,'a historical PASS is not current acceptance after a return');
    record=detailAt(15,{},modernCatalog);record.qa_reviews=[
      spoolQaRow(11,{status:'completed',latest_review:structuredClone(fitupPass)}),
      spoolQaRow(15,{status:'current',is_current:true,latest_review:structuredClone(weldFailure),defects:[{...structuredClone(weldFinding),needs_completion:false,completion:structuredClone(weldCorrection)}]}),
    ];await context.FabFlow.open({item:'ITM-001'});
    const active=qaTaskRow('QA-003');assert.match(active,/<span class="ff-tag current">/);assert.match(active,/Latest recorded review: <strong>FAIL<\/strong>/);
    assert.match(active,/Undersized &lt;weld&gt; &amp; incomplete cap/);assert.match(active,/Rebuilt &lt;cap&gt; &amp; checked the weld profile/);assert.match(active,/PROCESS-WELDER/);assert.match(active,/WELD-REPAIR-916/);
    assert.doesNotMatch(active,/<span class="ff-tag completed">/);assert.match(html(),/id="flowStepForm"/,'the current spool inspection retains its normal controlled form');
    const freshPass=spoolQaResult(15,'PASS',{actor:'REINSPECT-WELD-QA',reference:'WELD-REINSPECT-PASS',at:'2026-11-04T12:15:00Z',event_id:917});
    record=detailAt(16,{},modernCatalog);record.qa_reviews=[spoolQaRow(11,{status:'completed',latest_review:structuredClone(fitupPass)}),spoolQaRow(15,{status:'completed',latest_review:freshPass,completed_at:freshPass.at,last_actor:freshPass.actor})];
    await context.FabFlow.open({item:'ITM-001'});assert.match(qaTaskRow('QA-003'),/<span class="ff-tag completed">/);assert.match(qaTaskRow('QA-003'),/WELD-REINSPECT-PASS/);assert.doesNotMatch(qaTaskRow('QA-003'),/WELD-NCR-15/);
  });
  await catalogContract('unstarted and late-baseline spools expose planned QA002 and QA003 without inventing acceptance',async()=>{
    record=detailAt(9,{},modernCatalog);record.flow=null;record.suggested_route='spool';record.qa_reviews=[spoolQaRow(11),spoolQaRow(15)];record.spool_reviews=[];
    await context.FabFlow.open({item:'ITM-001'});
    for(const code of ['QA-002','QA-003']){assert.ok(qaTaskRow(code),'planned spool review remains visible before route setup');assert.match(qaTaskRow(code),/<span class="ff-tag pending">/);}
    assert.doesNotMatch(qaTaskPanel(),/Latest recorded review:|Last recorded by|<span class="ff-tag completed">/);assert.doesNotMatch(html(),/id="flowStepForm"/,'unstarted work cannot receive a QA approval from the summary');
    record=detailAt(16,{},modernCatalog);record.flow.baseline_step=16;record.qa_reviews=[spoolQaRow(11,{status:'not_recorded'}),spoolQaRow(15,{status:'not_recorded'})];
    // The old aggregate route rows may say completed, but carry no signed QA evidence.
    record.flow.steps=record.flow.steps.map(step=>({...step,status:'completed',last_actor:'BASELINE-ACTOR',completed_at:'2026-11-04T08:00:00Z'}));
    await context.FabFlow.open({item:'ITM-001'});
    for(const code of ['QA-002','QA-003'])assert.match(qaTaskRow(code),/<span class="ff-tag not_recorded">/);
    assert.doesNotMatch(qaTaskPanel(),/Latest recorded review:|BASELINE-ACTOR|<span class="ff-tag completed">/);
  });
  const relatedSpoolA=spoolQaGroup('SPL-REVIEW-A','643-777-PCW-03-01-[001]',[spoolQaRow(11,{status:'current',is_current:true}),spoolQaRow(15)]);
  const relatedSpoolB=spoolQaGroup('SPL-REVIEW-B','643-777-PCW-03-01-[002]',[
    spoolQaRow(11,{status:'completed',latest_review:spoolQaResult(11,'PASS',{actor:'SPOOL-B-QA2',reference:'SPOOL-B-FITUP-PASS'})}),
    spoolQaRow(15,{status:'rework',latest_review:spoolQaResult(15,'FAIL',{actor:'SPOOL-B-QA3',reference:'SPOOL-B-WELD-FAIL'}),defects:[{...structuredClone(weldFinding),reason:'Spool B weld repair is required',reference:'SPOOL-B-WELD-FAIL'}]}),
  ],{current_step:14,flow_stage:{key:'welding',source_item_id:'SPL-REVIEW-B',inherited:false}});
  const assemblyWithSpoolReviews=()=>{const value=testingAt('decision','decision',{},modernCatalog);value.qa_reviews=[];value.spool_reviews=[structuredClone(relatedSpoolA),structuredClone(relatedSpoolB)];value.spools=value.spool_reviews.map(group=>({...group,route:'spool',status:group.route_status}));return value;};
  await catalogContract('assembly view keeps each linked spool QA002 and QA003 separate with direct review links',async()=>{
    record=assemblyWithSpoolReviews();context.me={role:'inspector',badge:'QA1'};const beforeRead=calls.length;
    await context.FabFlow.open({item:'ITM-001',project:'P1',resetFilters:true});const panel=linkedQaPanel();
    assert.ok(panel,'assembly includes the linked spool review section');assert.deepEqual([...panel.matchAll(/\bdata-qa-spool="([^"]+)"/g)].map(match=>match[1]),['SPL-REVIEW-A','SPL-REVIEW-B']);
    const first=linkedQaSpool('SPL-REVIEW-A'),second=linkedQaSpool('SPL-REVIEW-B');
    for(const [id,source] of [['SPL-REVIEW-A',first],['SPL-REVIEW-B',second]]){
      assert.match(source,new RegExp('data-flow-action="item" data-flow-id="'+id+'"[^>]*>Open spool review<'));
      assert.match(spoolReviewRow(source,'QA-002'),/11 · QA\/QC-002/);assert.match(spoolReviewRow(source,'QA-003'),/15 · QA\/QC-003/);
      assert.match(source,/Check spool fit-up and alignment/);assert.match(source,/Check each weld visual examination record/);
      assert.doesNotMatch(source,/id="flowStepForm"|id="flowAdvance"|data-flow-action="fail"/,'linked cards do not approve another physical spool');
    }
    assert.match(first,/643-777-PCW-03-01-\[001\]/);assert.match(second,/643-777-PCW-03-01-\[002\]/);
    assert.match(spoolReviewRow(first,'QA-002'),/<span class="ff-tag current">/);assert.match(spoolReviewRow(first,'QA-003'),/<span class="ff-tag pending">/);
    assert.match(spoolReviewRow(second,'QA-002'),/<span class="ff-tag completed">/);assert.match(spoolReviewRow(second,'QA-003'),/<span class="ff-tag rework">/);
    assert.match(second,/SPOOL-B-FITUP-PASS/);assert.match(second,/SPOOL-B-WELD-FAIL/);assert.match(second,/Spool B weld repair is required/);assert.doesNotMatch(first,/SPOOL-B-|Spool B weld repair/,'another spool cannot supply this spool’s results');
    assertQaTasks('pending','pending','linked spool reviews do not displace the assembly’s own QA gates');
    assert.deepEqual(calls.slice(beforeRead).filter(call=>call.url.startsWith('/api/flow/items/')).map(call=>call.url),['/api/flow/items/ITM-001'],'linked summaries arrive in the current response without per-spool fetches');
  });
  await catalogContract('assigned-spool reviews remain visible from receiving and unstarted linked spools stay unapproved',async()=>{
    record=detailAt(2,{},modernCatalog);record.qa_reviews=[];record.parent={item_id:'SPL-REVIEW-A',route:'spool'};
    record.spool_reviews=[spoolQaGroup('SPL-REVIEW-A','643-777-PCW-03-01-[001]',[spoolQaRow(11,{status:'not_recorded'}),spoolQaRow(15,{status:'not_recorded'})],{has_flow:false,route_status:'not_started',current_step:null})];
    await context.FabFlow.open({item:'ITM-001'});const linked=linkedQaSpool('SPL-REVIEW-A');assert.ok(linked,'receiving retains the next spool reviews alongside its own QA001');
    assert.match(qaTaskPanel(),/QA\/QC-001/);assert.match(linked,/QA\/QC-002/);assert.match(linked,/QA\/QC-003/);
    for(const code of ['QA-002','QA-003'])assert.match(spoolReviewRow(linked,code),/<span class="ff-tag not_recorded">/);
    assert.doesNotMatch(linked,/Latest recorded review:|Last recorded by|<span class="ff-tag completed">|id="flowStepForm"/);
  });
  await catalogContract('QA task checklists stay inspector-only while other positions can read spool inspection summaries',async()=>{
    for(const role of ['admin','handler','process_welder']){
      context.me={role,badge:role==='admin'?'ADMIN':'WORKER'};
      record=detailAt(11,{},modernCatalog);record.qa_reviews=[spoolQaRow(11,{status:'current',is_current:true,latest_review:structuredClone(fitupPass)}),spoolQaRow(15)];record.spool_reviews=[];
      await context.FabFlow.open({item:'ITM-001'});const summary=spoolQaSummary();assert.ok(summary,role+' can see recorded spool QA status');
      assert.doesNotMatch(html(),/ff-position-work|QA\/QC review tasks/);assert.match(summary,/QA\/QC-002/);assert.match(summary,/QA\/QC-003/);assert.match(summary,/FITUP-REPORT &lt;signed&gt; &amp; checked/);
      assert.doesNotMatch(summary,/Check spool fit-up and alignment|Check each weld visual examination record|name="check_|id="flowStepForm"/,'a summary does not assign QA checklist tasks to another position');
      if(role==='admin')assert.match(html(),/id="flowStepForm"/,'the permitted administrator current inspection form is preserved');
      else assert.doesNotMatch(html(),/id="flowStepForm"/,'ordinary trades cannot perform the current QA review');
      record=assemblyWithSpoolReviews();await context.FabFlow.open({item:'ITM-001'});
      assert.match(linkedQaPanel(),/SPOOL-B-WELD-FAIL/);assert.doesNotMatch(linkedQaPanel(),/Check spool fit-up and alignment|Check each weld visual examination record|name="check_|id="flowStepForm"/);
      assert.doesNotMatch(html(),/ff-position-work/);
    }
    context.me={role:'inspector',badge:'QA1'};
  });
  await catalogContract('opening a linked spool review reads that physical spool and preserves context without QA writes',async()=>{
    record=assemblyWithSpoolReviews();context.me={role:'inspector',badge:'QA1'};await context.FabFlow.open({item:'ITM-001',project:'P1',resetFilters:true});
    assert.match(linkedQaSpool('SPL-REVIEW-B'),/data-flow-action="item" data-flow-id="SPL-REVIEW-B"[^>]*>Open spool review</);
    const child=detailAt(14,{},modernCatalog);Object.assign(child.item,{id:'SPL-REVIEW-B',qr_alias:relatedSpoolB.qr_alias});child.flow.item_id='SPL-REVIEW-B';child.transfer.item_id='SPL-REVIEW-B';child.production_process.item_id='SPL-REVIEW-B';child.qa_reviews=structuredClone(relatedSpoolB.reviews);child.spool_reviews=[];record=child;
    const beforeRead=calls.length,beforeWrite=posts().length;await click('item','SPL-REVIEW-B');
    assert.deepEqual(calls.slice(beforeRead).filter(call=>call.url.startsWith('/api/flow/items/')).map(call=>call.url),['/api/flow/items/SPL-REVIEW-B']);
    const url=new URL(context.url,context.location.origin);assert.equal(url.searchParams.get('item'),'SPL-REVIEW-B');assert.equal(url.searchParams.get('project'),'P1');
    assert.match(qaTaskPanel(),/SPOOL-B-WELD-FAIL/);assert.match(qaTaskPanel(),/Spool B weld repair is required/);assert.equal(posts().length,beforeWrite,'opening another spool is read-only');
  });
  assert.equal(posts().length,taskReadWrites,'review-list projections never create QA records or mutate the live workflow');

  // Every ordinary QA failure returns to the one server-selected preceding production step.
  context.me={role:'inspector',badge:'QA1'};
  for(const [qaStep,productionStep] of [[2,1],[11,10],[15,14],[18,17],[22,21]]){
    record=detailAt(qaStep,{},modernCatalog);await context.FabFlow.open({item:'ITM-001'});await click('fail');
    const fields=elements.get('flowDialogFields').innerHTML;assert.doesNotMatch(fields,/name="return_step"|<select/);assert.ok(fields.includes('Step '+(productionStep>=20?productionStep+4:productionStep)));
    await submitDialog({reason:'Recorded defect requiring correction',reference:'NCR-FIXED-'+qaStep,return_step:'2'});
    assert.equal(JSON.parse(posts().at(-1).body).return_step,productionStep);assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/fail');
  }
  record=detailAt(22);record.flow.current.return_steps=[17,21];await context.FabFlow.open({item:'ITM-001'});elements.get('flowDialog').close();const invalidReturnWrites=posts().length;await click('fail');assert.equal(elements.get('flowDialog').open,false);assert.equal(posts().length,invalidReturnWrites);assert.match(messages.at(-1),/production return step could not be verified/);

  const defect={id:990,step:11,display_step:11,return_step:10,return_display_step:10,reason:'Misaligned <fit-up> & damaged edge',reference:'NCR-990',opened_by:'QA1',opened_at:'2026-11-04T09:00:00Z',needs_completion:true,completion:null};
  const rework={source_item_id:'ITM-001',inherited:false,current_step:10,required_step:10,required_display_step:10,responsible_roles:['fitup_welder','admin'],needs_completion:true,requires_return:false,defects:[defect]};
  record=detailAt(10);record.rework=structuredClone(rework);record.exceptions=[structuredClone(defect)];record.flow.current.roles=['fitup_welder','admin'];record.flow.current.requires_resolution=true;record.flow.current.requires_rework=true;context.me={role:'fitup_welder',badge:'FIT1'};
  await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/ff-position-work/);assert.match(html(),/id="flowStepForm"/);assert.match(html(),/Completed rework and corrective action/);assert.match(html(),/id="ff-field-resolution"[^>]+minlength="4"/);
  assert.match(html(),/Misaligned &lt;fit-up&gt; &amp; damaged edge/);assert.doesNotMatch(html(),/<fit-up>/);assert.match(html(),/Completed rework has not been recorded/);assert.ok(html().indexOf('ff-rework-card')<html().indexOf('ff-current"'),'workers see the defect before their completion form');
  let reworkWrites=posts().length;await submitStep({...currentChecks(),resolution:'   '});assert.equal(posts().length,reworkWrites);assert.match(elements.get('flowStepError').textContent,/completed rework/);
  await submitStep({...currentChecks(),resolution:'abc'});assert.equal(posts().length,reworkWrites);
  await submitStep({...currentChecks(),resolution:'Realigned fit-up and replaced the damaged edge',notes:'Drawing verified'});let reworkBody=JSON.parse(posts().at(-1).body);assert.equal(reworkBody.resolution,'Realigned fit-up and replaced the damaged edge');assert.equal(reworkBody.reworked_exception_ids,undefined,'the server determines which defects this work satisfies');

  const completion={event_id:991,step:10,actor:'FIT1',at:'2026-11-04T10:00:00Z',description:'Replaced <edge> & checked alignment',reference:'WORK-991'};
  record=detailAt(11);record.exceptions=[structuredClone(defect)];record.rework={...structuredClone(rework),current_step:11,needs_completion:false,defects:[{...structuredClone(defect),needs_completion:false,completion}]};record.events=[{action:'advance',step:10,actor:'FIT1',at:completion.at,reference:completion.reference,data:{reworked_exception_ids:[990],resolution:completion.description}}];context.me={role:'inspector',badge:'QA1'};
  await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Recorded completed rework/);assert.match(html(),/Replaced &lt;edge&gt; &amp; checked alignment/);assert.match(html(),/Completed by<\/dt><dd>FIT1/);assert.match(html(),/WORK-991/);assert.match(html(),/QA\/QC reinspection findings/);assert.match(html(),/Completed rework recorded/);assert.doesNotMatch(html(),/Completed rework has not been recorded/);
  reworkWrites=posts().length;await submitStep({...currentChecks(),reference:'QA-REINSPECT-991'});assert.equal(posts().length,reworkWrites);assert.match(elements.get('flowStepError').textContent,/reinspection findings/);
  await submitStep({...currentChecks(),reference:'QA-REINSPECT-991',resolution:'Corrected alignment verified against drawing'});assert.equal(JSON.parse(posts().at(-1).body).resolution,'Corrected alignment verified against drawing');

  // An older open QA failure with no worker correction requires the controlled return first.
  record=detailAt(11);record.exceptions=[structuredClone(defect)];record.rework={...structuredClone(rework),current_step:11,requires_return:true};record.flow.blockers=['Record completed production rework before QA/QC PASS'];allowedOverride=['advance','fail','return-for-rework'];
  await context.FabFlow.open({item:'ITM-001'});assert.equal(elements.get('flowAdvance').disabled,true);assert.match(html(),/data-flow-action="return-for-rework"/);
  reworkWrites=posts().length;await submitStep({...currentChecks(),reference:'QA-BLOCKED',resolution:'QA text cannot replace completed production work'});assert.equal(posts().length,reworkWrites);assert.match(elements.get('flowStepError').textContent,/QA\/QC PASS is blocked/);
  await click('return-for-rework');assert.equal(posts().at(-1).url,'/api/flow/items/ITM-001/return-for-rework');assert.deepEqual(JSON.parse(posts().at(-1).body),{expected_version:7});
  allowedOverride=[];await context.FabFlow.open({item:'ITM-001'});assert.doesNotMatch(html(),/data-flow-action="return-for-rework"/);reworkWrites=posts().length;await click('return-for-rework');assert.equal(posts().length,reworkWrites);allowedOverride=null;

  // Completed child spools show assembly defects without acquiring assembly work controls.
  record=detailAt(16);Object.assign(record.flow,{current:null,current_step:null,status:'completed'});record.flow.steps=record.flow.steps.map(step=>({...step,status:'completed'}));record.parent={item_id:'ASM-DEFECT',route:'assembly'};record.flow_stage={key:'paint',inherited:true,source_item_id:'ASM-DEFECT'};
  record.rework={...structuredClone(rework),source_item_id:'ASM-DEFECT',inherited:true,current_step:21,required_step:21,required_display_step:25,responsible_roles:['painter','admin'],defects:[{...structuredClone(defect),step:22,display_step:26,return_step:21,return_display_step:25,reason:'Assembly coating <defect>'}]};context.me={role:'painter',badge:'PAINT1'};
  reworkWrites=posts().length;await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Assembly coating &lt;defect&gt;/);assert.match(html(),/QA\/QC finding · step 26/);assert.match(html(),/Required production step<\/dt><dd>25/);assert.match(html(),/data-flow-action="item" data-flow-id="ASM-DEFECT">Open parent assembly/);assert.doesNotMatch(html(),/id="flowStepForm"|data-flow-action="return-for-rework"|ff-position-work/);await click('return-for-rework');assert.equal(posts().length,reworkWrites);
  record.flow=null;record.suggested_route='spool';await context.FabFlow.open({item:'ITM-001'});assert.match(html(),/Assembly coating &lt;defect&gt;/,'an inherited defect remains visible without a local numbered traveler');assert.equal(posts().length,reworkWrites);
  context.FabFlow.cancelPending();assert.equal(readTimeouts.size,0);assert.equal(timers.size,0);
  console.log('PASS: QA/QC-only review summaries; preserved trade and admin forms; dynamic NDT/pressure hold points; fixed preceding-step FAIL routing; mandatory recorded worker corrections; blocked QA PASS and permitted legacy rework return; inherited assembly defects are read-only on child spools.');
  // QA item review and current production requirements remain after removal of the separate work overview.
  const taskWrites=posts().length;
  readHook=null;record=detailAt(11);context.me={role:'inspector',badge:'QA1',name:'QA <Employee>'};
  record.work={pending:true,for_position:true,in_custody:false,custodian_badge:'HANDLER1',responsible_roles:['inspector'],required_employee_badge:null,can_record:true,restriction:'',requirements:['Verify <drawing> & dimensions','Record the inspection reference']};
  await context.FabFlow.open({item:'ITM-001',project:'P1',resetFilters:true});
  assert.match(html(),/QA\/QC review tasks/);assert.match(html(),/QA &lt;Employee&gt;/);
  const qaPanel=elementHtml(html(),/<section class="card ff-position-work">/);assert.match(qaPanel,/QA\/QC hold points on this spool \(2\)/);assert.doesNotMatch(qaPanel,/Complete Welds|Fit-Up &amp; Tack Weld/);
  assert.match(html(),/Verify &lt;drawing&gt; &amp; dimensions/);assert.doesNotMatch(html(),/<drawing>/);assert.match(html(),/id="flowStepForm"/);
  assert.ok(html().indexOf('ff-position-work')>=0&&html().indexOf('ff-position-work')<html().indexOf('ff-route-step'));
  assert.ok(html().indexOf('ff-current"')<html().indexOf('ff-route-step'),'spool requirements and current actions remain before the route diagram');

  record=testingAt('ndt','complete',{},modernCatalog);context.me={role:'ndt',badge:'NDT1',name:'Assigned tester'};
  record.work={pending:true,for_position:true,in_custody:false,custodian_badge:'OTHER-EMPLOYEE',responsible_roles:['admin','ndt'],required_employee_badge:'NDT1',can_record:false,restriction:'Restore the recorded testing custodian before submitting its report.',requirements:['Record the actual NDT report reference']};
  await context.FabFlow.open({item:'ITM-001',project:'P1',view:'work',workScope:'custody',workPage:2});
  assert.doesNotMatch(html(),/ff-position-work|QA\/QC review tasks|Your tasks/);assert.match(html(),/Restore the recorded testing custodian/);assert.doesNotMatch(html(),/id="flowStepForm"/);
  assert.ok(html().indexOf('ff-current"')<html().indexOf('ff-route-step'),'assembly requirements and current actions remain before the route diagram');
  assert.doesNotMatch(html(),/My work|data-flow-action="my-work"|id="flowWorkScope"|data-work-item=/);
  const itemUrl=new URL(context.url,context.location.origin);
  assert.equal(itemUrl.searchParams.get('item'),'ITM-001');assert.equal(itemUrl.searchParams.get('project'),'P1');assert.equal(itemUrl.searchParams.get('view'),null);assert.equal(itemUrl.searchParams.get('work_scope'),null);
  for(const key of ['view','workScope','workPage'])assert.equal(Object.hasOwn(context.FabFlow.navigationState(),key),false,'removed overview state is not retained');

  record=detailAt(11);const boardReads=calls.length;
  await context.FabFlow.open({view:'work',workScope:'position',workPage:5,project:'P1',resetFilters:true});
  assert.match(html(),/Fabrication process flow/);assert.doesNotMatch(html(),/My work|data-flow-action="my-work"|id="flowWorkScope"|data-work-item=|work requirements could not be verified/);
  assert.equal(calls.slice(boardReads).filter(call=>call.url==='/api/flow/items').length,1);
  assert.equal(calls.slice(boardReads).filter(call=>call.url==='/api/flow/board').length,1,'former work options load the ordinary physical process board');
  assert.ok(!calls.slice(boardReads).some(call=>call.url.startsWith('/api/flow/items/')),'overview still avoids per-item fan-out');
  const boardUrl=new URL(context.url,context.location.origin);
  assert.equal(boardUrl.searchParams.get('flow'),'1');assert.equal(boardUrl.searchParams.get('project'),'P1');assert.equal(boardUrl.searchParams.get('item'),null);assert.equal(boardUrl.searchParams.get('view'),null);assert.equal(boardUrl.searchParams.get('work_scope'),null);
  context.me={role:'admin',badge:'ADMIN'};context.FabFlow.cancelPending();
  assert.equal(posts().length,taskWrites);assert.equal(readTimeouts.size,0);assert.equal(timers.size,0);
  console.log('PASS: My work overview and shortcuts are absent; former work options open ordinary Process flow; QA/QC review tasks and current production actions stay before the chart, escape record text, preserve item/project and respect exact testing-employee restrictions without writes.');
  const index=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
  assert.match(index,/params\.has\('flow'\)[\s\S]*FabFlow\.open/);assert.match(index,/id="itemFlowBtn"/);assert.match(index,/id="navFlow"/);assert.doesNotMatch(index,/navMyWork/);assert.match(index,/FabFlow\.cancelPending/);
  assert.equal(index,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'));
  console.log('PASS: neutral station labels, colored physical spool numbers, escaped unknown-station notices, retained blocked Ready To Ship, current 29-step map and retained traveler maps, entity-specific routes, filters, QR/manual IDs, location/handoff payloads, catalog checks and roles, QA failure/reinspection, hierarchy links, child verification, shipment/delivery, documented baselines, clocks, duplicate writes, conflicts, focused record reads, cancellation, bounded loading, navigation, required YES/NO testing, separate technician and QA results, fixed failure custody, mandatory rework/retest phases, Floor handoffs, pressure testing permissions, Not required bypasses, original testing custodian, inactive testing history, controlled restarts, cycle/attempt history and stale testing decisions.');
  console.log('PASS: '+catalogContracts.length+' current/retained traveler contracts: '+catalogContracts.join('; ')+'.');
})().catch(error=>{console.error(error);process.exitCode=1});




