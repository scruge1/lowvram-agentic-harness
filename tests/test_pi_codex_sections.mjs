import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';

process.env.PI_CODEX_PLAN_WRAPPER = 'isolated-fixture-only';
process.env.PI_CODEX_CAPABILITY_WRAPPER = 'isolated-fixture-only';
const source = readFileSync(new URL('../adapters/pi/project-workflow/codex-plan-consult.ts', import.meta.url), 'utf8');
let spawned = 0;
const bindings = {
  'node:child_process': { spawn() { spawned++; throw Error('No transport allowed'); } },
  'node:crypto': { createHash, randomUUID }
};
const context = vm.createContext({ process, Buffer, console, setTimeout, clearTimeout });
const mod = new vm.SourceTextModule(stripTypeScriptTypes(source), { context });
await mod.link(name => {
  const values = bindings[name];
  assert.ok(values, 'Unexpected dependency: ' + name);
  return new vm.SyntheticModule(Object.keys(values), function () {
    for (const [key, value] of Object.entries(values)) this.setExport(key, value);
  }, { context });
});
await mod.evaluate();
const hooks = new Map(), tools = [];
mod.namespace.default({
  on(event, listener) {
    if (!hooks.has(event)) hooks.set(event, []);
    hooks.get(event).push(listener);
  },
  registerTool(tool) { tools.push(tool.name); }
});
assert.ok(tools.includes('codex_plan_consult'), 'Original tool registration must remain');
const before = hooks.get('before_agent_start');
assert.equal(before?.length, 1);
const event = { systemPrompt: 'Current prompt', systemPromptOptions: { sections: {} } };
assert.equal(await before[0](event), undefined);
const selected = event.systemPromptOptions.sections.pi_codex_plan_consult;
assert.match(selected, /Codex planning consultation is optional/);
assert.match(selected, /cannot veto authorized local work/);
assert.equal(event.systemPrompt, 'Current prompt');
assert.equal(await before[0](event), undefined);
assert.equal(event.systemPromptOptions.sections.pi_codex_plan_consult, selected);
const fallback = await before[0]({ systemPrompt: 'Current prompt' });
assert.equal(fallback.systemPrompt, 'Current prompt\n' + selected);
const repeated = await before[0]({ systemPrompt: fallback.systemPrompt });
assert.equal(repeated, undefined, 'Legacy fallback must not reappend repeated policy');
assert.equal(spawned, 0);
console.log(JSON.stringify({ passed: true, named_section: 'pi_codex_plan_consult', stable: true,
  forced_replacement: false, legacy_idempotent: true, transport_calls: spawned }));
