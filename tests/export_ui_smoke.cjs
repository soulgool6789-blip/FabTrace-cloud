/* Run with node tests/export_ui_smoke.cjs. Synthetic download responses only. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
const script=source.match(/\/\/ Excel export:[\s\S]*?\/\/ End Excel export\./)?.[0];
assert.ok(script,'export handler must be present');
assert.match(source,/<button id="navExportExcel" class="hidden" type="button">Export Excel<\/button>/);
assert.match(source,/\$\('navExportExcel'\)\.classList\.toggle\('hidden',me\.role!=='admin'\)/);
assert.equal(fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'),source,'shell copies must match');

function setup(role='admin'){
 const button={disabled:false,textContent:'Export Excel',attributes:{},setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]}};
 const calls=[],downloads=[],revoked=[],timers=[],messages=[];
 const context={
  me:{role},$:id=>{assert.equal(id,'navExportExcel');return button},notify:message=>messages.push(message),
  URL:{createObjectURL:blob=>{assert.equal(blob,'workbook-blob');return 'blob:test-export'},revokeObjectURL:url=>revoked.push(url)},
  document:{body:{appendChild(){}},createElement(tag){assert.equal(tag,'a');return {href:'',download:'',click(){downloads.push({href:this.href,name:this.download})},remove(){}}}},
  setTimeout:fn=>{timers.push(fn)},
  fetch:async(url,options)=>{calls.push({url,options});return context.response},
  response:{ok:true,status:200,headers:{get(name){return name==='content-type'?'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':name==='content-disposition'?'attachment; filename="fabtrace-export-20261028T190000Z.xlsx"':null}},blob:async()=> 'workbook-blob'},
 };
 vm.createContext(context);vm.runInContext(script,context);
 return {context,button,calls,downloads,revoked,timers,messages};
}
(async()=>{
 const success=setup();
 await success.button.onclick();
 assert.equal(success.calls.length,1);
 assert.equal(success.calls[0].url,'/api/exports/excel');
 assert.equal(success.calls[0].options.credentials,'same-origin');
 assert.equal(success.downloads[0].name,'fabtrace-export-20261028T190000Z.xlsx');
 assert.equal(success.button.disabled,false);assert.equal(success.button.textContent,'Export Excel');
 assert.match(success.messages.at(-1),/download started/);
 success.timers.forEach(fn=>fn());assert.deepEqual(success.revoked,['blob:test-export']);

 const blocked=setup('supervisor');await blocked.button.onclick();
 assert.equal(blocked.calls.length,0);assert.match(blocked.messages[0],/administrator/);

 const expired=setup();expired.context.response={ok:false,status:401,json:async()=>({detail:'Badge login required'})};
 await expired.button.onclick();assert.equal(expired.downloads.length,0);assert.equal(expired.button.disabled,false);assert.match(expired.messages[0],/Sign in again/);

 const invalid=setup();invalid.context.response.headers.get=()=> 'text/html';
 await invalid.button.onclick();assert.equal(invalid.downloads.length,0);assert.match(invalid.messages[0],/did not return an Excel workbook/);

 const busy=setup();let resolve;
 busy.context.fetch=async()=>{busy.calls.push('fetch');return new Promise(r=>{resolve=r})};
 const first=busy.button.onclick();
 assert.equal(busy.button.disabled,true);assert.equal(busy.button.attributes['aria-busy'],'true');
 await busy.button.onclick();assert.equal(busy.calls.length,1,'repeated clicks must not create parallel exports');
 resolve(busy.context.response);await first;assert.equal(busy.button.disabled,false);

 assert.equal(success.context.excelDownloadName('attachment; filename="../record.xlsx"'),'.._record.xlsx');
 assert.equal(success.context.excelDownloadName('attachment; filename="not-a-workbook.html"'),'fabtrace-export.xlsx');
 console.log('PASS: admin visibility, authenticated XLSX download, filename handling, object-URL cleanup, expired-session error, response validation, and duplicate-click prevention.');
})().catch(error=>{console.error(error);process.exitCode=1});
