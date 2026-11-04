/* Employee badge printing uses the current server identity and position. No network. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
assert.equal(source,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'),'HTML entry points must stay identical');
for(const match of source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))if(match[1].trim())new vm.Script(match[1]);
const start=source.indexOf('async function printEmployeeBadge('),end=source.indexOf("$('phoneHandoffBtn').onclick",start);
assert.ok(start>=0&&end>start,'Exercise the actual employee badge print function');
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const calls=[],sheets=[],messages=[],checks=[];
let admin=true,blocked=false,mode='ok',resolvePending;
let employee={badge:'EMP-TEST-001',name:'Taylor Example',role:'supervisor',role_label:'Shop Foreman',active:true};
const context={console,esc,encodeURIComponent,qrStatus:{ready:true},
 requireJob:role=>role==='admin'&&admin,
 notify:message=>messages.push(message),
 FabPermissions:{label:()=> 'Outdated local position'},
 api:async(url,options={})=>{
  calls.push({url,...options});assert.equal(url,'/api/employees');assert.equal(options.method,undefined,'Printing must be read-only');
  if(mode==='error')throw Error('Employee roster could not be loaded');
  if(mode==='pending')return new Promise(resolve=>resolvePending=()=>resolve([structuredClone(employee)]));
  if(mode==='missing')return [];
  return [structuredClone(employee)];
 },
 open(){
  if(blocked)return null;
  const sheet={closed:false,html:'',finalOpenCount:0,
   document:{open(){sheet.html='';sheet.finalOpenCount++;},write(value){sheet.html+=value;},close(){}},
   close(){sheet.closed=true;}};
  sheets.push(sheet);return sheet;
 }
};
context.window=context;vm.createContext(context);vm.runInContext(source.slice(start,end),context);
(async()=>{
 for(const [role,label] of [['supervisor','Shop Foreman'],['finisher','Fab Prep Technician'],['pressure_testing_technician','Pressure Testing Technician'],['ndt','NDT'],['fitup_welder','Fit-up welder'],['process_welder','Process welder']]){
  employee={...employee,role,role_label:label};
  const before=calls.length;await context.printEmployeeBadge(employee.badge);
  const sheet=sheets.at(-1);assert.equal(sheet.closed,false);assert.equal(sheet.finalOpenCount,1);assert.equal(calls.length,before+1);
  assert.ok(sheet.html.includes('<h2 class="badge-name">Taylor Example</h2>'));
  assert.ok(sheet.html.includes('<p class="badge-position">'+label+'</p>'));
  assert.ok(sheet.html.includes('<p class="badge-id">EMP-TEST-001</p>'));
  assert.ok(sheet.html.includes('src="/api/employees/EMP-TEST-001/qr.png"'));
  assert.doesNotMatch(sheet.html,/Outdated local position|Assigned to/);
 }
 checks.push('Every current fabrication/testing position prints below the employee name with the original badge QR endpoint');

 employee={...employee,name:'Taylor <Lead> & "QA"',role_label:'Current <position> & "Team"'};
 await context.printEmployeeBadge(employee.badge);
 const escaped=sheets.at(-1).html;
 assert.match(escaped,/<h2 class="badge-name">Taylor &lt;Lead&gt; &amp; &quot;QA&quot;<\/h2>/);
 assert.match(escaped,/<p class="badge-position">Current &lt;position&gt; &amp; &quot;Team&quot;<\/p>/);
 assert.doesNotMatch(escaped,/<Lead>|<position>/);
 checks.push('Fresh server name and position override stale client labels and are escaped safely in print HTML');

 for(const invalid of [{active:false},{badge_signin:{enabled:false,version:2}},{name:''},{role_label:''},{role_label:undefined}]){
  const saved=employee;employee={...employee,...invalid};await context.printEmployeeBadge(employee.badge);
  assert.equal(sheets.at(-1).closed,true);assert.equal(sheets.at(-1).finalOpenCount,0);employee=saved;
 }
 for(const failure of ['missing','error']){
  mode=failure;await context.printEmployeeBadge(employee.badge);assert.equal(sheets.at(-1).closed,true);assert.equal(sheets.at(-1).finalOpenCount,0);
 }
 mode='ok';checks.push('Missing, inactive, disabled sign-in, incomplete or failed employee reads cannot print a stale or nameless badge');

 let beforeSheets=sheets.length,beforeCalls=calls.length;
 admin=false;await context.printEmployeeBadge(employee.badge);admin=true;
 context.qrStatus.ready=false;await context.printEmployeeBadge(employee.badge);context.qrStatus.ready=true;
 blocked=true;await context.printEmployeeBadge(employee.badge);blocked=false;
 assert.equal(sheets.length,beforeSheets);assert.equal(calls.length,beforeCalls);
 checks.push('Administrator, public QR configuration and popup checks run before preparing a badge');

 mode='pending';const pending=context.printEmployeeBadge(employee.badge);const closed=sheets.at(-1);closed.close();resolvePending();await pending;
 assert.equal(closed.finalOpenCount,0);checks.push('Closing a loading preview does not reopen or populate the closed print window');
 console.log(JSON.stringify({status:'passed',contracts:checks.length,checks},null,2));
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
