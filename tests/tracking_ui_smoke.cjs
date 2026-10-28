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
  constructor(id) { this.id=id;this.listeners={};this.dataset={};this.value='';this.disabled=false;this.open=false;this.attributes={};this.classes=new Set();this.classList={add:k=>this.classes.add(k),remove:k=>this.classes.delete(k),contains:k=>this.classes.has(k)}; }
  set innerHTML(value) {
    this.html=value;
    for(const match of value.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
      const el=new Element(match[1]);
      const attr=match[0].match(/\bvalue="([^"]*)"/);if(attr)el.value=attr[1];
      elements.set(match[1],el);
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
}
for(const id of ['trackingContent','trackingDialog','trackingDialogTitle','trackingDialogFields','trackingDialogForm','trackingDialogSubmit','trackingDialogError','trackingDialogClose','trackingDialogCancel','navTracking','itemTrackingBtn'])elements.set(id,new Element(id));

const requirement={id:11,item_id:'S1',weld_id:'WLD1',code:'MATERIALS',label:'Materials <check>',stage:'before_welding',allow_na:false,evidence_required:true,source:'Project procedure',owner_role:'inspector',status:'accepted',version:3,cycle:1,satisfied:true,check_errors:[],evidence:[{id:2,reference:'javascript:alert(1)',notes:'<img src=x onerror=alert(1)>',result:'recorded',actor:'QC1',at:'2026-10-28T12:00:00Z',cycle:1},{id:1,reference:'OLD-REF',notes:'Old evidence',result:'recorded',actor:'QC1',at:'2026-10-27T12:00:00Z',cycle:1}],reviews:[]};
const weld={id:'WLD1',item_id:'S1',number:'W01',description:'Joint <one>',joint_type:'SW',size:'2 in',wall_thickness:'Sch 80',component_a:'A',heat_a:'HA',mtr_a:'MA',component_b:'B',heat_b:'HB',mtr_b:'MB',wps:'WPS-1',wps_revision:'A',version:2,cycle:1,production_complete:false,qa_accepted:false,required_operations:['fill_cap'],requirements:[requirement],work:[{id:1,operation:'fitup',actor:'FIT1',at:'2026-10-28T11:00:00Z',cycle:1}],holds:[],repairs:[]};
const summary={item_id:'S1',description:'Spool <one>',project_id:'P1',project_name:'Plant One',subproject_id:'SUB1',subproject_name:'Package One',planned_welds:1,welds_defined:1,production_complete:0,qa_accepted:0,ready_to_release:false,released:false,blockers:['Welding incomplete'],due_date:null};
const released={...summary,item_id:'S2',description:'Released spool',planned_welds:1,production_complete:1,qa_accepted:1,ready_to_release:true,released:true,blockers:[]};
const spool={item:{id:'S1',description:'Spool <one>',kind:'Spool',location:'Bay 1',handler:'W1',released:false,on_hold:false,dimensional:'Pending'},plan:{item_id:'S1',project_id:'P1',subproject_id:'SUB1',assembly_id:null,planned_welds:1,drawing_revision:'A',version:1,notes:''},summary,welds:[weld],requirements:[],holds:[],history:[]};
const overview={projects:[{id:'P1',name:'Plant One'}],subprojects:[{id:'SUB1',project_id:'P1',name:'Package One'}],templates:[],spools:[summary,released]};
let failSpool=false, rejectMutation=false;
const calls=[],messages=[];
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const context={
  document:{getElementById:id=>elements.get(id)||null},
  me:{badge:'ADMIN',name:'Administrator',role:'admin'},current:null,
  URL,URLSearchParams,Date,console,esc,
  history:{replaceState(_a,_b,url){context.lastUrl=url}},
  show(name){context.lastPage=name},stopCloudCamera(){},notify(message){messages.push(message)},
  async openItem(id){context.lastItem=id},
  FormData:class {constructor(form){this.values=Object.entries(form.values||{})}[Symbol.iterator](){return this.values[Symbol.iterator]()}},
  api:async(url,options={})=>{
    calls.push({url,...options});
    if(options.method){if(rejectMutation)throw Error('Record changed; refresh and try again.');return requirement;}
    if(url.startsWith('/api/tracking/overview'))return structuredClone(overview);
    if(url==='/api/tracking/spools/S1'){if(failSpool){failSpool=false;throw Error('Temporary unavailable')}return structuredClone(spool)}
    if(url==='/api/tracking/welds/WLD1')return structuredClone(weld);
    if(url.startsWith('/api/tracking/exceptions'))return {exceptions:[]};
    throw Error('Unexpected endpoint '+url);
  },
};
context.window=context;
vm.createContext(context);
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
  assert.match(html(),/data-ft-action="evidence"/);
  assert.match(html(),/data-ft-id="fill_cap"/);

  context.me.role='inspector';await context.FabTracking.open({spool:'S1',weld:'WLD1'});
  assert.match(html(),/data-ft-action="review-accept"/);
  assert.doesNotMatch(html(),/data-ft-action="work"/);

  context.me.role='supervisor';await context.FabTracking.open({spool:'S1'});
  assert.doesNotMatch(html(),/data-ft-action="dimensional"/,'supervisors cannot perform inspector-only dimensional approval');
  assert.doesNotMatch(html(),/data-ft-action="release"/,'supervisors cannot grant final release');
  context.me.role='inspector';await context.FabTracking.open({spool:'S1'});
  assert.match(html(),/data-ft-action="dimensional"/);
  assert.match(html(),/data-ft-action="release"/);

  failSpool=true;await context.FabTracking.open({spool:'S1'});
  assert.match(html(),/Tracking records could not be loaded/);
  await click('retry');
  assert.match(html(),/Individual weld matrix/,'retry must preserve the originally requested spool');
  console.log('PASS: routes, metrics, role actions, configured production stages, evidence escaping, safe links, optimistic-write payload, failed-write recovery, and deep-link retry.');
})().catch(error=>{console.error(error);process.exitCode=1});
