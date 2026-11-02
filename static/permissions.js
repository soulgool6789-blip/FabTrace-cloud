/* Display the server's job permissions. Missing permissions never grant an action. */
(() => {
  'use strict';
  let roles=[],legacyRoles=[];
  const arr=value=>Array.isArray(value)?value:[];
  const current=()=>typeof me==='undefined'?null:me;
  function setRoles(value){
    roles=arr(value).filter(row=>row&&row.selectable!==false&&typeof row.id==='string'&&typeof row.label==='string').map(row=>({...row}));
  }
  function setLegacyRoles(value){
    legacyRoles=arr(value).filter(row=>row&&row.selectable===false&&typeof row.id==='string'&&typeof row.label==='string').map(row=>({...row}));
  }
  function role(id){return roles.find(row=>row.id===id)||legacyRoles.find(row=>row.id===id)||null;}
  function ownerRoles(currentRole){
    const retained=legacyRoles.find(row=>row.id===currentRole);
    return [...roles,...(retained&&!roles.some(row=>row.id===retained.id)?[retained]:[])].map(row=>({...row}));
  }
  function label(id){return role(id)?.label||(current()?.role===id&&current()?.role_label)||String(id||'Unassigned');}
  function description(id){return role(id)?.description||'Ask an administrator to review the permissions for this position.';}
  function can(capability){return arr(current()?.permissions?.capabilities).includes(capability);}
  async function load(){
    const result=await api('/api/permissions');
    if(!Array.isArray(result?.roles))throw Error('Job permissions could not be verified. Refresh and sign in again.');
    setRoles(result.roles);
    setLegacyRoles(result.legacy_roles);
    return result;
  }
  window.FabPermissions={load,setRoles,setLegacyRoles,roles:()=>roles.slice(),ownerRoles,role,label,description,can};
})();
