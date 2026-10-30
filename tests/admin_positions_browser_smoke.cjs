/* Employee position acceptance against the disposable local browser fixture. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const BASE='http://127.0.0.1:8782';
const OUT=process.env.ADMIN_POSITIONS_TEST_OUT||'/tmp/fabtrace-admin-positions-review';
const EXECUTABLE=process.env.CHROMIUM_EXECUTABLE||'/tmp/fabtrace-orders-browser/chrome-headless-shell-linux64/chrome-headless-shell';
fs.mkdirSync(OUT,{recursive:true});
const report={checks:[],screenshots:[],status:'running'},errors=[];
let browser,adminContext,handlerContext,page,handlerPage,step='start';
(async()=>{
  browser=await chromium.launch({executablePath:EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  adminContext=await browser.newContext({viewport:{width:1440,height:1000}});
  handlerContext=await browser.newContext({viewport:{width:1440,height:1000}});
  for(const context of [adminContext,handlerContext]){
    await context.route('**/*',route=>new URL(route.request().url()).origin===new URL(BASE).origin?route.continue():route.fulfill({status:200,contentType:'application/javascript',body:''}));
    context.on('page',p=>p.on('pageerror',e=>errors.push(e.message)));
  }
  page=await adminContext.newPage();handlerPage=await handlerContext.newPage();
  page.setDefaultTimeout(12000);handlerPage.setDefaultTimeout(12000);
  const login=async(target,badge)=>{await target.goto(BASE+'/');await target.locator('#login').waitFor({state:'visible'});await target.locator('#badge').fill(badge);await target.locator('#pin').fill('only-for-local-tests-12345');await target.locator('#loginForm button').click();await target.locator('#workspace').waitFor({state:'visible'});};
  const body=async response=>{assert.equal(response.status(),200,await response.text());return response.json();};
  const screenshot=async(name,target=page)=>{await target.screenshot({path:path.join(OUT,name),fullPage:true});report.screenshots.push(name);};
  const panel=async target=>{await target.locator('#adminPage').waitFor({state:'visible'});await target.locator('#adminContent[aria-busy="false"]').waitFor();};

  step='separate live handler session starts without administrator rights';
  await login(handlerPage,'TEST-HANDLER');
  assert.equal((await body(await handlerContext.request.get(BASE+'/api/me'))).role,'handler');
  assert.equal((await handlerContext.request.get(BASE+'/api/admin/overview')).status(),403);
  assert.equal(await handlerPage.locator('#navAdmin').isVisible(),false);
  assert.equal(await handlerPage.locator('#navStaff').isVisible(),false);
  report.checks.push('A signed-in Handler starts without Admin controls or employee-management access');

  step='direct Employees action opens a small position form';
  await login(page,'TEST-ADMIN');await page.locator('#navStaff').click();
  await page.locator('#staffPage').waitFor({state:'visible'});
  const direct=page.locator('#staffRows [data-employee-position="TEST-HANDLER"]');
  await direct.waitFor();await direct.click();await panel(page);
  await page.locator('#adminEmployeeRole').waitFor({state:'visible'});
  assert.equal(await page.locator('#adminEmployeeRole').inputValue(),'handler');
  assert.equal(await page.locator('#adminEmployeeName,#adminEmployeeActive').count(),0);
  assert.match(await page.locator('#adminEmployeeActionForm').innerText(),/Change job position/);
  assert.match(await page.locator('#adminEmployeeActionForm').innerText(),/Administrator/);
  await page.locator('#adminEmployeeRole').selectOption('admin');
  assert.match(await page.locator('#adminRoleScope').innerText(),/Full site administration/);
  await page.locator('#adminEmployeeReason').fill('Synthetic promotion from Handler to Administrator');
  await screenshot('position-change-desktop.png');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await screenshot('position-change-mobile.png');await page.setViewportSize({width:1440,height:1000});
  report.checks.push('Employees → Change position opens the selected employee with a role dropdown and reason; Administrator is available and mobile layout fits');

  step='save grants the chosen role while the acting admin stays signed in';
  const pending=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/admin/employees/TEST-HANDLER'&&r.request().method()==='PATCH');
  await page.locator('#adminSaveEmployee').click();const response=await pending,saved=await body(response);
  assert.equal(saved.role,'admin');assert.equal(saved.badge,'TEST-HANDLER');assert.equal(saved.active,true);assert.equal(saved.reauthenticate,false);
  await page.locator('#adminEmployeeActionForm').waitFor({state:'detached'});await panel(page);
  assert.match(await page.locator('#adminContent').innerText(),/Job position updated/);
  assert.match(await page.locator('#adminContent').innerText(),/Administrator/);
  assert.equal((await body(await adminContext.request.get(BASE+'/api/me'))).badge,'TEST-ADMIN');
  const roster=await body(await adminContext.request.get(BASE+'/api/admin/employees'));
  assert.equal(roster.employees.find(employee=>employee.badge==='TEST-HANDLER').role,'admin');
  assert.equal(roster.active_admins,2);await screenshot('position-saved-desktop.png');
  report.checks.push('Saving promotes the same active badge to Administrator, records the updated roster and keeps the acting administrator signed in');

  step='old handler session is revoked and fresh login receives full admin controls';
  assert.equal((await handlerContext.request.get(BASE+'/api/me')).status(),401);
  assert.equal((await handlerContext.request.get(BASE+'/api/admin/overview')).status(),401);
  await login(handlerPage,'TEST-HANDLER');
  const account=await body(await handlerContext.request.get(BASE+'/api/me'));
  assert.equal(account.role,'admin');assert.ok(account.permissions.capabilities.includes('admin'));
  await handlerPage.locator('#navAdmin').waitFor({state:'visible'});
  await handlerPage.locator('#navStaff').waitFor({state:'visible'});
  await handlerPage.locator('#navAdmin').click();await panel(handlerPage);
  assert.equal((await handlerContext.request.get(BASE+'/api/admin/overview')).status(),200);
  await screenshot('promoted-employee-admin-controls.png',handlerPage);
  report.checks.push('The previous Handler session stops immediately; its next sign-in has Administrator permissions and working Admin controls');

  assert.deepEqual(errors,[]);report.status='passed';report.page_errors=errors;
  fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  await browser.close();
})().catch(async error=>{console.error('FAILED',step,error.stack||error);if(page)await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true}).catch(()=>{});fs.writeFileSync(path.join(OUT,'failure.json'),JSON.stringify({step,error:error.message,page_errors:errors,checks:report.checks},null,2));if(browser)await browser.close();process.exitCode=1;});
