/* Run with: node tests/tracking_ui_smoke.cjs
 * Client contract / rendering smoke tests, without a browser or extra dependencies.
 * These tests use synthetic fixtures only; no service, account, or real record is touched.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = new Map();
class Element {
  constructor(id) { this.id=id;this.listeners={};this.dataset={};this.children=[];this.value='';this.disabled=false;this.open=false;this.attributes={};this.classes=new Set();this.classList={add:k=>this.classes.add(k),remove:k=>this.classes.delete(k),contains:k=>this.classes.has(k)}; }
  set innerHTML(value) {
    this.html=value;
    for(const match of value.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
      const el=new Element(match[1]);
      const attr=match[0].match(/\bvalue="([^"]*)"/);if(attr)el.value=attr[1];
      elements.set(match[1],el);
    }
    for(const match of value.matchAll(/<select[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){
      const options=[...match[2].matchAll(/<option value="([^"]*)"([^>]*)>/g)],select=elements.get(match[1]);
      select.html=match[2];select.value=(options.find(row=>row[2].includes('selected'))||options[0])?.[1]||'';
    }
  }
  get innerHTML() { return this.html||''; }
  addEventListener(name,handler) {this.listeners[name]=handler;}
  setAttribute(name,value) {this.attributes[name]=value;}
  showModal() {this.open=true;}
  close() {this.open=false;}
  focus() {}
  setSelectionRange() {}
  scrollIntoView() {}
  append(child) {this.children.push(child);child.parent=this;}
  remove() {if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this);}
  querySelector(selector) {if(selector==='[data-remove-template]')return this.removeButton||(this.removeButton=new Element('remove-template'));return null;}
  querySelectorAll(selector) {return selector==='[data-template-row]'?this.children.filter(child=>child.dataset.templateRow):[];}
}
for(const id of ['trackingContent','trackingDialog','trackingDialogTitle','trackingDialogFields','trackingDialogForm','trackingDialogSubmit','trackingDialogError','trackingDialogClose','trackingDialogCancel','navTracking','itemTrackingBtn'])elements.set(id,new Element(id));

const requirement={id:11,item_id:'S1',weld_id:'WLD1',code:'MATERIALS',label:'Materials <check>',stage:'before_welding',allow_na:false,evidence_required:true,source:'Project procedure',owner_role:'inspector',status:'accepted',version:3,cycle:1,satisfied:true,check_errors:[],evidence:[{id:2,reference:'javascript:alert(1)',notes:'<img src=x onerror=alert(1)>',result:'recorded',actor:'QC1',at:'2026-10-28T12:00:00Z',cycle:1},{id:1,reference:'OLD-REF',notes:'Old evidence',result:'recorded',actor:'QC1',at:'2026-10-27T12:00:00Z',cycle:1}],reviews:[]};
const weld={id:'WLD1',item_id:'S1',number:'W01',description:'Joint <one>',joint_type:'SW',size:'2 in',wall_thickness:'Sch 80',component_a:'A',heat_a:'HA',mtr_a:'MA',component_b:'B',heat_b:'HB',mtr_b:'MB',wps:'WPS-1',wps_revision:'A',version:2,cycle:1,production_complete:false,qa_accepted:false,required_operations:['fill_cap'],requirements:[requirement],work:[{id:1,operation:'fitup',actor:'FIT1',at:'2026-10-28T11:00:00Z',cycle:1}],holds:[],repairs:[]};
const summary={item_id:'S1',description:'Spool <one>',project_id:'P1',project_name:'Plant One',subproject_id:'SUB1',subproject_name:'Package One',planned_welds:1,welds_defined:1,production_complete:0,qa_accepted:0,ready_to_release:false,released:false,blockers:['Welding incomplete'],due_date:null};
const released={...summary,item_id:'S2',description:'Released spool',planned_welds:1,production_complete:1,qa_accepted:1,ready_to_release:true,released:true,blockers:[]};
const spool={item:{id:'S1',description:'Spool <one>',kind:'Spool',location:'Bay 1',handler:'W1',released:false,on_hold:false,dimensional:'Pending'},plan:{item_id:'S1',project_id:'P1',subproject_id:'SUB1',assembly_id:null,planned_welds:1,drawing_revision:'A',version:1,notes:''},summary,welds:[weld],requirements:[],holds:[],history:[]};
const overview={projects:[{id:'P1',name:'Plant One'}],subprojects:[{id:'SUB1',project_id:'P1',name:'Package One'}],templates:[],spools:[summary,released]};
let failSpool=false,rejectMutation=false,readHook=null,timeoutId=0;
const calls=[],messages=[],readTimeouts=new Map();
function scopedWeld(){const row=structuredClone(weld),p=require('./ui_permissions_fixture.cjs').policy(context.me.role);row.allowed_operations=p.weld_operations||[];for(const r of row.requirements)r.permissions={can_submit_evidence:['admin','supervisor','inspector'].includes(context.me.role)||r.owner_role===context.me.role,can_review:['admin','inspector'].includes(context.me.role)};return row;}
function scopedSpool(){const row=structuredClone(spool);row.welds=[scopedWeld()];return row;}
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const context={
  document:{getElementById:id=>elements.get(id)||null,createElement:tag=>new Element(tag)},
  me:{badge:'ADMIN',name:'Administrator',role:'admin'},current:null,
  URL,URLSearchParams,Date,console,esc,AbortController,
  setTimeout:(fn,delay)=>{readTimeouts.set(++timeoutId,{fn,delay});return timeoutId},clearTimeout:id=>readTimeouts.delete(id),
  history:{replaceState(_a,_b,url){context.lastUrl=url}},
  show(name){context.lastPage=name},stopCloudCamera(){},notify(message){messages.push(message)},
  async openItem(id){context.lastItem=id},FabParts:{open:options=>{context.openedParts=options;}},
  FormData:class {constructor(form){this.values=Object.entries(form.values||{})}[Symbol.iterator](){return this.values[Symbol.iterator]()}},
  api:async(url,options={})=>{
    calls.push({url,...options});
    if(options.method){if(rejectMutation)throw Error('Record changed; refresh and try again.');return requirement;}
    if(readHook){const pending=readHook(url,options);if(pending!==undefined)return pending;}
    if(url.startsWith('/api/tracking/overview'))return structuredClone(overview);
    if(url==='/api/tracking/projects')return structuredClone(overview.projects);
    if(url==='/api/tracking/subprojects')return structuredClone(overview.subprojects);
    if(url==='/api/tracking/templates')return structuredClone(overview.templates);
    if(url==='/api/tracking/spools/S1'){if(failSpool){failSpool=false;throw Error('Temporary unavailable')}return scopedSpool()}
    if(url==='/api/tracking/welds/WLD1')return scopedWeld();
    if(url.startsWith('/api/tracking/exceptions'))return {exceptions:[]};
    throw Error('Unexpected endpoint '+url);
  },
};
context.window=context;
vm.createContext(context);require('./ui_permissions_fixture.cjs').install(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/tracking.js'),'utf8'),context);
const html=()=>elements.get('trackingContent').innerHTML;
const click=async(action,id='')=>elements.get('trackingContent').listeners.click({target:{closest:()=>({dataset:{ftAction:action,ftId:id},disabled:false})}});
const submit=async(values)=>{const form=elements.get('trackingDialogForm');form.values=values;await form.listeners.submit({preventDefault(){},target:form})};

(async()=>{
  await context.FabTracking.open();
  assert.equal(context.lastPage,'trackingPage');
  assert.match(html(),/Production complete/);
  assert.match(html(),/Weld QA accepted/);
  assert.match(html(),/Final release/);
  assert.match(html(),/Ready for final release<\/span><strong>0 \/ 2/,'released spools must not remain in the ready queue');

  await context.FabTracking.open({project:'P1',subproject:'SUB1',view:'spools'});
  elements.get('ftSearch').value='unrelated search';elements.get('ftSearch').oninput();
  elements.get('ftProcessFilter').value='unrelated process';elements.get('ftProcessFilter').onchange();
  await context.FabTracking.open({project:'P1',view:'spools'});
  assert.match(html(),/value="unrelated search"/,'ordinary navigation preserves existing filters');
  await context.FabTracking.open({project:'P1',subproject:'',view:'spools',resetFilters:true});
  assert.match(html(),/data-ft-id="S1"/,'setup shortcut clears an unrelated prior search and process filter');assert.doesNotMatch(html(),/Spool &lt;one&gt;/,'physical descriptions are hidden');
  assert.doesNotMatch(html(),/unrelated search/);assert.match(html(),/<option value="" selected>All processes/);
  assert.equal(calls.at(-1).url,'/api/tracking/overview?project_id=P1','setup shortcut opens the whole exact project');

  spool.parts={configured:true,totals:{required_qty:6,prepared_qty:2,assigned_qty:4,received_qty:3,short_qty:2}};
  await context.FabTracking.open({spool:'S1'});assert.match(html(),/2 of 6 required pieces prepared/);await click('spool-parts','S1');assert.equal(context.openedParts.spool,'S1');assert.equal(context.openedParts.project,'P1');
  await context.FabTracking.open({spool:'S1',weld:'WLD1'});
  assert.match(context.lastUrl,/spool=S1/);assert.match(context.lastUrl,/weld=WLD1/);
  assert.match(html(),/Joint &lt;one&gt;/);
  assert.doesNotMatch(html(),/<img src=x/,'evidence notes must be escaped');
  assert.doesNotMatch(html(),/href="javascript:/,'untrusted URI schemes must not become links');
  assert.doesNotMatch(html(),/data-ft-id="root"/,'single-pass configuration must not show a root operation');
  assert.match(html(),/data-ft-id="complete" disabled/,'completion remains blocked until configured passes are recorded');
  assert.match(html(),/data-ft-action="review-accept"/);
  assert.match(html(),/Latest evidence:[\s\S]*javascript:alert/,'newest evidence is displayed first');

  await click('evidence','11');
  assert.equal(elements.get('trackingDialog').open,true);
  await submit({reference:'REPORT-20',result:'pass',notes:'Measured and recorded'});
  const evidenceCall=calls.find(c=>c.url==='/api/tracking/requirements/11/evidence');
  assert.ok(evidenceCall);
  assert.deepEqual(JSON.parse(evidenceCall.body),{reference:'REPORT-20',result:'pass',notes:'Measured and recorded',expected_version:3});
  assert.equal(elements.get('trackingDialog').open,false);

  rejectMutation=true;
  await click('evidence','11');
  await submit({reference:'REPORT-21',result:'pass',notes:''});
  assert.equal(elements.get('trackingDialog').open,true,'failed writes must leave the form open');
  assert.match(elements.get('trackingDialogError').textContent,/Record changed/);
  rejectMutation=false;elements.get('trackingDialog').close();

  context.me.role='welder';await context.FabTracking.open({spool:'S1',weld:'WLD1'});
  assert.doesNotMatch(html(),/data-ft-action="review-accept"/);
  assert.doesNotMatch(html(),/data-ft-action="edit-weld"/);
  assert.doesNotMatch(html(),/data-ft-action="new-hold"/);
  assert.doesNotMatch(html(),/data-ft-action="evidence"/,'an inspector-owned requirement is read-only to a welder');
  assert.match(html(),/data-ft-id="fill_cap"/);

  for(const [position,expected] of [['fitup_welder',['fitup']],['process_welder',['fill_cap','complete']],['painter',[]],['finisher',[]],['handler',[]],['supervisor',[]],['misc',[]],['pressure_testing_technician',[]],['ndt',[]]]){
    context.me.role=position;await context.FabTracking.open({spool:'S1',weld:'WLD1'});
    assert.deepEqual([...html().matchAll(/data-ft-action="work" data-ft-id="([^"]+)"/g)].map(x=>x[1]),expected,position+' sees only its authorized welding operations');
    if(!expected.length){const before=calls.filter(c=>c.method).length;await click('work','fill_cap');assert.equal(elements.get('trackingDialog').open,false);assert.equal(calls.filter(c=>c.method).length,before);}
  }
  context.me.role='inspector';await context.FabTracking.open({spool:'S1',weld:'WLD1'});
  assert.match(html(),/data-ft-action="review-accept"/);
  assert.doesNotMatch(html(),/data-ft-action="work"/);

  context.me.role='supervisor';await context.FabTracking.open({spool:'S1'});
  assert.doesNotMatch(html(),/data-ft-action="dimensional"/,'supervisors cannot perform inspector-only dimensional approval');
  assert.doesNotMatch(html(),/data-ft-action="release"/,'supervisors cannot grant final release');
  context.me.role='inspector';await context.FabTracking.open({spool:'S1'});
  assert.match(html(),/data-ft-action="dimensional"/);
  assert.match(html(),/data-ft-action="release"/);

  // New testing positions can supply their assigned evidence without gaining QA or welding controls.
  for(const position of ['pressure_testing_technician','ndt']){
    requirement.owner_role=position;context.me.role=position;await context.FabTracking.open({spool:'S1',weld:'WLD1'});
    assert.match(html(),/data-ft-action="evidence"/);assert.doesNotMatch(html(),/data-ft-action="(?:review-accept|work|edit-weld)"/);
    const before=calls.filter(c=>c.method).length;await click('review-accept','11');assert.equal(elements.get('trackingDialog').open,false);assert.equal(calls.filter(c=>c.method).length,before);
    await click('evidence','11');await submit({reference:'TEST-'+position,result:'pass',notes:'Recorded result for QA review'});
    assert.equal(calls.filter(c=>c.method).at(-1).url,'/api/tracking/requirements/11/evidence');
  }
  requirement.owner_role='inspector';context.me.role='admin';await context.FabTracking.open({spool:'S1',weld:'WLD1'});
  await click('new-requirement');
  const newOwner=elements.get('ft-field-owner_role');assert.equal(newOwner.value,'inspector');
  assert.doesNotMatch(newOwner.innerHTML,/value="(?:welder|misc)"/);
  assert.match(newOwner.innerHTML,/value="pressure_testing_technician"/);assert.match(newOwner.innerHTML,/value="ndt"/);
  assert.match(newOwner.innerHTML,/>Shop Foreman<|>Fab Prep Technician</);
  elements.get('trackingDialog').close();

  // A next revision retains an actual historical owner; unrelated edits never default to Administrator.
  for(const retired of ['welder','misc']){
    const template={id:'TPL-'+retired,code:'JOB-'+retired,name:'Retained owner',revision:1,required_operations:['fill_cap'],requirements:[{code:'CUSTOM',label:'Recorded check',stage:'after_welding',owner_role:retired,check:'none',source:'Original source',evidence_required:true}]};
    overview.templates=[template];await context.FabTracking.open({view:'templates'});await click('copy-template',template.id);
    const owner=elements.get('ft-field-req1_owner_role'),other=retired==='welder'?'misc':'welder';
    assert.equal(owner.value,retired);assert.match(owner.innerHTML,/retained owner/);assert.ok(!owner.innerHTML.includes('value="'+other+'"'));
    assert.ok(owner.innerHTML.includes('value="'+retired+'" selected>'));
    elements.get('ftAddTemplateRequirement').onclick();const nextOwner=elements.get('ft-field-req2_owner_role');
    assert.equal(nextOwner.value,'inspector');assert.doesNotMatch(nextOwner.innerHTML,/value="(?:welder|misc)"/);
    await submit({code:template.code,name:template.name,revision:'2',source:'Updated specification',operation_fill_cap:'on',req1_code:'CUSTOM',req1_label:'Recorded check',req1_stage:'after_welding',req1_owner_role:owner.value,req1_check:'none',req1_source:'Corrected reference',req1_evidence_required:'on',req2_code:'NDT',req2_label:'Assigned NDT',req2_stage:'after_welding',req2_owner_role:'ndt',req2_check:'none',req2_source:'New test instruction',req2_evidence_required:'on'});
    const call=calls.filter(c=>c.method).at(-1);assert.equal(call.url,'/api/tracking/templates');
    const payload=JSON.parse(call.body);assert.equal(payload.requirements[0].owner_role,retired);assert.equal(payload.requirements[0].source,'Corrected reference');assert.equal(payload.requirements[1].owner_role,'ndt');assert.equal(template.requirements[0].source,'Original source');
  }
  overview.templates=[];context.me.role='inspector';await context.FabTracking.open({spool:'S1'});

  failSpool=true;await context.FabTracking.open({spool:'S1'});
  assert.match(html(),/Tracking records could not be loaded/);
  await click('retry');
  assert.match(html(),/Individual weld matrix/,'retry must preserve the originally requested spool');

  // Catalogs remain available to forms while detail reads avoid the full spool overview.
  context.me.role='admin';let releaseProjects;
  readHook=url=>url==='/api/tracking/projects'?new Promise(resolve=>{releaseProjects=()=>resolve(structuredClone(overview.projects))}):undefined;
  const focusedStart=calls.length,focusedOpen=context.FabTracking.open({spool:'S1',weld:'WLD1'});
  assert.ok(calls.slice(focusedStart).some(row=>row.url==='/api/tracking/spools/S1'),'spool read starts without waiting for catalogs');
  assert.ok(!calls.slice(focusedStart).some(row=>row.url.startsWith('/api/tracking/overview')));
  releaseProjects();await focusedOpen;readHook=null;
  assert.ok(!calls.slice(focusedStart).some(row=>row.url==='/api/tracking/welds/WLD1'),'the weld included with the spool is reused');
  assert.match(html(),/Joint &lt;one&gt;/);
  await click('back-spool');await click('edit-plan');
  assert.match(elements.get('trackingDialogFields').innerHTML,/Plant One/);assert.match(elements.get('trackingDialogFields').innerHTML,/Package One/);
  elements.get('trackingDialog').close();
  const weldStart=calls.length;await context.FabTracking.open({weld:'WLD1'});
  assert.ok(calls.slice(weldStart).some(row=>row.url==='/api/tracking/welds/WLD1'));
  assert.equal(calls.slice(weldStart).filter(row=>row.url==='/api/tracking/spools/S1').length,1);
  assert.ok(!calls.slice(weldStart).some(row=>row.url.startsWith('/api/tracking/overview')));assert.match(html(),/Joint &lt;one&gt;/);
  const overviewStart=calls.length;await click('overview');assert.ok(calls.slice(overviewStart).some(row=>row.url.startsWith('/api/tracking/overview')));assert.match(html(),/0 \/ 2/);

  let signal;
  readHook=(url,options)=>url==='/api/tracking/spools/S1'?new Promise((_resolve,reject)=>{
    signal=options.signal;signal.addEventListener('abort',()=>reject(Object.assign(Error('Read aborted'),{name:'AbortError'})),{once:true});
  }):undefined;
  const cancelledOpen=context.FabTracking.open({spool:'S1'});assert.ok(signal&&!signal.aborted);assert.equal(readTimeouts.size,1);
  context.FabTracking.cancelPending();elements.get('trackingContent').innerHTML='<p>Destination screen</p>';
  await cancelledOpen;assert.equal(signal.aborted,true);assert.equal(html(),'<p>Destination screen</p>');assert.equal(readTimeouts.size,0);

  const writesBefore=calls.filter(row=>row.method).length,timedOpen=context.FabTracking.open({spool:'S1'});
  assert.equal(readTimeouts.size,1);const timeout=[...readTimeouts.values()][0];assert.equal(timeout.delay,30000);timeout.fn();
  await timedOpen;assert.match(html(),/request took too long/);assert.match(html(),/Try again/);assert.equal(elements.get('trackingContent').attributes['aria-busy'],'false');assert.equal(readTimeouts.size,0);assert.equal(calls.filter(row=>row.method).length,writesBefore);
  readHook=null;await click('retry');assert.match(html(),/Individual weld matrix/);
  readHook=url=>url==='/api/tracking/spools/S1'?Promise.resolve({...scopedSpool(),item:{...spool.item,id:'OTHER-COPY'}}):undefined;
  await context.FabTracking.open({spool:'S1'});assert.match(html(),/does not match the selected item/);assert.doesNotMatch(html(),/data-ft-action="release"/);
  readHook=null;context.FabTracking.cancelPending();assert.equal(readTimeouts.size,0);
  console.log('PASS: routes, metrics, scoped trade/QA actions, new testing evidence, current-only new requirement owners, exact retired template-owner retention, configured production stages, evidence escaping, safe links, optimistic-write payload, failed-write recovery, focused spool/weld reads with planning catalogs, cancellation, bounded loading, exact-copy identity, and deep-link retry.');
})().catch(error=>{console.error(error);process.exitCode=1});
