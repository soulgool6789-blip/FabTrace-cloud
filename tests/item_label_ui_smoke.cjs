/* Item, search and import QR labels. Synthetic records only; no network. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
assert.equal(source,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'),'HTML entry points must stay identical');
for(const match of source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))if(match[1].trim())new vm.Script(match[1]);
const clone=value=>JSON.parse(JSON.stringify(value)),nodes=new Map(),calls=[],sheets=[],messages=[],checks=[];
const element=id=>{if(!nodes.has(id))nodes.set(id,{id,innerHTML:'',textContent:'',style:{},disabled:false});return nodes.get(id);};
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const records={
 SPOOL:{id:'SPOOL',kind:'Spool',display_code:'643-TEST-[001]',qr_alias:'643-TEST-[001]',purchase_order:'PO-001',gpn:'GPN-002',assembly_number:'ACTUAL-003',part_number:'',handler:'B1',handler_name:'Alex <Lead> & "QA"',download_url:'/api/order-labels/items/SPOOL/download.svg'},
 UNMAPPED:{id:'UNMAPPED',kind:'Spool',display_code:'643-UNMAPPED-[001]',purchase_order:'',gpn:'',assembly_number:'',part_number:'',handler:'B2',handler_name:'Current unmapped employee',download_url:'/api/order-labels/items/UNMAPPED/download.svg'},
 PART:{id:'PART',kind:'Part',display_code:'PART',purchase_order:'',gpn:'',assembly_number:'',part_number:'REAL-PART-01',handler:'B3',handler_name:'Current part employee',download_url:'/api/order-labels/items/PART/download.svg'}
};
let mode='ok',releasePending=null;
const context={URLSearchParams,Set,Promise,console,qrStatus:{ready:true},location:{origin:'https://synthetic.example'},
 $:element,esc,notify:message=>messages.push(message),itemNumberLabel:item=>item.display_code||item.id,
 decorateItemNumber:(node,_item,text)=>node.textContent=text,bulkCreated:[],bulkPrintIndex:0,
 api:async(url,options={})=>{
  calls.push({url,...options});assert.equal(options.method,undefined,'Printing is read-only');
  const query=new URL(url,'https://synthetic.example');assert.equal(query.pathname,'/api/order-labels/items/preview');
  const ids=query.searchParams.getAll('item_id');assert.ok(ids.length<=100);
  const data={qr_ready:true,items:ids.map(id=>clone(records[id]))};
  if(mode==='error')throw Object.assign(Error('Selected item was removed'),{status:404});
  if(mode==='missing')data.items.pop();
  if(mode==='reordered')data.items.reverse();
  if(mode==='pending')return new Promise(resolve=>releasePending=()=>resolve(data));
  return data;
 },
 open(){const sheet={closed:false,html:'',document:{open(){sheet.html='';},write(value){sheet.html+=value;},close(){}},close(){sheet.closed=true;}};sheets.push(sheet);return sheet;}
};
context.window=context;vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function qrLabelFields('),source.indexOf('async function openItem(')),context);
vm.runInContext(source.slice(source.indexOf('function updateBulkLabelProgress('),source.indexOf("$('printSearchLabels').onclick")),context);
const selected=(...ids)=>ids.map(id=>({id,kind:records[id]?.kind||'Assembly',handler:'STALE-BADGE',handler_name:'Stale selected employee'}));
async function printScript(sheet,success){
 const script=sheet.html.match(/<script>([\s\S]*?)<\/script>/)?.[1];assert.ok(script);
 const dom={printButton:{disabled:true},printStatus:{textContent:''},closeButton:{}},printCalls=[];
 const run={document:{getElementById:id=>dom[id],images:[{complete:true,naturalWidth:success?100:0}]},setTimeout:(callback,delay)=>{if(delay===250)callback();return 1;},clearTimeout(){},Promise};
 run.window={print:()=>printCalls.push(true),close(){}};vm.runInNewContext(script,run);await new Promise(setImmediate);
 return {dom,printCalls};
}
(async()=>{
 const item={id:'SPOOL',kind:'Spool',display_code:records.SPOOL.display_code,handler:'B1',assembly_id:'ASM-TECHNICAL',qr_url:'https://synthetic.example/?spool=643-TEST-%5B001%5D',qr_label:clone(records.SPOOL)};
 context.renderItemQrLabel(item);
 assert.equal(element('qrImage').src,'/api/items/SPOOL/qr.png');assert.equal(element('qrDownload').href,records.SPOOL.download_url);assert.equal(element('qrDownload').download,'643-TEST-[001]-label.svg');assert.equal(element('qrDownload').style.display,'');
 assert.match(element('qrLabelDetails').innerHTML,/Assigned to/);assert.match(element('qrLabelDetails').innerHTML,/Alex &lt;Lead&gt; &amp; &quot;QA&quot; · B1/);assert.match(element('qrLabelDetails').innerHTML,/Assembly Number:<\/strong> ACTUAL-003/);assert.match(element('qrLabelDetails').innerHTML,/GPN:<\/strong> GPN-002/);assert.doesNotMatch(element('qrLabelDetails').innerHTML,/ASM-TECHNICAL|<Lead>/);
 assert.equal(element('qrCodeName').textContent,records.SPOOL.display_code);checks.push('Item QR cards show escaped own-employee names and separate real business identifiers, while full downloads retain the old bare QR source');

 context.renderItemQrLabel({id:'UNMAPPED',kind:'Spool',display_code:records.UNMAPPED.display_code,handler:'B2',qr_label:clone(records.UNMAPPED)});
 assert.match(element('qrLabelDetails').innerHTML,/Current unmapped employee/);assert.doesNotMatch(element('qrLabelDetails').innerHTML,/P\.O\.|GPN|Assembly Number/);assert.equal(element('qrDownload').href,records.UNMAPPED.download_url);
 context.renderItemQrLabel({id:'ASSEMBLY',kind:'Assembly',handler:'B1',qr_eligible:false,qr_label:null});assert.equal(element('qrImage').style.display,'none');assert.equal(element('qrDownload').style.display,'none');assert.equal(element('qrLabelDetails').innerHTML,'');assert.match(element('qrLink').textContent,/individual spools/);checks.push('Unmapped spools retain truthful available captions and assemblies have no QR download');

 records.SPOOL.handler='B4';records.SPOOL.handler_name='New <assigned> employee';
 const before=calls.length;assert.equal(await context.printLabelSheet([...selected('SPOOL','UNMAPPED','PART'),{id:'ASSEMBLY',kind:'Assembly'}]),true);
 assert.equal(calls.length,before+1);const sheet=sheets.at(-1);assert.equal((sheet.html.match(/class="label"/g)||[]).length,3);assert.match(sheet.html,/New &lt;assigned&gt; employee · B4/);assert.doesNotMatch(sheet.html,/Stale selected employee|ASM-TECHNICAL/);assert.match(sheet.html,/ACTUAL-003/);assert.match(sheet.html,/>PART<\/small>/);assert.match(sheet.html,/Google part number:<\/b> REAL-PART-01/);assert.match(sheet.html,/width:1\.05in;height:1\.05in/);assert.match(sheet.html,/min-height:2\.2in/);for(const id of ['SPOOL','UNMAPPED','PART'])assert.ok(sheet.html.includes('/api/items/'+id+'/qr.png'));checks.push('Search/import sheets refresh exact selected IDs in one read, include current assignment and real context, preserve ordinary PART labels and existing QR dimensions');

 const ready=await printScript(sheet,true);assert.equal(ready.dom.printButton.disabled,false);assert.equal(ready.printCalls.length,1);const failed=await printScript(sheet,false);assert.equal(failed.dom.printButton.disabled,true);assert.equal(failed.printCalls.length,0);assert.match(failed.dom.printStatus.textContent,/could not load/);checks.push('The shared print sheet waits for successful QR images and does not print an unreadable failed image');

 for(const problem of ['error','missing','reordered']){mode=problem;assert.equal(await context.printLabelSheet(selected('SPOOL','PART')),false);assert.equal(sheets.at(-1).closed,true);}mode='ok';assert.match(messages.at(-1),/could not be verified/);checks.push('Removed, missing or mismatched preview records close the sheet and fail without printing stale labels');

 const sheetsBefore=sheets.length,callsBefore=calls.length;mode='pending';const pending=context.printLabelSheet(selected('SPOOL'));assert.equal(sheets.length,sheetsBefore+1);assert.equal(await context.printLabelSheet(selected('PART')),false);assert.equal(calls.length,callsBefore+1);releasePending();assert.equal(await pending,true);mode='ok';checks.push('Overlapping print clicks prepare one sheet and issue one bounded read');

 context.bulkCreated=selected('SPOOL','PART');context.bulkPrintIndex=0;mode='error';await element('bulkPrint').onclick();assert.equal(context.bulkPrintIndex,0);mode='ok';await element('bulkPrint').onclick();assert.equal(context.bulkPrintIndex,2);assert.equal(element('bulkPrint').disabled,true);checks.push('Bulk printing advances its cursor only after the refreshed label sheet succeeds');

 context.bulkCreated=selected('SPOOL','PART');context.bulkPrintIndex=0;mode='pending';const oldBatch=element('bulkPrint').onclick();context.bulkCreated=selected('UNMAPPED');context.bulkPrintIndex=0;releasePending();await oldBatch;assert.equal(context.bulkPrintIndex,0);mode='ok';checks.push('A new import or search selection during preparation cannot advance the replacement batch cursor');

 const beforeBound=sheets.length;assert.equal(await context.printLabelSheet(Array.from({length:101},(_,i)=>({id:'EXCESS-'+i,kind:'Spool'}))),false);assert.equal(sheets.length,beforeBound);context.qrStatus.ready=false;assert.equal(await context.printLabelSheet(selected('SPOOL')),false);context.renderItemQrLabel(item);assert.equal(element('qrDownload').style.display,'none');assert.equal(sheets.length,beforeBound);checks.push('Print batches stay bounded at 100 and unavailable public QR configuration cannot produce a broken label');
 console.log(JSON.stringify({status:'passed',contracts:checks.length,checks},null,2));
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
