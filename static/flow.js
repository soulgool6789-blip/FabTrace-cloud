/* CLM's numbered fabrication traveler. The server owns all transition rules. */
(() => {
  'use strict';
  const ROOT='/api/flow', node=id=>document.getElementById(id), encode=encodeURIComponent;
  const arr=value=>Array.isArray(value)?value:[], num=value=>Number.isFinite(Number(value))?Number(value):0;
  const stamp=value=>value?new Date(value).toLocaleString():'—';
  const roleLabel=id=>window.FabPermissions?.label(id)||id;
  const flowStatus=()=>window.FabFlowStatus;
  const stageBadge=value=>flowStatus()?.badge(value)||'';
  const isSpool=value=>value?.route?value.route==='spool':value?.kind==='Spool';
  const spoolNumber=value=>flowStatus()?.spoolNumber?.(value)||value.qr_alias||value.spool_number||value.google_part_number||value.item_id||value.id;
  const itemLabel=value=>isSpool(value)?spoolNumber(value):(value.route==='assembly'||value.kind==='Assembly')&&value.assembly_number?'Assembly '+value.assembly_number:value.item_id||value.id;
  const spoolText=(value,label=spoolNumber(value))=>flowStatus()?.spoolText?.(value,label)||esc(label);
  const routeNames={component:'Component',spool:'Spool',assembly:'Assembly'};
  const statusNames={admin_released:'Administrative release',not_started:'Not started',active:'In progress',completed:'Route complete',shipped:'Shipped',delivered:'Delivered',rework:'Needs rework'};
  const stepStatusNames={pending:'Upcoming',current:'Current step',completed:'Completed',not_recorded:'Not recorded',not_required:'Not required',rework:'Needs reinspection',other_route:'Linked record'};
  const phases=[
    {id:'materials',label:'Material receipt & inventory',first:1,last:4},
    {id:'components',label:'Component preparation',first:5,last:8},
    {id:'spool',label:'Spool fabrication',first:9,last:16},
    {id:'assembly',label:'Testing decision, NDT & pressure',first:17,last:19},
    {id:'paint',label:'Sandblast & paint',first:20,last:22},
    {id:'shipping',label:'Shipment',first:23,last:Infinity},
  ];
  const state={catalog:null,handoffOptions:null,handoffControl:null,board:[],spools:[],detail:null,item:'',project:'',subproject:'',query:'',status:'',step:'',sequence:0,read:null,saving:false,dialogAction:null,dialogStale:false,notice:''};
  const clocks=new WeakMap();
  const now=()=>typeof performance!=='undefined'&&typeof performance.now==='function'?performance.now():Date.now();
  let clockTimer=null;
  const removed=()=>state.detail?.removal?.removed===true||state.detail?.item?.removal?.removed===true;
  const can=action=>!removed()&&arr(state.detail?.allowed_actions).includes(action)&&(!['scope','link-spool'].includes(action)||!testingScopeFrozen())&&(action!=='advance'||!testingActorRestriction()&&state.detail?.work?.can_record!==false)&&(action!=='restart-testing'||canRestartTesting());
  const action=(name,label,id='',className='',spool=null)=>`<button type="button" class="${esc(className)}" data-flow-action="${esc(name)}"${id?` data-flow-id="${esc(id)}"`:''}>${spool?spoolText(spool,label):esc(label)}</button>`;
  const option=(value,label,selected='')=>`<option value="${esc(value)}"${String(value)===String(selected)?' selected':''}>${esc(label)}</option>`;
  const secondary=text=>`<span class="ff-secondary">${esc(text)}</span>`;
  const tag=(status,label='')=>`<span class="ff-tag ${esc(status)}">${esc(label||statusNames[status]||status)}</span>`;
  const table=html=>`<div class="tablewrap">${html}</div>`;
  const currentCatalogVersion=()=>state.detail?.flow?state.detail.flow.catalog_version||'CLM-24-v6':state.catalog?.version||'';
  // Chart numbers are presentation labels; stored step IDs and action payloads stay stable.
  const chartTestingSteps={decision:[17,17],ndt:[17,18],ndt_rework:[17,18],ndt_qa:[18,19],floor_before_pressure:[19,20],pressure_test:[17,21],pressure_rework:[17,21],pressure_qa:[18,22],floor_before_paint:[19,23]};
  const chartStepNumber=(number,version=currentCatalogVersion(),phase='')=>{
    if(number==null)return null;
    const value=Number(number);if(version!=='CLM-25-v1')return value;
    const testingStep=chartTestingSteps[phase];
    if(testingStep&&testingStep[0]===value)return testingStep[1];
    return value===18?19:value===19?20:value>=20&&value<=25?value+4:value;
  };
  const rowStepNumber=row=>row.current_display_step??chartStepNumber(row.current_step,row.catalog_version||'CLM-24-v6');
  const matchesChartStep=(row,number,version=state.catalog?.version)=>Number(rowStepNumber(row))===Number(number)&&(Number(number)<17||(row.catalog_version||'CLM-24-v6')===version);
  const currentStepNumber=step=>state.detail?.flow?.current_display_step??chartStepNumber(step.number,currentCatalogVersion(),step.testing_phase||activeTesting()?.phase||'');
  const catalogLast=()=>Math.max(0,...arr(state.catalog?.steps).map(step=>chartStepNumber(step.number,state.catalog?.version)));
  const chartStepLabel=number=>{
    const labels={18:'NDT',19:'QA/QC-004 - Verify NDT Results',20:'Return to Floor',21:'Pressure Testing',22:'QA/QC-005 - Verify Pressure Test Results',23:'Return to Floor'};
    return state.catalog?.version==='CLM-25-v1'&&labels[number]||arr(state.catalog?.steps).find(step=>chartStepNumber(step.number,state.catalog?.version)===Number(number))?.title||'';
  };
  const route=id=>{
    const flow=state.detail?.flow,steps=arr(flow?.steps).filter(step=>step.route===id);
    if(flow?.route===id){if(flow.route_definition)return flow.route_definition;if(steps.length)return {id,first_step:Math.min(...steps.map(step=>num(step.number))),last_step:Math.max(...steps.map(step=>num(step.number)))};}
    return arr(state.catalog?.routes).find(row=>row.id===id);
  };
  const definition=step=>arr(state.detail?.flow?.steps).find(row=>Number(row.number)===Number(step))||(!state.detail?.flow?arr(state.catalog?.steps).find(row=>Number(row.number)===Number(step)):null);
  const isShipmentStep=step=>typeof step?.is_shipment==='boolean'?step.is_shipment:Number(step?.number)===Number(state.detail?.flow?.shipment_step||(currentCatalogVersion()==='CLM-25-v1'?25:24));
  const openExceptions=()=>arr(state.detail?.exceptions).filter(row=>!row.closed_at);
  const displayStatus=row=>num(row.open_exceptions)>0?'rework':row.status||'not_started';
  const testing=()=>state.detail?.flow?.testing?.protocol==='CLM-TEST-v1'?state.detail.flow.testing:null;
  const activeTesting=()=>{const value=testing();return value?.active===true&&value.action?value:null;};
  const testingScopeFrozen=()=>{const value=testing();return Boolean(value&&(value.phase!=='decision'||value.decision!=null||num(value.cycle)>1));};
  const testingReview=()=>activeTesting()?.action==='review';
  const failedTestReport=value=>value?.action==='review'&&value.report?.result==='FAIL';
  const canRestartTesting=()=>['admin','supervisor'].includes(me?.role);
  const testingPassBlockers=()=>testingReview()?arr(state.detail?.flow?.blockers):[];
  const needsResolution=step=>step.requires_resolution===true||activeTesting()?.action==='correct'||step.qa&&(testingReview()?arr(activeTesting().review_exception_ids).length>0:openExceptions().some(row=>Number(row.step)===Number(step.number)));
  function testingActorRestriction(){
    const value=activeTesting(),badge=value?.action==='complete'?value.test_started_by:value?.action==='correct'?value.return_to?.sender_badge:null;
    return badge&&me?.role!=='admin'&&badge!==me?.badge?`The recorded testing employee (${badge}) or an administrator must ${value.action==='correct'?'record the completed rework':'submit this test report'}.`:'';
  }
  const testingNames={decision:'Testing decision',ndt:'NDT',ndt_qa:'NDT · QA/QC result',ndt_rework:'NDT · Required rework',floor_before_pressure:'Floor · Before pressure testing',pressure_test:'Pressure testing',pressure_qa:'Pressure testing · QA/QC result',pressure_rework:'Pressure testing · Required rework',floor_before_paint:'Floor · Before Paint/finishing',complete:'Testing complete',not_required:'Testing not required'};
  function testingPhaseName(phase,version=currentCatalogVersion(),savedDefinition=null){
    if(!['ndt_qa','pressure_qa'].includes(phase))return testingNames[phase]||'Testing phase';
    const code=savedDefinition?.display_qa_code||(phase==='pressure_qa'&&version==='CLM-25-v1'?'QA/QC-005':'QA/QC-004');
    return code+' · '+(phase==='ndt_qa'?'NDT':'Pressure test')+' result';
  }
  function hasInlineTesting(selected){
    return selected?state.detail?.flow?.route==='assembly'&&(currentCatalogVersion()==='CLM-25-v1'||Boolean(testing())):state.catalog?.version==='CLM-25-v1';
  }
  function inlineTestingChart(selected){
    if(!hasInlineTesting(selected))return '';
    const value=selected?testing():null,flow=selected?state.detail.flow:null;
    const version=selected?currentCatalogVersion():state.catalog.version,pressureQa=version==='CLM-25-v1'?'QA/QC-005':'QA/QC-004';
    const decision=['YES','NO'].includes(value?.decision)?value.decision:'',active=selected&&activeTesting()?value.phase:'';
    const current=({ndt:'ndt',ndt_rework:'ndt',ndt_qa:'ndt_qa',floor_before_pressure:'floor_before_pressure',pressure_test:'pressure_test',pressure_rework:'pressure_test',pressure_qa:'pressure_qa',floor_before_paint:'floor_before_paint'})[active]||'';
    const nodes=[['ndt',17,'NDT','Perform and record the test'],['ndt_qa',18,'QA/QC-004','Verify NDT Results'],['floor_before_pressure',19,'Return to Floor','Before pressure testing'],['pressure_test',17,'Pressure Testing','Perform and record the test'],['pressure_qa',18,pressureQa,'Verify Pressure Test Results'],['floor_before_paint',19,'Return to Floor','Before Paint and Finishing']];
    const decisionStatus=active==='decision'?'current':decision?'completed':arr(flow?.steps).find(step=>step.number===17)?.status==='not_recorded'?'not_recorded':'pending';
    const intro=selected?(decision?`Recorded choice: ${decision}${Number.isInteger(value.cycle)&&value.cycle>1?' · Cycle '+value.cycle:''}.`:'No testing decision has been recorded.'):'Choose YES or NO at this step.';
    const badge=number=>selected?`<span class="ff-num">${number}</span>`:action('filter-step',String(number),String(number),'ff-num ff-link');
    const merge=chartStepNumber(20,version);
    const nodeHtml=nodes.map(([key,storedNumber,label,description])=>{
      const number=chartStepNumber(storedNumber,version,key);
      const isCurrent=key===current,review=key.endsWith('_qa'),skipped=decision==='NO';
      return `<li class="ff-branch-node${isCurrent?' ff-branch-current':''}${skipped?' not_required':''}" data-flow-chart-step="${number}" data-testing-node="${key}"${isCurrent?' aria-current="step"':''}${review?' data-testing-review="true"':''}>${badge(number)}<div class="ff-chart-node-copy"><strong>${esc(label)}</strong><small>${esc(description)}</small>${isCurrent?`<small class="ff-chart-phase-status">${active.endsWith('_rework')?'Required rework':'Current phase'}</small>`:skipped?'<small>Not required by the recorded NO</small>':''}${review?'<small class="ff-chart-outcomes">PASS ↓ Floor · FAIL ↩ Rework</small>':''}</div></li>`;
    }).join('');
    return `<div class="ff-chart-testing" data-testing-chart="inline" data-testing-catalog="${esc(version)}" aria-label="Testing decision and destinations"><div class="ff-chart-decision ${decisionStatus}" data-flow-chart-step="17" data-testing-node="decision"${active==='decision'?' aria-current="step"':''}>${badge(17)}<div class="ff-chart-node-copy"><strong>Determine if Spool Needs to Be Sent to Testing</strong><small>${esc(intro)}</small></div></div><div class="ff-chart-paths"><div class="ff-chart-path ff-chart-yes${decision==='YES'?' ff-branch-chosen':decision==='NO'?' ff-branch-skipped':''}" data-testing-branch="YES"><span class="ff-chart-edge-label">YES</span><ol>${nodeHtml}</ol></div><div class="ff-chart-path ff-chart-no${decision==='NO'?' ff-branch-chosen':''}" data-testing-branch="NO"><span class="ff-chart-edge-label">NO</span><span class="ff-chart-bypass-note">Directly to<br>step ${merge}</span><span class="ff-chart-bypass-line" aria-hidden="true"></span></div></div><div class="ff-chart-merge" data-testing-merge-step="${merge}"><span>↓ Continue to step ${merge}</span></div>${active.endsWith('_rework')?`<p class="ff-chart-rework">${esc(returnDestination(value))} Complete the required correction, then record a fresh test and QA/QC review.</p>`:''}</div>`;
  }
  const testName=value=>value?.test_kind==='pressure'?'Pressure test':'NDT';
  const childScans=step=>typeof step.requires_child_scans==='boolean'?step.requires_child_scans:!activeTesting()&&step.number===17;
  function testingPayload(value){
    if(value?.active!==true||!value.action)return {};
    if(!testingNames[value.phase]||!Number.isInteger(value.attempt)||value.attempt<1||!['decision','start','complete','review','correct','handoff'].includes(value.action))throw Error('Refresh the testing phase before recording this action.');
    return {testing_phase:value.phase,testing_attempt:value.attempt,testing_action:value.action};
  }
  function returnDestination(value){
    const to=value?.return_to;if(!to)return 'The prior testing station and sending employee must be verified before recording a failure.';
    return `Return to ${to.location_label||to.location_id||'the recorded testing station'} · ${to.sender_name?to.sender_name+' ('+to.sender_badge+')':to.sender_badge||'sending employee not recorded'}.`;
  }
  function testingSummary(){
    const value=testing();if(!value)return '';
    const phase=testingPhaseName(value.phase,currentCatalogVersion(),activeTesting()?state.detail.flow.current:null),decision=['YES','NO'].includes(value.decision)?`<p><strong>Testing required: ${esc(value.decision)}</strong>${value.decision==='NO'?' · Continue to Paint/finishing.':' · NDT and pressure testing each require their own QA/QC result.'}</p>`:'';
    let description=activeTesting()?(value.action==='start'?`The ${testName(value)} employee records receipt with both employee badges before starting this test.`:value.action==='complete'?`Record the ${testName(value)} report and its result, then hand the item to QA/QC. QA/QC records a separate acceptance decision.`:value.action==='review'?failedTestReport(value)?'The technician’s report records FAIL. QA/QC must record a FAIL disposition, with required rework and a fresh test.':`QA/QC must record PASS or FAIL for this ${testName(value).toLowerCase()} attempt. PASS proceeds to the required Floor handoff.`:value.action==='correct'?'Complete and document the required rework. A fresh test report and a new QA/QC result are required afterward.':value.phase==='floor_before_pressure'?'Record the Floor handoff before the pressure testing employee starts the next test.':value.phase==='floor_before_paint'?'Record the Floor handoff before continuing to Paint/finishing.':'Record the testing decision for this assembly and its linked spools.'):(['complete','not_required'].includes(value.phase)?'':'This saved testing phase is not active at the current process step.');
    if(testingPassBlockers().length&&!failedTestReport(value))description='QA/QC PASS is blocked. Resolve the recorded requirements below before accepting this test attempt.';
    if(activeTesting()?.action==='review')description+=' '+(failedTestReport(value)?'Required return: ':'If QA/QC records FAIL: ')+returnDestination(value);
    else if(activeTesting()?.rework_required)description+=' '+returnDestination(value);
    const report=value.report,reportFacts=report?`<div class="ff-testing-report"><strong>Technician test report</strong>${metadata([['Recorded result',report.result||report.test_result],['Report reference',report.reference],['Recorded by',report.actor||report.recorded_by],['Recorded at',report.at?stamp(report.at):'']])}<p>QA/QC acceptance is recorded separately.</p></div>`:'';
    const qaFacts=value.qa?`<div class="ff-testing-report"><strong>Recorded QA/QC decision</strong>${metadata([['QA/QC result',value.qa.result],['Review reference',value.qa.reference],['Reviewed by',value.qa.actor],['Reviewed at',value.qa.at?stamp(value.qa.at):'']])}</div>`:'';
    return `<section class="ff-testing-phase" data-testing-phase="${esc(value.phase)}"><span class="ff-phase-kicker">Testing route${Number.isInteger(value.cycle)&&value.cycle>1?' · Cycle '+value.cycle:''}${Number.isInteger(value.attempt)&&value.attempt>0?' · Attempt '+value.attempt:''}</span><h3>${esc(phase)}</h3>${decision}${description?`<p>${esc(description)}</p>`:''}${reportFacts}${qaFacts}</section>`;
  }
  function testingChoices(){
    const value=activeTesting();if(!value)return '';
    const decision=value.requires_decision===true,result=value.requires_result===true;
    if(!decision&&!result)return '';
    const name=decision?'testing_decision':'test_result',title=decision?'Does this spool need to be sent to testing?':value.action==='review'?'QA/QC result for this test attempt':'Result recorded in the technician’s test report';
    const choices=decision?[['YES','Send to NDT, then QA/QC. A passing NDT result is followed by Floor and pressure testing.'],['NO','Continue directly to Paint/finishing. Testing steps will be recorded as not required.']]:value.action==='review'?[['PASS','Accept this test attempt and proceed to the mandatory Floor handoff.'],['FAIL','Return to the recorded testing station and sending employee for rework and a fresh test.']]:[['PASS','The technician’s report records a passing test result. QA/QC must review it.'],['FAIL','The technician’s report records a failed test result. QA/QC must review it.']];
    return `<fieldset class="ff-test-choice"><legend>${esc(title)} *</legend><div class="ff-test-options">${choices.map(([choice,help])=>{const retained=decision&&choice==='NO'&&value.decision==='YES',failedReport=choice==='PASS'&&failedTestReport(value),blockedPass=choice==='PASS'&&testingPassBlockers().length>0,disabled=retained||failedReport||blockedPass||value.action==='review'&&!(choice==='FAIL'?can('fail'):can('advance'));return `<label class="ff-test-option" for="ff-${name}-${choice}"><input id="ff-${name}-${choice}" name="${name}" type="radio" value="${choice}" required${disabled?' disabled':''}><span><strong>${choice}</strong><small>${esc(retained?'Testing remains required by the recorded YES decision. This rework cycle must return to testing.':failedReport?'The technician’s report records FAIL. Record a FAIL disposition and complete rework before a fresh test can receive QA/QC PASS.':blockedPass?'QA/QC PASS is blocked. Review the recorded requirements shown above.':help)}</small></span></label>`;}).join('')}</div><p id="flowTestingHint" class="ff-testing-hint" aria-live="polite">Choose ${decision?'YES or NO':'PASS or FAIL'} before recording this action.</p></fieldset>`;
  }
  function handoffInputs(step,failed=false){
    const transfer=state.detail.transfer||state.detail.item.transfer,value=activeTesting(),destination=failed?returnDestination(value):step.handoff_target_role?`Receiving role: ${roleLabel(step.handoff_target_role)}.`:'';
    return `<div class="ff-span"><h3>Identify both employees for this handoff</h3><p class="fh-help">Current recorded custodian: <strong>${esc(transfer?.handler_name||transfer?.handler||state.detail.item.handler)}</strong>${transfer?.handler_name?' ('+esc(transfer.handler)+')':''}. Scan the sending badge and receiving badge in their separate fields. The signed-in employee records the step.</p>${destination?`<p class="ff-testing-return">${esc(destination)}</p>`:''}${window.FabHandoff.controlHtml('flowHandoff',{transfer,options:state.handoffOptions,heading:false})}<div id="flowHandoffReview" class="fh-review" aria-live="polite"></div><p class="fh-record-note">Badges identify the parties; no independent acceptance signature is recorded. Completing this numbered step applies its existing process and QA checks.</p></div>`;
  }
  function testingFailureInputs(step){
    if(!testingReview())return '';
    return `<fieldset id="flowTestingFailure" class="ff-testing-failure hidden" disabled><h3>Failure details and return handoff</h3><p>${esc(returnDestination(activeTesting()))}</p>${field('reason','Failure / nonconformance and required repair','',{required:true,type:'textarea',full:true,minlength:4,maxlength:3000})}${handoffInputs(step,true)}</fieldset>`;
  }
  function testingButton(value,choice){
    if(!value?.action)return '';
    if(value.action==='decision')return choice==='YES'?'Save YES · Send to NDT':choice==='NO'?'Save NO · Continue to Paint/finishing':'Record testing decision';
    if(value.action==='start')return 'Record receipt · Start '+testName(value);
    if(value.action==='complete')return 'Submit '+testName(value)+' report to QA/QC';
    if(value.action==='review')return choice==='FAIL'?'Record FAIL · Return for rework':choice==='PASS'?'Record PASS · Return to Floor':'Record QA/QC result';
    if(value.action==='correct')return 'Record rework · Require a fresh '+testName(value);
    return value.phase==='floor_before_pressure'?'Record Floor handoff · Pressure testing next':'Record Floor handoff · Paint/finishing next';
  }
  function updateTestingChoice(){
    const value=activeTesting();if(!value)return;
    const name=value.requires_decision?'testing_decision':value.requires_result?'test_result':'',choices=value.requires_decision?['YES','NO']:['PASS','FAIL'];
    const choice=name?choices.find(option=>node('ff-'+name+'-'+option)?.checked)||'':'';
    const failing=value.action==='review'&&choice==='FAIL',failure=node('flowTestingFailure'),checks=node('flowTestingPassChecks');
    if(failure){if(!failure.disabled&&!failing)window.FabHandoff?.stopCamera?.();failure.disabled=!failing;failure.classList.toggle('hidden',!failing);}
    if(checks)checks.disabled=failing;
    if(value.action==='review')for(const field of ['resolution','notes'])if(node('ff-field-'+field))node('ff-field-'+field).disabled=failing;
    const button=node('flowAdvance');if(button){button.textContent=testingButton(value,choice);button.disabled=state.saving||Boolean(name&&!choice)||Boolean(value.requires_decision&&value.decision==='YES'&&choice==='NO')||Boolean(choice==='PASS'&&failedTestReport(value))||(failing?!can('fail'):!can('advance')||arr(state.detail?.flow?.blockers).length>0);}
    const hint=node('flowTestingHint');if(hint)hint.textContent=failedTestReport(value)&&choice!=='FAIL'?'The technician’s report records FAIL. Select FAIL to record the required return and rework.':testingPassBlockers().length&&choice!=='FAIL'?'QA/QC PASS is blocked: '+testingPassBlockers().join(' '):!choice?'Choose '+(value.requires_decision?'YES or NO':'PASS or FAIL')+' before recording this action.':value.requires_decision?choice==='YES'?'YES: NDT, QA/QC, Floor, then pressure testing.':'NO: Continue to Paint/finishing; testing is recorded as not required.':value.action==='review'?choice==='PASS'?'PASS: Record QA/QC acceptance and proceed to the required Floor handoff.':'FAIL: '+returnDestination(value)+' Record the failure and scan both employees for the return.':'Record the technician’s '+choice+' test result and send the report to QA/QC for a separate decision.';
  }
  function constrainHandoffDestination(){
    const value=activeTesting(),step=state.detail?.flow?.current;if(!step||!node('flowHandoffLocation'))return;
    const target=value?.action==='review'?value.return_to?.location_id:step.handoff_location_id;if(!target)return;
    const location=arr(state.handoffOptions?.locations).find(row=>row.id===target&&row.active),element=node('flowHandoffLocation');
    element.innerHTML=location?option(location.id,location.label,location.id):option('','Recorded destination unavailable; refresh');element.value=location?.id||'';
  }

  function errorText(error){
    try{const detail=JSON.parse(error.message);if(Array.isArray(detail))return detail.map(row=>`${arr(row.loc).filter(x=>x!=='body').join(' / ')}: ${row.msg||'Check this value'}`).join('\n');if(detail.message)return detail.message;if(detail.flow_blockers)return arr(detail.flow_blockers).join('\n')}catch(_){}
    return error.message||'The request could not be completed.';
  }
  function duration(value){
    const seconds=Math.max(0,Math.floor(num(value))),days=Math.floor(seconds/86400),hours=Math.floor(seconds%86400/3600),minutes=Math.floor(seconds%3600/60),rest=seconds%60;
    return `${days?days+'d ':''}${days||hours?String(hours).padStart(days?2:1,'0')+'h ':''}${String(minutes).padStart(2,'0')}m ${String(rest).padStart(2,'0')}s`;
  }
  function anchor(snapshot){
    if(snapshot&&typeof snapshot==='object'&&!clocks.has(snapshot))clocks.set(snapshot,now());
    return clocks.get(snapshot)??now();
  }
  function clock(snapshot,value,live=false){
    const started=anchor(snapshot),seconds=num(value)+(live?Math.max(0,(now()-started)/1000):0);
    return `<span class="ff-clock"${live?` data-flow-clock="${num(value)}" data-flow-anchor="${started}"`:''}>${duration(seconds)}</span>`;
  }
  function stopClocks(){if(clockTimer!==null){clearInterval(clockTimer);clockTimer=null;}}
  function startClocks(){
    stopClocks();const host=node('flowContent');
    if(typeof setInterval!=='function'||typeof host.querySelectorAll!=='function')return;
    const elements=[...host.querySelectorAll('[data-flow-clock]')];if(!elements.length)return;
    const tick=()=>{const time=now();for(const element of elements)element.textContent=duration(num(element.dataset.flowClock)+Math.max(0,(time-num(element.dataset.flowAnchor))/1000))};
    tick();clockTimer=setInterval(tick,1000);
  }
  function markTimes(detail){
    if(detail?.production_process)anchor(detail.production_process);
    return detail;
  }
  function normalizeId(value){
    if(typeof qrId==='function')return qrId(value,'item');
    const text=String(value||'').trim();
    if(text.startsWith('FABTRACE:ITEM:'))return text.slice(14);
    try{const url=new URL(text);if(url.searchParams.has('item'))return url.searchParams.get('item')}catch(_){}
    return /^[A-Za-z0-9_-]{3,60}$/.test(text)?text:'';
  }
  async function readId(value,label='Item ID'){
    const id=typeof window.resolveItemQr==='function'?await window.resolveItemQr(value):normalizeId(value);
    if(!id)throw Error(label+': scan or enter a valid FabTrace spool label or item ID.');return id;
  }
  function field(name,label,value='',settings={}){
    const id='ff-field-'+name,common=`id="${esc(id)}" name="${esc(name)}"${settings.required?' required':''}${settings.disabled?' disabled':''}`;
    let control;
    if(settings.options)control=`<select ${common}>${settings.options.map(row=>option(row[0],row[1],value)).join('')}</select>`;
    else if(settings.type==='textarea')control=`<textarea ${common}${settings.maxlength?` maxlength="${settings.maxlength}"`:''} rows="${settings.rows||3}">${esc(value)}</textarea>`;
    else control=`<input ${common} type="${settings.type||'text'}" value="${esc(value)}"${settings.min!==undefined?` min="${settings.min}"`:''}${settings.max!==undefined?` max="${settings.max}"`:''}${settings.maxlength?` maxlength="${settings.maxlength}"`:''}${settings.minlength?` minlength="${settings.minlength}"`:''}${settings.placeholder?` placeholder="${esc(settings.placeholder)}"`:''}${settings.readonly?' readonly':''} autocomplete="off">`;
    return `<div class="field${settings.full?' ff-span':''}"><label for="${id}">${esc(label)}${settings.required?' *':''}</label>${control}${settings.help?`<span class="ff-form-help">${esc(settings.help)}</span>`:''}</div>`;
  }
  function fields(content){return `<div class="ff-fields">${content}</div>`}
  function empty(title,copy,controls=''){return `<div class="ff-empty"><strong>${esc(title)}</strong><p>${esc(copy)}</p>${controls}</div>`}
  function metadata(pairs){return `<div class="ff-meta">${pairs.map(([label,value])=>`<dl><dt>${esc(label)}</dt><dd>${esc(value||'—')}</dd></dl>`).join('')}</div>`}
  function updateUrl(){
    const query=new URLSearchParams({flow:'1'});if(state.item)query.set('item',state.item);if(state.project)query.set('project',state.project);
    history.replaceState(null,'','/?'+query.toString());
  }
  async function open(options={}){
    if(!me)return;
    show('flowPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;
    state.item=options.item||'';state.detail=null;state.notice='';
    for(const key of ['subproject','query','status','step'])if(Object.prototype.hasOwnProperty.call(options,key))state[key]=options[key]||'';
    if(Object.prototype.hasOwnProperty.call(options,'project'))state.project=options.project||'';
    if(options.resetFilters===true){state.subproject='';state.query='';state.status='';state.step='';}
    await load();
  }
  async function load(){
    const sequence=++state.sequence,item=state.item;cancelRead();stopClocks();state.handoffControl?.destroy();state.handoffControl=null;
    const pending={controller:new AbortController(),timer:null,timedOut:false};state.read=pending;
    pending.timer=setTimeout(()=>{pending.timedOut=true;pending.controller.abort();},30000);
    const read=url=>api(url,{signal:pending.controller.signal});
    node('flowContent').innerHTML='<div class="ff-state" role="status">Loading fabrication process records…</div>';
    node('flowContent').setAttribute('aria-busy','true');
    try{
      const [catalog,board,detail,handoffOptions,spools]=await Promise.all([
        state.catalog?Promise.resolve(state.catalog):read(ROOT+'/catalog'),
        item?Promise.resolve(null):read(ROOT+'/items'),
        item?read(ROOT+'/items/'+encode(item)):Promise.resolve(null),
        item?read('/api/transfers/options'):Promise.resolve(null),
        item?Promise.resolve(null):read(ROOT+'/board'),
      ]);
      if(sequence!==state.sequence)return;
      if(item&&detail?.item?.id!==item)throw Error('The process record does not match the selected item. Reopen it and try again.');
      if(!item&&(!Array.isArray(board?.items)||!Array.isArray(spools?.items)))throw Error('The process records could not be verified. Refresh to load the current work.');
      state.catalog=catalog;state.handoffOptions=handoffOptions;state.board=item?[]:board.items;if(!item)state.spools=spools?.items||[];state.detail=markTimes(detail);
      for(const row of state.board)markTimes(row);
      render();updateUrl();
    }catch(error){
      if(sequence!==state.sequence)return;
      const message=pending.timedOut?'This request took too long. Try again to load the current process record.':errorText(error);
      node('flowContent').innerHTML=`<div class="ff-state ff-error" role="alert"><strong>Process records could not be loaded.</strong><p>${esc(message)}</p><div class="actions">${action('refresh','Try again')}${action('board','Back to process board')}</div></div>`;
    }finally{clearTimeout(pending.timer);pending.controller.abort();if(state.read===pending)state.read=null;if(sequence===state.sequence)node('flowContent').setAttribute('aria-busy','false')}
  }
  function cancelRead(){const pending=state.read;if(!pending)return;state.read=null;clearTimeout(pending.timer);pending.controller.abort();}
  async function refresh(){await load()}
  function heading(title,description,controls='',spool=null){
    return `<div class="ff-head"><div><div class="ff-eyebrow">CLM fabrication · Track. Verify. Build. Deliver.</div><h1>${spool?spoolText(spool,title):esc(title)}</h1><p>${esc(description)}</p></div><div class="actions">${controls}${action('refresh','Refresh')}</div></div>`;
  }
  function lookup(){
    return '<form id="flowLookupForm" class="ff-lookup"><div class="field"><label for="flowLookup">Scan or enter item ID</label><input id="flowLookup" name="item" required autocomplete="off" placeholder="Component, spool, or assembly ID"></div><button type="submit" class="primary">Open record</button><p class="ff-help">Use a barcode scanner, type the ID, or paste a FabTrace QR link. A phone QR opens the item record, where Process flow is available.</p></form>';
  }
  function visibleItems(ignoreStep=false,source=state.board){
    const query=state.query.trim().toLowerCase();
    return source.filter(row=>(!state.project||row.project_id===state.project)&&(!state.subproject||row.subproject_id===state.subproject)&&(!state.status||displayStatus(row)===state.status)&&(ignoreStep||!state.step||matchesChartStep(row,state.step))&&(!query||[row.item_id,row.spool_number,row.google_part_number,row.qr_alias,row.display_code,row.current_title,row.flow_stage?.label,row.project_id,row.subproject_id,row.purchase_order,row.assembly_id,row.assembly_number,row.work?.title,row.work?.custodian_badge].some(value=>String(value||'').toLowerCase().includes(query))));
  }
  function filters(){
    const records=[...state.spools,...state.board];
    const projects=[...new Set([...records.map(row=>row.project_id),state.project].filter(Boolean))].sort();
    const subs=[...new Set(records.filter(row=>!state.project||row.project_id===state.project).map(row=>row.subproject_id).filter(Boolean))].sort();
    return `<div class="ff-filters"><div class="field"><label for="flowProject">Project</label><select id="flowProject">${option('','All projects',state.project)}${projects.map(value=>option(value,value,state.project)).join('')}</select></div><div class="field"><label for="flowSubproject">Subproject</label><select id="flowSubproject">${option('','All subprojects',state.subproject)}${subs.map(value=>option(value,value,state.subproject)).join('')}</select></div><div class="field"><label for="flowStatus">Status</label><select id="flowStatus">${option('','All statuses',state.status)}${['not_started','active','rework','admin_released','completed','shipped','delivered'].map(value=>option(value,statusNames[value],state.status)).join('')}</select></div><div class="field ff-search"><label for="flowSearch">Find spool or process</label><input id="flowSearch" type="search" value="${esc(state.query)}" placeholder="Spool number, process, P.O. or ID"></div></div>${state.step?`<div class="notice">Showing step ${esc(state.step)} · ${esc(chartStepLabel(state.step))} ${action('clear-step','Clear step filter','','ff-link')}</div>`:''}`;
  }
  function counts(rows){
    const values=[['In progress',rows.filter(row=>row.status==='active').length,'Active component, spool, and assembly routes'],['Needs rework',rows.filter(row=>num(row.open_exceptions)>0).length,'Open process exceptions'],['Shipped',rows.filter(row=>row.status==='shipped').length,'Awaiting delivery receipt'],['Delivered',rows.filter(row=>row.status==='delivered').length,'Delivery recorded']];
    return `<div class="ff-metrics">${values.map(([label,value,description])=>`<div class="ff-metric"><span>${label}</span><strong>${value}</strong><small>${description}</small></div>`).join('')}</div>`;
  }
  function timingCell(row){
    const process=row.production_process,current=process?.current;
    if(!current)return '<span class="muted">—</span>';
    return clock(process,current.elapsed_seconds,['running','paused'].includes(process.status))+secondary(process.status==='paused'?'Paused':'Running');
  }
  function workRecords(work){
    return arr(work?.requirements).length?`<p class="ff-work-records"><strong>Required records:</strong> ${arr(work.requirements).map(value=>esc(value)).join(' · ')}</p>`:'';
  }
  function positionWork(){
    const detail=state.detail,flow=detail.flow,work=detail.work;
    if(!flow)return '';
    const steps=arr(flow.steps).filter(step=>arr(step.roles).includes(me?.role));
    const own=work?.for_position===true,waiting=work?.pending===true&&!own;
    let message=removed()?'This removed record is available for history only.':work?.restriction||
      (waiting?`The current step belongs to ${arr(work.responsible_roles).map(roleLabel).join(' / ')}.`:own?'Review the required checks below and complete the work using the current-step form.':'Review the recorded and upcoming steps for your position on this route.');
    return `<section class="card ff-position-work"><div class="ff-section-head"><div><div class="ff-eyebrow">${esc(me?.name||me?.badge||'Employee')} · ${esc(roleLabel(me?.role))}</div><h2>Your tasks & requirements</h2></div>${work?.in_custody?tag('active','In your custody'):''}</div><p>${esc(message)}</p>${workRecords(work)}<details class="ff-fold"><summary>Steps for your position on this ${esc(routeNames[flow.route]?.toLowerCase()||'item')} (${steps.length})</summary>${steps.length?`<ol class="ff-position-steps">${steps.map(step=>`<li><div><strong>${esc(chartStepNumber(step.number,flow.catalog_version,step.testing_phase||''))} · ${esc(step.title)}</strong>${tag(step.status,stepStatusNames[step.status]||'Not recorded')}</div><ul>${arr(step.checks).map(check=>`<li>${esc(check.label)}</li>`).join('')}</ul>${step.last_actor?`<p class="ff-secondary">Last recorded by ${esc(step.last_actor)}${step.completed_at?` · ${esc(stamp(step.completed_at))}`:''}</p>`:''}</li>`).join('')}</ol>`:'<p class="ff-footer-note">This route currently has no numbered steps for your position. Related component and assembly work stays on its own record; testing duties appear when the required testing phase is reached.</p>'}</details></section>`;
  }
  function renderBoard(){
    const rows=visibleItems(),spools=visibleItems(false,state.spools);
    let html=heading('Fabrication process flow','Each individual spool appears under its current process. Select its spool number to open the physical record and its production steps.')+filters();
    html+=flowStatus()?.processBoard?.(spools,{attribute:'data-flow-spool',title:'Individual spools by process',catalog:state.catalog.stage_catalog})||empty('Individual spool board unavailable','Refresh to load the current spool positions.');
    html+=(flowStatus()?.legend(state.catalog.stage_catalog)||'')+lookup();
    html+=`<section class="card"><details class="ff-fold"><summary>Traveler records · ${rows.length} matching records</summary>${counts(rows)}<div class="ff-section-head"><h2>Numbered route records</h2></div>`;
    html+=rows.length?table(`<table class="ff-table"><thead><tr><th>Item / route</th><th>Project</th><th>Flow status / current step</th><th>Time in process</th><th>Status</th><th>Attention</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${action('item',itemLabel(row),row.item_id,'ff-link',isSpool(row)?row:null)}${secondary(routeNames[row.route]||row.route)}</td><td>${esc(row.project_id||'Unassigned')}${secondary(row.subproject_id||'')}</td><td><div class="ff-stage-label">${stageBadge(row.flow_stage)}</div>${row.current_step?`<strong>${esc(rowStepNumber(row))} · ${esc(row.current_title)}</strong>`:'<span class="muted">Route finished</span>'}</td><td>${timingCell(row)}</td><td>${tag(displayStatus(row))}</td><td>${num(row.open_exceptions)?`${num(row.open_exceptions)} open exception${num(row.open_exceptions)===1?'':'s'}`:arr(row.blockers).length?esc(row.blockers[0]):'<span class="muted">—</span>'}</td></tr>`).join('')}</tbody></table>`):empty('No matching process records',state.board.length?'Clear the filters or choose another project.':'Open an existing item above. An administrator or Shop Foreman can start its component, spool, or assembly route.');
    html+='</details></section><section class="card"><details class="ff-fold"'+(state.step?' open':'')+'><summary>The '+catalogLast()+'-step fabrication flow</summary><p class="ff-footer-note">Select a numbered step to filter the board. Components follow steps 1–8, spools follow 9–16, and new assemblies follow 17–'+catalogLast()+'. Each saved traveler retains its own route definitions.</p>'+renderMap(false)+'</details></section>';
    return html;
  }
  function stepState(step){
    const flow=state.detail?.flow;if(!flow)return 'pending';
    if(step.route!==flow.route)return 'other_route';
    const status=arr(flow.steps).find(row=>Number(row.number)===Number(step.number))?.status||'pending';
    return openExceptions().some(row=>Number(row.step)===Number(step.number))?'rework':status;
  }
  function renderMap(selected){
    const mapItems=visibleItems(true),definitions=selected?arr(state.detail?.flow?.steps):arr(state.catalog.steps),version=selected?currentCatalogVersion():state.catalog.version;
    return `<div class="ff-map">${phases.map(phase=>{
      const steps=definitions.filter(step=>step.number>=phase.first&&step.number<=phase.last);if(!steps.length)return '';
      const content=phase.id==='assembly'&&hasInlineTesting(selected)?inlineTestingChart(selected):`<ol>${steps.map(step=>{const number=chartStepNumber(step.number,version),visual=selected?stepState(step):state.step&&Number(state.step)===number?'current':'pending',count=mapItems.filter(row=>matchesChartStep(row,number,version)).length;return `<li class="ff-map-step ${visual}" data-flow-chart-step="${number}"><span class="ff-num">${number}</span><div class="ff-map-copy">${selected?`<strong>${esc(step.title)}</strong>`:action('filter-step',step.title,String(number),'ff-link')}<small>${selected?(visual==='other_route'?esc(routeNames[step.route]+' record'):stepStatusNames[visual]):count?`${count} record${count===1?'':'s'} at this step`:esc(routeNames[step.route]+' route')}</small></div></li>`}).join('')}</ol>`;
      const first=Math.min(...steps.map(step=>chartStepNumber(step.number,version))),last=phase.id==='assembly'&&hasInlineTesting(selected)&&version==='CLM-25-v1'?23:Math.max(...steps.map(step=>chartStepNumber(step.number,version)));
      return `<section class="ff-map-section" data-phase="${phase.id}"><h3>${first}–${last} · ${phase.label}</h3>${content}</section>`;
    }).join('')}</div>`;
  }
  function routeProgress(){
    const flow=state.detail.flow,inline=hasInlineTesting(true);
    return `<div class="ff-route" aria-label="${esc(routeNames[flow.route]||flow.route)} route progress">${arr(flow.steps).map(step=>{
      if(inline&&step.number===17)return inlineTestingChart(true);
      if(inline&&[18,19].includes(step.number))return '';
      const visual=stepState(step),number=chartStepNumber(step.number);return `<div class="ff-route-step ${visual}" data-flow-chart-step="${number}"${step.status==='current'?' aria-current="step"':''}><span class="ff-num">${number}</span><strong>${esc(step.title)}</strong><small>${esc(stepStatusNames[visual])}</small>${visual==='not_required'?'<small>Testing decision: NO</small>':''}</div>`;
    }).join('')}</div><div class="ff-legend"><span class="done">Completed</span><span class="current">Current step</span><span>Upcoming</span><span class="rework">Needs reinspection</span><span class="unknown">Earlier work not recorded</span>${arr(flow.steps).some(step=>step.status==='not_required')?'<span class="not-required">Not required by the recorded testing decision</span>':''}</div>`;
  }
  function timing(){
    const detail=state.detail,flow=detail.flow,process=detail.production_process,current=process?.current;
    if(!process||!flow)return '';
    const asOf=new Date(process.as_of).getTime(),entered=new Date(flow.step_entered_at).getTime();
    const age=Number.isFinite(asOf)&&Number.isFinite(entered)?Math.max(0,(asOf-entered)/1000):num(current?.elapsed_seconds);
    const running=process.status==='running'&&Boolean(current),paused=process.status==='paused'&&Boolean(current);
    let html='<div class="ff-time-row">';
    if(flow.current)html+=`<div><span>${activeTesting()?'Time in current phase':'Time at current step'}</span><strong>${clock(process,age,flow.status==='active')}</strong></div>`;
    if(current)html+=`<div><span>Running time</span><strong>${clock(process,current.active_seconds,running)}</strong></div><div><span>Paused time</span><strong>${clock(process,current.paused_seconds,paused)}</strong></div>`;
    html+='</div>';
    if(current)html+=`<div class="actions">${can('pause')?action('pause','Pause / record delay'):''}${can('resume')?action('resume','Resume process'):''}${process.status==='paused'?tag('rework','Process paused'):''}</div>`;
    return html+`<p class="ff-footer-note">Elapsed clock time includes pauses. This measures the item’s time in the process, not employee labor hours. ${activeTesting()?'Phase timers move with each recorded testing transition.':'Stage timers move when the numbered step advances.'}</p>`;
  }
  function stepInputs(step){
    let content='';
    if(step.requires_scan)content+=field('scanned_item_id','Scan or enter this item ID again','',{required:true,maxlength:500,help:'Verify the physical item being processed: '+state.detail.item.id});
    if(childScans(step))content+=field('scanned_child_ids','Scan or enter each linked spool ID','',{required:true,type:'textarea',full:true,rows:4,help:'One spool ID or FabTrace QR link per line. Verify every linked spool before recording this assembly’s testing decision.'});
    if(step.requires_handoff){
      content+=handoffInputs(step);
    }else if(step.requires_location||step.number===3){
      const transfer=state.detail.transfer||state.detail.item.transfer;
      content+=`<div class="field"><label for="ff-field-location_id">${step.number===3?'Storage location':'Receiving location / work center'} *</label><select id="ff-field-location_id" name="location_id" required>${window.FabHandoff.locationOptions(state.handoffOptions,transfer,transfer?.location?'current':'')}</select><span class="ff-form-help">Choose an active work center or retain the actual recorded location.</span></div>`;
    }
    if(step.number===5)content+=field('target_spool_id','Assigned spool ID',state.detail.parent?.item_id||'',{required:true,maxlength:500,help:'This must match the spool linked to this component.'});
    if(step.requires_reference||testingReview())content+=field('reference',activeTesting()?.action==='complete'?testName(activeTesting())+' report reference':testingReview()?'QA/QC inspection / approval or NCR reference':activeTesting()?.action==='correct'?'Repair / corrective work record reference':step.number===18?'Hydro/UT test report / approval reference':step.qa?'Inspection report / approval reference':'PO, BOM, drawing, or record reference','',{required:true,minlength:2,maxlength:500,full:true});
    if(isShipmentStep(step))content+=field('carrier','Carrier','',{required:true,maxlength:160})+field('shipment_reference','Shipping document / tracking reference','',{required:true,maxlength:500})+field('destination','Destination / customer','',{required:true,maxlength:500,full:true});
    if(needsResolution(step))content+=field('resolution',activeTesting()?.action==='correct'?'Completed rework and corrective action':'Rework resolution and reinspection findings','',{required:true,type:'textarea',full:true,maxlength:3000});
    content+=field('notes','Work notes / measurements','',{type:'textarea',full:true,maxlength:3000});
    return fields(content);
  }
  function blockers(){
    const list=arr(state.detail.flow?.blockers);
    return list.length?`<div class="ff-blockers"><strong>${testingReview()?'QA/QC PASS is blocked':'Resolve before completing this step'}</strong><ul>${list.map(value=>`<li>${esc(value)}</li>`).join('')}</ul></div>`:'';
  }
  function currentStep(){
    const detail=state.detail,flow=detail.flow,step=flow.current;
    if(!step){
      const inheritedAssembly=flow.route==='spool'&&detail.parent?.route==='assembly'&&detail.flow_stage?.inherited===true&&detail.flow_stage.source_item_id===detail.parent.item_id;
      let title=flow.status==='admin_released'?'Administrative release':flow.status==='shipped'?'Shipment recorded · awaiting delivery':flow.status==='delivered'?'Delivered to customer':'Route complete';
      let description=flow.route==='component'?'This component is ready for the linked spool’s fabrication route.':flow.route==='spool'?'This completed spool can be collected for its assembly.':'The assembly’s recorded route is complete.';
      if(flow.status==='admin_released')description='An administrator released this component. Its recorded work, inspections and unresolved requirements retain their actual status. Admin controls can return it to its previous process position.';
      if(flow.status==='shipped')description='Record the delivery receipt when the customer receives the assembly.';
      if(flow.status==='delivered')description='The delivery acknowledgment remains in the process history.';
      if(inheritedAssembly)description='This spool’s fabrication route is complete. Its recorded station follows the parent assembly, where testing and finishing are recorded for the linked spools.';
      const shipment=['shipped','delivered'].includes(flow.status)?metadata([['Shipped',stamp(flow.shipped_at)],['Carrier',flow.carrier],['Shipping reference',flow.shipment_reference],['Destination',flow.destination],...(flow.status==='delivered'?[['Delivered',stamp(flow.delivered_at)],['Receipt reference',flow.receipt_reference],['Received by',flow.recipient]]:[])]):'';
      return `<section class="card ff-current"><div class="ff-current-label">${esc(routeNames[flow.route])} route</div><h2>${title}</h2><p class="muted">${description}</p>${inheritedAssembly?`<div class="actions">${action('item','Open assembly process',detail.parent.item_id,'primary')}</div>`:''}${shipment}${can('deliver')?action('deliver','Record delivery receipt','','primary'):''}${timing()}</section>`;
    }
    const allowed=can('advance')||testingReview()&&can('fail'),qa=step.qa,blocked=arr(flow.blockers).length>0;
    let html=`<section class="card ff-current"><div class="ff-section-head"><div><div class="ff-current-label">Current step ${currentStepNumber(step)} · ${esc(routeNames[flow.route])} route</div><h2>${esc(step.title)}</h2></div>${tag(openExceptions().length?'rework':'active')}</div>${testingSummary()}${timing()}${blockers()}`;
    html+=`<p class="ff-footer-note">Recorded by: ${arr(step.roles).map(value=>esc(roleLabel(value))).join(' · ')}</p>`;
    if(allowed)html+='<form id="flowStepForm"><div id="flowStepError" class="ff-error hidden" role="alert"></div>'+testingChoices();
    if(allowed&&testingReview())html+='<fieldset id="flowTestingPassChecks" class="ff-testing-pass-checks">';
    html+=`<ul class="ff-checklist">${arr(step.checks).map(check=>`<li>${allowed?`<label><input type="checkbox" name="check_${esc(check.id)}" required> <span>${esc(check.label)}</span></label>`:`<span class="ff-check-read">${esc(check.label)}</span>`}</li>`).join('')}</ul>`;
    if(allowed&&testingReview())html+='</fieldset>';
    if(allowed){
      html+=stepInputs(step)+testingFailureInputs(step)+`<div class="actions"><button id="flowAdvance" type="submit" class="primary"${blocked?' disabled':''}>${activeTesting()?esc(testingButton(activeTesting())):isShipmentStep(step)?'Record shipment':qa?'Pass inspection & continue':'Complete step '+currentStepNumber(step)}</button>${can('fail')&&!activeTesting()?action('fail',step.number===2?'Record failure / exception':'Record failed inspection'):''}</div></form>`;
    }else{
      html+=`<p class="ff-footer-note">${esc(testingActorRestriction()||'An authorized employee can complete this step after checking the physical item and its records.')}</p>`;
      if(can('fail')&&!activeTesting())html+=action('fail','Record failed inspection');
    }
    if(can('restart-testing'))html+=`<div class="actions">${action('restart-testing','Return to testing')}</div><p class="ff-footer-note">Start a new testing cycle when changed material or physical scope requires another review.</p>`;
    return html+'</section>';
  }
  function childCard(child){
    return `<div class="ff-family">${action('item',itemLabel(child),child.item_id,'ff-link',isSpool(child)?child:null)}${stageBadge(child.flow_stage)}${tag(displayStatus(child))}${child.current_step?`<p>${esc(rowStepNumber(child))} · ${esc(child.current_title)}</p>`:''}</div>`;
  }
  function family(){
    const detail=state.detail,flow=detail.flow,components=arr(detail.components),spools=arr(detail.spools),orderedAssembly=flow.route==='assembly'&&detail.order_scope?.assembly_id===detail.item.id;
    let html='<section class="card"><div class="ff-section-head"><h2>Linked material & assemblies</h2></div><p class="ff-footer-note">Each link connects separate physical records: components → spool → assembly.</p>';
    if(detail.parent)html+=`<h3>${detail.parent.route==='assembly'?'Parent assembly':'Assigned spool'}</h3><div class="ff-family">${action('item',itemLabel(detail.parent),detail.parent.item_id,'ff-link',isSpool(detail.parent)?detail.parent:null)}</div>`;
    if(flow.route==='component'&&!detail.parent)html+='<p class="muted">No spool assigned yet.</p>';
    if(flow.route==='spool')html+=`<h3>Components · ${components.length} / ${num(flow.expected_children)} expected</h3>${components.length?components.map(childCard).join(''):'<p class="muted">No components linked. Open a component’s process record to assign it to this spool.</p>'}`;
    if(flow.route==='assembly')html+=`<h3>Spools · ${spools.length} / ${num(flow.expected_children)} expected</h3>${spools.length?spools.map(childCard).join(''):'<p class="muted">No spools linked yet.</p>'}`;
    html+=`<div class="actions">${can('assign-component')?action('assign-component',detail.parent?'Update spool assignment':'Assign component to spool'):''}${can('link-spool')?action('link-spool','Link spool to assembly'):''}${can('scope')&&!orderedAssembly?action('scope','Edit required count'):''}</div>`;
    if(testingScopeFrozen())html+='<p class="ff-footer-note">The linked spool scope is fixed by this recorded testing route.</p>';
    if(orderedAssembly)html+=`<p class="ff-footer-note">Required spool count is managed by PO <strong>${esc(detail.order_scope.purchase_order)}</strong> · GPN / Assembly ${esc(detail.order_scope.gpn)}${detail.order_scope.assembly_part_number!==detail.order_scope.gpn?` · Retained part number ${esc(detail.order_scope.assembly_part_number)}`:''}. The count is locked once the assembly traveler starts.</p>`;
    if(flow.material_reference)html+=`<p class="ff-footer-note">Existing material basis: ${esc(flow.material_reference)}</p>`;
    return html+'</section>';
  }
  function exceptions(){
    const rows=arr(state.detail.exceptions);
    return `<section class="card"><div class="ff-section-head"><h2>Exceptions & rework</h2><span class="muted">${rows.filter(row=>!row.closed_at).length} open</span></div>${rows.length?rows.map(row=>{
      const event=arr(state.detail.events).find(event=>event.action==='fail'&&row.id!=null&&String(event.data?.exception_id)===String(row.id)),savedDefinition=event?.data?.step_definition;
      const title=savedDefinition?.title||(event?.data?.testing_phase?testingPhaseName(event.data.testing_phase,event.data.definition_version||'CLM-24-v6'):testing()&&Number(row.step)===18?'QA/QC test-result review':definition(row.step)?.title||'Inspection');
      return `<article class="ff-exception ${row.closed_at?'closed':''}"><strong>Step ${esc(row.step)} · ${esc(title)}</strong>${secondary(row.closed_at?'Resolved':'Open · returned to step '+row.return_step)}<p>${esc(row.reason)}</p>${row.reference?`<p>Reference: ${esc(row.reference)}</p>`:''}<p class="ff-footer-note">${esc(row.opened_by)} · ${esc(stamp(row.opened_at))}</p>${row.closed_at?`<p><strong>Resolution:</strong> ${esc(row.resolution)}</p><p class="ff-footer-note">${esc(row.closed_by)} · ${esc(stamp(row.closed_at))}</p>`:''}</article>`;
    }).join(''):'<p class="muted">No process exceptions recorded.</p>'}</section>`;
  }
  function eventHistory(){
    const labels={start:'Route started',adopt:'Existing work adopted',advance:'Step completed',fail:'Inspection failed',deliver:'Delivery recorded',assign_component:'Component assigned',link_spool:'Spool linked',shipment:'Shipment recorded'};
    const rows=arr(state.detail.events);
    return `<section class="card"><h2>Process history</h2>${rows.length?[...rows].reverse().map(row=>{
      const data=row.data||{},isTesting=data.testing_protocol==='CLM-TEST-v1',restarted=isTesting&&data.testing_action==='restart',phase=isTesting?testingPhaseName(restarted?data.next_phase:data.testing_phase,data.definition_version||'CLM-24-v6',restarted?null:data.step_definition):'',cycle=restarted?data.next_cycle:data.testing_cycle,attempt=restarted?null:data.testing_attempt,decision=restarted&&data.testing_required_preserved===true?'YES':data.testing_decision||data.decision,result=data.test_result;
      const recorded=isTesting?({decision:'Testing decision recorded',start:'Test receipt recorded',complete:'Technician test report recorded',review:'QA/QC result recorded',correct:'Completed rework recorded',handoff:'Floor handoff recorded',restart:'Returned to testing'})[data.testing_action]:null;
      return `<div class="ff-history"><strong>${esc(recorded||labels[row.action]||String(row.action).replace(/_/g,' '))}${row.step?' · step '+esc(row.step):''}</strong>${data.step_definition?.title?`<p class="ff-recorded-step">${esc(data.step_definition.title)}</p>`:''}${isTesting?`<p>${esc(phase)}${Number.isInteger(cycle)&&cycle>1?' · Cycle '+cycle:''}${Number.isInteger(attempt)?' · Attempt '+attempt:''}${['YES','NO'].includes(decision)?' · Testing required: '+esc(decision):''}${['PASS','FAIL'].includes(result)?' · Result: '+esc(result):''}</p>`:''}${row.reference?`<p>Reference: ${esc(row.reference)}</p>`:''}${row.notes?`<p>${esc(row.notes)}</p>`:''}<small>${esc(row.actor)} · ${esc(stamp(row.at))}</small>${Object.keys(data).length?`<details><summary class="ff-footer-note">Recorded details</summary><pre>${esc(JSON.stringify(data,null,2))}</pre></details>`:''}</div>`;
    }).join(''):'<p class="muted">No route events recorded.</p>'}</section>`;
  }
  function timingHistory(){
    const process=state.detail.production_process;if(!process)return '';
    const totals=process.totals||{},rows=arr(process.by_process),delays=arr(process.events).filter(row=>['pause','resume'].includes(row.event));
    if(!rows.length)return '';
    return `<section class="card"><h2>Recorded process time</h2><p class="ff-footer-note">${duration(totals.elapsed_seconds)} recorded across ${num(totals.visits)} visits as of ${esc(stamp(process.as_of))}. Return visits stay in the totals.</p>${table(`<table><thead><tr><th>Process</th><th>Visits</th><th>Elapsed</th><th>Running</th><th>Paused</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.process_name)}</td><td>${num(row.visits)}</td><td>${duration(row.elapsed_seconds)}</td><td>${duration(row.active_seconds)}</td><td>${duration(row.paused_seconds)}</td></tr>`).join('')}</tbody></table>`)}${delays.length?`<details class="ff-fold"><summary>Pause history (${delays.length})</summary>${[...delays].reverse().map(row=>`<div class="ff-history"><strong>${row.event==='pause'?'Paused':'Resumed'} · ${esc(row.process_name)}</strong><p>${esc(row.notes||'')}</p><small>${esc(row.actor)} · ${esc(stamp(row.at))}</small></div>`).join('')}</details>`:''}</section>`;
  }
  function renderDetail(){
    const detail=state.detail,item=detail.item,flow=detail.flow;
    let controls=action('board','Process board')+action('item-record','Item & QR record',item.id);
    if(me?.role==='admin'&&!removed())controls+=action('admin-controls','Admin controls',item.id);
    if(['spool','assembly'].includes(flow?.route||detail.suggested_route)||['Spool','Assembly'].includes(item.kind))controls+=action('weld-record','Individual welds',item.id);
    if((flow?.route||detail.suggested_route)==='spool'||item.kind==='Spool')controls+=action('spool-parts','Spool parts',item.id);
    const identity={...item,route:flow?.route||item.route||detail.suggested_route,flow_stage:item.flow_stage||detail.flow_stage};
    let html=heading(itemLabel(identity),item.kind||'Fabrication item',controls,isSpool(identity)?identity:null)+(flowStatus()?.strip(detail.stage_catalog||state.catalog.stage_catalog,detail.flow_stage)||'')+(flowStatus()?.legend(detail.stage_catalog||state.catalog.stage_catalog)||'')+lookup();
    if(removed())html+='<div class="fr-removed-notice"><strong>Removed record · History only</strong><p>Its process route, checks and timing are retained. Open Item &amp; QR record to review or restore its removed group.</p></div>';
    if(state.notice)html+=`<div class="ff-error" role="alert">${esc(state.notice)}</div>`;
    if(!flow){
      html+=`<section class="card"><h2>Start a numbered process route</h2>${metadata([['Item type',item.kind],['Project',item.project],['Location',item.location],['Current handler',item.handler]])}<p>Components follow steps 1–8, spools follow 9–16, and assemblies follow 17–${catalogLast()}. Begin at the first step, or record a documented starting point for existing work.</p>${can('start')?action('start','Set up process route','','primary'):'<p class="muted">A Shop Foreman or administrator can start this item’s route.</p>'}</section>`;
      return html+'<section class="card"><h2>The fabrication flow</h2>'+renderMap(false)+'</section>';
    }

    if(detail.parts?.configured){const t=detail.parts.totals||{},required=num(t.required_qty),prepared=num(t.prepared_qty);html+=`<section class="card"><div class="ff-section-head"><h2>Required component pieces</h2>${action('spool-parts','Spool parts',item.id)}</div><p>${prepared} of ${required} required pieces prepared for fit-up · ${num(t.assigned_qty)} assigned · ${num(t.received_qty)} receipt recorded · ${num(t.short_qty)} still to assign</p>${required>0?`<progress max="${required}" value="${Math.min(required,prepared)}" aria-label="Required pieces prepared for fit-up" style="width:100%"></progress>`:''}</section>`;}
    html+=positionWork()+`<div class="ff-grid"><div>${currentStep()}${exceptions()}</div><div>${family()}<section class="card"><h2>Item record</h2>${metadata([['Project',detail.project_id||item.project],['Subproject',detail.subproject_id],['Location',item.location],['Current handler',item.handler],['Work status',(detail.transfer||item.transfer)?.status_label||'Not recorded'],['Drawing',item.drawing],['Release decision',(detail.release_control||item.release_control)?.label||(item.released?'Released':'Not released')]])}<p class="ff-footer-note">Each step stores its actor, time, checks, and reference. Quality acceptance and shipment remain separate records.</p></section></div></div>`;

    html+=`<section class="card"><div class="ff-section-head"><h2>${esc(routeNames[flow.route])} route · steps ${chartStepNumber(route(flow.route)?.first_step)}–${chartStepNumber(route(flow.route)?.last_step)}</h2>${tag(openExceptions().length?'rework':flow.status)}</div>${routeProgress()}${flow.baseline_reference?`<p class="ff-footer-note"><strong>Existing work starting point:</strong> ${esc(flow.baseline_reference)} · ${esc(flow.baseline_reason||'')} Earlier steps marked “Not recorded” have no completion recorded in this route.</p>`:''}</section>`;
    html+=`<section class="card"><details class="ff-fold"><summary>View this traveler’s numbered route</summary><p class="ff-footer-note">These are the saved definitions for this ${esc(routeNames[flow.route].toLowerCase())} traveler. Linked components, spools and assemblies retain their own routes.</p>${renderMap(true)}</details></section>`;
    return html+timingHistory()+eventHistory();
  }
  function render(){
    if(!state.catalog)return;
    state.handoffControl?.destroy();state.handoffControl=null;
    node('flowContent').innerHTML=state.detail?renderDetail():renderBoard();
    node('flowContent').setAttribute('aria-busy','false');wire();startClocks();
  }
  function wire(){
    const lookupForm=node('flowLookupForm');
    if(lookupForm)lookupForm.onsubmit=async event=>{event.preventDefault();const sequence=state.sequence,lookup=state.lookup=(state.lookup||0)+1;try{const item=await readId(node('flowLookup').value);if(sequence!==state.sequence||lookup!==state.lookup)return;await open({item})}catch(error){if(sequence===state.sequence&&lookup===state.lookup)notify(errorText(error))}};
    for(const [id,key] of [['flowProject','project'],['flowSubproject','subproject'],['flowStatus','status']]){
      const element=node(id);if(element)element.onchange=()=>{state[key]=element.value;if(key==='project')state.subproject='';render();updateUrl()};
    }
    const search=node('flowSearch');if(search)search.oninput=()=>{state.query=search.value;const start=search.selectionStart,end=search.selectionEnd;render();node('flowSearch').focus();node('flowSearch').setSelectionRange(start,end)};
    const form=node('flowStepForm');if(form)form.onsubmit=submitStep;
    for(const name of ['testing_decision','test_result'])for(const choice of ['YES','NO','PASS','FAIL'])if(node('ff-'+name+'-'+choice))node('ff-'+name+'-'+choice).onchange=updateTestingChoice;
    if(node('flowHandoffSender')){
      const transfer=state.detail.transfer||state.detail.item.transfer;
      const update=control=>{if(node('flowHandoffReview'))node('flowHandoffReview').innerHTML=window.FabHandoff.reviewHtml(control,transfer,state.handoffOptions,state.detail.item)};
      state.handoffControl=window.FabHandoff.bindControls('flowHandoff',{transfer,options:state.handoffOptions,onChange:update});constrainHandoffDestination();update(state.handoffControl);
    }
    updateTestingChoice();
  }
  async function save(path,payload){
    if(state.saving)return false;
    state.saving=true;const itemId=state.item,sequence=state.sequence;
    try{
      await api(path,{method:'POST',body:JSON.stringify(payload)});
      if(state.item!==itemId||state.sequence!==sequence)return false;
      state.notice='';notify('Process record saved.');
      await load();
      return true;
    }catch(error){
      if(state.item!==itemId||state.sequence!==sequence)return false;
      if(error.status===409){
        state.notice=errorText(error)+' The record has been refreshed. Review the current step before trying again.';
        state.dialogStale=true;
        if(state.item===itemId)await load();
      }
      throw error;
    }finally{state.saving=false}
  }
  async function submitStep(event){
    event.preventDefault();if(state.saving)return;
    const detail=state.detail,step=detail.flow.current,sequence=state.sequence,value=activeTesting();if(!step)return;
    const values=Object.fromEntries(new FormData(event.target)),button=node('flowAdvance'),errorNode=node('flowStepError');
    const qaFail=value?.action==='review'&&values.test_result==='FAIL';if(!(qaFail?can('fail'):can('advance')))return;
    button.disabled=true;errorNode.classList.add('hidden');
    try{
      if(value?.requires_decision&&!['YES','NO'].includes(values.testing_decision))throw Error('Choose YES or NO to record whether testing is required.');
      if(value?.requires_decision&&value.decision==='YES'&&values.testing_decision==='NO')throw Error('Testing remains required by the recorded YES decision. Select YES to continue this rework cycle.');
      if(value?.requires_result&&!['PASS','FAIL'].includes(values.test_result))throw Error('Choose PASS or FAIL for this test attempt.');
      if(failedTestReport(value)&&values.test_result==='PASS')throw Error('The technician’s report records FAIL. Record a QA/QC FAIL disposition, complete rework, and submit a fresh test before QA/QC PASS.');
      if(value?.action==='review'&&values.test_result==='PASS'&&testingPassBlockers().length)throw Error('QA/QC PASS is blocked: '+testingPassBlockers().join(' '));
      const confirmations=arr(step.checks).filter(check=>values['check_'+check.id]==='on').map(check=>check.id);
      if(!qaFail&&confirmations.length!==arr(step.checks).length)throw Error('Confirm every checklist item before completing this step.');
      const payload={expected_version:detail.flow.version,...testingPayload(value),...(!qaFail?{confirmations,notes:String(values.notes||'').trim()}:{test_result:'FAIL'})};
      if(value?.requires_decision)payload.testing_decision=values.testing_decision;
      if(value?.requires_result)payload.test_result=values.test_result;
      if(step.requires_scan)payload.scanned_item_id=await readId(values.scanned_item_id);
      if(childScans(step)){
        payload.scanned_child_ids=await Promise.all(String(values.scanned_child_ids||'').split(/\r?\n/).map(value=>value.trim()).filter(Boolean).map(value=>readId(value,'Linked spool ID')));
        if(!payload.scanned_child_ids.length)throw Error('Scan or enter each linked spool ID on its own line.');
      }
      if(step.requires_handoff||qaFail){
        if(qaFail&&(!value.return_to?.location_id||!value.return_to?.sender_badge))throw Error('Refresh the recorded return station and sending employee before recording QA/QC FAIL.');
        if(!state.handoffControl)throw Error('Refresh this handoff before identifying both employees.');
        Object.assign(payload,await state.handoffControl.read(values));
        if(value?.action==='start'&&me?.role!=='admin'&&(!me?.badge||payload.receiver_badge!==me.badge))throw Error('The signed-in testing employee must scan their own receiving badge before starting the test.');
        const destination=qaFail?value.return_to?.location_id:step.handoff_location_id;
        if(destination&&payload.location_id!==destination)throw Error('Use the destination required by this step.');
        if(qaFail&&(!value.return_to?.sender_badge||payload.receiver_badge!==value.return_to.sender_badge))throw Error('Scan the receiving badge of the recorded employee who sent this test into QA/QC.');
      }
      else if(step.requires_location||step.number===3){
        const transfer=detail.transfer||detail.item.transfer,location_id=String(values.location_id||'').trim();
        if(!transfer||!Number.isInteger(transfer.version))throw Error('Refresh the current location before completing this step.');
        if(!(location_id==='current'&&transfer.location)&&!arr(state.handoffOptions?.locations).some(row=>row.id===location_id&&row.active))throw Error('Choose an active storage or receiving location.');
        payload.location_id=location_id;payload.expected_transfer_version=transfer.version;
      }
      if(step.number===5)payload.target_spool_id=await readId(values.target_spool_id,'Assigned spool ID');
      if(step.requires_reference||qaFail){payload.reference=String(values.reference||'').trim();if(payload.reference.length<2)throw Error('Enter the required record or inspection reference (at least two characters).');}
      if(isShipmentStep(step))for(const key of ['carrier','shipment_reference','destination']){payload[key]=String(values[key]||'').trim();if(!payload[key])throw Error('Enter the carrier, shipping reference, and destination.');}
      if(!qaFail&&needsResolution(step)){payload.resolution=String(values.resolution||'').trim();if(payload.resolution.length<4)throw Error('Record the completed rework and reinspection findings (at least four characters).');}
      if(qaFail){payload.reason=String(values.reason||'').trim();if(payload.reason.length<4)throw Error('Record the failure, required repair and nonconformance details (at least four characters).');}
      if(state.sequence!==sequence||state.item!==detail.item.id)return;
      await save(ROOT+'/items/'+encode(detail.item.id)+(qaFail?'/fail':'/advance'),payload);
    }catch(error){
      if(state.sequence!==sequence)return;
      const target=node('flowStepError');if(target){target.textContent=errorText(error);target.classList.remove('hidden');target.scrollIntoView({block:'nearest'})}else notify(errorText(error));
    }finally{if(state.sequence===sequence){button.disabled=arr(state.detail?.flow?.blockers).length>0;updateTestingChoice();}}
  }
  function dialog(title,content,callback,label='Save'){
    node('flowDialogTitle').textContent=title;node('flowDialogFields').innerHTML=content;
    node('flowDialogError').textContent='';node('flowDialogError').classList.add('hidden');
    node('flowDialogSubmit').textContent=label;node('flowDialogSubmit').disabled=false;
    state.dialogAction=callback;state.dialogStale=false;node('flowDialog').showModal();
  }
  function startFlow(){
    if(!can('start'))return;
    const item=state.detail.item,initial=state.detail.suggested_route||(item.kind==='Spool'?'spool':item.kind==='Assembly'?'assembly':'component');
    const configuredParts=state.detail.parts?.configured===true,requiredParts=num(state.detail.parts?.totals?.required_qty),orderScope=item.kind==='Assembly'&&state.detail.order_scope?.assembly_id===item.id?state.detail.order_scope:null,requiredSpools=num(orderScope?.required_spools),expectedFor=id=>id==='spool'&&configuredParts?requiredParts:id==='assembly'&&orderScope?requiredSpools:id==='component'?0:1;
    if(initial==='spool'&&configuredParts&&(!Number.isInteger(requiredParts)||requiredParts<1))return notify('Refresh the required parts list before starting this spool route.');
    if(initial==='assembly'&&orderScope&&(!Number.isInteger(requiredSpools)||requiredSpools<1))return notify('Refresh the PO assembly scope before starting this route.');
    const stepOptions=id=>arr(state.catalog.steps).filter(step=>step.route===id&&!(id==='assembly'&&state.catalog.version==='CLM-25-v1'&&[18,19].includes(step.number))).map(step=>[step.number,`${chartStepNumber(step.number,state.catalog.version)} · ${step.title}`]);
    const content='<p>A component, spool, and assembly are separate physical records. Start the route that matches this item.</p>'+(orderScope?`<p class="notice">PO <strong>${esc(orderScope.purchase_order)}</strong> · GPN / Assembly <strong>${esc(orderScope.gpn)}</strong>${orderScope.assembly_part_number!==orderScope.gpn?` · Retained part number <strong>${esc(orderScope.assembly_part_number)}</strong>`:''}<br>Required spools: <strong>${requiredSpools}</strong>, from Purchase orders. Confirm this count before starting; it becomes locked with this traveler.</p>`:'')+(configuredParts?`<p class="notice">Required component count: <strong>${requiredParts}</strong>, from Spool parts (${esc(state.detail.parts.reference||'current list')}). To correct the quantity, close this dialog and open Spool parts.</p>`:'')+fields(field('route','Route',initial,{required:true,options:arr(state.catalog.routes).map(row=>[row.id,`${row.label} · steps ${chartStepNumber(row.first_step,state.catalog.version)}–${chartStepNumber(row.last_step,state.catalog.version)}`])})+field('start_step','Start at step',route(initial)?.first_step,{required:true,options:stepOptions(initial)}))+`<div id="flowChildrenFields">${fields(field('expected_children','Expected child records',expectedFor(initial),{required:true,type:'number',min:0,max:10000,readonly:initial==='spool'&&configuredParts||initial==='assembly'&&Boolean(orderScope),help:orderScope?'Required assembly spools are managed in Purchase orders.':configuredParts?'Spool component quantities are managed in Spool parts.':'Component records for a spool; spool records for an assembly.'})+field('material_reference','Existing material basis (if no components will be linked)','',{maxlength:500,help:'For an existing spool with zero linked components, identify its approved material records.'}))}</div><div id="flowBaselineFields" class="hidden">${fields(field('baseline_reference','Existing-work record / traveler reference','',{maxlength:500,full:true})+field('baseline_reason','Why this item starts after the first route step','',{type:'textarea',maxlength:3000,full:true}))}<p class="ff-form-help">Earlier steps will be marked “Not recorded.” This does not create historical completion or inspection approvals.</p></div>`+fields(field('notes','Setup notes','',{type:'textarea',maxlength:3000,full:true}));
    dialog('Set up process route · '+item.id,content,async values=>{
      const selected=route(values.route),start=Number(values.start_step),expected=values.route==='component'?0:Number(values.expected_children);
      if(!selected||!Number.isInteger(start)||!stepOptions(values.route).some(([number])=>number===start))throw Error(values.route==='assembly'&&[18,19].includes(start)?'Start at Step 17 to record the testing decision; a route cannot start inside an unrecorded testing phase.':'Choose a step within this route.');
      if(!Number.isInteger(expected)||expected<0)throw Error('Expected linked items must be a whole number of zero or more.');
      if(values.route==='spool'&&configuredParts&&expected!==requiredParts)throw Error('The component count must match the current required parts list. Edit quantities in Spool parts.');
      if(values.route==='assembly'&&orderScope&&expected!==requiredSpools)throw Error('The spool count must match the PO assembly scope. Review it in Purchase orders before starting the traveler.');
      const payload={route:values.route,expected_children:expected,start_step:start,notes:String(values.notes||'').trim()};
      if(values.route==='assembly'&&expected<1)throw Error('An assembly needs at least one expected spool.');
      if(values.route==='spool'){payload.material_reference=String(values.material_reference||'').trim();if(!expected&&!payload.material_reference)throw Error('Identify the existing material records when no components will be linked.');}
      if(start>selected.first_step){payload.baseline_reference=String(values.baseline_reference||'').trim();payload.baseline_reason=String(values.baseline_reason||'').trim();if(!payload.baseline_reference||!payload.baseline_reason)throw Error('Enter the existing-work reference and the reason for its starting point.');}
      return save(ROOT+'/items/'+encode(item.id)+'/start',payload);
    },'Start route');
    const updateFields=()=>{
      const selected=node('ff-field-route').value,first=route(selected)?.first_step;
      node('flowChildrenFields').classList.toggle('hidden',selected==='component');
      node('ff-field-expected_children').disabled=selected==='component';
      node('ff-field-expected_children').readOnly=selected==='spool'&&configuredParts||selected==='assembly'&&Boolean(orderScope);
      node('ff-field-material_reference').disabled=selected!=='spool';
      const late=Number(node('ff-field-start_step').value)>first;
      node('flowBaselineFields').classList.toggle('hidden',!late);
      for(const key of ['baseline_reference','baseline_reason']){node('ff-field-'+key).required=late;node('ff-field-'+key).disabled=!late;}
    };
    node('ff-field-route').onchange=()=>{const id=node('ff-field-route').value;node('ff-field-start_step').innerHTML=stepOptions(id).map(row=>option(row[0],row[1],route(id)?.first_step)).join('');node('ff-field-start_step').value=String(route(id)?.first_step);node('ff-field-expected_children').value=String(expectedFor(id));updateFields()};
    node('ff-field-start_step').onchange=updateFields;updateFields();
  }
  function failStep(){
    if(!can('fail'))return;
    if(activeTesting()){if(testingReview()&&node('ff-test_result-FAIL')){node('ff-test_result-PASS').checked=false;node('ff-test_result-FAIL').checked=true;updateTestingChoice();node('ff-field-reason')?.focus();}return;}
    const detail=state.detail,step=detail.flow.current,choices=arr(step.return_steps);
    dialog('Record failure · step '+currentStepNumber(step),'<p>The exception stays in the history. The item returns to the selected process and requires a new inspection before continuing.</p>'+fields(field('reason','Failure / nonconformance and required repair','',{required:true,type:'textarea',full:true,maxlength:3000})+field('reference','Inspection / NCR reference','',{required:true,maxlength:500,full:true})+field('return_step','Return to step',choices[0],{required:true,options:choices.map(number=>[number,`${chartStepNumber(number)} · ${definition(number)?.title||''}`])})),async values=>{
      const payload={expected_version:detail.flow.version,reason:String(values.reason||'').trim(),reference:String(values.reference||'').trim(),return_step:Number(values.return_step)};
      if(!payload.reason||!payload.reference)throw Error('Record the failure reason and inspection reference.');
      if(!choices.includes(payload.return_step))throw Error('Choose an allowed return step.');
      return save(ROOT+'/items/'+encode(detail.item.id)+'/fail',payload);
    },'Record exception & return');
  }
  function editScope(){
    if(!can('scope'))return;
    const detail=state.detail,flow=detail.flow,assembly=flow.route==='assembly',linked=arr(assembly?detail.spools:detail.components).length;
    if(assembly&&detail.order_scope)return notify('This assembly spool count is managed in Purchase orders and is locked by its existing traveler.');
    if(!assembly&&detail.parts?.configured)return window.FabParts.open({spool:detail.item.id,project:flow.project_id||state.project});
    dialog('Edit required '+(assembly?'spool':'component')+' count',`<p>${flow.route==='spool'?spoolText({...detail.item,flow_stage:detail.item.flow_stage||detail.flow_stage}):esc(detail.item.id)} has ${linked} linked ${assembly?'spools':'components'}. Record the corrected scope and its authorization reference.</p>`+fields(field('expected_children','Required '+(assembly?'spools':'components'),flow.expected_children,{required:true,type:'number',min:Math.max(linked,assembly?1:0),max:10000})+(!assembly?field('material_reference','Existing material basis (required for zero components)',flow.material_reference||'',{maxlength:500}):'')+field('reference','Scope / drawing / authorization reference','',{required:true,minlength:2,maxlength:500,full:true})+field('reason','Reason for the count correction','',{required:true,type:'textarea',maxlength:3000,full:true})),values=>{
      const expected=Number(values.expected_children),reason=String(values.reason||'').trim(),reference=String(values.reference||'').trim(),material=String(values.material_reference||'').trim();
      if(!Number.isInteger(expected)||expected<Math.max(linked,assembly?1:0))throw Error('The required count cannot be lower than the linked scope. Assemblies need at least one spool.');
      if(!assembly&&!expected&&material.length<2)throw Error('Identify the existing material records when no components will be linked.');
      if(reason.length<4||reference.length<2)throw Error('Enter the correction reason and authorization reference.');
      return save(ROOT+'/items/'+encode(detail.item.id)+'/scope',{expected_version:flow.version,expected_children:expected,material_reference:material,reason,reference});
    },'Save scope correction');
  }
  function restartTesting(){
    if(!can('restart-testing'))return;
    const detail=state.detail;
    dialog('Return to testing','<p>Return this assembly and its linked spools to Step 17 for a new testing cycle when the earlier testing evidence needs to be reviewed again. The earlier reports, failures, and correction records stay in the route history. Open failure requirements must still be resolved.</p>'+(testing()?.decision==='YES'?'<p class="notice">Testing remains required by the recorded YES decision. The new cycle must complete NDT, pressure testing, and their separate QA/QC reviews.</p>':'')+fields(field('reason','Why testing must be reviewed again','',{required:true,type:'textarea',full:true,maxlength:3000})+field('reference','Changed material, scope, or authorization reference','',{required:true,minlength:2,maxlength:500,full:true})),values=>{
      const reason=String(values.reason||'').trim(),reference=String(values.reference||'').trim();
      if(reason.length<4||reference.length<2)throw Error('Enter the reason (at least four characters) and a source or authorization reference (at least two characters).');
      return save(ROOT+'/items/'+encode(detail.item.id)+'/restart-testing',{expected_version:detail.flow.version,reason,reference});
    },'Return to testing');
  }
  function linkItem(kind){
    if(!can(kind))return;
    const detail=state.detail,assigning=kind==='assign-component',sequence=state.sequence;
    dialog(assigning?'Assign component to spool':'Link spool to assembly',`<p>${esc(detail.item.display_code||detail.item.id)} · ${assigning?'Assign this component to its existing spool record.':'Add an existing spool to this assembly. Verify its physical QR label or tracking ID.'}</p>`+fields(field('spool_id','Scan or enter spool label',assigning?detail.parent?.item_id||'':'',{required:true,maxlength:2000})+field('reference','BOM / drawing / link reference','',{maxlength:500})+field('notes','Link notes','',{type:'textarea',full:true,maxlength:3000})),async values=>{
      const spoolId=await readId(values.spool_id,'Spool label');
      if(state.sequence!==sequence||state.item!==detail.item.id||!node('flowDialog').open)return false;
      return save(ROOT+'/items/'+encode(detail.item.id)+'/'+kind,{expected_version:detail.flow.version,spool_id:spoolId,reference:String(values.reference||'').trim(),notes:String(values.notes||'').trim()});
    },assigning?'Assign component':'Link spool');
  }
  function deliver(){
    if(!can('deliver'))return;
    const detail=state.detail;
    dialog('Record customer delivery','<p>Record the customer’s acknowledgment after the shipped assembly arrives.</p>'+fields(field('receipt_reference','Delivery receipt / proof of delivery','',{required:true,maxlength:500,full:true})+field('recipient','Received by / customer representative','',{required:true,maxlength:200,full:true})+field('notes','Delivery notes','',{type:'textarea',full:true,maxlength:3000})),values=>{
      const payload={expected_version:detail.flow.version,receipt_reference:String(values.receipt_reference||'').trim(),recipient:String(values.recipient||'').trim(),notes:String(values.notes||'').trim()};
      if(!payload.receipt_reference||!payload.recipient)throw Error('Enter the delivery receipt reference and recipient.');
      return save(ROOT+'/items/'+encode(detail.item.id)+'/deliver',payload);
    },'Record delivery');
  }
  function pauseProcess(actionName){
    if(!can(actionName))return;
    const detail=state.detail,process=detail.production_process;
    dialog(actionName==='pause'?'Pause process / record delay':'Resume process',`<p>${esc(detail.flow.current?.title||'Current process')}</p>`+fields(field('notes',actionName==='pause'?'Delay reason':'Resume notes','',{required:actionName==='pause',type:'textarea',full:true,maxlength:2000})),values=>{
      const notes=String(values.notes||'').trim();if(actionName==='pause'&&notes.length<3)throw Error('Record a delay reason of at least 3 characters.');
      return save('/api/tracking/spools/'+encode(detail.item.id)+'/process',{action:actionName,expected_version:process.version,notes});
    },actionName==='pause'?'Pause process':'Resume process');
  }
  async function act(name,id){
    if(name==='board')return open({project:state.project});
    if(name==='refresh')return refresh();
    if(name==='item')return open({item:id});
    if(name==='item-record')return openItem(id);
    if(name==='admin-controls'&&me?.role==='admin')return window.FabAdmin.open({item:id});
    if(name==='weld-record')return window.FabTracking.open({spool:id});
    if(name==='spool-parts')return window.FabParts.open({spool:id,project:state.project});
    if(name==='filter-step'){const leavingDetail=Boolean(state.item);state.step=id;state.item='';state.detail=null;if(leavingDetail)return load();render();updateUrl();return;}
    if(name==='clear-step'){state.step='';render();return;}
    if(name==='start')return startFlow();
    if(name==='fail')return failStep();
    if(name==='scope')return editScope();
    if(name==='restart-testing')return restartTesting();
    if(name==='assign-component'||name==='link-spool')return linkItem(name);
    if(name==='deliver')return deliver();
    if(name==='pause'||name==='resume')return pauseProcess(name);
  }
  node('flowContent').addEventListener('click',async event=>{
    const spool=event.target.closest('[data-flow-spool]');
    const button=spool?.dataset.flowSpool!==undefined?spool:event.target.closest('[data-flow-action]');if(!button||button.disabled||state.saving)return;
    try{await act(button.dataset.flowSpool!==undefined?'item':button.dataset.flowAction,button.dataset.flowSpool??button.dataset.flowId)}catch(error){notify(errorText(error))}
  });
  node('flowDialogForm').addEventListener('submit',async event=>{
    event.preventDefault();if(!state.dialogAction||state.saving||state.dialogStale||node('flowDialogSubmit').disabled)return;
    const values=Object.fromEntries(new FormData(event.target));node('flowDialogSubmit').disabled=true;node('flowDialogError').classList.add('hidden');
    try{if(await state.dialogAction(values)!==false)node('flowDialog').close()}
    catch(error){node('flowDialogError').textContent=errorText(error)+(state.dialogStale?' Close this dialog and choose the action again using the refreshed record.':'');node('flowDialogError').classList.remove('hidden');node('flowDialogError').scrollIntoView({block:'nearest'})}
    finally{node('flowDialogSubmit').disabled=state.dialogStale}
  });
  node('flowDialogClose').onclick=()=>node('flowDialog').close();
  node('flowDialogCancel').onclick=()=>node('flowDialog').close();
  node('navFlow').onclick=()=>open({resetFilters:true});
  node('itemFlowBtn').onclick=()=>{if(current)open({item:current.id})};
  window.FabFlow={open,refresh,navigationState(){return {project:state.project,subproject:state.subproject,query:state.query,status:state.status,step:state.step}},cancelPending(){state.sequence++;cancelRead();stopClocks();state.handoffControl?.destroy();state.handoffControl=null}};
})();



