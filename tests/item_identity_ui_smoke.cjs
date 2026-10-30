/* Identifier-only item registration, CSV and current labels. Synthetic data only. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
const elements=new Map(),writes=[];let templateBlob,printed='';
class Element {
 constructor(id){this.id=id;this.value='';this.innerHTML='';this.textContent='';this.style={};this.disabled=false;this.classList={add(){},remove(){},toggle(){},contains(){return false}};}
 querySelectorAll(){return []}addEventListener(){}showModal(){this.open=true}close(){this.open=false}focus(){}click(){}setAttribute(){}removeAttribute(){}
}
const el=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id)};
const context={console,Date,URL:class extends URL{},URLSearchParams,Blob,setTimeout:()=>0,clearTimeout(){},confirm:()=>false,
 location:{search:'',origin:'https://example.test',reload(){}},history:{replaceState(){}},
 document:{getElementById:el,createElement:()=>new Element('created'),body:{appendChild(){}}},addEventListener(){},
 open:()=>({document:{write(value){printed=value},close(){}}})};
context.window=context;context.URL.createObjectURL=blob=>{templateBlob=blob;return 'blob:synthetic'};context.URL.revokeObjectURL=()=>{};
context.FabPermissions={can:()=>true};
for(const module of ['Orders','Tracking','Flow','Parts','Quality','Dossier','Progress','Guide','Admin'])context['Fab'+module]={cancelPending(){}};
context.FabHandoff={cancelPending(){},historyHtml:()=>''};
vm.createContext(context);vm.runInContext(script,context);
const record={id:'SPL-0001',google_part_number:'00001234',description:'Stored description <hidden>',kind:'Spool',project:'PO-1',location:'Yard',handler:'MC-1',welds_required:0,welds_done:0,reworks:[],inspections:[],permissions:{},released:false};
context.api=async(url,options={})=>{if(options.method){writes.push({url,payload:JSON.parse(options.body)});return record}if(url.startsWith('/api/items?'))return {items:[record],total:1};if(url==='/api/items/SPL-0001')return record;if(url.endsWith('/audit')||url.endsWith('/custody'))return [];throw Error('Unexpected synthetic request '+url)};
(async()=>{
 vm.runInContext("me={role:'admin'};qrStatus={ready:true}",context);
 context.openNewItem({kind:'Spool',project:'PO-1'});
 assert.equal(el('dlg').open,true);assert.doesNotMatch(el('dlgFields').innerHTML,/name="description"|>Description</);assert.match(el('dlgFields').innerHTML,/name="id"/);assert.match(el('dlgFields').innerHTML,/name="google_part_number"/);
 context.newItem={id:'SPL-0001',google_part_number:'00001234',kind:'Spool',project:'PO-1',drawing:'DWG-A',location:'Yard',handler:'MC-1',welds_required:'0'};
 await vm.runInContext('dialogSubmit(newItem)',context);
 assert.equal(writes[0].url,'/api/items');assert.equal(Object.hasOwn(writes[0].payload,'description'),false);assert.equal(writes[0].payload.google_part_number,'00001234');assert.equal(writes[0].payload.welds_required,0);

 const csv='google_part_number,kind,location,handler,quantity,id\n00001234,Spool,Yard,MC-1,2,\n';
 const parsed=context.parseBulk(csv);assert.equal(parsed.errors.length,0);assert.equal(parsed.total,2);assert.equal(parsed.rows[0].description,'');assert.equal(parsed.rows[0].google_part_number,'00001234');
 const legacy=context.parseBulk('google_part_number,description,kind,location,handler\n00005678,"Existing, retained description",Part,Yard,MC-1\n');assert.equal(legacy.errors.length,0);assert.equal(legacy.rows[0].description,'Existing, retained description');
 const invalid=context.parseBulk('google_part_number,kind,location,handler\n,Part,Yard,MC-1\n');assert.match(invalid.errors.join(' '),/missing Google part number/);
 assert.throws(()=>context.parseBulk('google_part_number,kind,location\n00001234,Part,Yard\n'),/Missing required CSV column: handler/);
 context.displayBulkPreview(legacy);assert.doesNotMatch(el('bulkPreview').innerHTML,/Existing, retained description|<th>Description<\/th>/);assert.match(el('bulkPreview').innerHTML,/00005678/);
 context.exportTemplate();const template=await templateBlob.text();assert.equal(template.split(/\r?\n/)[0],'google_part_number,kind,project,drawing,location,handler,welds_required,quantity,id');assert.equal(context.parseBulk(template).errors.length,0);

 await context.listItems();assert.match(el('itemsRows').innerHTML,/SPL-0001/);assert.match(el('itemsRows').innerHTML,/00001234/);assert.doesNotMatch(el('itemsRows').innerHTML,/Stored description/);
 await context.openItem('SPL-0001');assert.equal(el('itemTitle').textContent,'SPL-0001');assert.doesNotMatch(html,/id="itemDescription"/);assert.match(el('itemFields').innerHTML,/00001234/);
 context.printLabelSheet([record]);assert.match(printed,/SPL-0001/);assert.match(printed,/00001234/);assert.doesNotMatch(printed,/Stored description/);assert.match(printed,/\/api\/items\/SPL-0001\/qr.png/);
 assert.equal(fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'),html);
 console.log('PASS: identifier-only item form and API payload; new CSV without description; retained optional legacy CSV text; identity validation; description-free preview/template, current item screens and QR labels; identical HTML shells.');
})().catch(error=>{console.error(error.stack||error);process.exitCode=1});
