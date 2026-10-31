/* Resolve printed spool labels to existing physical identities. Resolution is
 * read-only; each screen remains responsible for its own explicit action. */
(function(){
  'use strict';
  const legacyId=value=>/^[A-Za-z0-9_-]{3,60}$/.test(value);
  const invalid=()=>Error('Scan a FabTrace spool label or enter the complete spool number and numbered suffix.');
  function trusted(url){
    if(url.username||url.password||!['http:','https:'].includes(url.protocol))return false;
    if(url.origin===location.origin)return true;
    try{return url.protocol==='https:'&&typeof qrStatus!=='undefined'&&qrStatus.public_base_url&&url.origin===new URL(qrStatus.public_base_url).origin}catch(_){return false}
  }
  async function resolveItemQr(value){
    let code=String(value??'').trim(),kind='auto';
    if(!code||code.length>2000||/[\x00-\x1f\x7f]/.test(code))throw invalid();
    if(code.startsWith('FABTRACE:EMP:'))throw Error('Scan the spool label, not an employee badge.');
    if(code.startsWith('FABTRACE:ITEM:')){
      code=code.slice(14);kind='item';
    }else if(/^https?:/i.test(code)||/^[a-z][a-z0-9+.-]*:\/\//i.test(code)){
      let url;try{url=new URL(code)}catch(_){throw invalid()}
      if(!trusted(url))throw Error('This QR link does not belong to this FabTrace website.');
      const itemValues=url.searchParams.getAll('item'),spoolValues=url.searchParams.getAll('spool');
      if(url.searchParams.has('badge')||itemValues.length+spoolValues.length!==1)throw invalid();
      kind=spoolValues.length?'spool':'item';code=(spoolValues[0]??itemValues[0]??'').trim();
    }
    if(kind==='item'||kind==='auto'&&legacyId(code)){
      if(!legacyId(code))throw invalid();return code;
    }
    if(code.length>540||!/^.+-\[[0-9]{3,}\]$/u.test(code)||/[\x00-\x1f\x7f]/.test(code))throw invalid();
    const resolved=await api('/api/spool-qr/resolve?code='+encodeURIComponent(code));
    if(!legacyId(resolved?.item_id||''))throw Error('This spool label could not be resolved. Refresh and try again.');
    return resolved.item_id;
  }
  window.resolveItemQr=resolveItemQr;
})();
