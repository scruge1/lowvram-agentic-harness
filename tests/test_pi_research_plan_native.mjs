/** Actual Pi1.4 tool/ModelRuntime/OpenAI serializer; synthetic SSE, zero HTTP/inference. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import childProcess from 'node:child_process';
import { syncBuiltinESMExports } from 'node:module';
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
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-research-plan-'));
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
// Only copied acquisition transports change. The source/runtime binding,
// planning, mining, scoring and native serializers execute their real bodies.
const transportBindings = py(`import ast,json;from pathlib import Path
h=Path(sys.argv[1]);r=h/'runtime';changes=[]
edits=[('harness/web_research.py','search',"return {'schema':'web-research/v1','ok':True,'status':'ok','query':query,'hits':[{'url':'https://example.org/orchard'},{'url':'https://example.org/fail'}],'attempts':[]}"),
('harness/research_fetch.py','fetch',"return {'schema':'web-research/v1','ok':not url.endswith('/fail'),'status':'network_error' if url.endswith('/fail') else 'ok','requested_url':url,'selected_url':url,'selected_kind':'requested','requested_source_complete':not url.endswith('/fail'),'text':'The orchard has seven trees.','content_scope':'full_extraction','attempts':[]}"),
('harness/web_browser.py','render',"return {'schema':'web-research/v1','ok':True,'status':'ok','page_url':url,'document':{'text':'The orchard has seven trees.','offset':0,'truncated':False}}")]
manifest=json.loads((r/'runtime-manifest.json').read_text())
for relative,method,body in edits:
 p=r/relative;raw=p.read_bytes();lines=raw.decode().splitlines(True);node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==method);lines.insert(node.body[0].lineno-1,'    '+body+'\\n');p.write_text(''.join(lines));after=p.read_bytes();changes.append({'path':relative,'original_sha256':__import__('hashlib').sha256(raw).hexdigest(),'injected_sha256':__import__('hashlib').sha256(after).hexdigest()})
for row in manifest['files']:row['sha256']=__import__('hashlib').sha256((r/row['path']).read_bytes()).hexdigest()
(r/'runtime-manifest.json').write_text(json.dumps(manifest));c=json.loads((h/'home.json').read_text());c['runtime_manifest_sha256']=__import__('hashlib').sha256((r/'runtime-manifest.json').read_bytes()).hexdigest();(h/'home.json').write_text(json.dumps(c));print(json.dumps(changes))`, [home]);
const originalSpawn = childProcess.spawn;
let abortAfterClose;
childProcess.spawn = (...args) => {
  const child = originalSpawn(...args), controller = abortAfterClose;
  if (controller && args[1]?.includes(path.join(runtime, 'harness/research_runtime.py')))
    child.once('spawn', () => child.once('close', () => controller.abort()));
  return child;
};
syncBuiltinESMExports();
const input = { action: 'plan', query: 'How many orchard trees?', extraction_schema: ['count'],
  angles: [{ id: 'count', query: 'orchard tree count source' }], timeout: 30 };
const read = async artifact_id => {
  let text = '', offset = 0;
  for (;;) {
    const part = await tool({ action: 'read', artifact_id, offset, limit: 8192 });
    assert.equal(part.isError, false); text += part.details.text;
    if (part.details.next_offset === null) return JSON.parse(text);
    offset = part.details.next_offset;
  }
};
try {
  assert.equal((await tool(input)).isError, true); checks.push('normal-plan-requires-native-project-selection');
  select(identities[0]);
  let result = await tool(input); assert.equal(result.isError, false, JSON.stringify(result));
  const research_plan_id = result.details.artifact_id;
  assert.equal(result.details.plan_data_only, true); checks.push('normal-plan-main-agent-data-no-model-no-authority');
  result = await tool({ action: 'search', research_plan_id, angle_id: 'count', query: 'orchard tree count source' });
  assert.equal(result.isError, false, JSON.stringify(result)); const search = result.details.artifact_id;
  assert.equal((await tool({ action: 'search', research_plan_id, angle_id: 'count', query: 'wrong query' })).isError, true);
  checks.push('native-search-exact-question-angle-binding');
  const requests = [{ id: 'good', angle_id: 'count', url: 'https://example.org/orchard', search_artifact_id: search, hit_index: 0 },
    { id: 'failed', angle_id: 'count', url: 'https://example.org/fail', search_artifact_id: search, hit_index: 1 },
    { id: 'missing', angle_id: 'count', url: 'https://example.org/unattempted' }];
  assert.equal((await tool({ action: 'retrieval_plan', research_plan_id,
    requests: [{ ...requests[0], url: 'https://example.org/replaced' }] })).isError, true);
  result = await tool({ action: 'retrieval_plan', research_plan_id, requests });
  assert.equal(result.isError, false, JSON.stringify(result)); const manifest1 = result.details.artifact_id;
  checks.push('native-request-manifest-exact-search-hit-no-url-substitution');
  assert.equal((await tool({ action: 'fetch', retrieval_plan_id: manifest1, request_id: 'good', url: 'https://example.org/wrong' })).isError, true);
  result = await tool({ action: 'fetch', retrieval_plan_id: manifest1, request_id: 'good', url: requests[0].url });
  assert.equal(result.isError, false, JSON.stringify(result)); const good = result.details.artifact_id;
  result = await tool({ action: 'fetch', retrieval_plan_id: manifest1, request_id: 'failed', url: requests[1].url });
  assert.equal(result.isError, true); const failed = result.details.artifact_id;
  assert.ok(failed); checks.push('native-good-and-failed-acquisitions-retain-request-identity');
  const mine = { action: 'mine', research_plan_id, retrieval_plan_id: manifest1, artifact_ids: [good], timeout: 30 };
  result = await tool(mine); assert.equal(result.isError, false, JSON.stringify(result));
  const mined = result.details.artifact_id;
  const request = providerCalls.at(-1).payload;
  assert.ok(JSON.stringify(request.messages).includes(input.query)); assert.equal(request.chat_template_kwargs.enable_thinking, false);
  assert.equal(providerCalls.at(-1).url, 'http://127.0.0.1:1/v1/chat/completions');
  checks.push('bound-mine-derives-schema-question-through-actual-selected-native-serializer');
  result = await tool({ action: 'consensus', research_plan_id, retrieval_plan_id: manifest1,
    artifact_ids: [mined], acquisition_artifact_ids: [search, good, failed] });
  assert.equal(result.isError, true); assert.equal(result.details.coverage_complete, false);
  const partial = await read(result.details.artifact_id);
  assert.deepEqual(partial.requested_coverage.requests.map(x => x.status), ['scored', 'acquisition_failed', 'unattempted']);
  checks.push('normal-consensus-retains-good-failed-and-unattempted-request-rows');
  result = await tool({ action: 'retrieval_plan', research_plan_id, requests: [requests[0]] });
  assert.equal(result.isError, false); const manifest2 = result.details.artifact_id;
  assert.equal((await tool({ ...mine, retrieval_plan_id: manifest2 })).isError, true);
  result = await tool({ action: 'fetch', retrieval_plan_id: manifest2, request_id: 'good', url: requests[0].url });
  assert.equal(result.isError, false); const source2 = result.details.artifact_id;
  result = await tool({ action: 'mine', research_plan_id, retrieval_plan_id: manifest2, artifact_ids: [source2], timeout: 30 });
  assert.equal(result.isError, false, JSON.stringify(result)); const mine2 = result.details.artifact_id;
  result = await tool({ action: 'consensus', research_plan_id, retrieval_plan_id: manifest2, artifact_ids: [mine2],
    acquisition_artifact_ids: [search, source2] });
  assert.equal(result.isError, false, JSON.stringify(result)); assert.equal(result.details.coverage_complete, true);
  assert.equal(result.details.consensus_established, false); checks.push('complete-native-bound-chain-without-mixed-manifest-or-truth-authority');
  mode = 'empty';
  result = await tool({ action: 'mine', research_plan_id, retrieval_plan_id: manifest2, artifact_ids: [source2], timeout: 30 });
  assert.equal(result.isError, true); assert.equal(result.details.status, 'zero_claims'); const empty = result.details.artifact_id;
  assert.equal((await tool({ action: 'mine', research_plan_id, retrieval_plan_id: manifest2, artifact_ids: [source2],
    resume_artifact_id: empty, timeout: 30 })).isError, true);
  result = await tool({ action: 'consensus', research_plan_id, retrieval_plan_id: manifest2, artifact_ids: [empty],
    acquisition_artifact_ids: [search, source2] });
  assert.equal(result.isError, true); assert.equal(result.details.coverage_complete, true);
  assert.equal(result.details.status, 'no_relevant_claims'); checks.push('healthy-zero-coverage-does-not-become-success-or-seen'); mode = 'valid';
  result = await tool({ action: 'retrieval_plan', research_plan_id, requests: [requests[1]] });
  assert.equal(result.isError, false); const recoveryManifest = result.details.artifact_id;
  result = await tool({ action: 'fetch', retrieval_plan_id: recoveryManifest, request_id: 'failed', url: requests[1].url });
  assert.equal(result.isError, true); const oldFailure = result.details.artifact_id;
  result = await tool({ action: 'render', retrieval_plan_id: recoveryManifest, request_id: 'failed', url: requests[1].url });
  assert.equal(result.isError, false); const rendered = result.details.artifact_id;
  result = await tool({ action: 'mine', research_plan_id, retrieval_plan_id: recoveryManifest, artifact_ids: [rendered], timeout: 30 });
  assert.equal(result.isError, false); const recoveredMine = result.details.artifact_id;
  result = await tool({ action: 'consensus', research_plan_id, retrieval_plan_id: recoveryManifest, artifact_ids: [recoveredMine],
    acquisition_artifact_ids: [search, oldFailure, rendered] });
  assert.equal(result.isError, false, JSON.stringify(result)); assert.equal(result.details.coverage_complete, true);
  const recovered = await read(result.details.artifact_id), row = recovered.requested_coverage.requests[0];
  assert.equal(row.selection, 'unique_eligible'); assert.equal(row.fulfillment.acquisition_artifact_id, rendered);
  assert.deepEqual(row.analysis_scope, { content_scope: 'captured_browser_window', input_chars: 28, source_chars: 28, input_truncated: false });
  assert.deepEqual(row.acquisitions.map(x => x.ok), [false, true]);
  checks.push('failed-fetch-complete-render-healthy-mine-fulfills-while-retaining-failure-audit');
  select(identities[1]); assert.equal((await tool({ action: 'retrieval_plan', research_plan_id, requests })).isError, true);
  select(identities[0]); checks.push('foreign-native-project-plan-held');
  const abort = new AbortController(); abort.abort();
  result = await tool({ ...input, query: 'Cancelled new plan' }, abort.signal);
  assert.equal(result.isError, true); assert.equal(result.details.status, 'cancelled'); checks.push('preaborted-new-local-action-held');
  const late = new AbortController(); abortAfterClose = late;
  result = await tool({ ...input, query: 'Late-cancelled new plan' }, late.signal); abortAfterClose = undefined;
  assert.equal(late.signal.aborted, true); assert.equal(result.isError, true); assert.equal(result.details.status, 'cancelled');
  checks.push('new-local-action-final-helper-boundary-abort-held');
  const planner = path.join(runtime, 'harness/research_plan.py'), plannerBytes = fs.readFileSync(planner);
  const delayedPlanner = plannerBytes.toString().replace('def plan(request):', "def plan(request):\n    __import__('time').sleep(2.2)");
  assert.notEqual(delayedPlanner, plannerBytes.toString());
  const rebindPlanner = bytes => {
    fs.writeFileSync(planner, bytes);
    const file = path.join(runtime, 'runtime-manifest.json'), current = JSON.parse(fs.readFileSync(file));
    current.files.find(x => x.path === 'harness/research_plan.py').sha256 = digest(planner); write(file, current);
    const configFile = path.join(home, 'home.json'), currentConfig = JSON.parse(fs.readFileSync(configFile));
    currentConfig.runtime_manifest_sha256 = digest(file); write(configFile, currentConfig);
  };
  const planCount = () => py(`import json;from pathlib import Path
p=Path(sys.argv[1])/'research/artifacts';print(json.dumps(sum(json.loads(f.read_text()).get('action')=='plan' for f in p.glob('*.json'))))`, [identities[0].state_root]);
  rebindPlanner(delayedPlanner);
  const timing = [];
  try {
    const before = planCount(), began = Date.now();
    result = await tool({ ...input, query: 'Expired new plan', timeout: 2 });
    timing.push({ kind: 'deadline', before, after: planCount(), elapsed_ms: Date.now() - began, status: result.details.status });
    assert.equal(result.isError, true); assert.equal(result.details.status, 'deadline');
    assert.equal(timing[0].after, before); checks.push('new-local-action-productive-deadline-no-success-artifact');
    const pending = tool({ ...input, query: 'Changed native input during planning' });
    await new Promise(resolve => setTimeout(resolve, 200));
    sessionManager.appendCustomEntry('synthetic-input-during-planning', {});
    result = await pending; assert.equal(result.isError, true); assert.match(result.details.reason, /admission changed.*delivery held/);
    checks.push('new-local-plan-last-await-native-epoch-holds-delivery');
  } finally { rebindPlanner(plannerBytes); }
  assert.deepEqual(errors, []);
  write(path.join(fixture, 'receipt.json'), { schema: 'pi-research-plan-native-qualification/v1', ok: true, checks,
    fixture, elapsed_ms: Date.now() - start, source_files: manifest, trace, transportBindings,
    planner_instrumentation: { original_sha256: sha(plannerBytes), delayed_sha256: sha(Buffer.from(delayedPlanner)), timing,
      scope: 'Copied planner entry2.2s delay for deadline and native-input epoch controls only.' },
    borrowed_python: borrowedPython, native_provider_calls: providerCalls.length, provider_wire: providerCalls,
    network_requests: 0, model_inferences: 0,
    scope: 'Actual Pi1.4 registered tools, installed guarded helper, immutable question/request chain and native selected serializer. Copied acquisition functions and final SSE are explicit synthetic transports; no real acquisition/model/useful journey/fresh install/intake-progress proof.' });
  console.log(JSON.stringify({ ok: true, checks: checks.length, fixture, receipt: path.join(fixture, 'receipt.json'), elapsed_ms: Date.now() - start }));
} catch (error) {
  write(path.join(fixture, 'failure.json'), { ok: false, checks, trace, transportBindings, error: String(error.stack || error) }); throw error;
} finally { abortAfterClose = undefined; childProcess.spawn = originalSpawn; syncBuiltinESMExports(); hook = () => {}; globalThis.fetch = oldFetch; await session.dispose(); }
