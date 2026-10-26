/** Native history-only crash-window control; no child, model or service run. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const [source, pkg, python, home, history, output] = process.argv.slice(2);
for (const value of [source, pkg, python, home, history, output]) assert.ok(path.isAbsolute(value));
const sha = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const protectedFiles = [history, path.join(home, 'home.json'), path.join(home, 'agent/models.json'), path.join(home, 'agent/settings.json')];
const before = Object.fromEntries(protectedFiles.map(file => [file, sha(file)]));
const setup = spawnSync(python, ['-B', '-c', 'import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from harness.home import environment;print(json.dumps(environment(Path(sys.argv[2]))))', source, home], { encoding: 'utf8', timeout: 30000 });
assert.equal(setup.status, 0, setup.stderr + setup.stdout);
Object.assign(process.env, JSON.parse(setup.stdout), { PI_PROJECT_KANBAN_PYTHON: python, PI_PROJECT_CONTEXT_PI_PACKAGE: pkg,
  PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', CUDA_VISIBLE_DEVICES: '' });
const sdk = await import(pathToFileURL(path.join(pkg, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg, 'package.json'))).version, '1.4.0');
const opened = sdk.SessionManager.open(history), entries = opened.getEntries(), cwd = opened.getHeader().cwd;
const start = entries.findLast(row => row.customType === 'pi-managed-child-start/v1').data;
assert.equal(entries.findLast(row => row.customType === 'pi-request-work-state/v1').data.mode, 'running');
assert.ok(!entries.some(row => row.customType === 'pi-managed-child-result/v1' && row.data.id === start.id));
let network = 0;
globalThis.fetch = async () => { network++; throw Error('NO NETWORK'); };
const modelRuntime = await sdk.ModelRuntime.create({ modelsPath: path.join(home, 'agent/models.json'),
  authPath: path.join(home, 'agent/auth.json'), allowModelNetwork: false, refreshOnCreate: false });
const model = modelRuntime.getModel('local', 'managed-child-fixture'), rows = [], checks = [];
const check = (name, passed) => { checks.push({ name, passed: Boolean(passed) }); };
for (const state of ['failed', 'deadline', 'cancelled', 'delivery_held', 'unknown', undefined, 'returned']) {
  const label = state ?? 'missing_state';
  const manager = sdk.SessionManager.inMemory(cwd, undefined, [opened.getHeader(), ...entries]);
  // Deliberate synthetic crash window: final custom entry exists, native parent
  // task_agent tool_result and its failure hook never happened. Original untouched.
  manager.appendCustomEntry('pi-managed-child-result/v1', { ...start, state, child_session: 'history-only', messages: [], calls: [], toolResults: [] });
  const settings = sdk.SettingsManager.inMemory({ extensions: [path.join(source, 'adapters/pi/project-workflow/pi-kanban.ts')],
    defaultTools: [], cacheWarming: 'off', retry: { enabled: false }, compaction: { enabled: false } });
  const loader = new sdk.DefaultResourceLoader({ cwd, agentDir: path.join(home, 'agent'), settingsManager: settings,
    noSkills: true, noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
  await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
  const { session } = await sdk.createAgentSession({ cwd, agentDir: path.join(home, 'agent'), modelRuntime, model,
    resourceLoader: loader, settingsManager: settings, sessionManager: manager });
  await session.bindExtensions({ onError: error => { throw Error(String(error)); } });
  let sequence = 0;
  const tool = async (name, args) => {
    const item = session.extensionRunner.getAllRegisteredTools().find(row => row.definition.name === name);
    return sdk.wrapRegisteredTool(item, session.extensionRunner).execute('history-' + ++sequence, args, new AbortController().signal);
  };
  try {
    const current = () => manager.getBranch().findLast(row => row.customType === 'pi-request-work-state/v1').data;
    const initial = structuredClone(current()), held = initial.mode === 'blocked' && /Unsettled in-memory child/.test(initial.reason);
    check(label + '-restore', state === 'returned' ? !held : held);
    const inspected = await tool('task_agent_inspect', { call_id: start.id });
    check(label + '-inspectable', !inspected.isError && JSON.parse(inspected.content[0].text).record.custom_type === 'pi-managed-child-result/v1');
    if (state !== 'returned') {
      // Raw bash is also an effect entrypoint in the actual intake hook. Test
      // only its event, avoiding unrelated discovery/context refusals that run
      // before intake on workflow_step. Never execute a bash handler.
      const gate = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'must-not-run', toolName: 'bash', input: { command: 'must-not-run' } });
      check(label + '-effect-held-by-child-uncertainty', gate?.block === true && /unsettled/i.test(gate.reason));
    }
    if (state === 'failed') {
      await tool('kanban_work_checkpoint', { disposition: 'continue', reason: 'A model checkpoint cannot clear crash uncertainty', next_action: 'Inspect only' });
      const gate = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'checkpoint-negative', toolName: 'bash', input: { command: 'must-not-run' } });
      check('failed-checkpoint-cannot-clear-uncertainty', gate?.block === true && /unsettled/i.test(gate.reason));
      const boundary = await session.extensionRunner.emitBoundary({ type: 'agent_before_settle', outcome: 'completed' },
        () => ({ contextEntries: [], contextMessages: [], llmMessages: [], pendingMessages: [], canContinue: false }));
      check('failed-no-automatic-continuation', boundary.continue === false && current().mode === 'blocked' && /Unsettled/.test(current().reason));
      await session.extensionRunner.emitInput('The fixture owner inspected the failed child history. Resume the original scope only; do not replay uncertain effects.', undefined, 'interactive');
      const pending = (await tool('kanban_intake_status', {})).details.result.pending.at(-1).id;
      const resumed = await tool('kanban_intake_route', { source_id: pending, parts: [{ kind: 'control', summary: 'Explicit owner resume after inspection' }], control: 'resume' });
      check('failed-fresh-owner-resume', !resumed.isError && current().mode === 'running');
    }
    rows.push({ state: label, initial_mode: initial.mode, initial_reason: initial.reason });
  } finally { await session.abort(); session.dispose(); }
}
check('original-history-and-config-conserved', protectedFiles.every(file => before[file] === sha(file)));
check('zero-network', network === 0);
const receipt = { scope: 'Actual Pi1.4 native reopen of conserved owned007 history in in-memory copies, synthetic final custom records before missing parent tool_result. Actual public coordinator restore/effect/settlement/inspection/resume; no child execution, lifetime or model run.',
  source_sha256: Object.fromEntries(['adapters/pi/intake/request-intake-138.ts', 'adapters/pi/project-workflow/pi-kanban.ts', 'tests/test_pi_managed_child_history_native.mjs'].map(file => [file, sha(path.join(source, file))])),
  history_sha256: before[history], rows, checks, network_requests: network };
fs.writeFileSync(output, JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify({ passed: checks.filter(row => row.passed).length, total: checks.length, output }));
assert.ok(checks.every(row => row.passed), 'Native failed-result crash-window policy');
