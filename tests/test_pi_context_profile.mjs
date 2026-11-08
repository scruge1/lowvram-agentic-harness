import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { createHash } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';
import { pathToFileURL } from 'node:url';

const source = pathToFileURL(path.resolve('adapters/pi/project-workflow/agent-capabilities.ts'));
const fakeType = { Object: () => ({}) };
const deps = {
  typebox: { Type: fakeType },
  'node:crypto': { createHash },
  'node:fs': fs,
  'node:path': path,
};
const context = vm.createContext({ Buffer, console, process, setTimeout, clearTimeout,
  URL, Date });
const mod = new vm.SourceTextModule(stripTypeScriptTypes(fs.readFileSync(source, 'utf8')), {
  context, identifier: source.href,
  initializeImportMeta(meta) { meta.url = source.href; }
});
await mod.link(name => {
  const values = deps[name];
  assert.ok(values, 'Unexpected native dependency: ' + name);
  return new vm.SyntheticModule(Object.keys(values), function () {
    for (const [key, value] of Object.entries(values)) this.setExport(key, value);
  }, { context });
});
await mod.evaluate();

const privatePrompt = 'SECRET: model prompt must never be returned raw.';
const toolSource = 'secret_tool_description_should_not_be_exposed_as_profile_text';
const all = [
  { name:'read', description: toolSource, parameters:{ type:'object',properties:{path:{type:'string'}} },
    sourceInfo:{} },
  { name:'agent_capabilities', description:'current capability registry',
    parameters:{type:'object',properties:{}}, sourceInfo:{} },
  { name:'other_inactive', description:'inactive tool', parameters:{ type:'object' }, sourceInfo:{} },
];
let active = ['read','agent_capabilities'];
let appends = [];
const tools = {};
const pi = {
  getAllTools: () => all,
  getActiveTools: () => active,
  registerTool(tool) { tools[tool.name] = tool; },
  registerCommand() {},
  appendEntry(type, profile) { appends.push({type,profile}); },
};
const ctx = {
  sessionManager:{getSessionId:()=> 'synthetic-session-id'},
  getSystemPrompt:()=> privatePrompt,
  getContextUsage:()=> ({ tokens: 4096, contextWindow: 65536 }),
  model:{provider:'local-offline-fixture',id:'synthetic-model',apiKey:'UNREAD'},
};
const snap=mod.namespace.collectCapabilities(pi,ctx.sessionManager.getSessionId());
const profile=mod.namespace.collectContextProfile(pi,ctx,snap);
assert.equal(profile.schema,'pi-context-profile/v1');
assert.equal(profile.native_reported_context_tokens,4096);
assert.equal(profile.native_reported_context_window,65536);
assert.equal(profile.system_prompt_utf8_bytes,Buffer.byteLength(privatePrompt));
assert.equal(profile.system_prompt_sha256,createHash('sha256').update(privatePrompt).digest('hex'));
assert.equal(profile.configured_tool_count,3);
assert.equal(profile.active_tool_count,2);
assert.ok(profile.active_parameter_schema_utf8_bytes>0);
assert.ok(profile.active_declaration_metadata_utf8_bytes>=profile.active_parameter_schema_utf8_bytes);
assert.ok(profile.active_parameter_schema_sha256);
assert.equal(profile.effective_provider_payload_captured,false);
assert.equal(profile.authority,'none');
assert.ok(!JSON.stringify(profile).includes('SECRET:'));
assert.ok(!JSON.stringify(profile).includes(toolSource));
assert.ok(!JSON.stringify(profile).includes('UNREAD'));

const absent={...ctx,getSystemPrompt(){throw Error('private prompt inaccessible');},
 getContextUsage(){throw Error('native context unknown');},model:null};
const abstain=mod.namespace.collectContextProfile(pi,absent,snap);
assert.equal(abstain.system_prompt_utf8_bytes,null,'Unknown must not equal zero');
assert.equal(abstain.native_reported_context_tokens,null);
assert.equal(abstain.model_identity_sha256,null);

