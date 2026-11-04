/* Browser-free checks of the shared dual-badge controller and generic transfer view. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const elements=new Map();
class Element {
  constructor(id){this.id=id;this.value='';this.textContent='';this.dataset={};this.attributes={};this.disabled=false;this.children=[];this.actions=[];this.classes=new Set();this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),contains:x=>this.classes.has(x),toggle:(x,force)=>{if(force===undefined?!this.classes.has(x):force)this.classes.add(x);else this.classes.delete(x)}};}
  set innerHTML(html){
    for(const id of this.children)elements.delete(id);this.children=[];this.actions=[];this.html=html;
    for(const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){
      const child=new Element(match[1]);child.value=match[0].match(/\bvalue="([^"]*)"/)?.[1]||'';child.disabled=/\sdisabled(?:\s|>)/.test(match[0]);
      for(const cls of (match[0].match(/\bclass="([^"]*)"/)?.[1]||'').split(' '))child.classes.add(cls);
      elements.set(child.id,child);this.children.push(child.id);
    }
    for(const match of html.matchAll(/<select[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g))elements.get(match[1]).innerHTML=match[2];
    if(html.includes('<option')){const options=[...html.matchAll(/<option value="([^"]*)"([^>]*)>/g)];this.value=(options.find(row=>row[2].includes('selected'))||options[0])?.[1]||''}
    for(const match of html.matchAll(/<button[^>]+data-location-action="([^"]+)"[^>]*>/g)){const child=new Element('action');child.dataset.locationAction=match[1];child.dataset.locationId=match[0].match(/data-location-id="([^"]+)"/)?.[1];this.actions.push(child)}
  }
  get innerHTML(){return this.html||''}
  setAttribute(name,value){this.attributes[name]=value}querySelectorAll(selector){return selector==='[data-location-action]'?this.actions:[]}
  focus(){if(this.onfocus)this.onfocus()}scrollIntoView(){}remove(){this.removed=true;}
}
for(const id of ['navHandoff','handoffBack','handoffIncoming','handoffItem','handoffItemFind','handoffItemCamera','handoffItemInfo','handoffProcessNotice','handoffControls','handoffNotes','handoffSummary','handoffError','handoffConfirm','handoffLocationSettings'])elements.set(id,new Element(id));
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const initialOptions=()=>({locations:[{id:'welding',label:'Welding',kind:'builtin',active:true,version:1},{id:'qa_qc',label:'QA / QC',kind:'builtin',active:true,version:1},{id:'custom_1',label:'Weld Bay 2',kind:'custom',active:true,version:2},{id:'custom_2',label:'Retired rack',kind:'custom',active:false,version:4}],statuses:[{id:'queued',label:'Queued'},{id:'in_progress',label:'In progress'},{id:'awaiting_inspection',label:'Awaiting inspection'},{id:'waiting_material',label:'Waiting for material'},{id:'paused',label:'Paused'},{id:'ready_next_operation',label:'Ready for next operation'}],keep_current_location_id:'current',can_manage_locations:true});
const employees=[{badge:'SHOP1',name:'Alex Sender',role:'welder',active:true},{badge:'SHOP2',name:'Sam Receiver',role:'handler',active:true},{badge:'SHOP3',name:'Lee Other',role:'handler',active:true},{badge:'OLD1',name:'Inactive worker',role:'handler',active:false}];
function item(id='SPL-001',extra={}){return {id,kind:'Spool',description:'Fixture <spool>',handler:'SHOP1',location:'Legacy Rack 7',released:false,flow_enabled:true,flow_step:13,flow_status:'active',transfer:{item_id:id,version:4,handler:'SHOP1',handler_name:'Alex Sender',handler_active:true,location:'Legacy Rack 7',location_id:null,operational_status:'queued',status_label:'Queued',can_transfer:true,released:false},...extra}}
let options=initialOptions(),items={'SPL-001':item(),'SPL-002':item('SPL-002')},directoryQueue=[],reads={},qrReads={},postHold=null,postFailure=null,locationFailure=null;
const calls=[],messages=[],storage=new Map(),cameras=[],events={},scripts=[],scriptTimers=new Map();
let startHold=null,scriptTimerId=0;
class Scanner {
  constructor(id){this.id=id;this.stops=0;this.clears=0;cameras.push(this)}
  async start(_camera,_config,decode){this.decode=decode;if(startHold)await startHold}
  async stop(){this.stops++}async clear(){this.clears++}
}
const context={document:{getElementById:id=>elements.get(id)||null,createElement:tag=>new Element(tag),head:{appendChild:script=>scripts.push(script)}},me:{name:'Authenticated Recorder',badge:'ADMIN',role:'admin'},current:null,URL,URLSearchParams,Date,console,esc,Html5Qrcode:Scanner,
  setTimeout:(fn,delay)=>{scriptTimers.set(++scriptTimerId,{fn,delay});return scriptTimerId;},clearTimeout:id=>scriptTimers.delete(id),
  location:{origin:'https://fabtrace-cloud.onrender.com'},history:{replaceState(_a,_b,url){context.url=url}},
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  show(page){if(page!=='handoffPage')context.FabHandoff?.cancelPending();context.page=page},notify:message=>messages.push(message),listItems(){context.show('itemsPage')},FabFlow:{open(value){context.openedFlow=value;context.show('flowPage')}},addEventListener:(event,callback)=>{events[event]=callback},
  api:async(url,request={})=>{
    calls.push({url,...request});
    if(url.startsWith('/api/spool-qr/resolve?')){
      const code=new URL(url,'https://fabtrace-cloud.onrender.com').searchParams.get('code');
      if(qrReads[code])return await qrReads[code];
      const record=Object.values(items).find(row=>row.qr_alias===code);
      if(!record)throw Error('Spool QR code not found');
      return {item_id:record.id,qr_alias:record.qr_alias,display_code:record.display_code};
    }
    if(url==='/api/transfers/options')return structuredClone(options);
    if(url==='/api/employees/directory')return directoryQueue.length?await directoryQueue.shift():structuredClone(employees);
    if(url==='/api/transfers/locations'&&request.method==='POST'){
      if(locationFailure)throw locationFailure;const body=JSON.parse(request.body),created={id:'custom_3',label:body.label,kind:'custom',active:true,version:1};options.locations.push(created);return structuredClone(created);
    }
    if(url.startsWith('/api/transfers/locations/')&&request.method==='PATCH'){
      if(locationFailure)throw locationFailure;const record=options.locations.find(row=>row.id===url.split('/').at(-1)),body=JSON.parse(request.body);assert.equal(body.expected_version,record.version);Object.assign(record,{label:body.label,active:body.active,version:record.version+1});return structuredClone(record);
    }
    const match=url.match(/^\/api\/items\/([^/]+)(\/transfer)?$/);if(match){
      const id=decodeURIComponent(match[1]);if(!match[2])return reads[id]?await reads[id]:structuredClone(items[id]);
      if(postHold)await postHold;if(postFailure)throw postFailure;
      const body=JSON.parse(request.body),old=items[id],employee=employees.find(row=>row.badge===body.handler),location=body.location_id==='current'?old.transfer.location:options.locations.find(row=>row.id===body.location_id).label;
      const transfer={...old.transfer,handler:body.handler,handler_name:employee.name,location,location_id:body.location_id==='current'?old.transfer.location_id:body.location_id,operational_status:body.operational_status,status_label:options.statuses.find(row=>row.id===body.operational_status).label,version:old.transfer.version+1};items[id]={...old,handler:transfer.handler,location,transfer};return structuredClone(items[id]);
    }
    throw Error('Unexpected endpoint '+url);
  },
};context.window=context;vm.createContext(context);
const index=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
vm.runInContext(index.slice(index.indexOf('function qrId('),index.indexOf('function stopCloudCamera(')),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/spool-qr.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/handoff.js'),'utf8'),context);
const el=id=>elements.get(id),click=async id=>{assert.ok(el(id),id+' exists');return await el(id).onclick()},input=(id,value)=>{el(id).value=value;el(id).oninput?.()},change=async(id,value)=>{el(id).value=value;return await el(id).onchange?.()},lookup=async(role,value)=>{input('handoff'+role,value);await click('handoff'+role+'Find')};
const posts=()=>calls.filter(row=>row.method==='POST'&&row.url.endsWith('/transfer')),flush=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((ok,no)=>{resolve=ok;reject=no});return {promise,resolve,reject}};
async function ready(receiver='SHOP2'){await lookup('Sender','SHOP1');await lookup('Receiver',receiver)}
(async()=>{
  await context.FabHandoff.open({item:'SPL-001'});
  assert.equal(context.page,'handoffPage');assert.match(context.url,/handoff=1&item=SPL-001/);
  assert.match(el('handoffItemInfo').innerHTML,/Alex Sender|Legacy Rack 7/);assert.match(el('handoffItemInfo').innerHTML,/<strong>SPL-001<\/strong>/);assert.doesNotMatch(el('handoffItemInfo').innerHTML,/Fixture &lt;spool&gt;/);
  assert.equal(el('handoffSender').value,'','recorded custodian never prefills sender input');assert.equal(el('handoffReceiver').value,'');assert.equal(el('handoffLocation').value,'current');assert.equal(el('handoffStatus').value,'queued');
  assert.doesNotMatch(el('handoffLocation').innerHTML,/Retired rack/);assert.match(el('handoffControls').innerHTML,/does not advance the process, pause its timer, or grant QA release/);
  assert.equal(el('handoffConfirm').disabled,true);await lookup('Sender','SHOP3');assert.match(el('handoffSenderInfo').textContent,/recorded custodian/);assert.equal(el('handoffConfirm').disabled,true);
  await lookup('Sender','OLD1');assert.match(el('handoffSenderInfo').textContent,/inactive/);
  await ready();assert.equal(el('handoffConfirm').disabled,false);assert.match(el('handoffSummary').innerHTML,/Authenticated Recorder \(ADMIN\)/);assert.match(el('handoffSummary').innerHTML,/Sam Receiver/);
  input('handoffSender','SHOP3');assert.equal(el('handoffConfirm').disabled,true,'editing invalidates earlier badge lookup immediately');await lookup('Sender','FABTRACE:EMP:SHOP1');
  await change('handoffLocation','made_up');assert.equal(el('handoffConfirm').disabled,true);await change('handoffLocation','welding');
  input('handoffNotes','  Shift move  ');await click('handoffConfirm');
  assert.deepEqual(JSON.parse(posts().at(-1).body),{sender_badge:'SHOP1',handler:'SHOP2',location_id:'welding',operational_status:'queued',expected_transfer_version:4,expected_handler:'SHOP1',notes:'Shift move',scan_method:'manual'});
  assert.equal(el('handoffSender').value,'');assert.equal(el('handoffReceiver').value,'');assert.equal(el('handoffItem').value,'');assert.match(el('handoffItemInfo').textContent,/Transfer recorded/);

  items['SPL-001']=item();await context.FabHandoff.open({item:'SPL-001'});await ready('SHOP1');assert.match(el('handoffSummary').innerHTML,/Same custodian — location\/status update/);assert.equal(el('handoffConfirm').disabled,true);
  await change('handoffStatus','paused');assert.equal(el('handoffConfirm').disabled,false);assert.equal(el('handoffConfirm').textContent,'Record location/status update');
  const hold=deferred();postHold=hold.promise;const before=posts().length,first=click('handoffConfirm');await flush();await click('handoffConfirm');assert.equal(posts().length,before+1,'double click sends one mutation');hold.resolve();await first;postHold=null;
  assert.equal(items['SPL-001'].flow_step,13,'operational status does not change the numbered step');

  for(const outcome of ['success','conflict']){
    items['SPL-001']=item();await context.FabHandoff.open({item:'SPL-001'});await ready();
    const waitingSave=deferred();postHold=waitingSave.promise;postFailure=outcome==='conflict'?Object.assign(Error('Old selection changed'),{status:409}):null;
    const saving=click('handoffConfirm');await flush();await change('handoffItem','SPL-002');waitingSave.resolve();await saving;postHold=null;postFailure=null;
    assert.match(el('handoffItemInfo').innerHTML,/SPL-002/,'old '+outcome+' response cannot clear or refresh the new item');assert.equal(el('handoffItem').value,'SPL-002');assert.doesNotMatch(el('handoffError').textContent,/Old selection changed/);
  }

  items['SPL-001']=item();await context.FabHandoff.open({item:'SPL-001'});await ready();
  items['SPL-001'].transfer={...items['SPL-001'].transfer,version:5,handler:'SHOP3',handler_name:'Lee Other'};items['SPL-001'].handler='SHOP3';postFailure=Object.assign(Error('Custody changed'),{status:409});
  await click('handoffConfirm');postFailure=null;assert.equal(el('handoffSender').value,'');assert.equal(el('handoffReceiver').value,'');assert.match(el('handoffItemInfo').innerHTML,/Lee Other/);assert.match(el('handoffError').textContent,/Scan both employee badges again/);assert.equal(el('handoffConfirm').disabled,true);

  items['SPL-001']=item();await context.FabHandoff.open({item:'SPL-001'});
  const slowBadge=deferred();directoryQueue.push(slowBadge.promise);input('handoffSender','SHOP3');const earlier=click('handoffSenderFind');await flush();await lookup('Sender','SHOP1');slowBadge.resolve(employees);await earlier;
  assert.match(el('handoffSenderInfo').textContent,/Alex Sender/,'older lookup cannot replace a newly identified badge');
  const staleBadge=deferred();directoryQueue.push(staleBadge.promise);input('handoffReceiver','SHOP2');const prior=click('handoffReceiverFind');await flush();await change('handoffItem','SPL-002');staleBadge.resolve(employees);await prior;
  assert.equal(el('handoffSender').value,'');assert.equal(el('handoffReceiver').value,'','switching items resets both identities');assert.equal(el('handoffConfirm').disabled,true);
  const slowItem=deferred();reads['SPL-001']=slowItem.promise;el('handoffItem').value='SPL-001';const priorItem=click('handoffItemFind');await flush();await change('handoffItem','SPL-002');slowItem.resolve(item());await priorItem;delete reads['SPL-001'];assert.match(el('handoffItemInfo').innerHTML,/SPL-002/);

  await context.FabHandoff.open({item:'SPL-001'});await click('handoffSenderCamera');let camera=cameras.at(-1);await camera.decode('FABTRACE:ITEM:SPL-001');assert.match(el('handoffCameraStatus').textContent,/not a valid employee badge/);await camera.decode('FABTRACE:EMP:SHOP1');assert.equal(el('handoffSender').value,'SHOP1');assert.equal(camera.stops,1);assert.equal(camera.clears,1);
  await click('handoffReceiverCamera');camera=cameras.at(-1);await camera.decode('https://fabtrace-cloud.onrender.com/?badge=SHOP2#badge_login=synthetic-camera-credential');assert.equal(el('handoffReceiver').value,'SHOP2');assert.equal(el('handoffSender').value,'SHOP1');assert.equal(camera.stops,1);await change('handoffStatus','in_progress');await click('handoffConfirm');assert.equal(JSON.parse(posts().at(-1).body).scan_method,'employee_qr');
  assert.equal(context.me.badge,'ADMIN');assert.doesNotMatch(JSON.stringify(calls),/synthetic-camera-credential|badge_login/);assert.doesNotMatch(JSON.stringify([...storage.values()]),/synthetic-camera-credential|badge_login/);
  items['SPL-001']=item();await context.FabHandoff.open({item:'SPL-001'});input('handoffSender','https://fabtrace-cloud.onrender.com/?badge=SHOP1#badge_login=synthetic-usb-credential');let prevented=false;el('handoffSender').onkeydown({key:'Enter',preventDefault(){prevented=true}});await flush();assert.equal(prevented,true);assert.equal(el('handoffSender').value,'SHOP1');assert.equal(context.me.badge,'ADMIN');assert.doesNotMatch(JSON.stringify(calls),/synthetic-usb-credential|badge_login/);assert.doesNotMatch(JSON.stringify([...storage.values()]),/synthetic-usb-credential|badge_login/);
  items['SPL-001']=item();await context.FabHandoff.open({item:'SPL-001'});const waiting=deferred();startHold=waiting.promise;const opening=click('handoffSenderCamera');await flush();camera=cameras.at(-1);context.FabHandoff.cancelPending();waiting.resolve();await opening;startHold=null;assert.equal(camera.stops,1,'camera finishing startup after navigation is stopped');assert.equal(camera.clears,1);

  storage.clear();await context.FabHandoff.openBadge('SHOP2');assert.equal(el('handoffSender').value,'');assert.equal(el('handoffReceiver').value,'');assert.match(el('handoffIncoming').innerHTML,/Identify the item first/);assert.equal(el('handoffIncomingReceiver').disabled,true);
  await change('handoffItem','SPL-001');await click('handoffIncomingReceiver');assert.equal(el('handoffReceiver').value,'SHOP2');assert.equal(el('handoffSender').value,'');
  await lookup('Sender','SHOP1');el('handoffReceiver').onfocus();const saved=JSON.parse(storage.get('fabtrace_pending_handoff'));assert.equal(saved.role,'receiver');assert.equal(saved.sender,'SHOP1');
  await context.FabHandoff.openBadge('SHOP3');assert.equal(el('handoffSender').value,'SHOP1');assert.equal(el('handoffReceiver').value,'SHOP3','pending role targets receiver rather than sender');
  storage.set('fabtrace_pending_handoff',JSON.stringify({id:'SPL-001',time:Date.now()}));await context.FabHandoff.openBadge('SHOP2');assert.equal(el('handoffReceiver').value,'','legacy pending item does not blindly assign receiver');assert.match(el('handoffIncoming').innerHTML,/Choose which employee/);
  storage.set('fabtrace_pending_handoff',JSON.stringify({item_id:'SPL-001',role:'receiver',recorder:'OTHER',time:Date.now()}));await context.FabHandoff.openBadge('SHOP2');assert.equal(el('handoffItem').value,'','pending context cannot cross signed-in accounts');
  storage.set('fabtrace_pending_handoff',JSON.stringify({item_id:'SPL-001',role:'receiver',recorder:'ADMIN',time:Date.now()-21*60*1000}));await context.FabHandoff.openBadge('SHOP2');assert.equal(el('handoffItem').value,'','expired context is ignored');

  await context.FabHandoff.open({item:'SPL-001'});input('handoffNewLocation','Fabrication Bay C');await click('handoffAddLocation');assert.match(el('handoffLocation').innerHTML,/Fabrication Bay C/);
  const rename=el('handoffLocationSettings').actions.find(action=>action.dataset.locationId==='custom_3'&&action.dataset.locationAction==='rename');input('handoffLocationName-custom_3','Fabrication Bay D');await rename.onclick();assert.match(el('handoffLocation').innerHTML,/Fabrication Bay D/);
  await change('handoffLocation','custom_3');const disable=el('handoffLocationSettings').actions.find(action=>action.dataset.locationId==='custom_3'&&action.dataset.locationAction==='toggle');await disable.onclick();assert.equal(el('handoffLocation').value,'');assert.doesNotMatch(el('handoffLocation').innerHTML,/Fabrication Bay D/);
  const patch=calls.filter(row=>row.method==='PATCH').at(-1);assert.equal(JSON.parse(patch.body).expected_version,2);
  options.can_manage_locations=false;await context.FabHandoff.open({item:'SPL-001'});assert.equal(el('handoffLocationSettings').innerHTML,'','unprivileged view has no management controls');
  options.can_manage_locations=true;

  const legacy=context.FabHandoff.historyHtml([{actor:'ADMIN',at:'2026-10-29T12:00:00Z',details:{from:{handler:'SHOP1',location:'A'},to:{handler:'SHOP2',name:'Sam <Receiver>',location:'B'}}}]);assert.match(legacy,/Historical custody record/);assert.doesNotMatch(legacy,/Sending badge:/);assert.match(legacy,/Sam &lt;Receiver&gt;/);
  const current=context.FabHandoff.historyHtml([{actor:'ADMIN',details:{sender_badge:'SHOP1',receiver_badge:'SHOP2',from:{handler:'SHOP1',location:'A'},to:{handler:'SHOP2',location:'B',operational_status:'awaiting_inspection'}}}]);assert.match(current,/Sending badge: SHOP1/);assert.match(current,/Awaiting inspection/);assert.match(current,/Independent sender\/receiver acceptance signatures are not recorded/);
  const correction=context.FabHandoff.historyHtml([{event:'ADMIN_CUSTODY_CORRECTION',actor:'ADMIN',details:{administrative_correction:true,badge_scans_recorded:false,from:{handler:'SHOP1',location:'A'},to:{handler:'SHOP2',location:'B',operational_status:'queued'},reason:'Correct misplaced <record>',reference:'CORR-01'}}]);assert.match(correction,/Administrative custody correction/);assert.match(correction,/Correct misplaced &lt;record&gt;/);assert.match(correction,/CORR-01/);assert.match(correction,/badge scans and independent acceptance signatures were not recorded/);assert.doesNotMatch(correction,/Sending badge:|Receiving badge:/);
  assert.equal(context.qrId('https://unrelated.example/?badge=SHOP1','badge'),'');assert.equal(context.qrId('FABTRACE:EMP:SHOP1','badge'),'SHOP1');assert.equal(context.qrId('FABTRACE:ITEM:SPL-001','item'),'SPL-001');
  // Alias resolution is asynchronous; a delayed scan must not replace a newer spool.
  const alias='643-777-PCW-03-01-[001]',aliasUrl='https://fabtrace-cloud.onrender.com/?spool='+encodeURIComponent(alias);
  items['SPL-001']=item('SPL-001',{qr_alias:alias,display_code:alias});
  assert.equal(typeof context.resolveItemQr,'function');
  await context.FabHandoff.open();await change('handoffItem',aliasUrl);
  assert.ok(el('handoffItemInfo').innerHTML.includes('<strong>'+alias+'</strong>'));assert.equal(el('handoffItem').value,alias);
  await ready();await change('handoffStatus','in_progress');await click('handoffConfirm');
  assert.equal(posts().at(-1).url,'/api/items/SPL-001/transfer');assert.match(el('handoffItemInfo').textContent,/643-777-PCW-03-01-\[001\]/);
  items['SPL-001']=item('SPL-001',{qr_alias:alias,display_code:alias});await context.FabHandoff.open();
  const delayedAlias=deferred();qrReads[alias]=delayedAlias.promise;el('handoffItem').value=alias;const resolving=click('handoffItemFind');await flush();await change('handoffItem','SPL-002');delayedAlias.resolve({item_id:'SPL-001',qr_alias:alias,display_code:alias});await resolving;delete qrReads[alias];assert.match(el('handoffItemInfo').innerHTML,/SPL-002/);
  await context.FabHandoff.open();await click('handoffItemCamera');camera=cameras.at(-1);await camera.decode(aliasUrl);assert.equal(el('handoffItem').value,alias);assert.equal(camera.stops,1);assert.equal(camera.clears,1);

  // Ordinary navigation/manual input never downloads the optional camera library.
  assert.equal(scripts.length,0,'an available scanner is reused without adding a script');
  delete context.Html5Qrcode;await context.FabHandoff.open({item:'SPL-001'});await lookup('Sender','SHOP1');
  assert.equal(scripts.length,0);assert.equal(scriptTimers.size,0);
  await context.FabHandoff.open({item:'SPL-001'});
  const cameraCount=cameras.length,firstLoad=click('handoffSenderCamera');await flush();
  assert.equal(scripts.length,1);assert.equal(scripts[0].async,true);assert.match(scripts[0].src,/^\/static\/vendor\/html5-qrcode-2\.3\.8\.min\.js(?:\?v=[^\s]+)?$/);assert.equal(cameras.length,cameraCount);assert.match(el('handoffCameraStatus').textContent,/Loading camera scanner/);
  const secondLoad=click('handoffReceiverCamera');await flush();assert.equal(scripts.length,1,'concurrent scan actions share the script download');
  context.Html5Qrcode=Scanner;scripts[0].onload();await Promise.all([firstLoad,secondLoad]);
  assert.equal(scriptTimers.size,0);assert.equal(cameras.length,cameraCount+1,'only the latest requested camera starts');camera=cameras.at(-1);await camera.decode('FABTRACE:EMP:SHOP2');assert.equal(el('handoffReceiver').value,'SHOP2');assert.equal(el('handoffSender').value,'');

  // Download errors and timeouts leave manual entry usable and allow a later retry.
  delete context.Html5Qrcode;await context.FabHandoff.open({item:'SPL-001'});const failed=click('handoffSenderCamera');await flush();const failedScript=scripts.at(-1);failedScript.onerror();await failed;
  assert.equal(failedScript.removed,true);assert.equal(scriptTimers.size,0);assert.match(el('handoffCameraStatus').textContent,/could not be downloaded/);assert.match(el('handoffCameraStatus').textContent,/manual entry/);await lookup('Sender','SHOP1');assert.match(el('handoffSenderInfo').textContent,/Alex Sender/);
  const retryCount=scripts.length,retry=click('handoffReceiverCamera');await flush();assert.equal(scripts.length,retryCount+1);context.Html5Qrcode=Scanner;scripts.at(-1).onload();await retry;camera=cameras.at(-1);await context.FabHandoff.stopCamera();assert.equal(camera.stops,1);
  const preloadedCount=scripts.length;await click('handoffSenderCamera');assert.equal(scripts.length,preloadedCount,'subsequent scans reuse the downloaded library');await context.FabHandoff.stopCamera();

  delete context.Html5Qrcode;const timed=click('handoffSenderCamera');await flush();assert.equal(scriptTimers.size,1);const timer=[...scriptTimers.values()][0];assert.equal(timer.delay,15000);const timedScript=scripts.at(-1);timer.fn();await timed;
  assert.equal(timedScript.removed,true);assert.equal(scriptTimers.size,0);assert.match(el('handoffCameraStatus').textContent,/did not load in time/);

  const beforeAbandoned=cameras.length,abandoned=click('handoffSenderCamera');await flush();const abandonedScript=scripts.at(-1);context.FabHandoff.cancelPending();context.Html5Qrcode=Scanner;abandonedScript.onload();await abandoned;
  assert.equal(cameras.length,beforeAbandoned,'a library arriving after navigation must not start a camera');assert.equal(scriptTimers.size,0);
  delete context.Html5Qrcode;await context.FabHandoff.open({item:'SPL-001'});const stopped=click('handoffSenderCamera');await flush();const stoppedScript=scripts.at(-1);await click('handoffStopCamera');assert.match(el('handoffCameraStatus').textContent,/Camera stopped/);context.Html5Qrcode=Scanner;stoppedScript.onload();await stopped;
  assert.equal(cameras.length,beforeAbandoned,'stopping while the library loads prevents later camera startup');assert.equal(scriptTimers.size,0);
  assert.equal(index,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'));assert.ok(index.indexOf('/static/handoff.js')<index.indexOf('/static/flow.js'));assert.match(index,/FabHandoff\.openBadge/);assert.match(index,/params\.has\('handoff'\)/);assert.doesNotMatch(index,/handler:handoffStaff|findHandoffBadge|function pendingItem/);
  console.log('PASS: two badge identities, current-custodian check, active employees, recorder distinction, catalog selectors, same-custodian updates, snapshot payloads, reset/conflicts, lookup races, camera targets/cleanup, lazy coalesced scanner loading, error/timeout retry, manual fallback, navigation/stop during loading, role-safe credential QR links with an unchanged recorder and no credential storage, location management, and truthful legacy history.');
})().catch(error=>{console.error(error);process.exitCode=1});
