/* Job-control UI acceptance with synthetic server responses; no production access. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {roles,legacyRoles,allRoles,policy}=require('./ui_permissions_fixture.cjs');
const html=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
assert.ok(script,'the application shell must be present');
const elements=new Map();
class Element{
 constructor(id){this.id=id;this.value='';this.textContent='';this.disabled=false;this.open=false;this.style={};this.attributes={};this.classes=new Set();this.classList={add:k=>this.classes.add(k),remove:k=>this.classes.delete(k),contains:k=>this.classes.has(k),toggle:(k,on)=>{if(on===undefined?!this.classes.has(k):on)this.classes.add(k);else this.classes.delete(k)}};}
 set innerHTML(value){this.html=value;for(const match of value.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g))el(match[1]);if(this.id==='employeeRole'){const options=[...value.matchAll(/<option value="([^"]*)"([^>]*)>/g)];this.value=(options.find(row=>row[2].includes('selected'))||options[0])?.[1]||'';}}
 get innerHTML(){return this.html||''}querySelectorAll(){return []}addEventListener(){}setAttribute(k,v){this.attributes[k]=v}removeAttribute(k){delete this.attributes[k]}showModal(){this.open=true}close(){this.open=false}focus(){}reset(){this.values={}}click(){return this.onclick?.()}
}
function el(id){if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id)}
for(const match of html.matchAll(/\bid="([^"]+)"/g))el(match[1]);
let selectedRole='misc',itemPermissionOverride=null;
const calls=[],messages=[],routes=[];
function employee(){const p=policy(selectedRole);return {badge:'SYNTHETIC',name:'Synthetic position test',role:selectedRole,role_label:p.label,permissions:{...p}};}
function item(){const p=policy(selectedRole),has=cap=>p.capabilities.includes(cap);return {id:'SYNTHETIC-ITEM',description:'Disposable UI fixture',kind:'Part',project:'UI-TEST',location:'Shop',handler:'SYNTHETIC',welds_done:0,welds_required:1,dimensional:'Not started',weld:'Not started',released:false,tracking_enabled:false,reworks:[{id:1,kind:'Correction',reason:'Fixture only',assigned:'SYNTHETIC',can_close:has('close_rework')}],inspections:[],permissions:itemPermissionOverride||{can_weld:has('weld_production'),can_inspect:has('inspect'),can_open_rework:has('open_rework'),can_release:has('inspect'),can_reopen:has('admin')},transfer:{status_label:'Queued',can_transfer:true},release_control:{mode:'not_released',label:'Not released'}};}
const context={console,URL,URLSearchParams,Date,Blob,location:{search:'',origin:'https://example.test',reload(){}},history:{replaceState(){}},
 document:{getElementById:el,createElement:()=>new Element('created'),body:{appendChild(){}},addEventListener(){}},setTimeout:()=>0,clearTimeout(){},confirm:()=>false,
 FormData:class{constructor(form){this.values=Object.entries(form.values||{})}[Symbol.iterator](){return this.values[Symbol.iterator]()}},
 addEventListener(){},open:()=>null,
};
context.window=context;vm.createContext(context);vm.runInContext(script,context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/permissions.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/employee-roster.js'),'utf8'),context);
for(const name of ['OrderSetup','Tracking','Flow','Quality','Progress','Parts','Dossier','Guide','Admin'])context['Fab'+name]={cancelPending(){},open:value=>routes.push({name,...value})};
context.FabHandoff={cancelPending(){},historyHtml:()=>'<p>No custody records in this fixture.</p>',open:value=>routes.push({name:'Handoff',...value})};
context.notify=message=>messages.push(message);
context.api=async(url,options={})=>{
 calls.push({url,...options});
 if(options.method){if(url==='/api/employees')return JSON.parse(options.body);throw Error('Unexpected synthetic mutation '+url)}
 if(url==='/api/me')return employee();
 if(url==='/api/permissions')return {version:'SYNTHETIC-JOBS',roles:allRoles,legacy_roles:legacyRoles,current:employee()};
 if(url==='/api/qr/status')return {ready:false};
 if(url==='/api/employees')return [{badge:'SYNTHETIC',name:'Synthetic worker',role:selectedRole,active:true}];
 if(url.startsWith('/api/items?'))return {items:[],total:0};
 if(url==='/api/items/SYNTHETIC-ITEM')return item();
 if(url.endsWith('/custody')||url.endsWith('/audit'))return [];
 throw Error('Unexpected synthetic read '+url);
};
const visible=id=>!el(id).classes.has('hidden');
const writes=()=>calls.filter(call=>call.method);
async function signIn(role){selectedRole=role;const before=routes.length;await context.refreshAuth();assert.equal(routes.length,before+1,'sign-in opens one landing view');assert.deepEqual(routes.at(-1),{name:'OrderSetup'},role+' default landing remains Orders');await context.openItem('SYNTHETIC-ITEM')}
(async()=>{
 for(const {id:role} of allRoles){
  await signIn(role);
  assert.equal(visible('weldBtn'),['welder','process_welder','admin'].includes(role),role+' aggregate welding control');
  assert.equal(visible('inspectBtn'),['inspector','admin'].includes(role),role+' inspection control');
  assert.equal(visible('releaseBtn'),['inspector','admin'].includes(role),role+' ordinary QA release control');
  assert.equal(visible('reworkBtn'),['supervisor','inspector','admin'].includes(role),role+' rework opening control');
  assert.equal(el('reworkRecords').innerHTML.includes('class="close-rw"'),['supervisor','admin'].includes(role),role+' generic rework closure');
  assert.equal(visible('navNew'),['supervisor','admin'].includes(role),role+' production setup control');
  assert.equal(visible('navBulk'),['supervisor','admin'].includes(role),role+' import control');
  assert.equal(visible('navAdmin'),role==='admin',role+' administrative controls');
  assert.equal(visible('transferBtn'),true,role+' ordinary custody handoff');
  assert.ok(el('userTop').innerHTML.includes(policy(role).label.replace('&','&amp;')),role+' readable position label');
 }
 assert.doesNotMatch(html,/navMyWork/,'My work has no navigation button or stale shell binding');
 assert.match(html,/<h2>Item identification<\/h2><button id="itemFlowBtn" type="button" class="primary">My tasks &amp; requirements<\/button>/,'QR/item users see their requirements beside item identification');
 assert.equal((html.match(/id="itemFlowBtn"/g)||[]).length,1,'the existing item flow action remains unique');
 selectedRole='painter';
 vm.runInContext("params.set('flow','1');params.set('item','SYNTHETIC-ITEM');params.set('project','UI-TEST');params.set('view','work');params.set('work_scope','custody')",context);
 await context.refreshAuth();assert.deepEqual(routes.at(-1),{name:'Flow',item:'SYNTHETIC-ITEM',project:'UI-TEST'},'a former work deep link opens the ordinary flow record and retains item/project');
 vm.runInContext("params.delete('view');params.set('work_scope','invalid')",context);
 await context.refreshAuth();assert.deepEqual(routes.at(-1),{name:'Flow',item:'SYNTHETIC-ITEM',project:'UI-TEST'},'ordinary flow links ignore obsolete work scope');
 vm.runInContext("params.delete('flow');params.delete('item');params.delete('project');params.delete('work_scope')",context);
 await signIn('painter');const beforeDenied=writes().length;await el('weldBtn').onclick();await el('inspectBtn').onclick();await el('releaseBtn').onclick();await el('navNew').onclick();
 assert.equal(el('dlg').open,false,'unavailable controls cannot open mutation dialogs through programmatic clicks');assert.equal(writes().length,beforeDenied);
 await signIn('admin');itemPermissionOverride={};await context.openItem('SYNTHETIC-ITEM');assert.equal(visible('weldBtn'),false);assert.equal(visible('inspectBtn'),false);assert.equal(visible('releaseBtn'),false,'a privileged role cannot override a missing server item permission in the UI');itemPermissionOverride=null;
 await el('navStaff').onclick();assert.equal(el('employeeRole').value,'','new accounts require an explicit position selection');assert.match(el('employeeRole').innerHTML,/Choose a job position/);
 for(const role of roles)assert.ok(el('employeeRole').innerHTML.includes('value="'+role.id+'"'),role.id+' must be selectable');
 assert.equal(roles.length,10);
 for(const label of ['Shop Foreman','Fab Prep Technician','Pressure Testing Technician','NDT'])assert.ok(el('employeeRole').innerHTML.includes('>'+label+'</option>'),label+' is a current job position');
 assert.doesNotMatch(el('employeeRole').innerHTML,/value="(?:welder|misc)"|>Supervisor<|>Finisher</);
 assert.deepEqual(Array.from(context.FabPermissions.roles(),row=>row.id),roles.map(row=>row.id));
 for(const legacy of legacyRoles){
  assert.equal(context.FabPermissions.label(legacy.id),legacy.label,'historical positions keep readable labels');
  assert.equal(context.FabPermissions.description(legacy.id),legacy.description);
  assert.equal(context.FabPermissions.ownerRoles().some(row=>row.id===legacy.id),false,'new requirements omit retired positions');
  const ownerOptions=Array.from(context.FabPermissions.ownerRoles(legacy.id),row=>row.id);
  assert.ok(ownerOptions.includes(legacy.id),'the saved retired owner remains selectable when retained');
  assert.equal(ownerOptions.filter(id=>legacyRoles.some(row=>row.id===id)).length,1,'only this saved retired owner is offered');
 }
 assert.equal(context.FabPermissions.ownerRoles('unrecognized-position').length,roles.length);
 const blankBefore=writes().length;el('employeeForm').values={badge:'NEW',name:'Synthetic new user',pin:'synthetic-private-value',role:''};await el('employeeForm').onsubmit({preventDefault(){},target:el('employeeForm')});assert.equal(writes().length,blankBefore,'blank positions cannot create employees');
 for(const retired of ['welder','misc','unrecognized-position']){
  el('employeeRole').value=retired;el('employeeForm').values={badge:'NEW',name:'Synthetic new user',pin:'synthetic-private-value',role:retired};
  await el('employeeForm').onsubmit({preventDefault(){},target:el('employeeForm')});assert.equal(writes().length,blankBefore,'new accounts cannot select '+retired);
 }
 el('employeeRole').value='painter';el('employeeRole').onchange();assert.match(el('employeeRoleHelp').textContent,/coating/);
 el('employeeForm').values={badge:'NEW',name:'Synthetic new user',pin:'synthetic-private-value',role:'painter'};await el('employeeForm').onsubmit({preventDefault(){},target:el('employeeForm')});assert.equal(JSON.parse(writes().at(-1).body).role,'painter');assert.equal(el('employeeRole').value,'','the next employee also needs explicit selection');
 vm.runInContext("me={role:'admin'}",context);assert.equal(context.FabPermissions.can('admin'),false,'role names never replace missing server capability grants');
 const originalApi=context.api, pending=new Map(), started=[];
 context.api=(url,options)=>{
   if(['/api/me','/api/permissions','/api/qr/status'].includes(url)){
     started.push(url);return new Promise((resolve,reject)=>pending.set(url,{resolve,reject}));
   }
   return originalApi(url,options);
 };
 el('workspace').classList.add('hidden');selectedRole='admin';
 const startup=context.refreshAuth();
 assert.deepEqual(started,['/api/me','/api/permissions','/api/qr/status'],'independent startup reads begin together');
 pending.get('/api/me').resolve(employee());
 pending.get('/api/qr/status').reject(Error('QR status temporarily unavailable'));
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(visible('workspace'),false,'workspace waits for verified permissions');
 pending.get('/api/permissions').resolve({roles:allRoles,legacy_roles:legacyRoles});await startup;
 assert.equal(visible('workspace'),true,'a QR configuration read failure does not block authenticated use');
 const denied=context.refreshAuth();
 pending.get('/api/me').resolve(employee());
 pending.get('/api/qr/status').resolve({ready:false});
 pending.get('/api/permissions').reject(Error('Permission verification failed'));await denied;
 assert.equal(visible('workspace'),false,'permission failures still deny access to the workspace');
 assert.equal(context.FabPermissions.can('admin'),false,'failed authentication clears stale capability grants');
 context.api=originalApi;
 assert.equal(fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'),html,'both HTML entrypoints stay identical');
 console.log('PASS: controls and navigation for 10 current positions and 2 retained historical roles; all employees land on Orders; former work links retain item/project in ordinary Process flow; My work navigation is absent and per-item requirements remain prominent; server denial is authoritative; current-only employee selection; exact retained owner options; ordinary badge transfers remain available; missing capabilities fail closed.');
})().catch(error=>{console.error(error);process.exitCode=1});
