/* Synthetic client contract checks; no browser, account, or service is touched.
 * Run: node tests/process_ui_smoke.cjs
 */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const elements=new Map();
class Element {
  constructor(id){
    this.id=id;this.listeners={};this.dataset={};this.value='';this.disabled=false;
    this.open=false;this.attributes={};this.classes=new Set();this.clockNodes=[];
    this.classList={add:k=>this.classes.add(k),remove:k=>this.classes.delete(k),contains:k=>this.classes.has(k),toggle:(k,force)=>{if(force===undefined?!this.classes.has(k):force)this.classes.add(k);else this.classes.delete(k)}};
  }
  set innerHTML(value){
    this.html=value;this.clockNodes=[];
    for(const match of value.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){
      const el=new Element(match[1]);
      const valueAttr=match[0].match(/\bvalue="([^"]*)"/);if(valueAttr)el.value=valueAttr[1];
      el.disabled=/\sdisabled(?:\s|>)/.test(match[0]);
      for(const c of (match[0].match(/\bclass="([^"]*)"/)?.[1]||'').split(' '))el.classes.add(c);
      elements.set(match[1],el);
    }
    for(const match of value.matchAll(/<span[^>]+data-ft-clock="([^"]+)"[^>]*>/g)){
      const clock=new Element('clock');
      clock.dataset.ftClock=match[1];
      clock.dataset.ftRate=match[0].match(/data-ft-rate="([^"]+)"/)[1];
      clock.dataset.ftAnchor=match[0].match(/data-ft-anchor="([^"]+)"/)[1];
      this.clockNodes.push(clock);
    }
  }
  get innerHTML(){return this.html||''}
  addEventListener(name,handler){this.listeners[name]=handler}
  setAttribute(name,value){this.attributes[name]=value}
  querySelectorAll(selector){if(selector==='[data-ft-clock]')return this.clockNodes;return []}
  showModal(){this.open=true}
  close(){this.open=false}
  focus(){}
  setSelectionRange(){}
  scrollIntoView(){}
}
for(const id of ['trackingContent','trackingDialog','trackingDialogTitle','trackingDialogFields','trackingDialogForm','trackingDialogSubmit','trackingDialogError','trackingDialogClose','trackingDialogCancel','navTracking','itemTrackingBtn'])elements.set(id,new Element(id));

const instant='2026-10-28T12:05:00+00:00';
const emptyProcess=()=>({item_id:'S1',version:0,as_of:instant,status:'not_started',current:null,totals:{elapsed_seconds:0,active_seconds:0,paused_seconds:0,visits:0},by_process:[],visits:[],events:[]});
function runningProcess(status='running'){
  const current={id:4,group_key:'welding',process_key:'welding',process_name:'Welding',started_at:'2026-10-28T12:00:00+00:00',ended_at:null,started_by:'WELD1',ended_by:null,status,end_reason:null,elapsed_seconds:300,active_seconds:240,paused_seconds:60};
  const prior={...current,id:1,status:'finished',started_at:'2026-10-28T11:00:00+00:00',ended_at:'2026-10-28T11:02:00+00:00',ended_by:'SHOP1',elapsed_seconds:120,active_seconds:100,paused_seconds:20,end_reason:'move',process_key:'fit_up',process_name:'Fit-up',group_key:'fit_up'};
  const repeated={...prior,id:2,process_key:'welding',process_name:'Welding',group_key:'welding',elapsed_seconds:100,active_seconds:100,paused_seconds:0};
  return {item_id:'S1',version:8,as_of:instant,status,current,totals:{elapsed_seconds:520,active_seconds:440,paused_seconds:80,visits:3},visits:[prior,repeated,current],by_process:[{group_key:'fit_up',process_key:'fit_up',process_name:'Fit-up',visits:1,elapsed_seconds:120,active_seconds:100,paused_seconds:20},{group_key:'welding',process_key:'welding',process_name:'Welding',visits:2,elapsed_seconds:400,active_seconds:340,paused_seconds:60}],events:[{id:4,sequence:4,item_id:'S1',event:'pause',process_key:'welding',process_name:'Welding',notes:'Waiting for <img src=x onerror=alert(1)>',actor:'QA<one>',at:instant}]};
}
const summary={item_id:'S1',description:'Spool One',project_id:'P1',project_name:'Plant One',planned_welds:0,welds_defined:0,production_complete:0,qa_accepted:0,ready_to_release:false,released:false,blockers:[]};
let processData=emptyProcess(),released=false,rejectMutation=null,holdMutation=null;
const calls=[],messages=[],timers=new Map();
const processLabels={material_prep:'Material preparation',cutting_beveling:'Cutting & beveling',fit_up:'Fit-up',welding:'Welding',nde:'NDE / testing',pwht:'PWHT',dimensional:'Dimensional inspection',coating:'Coating / painting',final_qa:'Final QA',dispatch:'Ready for dispatch',custom:'Custom process'};
function scopedProcess(){
 const row=structuredClone(processData),keys=require('./ui_permissions_fixture.cjs').policy(context.me.role).process_keys||[],actions=[];
 if(!released){if(!row.current&&keys.length)actions.push('start');else if(row.current&&keys.includes(row.current.process_key)){if(keys.some(key=>key==='custom'||key!==row.current.process_key))actions.push('move');actions.push(row.status==='paused'?'resume':'pause','finish')}}
 row.permissions={allowed_actions:actions,allowed_processes:keys.map(key=>({key,label:processLabels[key]}))};return row;
}

