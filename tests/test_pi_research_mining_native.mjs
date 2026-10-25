/** Actual Pi1.4 tool/ModelRuntime/OpenAI serializer; synthetic SSE, zero HTTP/inference. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i].startsWith('--') && process.argv[i + 1]);
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const key of ['source', 'pi-package', 'research-python', 'fixture-parent']) assert.ok(options[key], `Missing --${key}`);
assert.equal(process.platform, 'linux', 'This probe uses an explicit read-only environment alias');
const start = Date.now();
const source = fs.realpathSync(options.source);
const piPackage = fs.realpathSync(options['pi-package']);
const borrowedPython = path.resolve(options['research-python']);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-research-mining-'));
const home = path.join(fixture, 'home');
const runtime = path.join(home, 'runtime');
const agentDir = path.join(home, 'agent');
const project = path.join(fixture, 'project with spaces');
const second = path.join(fixture, 'second project');
for (const dir of [runtime, agentDir, project, second, path.join(home, 'envs'), path.join(home, 'state')]) fs.mkdirSync(dir, { recursive: true });
const sha = value => createHash('sha256').update(value).digest('hex');
const digest = file => sha(fs.readFileSync(file));
const write = (file, value) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(value) + '\n'); };
const manifest = [];
function copy(relative) {
  for (const entry of fs.readdirSync(path.join(source, relative), { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue;
    assert.ok(!entry.isSymbolicLink());
    const name = path.join(relative, entry.name);
    if (entry.isDirectory()) copy(name);
    else if (/\.(py|ts|mjs|md)$/.test(name) || ['claude-memory-patch.json', 'model-service-pins.json'].includes(entry.name)) {
      const destination = path.join(runtime, name);
      fs.mkdirSync(path.dirname(destination), { recursive: true }); fs.copyFileSync(path.join(source, name), destination);
      manifest.push({ path: name.split(path.sep).join('/'), sha256: digest(destination) });
    }
  }
}
for (const dir of ['harness', 'ssot', 'adapters/pi']) copy(dir);
for (const name of ['pi-task-worker.py', 'pi_native_events.py']) {
  const destination = path.join(runtime, name);
  fs.copyFileSync(path.join(runtime, 'adapters/pi/project-workflow', name), destination);
  manifest.push({ path: name, sha256: digest(destination) });
}
write(path.join(runtime, 'runtime-manifest.json'), { files: manifest });
write(path.join(home, 'home.json'), { schema: 'agent-home/v1', home,
  selected_packages: { research: 'native-fixture-readonly-alias' },
  runtime_manifest_sha256: digest(path.join(runtime, 'runtime-manifest.json')),
  model: 'synthetic-miner', base_url: 'http://127.0.0.1:1/v1',
  validated_registry_sha256: sha(Buffer.alloc(0)), bounded_compaction_sha256: sha(Buffer.from('{}')) });
// No dependency install/doctor claim: only executable alias in this fixture.
fs.symlinkSync(path.dirname(path.dirname(borrowedPython)), path.join(home, 'envs/research'), 'dir');
const python = path.join(home, 'envs/research/bin/python');
function py(script, args = []) {
  const result = spawnSync(python, ['-I', '-B', '-c', `import sys;sys.path.insert(0,${JSON.stringify(runtime)});` + script, ...args], {
    cwd: home, encoding: 'utf8', timeout: 30000, maxBuffer: 4 * 1024 * 1024,
    env: { ...process.env, PI_PROJECT_STATE_BASE: path.join(home, 'state/projects'), PYTHONDONTWRITEBYTECODE: '1' },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout); return JSON.parse(result.stdout);
}
const guardBinding = py(`import json;from pathlib import Path;from harness import home_entry
h=Path(sys.argv[1]);b=home_entry.install(h);c=json.loads((h/'home.json').read_text());c['lifecycle_guard_sha256']=b['guard_sha256'];(h/'home.json').write_text(json.dumps(c));print(json.dumps(b))`, [home]);
const identities = py(`import importlib.util,json;from pathlib import Path
s=importlib.util.spec_from_file_location('identity',Path(sys.path[0])/'adapters/pi/project-workflow/project_identity.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
print(json.dumps([m.initialize_identity(Path(p))[0] for p in sys.argv[1:]]))`, [project, second]);
const text = 'The orchard has seven trees. SYNTHETIC_PUBLIC_RESEARCH_73 漢字🙂\n\t"\\\x01 '.repeat(2400);
const textFile = path.join(fixture, 'synthetic-text.txt'); fs.writeFileSync(textFile, text);
const seeded = py(`import json;from pathlib import Path;from harness import research_runtime as r
i=json.loads(sys.argv[1]);p={'project_id':i['project_id'],'board_id':i['board_id'],'canonical_root':i['canonical_root']}
t=Path(sys.argv[2]).read_text();v={'schema':'project-research-artifact/v1','project':p,'action':'fetch','authority':r.AUTHORITY,'payload':{'ok':True,'status':'ok','response':{'final_url':'https://example.org/orchard','cleaned_text_full':t,'raw_content_base64':'HOST_ONLY_BINARY','cleaned_text':'short'}}}
print(json.dumps({'artifact_id':r.ArtifactStore(i['state_root'],p).put(v),'text_sha256':r.digest(t.encode())}))`, [JSON.stringify(identities[0]), textFile]);
Object.assign(process.env, py(`import json;from pathlib import Path;from harness.home import environment;print(json.dumps(environment(Path(sys.argv[1]))))`, [home]),
  { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PI_CODING_AGENT_DIR: agentDir });
Object.assign(process.env, py(`import json,hashlib;from pathlib import Path;from harness import home_entry
h=Path(sys.argv[1]);p=str(h/'envs/research/bin/python');c=home_entry.guarded_command(h,[p,'-I','-B',str(h/'runtime/harness/research_runtime.py'),'--home',str(h)],python=p);raw=json.dumps(c);print(json.dumps({'PI_WEB_RESEARCH_COMMAND':raw,'PI_WEB_RESEARCH_COMMAND_SHA256':hashlib.sha256(raw.encode()).hexdigest()}))`, [home]));
const definition = { id: 'synthetic-miner', name: 'Synthetic miner', input: ['text'], reasoning: true,
  contextWindow: 32768, maxTokens: 4096, compat: { thinkingFormat: 'qwen-chat-template', supportsReasoningEffort: true },
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
write(path.join(agentDir, 'models.json'), { providers: { local: { baseUrl: 'http://127.0.0.1:1/v1',
  api: 'openai-completions', apiKey: 'local', models: [definition] } } });
let mode = 'valid', hook = () => {};
const providerCalls = [], oldFetch = globalThis.fetch;
// The final native wire request receives an owned in-memory response. This
// fetch trap never delegates to a network transport or starts inference.
globalThis.fetch = async (input, init) => {
  const request = new Request(input, init), payload = JSON.parse(await request.text());
  providerCalls.push({ url: request.url, payload }); hook();
  assert.equal(request.url, 'http://127.0.0.1:1/v1/chat/completions');
  if (mode === 'abort') return await new Promise((_resolve, reject) => {
    const abort = () => reject(new Error('synthetic abort'));
    request.signal.addEventListener('abort', abort, { once: true });
    if (request.signal.aborted) abort();
  });
  if (mode === 'transport') throw new Error('synthetic unavailable');
  const claim = { field: 'count', claim: 'There are seven trees.', relevance: 3, confidence: 0.9,
    evidence_span: mode === 'quote' ? 'invented source quote' : 'The orchard has seven trees.' };
  const content = mode === 'malformed' ? '{}' : mode === 'empty' ? '{"claims":[]}' : JSON.stringify({ claims: [claim] });
  const chunks = [
    { id: 'synthetic-response', model: 'synthetic-miner', choices: [{ index: 0, delta: { role: 'assistant', content }, finish_reason: null }] },
    { id: 'synthetic-response', model: 'synthetic-miner', choices: [{ index: 0, delta: {}, finish_reason: mode === 'length' ? 'length' : 'stop' }] },
  ];
  return new Response(chunks.map(x => 'data: ' + JSON.stringify(x) + '\n\n').join('') + 'data: [DONE]\n\n',
    { headers: { 'content-type': 'text/event-stream' } });
};
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
const settings = sdk.SettingsManager.inMemory({ extensions: [path.join(runtime, 'adapters/pi/research/research-tools.ts')], cacheWarming: 'off', defaultTools: [] });
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
  noSkills: true, noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const sessionManager = sdk.SessionManager.inMemory(project);
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const catalog = new Map();
const modelsStore = { async read(id) { return catalog.get(id); }, async write(id, value) { catalog.set(id, value); }, async delete(id) { catalog.delete(id); } };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsStore, modelsPath: path.join(agentDir, 'models.json'), allowModelNetwork: false, refreshOnCreate: false });
const model = (await modelRuntime.getAvailable('local')).find(m => m.id === definition.id); assert.ok(model);
const { session } = await sdk.createAgentSession({ cwd: project, agentDir, resourceLoader: loader, settingsManager: settings,
  sessionManager, modelRuntime, thinkingLevel: 'off', model });
const errors = [], checks = [], trace = [];
await session.bindExtensions({ onError: error => errors.push(error) });
let sequence = 0;
const select = identity => sessionManager.appendCustomEntry('pi-kanban-selection/v1', { project: { root: identity.canonical_root, projectId: identity.project_id, boardId: identity.board_id }, task: null, boardAdmissionFailed: false });
async function tool(input, signal = new AbortController().signal) {
  const runner = session.extensionRunner;
  const id = `research-native-${++sequence}`;
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: 'web_research', input });
  assert.ok(!blocked?.block, JSON.stringify(blocked));
  const registered = runner.getAllRegisteredTools().find(item => item.definition.name === 'web_research');
  assert.ok(registered, 'Actual tool must register');
  const value = await sdk.wrapRegisteredTool(registered, runner).execute(id, input, signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: 'web_research', input, ...value, isError: value.isError === true });
  const result = { ...value, ...changed };
  assert.ok(Buffer.byteLength(result.content[0].text) <= 12288);
  assert.equal(result.content[0].text.includes('HOST_ONLY_BINARY'), false);
  trace.push({ input, result }); return result;
}
const input = { action: 'mine', artifact_ids: [seeded.artifact_id], query: 'How many trees?', extraction_schema: ['count'], timeout: 30 };
try {
  assert.equal((await tool(input)).isError, true); checks.push('unselected-refused');
  select(identities[0]);
  let result = await tool(input);
  assert.equal(result.isError, false, JSON.stringify(result));
  assert.equal(result.details.complete, true); assert.equal(result.details.claim_count, 1);
  const successful = result.details.artifact_id;
  assert.equal(providerCalls.length, 1);
  const body = providerCalls[0].payload;
  assert.equal(body.model, definition.id); assert.equal(body.max_tokens ?? body.max_completion_tokens, 1000);
  assert.equal(body.temperature, 0.1); assert.equal(body.chat_template_kwargs.enable_thinking, false);
  assert.ok(JSON.stringify(body.messages).includes('The orchard has seven trees.'));
  assert.ok(!body.tools?.length); checks.push('actual-native-model-registry-auth-serializer-source-prompt-thinking-off-no-tools');
  const callsBeforeResume = providerCalls.length;
  result = await tool({ ...input, resume_artifact_id: successful });
  assert.equal(result.isError, false); assert.equal(result.details.artifact_id, successful);
  assert.equal(providerCalls.length, callsBeforeResume); checks.push('unchanged-success-resume-no-provider-call');
  result = await tool({ action: 'read', artifact_id: successful, limit: 8192 });
  assert.match(result.details.text, /evidence_start/); assert.match(result.details.text, /source_text_sha256/);
  assert.match(result.details.text, /synthetic-miner/); checks.push('cached-mining-provenance-offsets-actual-model');
  for (const failure of ['empty', 'malformed', 'quote', 'length', 'transport']) {
    mode = failure; result = await tool(input);
    assert.equal(result.isError, true, failure); assert.equal(result.details.complete, false, failure);
    assert.equal(result.details.status, failure === 'empty' ? 'zero_claims' : 'all_failed');
    const response = await tool({ ...input, resume_artifact_id: result.details.artifact_id });
    assert.equal(response.isError, true); checks.push('native-' + failure + '-ledger-not-seen');
  }
  const beforeDead = providerCalls.length;
  result = await tool({ ...input, extraction_schema: ['count', ...Array.from({ length: 8 }, (_, n) => 'field' + n)] });
  assert.equal(result.details.expected_shards, 2); assert.equal(result.details.attempted_shards, 1);
  assert.equal(providerCalls.length, beforeDead + 1); checks.push('first-dead-native-route-stops-before-remaining-shards');
  mode = 'valid';
  const aborted = new AbortController(); aborted.abort();
  const beforeAbort = providerCalls.length;
  assert.equal((await tool(input, aborted.signal)).isError, true);
  assert.equal(providerCalls.length, beforeAbort); checks.push('preabort-no-provider-call');
  const abort = new AbortController(); mode = 'abort'; hook = () => { setTimeout(() => abort.abort(), 20); };
  result = await tool(input, abort.signal);
  assert.equal(result.details.status, 'cancelled'); assert.equal(result.details.complete, false);
  checks.push('native-abort-propagates-and-failure-ledger-not-seen');
  hook = () => {}; mode = 'abort';
  result = await tool({ ...input, timeout: 2 });
  assert.equal(result.details.status, 'deadline'); assert.equal(result.details.complete, false);
  checks.push('declared-mine-deadline-no-session-limit');
  mode = 'valid';
  hook = () => select(identities[1]);
  result = await tool(input); assert.equal(result.isError, true);
  assert.match(result.details.reason, /admission changed/); checks.push('native-admission-epoch-change-refuses-publish');
  select(identities[0]); hook = () => sessionManager.appendCustomEntry('synthetic-new-input', { text: 'new request' });
  result = await tool(input); assert.equal(result.isError, true);
  assert.match(result.details.reason, /admission changed/); checks.push('native-session-leaf-input-change-refuses-publish');
  hook = () => {};
  const modelFile = path.join(agentDir, 'models.json'), bytes = fs.readFileSync(modelFile);
  hook = () => fs.appendFileSync(modelFile, ' ');
  result = await tool(input); assert.equal(result.isError, true);
  assert.match(result.details.reason, /model or transport changed/); fs.writeFileSync(modelFile, bytes);
  checks.push('native-configured-model-byte-drift-refuses-publish'); hook = () => {};
  const long = await tool({ ...input, timeout: 86401 }); assert.equal(long.isError, true);
  assert.match(long.details.reason, /86400/); checks.push('per-operation-budget-validation');
  assert.deepEqual(errors, []);
  write(path.join(fixture, 'receipt.json'), { schema: 'pi-research-mining-native-qualification/v1', ok: true, checks, fixture,
    elapsed_ms: Date.now() - start, source_files: manifest, trace, borrowed_python: borrowedPython,
    native_provider_calls: providerCalls.length, provider_wire: providerCalls, network_requests: 0, model_inferences: 0,
    scope: 'Actual Pi1.4 registered tool, selected ModelRuntime/auth/OpenAI serializer and installed guarded Python helper. Synthetic SSE in memory; no HTTP/inference or useful-research quality claim. In-memory session/project-selection fixture; no coordinator/intake/root-task acceptance claim.' });
  console.log(JSON.stringify({ ok: true, checks: checks.length, fixture, receipt: path.join(fixture, 'receipt.json'), elapsed_ms: Date.now() - start }));
} catch (error) {
  write(path.join(fixture, 'failure.json'), { ok: false, checks, error: String(error.stack || error), trace, source_files: manifest, providerCalls }); throw error;
} finally { hook = () => {}; globalThis.fetch = oldFetch; await session.dispose(); }
