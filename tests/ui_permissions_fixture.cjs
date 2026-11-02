/* Synthetic server permission responses for UI contract tests. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const allRoles=require('./permissions_fixture.json');
const roles=allRoles.filter(row=>row.selectable!==false),legacyRoles=allRoles.filter(row=>row.selectable===false);
const empty={capabilities:[],weld_operations:[],process_keys:[],dossier_check_codes:[],dossier_upload_sections:[]};
const policy=role=>allRoles.find(row=>row.id===role)||empty;
function attach(user){
  if(!user)return user;
  if(!Object.prototype.hasOwnProperty.call(user,'permissions'))Object.defineProperty(user,'permissions',{enumerable:true,configurable:true,get(){return policy(this.role)}});
  if(!Object.prototype.hasOwnProperty.call(user,'role_label'))Object.defineProperty(user,'role_label',{enumerable:true,configurable:true,get(){return policy(this.role).label||this.role}});
  return user;
}
function install(context){
  let employee=attach(context.me);
  Object.defineProperty(context,'me',{enumerable:true,configurable:true,get(){return employee},set(value){employee=attach(value)}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/permissions.js'),'utf8'),context);
  context.FabPermissions.setRoles(roles);
  context.FabPermissions.setLegacyRoles(legacyRoles);
}
module.exports={roles,legacyRoles,allRoles,policy,install};
