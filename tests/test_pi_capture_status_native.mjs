/** Actual SDK/source-bound metadata reads; no provider, palace, miner or service. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [source, pkg, python, parent] = process.argv.slice(2);
for (const value of [source, pkg, python, parent]) assert.ok(path.isAbsolute(value));
const base = fs.mkdtempSync(path.join(fs.realpathSync(parent), 'pi-capture-status-'));
const home = path.join(base, 'Capture fixture Ω home'), agentDir = path.join(home, 'agent');
const originalEnv = { ...process.env }, originalFetch = globalThis.fetch;
for (const key of Object.keys(process.env)) if (!['HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR'].includes(key)) delete process.env[key];
Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' });
const setup = spawnSync(python, ['-B', '-c', 'import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from harness.home import scaffold,environment;h=Path(sys.argv[2]);scaffold(h,source=Path(sys.argv[1]),profile="core",offline=True,name="QualificationOwner",base_url="http://127.0.0.1:1/v1",model="no-inference-fixture");print(json.dumps(environment(h)))', source, home],
  { encoding: 'utf8', timeout: 30000 });
assert.equal(setup.status, 0, setup.stderr + setup.stdout);
Object.assign(process.env, JSON.parse(setup.stdout), { PI_MEMORY_CAPTURE_PYTHON: python });
// Explicit provided interpreter for a component fixture, not an installed env claim.
fs.mkdirSync(path.join(home, 'packages'), { recursive: true });
fs.symlinkSync(path.resolve(pkg, '../../..'), path.join(home, 'packages/pi'), 'dir');
const sdk = await import(pathToFileURL(path.join(pkg, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg, 'package.json'))).version, '1.4.0');
let fetchAttempts = 0;
globalThis.fetch = async () => { fetchAttempts++; throw Error('NO MODEL OR NETWORK'); };
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const model = { id: 'no-inference-fixture', name: 'No inference fixture', provider: 'fixture', api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/v1',
  reasoning: false, input: ['text'], contextWindow: 32768, maxTokens: 4096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const checks = [], errors = [], instances = [];
const closed = new Set();
const check = (name, value) => { checks.push({ name, passed: Boolean(value) }); assert.ok(value, name); };
const hash = value => createHash('sha256').update(value).digest('hex');
const helper = path.join(home, 'runtime/adapters/pi/memory-capture/capture.py'), originalHelper = fs.readFileSync(helper);
const wrapper = path.join(home, 'runtime/harness/memory_runtime.py'), originalWrapper = fs.readFileSync(wrapper);
const configHash = hash(fs.readFileSync(path.join(home, 'home.json')));
let sequence = 0, failure, report, reopenedReport, sessionFile, rawHash;
let capturedRaw, reopenedRaw;
let formatter;
async function load(manager) {
  const settings = sdk.SettingsManager.inMemory({ extensions: [path.join(home, 'runtime/adapters/pi/memory-capture.ts')],
    defaultTools: [], cacheWarming: 'off', retry: { enabled: false } });
  const loader = new sdk.DefaultResourceLoader({ cwd: base, agentDir, settingsManager: settings, noSkills: true,
    noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
  await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
  const { session } = await sdk.createAgentSession({ cwd: base, agentDir, modelRuntime, model, resourceLoader: loader, settingsManager: settings, sessionManager: manager });
  await session.bindExtensions({ onError: error => errors.push(String(error)) });
  instances.push(session);
  return session;
}
async function tool(session, signal = new AbortController().signal) {
  const runner = session.extensionRunner, id = 'capture-read-' + ++sequence;
  const gate = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: 'pi_memory_capture_status', input: {} });
  assert.ok(!gate?.block);
  const item = runner.getAllRegisteredTools().find(row => row.definition.name === 'pi_memory_capture_status');
  const raw = await sdk.wrapRegisteredTool(item, runner).execute(id, {}, signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: 'pi_memory_capture_status', input: {}, ...raw, isError: raw.isError === true });
  return { ...raw, ...changed };
}
try {
  const sessions = path.join(home, 'agent/sessions');
  const manager = sdk.SessionManager.create(base, sessions);
  manager.appendMessage({ role: 'user', content: [{ type: 'text', text: 'Synthetic owned capture-status fixture. No action or approval.' }], timestamp: Date.now() });
  sessionFile = manager.getSessionFile(); assert.ok(sessionFile);
  const session = await load(manager);
  const empty = await tool(session);
  check('normal-registered-status-works-before-palace-or-capture', !empty.isError && JSON.parse(empty.content[0].text).status === 'not_observed');
  const captureCli = path.join(path.dirname(python), 'mempalace');
  assert.ok(fs.existsSync(captureCli), 'Supply the accepted MemPalace environment for its real pure formatter');
  const provenance = spawnSync(python, ['-I', '-B', '-c', 'import hashlib,json;from pathlib import Path;from importlib.metadata import version;import mempalace.normalize as n;print(json.dumps({"version":version("mempalace"),"normalize_sha256":hashlib.sha256(Path(n.__file__).read_bytes()).hexdigest()}))'],
    { encoding: 'utf8', timeout: 10000 });
  assert.equal(provenance.status, 0, provenance.stderr); formatter = JSON.parse(provenance.stdout); assert.equal(formatter.version, '3.11.0');
  capturedRaw = fs.readFileSync(sessionFile); rawHash = hash(capturedRaw);
  const exported = spawnSync(python, ['-I', '-B', helper, '--sessions-root', sessions, '--state-root', path.join(home, 'memory/pi-capture'),
    '--palace', path.join(home, 'memory/palace'), '--mempalace-cli', captureCli, '--session-file', sessionFile, '--export-only'],
  { encoding: 'utf8', timeout: 30000 });
  check('real-pi-jsonl-pure-native-formatter-captures-without-miner', exported.status === 0 && JSON.parse(exported.stdout).mining === 'not_requested');
  const catalog = path.join(home, 'memory/pi-capture/sources.json'), catalogHash = hash(fs.readFileSync(catalog));
  const customBefore = JSON.stringify(manager.getBranch().filter(entry => entry.type === 'custom'));
  const result = await tool(session); report = JSON.parse(result.content[0].text);
  check('actual-bound-python-wrapper-returns-persisted-prefix-and-export', !result.isError && report.sources[0].raw_prefix_sha256 === rawHash
    && report.sources[0].export_sha256.length === 64 && report.current_raw_bytes_verified === false);
  check('actual-model-content-serialization-within12k', Buffer.byteLength(JSON.stringify(result.content), 'utf8') <= 12288);
  await session.abort(); session.dispose(); closed.add(session);
  const reopened = sdk.SessionManager.open(sessionFile, sessions);
  const reloaded = await load(reopened);
  reopenedRaw = fs.readFileSync(sessionFile);
  const after = await tool(reloaded); reopenedReport = JSON.parse(after.content[0].text);
  check('actual-native-session-open-does-not-reset-durable-capture-status', !after.isError && reopenedReport.catalog_sha256 === catalogHash
    && reopenedReport.sources[0].raw_prefix_sha256 === rawHash && reopenedReport.sources[0].receipt_age_seconds >= report.sources[0].receipt_age_seconds);
  check('status-reads-conserve-native-raw-catalog-and-custom-authority', fs.readFileSync(sessionFile).equals(reopenedRaw)
    && reopenedRaw.subarray(0, capturedRaw.length).equals(capturedRaw)
    && hash(fs.readFileSync(catalog)) === catalogHash && JSON.stringify(reopened.getBranch().filter(entry => entry.type === 'custom')) === customBefore);
  const cancelled = new AbortController(); cancelled.abort();
  check('cancelled-read-refused', (await tool(reloaded, cancelled.signal)).isError === true);
  fs.appendFileSync(helper, '\n# Controlled source drift\n');
  check('changed-helper-refused', (await tool(reloaded)).isError === true); fs.writeFileSync(helper, originalHelper);
  fs.appendFileSync(wrapper, '\n# Controlled wrapper drift\n');
  check('changed-wrapper-refused', (await tool(reloaded)).isError === true); fs.writeFileSync(wrapper, originalWrapper);
  const selected = process.env.AGENT_HOME; process.env.AGENT_HOME = base;
  check('foreign-home-environment-refused', (await tool(reloaded)).isError === true); process.env.AGENT_HOME = selected;
  check('no-palace-cache-or-hub-started', !fs.existsSync(path.join(home, 'memory/palace'))
    && !fs.existsSync(path.join(home, 'state/mempalace-hub/owner.json')) && !fs.existsSync(path.join(home, 'cache/chroma')));
  check('home-config-and-native-raw-stay-conserved', hash(fs.readFileSync(path.join(home, 'home.json'))) === configHash && fs.readFileSync(sessionFile).equals(reopenedRaw));
  check('zero-provider-fetch-and-native-extension-errors', fetchAttempts === 0 && errors.length === 0);
} catch (error) { failure = String(error?.stack ?? error); }
finally {
  fs.writeFileSync(helper, originalHelper); fs.writeFileSync(wrapper, originalWrapper);
  for (const session of instances) if (!closed.has(session)) { await session.abort(); session.dispose(); }
  for (const key of Object.keys(process.env)) if (!(key in originalEnv)) delete process.env[key];
  Object.assign(process.env, originalEnv); globalThis.fetch = originalFetch;
  const receipt = { schema: 'pi-capture-status-native/v1', status: failure ? 'failed' : 'passed', failure, checks, base, source, session_file: sessionFile,
    native_raw_sha256: rawHash, report, reopened_report: reopenedReport, fetch_attempts: fetchAttempts, formatter,
    source_sha256: Object.fromEntries(['harness/memory_runtime.py', 'adapters/pi/memory-capture.ts', 'adapters/pi/memory-capture/capture.py',
      'adapters/pi/memory-capture/verify.py', 'tests/test_pi_capture_status_native.mjs'].map(file => [file, hash(fs.readFileSync(path.join(source, file)))])),
    scope: 'Actual Pi1.4 SDK/default loader/tool hooks/session create+open and bound Python/shared consumer in an owned offline core scaffold. Explicit read-only provided Pi dependency and MemPalace Python, no installed-environment claim. Actual pure Pi formatter export-only. No model/provider, miner, embedding, palace, service, private/current home or whole managed CLI deployment. Scripted fixture data; historical metadata is not cryptographic raw freshness or semantic authority.' };
  fs.writeFileSync(path.join(base, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ status: receipt.status, checks: checks.length, base, failure })); process.exitCode = failure ? 1 : 0;
}
