/* App navigation regression. Run only with the loopback-only orders_browser_server.py fixture. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const BASE=process.env.ORDERS_TEST_BASE||'http://127.0.0.1:8782';
assert.ok(['127.0.0.1','localhost'].includes(new URL(BASE).hostname),'Synthetic loopback server only.');
const OUT=process.env.NAVIGATION_TEST_OUT||'/tmp/fabtrace-navigation-review';fs.mkdirSync(OUT,{recursive:true});fs.rmSync(path.join(OUT,'report.json'),{force:true});fs.rmSync(path.join(OUT,'failure.json'),{force:true});
const PIN='only-for-local-tests-12345',run=Date.now().toString(36),errors=[],checks=[];
let browser,page,stage='initialization';
(async()=>{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  await context.route('**/*',route=>new URL(route.request().url()).origin===new URL(BASE).origin?route.continue():route.fulfill({status:200,contentType:'application/javascript',body:''}));
  page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',error=>errors.push(error.message));
  const api=async(method,url,data)=>{const response=await context.request[method](BASE+url,{data});assert.ok(response.ok(),await response.text());return response.json();};
  const visible=async name=>{await page.locator('#'+name).waitFor({state:'visible'});await page.waitForFunction(name=>![...document.querySelectorAll('#'+name+' [aria-busy]')].some(el=>el.getAttribute('aria-busy')==='true'),name);await page.locator('#navBack').waitFor({state:'visible'});};
  const back=async name=>{await page.locator('#navBack').click();await visible(name);await page.waitForFunction(()=>!document.getElementById('navBack').disabled);};
  const more=async id=>{if(!(await page.locator('#moreTools').getAttribute('open')))await page.locator('#moreTools>summary').click();await page.locator('#'+id).click();};
  const action=value=>page.locator('[data-os-action="'+value+'"]');
  const noOverflow=async()=>assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'No horizontal document overflow');
  await api('post','/api/login',{badge:'TEST-ADMIN',pin:PIN});
  const setup=await api('post','/api/order-setup',{expected_version:0,purchase_order:'NAV-PO-'+run,assemblies:[{gpn:'000-NAV-GPN',assembly_number:'000-TEST-NAV-ASM',assembly_quantity:1,spools:[{spool_number:'000-NAV-SPOOL',quantity_per_assembly:2,welds_per_spool:2}]}]});
  const project=setup.order.project_id,gpn=setup.assemblies[0].gpn_id;
  await api('post','/api/order-labels/'+project+'/generate',{expected_version:setup.order.version,kind:'Spool',location:'Receiving',handler:'TEST-HANDLER'});
  const labels=await api('get','/api/order-labels/'+project+'/labels'),spool=labels.items[0].id,assembly=labels.items[0].assembly_id;
  await page.goto(BASE+'/');await visible('orderSetupPage');

  stage='small primary menu and retained tools';
  assert.deepEqual(await page.locator('#mainNav>button').evaluateAll(nodes=>nodes.map(el=>el.id)),['navOrders','navProgress','navHandoff','navFlow','navGuide']);
  assert.equal(await page.locator('#moreTools').getAttribute('open'),null);
  for(const id of ['navItems','navTracking','navParts','navQuality','navDossier','navBulk','navNew','navStaff','navAdmin','navRemoved','navAudit','navExportExcel'])assert.equal(await page.locator('#moreTools #'+id).count(),1);
  for(const [id,screen] of [['navProgress','productionProgressPage'],['navHandoff','handoffPage'],['navFlow','flowPage'],['navGuide','guidePage']]){await page.locator('#'+id).click();await visible(screen);if(id==='navFlow'){assert.equal(new URL(page.url()).searchParams.get('view'),null);assert.equal(new URL(page.url()).searchParams.get('work_scope'),null);}await back('orderSetupPage');}
  for(const [id,screen] of [['navItems','itemsPage'],['navTracking','trackingPage'],['navParts','partsPage'],['navQuality','qualityPage'],['navDossier','dossierPage'],['navBulk','bulkPage'],['navStaff','staffPage'],['navAdmin','adminPage'],['navRemoved','removalsPage'],['navAudit','auditPage']]){await more(id);await visible(screen);assert.equal(await page.locator('#moreTools').getAttribute('open'),null);await back('orderSetupPage');}
  checks.push('The five primary screens remain without My work; every retained specialist/admin workspace opens from More tools and returns through contextual Back');

  stage='wizard draft across tabs and Back';
  await action('new').click();await page.locator('#osPoNumber').fill('NAV-DRAFT-'+run);await action('next').click();
  const assemblyInput=page.locator('input[id^="osAssemblyNumber-"]').first(),assemblyKey=(await assemblyInput.getAttribute('id')).replace('osAssemblyNumber-','');
  await assemblyInput.fill('000-DRAFT-ASSEMBLY');await page.locator('#osGpn-'+assemblyKey).fill('000-DRAFT-GPN');await page.locator('#osAssemblyQty-'+assemblyKey).fill('3');assert.equal(await page.locator('input[id^="osSpoolNumber-"]').count(),0);await action('next').click();
  const spoolInput=page.locator('input[id^="osSpoolNumber-"]').first(),spoolKey=(await spoolInput.getAttribute('id')).replace('osSpoolNumber-','');
  await spoolInput.fill('000-DRAFT-SPOOL');await page.locator('#osSpoolQty-'+spoolKey).fill('2');await page.locator('#osSpoolWelds-'+spoolKey).fill('4');
  assert.equal(await page.locator('#osSave').count(),1);assert.doesNotMatch(await page.locator('#orderSetupContent').innerText(),/Review P.O./);
  await back('orderSetupPage');assert.equal(await page.locator('#osAssemblyQty-'+assemblyKey).inputValue(),'3');await action('next').click();
  assert.equal(await page.locator('#osSpoolNumber-'+spoolKey).inputValue(),'000-DRAFT-SPOOL');
  await page.locator('#navProgress').click();await visible('productionProgressPage');await back('orderSetupPage');
  assert.equal(await page.locator('#osSpoolQty-'+spoolKey).inputValue(),'2');
  await page.locator('#navFlow').click();await visible('flowPage');await page.locator('#navOrders').click();await visible('orderSetupPage');
  assert.equal(await page.locator('#osSpoolNumber-'+spoolKey).inputValue(),'000-DRAFT-SPOOL');
  await back('orderSetupPage');await back('orderSetupPage');assert.equal(await page.locator('#osPoNumber').inputValue(),'NAV-DRAFT-'+run);
  await back('orderSetupPage');await action('resume').click();assert.equal(await page.locator('#osPoNumber').inputValue(),'NAV-DRAFT-'+run);
  await action('next').click();await action('next').click();
  checks.push('Step Back, screen Back, Orders reopening, and paused Resume setup preserve unsaved PO, assembly, spool and quantity values');

  stage='navigation guard during a real pending save';
  let release,intercepted;const held=new Promise(resolve=>{release=resolve;}),received=new Promise(resolve=>{intercepted=resolve;});
  await context.route('**/api/order-setup',async route=>{if(route.request().method()==='POST'){intercepted();await held;}await route.continue();});
  const savedResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/order-setup'&&response.request().method()==='POST');
  await page.locator('#osSave').click();await received;await page.locator('#navProgress').click();assert.equal(await page.locator('#orderSetupPage').isVisible(),true);
  release();assert.ok((await savedResponse).ok());await visible('orderSetupPage');await page.locator('#orderSetupForm').waitFor({state:'detached'});
  assert.match(await page.locator('#orderSetupContent').innerText(),/NAV-DRAFT-/);assert.match(await page.locator('#orderSetupContent').innerText(),/More tools/);
  await action('documents').click();assert.match(await page.locator('#orderSetupContent').innerText(),/Optional files/);await back('orderSetupPage');assert.match(await page.locator('#orderSetupContent').innerText(),/NAV-DRAFT-/);
  await context.unroute('**/api/order-setup');
  checks.push('A pending setup save cannot be interrupted by main navigation; saving returns to the P.O. and optional files return through Back without a duplicate save');

  stage='exact order and spool return';
  await page.goto(BASE+'/?orders=1&po='+project+'&gpn='+gpn+'&assembly='+assembly);await visible('ordersPage');
  await page.locator('[data-order-action="parts"][data-order-id="'+spool+'"]').click();await visible('partsPage');
  assert.equal(new URL(page.url()).searchParams.get('spool'),spool);await back('ordersPage');
  for(const [key,value] of Object.entries({po:project,gpn,assembly}))assert.equal(new URL(page.url()).searchParams.get(key),value);
  await page.locator('[data-order-action="flow"][data-order-id="'+spool+'"]').click();await visible('flowPage');
  await page.evaluate(id=>window.openItem(id),spool);await visible('itemPage');await back('flowPage');assert.equal(new URL(page.url()).searchParams.get('item'),spool);await back('ordersPage');
  checks.push('Orders → spool BOM/flow → item → Back restores the exact PO, GPN, assembly and unique spool');

  stage='readable spool QR and materials return';
  const alias=labels.items[0].qr_alias;assert.ok(alias&&alias!==spool);
  await page.goto(BASE+'/?spool='+encodeURIComponent(alias));await visible('itemPage');assert.equal(await page.evaluate(()=>current.id),spool);assert.ok((await page.locator('#itemTitle').innerText()).includes(alias));
  await page.locator('#itemPage [data-spool-bom-url]').click();await page.locator('#spoolBomDialog[open]').waitFor();await page.locator('#spoolBomContent[aria-busy="false"]').waitFor();assert.ok((await page.locator('#spoolBomSubtitle').innerText()).includes(alias));await page.locator('#spoolBomClose').click();
  await page.locator('#navGuide').click();await visible('guidePage');await back('itemPage');assert.equal(await page.evaluate(()=>current.id),spool);assert.ok((await page.locator('#itemTitle').innerText()).includes(alias));assert.equal(await page.locator('#spoolBomDialog').evaluate(el=>el.open),false);
  const otherSpool=labels.items[1];await page.evaluate(id=>window.openItem(id),otherSpool.id);await visible('itemPage');assert.equal(await page.evaluate(()=>current.id),otherSpool.id);assert.equal(await page.locator('#itemTitle').innerText(),otherSpool.display_code);await back('itemPage');assert.equal(await page.evaluate(()=>current.id),spool);assert.equal(await page.locator('#itemTitle').innerText(),alias);
  checks.push('Readable spool QR resolves to its stable record; Materials and cross-screen Back retain it, and item A → item B → Back restores A');

  stage='same-workspace tabs';
  const quality=await api('post','/api/quality/workspaces',{name:'NAV audit '+run,customer:'Synthetic navigation fixture',project_id:project,purchase_order:'NAV-PO-'+run,owner_badge:'TEST-QA',template:'kelvion'});
  const workspace=quality.workspace.id;
  await page.goto(BASE+'/?quality=1&workspace='+workspace);await visible('qualityPage');
  await page.locator('[data-quality-action="tab"][data-quality-id="documents"]').click();await page.locator('[data-quality-action="tab"][data-quality-id="evidence"]').click();
  await back('qualityPage');assert.equal(new URL(page.url()).searchParams.get('tab'),'documents');assert.equal(await page.locator('[data-quality-id="documents"][data-quality-action="tab"]').getAttribute('aria-pressed'),'true');
  await back('qualityPage');assert.equal(await page.locator('[data-quality-id="requirements"][data-quality-action="tab"]').getAttribute('aria-pressed'),'true');
  await more('navAdmin');await visible('adminPage');await page.locator('[data-admin-action="tab"][data-admin-id="employees"]').click();await back('adminPage');assert.equal(await page.locator('[data-admin-action="tab"][data-admin-id="items"]').getAttribute('aria-selected'),'true');
  checks.push('Audit and administrator tabs have distinct Back destinations and restore the selected tab');

  stage='deep links, legacy project fallback and safe root';
  await page.goto(BASE+'/?parts=1&project='+project+'&spool='+spool);await visible('partsPage');await back('partsPage');assert.equal(new URL(page.url()).searchParams.get('spool'),null);assert.equal(new URL(page.url()).searchParams.get('project'),project);await back('partsPage');assert.equal(new URL(page.url()).searchParams.get('project'),null);await back('orderSetupPage');
  await page.goto(BASE+'/?item='+spool);await visible('itemPage');await back('orderSetupPage');
  await page.goto(BASE+'/?spool='+encodeURIComponent(alias));await visible('itemPage');await back('orderSetupPage');
  for(let i=0;i<3;i++){await back('orderSetupPage');assert.equal(new URL(page.url()).origin,new URL(BASE).origin);assert.equal(new URL(page.url()).searchParams.get('order-setup'),'1');}
  assert.equal(await page.evaluate(()=>window.FabNavigation.state().depth),0);
  checks.push('Direct spool/item links get safe same-app parents; project roots never assume a legacy project is a PO; repeated root Back never leaves FabTrace or creates a loop');

  stage='mobile and role gates';
  await page.setViewportSize({width:390,height:844});await noOverflow();await page.locator('#moreTools>summary').click();await noOverflow();
  await page.screenshot({path:path.join(OUT,'navigation-mobile.png'),fullPage:true});await page.keyboard.press('Escape');assert.equal(await page.locator('#moreTools').getAttribute('open'),null);
  await api('post','/api/logout');await api('post','/api/login',{badge:'TEST-WELDER',pin:PIN});await page.goto(BASE+'/');await visible('orderSetupPage');
  await page.locator('#moreTools>summary').click();
  for(const id of ['navStaff','navAdmin','navRemoved','navExportExcel','navBulk','navNew'])assert.equal(await page.locator('#'+id).isVisible(),false,id+' remains role-gated');
  assert.equal(await action('new').count(),0);await page.locator('#navItems').click();await visible('itemsPage');await back('orderSetupPage');
  await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:path.join(OUT,'navigation-desktop.png'),fullPage:true});
  checks.push('Compact menu fits 390px and keyboard Escape closes it; floor roles land on read-only Orders and retain existing access restrictions');
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify({status:'passed',checks,page_errors:errors,project,spool},null,2));fs.rmSync(path.join(OUT,'failure.json'),{force:true});console.log(JSON.stringify({status:'passed',checks,artifacts:OUT},null,2));await browser.close();
})().catch(async error=>{console.error('FAILED',stage,error.stack||error);if(page)await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true}).catch(()=>{});fs.writeFileSync(path.join(OUT,'failure.json'),JSON.stringify({stage,error:error.message,page_errors:errors},null,2));if(browser)await browser.close();process.exitCode=1;});

