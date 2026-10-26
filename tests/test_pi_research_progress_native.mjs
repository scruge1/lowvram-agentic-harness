/** Native committed research progress and retained-history controls; no network/model. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let index = 2; index < process.argv.length; index += 2) {
  assert.ok(process.argv[index]?.startsWith('--') && process.argv[index + 1]);
  options[process.argv[index].slice(2)] = process.argv[index + 1];
}
for (const name of ['source', 'pi-package', 'research-python', 'hermes-python', 'framework-python', 'fixture-parent'])
  assert.ok(options[name], `Missing --${name}`);
assert.equal(process.platform, 'linux');
const source = fs.realpathSync(options.source), piPackage = fs.realpathSync(options['pi-package']);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-research-progress-'));
const home = path.join(fixture, 'home'), runtime = path.join(home, 'runtime'), agentDir = path.join(home, 'agent');
for (const name of [runtime, agentDir, path.join(home, 'envs'), path.join(home, 'state')]) fs.mkdirSync(name, { recursive: true });
const hashBytes = value => createHash('sha256').update(value).digest('hex');
const hash = file => hashBytes(fs.readFileSync(file));
const write = (file, value) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n'); };
const originalEnvironment = { ...process.env }, originalFetch = globalThis.fetch;
const allowedEnvironment = new Set(['HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TMP', 'TEMP']);
for (const name of Object.keys(process.env)) if (!allowedEnvironment.has(name)) delete process.env[name];
Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' });
let httpAttempts = 0;
globalThis.fetch = async () => { httpAttempts++; throw new Error('This native counterexample forbids HTTP/inference'); };
const manifest = [];
function copy(relative) {
  for (const item of fs.readdirSync(path.join(source, relative), { withFileTypes: true })) {
    if (item.name === '__pycache__') continue;
    assert.ok(!item.isSymbolicLink());
    const name = path.join(relative, item.name);
    if (item.isDirectory()) copy(name);
    else if (/\.(py|ts|mjs|md)$/.test(name) || ['harness/model-service-pins.json', 'harness/claude-memory-patch.json'].includes(name.split(path.sep).join('/'))) {
      const target = path.join(runtime, name); fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(path.join(source, name), target);
      manifest.push({ path: name.split(path.sep).join('/'), sha256: hash(target) });
    }
  }
}
for (const directory of ['harness', 'ssot', 'adapters/pi']) copy(directory);
for (const name of ['pi-task-worker.py', 'pi_native_events.py']) {
  fs.copyFileSync(path.join(runtime, 'adapters/pi/project-workflow', name), path.join(runtime, name));
  manifest.push({ path: name, sha256: hash(path.join(runtime, name)) });
}
const helper = path.join(runtime, 'harness/research_runtime.py'), originalHelper = fs.readFileSync(helper, 'utf8');
const marker = 'if __name__ == "__main__":';
assert.equal(originalHelper.split(marker).length, 2);
const transportFixture = `
# Explicit synthetic transport only. Preserve the real ResearchRuntime, selected
# project/card validation, immutable ArtifactStore, projection and tool result.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socket as _fixture_socket
def _no_network(*args, **kwargs):
    raise AssertionError('Network is forbidden by this source counterexample')
_fixture_socket.socket.connect = _no_network
_fixture_socket.create_connection = _no_network
from harness import research_fetch as _fixture_retrieval
def _fixture_fetch(url, **kwargs):
    assert url.startswith('https://example.org/native-progress/')
    text = 'Controlled public research evidence: ' + url.rsplit('/', 1)[1]
    return {'ok': True, 'status': 'ok', 'text': text, 'content_scope': 'full_extraction',
            'requested_url': url, 'selected_url': url, 'selected_kind': 'requested_static',
            'requested_source_complete': True, 'attempts': [{'status': 'ok', 'fixture': 'synthetic_transport_no_http'}]}
_fixture_retrieval.fetch = _fixture_fetch
_fixture_native_progress = ResearchRuntime.progress_validation
def _fixture_progress(self, request):
    hold = Path(${JSON.stringify(path.join(home, 'state/hold-progress-validation'))})
    if hold.exists():
        Path(${JSON.stringify(path.join(home, 'state/progress-validation-entered'))}).write_text('entered')
        deadline = time.monotonic() + 20
        while hold.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if hold.exists():
            raise TimeoutError('Owned validation fixture barrier deadline')
    return _fixture_native_progress(self, request)
ResearchRuntime.progress_validation = _fixture_progress
`;
fs.writeFileSync(helper, originalHelper.replace(marker, transportFixture + '\n' + marker));
manifest.find(item => item.path === 'harness/research_runtime.py').sha256 = hash(helper);
write(path.join(runtime, 'runtime-manifest.json'), { files: manifest });
write(path.join(home, 'home.json'), { schema: 'agent-home/v1', home, selected_packages: { research: 'explicit-readonly-fixture-alias' },
  runtime_manifest_sha256: hash(path.join(runtime, 'runtime-manifest.json')), validated_registry_sha256: hashBytes(''), bounded_compaction_sha256: hashBytes('{}') });
for (const name of ['research', 'hermes']) {
  const python = path.resolve(options[name + '-python']);
  fs.symlinkSync(path.dirname(path.dirname(python)), path.join(home, 'envs', name), 'dir');
}
const python = path.join(home, 'envs/research/bin/python');
function py(code, args = [], interpreter = python) {
  const result = spawnSync(interpreter, ['-I', '-B', '-c', `import sys;sys.path.insert(0,${JSON.stringify(runtime)});` + code, ...args],
    { cwd: home, env: process.env, encoding: 'utf8', timeout: 45000, maxBuffer: 4 * 1024**2 });
  assert.equal(result.status, 0, result.stderr + result.stdout); return JSON.parse(result.stdout);
}
const guarded = py(`import json;from pathlib import Path;from harness import home_entry
h=Path(sys.argv[1]);b=home_entry.install(h);c=json.loads((h/'home.json').read_text());c['lifecycle_guard_sha256']=b['guard_sha256'];(h/'home.json').write_text(json.dumps(c));print(json.dumps(b))`, [home]);
const frameworkBinding = path.join(home, 'state/framework-binding.json');
const generated = spawnSync(options['framework-python'], ['-B', path.join(runtime, 'adapters/pi/intake/framework_binding.py'), '--output', frameworkBinding],
  { env: process.env, encoding: 'utf8', timeout: 45000 });
assert.equal(generated.status, 0, generated.stderr + generated.stdout);
const framework = JSON.parse(generated.stdout); assert.equal(framework.ok, true);
const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
config.framework_binding_sha256 = framework.sha256; write(path.join(home, 'home.json'), config);
Object.assign(process.env, py(`import json;from pathlib import Path;from harness.home import environment;print(json.dumps(environment(Path(sys.argv[1]))))`, [home]));
process.env.PI_PROJECT_CONTEXT_PI_PACKAGE = piPackage;
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(piPackage, 'package.json'))).version, '1.4.0');
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const historyProbe = path.join(fixture, 'native-history-cache-probe.ts');
fs.writeFileSync(historyProbe, `import assert from 'node:assert/strict';
import { Type } from 'typebox';
import { SessionManager } from ${JSON.stringify(path.join(piPackage, 'dist/index.js'))};
import { researchCreditSeen, rememberResearchCredit } from ${JSON.stringify(path.join(runtime, 'adapters/pi/intake/request-intake-138.ts'))};
export default function(pi){pi.registerTool({name:'research_history_probe',label:'History membership unit',description:'Private membership fixture only, never evidence authority',parameters:Type.Object({}),
async execute(){const manager=SessionManager.inMemory('history-membership-only');const recent=new Set();
const key=i=>i.toString(16).padStart(64,'0');
for(let i=1;i<=300;i++){manager.appendCustomEntry('pi-request-work-state/v1',{research_credit:{key:key(i)}});rememberResearchCredit(recent,key(i));}
assert.equal(recent.size,256);assert.equal(recent.has(key(1)),false);
assert.equal(researchCreditSeen(manager.getBranch(),recent,key(301)),false,'New evidence beyond256 is not a lifetime cap');
assert.equal(researchCreditSeen(manager.getBranch(),recent,key(1)),true,'Evicted old evidence remains seen in native history');
manager.appendCustomEntry('pi-request-work-state/v1',{research_credit:{key:key(301)}});rememberResearchCredit(recent,key(301));
assert.equal(recent.size,256);recent.clear();assert.equal(researchCreditSeen(manager.getBranch(),recent,key(1)),true);
assert.equal(researchCreditSeen(manager.getBranch(),recent,key(301)),true);assert.equal(researchCreditSeen(manager.getBranch(),recent,key(302)),false);
const result={checks:5,native_history_credits:301,recent_cache_bound:256,scope:'Membership primitive with synthetic native snapshots, not301 research operations or task-progress credits'};
return{content:[{type:'text',text:JSON.stringify(result)}],details:{ok:true,result}};}});}
`);
const sessions = [], arms = [], trace = [];
let sequence = 0;
async function tool(profile, name, input, options = {}) {
  const runner = profile.session.extensionRunner, id = 'research-progress-' + (++sequence);
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!blocked?.block, name + ': ' + blocked?.reason);
  profile.manager.appendMessage({ role: 'assistant', api: 'openai-completions', provider: 'fixture-local', model: 'fixture-no-inference',
    content: [{ type: 'toolCall', id, name, arguments: input }], stopReason: 'toolUse', timestamp: Date.now() });
  const registered = runner.getAllRegisteredTools().find(item => item.definition.name === name);
  assert.ok(registered, `Missing native registered tool ${name}`);
  const value = await sdk.wrapRegisteredTool(registered, runner).execute(id, input, new AbortController().signal);
  if (options.transformContent) value.content = options.transformContent(value);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...value, isError: value.isError === true });
  const result = { ...value, ...changed };
  const message = { role: 'toolResult', toolCallId: id, toolName: name, content: result.content, details: result.details,
    isError: result.isError === true, timestamp: Date.now() };
  if (options.changeMessage) options.changeMessage(message);
  profile.manager.appendMessage(message);
  profile.lastCommitted = { message, entryId: profile.manager.getLeafId() };
  trace.push({ arm: profile.label, id, name, input, result });
  assert.ok(!result.isError, JSON.stringify(result));
  if (options.beforeTurnEnd) await options.beforeTurnEnd(result);
  if (options.commit !== false) await turnEnd(profile);
  return result;
}
async function turnEnd(profile) {
  const { message, entryId } = profile.lastCommitted;
  await profile.session.extensionRunner.emit({ type: 'turn_end', turnIndex: 0, message: { role: 'assistant', content: [] },
    toolResults: [message], toolResultEntryIds: [entryId] });
}
const snapshot = profile => structuredClone([...profile.manager.getBranch()].reverse().find(entry => entry.customType === 'pi-request-work-state/v1')?.data);
const state = async profile => (await tool(profile, 'kanban_intake_status', {})).details.result;
async function createProfile(label) {
  const project = path.join(home, 'projects', label); fs.mkdirSync(project, { recursive: true });
  fs.writeFileSync(path.join(project, 'AGENTS.md'), '# Controlled research-progress fixture\n\nRetain unfinished authorized work. Evidence is not root acceptance.\n');
  const settings = sdk.SettingsManager.inMemory({ extensions: [path.join(runtime, 'adapters/pi/project-workflow/pi-kanban.ts'),
    path.join(runtime, 'adapters/pi/research/research-tools.ts'), historyProbe], defaultTools: [], cacheWarming: 'off' });
  const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
    noSkills: true, noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
  await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
  const manager = sdk.SessionManager.create(project, path.join(agentDir, 'sessions', label));
  const { session } = await sdk.createAgentSession({ cwd: project, agentDir, settingsManager: settings, resourceLoader: loader,
    sessionManager: manager, modelRuntime, thinkingLevel: 'off', model: { id: 'fixture-no-inference', name: 'No inference',
      provider: 'fixture-local', api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/v1', reasoning: false, input: ['text'],
      contextWindow: 32768, maxTokens: 4096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } } });
  const errors = []; await session.bindExtensions({ onError: error => errors.push(String(error)) });
  const profile = { label, project, manager, session, errors }; sessions.push(profile);
  await tool(profile, 'project_admit', { project_root: project, initialize: true,
    native_authority: 'Owner explicitly authorized this isolated no-inference research-progress counterexample',
    target: 'Compare distinct durable research evidence with unchanged cached reads while retaining unfinished work',
    why: 'Test normal native tool results and injected settlement, without model/HTTP or execution effects' });
  await session.extensionRunner.emitInput('Research three distinct source facts for this unfinished fixture task. Do not complete the task or infer root acceptance from retrieved evidence.', undefined, 'interactive');
  const pending = (await state(profile)).pending;
  await tool(profile, 'kanban_intake_route', { source_id: pending.at(-1).id,
    parts: [{ kind: 'task', summary: 'Research three distinct source facts; preserve unfinished task and independent outcome verification', execute: true }] });
  const routed = await state(profile); assert.equal(routed.queue.length, 1);
  profile.task = routed.queue[0].task;
  profile.identity = JSON.parse(fs.readFileSync(path.join(project, '.icm/project.json')));
  return profile;
}
function durable(profile, artifact) {
  assert.match(artifact.artifact_id, /^sha256:[a-f0-9]{64}$/);
  const file = path.join(profile.identity.state_root, 'research/artifacts', artifact.artifact_id.slice(7) + '.json');
  assert.ok(fs.existsSync(file)); assert.equal(hash(file), artifact.artifact_sha256);
  const record = JSON.parse(fs.readFileSync(file));
  assert.equal(record.project.canonical_root, profile.project);
  assert.equal(record.project.project_id, profile.identity.project_id);
  assert.equal(record.project.board_id, profile.identity.board_id);
  assert.equal(record.session_id, profile.manager.getSessionId());
  return { path: file, sha256: hash(file), text_sha256: artifact.text_sha256, session_id: record.session_id };
}
const started = Date.now();
let failure;
try {
  for (const kind of ['new_artifact', 'repeat_cached_read']) {
    const p = await createProfile(kind), checks = [], artifacts = [];
    const arm = { kind, project: p.project, task: p.task, session_id: p.manager.getSessionId(), session_file: p.manager.getSessionFile(), initial: await state(p), checks };
    arms.push(arm);
    let cached;
    if (kind === 'repeat_cached_read') cached = (await tool(p, 'web_research', { action: 'fetch', url: 'https://example.org/native-progress/cached', timeout: 2 })).details;
    for (let step = 1; step <= 3; step++) {
      const before = await state(p);
      const result = await tool(p, 'web_research', kind === 'new_artifact'
        ? { action: 'fetch', url: 'https://example.org/native-progress/fact-' + step, timeout: 2 }
        : { action: 'read', artifact_id: cached.artifact_id, limit: 8192 });
      const artifact = result.details;
      assert.equal(artifact.ok, true); assert.equal(artifact.authority, 'untrusted_source_evidence');
      const stored = durable(p, artifact); artifacts.push(artifact.artifact_id);
      const afterTool = await state(p);
      const decisionCount = p.manager.getBranch().filter(entry => entry.customType === 'pi-work-decision/v1').length;
      // Exactly the existing test_pi_native_loader native boundary driver:
      // no model/agent run. The real extension runner calls normal settle hooks
      // and rechecks continuation from each handler's emitted context entries.
      const boundary = await p.session.extensionRunner.emitBoundary({ type: 'agent_before_settle', outcome: 'completed' },
        entries => ({ contextEntries: [], contextMessages: [], llmMessages: [], pendingMessages: [], canContinue: entries.length > 0 }));
      const afterSettle = await state(p);
      const shown = (await tool(p, 'kanban_show', { task_id: p.task })).details.result.task;
      assert.ok(['ready', 'running'].includes(shown.status));
      checks.push({ step, before, artifact, durable: stored, after_tool: afterTool, boundary, after_settle: afterSettle,
        task_status: shown.status, decisions_emitted: p.manager.getBranch().filter(entry => entry.customType === 'pi-work-decision/v1').slice(decisionCount).map(entry => entry.data) });
    }
    arm.artifact_ids = artifacts;
    if (kind === 'new_artifact') assert.equal(new Set(artifacts).size, 3);
    else {
      assert.equal(new Set(artifacts).size, 1);
      assert.equal(new Set(checks.map(value => JSON.stringify(value.artifact))).size, 1, 'Repeated cached result must remain byte-identical');
    }
    arm.observed_no_progress_stop = checks[2].boundary.continue === false && /No progress across two settlement checks/.test(checks[2].after_settle.reason);
    arm.errors = p.errors; assert.deepEqual(p.errors, []);
  }
  assert.equal(httpAttempts, 0);
  const fresh = arms[0], cachedArm = arms[1];
  assert.ok(fresh.checks.every(check => check.after_tool.progress === check.before.progress + 1));
  assert.deepEqual(fresh.checks.map(check => check.after_settle.stalls), [0, 0, 0]);
  assert.ok(fresh.checks.every(check => check.boundary.continue === true));
  assert.ok(cachedArm.checks.every(check => check.after_tool.progress === check.before.progress));
  assert.equal(cachedArm.observed_no_progress_stop, true);
  const negative = await createProfile('delivery_negatives');
  const negatives = [];
  let before = snapshot(negative);
  await tool(negative, 'web_research', { action: 'fetch', url: 'https://example.org/native-progress/not-yet-committed', timeout: 2 }, { commit: false });
  assert.equal(snapshot(negative).progress, before.progress, 'Result cannot credit before committed turn_end validation');
  await turnEnd(negative);
  assert.equal(snapshot(negative).progress, before.progress + 1);
  negatives.push('matching-native-commit-required');
  before = snapshot(negative);
  await tool(negative, 'web_research', { action: 'fetch', url: 'https://example.org/native-progress/not-yet-committed', timeout: 2 });
  assert.equal(snapshot(negative).progress, before.progress, 'New timestamp/ID for same source text must not earn credit');
  negatives.push('repeated-content-new-artifact-abstains');
  before = snapshot(negative);
  await tool(negative, 'web_research', { action: 'fetch', url: 'https://example.org/native-progress/changed-message', timeout: 2 },
    { changeMessage: message => { message.content = [{ type: 'text', text: 'Different saved result' }]; } });
  assert.equal(snapshot(negative).progress, before.progress);
  negatives.push('mismatching-committed-result-abstains');
  for (const kind of ['metadata_only', 'altered_text']) {
    before = snapshot(negative);
    await tool(negative, 'web_research', { action: 'fetch', url: 'https://example.org/native-progress/' + kind, timeout: 2 },
      { transformContent: value => [{ type: 'text', text: JSON.stringify(kind === 'metadata_only'
        ? { artifact_id: value.details.artifact_id, status: 'metadata_only' }
        : { ...value.details, text: 'An altered model-facing body, while hidden details remain valid.' }) }] });
    assert.equal(snapshot(negative).progress, before.progress, 'Hidden valid details must not credit a replaced model-facing window');
    negatives.push(kind + '-model-content-with-valid-details-abstains');
  }
  before = snapshot(negative);
  let damaged, original;
  try {
    await tool(negative, 'web_research', { action: 'fetch', url: 'https://example.org/native-progress/damaged-before-credit', timeout: 2 },
      { beforeTurnEnd: result => { damaged = path.join(negative.identity.state_root, 'research/artifacts', result.details.artifact_id.slice(7) + '.json');
        original = fs.readFileSync(damaged); fs.appendFileSync(damaged, ' '); } });
    assert.equal(snapshot(negative).progress, before.progress);
  } finally { if (damaged) fs.writeFileSync(damaged, original); }
  negatives.push('artifact-byte-drift-abstains');
  before = snapshot(negative);
  await tool(negative, 'web_research', { action: 'fetch', url: 'https://example.org/native-progress/stale-input', timeout: 2 },
    { beforeTurnEnd: () => negative.session.extensionRunner.emitInput('A new source arrived; do not credit the previous operation under this request.', undefined, 'interactive') });
  assert.equal(snapshot(negative).progress, before.progress);
  negatives.push('new-native-input-invalidates-pending-credit');
  const history = (await tool(negative, 'research_history_probe', {})).details.result;
  assert.equal(history.recent_cache_bound, 256);
  negatives.push('native-history-membership-beyond-recent256-cache');
  // Hold the real guarded validator so input/abort changes happen during its
  // asynchronous readback, rather than only before the handler begins.
  const hold = path.join(home, 'state/hold-progress-validation'), entered = path.join(home, 'state/progress-validation-entered');
  async function asynchronousChange(label, change) {
    const p = await createProfile(label), before = snapshot(p);
    fs.writeFileSync(hold, 'hold'); if (fs.existsSync(entered)) fs.unlinkSync(entered);
    const pending = tool(p, 'web_research', { action: 'fetch', url: 'https://example.org/native-progress/' + label, timeout: 2 });
    try {
      const deadline = Date.now() + 15000;
      while (!fs.existsSync(entered) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
      assert.ok(fs.existsSync(entered), 'Real validator must reach owned fixture barrier');
      await change(p);
    } finally { if (fs.existsSync(hold)) fs.unlinkSync(hold); }
    await pending;
    assert.equal(snapshot(p).progress, before.progress);
  }
  await asynchronousChange('async_source_change', p => p.session.extensionRunner.emitInput('New source during validation; hold old accounting.', undefined, 'interactive'));
  negatives.push('native-input-during-validator-holds-credit');
  const aborted = await createProfile('async_abort'), controller = new AbortController();
  const runner = aborted.session.extensionRunner, originalSignal = runner.getSignalFn;
  // Source-bound fixture signal injection only. The real native createContext
  // getter reads this supplier; no actual model operation is submitted.
  runner.getSignalFn = () => controller.signal;
  before = snapshot(aborted);
  fs.writeFileSync(hold, 'hold'); if (fs.existsSync(entered)) fs.unlinkSync(entered);
  const pendingAbort = tool(aborted, 'web_research', { action: 'fetch', url: 'https://example.org/native-progress/async_abort', timeout: 2 });
  try {
    const deadline = Date.now() + 15000;
    while (!fs.existsSync(entered) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
    assert.ok(fs.existsSync(entered)); controller.abort();
  } finally {
    if (fs.existsSync(hold)) fs.unlinkSync(hold);
  }
  try { await pendingAbort; assert.equal(snapshot(aborted).progress, before.progress); }
  finally { runner.getSignalFn = originalSignal; }
  negatives.push('injected-native-context-abort-during-validator-holds-credit');
  write(path.join(fixture, 'negative-checks.json'), { negatives, history, task: negative.task, state: snapshot(negative),
    abort_scope: 'Exact native context signal supplier is injected in owned fixture; no live model cancellation acceptance claim' });
} catch (error) {
  failure = String(error);
} finally {
  for (const profile of sessions) await profile.session.dispose();
  globalThis.fetch = originalFetch;
  let exclusive = false;
  try {
    exclusive = py(`import json;from pathlib import Path;from harness import home_entry
h=Path(sys.argv[1]);c=json.loads((h/'home.json').read_text());g=home_entry._load_guard(h,c['lifecycle_guard_sha256'])
with g.lease(h,expected_sha256=c['lifecycle_guard_sha256'],mode='exclusive'):
 print(json.dumps(True))`, [home]);
  } catch (error) { failure = failure || 'Fixture exclusive cleanup failed: ' + String(error); }
  const receipt = { schema: 'native-research-progress-counterexample/v1', status: failure ? 'FAILED_PROBE' : 'PASS_SCOPED_PROGRESS', failure,
    fixture, seconds: (Date.now() - started) / 1000, arms, trace, http_attempts: httpAttempts, inference_calls: 0,
    settlement_driver: 'Actual native SessionManager appends committed assistant/toolResult entries; ExtensionRunner.emit(turn_end) with real entry IDs precedes emitBoundary(agent_before_settle, completed) and existing injected context callback. No session.prompt/model acceptance claim.',
    instrumentation: { helper_original_sha256: hashBytes(originalHelper), helper_fixture_sha256: hash(helper), scope: 'Only guarded helper transport replaced with strict deterministic synthetic public text and Python socket denial; production intake/research tool/ArtifactStore unchanged' },
    borrowed_public_dependencies: { pi_package: piPackage, pi_package_json_sha256: hash(path.join(piPackage, 'package.json')),
      research_python: options['research-python'], research_python_sha256: hash(options['research-python']),
      hermes_python: options['hermes-python'], hermes_python_sha256: hash(options['hermes-python']),
      framework_python: options['framework-python'], framework_python_sha256: hash(options['framework-python']), framework_binding_sha256: framework.sha256 },
    guard_sha256: guarded.guard_sha256, home_exclusive_passed: exclusive, source_files: manifest,
    scope: 'Injected zero-inference no-network counterexample on two new own retained unfinished fixture tasks; no source fix, effect-gate change, package install, model/service/MCP/Bun activation, live home or full9 adoption' };
  write(path.join(fixture, 'receipt.json'), receipt);
  for (const name of Object.keys(process.env)) delete process.env[name]; Object.assign(process.env, originalEnvironment);
  console.log(JSON.stringify({ status: receipt.status, failure, fixture, seconds: receipt.seconds, receipt_sha256: hash(path.join(fixture, 'receipt.json')),
    arms: arms.map(arm => ({ kind: arm.kind, stop: arm.observed_no_progress_stop, states: arm.checks.map(check => ({ progress: check.after_settle.progress, seen: check.after_settle.seen, stalls: check.after_settle.stalls, continue: check.boundary.continue, task_status: check.task_status })) })) }));
}
assert.ok(!failure, 'Inspect retained counterexample/probe failure; do not replay: ' + failure);
