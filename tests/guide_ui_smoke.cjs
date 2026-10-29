/* Read-only Guide & setup contracts. Synthetic records only; no server or production access. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const elements=new Map(),decode=v=>v.replace(/&(amp|lt|gt|quot|#39);/g,(_m,k)=>({amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"}[k]));
class Element{
  constructor(id){this.id=id;this.listeners={};this.attributes={};this.children=[];this.value='';this.disabled=false;this.classes=new Set();this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),contains:x=>this.classes.has(x)};}
  set innerHTML(html){
    for(const id of this.children)elements.delete(id);this.children=[];this.html=html;
    for(const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const child=new Element(decode(match[1]));child.value=decode(match[0].match(/\bvalue="([^"]*)"/)?.[1]||'');elements.set(child.id,child);this.children.push(child.id);}
    for(const match of html.matchAll(/<select[^>]+id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){const opts=[...match[2].matchAll(/<option value="([^"]*)"([^>]*)>/g)];elements.get(decode(match[1])).value=decode((opts.find(v=>v[2].includes('selected'))||opts[0])?.[1]||'');}
  }
  get innerHTML(){return this.html||'';}addEventListener(name,fn){this.listeners[name]=fn;}setAttribute(name,value){this.attributes[name]=value;}focus(){this.focused=true;}setSelectionRange(){}scrollIntoView(){}
}
for(const id of ['guideContent','navGuide','body'])elements.set(id,new Element(id));
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function complete(id='P1',name='Kelvion <project>'){
  const project={id,name,client:'Customer & QA'},latest={id:21,kind:'project',revision:2,current:true};
  const dispatch={id:201,issue_id:21,channel:'digital',event:'dispatch',occurred_on:'2026-10-29',reference:'SEND <current>'};
  const receipt={id:202,issue_id:21,channel:'digital',event:'receipt',dispatch_id:201,occurred_on:'2026-10-29',reference:'ACK <current>'};
  return {progress:{project,counts:{total_parts:3,finished:3,planning_needed:0},as_of:'2026-10-29T12:00:00Z',items:[
    {id:'C1',description:'Prepared component',kind:'component',fabrication_finished:true,status:'finished',blockers:[]},
    {id:'S1',description:'Shipped spool',kind:'spool',fabrication_finished:true,status:'shipped',blockers:[]},
    {id:'A1',description:'Delivered assembly',kind:'assembly',fabrication_finished:true,status:'delivered',blockers:[]}
  ]},dossier:{project,configured:true,config:{expected_packets:2},source_status:'confirmed',documents:[{id:1,current:true},{id:2,current:false}],
    items:['S1','A1'].map((item_id,i)=>({item_id,percent:100,latest_issue:{id:11+i,current:true}})),latest_project_issue:latest,completion_blockers:[],
    issues:[latest,{id:20,kind:'project',revision:1,current:false}],handovers:[
      {id:101,issue_id:20,channel:'physical',event:'dispatch',occurred_on:'2026-10-28',reference:'SEND <old>'},
      {id:102,issue_id:20,channel:'physical',event:'receipt',dispatch_id:101,occurred_on:'2026-10-28',reference:'ACK <old>'},dispatch,receipt
    ],transfer_status:{digital:{status:'received',dispatch,receipt},physical:{status:'not_dispatched',dispatch:null,receipt:null}},permissions:{manage:false,write:false,review:false}}};
}
let responses=new Map(),failures=new Map(),holds=new Map(),printFailure=null;
const calls=[],messages=[],prints=[],routes=[];
function setProjects(...fixtures){
  responses=new Map([
    ['/api/progress/projects',{projects:fixtures.map(f=>({...f.progress.project,...f.progress.counts}))}],
    ['/api/dossier/projects',{projects:fixtures.map(f=>({...f.dossier.project,configured:!!f.dossier.config,summary:{items:f.dossier.items?.length}}))}]
  ]);
  for(const f of fixtures){const id=encodeURIComponent(f.progress.project.id);responses.set('/api/progress/projects/'+id,f.progress);responses.set('/api/dossier/projects/'+id,f.dossier);}
}
const context={document:{getElementById:id=>elements.get(id)||null,body:elements.get('body')},me:null,current:'previous item',URLSearchParams,Date,esc,
  history:{replaceState(_a,_b,url){context.url=url;}},show(page){context.page=page;},stopCloudCamera(){context.cameraStopped=true;},notify:x=>messages.push(x),
  openItem:id=>routes.push({module:'item',id}),listItems:()=>routes.push({module:'items'}),
  print(){prints.push({html:html(),printing:elements.get('body').classList.contains('fg-printing')});if(printFailure)throw printFailure;},
  api:async(url,options={})=>{
    calls.push({url,...options});assert.ok(!options.method||options.method==='GET','guide requests must remain read-only');assert.equal(options.body,undefined);
    assert.ok(responses.has(url),'unexpected guide API route: '+url);const response=structuredClone(responses.get(url)),failure=failures.get(url),hold=holds.get(url);
    if(hold)await hold;if(failure)throw failure;return response;
  }
};
for(const name of ['Tracking','Progress','Dossier','Flow','Quality','Parts','Admin'])context['Fab'+name]={open:options=>routes.push({module:name.toLowerCase(),...options})};
context.window=context;vm.createContext(context);require('./ui_permissions_fixture.cjs').install(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/guide.js'),'utf8'),context);
const html=()=>elements.get('guideContent').innerHTML;
const click=(action,id='',tab='')=>elements.get('guideContent').listeners.click({target:{closest:()=>({disabled:false,dataset:{guideAction:action,guideId:id,guideTab:tab}})}});
const input=(id,value)=>{elements.get(id).value=value;return elements.get(id).oninput();};
const select=(id,value)=>{elements.get(id).value=value;return elements.get(id).onchange();};
const status=id=>{const result=html().match(new RegExp('data-guide-stage="'+id+'" data-guide-status="([^"]+)"'));assert.ok(result,'stage '+id+' must be displayed');return result[1];};
const topics=()=>[...html().matchAll(/class="fg-card fg-topic" id="guide-topic-([^"]+)"/g)].map(v=>v[1]);
const transfer=channel=>{const result=html().match(new RegExp('<article class="fg-transfer"><h3>'+channel+' packet</h3>([\\s\\S]*?)</article>'));assert.ok(result);return result[1];};
const pending=()=>{let release;const promise=new Promise(resolve=>release=resolve);return {promise,release};};
const checks=[];
async function check(name,fn){await fn();checks.push(name);}
(async()=>{
  await check('authentication and exact read-only routes',async()=>{
    await context.FabGuide.open({project:'P1'});assert.equal(calls.length,0);assert.equal(context.page,undefined);assert.equal(html(),'');
    context.me={role:'handler'};setProjects(complete(),complete('P2','Other project'));
    await elements.get('navGuide').onclick();assert.equal(context.page,'guidePage');assert.equal(context.current,null);assert.equal(context.cameraStopped,true);
    assert.deepEqual(calls.map(c=>c.url),['/api/progress/projects','/api/dossier/projects']);assert.match(html(),/Kelvion &lt;project&gt;/);assert.match(html(),/Customer &amp; QA/);
    const before=calls.length;await context.FabGuide.open({project:'P1',section:'flow'});
    assert.deepEqual(calls.slice(before).map(c=>c.url),['/api/progress/projects','/api/dossier/projects','/api/progress/projects/P1','/api/dossier/projects/P1']);
    assert.equal(context.url,'/?guide=1&project=P1&section=flow');assert.deepEqual(topics(),['flow']);
  });
  await check('empty and zero scope never means finished',async()=>{
    setProjects();await context.FabGuide.open();assert.match(html(),/No structured projects are registered/);assert.doesNotMatch(html(),/data-guide-status="done"/);assert.ok(topics().length>=10);
    const f=complete();f.progress.counts={total_parts:0,finished:0,planning_needed:0};f.progress.items=[];f.dossier.items=[];f.dossier.config.expected_packets=0;f.dossier.latest_project_issue=null;
    setProjects(f);await context.FabGuide.open({project:'P1'});
    for(const id of ['scope','config','fabrication','packets','issue'])assert.notEqual(status(id),'done',id+' cannot complete on zero scope');
    assert.match(html(),/Zero registered items never mean complete/);assert.match(html(),/Confirm the complete approved BOM/);
  });
  await check('current issued project and exact-revision handover',async()=>{
    setProjects(complete());await context.FabGuide.open({project:'P1'});
    for(const id of ['scope','config','source','files','fabrication','packets','issue'])assert.equal(status(id),'done',id);
    assert.match(html(),/3 of 3 registered physical item\(s\) currently finished/);assert.match(html(),/2 of 2 registered spool\/assembly packet\(s\)/);
    assert.match(html(),/This checks availability only/);assert.match(html(),/does not establish contract acceptance/);
    assert.match(transfer('Digital'),/Current project revision 2/);assert.match(transfer('Digital'),/fg-done">Receipt recorded/);
    assert.match(transfer('Digital'),/ACK &lt;current&gt;/);assert.match(transfer('Physical'),/Not recorded · if required/);
    assert.match(transfer('Physical'),/Historical revision 1/);assert.match(transfer('Physical'),/ACK &lt;old&gt;/);assert.doesNotMatch(transfer('Physical'),/fg-done/);
    assert.match(html(),/missing optional channel is not classified as a contract failure/);
  });
  await check('unconfigured and incomplete records cannot invent readiness',async()=>{
    const f=complete();f.dossier.config=null;f.dossier.configured=false;f.dossier.source_status='needs_confirmation';f.dossier.documents=[];
    f.dossier.items.forEach(p=>{p.latest_issue=null;p.percent=0;});f.dossier.latest_project_issue=null;f.dossier.completion_blockers=['Configure project Job Packets first'];
    setProjects(f);await context.FabGuide.open({project:'P1'});
    assert.match(html(),/No Job Packet configuration is recorded/);for(const id of ['config','source','files','packets','issue'])assert.notEqual(status(id),'done',id);
    const incomplete=complete();delete incomplete.progress.counts;delete incomplete.progress.items;delete incomplete.dossier.items;delete incomplete.dossier.completion_blockers;
    setProjects(incomplete);await context.FabGuide.refresh();for(const id of ['scope','config','fabrication','packets','issue'])assert.notEqual(status(id),'done',id+' needs verified data');
    assert.match(html(),/Unknown number of registered physical item/);
  });
  await check('scope, source, fabrication and packet gates are separate',async()=>{
    const cases=[
      ['source',f=>{f.dossier.source_status='needs_confirmation';}],
      ['config',f=>{f.dossier.config.expected_packets=3;}],
      ['scope',f=>{f.progress.items[0].kind='unplanned';f.progress.counts.planning_needed=1;}],
      ['fabrication',f=>{f.progress.items[0].fabrication_finished=false;f.progress.counts.finished=2;}],
      ['packets',f=>{f.dossier.items[0].latest_issue.current=false;}],
      ['issue',f=>{f.dossier.completion_blockers=['Actual QA acceptance remains <required>'];}],
      ['scope',f=>{f.progress.items.pop();}],
      ['config',f=>{f.dossier.config.expected_packets='2';}]
    ];
    for(const [id,change] of cases){const f=complete();change(f);setProjects(f);await context.FabGuide.refresh();assert.notEqual(status(id),'done',id+' must respect its actual basis');assert.notEqual(status('issue'),'done','a current issue flag cannot replace '+id+' verification');}
    const f=complete();f.dossier.latest_project_issue=null;setProjects(f);await context.FabGuide.refresh();assert.equal(status('packets'),'done');assert.equal(status('issue'),'pending','100% checks and current item packets do not create a project issue');
  });
  await check('stale issues retain receipt history without claiming current completion',async()=>{
    const f=complete();f.dossier.latest_project_issue.current=false;f.dossier.items[0].latest_issue.current=false;
    f.dossier.completion_blockers=['S1: current revision <changed>'];setProjects(f);await context.FabGuide.refresh();
    assert.equal(status('issue'),'historical');assert.match(html(),/current revision &lt;changed&gt;/);
    for(const channel of ['Digital','Physical']){assert.match(transfer(channel),/Awaiting a current completed-project issue/);assert.match(transfer(channel),/Historical revision/);assert.match(transfer(channel),/Receipt recorded/);assert.match(transfer(channel),/This is history, not current completion or delivery/);assert.doesNotMatch(transfer(channel),/fg-done/);}
    const mismatched=complete();mismatched.dossier.transfer_status.digital.dispatch.issue_id=20;
    setProjects(mismatched);await context.FabGuide.refresh();assert.doesNotMatch(transfer('Digital'),/fg-done/,'an old issue dispatch cannot satisfy the current revision');
    const wrongReceipt=complete();wrongReceipt.dossier.transfer_status.digital.receipt.dispatch_id=999;
    setProjects(wrongReceipt);await context.FabGuide.refresh();assert.match(transfer('Digital'),/fg-done">Dispatched/);assert.doesNotMatch(transfer('Digital'),/fg-done">Receipt recorded/);
  });
  await check('partial API failure clears readiness while preserving the operating guide',async()=>{
    setProjects(complete());await context.FabGuide.refresh();assert.equal(status('issue'),'done');
    failures.set('/api/dossier/projects/P1',Error('Service <temporarily> unavailable'));await context.FabGuide.refresh();
    assert.match(html(),/Setup status could not be verified/);assert.match(html(),/Service &lt;temporarily&gt; unavailable/);assert.match(html(),/Missing status is not completion/);
    assert.doesNotMatch(html(),/data-guide-stage=/);assert.ok(topics().length>=10);failures.clear();await click('refresh');assert.equal(status('issue'),'done');
    responses.set('/api/progress/projects',{});await context.FabGuide.refresh();assert.match(html(),/project lists could not be verified/);assert.doesNotMatch(html(),/data-guide-stage=/);
  });
  await check('roles explain ownership without granting mutations',async()=>{
    setProjects(complete());
    const roles={handler:/Material coordination/,welder:/root and fill/,fitup_welder:/Fit-up and tack/,process_welder:/PWHT/,painter:/Sandblast and paint/,finisher:/Component preparation/,misc:/General support/,supervisor:/specialized work and QA acceptance/,inspector:/QA\/QC inspections/,admin:/Full site administration/};
    const allowed=new Set(['topic','refresh','project','tracking','progress','dossier','item','flow-item','packet','print','clear','items','flow','quality','parts','admin']);
    for(const [role,expectation] of Object.entries(roles)){context.me.role=role;await context.FabGuide.open({project:'P1'});const note=html().match(/<p class="fg-role">([\s\S]*?)<\/p>/)[1];assert.match(note,expectation);assert.match(note,/only reads existing records/);for(const m of html().matchAll(/data-guide-action="([^"]+)"/g))assert.ok(allowed.has(m[1]),'guide must navigate to the permission-enforcing screen: '+m[1]);}
    assert.equal(calls.filter(c=>c.method&&c.method!=='GET').length,0);
  });
  await check('dynamic labels, IDs, errors and query values are escaped',async()=>{
    const id='P<&"/1',f=complete(id,'<img src=x onerror=alert(1)>');f.progress.items[0].fabrication_finished=false;
    f.progress.items[0].id='C"<unsafe>';f.progress.items[0].description='<script>unsafe</script>';f.progress.items[0].blockers=['Hold <blocked>'];
    f.dossier.completion_blockers=['QA <required>'];setProjects(f);context.me.role='<employee>';await context.FabGuide.open({project:id});
    assert.match(html(),/Your role: &lt;employee&gt;/);assert.match(html(),/&lt;img src=x onerror=alert\(1\)&gt;/);assert.match(html(),/&lt;script&gt;unsafe&lt;\/script&gt;/);assert.match(html(),/Hold &lt;blocked&gt;/);assert.match(html(),/QA &lt;required&gt;/);
    assert.match(html(),/data-guide-id="C&quot;&lt;unsafe&gt;"/);assert.doesNotMatch(html(),/data-guide-action="packet" data-guide-id="C&quot;&lt;unsafe&gt;"/,'components do not receive invented item packets');assert.doesNotMatch(html(),/<script>|<img src=x/);assert.equal(new URL(context.url,'https://example.test').searchParams.get('project'),id);
    assert.ok(calls.some(c=>c.url==='/api/progress/projects/'+encodeURIComponent(id)));input('guideSearch','"<input unsafe>');assert.match(html(),/value="&quot;&lt;input unsafe&gt;"/);assert.doesNotMatch(html(),/<input unsafe>/);
    context.me.role='handler';
  });
  await check('guide search, topic deep links and full printing preserve the selected project',async()=>{
    setProjects(complete(),complete('P2','Other project'));await context.FabGuide.open();input('guideProjectSearch','P1');
    assert.doesNotMatch(html(),/<h3>Other project<\/h3>/);assert.match(html(),/<h3>Kelvion &lt;project&gt;<\/h3>/);
    await select('guideProject','P1');assert.equal(new URL(context.url,'https://example.test').searchParams.get('project'),'P1');const total=topics().length,before=calls.length;
    input('guideSearch','8 MiB');assert.deepEqual(topics(),['packet-setup']);input('guideSearch','no-such-topic-xyz');assert.match(html(),/No guide topics match/);
    await click('clear');await select('guideSection','flow');assert.deepEqual(topics(),['flow']);assert.match(context.url,/section=flow/);
    await click('print');assert.equal(prints.at(-1).printing,true);assert.equal([...prints.at(-1).html.matchAll(/class="fg-card fg-topic"/g)].length,total);
    assert.match(prints.at(-1).html,/Project setup checklist · Kelvion &lt;project&gt;/);assert.deepEqual(topics(),['flow']);assert.equal(elements.get('body').classList.contains('fg-printing'),false);assert.equal(calls.length,before,'search, filtering and print never fetch or mutate records');
    printFailure=Error('Print unavailable');await click('print');assert.equal(elements.get('body').classList.contains('fg-printing'),false);assert.deepEqual(topics(),['flow']);assert.equal(messages.at(-1),'Print unavailable');printFailure=null;
    await context.FabGuide.open({project:'P1',section:'invalid'});assert.equal(topics().length,total);assert.doesNotMatch(context.url,/section=/);await click('topic');assert.equal(elements.get('guideSearch').focused,true);
  });
  await check('project shortcuts clear tracking filters and reach exact records',async()=>{
    await click('tracking');assert.deepEqual(routes.at(-1),{module:'tracking',project:'P1',subproject:'',view:'spools',resetFilters:true});
    await click('progress');assert.deepEqual(routes.at(-1),{module:'progress',project:'P1'});await click('parts');assert.deepEqual(routes.at(-1),{module:'parts',project:'P1'});
    for(const tab of ['items','documents','issues','handovers']){await click('dossier','P1',tab);assert.deepEqual(routes.at(-1),{module:'dossier',project:'P1',tab});}
    await click('packet','S1');assert.deepEqual(routes.at(-1),{module:'dossier',project:'P1',item:'S1'});
    await click('item','C1');assert.deepEqual(routes.at(-1),{module:'item',id:'C1'});
    await click('flow-item','C1');assert.deepEqual(routes.at(-1),{module:'flow',project:'P1',item:'C1',resetFilters:true});
    await click('flow');assert.deepEqual(routes.at(-1),{module:'flow',project:'P1',resetFilters:true});await click('quality');assert.deepEqual(routes.at(-1),{module:'quality',project:'P1'});
    await click('items');assert.deepEqual(routes.at(-1),{module:'items'});assert.equal(context.url,'/','reloading Items must not reopen the guide');
  });
  await check('late project responses and cancelled navigation cannot replace current state',async()=>{
    setProjects(complete(),complete('P2','Second selected project'));const first=pending();holds.set('/api/progress/projects/P1',first.promise);
    const old=context.FabGuide.open({project:'P1'}),before=calls.length;const duplicate=context.FabGuide.refresh();assert.equal(calls.length,before,'refresh coalesces an existing same-project read');
    assert.equal(elements.get('guideContent').attributes['aria-busy'],'true');await context.FabGuide.open({project:'P2'});const newest=html();assert.match(newest,/Project setup checklist · Second selected project/);
    first.release();await Promise.all([old,duplicate]);holds.clear();assert.equal(html(),newest,'old P1 response cannot overwrite selected P2');assert.match(context.url,/project=P2/);
    const navigation=pending();holds.set('/api/dossier/projects/P2',navigation.promise);const leaving=context.FabGuide.refresh();context.FabGuide.cancelPending();elements.get('guideContent').innerHTML='Another page owns navigation';
    navigation.release();await leaving;holds.clear();assert.equal(html(),'Another page owns navigation');await context.FabGuide.open({project:'P1'});assert.equal(status('issue'),'done');
  });
  await check('navigation, authenticated deep-link wiring and printable assets',async()=>{
    const index=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
    for(const phrase of ['id="navGuide"','id="guidePage"','id="guideContent"','/static/guide.js','/static/guide.css','FabGuide.cancelPending'])assert.ok(index.includes(phrase),phrase);
    assert.match(index,/async function refreshAuth\(\)[\s\S]*me=await api\('\/api\/me'\)[\s\S]*params\.has\('guide'\)[\s\S]*FabGuide\.open\(\{project:params\.get\('project'\)[\s\S]*section:params\.get\('section'\)/);
    assert.equal(index,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'),'both entrypoints carry the same guide wiring');
    assert.match(fs.readFileSync(path.join(__dirname,'../static/guide.css'),'utf8'),/@media print[\s\S]*body\.fg-printing/);
    assert.equal(calls.filter(c=>c.method&&c.method!=='GET'||c.body!==undefined).length,0);
  });
  console.log('PASS: Guide & setup ('+checks.length+' contracts): '+checks.join('; ')+'.');
})().catch(error=>{console.error(error);process.exitCode=1;});
