/* Shared badge, location and operational-status controls. The server owns custody and QA gates. */
(() => {
  'use strict';
  const ROOT='/api/transfers', node=id=>document.getElementById(id), encode=encodeURIComponent;
  const rows=value=>Array.isArray(value)?value:[], storageKey='fabtrace_pending_handoff', pendingAge=20*60*1000;
  const roleTitle={sender:'Sending employee',receiver:'Receiving employee'};
  const statusNames={queued:'Queued',in_progress:'In progress',awaiting_inspection:'Awaiting inspection',waiting_material:'Waiting for material',paused:'Paused',ready_next_operation:'Ready for next operation'};
  const state={active:false,epoch:0,itemSequence:0,item:null,options:null,control:null,saving:false,managing:false,incoming:null};
  let camera=null,cameraRequest=0;
  const text=value=>String(value??'');
  const badgeId=value=>typeof qrId==='function'?qrId(value,'badge'):text(value).trim();
  const itemId=value=>typeof qrId==='function'?qrId(value,'item'):text(value).trim();
  const snapshot=item=>item?.transfer||null;
  const statusLabel=(options,id)=>rows(options?.statuses).find(row=>row.id===id)?.label||'Not recorded';
  const destination=(options,transfer,id)=>id==='current'?transfer?.location||'':rows(options?.locations).find(row=>row.id===id&&row.active)?.label||'';
  function errorText(error){
    try{const detail=JSON.parse(error.message);if(Array.isArray(detail))return detail.map(row=>`${rows(row.loc).filter(x=>x!=='body').join(' / ')}: ${row.msg||'Check this value'}`).join('\n');if(detail.message)return detail.message}catch(_){}
    return error?.message||'The request could not be completed.';
  }
  function option(value,label,selected=''){return `<option value="${esc(value)}"${value===selected?' selected':''}>${esc(label)}</option>`}
  function locationOptions(options,transfer,selected='current'){
    return option('','Choose a destination',selected)+(transfer?.location?option('current','Keep current location · '+transfer.location,selected):'')+rows(options?.locations).filter(row=>row.active).map(row=>option(row.id,row.label,selected)).join('');
  }
  function statusOptions(options,selected=''){return option('','Choose the current work status',selected)+rows(options?.statuses).map(row=>option(row.id,row.label,selected)).join('')}
  function controlHtml(prefix,{transfer,options,heading=true}={}){
    const people=['sender','receiver'].map(role=>{const suffix=role==='sender'?'Sender':'Receiver';return `<section class="fh-person"><h3>${roleTitle[role]}</h3><div class="field"><label for="${prefix+suffix}">${role==='sender'?'Sending':'Receiving'} employee badge QR / ID</label><input id="${prefix+suffix}" name="${role}_badge" autocomplete="off" maxlength="500" placeholder="Scan badge QR or enter badge ID" required></div><div class="actions"><button type="button" id="${prefix+suffix}Camera">Scan ${role} badge</button><button type="button" id="${prefix+suffix}Find">Find employee</button></div><div id="${prefix+suffix}Info" class="fh-badge-result" aria-live="polite">No ${role==='sender'?'sending':'receiving'} badge identified.</div></section>`}).join('');
    return `<div class="fh-people">${people}</div>${heading?'<h3 style="margin:20px 0 8px;font-size:17px">3 · Choose destination and work status</h3>':''}<div class="fh-destination"><div class="field"><label for="${prefix}Location">Destination location / work center</label><select id="${prefix}Location" name="location_id" required>${locationOptions(options,transfer,transfer?.location?'current':'')}</select><span class="fh-help">Select a listed work center or keep the actual recorded location.</span></div><div class="field"><label for="${prefix}Status">Current work status</label><select id="${prefix}Status" name="operational_status" required>${statusOptions(options,transfer?.operational_status||'')}</select></div></div><p class="fh-help">Work status describes this handoff. It does not advance the process, pause its timer, or grant QA release.</p><div id="${prefix}CameraPanel" class="fh-camera"><div class="row"><h3>QR camera scanner</h3><button type="button" id="${prefix}StopCamera">Stop camera</button></div><div id="${prefix}CameraStatus" class="fh-camera-note" role="status">Choose a scan button. A handheld scanner or manual badge entry also works.</div><div id="${prefix}Camera" class="fh-camera-view"></div></div>`;
  }
  function reviewHtml(control,transfer,options,item){
    if(!transfer)return 'Identify the physical item and both employees to review the transfer.';
    const sender=control?.people.sender,receiver=control?.people.receiver,location=destination(options,transfer,node(control?.prefix+'Location')?.value),status=node(control?.prefix+'Status')?.value;
    const person=employee=>employee?`${employee.name} (${employee.badge})`:'Badge identification required';
    const pair=(label,value)=>`<dt>${esc(label)}</dt><dd>${esc(value||'—')}</dd>`;
    const same=sender&&receiver&&sender.badge===receiver.badge;
    return `<h3>${esc(item?.id||transfer.item_id)}</h3>${same?'<p class="fh-same">Same custodian — location/status update</p>':''}<dl>${pair('Sending employee',person(sender))}${pair('Receiving employee',person(receiver))}${pair('From location',transfer.location)}${pair('To location',location||'Choose a destination')}${pair('Work status',statusLabel(options,status))}${pair('Recorded by',me?`${me.name} (${me.badge})`:'Sign in required')}</dl>${same&&location===transfer.location&&status===transfer.operational_status?'<p class="fh-help">Choose a changed location or work status before recording this update.</p>':''}`;
  }
  function validVersion(transfer){return transfer&&Number.isInteger(transfer.version)&&transfer.version>=0}
  function bindControls(prefix,{transfer,options,onChange=()=>{},onRole=()=>{}}={}){
    const control={prefix,transfer,options,alive:true,people:{sender:null,receiver:null},methods:{sender:'manual',receiver:'manual'},sequence:{sender:0,receiver:0}};
    const element=(role,suffix='')=>node(prefix+(role==='sender'?'Sender':'Receiver')+suffix);
    const changed=()=>{if(control.alive)onChange(control)};
    function info(role,message,kind=''){
      const target=element(role,'Info');if(!target||!control.alive)return;
      target.textContent=message;target.dataset.state=kind;
    }
    control.invalidate=role=>{control.sequence[role]++;control.people[role]=null;control.methods[role]='manual';info(role,'Identify the '+(role==='sender'?'sending':'receiving')+' badge.');changed()};
    control.lookup=async(role,value,method='manual')=>{
      if(!control.alive)return null;
      const input=element(role);if(!input)return null;if(value!==undefined)input.value=text(value);
      const original=input.value,id=badgeId(original),sequence=++control.sequence[role];
      control.people[role]=null;control.methods[role]=method;changed();
      if(!id){info(role,'Scan an employee badge QR or enter its valid badge ID.','error');return null}
      info(role,'Looking up badge '+id+'…');
      try{
        const directory=await api('/api/employees/directory');
        if(!control.alive||sequence!==control.sequence[role]||input.value!==original)return null;
        const employee=rows(directory).find(row=>row.badge===id&&row.active!==false);
        if(!employee){info(role,'Badge not found or employee is inactive.','error');changed();return null}
        if(role==='sender'&&transfer&&employee.badge!==transfer.handler){info(role,`This is ${employee.name} (${employee.badge}). The recorded custodian is ${transfer.handler_name||transfer.handler} (${transfer.handler}); scan that employee's badge.`,'error');changed();return null}
        input.value=employee.badge;control.people[role]=employee;
        info(role,`${employee.name} · ${employee.badge}${employee.role?' · '+employee.role:''}`,'valid');changed();return employee;
      }catch(error){if(control.alive&&sequence===control.sequence[role]){info(role,errorText(error),'error');changed()}return null}
    };
    control.validate=()=>{
      if(!control.alive||!validVersion(transfer))throw Error('Refresh the item before recording its handoff.');
      for(const role of ['sender','receiver']){
        const employee=control.people[role];
        if(!employee||badgeId(element(role)?.value)!==employee.badge)throw Error('Identify the '+(role==='sender'?'sending':'receiving')+' employee badge.');
      }
      if(control.people.sender.badge!==transfer.handler)throw Error('The sending employee must match the current recorded custodian. Refresh the item and scan both badges again.');
      const location_id=node(prefix+'Location')?.value||'',operational_status=node(prefix+'Status')?.value||'';
      if(!destination(control.options,transfer,location_id))throw Error('Choose an active destination location or keep the current recorded location.');
      if(!rows(control.options?.statuses).some(row=>row.id===operational_status))throw Error('Choose the current work status.');
      return {sender_badge:control.people.sender.badge,receiver_badge:control.people.receiver.badge,location_id,operational_status,expected_transfer_version:transfer.version};
    };
    control.read=async(values)=>{
      if(values){
        for(const role of ['sender','receiver'])if(Object.prototype.hasOwnProperty.call(values,role+'_badge')&&element(role)?.value!==text(values[role+'_badge'])){element(role).value=text(values[role+'_badge']);control.invalidate(role)}
        if(Object.prototype.hasOwnProperty.call(values,'location_id'))node(prefix+'Location').value=text(values.location_id);
        if(Object.prototype.hasOwnProperty.call(values,'operational_status'))node(prefix+'Status').value=text(values.operational_status);
      }
      await Promise.all(['sender','receiver'].map(role=>control.people[role]&&badgeId(element(role)?.value)===control.people[role].badge?Promise.resolve():control.lookup(role)));
      return control.validate();
    };
    control.scan=role=>{
      onRole(role);return scanCamera({prefix,kind:'badge',label:roleTitle[role].toLowerCase()+' badge',isCurrent:()=>control.alive,onValue:(id,method)=>control.lookup(role,id,method)});
    };
    control.updateOptions=value=>{
      control.options=value;
      const location=node(prefix+'Location'),status=node(prefix+'Status'),priorLocation=location?.value,priorStatus=status?.value;
      if(location){location.innerHTML=locationOptions(value,transfer,destination(value,transfer,priorLocation)?priorLocation:'');location.value=destination(value,transfer,priorLocation)?priorLocation:''}
      if(status){status.innerHTML=statusOptions(value,priorStatus);status.value=rows(value?.statuses).some(row=>row.id===priorStatus)?priorStatus:''}
      changed();
    };
    control.destroy=()=>{control.alive=false;control.sequence.sender++;control.sequence.receiver++;if(camera?.prefix===prefix)stopCamera()};
    for(const role of ['sender','receiver']){
      const input=element(role);if(!input)continue;
      input.oninput=()=>control.invalidate(role);
      input.onchange=()=>control.lookup(role);
      input.onfocus=()=>onRole(role);
      input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();control.lookup(role)}};
      element(role,'Find').onclick=()=>{onRole(role);return control.lookup(role)};
      element(role,'Camera').onclick=()=>control.scan(role);
    }
    for(const suffix of ['Location','Status'])if(node(prefix+suffix))node(prefix+suffix).onchange=changed;
    if(node(prefix+'StopCamera'))node(prefix+'StopCamera').onclick=stopCamera;
    return control;
  }
  async function cleanupCamera(active){
    if(active.cleaned)return;active.cleaned=true;
    try{if(active.started)await active.reader.stop()}catch(_){}
    try{await active.reader.clear()}catch(_){}
  }
  async function stopCamera(){
    const request=++cameraRequest,active=camera;camera=null;if(!active)return request;
    active.cancelled=true;
    const status=node(active.prefix+'CameraStatus'),panel=node(active.prefix+'CameraPanel');
    if(status)status.textContent='Camera stopped. Handheld scanner and manual entry still work.';
    if(panel)panel.dataset.active='false';
    if(active.started)await cleanupCamera(active);return request;
  }
  async function scanCamera({prefix,kind,label,isCurrent=()=>true,onValue}){
    const request=await stopCamera();
    if(request!==cameraRequest||!isCurrent())return;
    const status=node(prefix+'CameraStatus'),panel=node(prefix+'CameraPanel');
    if(!status)return;
    if(!window.Html5Qrcode){status.textContent='Camera scanner unavailable. Use a handheld scanner or enter the QR value manually.';return}
    const active={reader:new Html5Qrcode(prefix+'Camera'),prefix,started:false,cancelled:false,cleaned:false,handling:false};camera=active;
    if(panel)panel.dataset.active='true';status.textContent='Point the camera at the '+label+'.';
    try{
      await active.reader.start({facingMode:'environment'},{fps:10,qrbox:{width:210,height:210}},async decoded=>{
        if(camera!==active||active.cancelled||active.handling||request!==cameraRequest||!isCurrent())return;
        const id=kind==='item'?itemId(decoded):badgeId(decoded);
        if(!id){status.textContent='That QR is not a valid '+(kind==='item'?'item':'employee badge')+' code. Try again.';return}
        active.handling=true;await stopCamera();if(isCurrent())await onValue(id,'employee_qr');
      },()=>{});
      active.started=true;
      if(active.cancelled||camera!==active||request!==cameraRequest||!isCurrent())await cleanupCamera(active);
    }catch(error){
      if(camera===active){camera=null;status.textContent='Camera unavailable: '+errorText(error)+'. Allow camera permission on HTTPS, or use a handheld scanner/manual entry.';if(panel)panel.dataset.active='false'}
      await cleanupCamera(active);
    }
  }
  function pending(){
    try{
      const saved=JSON.parse(localStorage.getItem(storageKey)||'null'),age=Date.now()-saved?.time,id=saved?.item_id||saved?.id;
      if(!saved||!Number.isFinite(age)||age<0||age>=pendingAge||!itemId(id))return null;
      if(saved.recorder&&saved.recorder!==me?.badge)return null;
      return {...saved,item_id:id,role:['sender','receiver'].includes(saved.role)?saved.role:null};
    }catch(_){return null}
  }
  function clearPending(){try{localStorage.removeItem(storageKey)}catch(_){}}
  function remember(role=null){
    const transfer=snapshot(state.item);if(!state.active||!transfer)return;
    if(!['sender','receiver'].includes(role))role=null;
    const control=state.control;
    try{localStorage.setItem(storageKey,JSON.stringify({version:2,item_id:state.item.id,role,recorder:me?.badge,time:Date.now(),expected_transfer_version:transfer.version,sender:control?.people.sender?.badge||'',receiver:control?.people.receiver?.badge||'',location_id:node('handoffLocation')?.value||'',operational_status:node('handoffStatus')?.value||''}))}catch(_){}
  }
  function error(message=''){
    const target=node('handoffError');if(!target)return;target.textContent=message;target.classList.toggle('hidden',!message);
  }
  function renderIncoming(){
    const target=node('handoffIncoming');if(!target)return;
    target.classList.toggle('hidden',!state.incoming);if(!state.incoming){target.innerHTML='';return}
    target.innerHTML=`<p>Badge link received: <code>${esc(state.incoming.badge)}</code>. ${state.item?'Choose which employee this badge identifies.':'Identify the item first, then choose which employee this badge identifies.'}</p><div class="actions"><button type="button" id="handoffIncomingSender"${state.item?'':' disabled'}>Use as sending badge</button><button type="button" id="handoffIncomingReceiver"${state.item?'':' disabled'}>Use as receiving badge</button></div>`;
    for(const role of ['sender','receiver'])node('handoffIncoming'+(role==='sender'?'Sender':'Receiver')).onclick=async()=>{
      if(!state.item||!state.incoming)return;const badge=state.incoming.badge;state.incoming=null;renderIncoming();remember(role);await state.control.lookup(role,badge,'employee_qr');
    };
  }
  function updateReview(){
    if(!state.active)return;
    const transfer=snapshot(state.item),control=state.control;
    node('handoffSummary').innerHTML=reviewHtml(control,transfer,state.options,state.item);
    let valid=false;
    try{
      const value=control?.validate();valid=Boolean(value)&&Boolean(transfer?.can_transfer)&&!state.saving&&!state.managing;
      if(value&&value.sender_badge===value.receiver_badge&&destination(state.options,transfer,value.location_id)===transfer.location&&value.operational_status===transfer.operational_status)valid=false;
    }catch(_){}
    node('handoffConfirm').disabled=!valid;
    node('handoffConfirm').textContent=state.saving?'Recording…':control?.people.sender&&control?.people.receiver&&control.people.sender.badge===control.people.receiver.badge?'Record location/status update':'Record custody transfer';
    const saved=pending();if(saved&&saved.item_id===state.item?.id&&saved.role)remember(saved.role);
  }
  function mountControls(){
    state.control?.destroy();node('handoffControls').innerHTML=controlHtml('handoff',{transfer:snapshot(state.item),options:state.options});
    state.control=bindControls('handoff',{transfer:snapshot(state.item),options:state.options,onChange:updateReview,onRole:remember});
    updateReview();
  }
  function renderItem(){
    const item=state.item,transfer=snapshot(item),target=node('handoffItemInfo'),process=node('handoffProcessNotice');
    if(!item){target.textContent='Scan or enter the physical item to begin.';process.classList.add('hidden');return}
    const pair=(label,value)=>`<dl><dt>${esc(label)}</dt><dd>${esc(value||'—')}</dd></dl>`;
    target.innerHTML=`<strong>${esc(item.id)}</strong> · ${esc(item.description||'')}<div class="fh-current">${pair('Recorded custodian',`${transfer?.handler_name||item.handler||'—'}${transfer?.handler_name?' ('+transfer.handler+')':''}`)}${pair('Recorded location',transfer?.location||item.location)}${pair('Recorded work status',transfer?.status_label||'Not recorded')}${pair('Current process',item.flow_step?'Step '+item.flow_step+' · '+(item.flow_status||'In progress'):item.flow_enabled?item.flow_status||'Route recorded':'No numbered route')}${pair('Quality release',item.released?'Released':'Not released')}</div>${transfer?.handler_active===false?'<p class="fh-inline-error">The recorded custodian is inactive. A supervisor must resolve the employee record before this handoff.</p>':''}`;
    process.classList.toggle('hidden',!item.flow_enabled&&!item.released);
    process.innerHTML=`${item.released?'This item is released. Use its permitted later handoff in Process flow.':'To complete a production handoff and move the process clock, use the current numbered step.'}${item.flow_enabled?' <button type="button" id="handoffOpenFlow">Open current process step</button>':''}`;
    if(node('handoffOpenFlow'))node('handoffOpenFlow').onclick=()=>window.FabFlow.open({item:item.id});
    if(transfer&&!transfer.can_transfer&&!item.released&&transfer.handler_active!==false)error('Your account cannot record an ordinary custody transfer for this item.');
  }
  async function findItem(value){
    if(!state.active)return;
    if(value!==undefined)node('handoffItem').value=text(value);
    const original=node('handoffItem').value,id=itemId(original),sequence=++state.itemSequence,epoch=state.epoch;
    await stopCamera();if(!state.active||sequence!==state.itemSequence||epoch!==state.epoch||node('handoffItem').value!==original)return;
    state.item=null;clearPending();mountControls();renderIncoming();error();node('handoffProcessNotice').classList.add('hidden');
    if(!id){node('handoffItemInfo').textContent='Scan an item QR label or enter a valid item ID.';return}
    node('handoffItemInfo').textContent='Loading item '+id+'…';
    try{
      const item=await api('/api/items/'+encode(id));
      if(!state.active||sequence!==state.itemSequence||epoch!==state.epoch||node('handoffItem').value!==original)return;
      if(!validVersion(snapshot(item)))throw Error('Transfer details are unavailable. Refresh the page before recording this item.');
      state.item=item;node('handoffItem').value=item.id;mountControls();renderItem();renderIncoming();remember();
    }catch(err){if(state.active&&sequence===state.itemSequence&&epoch===state.epoch){node('handoffItemInfo').textContent=errorText(err);updateReview()}}
  }
  function invalidateItem(){
    state.itemSequence++;state.item=null;clearPending();stopCamera();mountControls();renderItem();renderIncoming();error();
  }
  async function open({item='',phone=false}={}){
    if(!me)return;show('handoffPage');state.active=true;const epoch=++state.epoch;state.itemSequence++;state.item=null;state.options=null;state.incoming=null;state.control?.destroy();
    node('handoffItem').value=item;node('handoffNotes').value='';node('handoffItemInfo').textContent='Loading transfer options…';node('handoffProcessNotice').classList.add('hidden');node('handoffLocationSettings').innerHTML='';error();renderIncoming();mountControls();
    history.replaceState(null,'','/?handoff=1'+(item?'&item='+encode(item):''));
    try{
      const options=await api(ROOT+'/options');if(!state.active||epoch!==state.epoch)return;
      state.options=options;mountControls();renderLocations();if(item)await findItem(item);else renderItem();
      if(phone&&state.active&&epoch===state.epoch&&state.item){remember('sender');await state.control.scan('sender')}
    }catch(err){if(state.active&&epoch===state.epoch){error('Transfer options could not be loaded. '+errorText(err));node('handoffItemInfo').textContent='Open Scan & handoff again to retry.'}}
  }
  async function openBadge(value){
    const id=badgeId(value);if(!id){await open();error('That badge link is invalid. Scan an issued FabTrace employee badge.');return}
    const saved=pending();await open({item:saved?.item_id||''});if(!state.active)return;
    if(saved?.role&&state.item){
      if(saved.version===2&&saved.expected_transfer_version===snapshot(state.item)?.version){
        if(saved.location_id&&destination(state.options,snapshot(state.item),saved.location_id))node('handoffLocation').value=saved.location_id;
        if(rows(state.options.statuses).some(row=>row.id===saved.operational_status))node('handoffStatus').value=saved.operational_status;
        for(const role of ['sender','receiver'])if(role!==saved.role&&saved[role])await state.control.lookup(role,saved[role]);
      }else if(saved.version===2)error('The item changed after the earlier scan. Review its current custodian and identify both badges again.');
      remember(saved.role);await state.control.lookup(saved.role,id,'employee_qr');
    }else{state.incoming={badge:id};renderIncoming()}
  }
  async function confirmTransfer(){
    if(state.saving||state.managing||!state.active)return;
    const item=state.item,transfer=snapshot(item),epoch=state.epoch,sequence=state.itemSequence;
    try{
      if(!item||!transfer?.can_transfer)throw Error('Choose an item you are authorized to transfer. Released items use their permitted numbered handoff.');
      const value=state.control.validate();
      if(value.sender_badge===value.receiver_badge&&destination(state.options,transfer,value.location_id)===transfer.location&&value.operational_status===transfer.operational_status)throw Error('Choose a changed location or work status before recording a same-custodian update.');
      const payload={sender_badge:value.sender_badge,handler:value.receiver_badge,location_id:value.location_id,operational_status:value.operational_status,expected_transfer_version:value.expected_transfer_version,expected_handler:transfer.handler,notes:node('handoffNotes').value.trim(),scan_method:Object.values(state.control.methods).includes('employee_qr')?'employee_qr':'manual'};
      state.saving=true;error();updateReview();await stopCamera();
      await api('/api/items/'+encode(item.id)+'/transfer',{method:'POST',body:JSON.stringify(payload)});
      if(!state.active||epoch!==state.epoch||sequence!==state.itemSequence||state.item?.id!==item.id)return;
      clearPending();state.item=null;state.itemSequence++;node('handoffItem').value='';node('handoffNotes').value='';state.incoming=null;mountControls();renderIncoming();node('handoffProcessNotice').classList.add('hidden');node('handoffItemInfo').textContent='Transfer recorded for '+item.id+'. Scan the next item and both badges.';notify('Handoff recorded for '+item.id+'.');
    }catch(err){
      if(!state.active||epoch!==state.epoch||sequence!==state.itemSequence||state.item?.id!==item?.id)return;
      if(err.status===409&&item){
        const reload=findItem(item.id),reloadSequence=state.itemSequence;await reload;
        if(state.active&&epoch===state.epoch&&reloadSequence===state.itemSequence&&state.item?.id===item.id)error(errorText(err)+' The item has been refreshed. Scan both employee badges again before recording another transfer.');
      }
      else error(errorText(err));
    }finally{state.saving=false;if(state.active)updateReview()}
  }
  function renderLocations(){
    const host=node('handoffLocationSettings');if(!host)return;
    if(!state.options?.can_manage_locations){host.innerHTML='';return}
    const custom=rows(state.options.locations).filter(row=>row.kind==='custom');
    host.innerHTML=`<details class="fh-settings"><summary>Manage shop locations</summary><div class="fh-settings-body"><p class="fh-help">Supervisors and administrators can add actual shop locations, rename them, or make them inactive. Existing transfer history retains the location recorded at that time.</p><p class="fh-help">Standard process work centers remain available.</p><div class="fh-locations-list">${custom.length?custom.map(row=>`<div class="fh-location-row"><input id="handoffLocationName-${esc(row.id)}" maxlength="160" value="${esc(row.label)}" aria-label="Location name ${esc(row.label)}"><span class="pill">${row.active?'Active':'Inactive'}</span><button type="button" data-location-action="rename" data-location-id="${esc(row.id)}">Save name</button><button type="button" data-location-action="toggle" data-location-id="${esc(row.id)}">${row.active?'Make inactive':'Activate'}</button></div>`).join(''):'<p class="fh-help">No custom shop locations added.</p>'}</div><div class="field"><label for="handoffNewLocation">New shop location</label><input id="handoffNewLocation" maxlength="160" placeholder="For example: Weld Bay 2"></div><button type="button" id="handoffAddLocation">Add location</button><div id="handoffLocationError" class="fh-inline-error hidden" role="alert"></div></div></details>`;
    node('handoffAddLocation').onclick=()=>manageLocation('create');
    if(typeof host.querySelectorAll==='function')host.querySelectorAll('[data-location-action]').forEach(button=>button.onclick=()=>manageLocation(button.dataset.locationAction,button.dataset.locationId));
  }
  async function manageLocation(action,id){
    if(state.managing||state.saving||!state.options?.can_manage_locations)return;
    const epoch=state.epoch,target=node('handoffLocationError'),old=rows(state.options.locations).find(row=>row.id===id);
    try{
      target.classList.add('hidden');state.managing=true;updateReview();
      if(action==='create'){
        const label=node('handoffNewLocation').value.trim();if(!label)throw Error('Enter the shop location name.');
        await api(ROOT+'/locations',{method:'POST',body:JSON.stringify({label})});
      }else{
        if(!old||old.kind!=='custom')throw Error('Refresh the location list before editing.');
        const label=action==='rename'?node('handoffLocationName-'+id).value.trim():old.label;if(!label)throw Error('Enter the location name.');
        await api(ROOT+'/locations/'+encode(id),{method:'PATCH',body:JSON.stringify({label,active:action==='toggle'?!old.active:old.active,expected_version:old.version})});
      }
      const options=await api(ROOT+'/options');if(!state.active||epoch!==state.epoch)return;
      state.options=options;state.control?.updateOptions(options);renderLocations();notify('Shop locations updated.');
    }catch(err){if(state.active&&epoch===state.epoch){
      if(err.status===409){try{state.options=await api(ROOT+'/options');if(!state.active||epoch!==state.epoch)return;state.control?.updateOptions(state.options);renderLocations()}catch(_){} }
      const currentTarget=node('handoffLocationError');if(currentTarget){currentTarget.textContent=errorText(err)+(err.status===409?' The location list has been refreshed. Review it before trying again.':'');currentTarget.classList.remove('hidden')}
    }}
    finally{state.managing=false;if(state.active)updateReview()}
  }
  function historyHtml(events){
    return rows(events).map(event=>{
      const d=event.details||{},from=d.from||{},to=d.to||{},sender=d.sender_badge||d.sender?.badge;
      const newFields=Boolean(sender),pair=(label,value)=>value?`<br>${esc(label)}: ${esc(value)}`:'';
      const oldStatus=from.operational_status,newStatus=to.operational_status||d.operational_status;
      return `<div class="event"><b>${esc(from.handler||sender||'—')} → ${esc(to.handler||d.receiver_badge||'—')}</b>${to.name?' · '+esc(to.name):''}${newFields&&d.custody_changed===false?'<span class="fh-status">Same custodian · location/status update</span>':''}<p>${esc(from.location||'—')} → ${esc(to.location||'—')}${pair('Work status',newStatus?(statusNames[oldStatus]||oldStatus||'Not previously recorded')+' → '+(statusNames[newStatus]||newStatus):'')}${newFields?pair('Sending badge',sender)+pair('Receiving badge',d.receiver_badge||to.handler):''}<br>Recorded by: ${esc(event.actor)} · ${esc(event.at?new Date(event.at).toLocaleString():'—')}${d.notes?'<br>'+esc(d.notes):''}</p><p class="fh-history-note">${newFields?'Employee badges identified for this record. Independent sender/receiver acceptance signatures are not recorded.':'Historical custody record. Separate sending-badge identification was not recorded.'}</p></div>`;
    }).join('')||'<p class="muted">No custody handoffs recorded yet.</p>';
  }
  function cancelPending(){
    if(!state.active)return;state.active=false;state.epoch++;state.itemSequence++;state.control?.destroy();state.control=null;state.item=null;state.incoming=null;clearPending();stopCamera();
  }
  if(node('navHandoff'))node('navHandoff').onclick=()=>open();
  if(node('handoffBack'))node('handoffBack').onclick=()=>listItems();
  if(node('handoffItemFind'))node('handoffItemFind').onclick=()=>findItem();
  if(node('handoffItem')){
    node('handoffItem').oninput=invalidateItem;node('handoffItem').onchange=()=>findItem();
    node('handoffItem').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();findItem()}};
  }
  if(node('handoffItemCamera'))node('handoffItemCamera').onclick=()=>scanCamera({prefix:'handoff',kind:'item',label:'physical item QR',isCurrent:()=>state.active,onValue:id=>findItem(id)});
  if(node('handoffConfirm'))node('handoffConfirm').onclick=confirmTransfer;
  if(typeof window.addEventListener==='function')window.addEventListener('pagehide',()=>stopCamera());
  window.FabHandoff={open,openBadge,cancelPending,stopCamera,controlHtml,bindControls,locationOptions,statusLabel,reviewHtml,historyHtml,errorText};
})();
