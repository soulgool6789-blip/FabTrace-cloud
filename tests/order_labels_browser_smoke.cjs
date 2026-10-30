/* Real browser acceptance against the isolated orders_browser_server.py fixture. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const BASE='http://127.0.0.1:8782';
const OUT=process.env.ORDER_LABELS_TEST_OUT||'/tmp/fabtrace-order-labels-review';
const EXECUTABLE=process.env.CHROMIUM_EXECUTABLE||'/tmp/fabtrace-orders-browser/chrome-headless-shell-linux64/chrome-headless-shell';
fs.mkdirSync(OUT,{recursive:true});
const report={checks:[],screenshots:[],status:'running'},errors=[],writes=[];
let browser,context,page,step='start';
const run=Date.now().toString(36),PO='000-QR-PO-'+run;
const setupBody=number=>({expected_version:0,purchase_order:number,assemblies:[
  {gpn:'000-GPN-A',assembly_quantity:3,spools:[{spool_number:'000-SP-A',quantity_per_assembly:2}]},
  {gpn:'000-GPN-B',assembly_quantity:2,spools:[{spool_number:'000-SP-B',quantity_per_assembly:1}]}
]});
(async()=>{
  browser=await chromium.launch({executablePath:EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addInitScript(()=>{window.print=()=>{window.__printCalls=(window.__printCalls||0)+1;};});
  context.on('page',p=>p.on('pageerror',e=>errors.push(e.message)));
  context.on('request',r=>{if(r.method()!=='GET')writes.push({method:r.method(),url:r.url()});});
  page=await context.newPage();page.setDefaultTimeout(12000);
  const send=async(method,url,body,status=200)=>{
    const response=await context.request[method](BASE+url,body===undefined?{}:{data:body});
    assert.equal(response.status(),status,await response.text());
    return response.json();
  };
  const login=async badge=>send('post','/api/login',{badge,pin:'only-for-local-tests-12345'});
  const panel=async()=>{await page.locator('#orderLabelsPage').waitFor({state:'visible'});await page.locator('#orderLabelsContent[aria-busy="false"]').waitFor();assert.equal(await page.locator('#orderLabelsContent > .ol-error').count(),0);};
  const os=action=>'#orderSetupContent [data-os-action="'+action+'"]';
  const ol=action=>'#orderLabelsContent [data-ol-action="'+action+'"]';
  const openSetup=async project=>{await page.goto(BASE+'/?order-setup=1&po='+project);await page.locator('#orderSetupContent[aria-busy="false"]').waitFor();};
  const openLabels=async(project,gpn='',kind='Assembly')=>{await page.goto(BASE+'/?order-labels=1&po='+project+(gpn?'&gpn='+gpn:'')+(kind==='Spool'?'&kind=Spool':''));await panel();assert.equal(await page.locator('#olKind').inputValue(),kind);};
  const noOverflow=async()=>{const value=await page.evaluate(()=>({document:document.documentElement.scrollWidth,viewport:innerWidth}));assert.ok(value.document<=value.viewport+1,JSON.stringify(value));};
  const screenshot=async(name,target=page)=>{await target.screenshot({path:path.join(OUT,name),fullPage:true});report.screenshots.push(name);};
  const waitLabels=async count=>{await panel();await page.waitForFunction(n=>document.querySelectorAll('#orderLabelsContent .ol-label').length===n,count);};
  const generate=async(project,status=200)=>{
    const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/order-labels/'+project+'/generate'&&r.request().method()==='POST');
    await page.locator('#olGenerate').click();const saved=await response;assert.equal(saved.status(),status,await saved.text());return saved.json();
  };
  const printSheet=async()=>{
    const popup=context.waitForEvent('page');await page.locator(ol('print')).click();const sheet=await popup;
    sheet.setDefaultTimeout(12000);await sheet.locator('#printButton').waitFor();return sheet;
  };

  step='saved P.O. entry point and explicit actual custody';
  await login('TEST-ADMIN');const setup=await send('post','/api/order-setup',setupBody(PO),201);
  const project=setup.order.project_id,gpnA=setup.assemblies.find(a=>a.gpn==='000-GPN-A').gpn_id;
  report.project_id=project;report.purchase_order=PO;
  await openSetup(project);await page.locator(os('qr-labels')).click();await panel();
  assert.equal(new URL(page.url()).searchParams.get('order-labels'),'1');
  assert.equal(await page.locator('#olLocation').inputValue(),'');assert.equal(await page.locator('#olHandler').inputValue(),'');
  assert.match(await page.locator('#olGenerate').innerText(),/Generate 5 QR codes/);
  assert.equal((await send('get','/api/items')).total,0);
  await screenshot('generate-desktop.png');
  await page.setViewportSize({width:390,height:844});await noOverflow();await screenshot('generate-mobile.png');
  await page.setViewportSize({width:1440,height:1000});
  report.checks.push('Saved P.O. opens all GPN labels, derives five required units, and requests actual location/employee without creating records on read');

  step='generation of five independent durable assembly identities';
  await page.locator('#olLocation').fill('Receiving Bay 2');await page.locator('#olHandler').selectOption('TEST-HANDLER');
  const created=await generate(project);assert.equal(created.created_count,5);await waitLabels(5);
  const all=await send('get','/api/order-labels/'+project+'/labels'),ids=all.items.map(i=>i.id).sort();
  assert.equal(new Set(ids).size,5);assert.equal(all.items.filter(i=>i.google_part_number==='000-GPN-A').length,3);assert.equal(all.items.filter(i=>i.google_part_number==='000-GPN-B').length,2);
  assert.ok(all.items.every(i=>i.purchase_order===PO&&i.qr_url==='https://fabtrace-training.example/?item='+i.id));
  const items=await send('get','/api/items');assert.equal(items.total,5);
  assert.ok(items.items.every(i=>i.kind==='Assembly'&&i.location==='Receiving Bay 2'&&i.handler==='TEST-HANDLER'&&!i.released&&!i.tracking_enabled));
  assert.equal(await page.locator('#olGenerate').count(),0);assert.match(await page.locator('#orderLabelsContent').innerText(),/All assembly QR codes are ready/);
  await screenshot('labels-desktop.png');await page.setViewportSize({width:390,height:844});await noOverflow();await screenshot('labels-mobile.png');await page.setViewportSize({width:1440,height:1000});
  report.checks.push('One explicit generation creates five unique Assembly Items with selected custody, correct 3/2 GPN counts, and no production enrollment or release');

  step='individual GPN selection and read-only print reuse';
  await page.locator('#olGpn').selectOption(gpnA);await waitLabels(3);
  const beforePrint=writes.length;const sheet=await printSheet();
  await sheet.waitForFunction(()=>!document.getElementById('printButton').disabled);
  assert.equal(await sheet.locator('.label').count(),3);assert.equal(await sheet.locator('.label img').evaluateAll(images=>images.filter(i=>i.complete&&i.naturalWidth>0).length),3);
  assert.match(await sheet.locator('body').innerText(),new RegExp(PO));assert.match(await sheet.locator('body').innerText(),/000-GPN-A/);assert.doesNotMatch(await sheet.locator('body').innerText(),/000-GPN-B/);
  const printedIds=await sheet.locator('.label code').allTextContents();assert.deepEqual(printedIds.sort(),all.items.filter(i=>i.gpn_id===gpnA).map(i=>i.id).sort());
  await screenshot('print-sheet.png',sheet);await sheet.close();assert.equal(writes.length,beforePrint);
  await page.locator(ol('refresh')).click();await waitLabels(3);
  assert.deepEqual((await send('get','/api/order-labels/'+project+'/labels')).items.map(i=>i.id).sort(),ids);
  assert.equal((await send('get','/api/items')).total,5);
  report.checks.push('GPN filter prints only its three original IDs; every QR image loads and repeated reads/printing create no additional records');

  step='individual setup QR entry point and original scan destination';
  await openSetup(project);await page.locator(os('qr-gpn')+'[data-os-id="'+gpnA+'"]').click();await waitLabels(3);assert.equal(await page.locator('#olGpn').inputValue(),gpnA);
  await page.goto(BASE+'/?item='+ids[0]);await page.locator('#itemPage').waitFor({state:'visible'});await page.waitForFunction(id=>typeof current!=='undefined'&&current?.id===id,ids[0]);
  assert.match(await page.locator('#itemPage').innerText(),new RegExp(ids[0]));assert.equal((await send('get','/api/items')).total,5);
  report.checks.push('Individual GPN button opens its scoped label list; QR item route lands on the original unique assembly');

  step='Spool selector derives and generates eight children for the five physical assemblies';
  await openLabels(project);await page.locator('#olKind').selectOption('Spool');await panel();
  assert.equal(new URL(page.url()).searchParams.get('kind'),'Spool');
  assert.match(await page.locator('#olGenerate').innerText(),/Generate spool QR codes/);assert.equal(await page.locator('.ol-counts > div').nth(1).locator('strong').innerText(),'8');
  await page.locator('#olLocation').fill('Spool receiving bay');await page.locator('#olHandler').selectOption('TEST-HANDLER');
  const spoolCreated=await generate(project);assert.equal(spoolCreated.created_count,8);assert.equal(spoolCreated.created_spool_count,8);assert.equal(spoolCreated.created_assembly_count,0);await waitLabels(8);
  const spoolAll=await send('get','/api/order-labels/'+project+'/labels?kind=Spool'),spoolIds=spoolAll.items.map(i=>i.id).sort();
  assert.equal(new Set(spoolIds).size,8);assert.equal(spoolAll.items.filter(i=>i.google_part_number==='000-SP-A').length,6);assert.equal(spoolAll.items.filter(i=>i.google_part_number==='000-SP-B').length,2);
  for(const assembly of all.items){const children=spoolAll.items.filter(i=>i.assembly_id===assembly.id);assert.equal(children.length,assembly.google_part_number==='000-GPN-A'?2:1);assert.ok(children.every(i=>i.gpn_id===assembly.gpn_id&&i.gpn===assembly.google_part_number));}
  for(const spool of spoolAll.items){assert.equal(spool.kind,'Spool');assert.ok(ids.includes(spool.assembly_id));assert.equal(spool.qr_url,'https://fabtrace-training.example/?item='+spool.id);assert.equal(spool.weld_plan_exists,false);const card=page.locator('.ol-label').filter({has:page.locator('code',{hasText:spool.id})});assert.equal(await card.count(),1);assert.match(await card.locator('.ol-parent').innerText(),new RegExp(spool.assembly_id));assert.equal(await card.locator('strong').innerText(),spool.spool_number);}
  assert.equal((await send('get','/api/items')).total,13);const firstSpool=spoolAll.items[0];assert.equal((await send('get','/api/tracking/spools/'+firstSpool.id)).plan,null);
  await screenshot('spool-labels-desktop.png');await page.setViewportSize({width:390,height:844});await noOverflow();await screenshot('spool-labels-mobile.png');await page.setViewportSize({width:1440,height:1000});
  report.checks.push('Spool selector creates exactly eight children (six A and two B), each tied to its correct unique assembly, without a fabricated weld plan');

  step='spool print sheet preserves exact parent and reusable QR identity';
  await page.locator('#olGpn').selectOption(gpnA);await waitLabels(6);const beforeSpoolPrint=writes.length,spoolSheet=await printSheet();
  await spoolSheet.waitForFunction(()=>!document.getElementById('printButton').disabled);assert.equal(await spoolSheet.locator('.label').count(),6);
  for(const spool of spoolAll.items.filter(i=>i.gpn_id===gpnA)){const label=spoolSheet.locator('.label').filter({has:spoolSheet.locator('code',{hasText:spool.id})});assert.equal(await label.count(),1);const text=await label.innerText();assert.ok(text.includes(spool.spool_number)&&text.includes(spool.assembly_id)&&text.includes(spool.gpn));assert.match(await label.locator('.label-parent').filter({hasText:'Assembly '+spool.assembly_id}).innerText(),new RegExp(spool.assembly_id));}
  assert.equal(await spoolSheet.locator('.label img').evaluateAll(images=>images.filter(i=>i.complete&&i.naturalWidth>0).length),6);await screenshot('spool-print-sheet.png',spoolSheet);await spoolSheet.emulateMedia({media:'print'});assert.equal(await spoolSheet.locator('.label').evaluateAll(labels=>labels.some(label=>label.scrollWidth>label.clientWidth+1||label.scrollHeight>label.clientHeight+1)),false);await screenshot('spool-print-layout.png',spoolSheet);await spoolSheet.close();
  await page.locator(ol('refresh')).click();await waitLabels(6);assert.deepEqual((await send('get','/api/order-labels/'+project+'/labels?kind=Spool')).items.map(i=>i.id).sort(),spoolIds);assert.equal(writes.length,beforeSpoolPrint);
  report.checks.push('Filtered spool print sheet includes each spool number, GPN and exact parent assembly; reprinting keeps all original IDs and performs no writes');

  step='Set weld plan preserves the registered spool and assembly context';
  const plannedSpool=spoolAll.items.find(i=>i.gpn_id===gpnA),beforePlan=writes.length;
  await page.locator('[data-ol-plan="'+plannedSpool.id+'"]').click();await page.locator('#trackingDialog[open]').waitFor();
  assert.equal(await page.locator('#ft-field-item_id').inputValue(),plannedSpool.id);assert.equal(await page.locator('#ft-field-project_id').inputValue(),project);assert.equal(await page.locator('#ft-field-assembly_id').inputValue(),plannedSpool.assembly_id);assert.equal(await page.locator('#ft-field-assembly_id').isEditable(),false);assert.equal(await page.locator('#ft-field-zero_weld_reason').inputValue(),'');
  await screenshot('spool-weld-plan-prefill.png');await page.locator('#trackingDialogCancel').click();assert.equal(writes.length,beforePlan);assert.equal((await send('get','/api/tracking/spools/'+plannedSpool.id)).plan,null);
  report.checks.push('Set weld plan preselects the exact physical spool, PO and fixed assembly parent; opening/canceling the form does not invent weld scope');

  step='failed QR image prevents automatic or manual printing';
  await openLabels(project,gpnA,'Spool');await waitLabels(6);
  await context.route('**/api/items/*/qr.png',route=>route.abort('failed'));
  const failed=await printSheet();
  try{await failed.locator('#printStatus').filter({hasText:'A QR image could not load'}).waitFor({timeout:25000});}
  catch(error){console.error('PRINT FAILURE STATE',await failed.evaluate(()=>({status:document.getElementById('printStatus')?.textContent,disabled:document.getElementById('printButton')?.disabled,printCalls:window.__printCalls||0,images:[...document.images].map(i=>({src:i.src,complete:i.complete,width:i.naturalWidth}))})));await screenshot('unexpected-print-failure.png',failed);throw error;}
  assert.equal(await failed.locator('#printButton').isDisabled(),true);assert.equal(await failed.evaluate(()=>window.__printCalls||0),0);await screenshot('print-image-failure.png',failed);await failed.close();
  await context.unroute('**/api/items/*/qr.png');
  report.checks.push('Any QR image failure keeps the print button disabled and prevents automatic printing');

  step='stale generation reload preserves quantities and avoids duplicate units';
  const secondBody={expected_version:0,purchase_order:'000-STALE-'+run,assemblies:[{gpn:'000-GPN-STALE',assembly_quantity:2,spools:[{spool_number:'000-SP-STALE',quantity_per_assembly:1}]}]};
  const second=await send('post','/api/order-setup',secondBody,201),secondProject=second.order.project_id;
  await openLabels(secondProject);await page.locator('#olLocation').fill('Assembly staging');await page.locator('#olHandler').selectOption('TEST-HANDLER');
  await send('patch','/api/order-setup/'+secondProject+'/assemblies/'+second.assemblies[0].gpn_id,{...secondBody.assemblies[0],assembly_quantity:3,expected_version:second.order.version,reason:'Synthetic separate-session quantity correction'});
  await generate(secondProject,409);await page.locator('.ol-error').filter({hasText:'Reload the saved labels'}).waitFor();assert.equal(await page.locator('#olGenerate').isDisabled(),true);
  assert.equal((await send('get','/api/order-labels/'+secondProject+'/labels')).total,0);
  await page.locator(ol('refresh')).first().click();await panel();assert.match(await page.locator('#olGenerate').innerText(),/Generate 3 QR codes/);
  await page.locator('#olLocation').fill('Assembly staging');await page.locator('#olHandler').selectOption('TEST-HANDLER');assert.equal((await generate(secondProject)).created_count,3);await waitLabels(3);
  report.checks.push('Concurrent setup correction rejects stale generation without partial records; explicit reload uses the corrected quantity');

  step='fresh PO spool generation automatically registers missing parents as well';
  const automatic=await send('post','/api/order-setup',setupBody('000-AUTO-SPOOL-'+run),201),autoProject=automatic.order.project_id;
  await openLabels(autoProject,'','Spool');await page.locator('#olLocation').fill('Automatic registration bay');await page.locator('#olHandler').selectOption('TEST-HANDLER');
  const autoCreated=await generate(autoProject);assert.equal(autoCreated.created_assembly_count,5);assert.equal(autoCreated.created_spool_count,8);assert.equal(autoCreated.created_count,13);await waitLabels(8);
  const autoAssemblies=await send('get','/api/order-labels/'+autoProject+'/labels?kind=Assembly'),autoSpools=await send('get','/api/order-labels/'+autoProject+'/labels?kind=Spool');assert.equal(autoAssemblies.total,5);assert.equal(autoSpools.total,8);
  for(const assembly of autoAssemblies.items){const children=autoSpools.items.filter(i=>i.assembly_id===assembly.id);assert.equal(children.length,assembly.gpn==='000-GPN-A'?2:1);assert.ok(children.every(i=>i.gpn_id===assembly.gpn_id));}
  const currentAuto=await send('get','/api/order-labels/'+autoProject+'?kind=Spool'),autoIds=autoSpools.items.map(i=>i.id).sort();
  const noOp=await send('post','/api/order-labels/'+autoProject+'/generate',{expected_version:currentAuto.order.version,kind:'Spool',location:'Do not overwrite existing custody',handler:'TEST-HANDLER'});assert.equal(noOp.created_count,0);assert.deepEqual((await send('get','/api/order-labels/'+autoProject+'/labels?kind=Spool')).items.map(i=>i.id).sort(),autoIds);
  report.checks.push('A fresh PO can generate spool labels directly: five missing parent assemblies and eight correctly linked spools are registered once');

  step='QA read-only labels and mobile scope';
  await login('TEST-QA');await openLabels(project);await waitLabels(5);assert.equal(await page.locator('#olGenerate,#olLocation,#olHandler').count(),0);assert.match(await page.locator('#orderLabelsContent').innerText(),/administrator or supervisor/);
  const beforeQaPrint=writes.length;const qaSheet=await printSheet();await qaSheet.waitForFunction(()=>!document.getElementById('printButton').disabled);assert.equal(await qaSheet.locator('.label').count(),5);await qaSheet.close();assert.equal(writes.length,beforeQaPrint);
  await page.locator('#olKind').selectOption('Spool');await waitLabels(8);assert.equal(await page.locator('#olGenerate,#olLocation,#olHandler,[data-ol-plan]').count(),0);
  const beforeQaSpoolPrint=writes.length,qaSpoolSheet=await printSheet();await qaSpoolSheet.waitForFunction(()=>!document.getElementById('printButton').disabled);assert.equal(await qaSpoolSheet.locator('.label').count(),8);await qaSpoolSheet.close();assert.equal(writes.length,beforeQaSpoolPrint);
  await page.setViewportSize({width:390,height:844});await noOverflow();await screenshot('qa-labels-mobile.png');
  report.checks.push('QA can view and print both assembly and spool labels but cannot generate, set custody or open weld planning; 390px view has no horizontal overflow');
  assert.deepEqual(errors,[]);report.status='passed';report.page_errors=errors;report.generated_ids=ids;report.generated_spool_ids=spoolIds;
  fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();
})().catch(async error=>{console.error('FAILED',step,error.stack||error);if(page)await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true}).catch(()=>{});fs.writeFileSync(path.join(OUT,'failure.json'),JSON.stringify({step,error:error.message,page_errors:errors,checks:report.checks},null,2));if(browser)await browser.close();process.exitCode=1;});
