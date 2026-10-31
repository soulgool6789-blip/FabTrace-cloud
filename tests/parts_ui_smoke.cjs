/* Spool parts UI contracts. Synthetic fixtures only; no server or production records. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const elements=new Map(),decode=v=>v.replace(/&(amp|lt|gt|quot|#39);/g,(_m,k)=>({amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"}[k]));
class Element{
  constructor(id){this.id=id;this.listeners={};this.attributes={};this.children=[];this.value='';this.disabled=false;this.selectionStart=0;this.classList={add(){},remove(){},toggle(){}};}
  set innerHTML(html){
    for(const id of this.children)elements.delete(id);this.children=[];this.html=html;
    for(const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const child=new Element(decode(match[1]));child.value=decode(match[0].match(/\bvalue="([^"]*)"/)?.[1]||'');child.disabled=/\sdisabled(?:\s|>)/.test(match[0]);elements.set(child.id,child);this.children.push(child.id);}
    for(const match of html.matchAll(/<textarea[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/textarea>/g))elements.get(decode(match[1])).value=decode(match[2]);
    for(const match of html.matchAll(/<select[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){const opts=[...match[2].matchAll(/<option value="([^"]*)"([^>]*)>/g)];elements.get(decode(match[1])).value=decode((opts.find(v=>v[2].includes('selected'))||opts[0])?.[1]||'');}
  }
  get innerHTML(){return this.html||'';}addEventListener(name,fn){this.listeners[name]=fn;}setAttribute(name,value){this.attributes[name]=value;}focus(){}setSelectionRange(){}scrollIntoView(){}closest(){return {open:false};}
}
for(const id of ['partsContent','navParts','itemPartsBtn','navBulk'])elements.set(id,new Element(id));
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const piece=(id,extra={})=>({id,description:'Flange <piece>',google_part_number:'PN-FLANGE',handler:'MC1',location:'Prep <bay>',current_step:7,current_title:'Prep Components',flow_status:'active',baseline_step:1,not_recorded_steps:[],received:true,prepared:false,blockers:['Prep still open'],can_remove:true,...extra});
const fixture=(extra={})=>({item:{id:'SPL-001',description:'Cooling spool <one>',project_id:'P1',project_name:'Customer & area',subproject_id:'SUB1'},configured:true,version:3,reference:'BOM-01 Rev A',editable:true,locked_reason:'',permissions:{can_manage:true,can_allocate:true},lines:[
  {id:'LINE-101',part_number:'PN-FLANGE',description:'Flanges <required>',required_qty:4,notes:'Approved drawing',assigned_qty:2,received_qty:1,prepared_qty:1,short_qty:2,remaining_qty:3,components:[piece('PART-001',{prepared:true,flow_status:'completed',current_step:null,current_title:'',blockers:[]}),piece('PART-002',{received:false,not_recorded_steps:[1,2]})]},
  {id:'LINE-102',part_number:'PN-ELBOW',description:'Elbows',required_qty:2,notes:'',assigned_qty:0,received_qty:0,prepared_qty:0,short_qty:2,remaining_qty:2,components:[]}
],totals:{required_qty:6,assigned_qty:2,received_qty:1,prepared_qty:1,short_qty:4,remaining_qty:5},candidates:[piece('PART-003'),piece('PART-004'),piece('PART-005',{google_part_number:'PN-ELBOW'})],unallocated_components:[],blockers:['4 pieces still need assignment'],events:[{action:'plan_saved',actor:'SUP1',at:'2026-10-29T12:00:00Z',reference:'BOM-01',reason:'Actual material scope'}],...extra});
let record=fixture(),items=[],fail=null,mutationFail=null,writeHold=null,readHolds=new Map();
const calls=[],routes=[],messages=[];
function setItems(){items=[{item_id:'SPL-001',description:'Cooling spool <one>',project_id:'P1',project_name:'Customer & area',configured:true,version:3,totals:record.totals,editable:true},{item_id:'SPL-002',description:'Other spool',project_id:'P2',project_name:'Other project',configured:false,version:0,totals:{required_qty:0,assigned_qty:0,received_qty:0,prepared_qty:0,short_qty:0}}];}
setItems();
const context={document:{getElementById:id=>elements.get(id)||null},me:null,current:null,URLSearchParams,Date,esc,
  history:{replaceState(_a,_b,url){context.url=url;}},show(page){context.page=page;},stopCloudCamera(){},notify:m=>messages.push(m),
  openItem:id=>routes.push({type:'item',id}),listItems:()=>routes.push({type:'items'}),
  FabTracking:{open:options=>routes.push({type:'tracking',...options})},FabFlow:{open:options=>routes.push({type:'flow',...options})},
  qrId(value,kind){const v=String(value||'').trim();if(kind==='item'){if(v.startsWith('FABTRACE:ITEM:'))return v.slice(14);try{return new URL(v).searchParams.get('item')||'';}catch(_){}return /^[-A-Za-z0-9_]{3,60}$/.test(v)?v:'';}return v;},
  api:async(url,options={})=>{
    calls.push({url,...options});
    if(options.method){const target=structuredClone(record);if(writeHold)await writeHold;if(mutationFail)throw mutationFail;const body=JSON.parse(options.body);let result;if(url.endsWith('/plan')){result={...target,configured:true,version:target.version+1,reference:body.reference,lines:body.lines.map((l,i)=>({...l,id:l.id||'NEW-'+i,assigned_qty:0,received_qty:0,prepared_qty:0,short_qty:l.required_qty,components:[]}))};}else result={...target,version:target.version+1};if(record.item.id===target.item.id)record=result;return structuredClone(result);}
    const captured=url==='/api/parts/spools'?{items:structuredClone(items)}:structuredClone(record);if(readHolds.has(url))await readHolds.get(url);if(fail)throw fail;
    assert.ok(url==='/api/parts/spools'||url.startsWith('/api/parts/spools/'),'unexpected route '+url);return captured;
  }
};
elements.get('navBulk').onclick=()=>routes.push({type:'bulk'});context.window=context;vm.createContext(context);require('./ui_permissions_fixture.cjs').install(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/parts.js'),'utf8'),context);
const html=()=>elements.get('partsContent').innerHTML,click=(action,id='')=>elements.get('partsContent').listeners.click({target:{closest:()=>({disabled:false,dataset:{partsAction:action,partsId:String(id)}})}});
const set=(id,value)=>{assert.ok(elements.has(id),'field '+id);elements.get(id).value=String(value);};
const submit=id=>{const form=elements.get(id);assert.ok(form,'form '+id);return form.onsubmit({preventDefault(){},target:form});};
const writes=()=>calls.filter(c=>c.method),hold=()=>{let release;const promise=new Promise(r=>release=r);return {promise,release};};
const checks=[];async function check(name,fn){await fn();checks.push(name);}
(async()=>{
  await check('authentication, discovery, project/search and deep links',async()=>{
    await context.FabParts.open();assert.equal(calls.length,0);
    context.me={role:'admin'};await context.FabParts.open();assert.equal(context.page,'partsPage');assert.equal(calls.at(-1).url,'/api/parts/spools');assert.match(html(),/Customer &amp; area/);assert.match(html(),/Parts list not configured/);
    set('partsSearch','other');elements.get('partsSearch').oninput();assert.doesNotMatch(html(),/Cooling spool/);assert.match(html(),/SPL-002/);assert.doesNotMatch(html(),/Other spool/);
    await context.FabParts.open({project:'EMPTY-PROJECT'});assert.match(html(),/No matching planned spools/);assert.equal(elements.get('partsProject').value,'EMPTY-PROJECT');
    await context.FabParts.open({project:'P1'});assert.doesNotMatch(html(),/Other spool<\/h2>/);await click('spool','SPL-001');assert.equal(context.url,'/?parts=1&project=P1&spool=SPL-001');assert.equal(calls.at(-1).url,'/api/parts/spools/SPL-001');
  });
  await check('required denominator, missing quantities, actual records and escaping',async()=>{
    assert.match(html(),/1 of 6 required pieces/);assert.match(html(),/16\.7%/);assert.match(html(),/4 still need assignment|4 pieces still need assignment/);assert.match(html(),/Flanges &lt;required&gt;/);assert.match(html(),/Prep &lt;bay&gt;/);assert.match(html(),/2 earlier step\(s\) not recorded/);assert.match(html(),/Receipt not recorded/);assert.match(html(),/Prepared for fit-up/);assert.match(html(),/Each assigned Part QR counts once/);
    const original=record;record=fixture({configured:false,version:0,lines:[],totals:{required_qty:0,assigned_qty:0,received_qty:0,prepared_qty:0,short_qty:0},events:[]});await context.FabParts.refresh();assert.match(html(),/No required parts list/);assert.doesNotMatch(html(),/100%/);assert.match(html(),/Create parts list/);record=original;await context.FabParts.refresh();
  });
  await check('plan editing preserves IDs, whole quantities and references',async()=>{
    await click('edit');set('parts-quantity_0','0');set('parts-reason','Approved scope correction');const before=writes().length;await submit('partsPlanForm');assert.equal(writes().length,before);assert.match(html(),/whole pieces/);
    set('parts-quantity_0','3.5');await submit('partsPlanForm');assert.equal(writes().length,before);
    set('parts-quantity_0','4');await click('add-line');assert.equal(elements.get('parts-reason').value,'Approved scope correction','adding a row preserves draft');set('parts-number_2','PN-TEE');set('parts-description_2','Tee');set('parts-quantity_2','1');set('parts-notes_2','Actual drawing');await submit('partsPlanForm');
    const call=writes().at(-1),body=JSON.parse(call.body);assert.equal(call.method,'PUT');assert.equal(call.url,'/api/parts/spools/SPL-001/plan');assert.equal(body.expected_version,3);assert.deepEqual(body.lines.map(l=>l.id),['LINE-101','LINE-102',undefined]);assert.equal(body.lines[2].required_qty,1);assert.equal(body.reference,'BOM-01 Rev A');assert.equal(body.reason,'Approved scope correction');assert.match(messages.at(-1),/saved/);
    record=fixture();await context.FabParts.refresh();await click('edit');await click('delete-line','0');assert.ok(elements.has('parts-quantity_1'),'allocated lines cannot be deleted by invoking action directly');await click('cancel-form');
  });
  await check('batch QR allocation, duplicates, payload and candidate selection',async()=>{
    await click('assign','LINE-101');set('parts-component_ids','PART-003\nhttps://fabtrace-cloud.onrender.com/?item=PART-003');set('parts-notes','Allocate actual pieces');let before=writes().length;await submit('partsAssignForm');assert.equal(writes().length,before);assert.match(html(),/Remove duplicate IDs/);
    set('parts-component_ids','https://fabtrace-cloud.onrender.com/?item=PART-003\nFABTRACE:ITEM:PART-004');await submit('partsAssignForm');const body=JSON.parse(writes().at(-1).body);assert.deepEqual(body,{expected_version:3,line_id:'LINE-101',component_ids:['PART-003','PART-004'],reference:'BOM-01 Rev A',notes:'Allocate actual pieces'});
    record=fixture();await context.FabParts.refresh();await click('assign','LINE-101');assert.match(html(),/PART-003/);assert.doesNotMatch(html(),/<option value="PART-005"/,'part-number mismatch is not offered');set('partsCandidate','PART-003');await click('add-candidate');assert.equal(elements.get('parts-component_ids').value,'PART-003');set('parts-candidate_search','004');elements.get('parts-candidate_search').oninput();assert.match(html(),/<option value="PART-004"/);assert.doesNotMatch(html(),/<option value="PART-003"/);assert.equal(elements.get('parts-component_ids').value,'PART-003');await click('cancel-form');
  });
  await check('unassignment is explicit, versioned and preserves physical identity',async()=>{
    await click('remove','PART-001');assert.match(html(),/removes the part from its required line and from this spool/);assert.match(html(),/QR, traveler and recorded history remain registered/);set('parts-reference','CORR-01');set('parts-notes','Wrong component selected');await submit('partsRemoveForm');const call=writes().at(-1);assert.equal(call.url,'/api/parts/spools/SPL-001/allocations/PART-001/remove');assert.deepEqual(JSON.parse(call.body),{expected_version:3,reference:'CORR-01',notes:'Wrong component selected'});
  });
  await check('asynchronous QR resolution keeps input order, rejects alias duplicates and abandons canceled or edited assignments',async()=>{
    context.me={role:'admin'};record=fixture();await context.FabParts.open({spool:'SPL-001'});const lookups=[];context.resolveItemQr=async value=>{lookups.push(value);return value==='PART-ALIAS-[003]'?'PART-003':value==='PART-ALIAS-[004]'?'PART-004':value;};
    await click('assign','LINE-101');set('parts-component_ids','PART-ALIAS-[004]\nPART-ALIAS-[003]');set('parts-notes','Actual readable QR codes scanned');await submit('partsAssignForm');assert.deepEqual(JSON.parse(writes().at(-1).body).component_ids,['PART-004','PART-003']);
    record=fixture();await context.FabParts.refresh();await click('assign','LINE-101');set('parts-component_ids','PART-ALIAS-[003]\nPART-003');set('parts-notes','Actual readable QR codes scanned');let before=writes().length;await submit('partsAssignForm');assert.equal(writes().length,before);assert.match(html(),/Remove duplicate IDs/);await click('cancel-form');
    const wait=hold();context.resolveItemQr=async value=>{lookups.push(value);await wait.promise;return 'PART-003';};await click('assign','LINE-101');set('parts-component_ids','PART-ALIAS-[003]');set('parts-notes','Actual readable QR codes scanned');let n=lookups.length;const canceled=submit('partsAssignForm');await submit('partsAssignForm');assert.equal(lookups.length,n+1);assert.match(html(),/Checking QR codes/);await click('cancel-form');wait.release();await canceled;assert.equal(writes().length,before);assert.doesNotMatch(html(),/partsAssignForm/);
    const edit=hold();context.resolveItemQr=async()=>{await edit.promise;return 'PART-003';};await click('assign','LINE-101');set('parts-component_ids','PART-ALIAS-[003]');set('parts-notes','Actual readable QR codes scanned');const changing=submit('partsAssignForm');set('parts-component_ids','PART-004');edit.release();await changing;assert.equal(writes().length,before);assert.equal(elements.get('parts-component_ids').value,'PART-004');assert.match(html(),/assignment changed while its QR codes were checked/);assert.equal(elements.get('partsSaveAllocation').disabled,false);await click('cancel-form');
    const moved=hold();context.resolveItemQr=async()=>{await moved.promise;throw Error('Late resolution failure');};await click('assign','LINE-101');set('parts-component_ids','PART-ALIAS-[003]');set('parts-notes','Actual readable QR codes scanned');const leaving=submit('partsAssignForm');context.FabParts.cancelPending();elements.get('partsContent').innerHTML='A different workspace';moved.release();await leaving;assert.equal(writes().length,before);assert.equal(html(),'A different workspace');delete context.resolveItemQr;record=fixture();await context.FabParts.open({spool:'SPL-001'});
  });
  await check('server permissions and workflow scope locks govern every write',async()=>{
    for(const role of ['inspector','welder']){context.me={role};record=fixture();await context.FabParts.refresh();assert.doesNotMatch(html(),/data-parts-action="edit"|data-parts-action="assign"|data-parts-action="remove"/);await click('edit');await click('assign','LINE-101');assert.doesNotMatch(html(),/partsPlanForm|partsAssignForm/);}
    context.me={role:'handler'};record=fixture();await context.FabParts.refresh();assert.doesNotMatch(html(),/data-parts-action="edit"/);assert.match(html(),/data-parts-action="assign"/);await click('assign','LINE-101');assert.match(html(),/partsAssignForm/);await click('cancel-form');
    context.me={role:'admin'};record=fixture({editable:false,locked_reason:'Fit-up already started <locked>'});await context.FabParts.refresh();assert.match(html(),/Fit-up already started &lt;locked&gt;/);assert.doesNotMatch(html(),/data-parts-action="edit"|data-parts-action="assign"|data-parts-action="remove"/);await click('edit');await click('remove','PART-001');assert.doesNotMatch(html(),/partsPlanForm|partsRemoveForm/);
    record=fixture({permissions:{can_manage:false,can_allocate:false}});await context.FabParts.refresh();assert.doesNotMatch(html(),/data-parts-action="edit"|data-parts-action="assign"/);
  });
  await check('conflicts require refresh, duplicates are coalesced and writes cannot retarget',async()=>{
    record=fixture();await context.FabParts.refresh();await click('assign','LINE-101');set('parts-component_ids','PART-003');set('parts-notes','Actual assigned component');mutationFail=Error('Record changed <refresh>');let before=writes().length;await submit('partsAssignForm');assert.equal(writes().length,before+1);assert.match(html(),/Record changed &lt;refresh&gt;/);assert.match(html(),/Close this form, refresh/);await submit('partsAssignForm');assert.equal(writes().length,before+1);mutationFail=null;await click('cancel-form');await context.FabParts.refresh();
    await click('assign','LINE-101');set('parts-component_ids','PART-003');set('parts-notes','Actual assigned component');const h=hold();writeHold=h.promise;before=writes().length;const pending=submit('partsAssignForm');await submit('partsAssignForm');assert.equal(writes().length,before+1);context.FabParts.cancelPending();elements.get('partsContent').innerHTML='New page';h.release();await pending;writeHold=null;assert.equal(html(),'New page');
  });
  await check('navigation during a save loads the new spool and preserves failed-read states',async()=>{
    record=fixture();await context.FabParts.open({spool:'SPL-001'});await click('assign','LINE-101');set('parts-component_ids','PART-003');set('parts-notes','Actual component assignment');const h=hold();writeHold=h.promise;const pending=submit('partsAssignForm');context.FabParts.cancelPending();record=fixture({item:{id:'SPL-002',description:'Different spool',project_id:'P2',project_name:'Other project'},configured:false,version:0,lines:[]});await context.FabParts.open({spool:'SPL-002'});assert.match(html(),/SPL-002/);assert.doesNotMatch(html(),/Different spool/);assert.match(context.url,/spool=SPL-002/);h.release();await pending;writeHold=null;assert.match(html(),/SPL-002/);assert.doesNotMatch(html(),/Different spool/);await click('edit');assert.match(html(),/partsPlanForm/);await click('cancel-form');
    record=fixture();await context.FabParts.open({spool:'SPL-001'});await click('assign','LINE-101');set('parts-component_ids','PART-003');set('parts-notes','Actual component assignment');const second=hold();writeHold=second.promise;const saving=submit('partsAssignForm');context.FabParts.cancelPending();fail=Error('New spool could not be read');await context.FabParts.open({spool:'SPL-002'});second.release();await saving;writeHold=null;assert.match(html(),/New spool could not be read/);assert.doesNotMatch(html(),/data-parts-action="edit"/);fail=null;
    record=fixture();await context.FabParts.open({spool:'SPL-002'});assert.match(html(),/response could not be verified/,'wrong item responses cannot be used to edit another spool');await context.FabParts.open({spool:'SPL-001'});
  });
  await check('physical QR and project shortcuts preserve intended context',async()=>{
    record=fixture();await context.FabParts.open({spool:'SPL-001'});await click('flow','PART-001');assert.deepEqual(routes.at(-1),{type:'flow',item:'PART-001',project:'P1',resetFilters:true});await click('tracking-item','SPL-001');assert.deepEqual(routes.at(-1),{type:'tracking',spool:'SPL-001'});await click('item','PART-001');assert.deepEqual(routes.at(-1),{type:'item',id:'PART-001'});await click('tracking','P1');assert.deepEqual(routes.at(-1),{type:'tracking',project:'P1',view:'spools',subproject:'',resetFilters:true});await click('bulk');assert.equal(context.url,'/');assert.equal(routes.at(-1).type,'bulk');context.current={id:'SPL-001'};await elements.get('itemPartsBtn').onclick();assert.match(context.url,/spool=SPL-001/);
  });
  await check('read failures clear prior progress and late responses cannot replace navigation',async()=>{
    fail=Error('Service <unavailable>');await context.FabParts.refresh();assert.match(html(),/Service &lt;unavailable&gt;/);assert.doesNotMatch(html(),/1 of 6 required pieces/);fail=null;await context.FabParts.refresh();
    const h=hold();readHolds.set('/api/parts/spools/SPL-001',h.promise);const before=calls.length,pending=context.FabParts.refresh(),duplicate=context.FabParts.refresh();assert.equal(calls.length,before+1);context.FabParts.cancelPending();elements.get('partsContent').innerHTML='Another page';h.release();await Promise.all([pending,duplicate]);readHolds.clear();assert.equal(html(),'Another page');
  });
  await check('mirrored shell, authenticated links, navigation and guide integrate the workspace',async()=>{
    const index=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');assert.equal(index,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'));
    for(const value of ['id="navParts"','id="partsPage"','id="partsContent"','id="itemPartsBtn"','/static/parts.js','/static/parts.css','FabParts.cancelPending'])assert.ok(index.includes(value),value);
    assert.match(index,/params\.has\('parts'\)[\s\S]*FabParts\.open/);assert.match(index,/params\.has\('badge'\)[\s\S]*FabHandoff\.openBadge/);assert.match(index,/else if\(params\.has\('spool'\)\|\|params\.has\('item'\)\)[\s\S]*resolveItemQr[\s\S]*\/scan/);
    for(const name of ['tracking','flow','progress'])assert.match(fs.readFileSync(path.join(__dirname,'../static/'+name+'.js'),'utf8'),/FabParts\.open/);
    const guide=fs.readFileSync(path.join(__dirname,'../static/guide.js'),'utf8');assert.match(guide,/id:'parts'/);assert.match(guide,/Required quantities do not create inventory/);assert.match(guide,/prepared|Prepared/);
  });
  console.log(`PASS: Spool parts (${checks.length} contracts): ${checks.join('; ')}.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