let now=10000,timerSequence=0;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const context={
  document:{getElementById:id=>elements.get(id)||null},
  me:{badge:'TEST-ADMIN',name:'Test admin',role:'admin'},current:null,
  URL,URLSearchParams,Date,console,esc,
  performance:{now:()=>now},setInterval:fn=>{const id=++timerSequence;timers.set(id,fn);return id},clearInterval:id=>timers.delete(id),
  history:{replaceState(){}},show(){},stopCloudCamera(){},notify:message=>messages.push(message),async openItem(){},
  FormData:class{constructor(form){this.values=Object.entries(form.values||{})}[Symbol.iterator](){return this.values[Symbol.iterator]()}},
  api:async(url,options={})=>{
    calls.push({url,...options});
    if(options.method){
      if(holdMutation)await holdMutation;
      if(rejectMutation)throw rejectMutation;
      return scopedProcess();
    }
    if(url==='/api/tracking/processes')return [{key:'fit_up',label:'Fit-up'},{key:'welding',label:'Welding'},{key:'nde',label:'NDE / testing'}];
    if(url.startsWith('/api/tracking/overview'))return {projects:[{id:'P1',name:'Plant One'}],subprojects:[],templates:[],spools:[{...summary,production_process:scopedProcess()},{...summary,item_id:'S2',description:'Untimed spool',production_process:emptyProcess()}]};
    if(url==='/api/tracking/spools/S1')return {item:{id:'S1',description:'Spool One',released},plan:{item_id:'S1',project_id:'P1',planned_welds:0,drawing_revision:'A',version:1},summary,welds:[],requirements:[],holds:[],history:[],production_process:scopedProcess()};
    throw Error('Unexpected endpoint '+url);
  },
};
context.window=context;
vm.createContext(context);require('./ui_permissions_fixture.cjs').install(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/tracking.js'),'utf8'),context);
const html=()=>elements.get('trackingContent').innerHTML;
const click=async(action,id='')=>elements.get('trackingContent').listeners.click({target:{closest:()=>({dataset:{ftAction:action,ftId:id},disabled:false})}});
const submit=async values=>{const form=elements.get('trackingDialogForm');form.values=values;await form.listeners.submit({preventDefault(){},target:form})};
const postCalls=()=>calls.filter(c=>c.method==='POST');
const tick=milliseconds=>{now+=milliseconds;for(const fn of timers.values())fn()};
const liveValues=()=>elements.get('trackingContent').clockNodes.map(n=>n.textContent);

(async()=>{
  context.me.role='painter';await context.FabTracking.open({spool:'S1'});await click('process-start');
  assert.match(elements.get('trackingDialogFields').innerHTML,/<option value="coating"/);
  assert.doesNotMatch(elements.get('trackingDialogFields').innerHTML,/<option value="(?:welding|fit_up|nde|custom)"/,'painters receive only server-permitted timing choices');
  const beforeWrongProcess=postCalls().length;await submit({process_key:'welding',notes:'Unpermitted work'});assert.equal(postCalls().length,beforeWrongProcess,'a forged process option cannot be submitted');elements.get('trackingDialog').close();
  processData=runningProcess();await context.FabTracking.open({spool:'S1'});assert.doesNotMatch(html(),/data-ft-action="process-(?:move|pause|resume|finish)"/,'a painter cannot close or pause another trade’s current timer');
  await click('process-pause');assert.equal(postCalls().length,beforeWrongProcess);
  processData=emptyProcess();
  for(const role of ['admin','supervisor','handler','welder','fitup_welder','process_welder','inspector','painter','finisher','misc']){
    context.me.role=role;await context.FabTracking.open({spool:'S1'});
    assert.match(html(),/data-ft-action="process-start"/,role+' can record a process start');
  }
  context.me.role='unknown';await context.FabTracking.open({spool:'S1'});
  assert.doesNotMatch(html(),/data-ft-action="process-start"/);
  context.me.role='supervisor';await context.FabTracking.open({spool:'S1'});
  await click('process-start');
  assert.match(elements.get('trackingDialogFields').innerHTML,/Custom process/);
  elements.get('ft-field-process_key').value='custom';elements.get('ft-field-process_key').onchange();
  assert.equal(elements.get('ft-field-process_name').required,true);
  assert.equal(elements.get('ft-field-process_name').disabled,false);
  await submit({process_key:'custom',process_name:'  Heat treatment bay 2  ',notes:'  Shift A  '});
  assert.deepEqual(JSON.parse(postCalls().at(-1).body),{action:'start',expected_version:0,process_key:'custom',process_name:'Heat treatment bay 2',notes:'Shift A'});
  assert.equal(elements.get('trackingDialog').open,false);

  processData=runningProcess();await context.FabTracking.open({spool:'S1'});
  assert.match(html(),/data-ft-action="process-move"/);
  assert.match(html(),/data-ft-action="process-pause"/);
  assert.match(html(),/data-ft-action="process-finish"/);
  assert.doesNotMatch(html(),/data-ft-action="process-resume"/);
  assert.match(html(),/not crew labor hours/);
  assert.match(html(),/Time by process/);assert.match(html(),/Process visits/);
  assert.match(html(),/Waiting for &lt;img/);assert.doesNotMatch(html(),/<img src=x/);
  assert.match(html(),/QA&lt;one&gt;/);
  assert.equal(timers.size,1);
  assert.deepEqual(liveValues().slice(0,2),['05m 00s','04m 00s']);
  tick(61000);
  assert.deepEqual(liveValues().slice(0,2),['06m 01s','05m 01s'],'running advances elapsed and running, while paused is static');
  assert.ok(liveValues().includes('07m 41s'),'repeated process total advances from its cumulative baseline');
  await context.FabTracking.refresh();assert.equal(timers.size,1,'refresh replaces the timer');

  await click('process-move');
  assert.doesNotMatch(elements.get('trackingDialogFields').innerHTML,/<option value="welding"/,'move does not offer the same catalog process');
  await submit({process_key:'nde',process_name:'ignored',notes:'Ready for examination'});
  assert.deepEqual(JSON.parse(postCalls().at(-1).body),{action:'move',expected_version:8,process_key:'nde',notes:'Ready for examination'});

  await click('process-pause');
  const beforeValidation=postCalls().length;
  await submit({notes:'  '});
  assert.equal(postCalls().length,beforeValidation,'a pause needs a meaningful reason');
  assert.match(elements.get('trackingDialogError').textContent,/delay reason/);
  await submit({notes:'Waiting for crane'});
  assert.deepEqual(JSON.parse(postCalls().at(-1).body),{action:'pause',expected_version:8,notes:'Waiting for crane'});

  processData=runningProcess('paused');await context.FabTracking.open({spool:'S1'});
  assert.match(html(),/data-ft-action="process-resume"/);
  assert.doesNotMatch(html(),/data-ft-action="process-pause"/);
  assert.deepEqual(liveValues().slice(0,2),['05m 00s','01m 00s']);
  tick(120000);
  assert.deepEqual(liveValues().slice(0,2),['07m 00s','03m 00s'],'paused advances elapsed and pause, while running stays fixed');
  await click('process-resume');await submit({notes:'Crane available'});
  assert.deepEqual(JSON.parse(postCalls().at(-1).body),{action:'resume',expected_version:8,notes:'Crane available'});

  // Unicode spellings can have different lowercase forms but the same server
  // identity. Group totals must tick using that identity, not client spelling.
  processData=runningProcess();
  Object.assign(processData.current,{group_key:'custom:strasse',process_key:'custom',process_name:'STRAẞE'});
  Object.assign(processData.by_process[1],{group_key:'custom:strasse',process_key:'custom',process_name:'Strasse'});
  await context.FabTracking.open({spool:'S1'});
  assert.ok(liveValues().includes('06m 40s'));
  tick(5000);assert.ok(liveValues().includes('06m 45s'),'server process identity controls cumulative live ticks');

  processData=runningProcess();await context.FabTracking.open({view:'spools'});
  assert.match(html(),/Current process \/ elapsed/);assert.match(html(),/ftProcessFilter/);
  elements.get('ftProcessFilter').value='welding';elements.get('ftProcessFilter').onchange();
  assert.match(html(),/data-ft-id="S1"/);assert.doesNotMatch(html(),/data-ft-id="S2"/);assert.doesNotMatch(html(),/Spool One|Untimed spool/,'physical item descriptions are hidden');
  assert.equal(timers.size,1);
  context.FabTracking.cancelPending();assert.equal(timers.size,0,'navigation stops live updates');

  released=true;await context.FabTracking.open({spool:'S1'});
  assert.doesNotMatch(html(),/data-ft-action="process-(?:start|move|pause|resume|finish)"/);
  released=false;processData=runningProcess();await context.FabTracking.open({spool:'S1'});
  await click('process-finish');
  let releasePost;
  holdMutation=new Promise(resolve=>{releasePost=resolve});
  const beforeDouble=postCalls().length;
  const first=submit({notes:'Sent to coating'});
  await submit({notes:'Second click'});
  assert.equal(postCalls().length,beforeDouble+1,'duplicate submit is ignored while the first request is in flight');
  releasePost();await first;holdMutation=null;

  await click('process-pause');
  rejectMutation=Object.assign(Error('Process timing changed since you opened it; refresh and retry. No changes were saved.'),{status:409});
  const readsBefore=calls.filter(c=>c.url==='/api/tracking/spools/S1'&&!c.method).length;
  const messagesBefore=messages.length;
  await submit({notes:'Material not ready'});
  assert.ok(calls.filter(c=>c.url==='/api/tracking/spools/S1'&&!c.method).length>readsBefore,'conflict reloads the current spool');
  assert.match(elements.get('trackingDialogError').textContent,/Process timing changed/);
  assert.match(elements.get('trackingDialogError').textContent,/Close this dialog/);
  assert.equal(elements.get('trackingDialogSubmit').disabled,true,'the stale dialog cannot resubmit old expected_version');
  assert.equal(elements.get('trackingDialog').open,true);
  assert.equal(messages.length,messagesBefore,'no success notification follows a conflict');
  rejectMutation=null;
  elements.get('trackingDialog').close();await click('process-pause');
  assert.equal(elements.get('trackingDialogSubmit').disabled,false,'opening a fresh action clears stale state');
  await submit({notes:'Fresh delay record'});

  processData=runningProcess();processData.status='finished';processData.current=null;
  processData.visits.at(-1).status='finished';processData.visits.at(-1).ended_at=instant;
  await context.FabTracking.open({spool:'S1'});
  assert.match(html(),/Start another process/);assert.equal(timers.size,0,'finished records have no ticking timer');

  const index=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
  assert.match(index,/error\.status=r\.status;throw error/,'JSON API retains HTTP conflict status');
  assert.equal(index,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'),'both HTML entrypoints stay synchronized');
  console.log('PASS: process role controls, stage selection/custom payloads, exact write versions, elapsed/running/paused clocks, repeated-stage totals, server group identities, filters, escaping, release lock, duplicate submits, conflict refresh, and timer cleanup.');
})().catch(error=>{console.error(error);process.exitCode=1});
