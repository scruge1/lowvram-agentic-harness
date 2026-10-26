/** Native read-only SDK fixture; no owned model, service or inference acceptance. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { syncBuiltinESMExports } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [source, pkg, python, parent] = process.argv.slice(2);
for (const value of [source, pkg, python, parent]) assert.ok(path.isAbsolute(value));
const base = fs.mkdtempSync(path.join(fs.realpathSync(parent), 'pi-resource-status-'));
const home = path.join(base, 'Resource fixture Ω home'), agentDir = path.join(home, 'agent');
const originalEnv = { ...process.env }, originalFetch = globalThis.fetch;
for (const key of Object.keys(process.env)) if (!['HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR'].includes(key)) delete process.env[key];
Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' });
const setup = spawnSync(python, ['-B', '-c', 'import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from harness.home import scaffold,environment;h=Path(sys.argv[2]);scaffold(h,source=Path(sys.argv[1]),profile="core",offline=True,name="QualificationOwner",base_url="http://127.0.0.1:1/v1",model="unowned-fixture");print(json.dumps(environment(h)))', source, home],
  { encoding: 'utf8', timeout: 30000 });
assert.equal(setup.status, 0, setup.stderr + setup.stdout);
Object.assign(process.env, JSON.parse(setup.stdout));
fs.mkdirSync(path.join(home, 'packages'), { recursive: true });
fs.symlinkSync(path.resolve(pkg, '../../..'), path.join(home, 'packages/pi'), 'dir');
const sdk = await import(pathToFileURL(path.join(pkg, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg, 'package.json'))).version, '1.4.0');
let fetchAttempts = 0;
globalThis.fetch = async () => { fetchAttempts++; throw Error('NO MODEL OR NETWORK'); };
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const model = { id: 'unowned-fixture', name: 'No inference fixture', provider: 'fixture', api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/v1',
  reasoning: false, input: ['text'], contextWindow: 32768, maxTokens: 4096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const settings = sdk.SettingsManager.inMemory({ extensions: ['agent-capabilities.ts', 'pi-kanban.ts'].map(name => path.join(home, 'runtime/adapters/pi/project-workflow', name)),
  defaultTools: [], cacheWarming: 'off', retry: { enabled: false } });
const loader = new sdk.DefaultResourceLoader({ cwd: base, agentDir, settingsManager: settings, noSkills: true,
  noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const manager = sdk.SessionManager.inMemory(base), errors = [];
const { session } = await sdk.createAgentSession({ cwd: base, agentDir, modelRuntime, model, resourceLoader: loader, settingsManager: settings, sessionManager: manager });
await session.bindExtensions({ onError: error => errors.push(String(error)) });
const checks = [], check = (name, value) => { checks.push({ name, passed: Boolean(value) }); assert.ok(value, name); };
const helper = path.join(home, 'runtime/harness/resource_status.py'), originalHelper = fs.readFileSync(helper);
const hash = value => createHash('sha256').update(value).digest('hex');
const configBefore = hash(fs.readFileSync(path.join(home, 'home.json')));
const customBefore = JSON.stringify(manager.getBranch().filter(entry => entry.type === 'custom'));
let sequence = 0, failure, report, commandReport;
async function tool(signal = new AbortController().signal) {
  const runner = session.extensionRunner, id = 'resource-read-' + ++sequence;
  const gate = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: 'resource_status', input: {} });
  assert.ok(!gate?.block);
  const item = runner.getAllRegisteredTools().find(row => row.definition.name === 'resource_status');
  const raw = await sdk.wrapRegisteredTool(item, runner).execute(id, {}, signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: 'resource_status', input: {}, ...raw, isError: raw.isError === true });
  return { ...raw, ...changed };
}
try {
  const result = await tool(); check('actual-native-tool-spawns-bound-isolated-python', !result.isError);
  report = JSON.parse(result.content[0].text);
  check('attached-config-stays-unowned-unknown-without-model-status-probe', report.service.mode === 'attached_or_unmanaged' && report.service.status === 'unknown');
  check('queue-fit-capacity-and-new-gpu-admission-remain-honest', report.queue.busy === null && report.fit === 'not_probed'
    && report.host_snapshot.capacity_for_this_model === 'not_established' && report.new_owned_gpu_start_admission.startsWith('held_'));
  check('actual-model-visible-report-is-bounded-and-current-home', report.home === home && Buffer.byteLength(result.content[0].text) <= 12288);
  const writes = [], realWrite = fs.writeSync;
  try {
    fs.writeSync = (fd, data, ...rest) => fd === 1 ? (writes.push(String(data)), Buffer.byteLength(String(data))) : realWrite(fd, data, ...rest);
    syncBuiltinESMExports();
    await session.extensionRunner.getCommand('resource-status').handler('', session.extensionRunner.createCommandContext());
    commandReport = JSON.parse(writes.join(''));
    check('actual-native-command-reuses-same-status-facade', commandReport.schema === report.schema && commandReport.home === home);
    writes.length = 0;
    await session.extensionRunner.getCommand('resource-status').handler('--home foreign', session.extensionRunner.createCommandContext());
    check('native-command-refuses-home-override-arguments', JSON.parse(writes.join('')).status === 'unavailable');
  } finally { fs.writeSync = realWrite; syncBuiltinESMExports(); }
  const cancelled = new AbortController(); cancelled.abort();
  check('already-cancelled-read-refused', (await tool(cancelled.signal)).isError === true);
  fs.appendFileSync(helper, '\n# Controlled source drift\n');
  check('helper-source-drift-refused', (await tool()).isError === true);
  fs.writeFileSync(helper, originalHelper);
  const boundHome = process.env.AGENT_HOME; process.env.AGENT_HOME = base;
  check('foreign-home-environment-refused', (await tool()).isError === true);
  process.env.AGENT_HOME = boundHome;
  check('no-intake-approval-progress-wait-or-selection-records-changed', JSON.stringify(manager.getBranch().filter(entry => entry.type === 'custom')) === customBefore);
  check('home-config-conserved', hash(fs.readFileSync(path.join(home, 'home.json'))) === configBefore);
  check('zero-native-provider-fetch-and-no-extension-errors', fetchAttempts === 0 && errors.length === 0);
} catch (error) { failure = String(error?.stack ?? error); }
finally {
  fs.writeFileSync(helper, originalHelper);
  await session.abort(); session.dispose();
  for (const key of Object.keys(process.env)) if (!(key in originalEnv)) delete process.env[key];
  Object.assign(process.env, originalEnv); globalThis.fetch = originalFetch;
  const receipt = { status: failure ? 'failed' : 'passed', failure, source, base, checks, fetch_attempts: fetchAttempts,
    report, command_report: commandReport, source_sha256: Object.fromEntries(['harness/resource_status.py', 'adapters/pi/project-workflow/agent-capabilities.ts', 'tests/test_pi_resource_status_native.mjs'].map(file => [file, hash(fs.readFileSync(path.join(source, file)))])),
    scope: 'Actual Pi1.4 SDK/default loader/tool hooks/command and isolated Python helper in owned offline core scaffold with read-only supplied Pi dependency. Attached/unowned branch, no owned model/status HTTP/service/CLI deployment/natural agent behavior acceptance. No inference or current/private home access.' };
  fs.writeFileSync(path.join(base, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ status: receipt.status, checks: checks.length, base, failure })); process.exitCode = failure ? 1 : 0;
}
