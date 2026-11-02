/* Saved-BOM piece controls with the receiving heat policy. Synthetic records; no network. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const clone=value=>JSON.parse(JSON.stringify(value)),calls=[],events=[],checks=[],records={};
const fields=['supplier','supplier_piece_id','heat_number','mtr_reference','mtr_url','notes'];
const source={document_id:'DOC1',sha256:'a'.repeat(64),filename:'material-list.xlsx'};
const make=(id,{deferred=true,mtr=true}={})=>records[id]={
 context:{kind:'spool',item_id:id,display_code:'SPOOL-'+id},spool_number:'643-TEST',bom_available:true,
 source_status:{current:clone(source),pinned:clone(source),changed:false,expected_bom_sha256:source.sha256},
 traceability:{version:1,configured:true,editable:true,complete:false,...(deferred?{receiving_complete:mtr,heat_numbers_complete:false,heat_required_for_receiving:false,heat_required_from_step:15,heat_required_at_label:'QA/QC-003 - Inspect Welds'}:{}),materials:Array.from({length:3},(_,index)=>({piece_key:'1-'+(index+1),item:1,line_number:1,piece_number:index+1,pieces_on_line:3,piece_label:'Item 1 · Piece '+(index+1),piece_identifier:id+'/MAT-'+(index+1),persisted:true,...Object.fromEntries(fields.map(key=>[key,''])),mtr_reference:mtr?'ACTUAL-MTR-'+(index+1):'',qa001:{code:'QA-001',version:0,status:'pending',can_proceed:false,basis_sha256:'b'.repeat(64),latest:null,permissions:{can_inspect:true},history_url:'/api/spool-boms/spools/'+id+'/materials/1-'+(index+1)+'/qa-001'}}))},
 arrival:{version:0,status:'pending'},mtr_documents:{current:[]}
};
const wrapper=record=>({context:{kind:'spool',item_id:record.context.item_id},spools:[{item_id:record.context.item_id,display_code:record.context.display_code}],selected_spool_id:record.context.item_id,document_id:'DOC1',selection_required:false,record_matches_document:true,record});
let writeError=null;
const assertPass=(record,row)=>{assert.equal(record.source_status.changed,false);assert.ok(row.persisted);assert.ok(row.mtr_reference.trim());assert.ok(record.traceability.heat_required_for_receiving===false||row.heat_number.trim());};
const saveDecision=(row,value)=>{row.qa001.version++;Object.assign(row.qa001,{status:value.result==='Pass'?'passed':'failed',can_proceed:value.result==='Pass',latest:{...value,version:row.qa001.version,actor:'TEST-QA',at:'2026-11-02T10:00:00Z'}});};
const fetch=async(url,options={})=>{
 calls.push({url,...options});const id=url.split('/')[4],record=records[id];assert.ok(record,'Known synthetic spool');
 if(options.method&&writeError)return {ok:false,status:writeError.status,json:async()=>({detail:writeError.message})};
 if(url.includes('/material-records'))return {ok:true,status:200,json:async()=>clone(wrapper(record))};
 const value=options.body?JSON.parse(options.body):null,t=record.traceability;
 if(options.method==='PUT'){
  assert.equal(value.expected_version,t.version);assert.equal(value.expected_bom_sha256,record.source_status.expected_bom_sha256);
  if(value.qa001_guard){const row=t.materials.find(row=>row.piece_key===value.qa001_guard.piece_key);assert.equal(value.qa001_guard.expected_version,row.qa001.version);assert.equal(value.qa001_guard.basis_sha256,row.qa001.basis_sha256);}
  for(const submitted of value.materials){const row=t.materials.find(row=>row.piece_key===submitted.piece_key);Object.assign(row,submitted);row.qa001.basis_sha256='c'.repeat(64);}
  t.version++;t.complete=t.materials.every(row=>row.heat_number.trim()&&row.mtr_reference.trim());if(t.heat_required_for_receiving===false)t.receiving_complete=t.materials.every(row=>row.mtr_reference.trim());
 }else if(url.endsWith('/materials/qa-001/pass-all')){
  assert.equal(value.expected_trace_version,t.version);assert.equal(value.expected_bom_sha256,record.source_status.expected_bom_sha256);assert.equal(value.pieces.length,t.materials.length);let passed=0,already=0;
  for(const row of t.materials){assertPass(record,row);const selected=value.pieces.find(piece=>piece.piece_key===row.piece_key);assert.equal(selected.expected_version,row.qa001.version);assert.equal(selected.basis_sha256,row.qa001.basis_sha256);if(row.qa001.can_proceed){already++;continue;}saveDecision(row,{result:'Pass',reference:value.reference,notes:value.notes});passed++;}
  record.qa001_bulk_result={spool_id:id,passed_count:passed,already_passed_count:already};
 }else if(options.method==='POST'){
  const row=t.materials.find(row=>row.piece_key===url.split('/')[6]);assert.ok(row);assert.equal(value.expected_version,row.qa001.version);assert.equal(value.basis_sha256,row.qa001.basis_sha256);if(value.result==='Pass')assertPass(record,row);saveDecision(row,value);
 }else throw Error('Unexpected request '+url);
 return {ok:true,status:200,json:async()=>clone(record)};
};
const listeners={},host={innerHTML:'',querySelector:()=>null};
const context={URL,AbortController,Intl,Object,Number,Set,fetch,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},document:{addEventListener:(name,handler)=>listeners[name]=handler,dispatchEvent:event=>{events.push(event);listeners[event.type]?.(event);}}};
context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/document-piece-qa.js'),'utf8'),context);
const ui=context.FabDocumentPieceQa,html=()=>host.innerHTML,writes=()=>calls.filter(call=>call.method==='PUT'||call.method==='POST');
async function mount(id){ui.mount({target:{kind:'spools',id},document:{id:'DOC1',bom:{lines:[{item:1,quantity:3,unit:'EA',description:'Test piece'}]}},context:{spool_number:'643-TEST'},host});await new Promise(setImmediate);assert.match(html(),/data-state="ready"/);assert.equal(ui.snapshot().selected,id);}
const action=(name,key='')=>host.onclick({preventDefault(){},target:{closest:selector=>selector==='[data-dpqa-action]'?{disabled:false,dataset:{dpqaAction:name,dpqaKey:key}}:null}});
const choose=(key,result='Pass')=>host.onchange({target:{dataset:{dpqaResult:key},value:result}});
const input=(key,field,value)=>host.oninput({target:{id:'dpqa-'+key+'-'+field,dataset:{dpqaKey:key,dpqaMaterial:field},value,closest:()=>null}});
(async()=>{
 const individual=make('INDIVIDUAL');await mount('INDIVIDUAL');assert.match(html(),/Heat number \(optional until QA\/QC-003 - Inspect Welds\)/);assert.match(html(),/MTR reference \(required for arrival\)/);assert.match(html(),/optional through step 14/);const before=writes().length;choose('1-1');await action('save-qa','1-1');assert.equal(writes().length,before+1);assert.equal(individual.traceability.materials[0].qa001.status,'passed');assert.equal(individual.traceability.materials[1].qa001.status,'pending');assert.ok(individual.traceability.materials.every(row=>row.heat_number===''));assert.equal(individual.traceability.complete,false);assert.equal(individual.arrival.version,0);checks.push('BOM & drawings saves an explicit individual Pass with real MTR and blank heat, leaving other pieces and arrival unchanged');

 const combined=make('COMBINED',{mtr:false});await mount('COMBINED');input('1-1','mtr_reference','INSPECTOR-MTR');choose('1-1');assert.match(html(),/Save material details &amp; Pass/);const beforeCombined=writes().length;await action('save-qa','1-1');assert.equal(writes().length,beforeCombined+2);assert.equal(writes().at(-2).method,'PUT');assert.equal(writes().at(-1).method,'POST');assert.equal(JSON.parse(writes().at(-2).body).materials[0].heat_number,'');assert.equal(combined.traceability.materials[0].mtr_reference,'INSPECTOR-MTR');assert.equal(combined.traceability.materials[0].qa001.status,'passed');assert.ok(combined.traceability.materials.every(row=>row.heat_number===''));checks.push('Combined save and Pass revalidates the new material revision while preserving blank heat and the actual inspector MTR');

 const bulk=make('BULK');await mount('BULK');const beforeBulk=writes().length;await action('pass-all');await action('confirm-pass-all');assert.equal(writes().length,beforeBulk+1);assert.match(writes().at(-1).url,/\/materials\/qa-001\/pass-all$/);assert.ok(bulk.traceability.materials.every(row=>row.qa001.can_proceed&&row.heat_number===''));assert.match(html(),/PASS ALL saved 3 individual decisions/);assert.equal(bulk.arrival.version,0);checks.push('PASS ALL submits every current piece version/basis with deferred heat and does not approve arrival');

 const missing=make('MISSING_MTR',{mtr:false});await mount('MISSING_MTR');const beforeMissing=writes().length;choose('1-1');await action('save-qa','1-1');assert.match(html(),/Enter this piece’s MTR reference/);assert.doesNotMatch(html(),/Enter this piece’s heat number/);await action('pass-all');await action('confirm-pass-all');assert.equal(writes().length,beforeMissing);assert.match(html(),/Save an MTR reference/);assert.ok(missing.traceability.materials.every(row=>row.qa001.status==='pending'));checks.push('Missing MTR still prevents individual and bulk Pass even though the heat field is optional');

 const strict=make('STRICT',{deferred:false});await mount('STRICT');const beforeStrict=writes().length;choose('1-1');await action('save-qa','1-1');assert.match(html(),/Enter this piece’s heat number/);await action('pass-all');await action('confirm-pass-all');assert.equal(writes().length,beforeStrict);assert.match(html(),/Save a heat number/);assert.ok(strict.traceability.materials.every(row=>row.qa001.status==='pending'));checks.push('An older response with no explicit policy keeps heat mandatory for individual and bulk Pass');

 const changed=make('CHANGED');changed.source_status.changed=true;for(const row of changed.traceability.materials)row.qa001.pass_blockers=['Adopt and review the current BOM.'];await mount('CHANGED');const beforeChanged=writes().length;choose('1-1');await action('save-qa','1-1');await action('pass-all');await action('confirm-pass-all');assert.equal(writes().length,beforeChanged);assert.match(html(),/Adopt and review the current BOM/);assert.ok(changed.traceability.materials.every(row=>row.qa001.status==='pending'));checks.push('Deferred heat does not bypass changed-source adoption or server-provided piece prerequisites');

 const stale=make('STALE');await mount('STALE');choose('1-1');writeError={status:409,message:'The material evidence changed'};await action('save-qa','1-1');const afterConflict=writes().length;assert.equal(ui.snapshot().drafts.STALE['1-1'].qa.stale,true);await action('save-qa','1-1');assert.equal(writes().length,afterConflict);assert.equal(stale.traceability.materials[0].qa001.status,'pending');writeError=null;checks.push('A concurrent evidence conflict retains the decision draft and blocks repeat approval until reload');
 console.log(JSON.stringify({status:'passed',contracts:checks.length,checks},null,2));
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
