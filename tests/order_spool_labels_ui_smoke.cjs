/* Spool-only QR UI contracts. Synthetic data; no network or production writes. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),calls=[],checks=[],routes=[],sheets=[];
const clone=v=>JSON.parse(JSON.stringify(v));
class Element{
  constructor(id){this.id=id;this.value='';this.listeners={};this.children=[];this.attributes={};}
  set innerHTML(value){for(const id of this.children)nodes.delete(id);this.children=[];this.html=value;for(const m of value.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const e=new Element(m[1]);e.value=m[0].match(/\bvalue="([^"]*)"/)?.[1]||'';e.disabled=/\sdisabled(?:\s|>)/.test(m[0]);nodes.set(e.id,e);this.children.push(e.id);}}
  get innerHTML(){return this.html||'';}
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this.attributes[name]=value;}
}
nodes.set('orderLabelsContent',new Element('orderLabelsContent'));
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let remaining=18,remainingWelds=0,unknown=0,items=[],version=1,writeError=null,badLabels=false;
const groups=[{gpn_id:'G1',gpn:'GPN-18',registered_quantity:0}];
const overview=()=>({kind:'Spool',order:{project_id:'P1',purchase_order:'PO-18',version},groups,totals:{registered_quantity:items.length,remaining_quantity:remaining,undeclared_groups:0,remaining_weld_spools:remainingWelds,undeclared_weld_spools:unknown},permissions:{can_manage:true},qr_ready:true,limit:500});
const context={URLSearchParams,Set,Number,Date,me:{role:'admin'},current:null,esc,document:{getElementById:id=>nodes.get(id)||null},history:{replaceState(_a,_b,url){context.url=url;}},show(page){context.FabOrderLabels?.cancelPending();context.page=page;},stopCloudCamera(){},notify(){},FabPermissions:{can:()=>context.me?.role==='admin'},FabOrderSetup:{open:x=>routes.push(x)},openItem:id=>routes.push({item:id}),open(){const sheet={closed:false,html:'',document:{open(){sheet.html='';},write(s){sheet.html+=s;},close(){}},close(){sheet.closed=true;}};sheets.push(sheet);return sheet;},api:async(url,options={})=>{
  calls.push({url,...options});const request=new URL(url,'https://synthetic.example');
  if(request.pathname==='/api/employees/directory')return [{badge:'B1',name:'Training handler'}];
  if(options.method==='POST'){
    if(writeError)throw writeError;
    const count=remaining,initialized=remainingWelds;remaining=0;remainingWelds=0;version++;
    if(count)items=Array.from({length:count},(_,i)=>({id:'SPL-'+String(i+1).padStart(2,'0'),kind:'Spool',flow_stage:{key:i===1?'floor':'welding'},spool_number:'643-777-PCW-03-01',google_part_number:'643-777-PCW-03-01',qr_alias:'643-777-PCW-03-01-['+String(i+1).padStart(3,'0')+']',display_code:'643-777-PCW-03-01-['+String(i+1).padStart(3,'0')+']',purchase_order:'PO-18',assembly_id:'ASM-1',gpn_id:'G1',gpn:'GPN-18',weld_plan_exists:true,welds_per_spool:6,planned_welds:6}));
    return {...overview(),created_count:count?count+1:0,created_spool_count:count,initialized_weld_spool_count:initialized,created_weld_count:6*(count+initialized)};
  }
  if(request.pathname.endsWith('/labels'))return {kind:'Spool',order:overview().order,total:items.length,items:badLabels?[{...items[0],kind:'Assembly'}]:items.slice(Number(request.searchParams.get('offset')||0),Number(request.searchParams.get('offset')||0)+100),qr_ready:true};
  return clone(overview());
}};
context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/flow-status.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/order-labels.js'),'utf8'),context);
const root=()=>nodes.get('orderLabelsContent'),html=()=>root().innerHTML,writes=()=>calls.filter(c=>c.method==='POST');
const click=action=>root().listeners.click({target:{closest:selector=>selector==='[data-ol-action]'?{disabled:false,dataset:{olAction:action}}:null}});
const set=(id,value)=>{const e=nodes.get(id);assert.ok(e,id);e.value=value;if(e.oninput)e.oninput();else if(e.onchange)e.onchange();};
const generate=()=>nodes.get('orderLabelsForm').onsubmit({preventDefault(){}});
(async()=>{
  await context.FabOrderLabels.open({po:'P1',kind:'Assembly'});
  assert.equal(writes().length,0);assert.match(html(),/Spool QR labels/);assert.equal(nodes.has('olKind'),false);assert.doesNotMatch(html(),/GPN \/ Assembly labels|assembly QR|data-ol-plan/);
  assert.ok(calls.filter(c=>c.url.startsWith('/api/order-labels/')).every(c=>new URL(c.url,'https://synthetic.example').searchParams.get('kind')==='Spool'));
  assert.equal(new URL(context.url,'https://synthetic.example').searchParams.get('kind'),'Spool');checks.push('Every entry point resolves only spool labels; opening a screen creates no records');
  await generate();assert.equal(writes().length,0);assert.match(html(),/actual current location/);
  set('olLocation','Receiving');set('olHandler','B1');await generate();assert.equal(writes().length,1);
  assert.deepEqual(JSON.parse(writes()[0].body),{expected_version:1,kind:'Spool',location:'Receiving',handler:'B1'});
  assert.equal((html().match(/class="ol-label"/g)||[]).length,18);assert.equal(new Set(items.map(i=>i.id)).size,18);assert.match(html(),/18 unique spool QR codes created/);assert.match(html(),/6 welds on this spool/);assert.equal(nodes.has('olGenerate'),false);for(const row of items)assert.ok(html().includes('>'+row.qr_alias+'</span></strong>'));assert.match(html(),/643-777-PCW-03-01-\[001\]/);assert.match(html(),/643-777-PCW-03-01-\[018\]/);assert.match(html(),/data-spool-id="SPL-01" class="fst-text fst-color-blue"/);assert.match(html(),/data-spool-id="SPL-02" class="fst-text fst-color-yellow"/);checks.push('One explicit generation displays 18 permanent spool-number aliases with each physical spool’s current color and weld count');
  const before=writes().length;await click('print');assert.equal(sheets.length,1);assert.equal(writes().length,before);assert.equal((sheets[0].html.match(/class="label"/g)||[]).length,18);assert.doesNotMatch(sheets[0].html,/GPN \/ ASSEMBLY|assembly labels|fst-color|data-flow-stage/);assert.match(sheets[0].html,/Assembly ASM-1/);for(const row of items){assert.ok(sheets[0].html.includes('/api/items/'+row.id+'/qr.png'));assert.ok(sheets[0].html.includes('<strong class="label-code">'+row.qr_alias+'</strong>'));assert.ok(!sheets[0].html.includes('<code>'+row.id+'</code>'));}await click('refresh');assert.equal(writes().length,before);checks.push('Print and refresh reuse the 18 spool IDs and include exact assembly context without writes');
  remainingWelds=2;await click('refresh');assert.match(html(),/Create weld records/);assert.ok(nodes.has('olGenerate'));set('olLocation','Receiving');set('olHandler','B1');await generate();assert.match(html(),/Weld records created for 2 spools/);assert.equal(items.length,18);checks.push('Existing spool weld backfill remains available even when all QR codes already exist');
  unknown=2;await click('refresh');assert.match(html(),/Set weld counts/);assert.doesNotMatch(html(),/data-ol-plan/);checks.push('Undeclared legacy weld counts route back to setup and never invent zero or expose a bypass');
  remaining=1;unknown=0;await click('refresh');writeError=Object.assign(Error('Changed in another session'),{status:409});set('olLocation','Receiving');set('olHandler','B1');await generate();const staleCount=writes().length;await generate();assert.equal(writes().length,staleCount);assert.match(html(),/Reload the saved labels/);writeError=null;remaining=0;await click('refresh');checks.push('Concurrent changes stop duplicate generation until the saved state is reloaded');
  context.me={role:'inspector'};await context.FabOrderLabels.open({po:'P1'});assert.equal(nodes.has('olGenerate'),false);assert.match(html(),/administrator or supervisor/);await click('print');assert.equal(sheets.length,2);checks.push('Read-only roles can inspect and reprint spools without generation controls');
  badLabels=true;await click('refresh');assert.match(html(),/could not be verified/);assert.equal((html().match(/class="ol-label"/g)||[]).length,0);checks.push('Unexpected assembly labels fail closed and cannot be printed');
  console.log(JSON.stringify({status:'passed',contracts:checks.length,checks},null,2));
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