const changed = {...pi, getAllTools: () => [...all,{name:'new_tool',description:'changed',parameters:{}}]};
const stale=mod.namespace.collectContextProfile(changed,ctx,snap);
assert.equal(stale.active_parameter_schema_utf8_bytes,null,'Registry drift must not attribute stale schemas');
assert.equal(stale.system_prompt_sha256,profile.system_prompt_sha256);

const cyclic = {};cyclic.self=cyclic;
const mutatedTools=all.map(t=>t.name==='read'?{...t,parameters:cyclic}:t);
const cyclicPi={...pi,getAllTools:()=>mutatedTools};
const cycled=mod.namespace.collectContextProfile(cyclicPi,ctx,snap);
assert.equal(cycled.active_parameter_schema_sha256,null);
assert.equal(cycled.active_declaration_metadata_sha256,null);

mod.namespace.default(pi);
const oldEnable=process.env.PI_CONTEXT_PROFILE_ENABLE;
const oldPersist=process.env.PI_CONTEXT_PROFILE_PERSIST;
try {
  delete process.env.PI_CONTEXT_PROFILE_ENABLE;
  delete process.env.PI_CONTEXT_PROFILE_PERSIST;
  const actual=await tools.agent_capabilities.execute('fixture',{},undefined,undefined,ctx);
  assert.equal(actual.details.ok,true);
  const fresh = JSON.parse(actual.content[0].text);
  assert.equal(fresh.schema, snap.schema);
  assert.equal(fresh.session_id, snap.session_id);
  assert.equal(JSON.stringify(fresh.configured_tools), JSON.stringify(snap.configured_tools));
  assert.equal(JSON.stringify(fresh.limits), JSON.stringify(snap.limits));
  assert.equal(actual.details.context_profile,undefined,'Default should not compute expensive telemetry');
  assert.equal(appends.length,0,'Default public profile must not append optional telemetry');
  process.env.PI_CONTEXT_PROFILE_PERSIST='1';
  const persistenceOnly=await tools.agent_capabilities.execute('persist-only',{},undefined,undefined,ctx);
  assert.equal(persistenceOnly.details.context_profile,undefined,'Persistence alone cannot turn telemetry on');
  assert.equal(appends.length,0);

  delete process.env.PI_CONTEXT_PROFILE_PERSIST;
  process.env.PI_CONTEXT_PROFILE_ENABLE='1';
  const observed=await tools.agent_capabilities.execute('observe',{},undefined,undefined,ctx);
  assert.ok(observed.details.context_profile);
  assert.equal(appends.length,0,'Observation alone cannot mutate history');
  assert.ok(!JSON.stringify(observed.details.context_profile).includes(privatePrompt));
  process.env.PI_CONTEXT_PROFILE_PERSIST='1';
  const persisted=await tools.agent_capabilities.execute('fixture2',{},undefined,undefined,ctx);
  assert.equal(persisted.details.ok,true);
  assert.equal(appends.length,1);
  assert.equal(appends[0].type,'pi-context-profile/v1');
  assert.ok(!JSON.stringify(appends[0]).includes(privatePrompt));
} finally {
  if (oldEnable === undefined) delete process.env.PI_CONTEXT_PROFILE_ENABLE;
  else process.env.PI_CONTEXT_PROFILE_ENABLE=oldEnable;
  if (oldPersist === undefined) delete process.env.PI_CONTEXT_PROFILE_PERSIST;
  else process.env.PI_CONTEXT_PROFILE_PERSIST=oldPersist;
}
console.log(JSON.stringify({status:'PASS',checks:22,tool_bytes:profile.active_parameter_schema_utf8_bytes,
  declared_bytes:profile.active_declaration_metadata_utf8_bytes,
  context_tokens:profile.native_reported_context_tokens,capability_stable:true,
  default_history_unchanged:true,opt_in_appends:appends.length,network_calls:0}));
