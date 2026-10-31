'use strict';
// Synthetic input-resolution checks; no service or account is contacted.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const calls=[];
const codes=new Map([
  ['643-777-PCW-03-01-[001]','SPL-ORIGINAL-1'],
  ['643-777-PCW-03-01-[018]','SPL-ORIGINAL-18'],
  ['Skid α / A&B:main-[1000]','SPL-UNICODE']
]);
const context={URL,location:{origin:'https://shop.example'},qrStatus:{public_base_url:'https://fabtrace-cloud.onrender.com'},api:async url=>{
  calls.push(url);
  const parsed=new URL(url,'https://shop.example');assert.equal(parsed.pathname,'/api/spool-qr/resolve');
  const code=parsed.searchParams.get('code');
  if(!codes.has(code))throw Object.assign(Error('Spool QR label not found'),{status:404});
  return {item_id:codes.get(code),qr_alias:code,display_code:code};
}};
context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/spool-qr.js'),'utf8'),context);
(async()=>{
  for(const value of ['SPL-ORIGINAL-1',' FABTRACE:ITEM:SPL-ORIGINAL-1 ','https://shop.example/?item=SPL-ORIGINAL-1','https://fabtrace-cloud.onrender.com/?item=SPL-ORIGINAL-1'])assert.equal(await context.resolveItemQr(value),'SPL-ORIGINAL-1');
  assert.equal(calls.length,0,'legacy IDs require no alias lookup');
  for(const [code,id] of codes){
    assert.equal(await context.resolveItemQr(code),id);
    assert.equal(await context.resolveItemQr('https://shop.example/?'+new URLSearchParams({spool:code})),id);
  }
  assert.equal(await context.resolveItemQr('https://fabtrace-cloud.onrender.com/?spool=643-777-PCW-03-01-%5B018%5D'),'SPL-ORIGINAL-18');
  const before=calls.length;
  for(const bad of ['', '643-777-PCW-03-01-[1]', '643-777-PCW-03-01-[]', 'FABTRACE:EMP:SHOP1',
    'https://foreign.example/?spool=643-777-PCW-03-01-[001]',
    'https://shop.example@foreign.example/?item=SPL-ORIGINAL-1',
    'https://user:secret@shop.example/?item=SPL-ORIGINAL-1',
    'ftp://shop.example/?item=SPL-ORIGINAL-1', 'javascript:alert(1)',
    'https://shop.example/?item=SPL-ORIGINAL-1&item=SPL-ORIGINAL-18',
    'https://shop.example/?spool=643-777-PCW-03-01-[001]&spool=643-777-PCW-03-01-[018]',
    'https://shop.example/?item=SPL-ORIGINAL-1&spool=643-777-PCW-03-01-[001]',
    'https://shop.example/?item=SPL-ORIGINAL-1&badge=SHOP1',
    'https://shop.example/?spool=', 'https://shop.example/?item=wrong%2Fid',
    'https://shop.example/?item=643-777-PCW-03-01-[001]', 'A'.repeat(2100), 'A\nB-[001]']){
    await assert.rejects(context.resolveItemQr(bad),undefined,bad);
  }
  assert.equal(calls.length,before,'invalid or foreign scans never reach an action or a lookup');
  await assert.rejects(context.resolveItemQr('643-777-PCW-03-01-[999]'),error=>error.status===404);
  assert.equal(calls.at(-1),'/api/spool-qr/resolve?code=643-777-PCW-03-01-%5B999%5D','a missing suffix is never guessed');
  context.api=async()=>({item_id:'bad/identity'});
  await assert.rejects(context.resolveItemQr('643-777-PCW-03-01-[001]'),/could not be resolved/);
  console.log('Spool QR resolver: legacy compatibility, permanent aliases, Unicode, trusted origins, ambiguous scans and missing labels passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
