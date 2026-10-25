/** Native Pi declaration/discovery/handler pipeline with synthetic SSE; no HTTP or model. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let index = 2; index < process.argv.length; index += 2) {
  assert.ok(process.argv[index]?.startsWith('--') && process.argv[index + 1], 'Use --name value arguments');
  options[process.argv[index].slice(2)] = process.argv[index + 1];
}
for (const name of ['source', 'baseline-source', 'pi-package', 'home', 'python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
const started = Date.now(), source = fs.realpathSync(options.source), baseline = fs.realpathSync(options['baseline-source']);
const home = fs.realpathSync(options.home), piPackage = fs.realpathSync(options['pi-package']);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-rare-tools-'));
const hash = value => createHash('sha256').update(value).digest('hex');
const writeJson = (name, value) => fs.writeFileSync(path.join(fixture, name), JSON.stringify(value, null, 2) + '\n');
const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
assert.equal(config.name, 'RareToolExposureOwner', 'Use a fresh owned qualification home, not a personal or previous C6 home');
assert.ok(fs.existsSync(path.join(home, 'state/borrowed-dependency-qualification.json')), 'Use the reviewed no-install borrowed-dependency bootstrap');
assert.equal(config.profile, 'pi');
const settingsJson = JSON.parse(fs.readFileSync(path.join(home, 'agent/settings.json')));
const modelsJson = JSON.parse(fs.readFileSync(path.join(home, 'agent/models.json')));
const watched = ['home.json', 'agent/settings.json', 'agent/models.json', 'runtime/runtime-manifest.json'];
const watchedHashes = () => Object.fromEntries(watched.map(name => [name, hash(fs.readFileSync(path.join(home, name)))]));
const before = watchedHashes(), checks = [], captures = [];
const allowedEnvironment = new Set(['HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TMP', 'TEMP']);
const removedEnvironmentNames = Object.keys(process.env).filter(name => !allowedEnvironment.has(name));
for (const name of removedEnvironmentNames) delete process.env[name];
Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' });
const rare = ['kanban_hierarchy', 'kanban_decompose', 'project_knowledge_rebuild', 'project_closeout_prepare',
  'project_skill_candidate_compile', 'project_memory_candidate_prepare', 'kanban_list', 'kanban_show', 'kanban_create', 'kanban_comment'];
const moduleName = 'adapters/pi/project-workflow/pi-kanban.ts';
const setupCode = `import json,os,sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom harness import home as h\nhome=Path(sys.argv[2]);project=Path(sys.argv[3]);project.mkdir()\n(project/'AGENTS.md').write_text('# Owned native exposure fixture\\nRead-only discovery and board reads only. No task execution is authorized.\\n')\nos.environ.update(h.environment(home,project))\nresult=h.board(home,{'action':'project_admit','project_root':str(project),'initialize':True,'native_authority':'Owner authorized a disposable native exposure qualification','target':'Native deferred metadata and existing read handlers','why':'No model, GPU, shared board or private data'})\nprint(json.dumps({'result':result,'environment':h.environment(home,project)}))\n`;
const project = path.join(fixture, 'project');
const setup = spawnSync(options.python, ['-B', '-c', setupCode, source, home, project], { encoding: 'utf8', timeout: 90000 });
assert.equal(setup.status, 0, setup.stderr + setup.stdout);
const prepared = JSON.parse(setup.stdout);
Object.assign(process.env, prepared.environment, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' });
const originalFetch = globalThis.fetch;
let active;
function response(model, call, id) {
  const delta = call ? { role: 'assistant', tool_calls: [{ index: 0, id, type: 'function',
    function: { name: call.name, arguments: JSON.stringify(call.args) } }] } : { role: 'assistant', content: 'Owned read-only fixture complete.' };
  const chunks = [{ id, object: 'chat.completion.chunk', created: 0, model, choices: [{ index: 0, delta, finish_reason: null }] },
    { id, object: 'chat.completion.chunk', created: 0, model, choices: [{ index: 0, delta: {}, finish_reason: call ? 'tool_calls' : 'stop' }] }];
  return new Response(chunks.map(chunk => 'data: ' + JSON.stringify(chunk) + '\n\n').join('') + 'data: [DONE]\n\n',
    { status: 200, headers: { 'content-type': 'text/event-stream' } });
}
// Synthetic provider responses exercise the real serializer, parser, agent loop,
// extension hooks and registered handler. This never calls the original fetch.
globalThis.fetch = async (input, init) => {
  assert.ok(active, 'Unexpected transport outside the owned native fixture');
  const request = new Request(input, init), body = await request.text(), payload = JSON.parse(body);
  assert.equal(request.url, modelsJson.providers.local.baseUrl + '/chat/completions');
  const phase = active.payloads.length;
  active.payloads.push({ body_sha256: hash(body), payload });
  const id = active.label + '-' + phase;
  let call;
  if (phase === 0) {
    const captured = [...active.session.sessionManager.getBranch()].reverse().find(entry => entry.type === 'custom' && entry.customType === 'pi-request-capture/v1');
    assert.ok(captured?.data?.id, 'Normal session.prompt must capture the actual question');
    call = { name: 'kanban_intake_route', args: { source_id: captured.data.id,
      parts: [{ kind: 'question', summary: 'Read-only inspection of the owned project board using native tool discovery.', execute: false }], control: 'preserve' } };
  } else if (active.kind !== 'candidate') {
    assert.ok(phase <= 2, 'Unexpected automatic continuation in direct fixture');
    if (phase === 1) call = { name: 'kanban_list', args: { limit: 2 } };
  } else {
    const steps = [
      { name: 'tool_search', args: { query: 'kanban_list', limit: 1 } },
      { name: 'kanban_list', args: { limit: 2 } },
      { name: 'nonexistent_rare_tool_fixture_zzqvx', args: {} },
      { name: 'tool_search', args: { query: '', limit: 1 } },
      { name: 'tool_search', args: { query: 'zzqvx_unmatched_fixture_5930', limit: 1 } },
      { name: 'kanban_list', args: { limit: 2, view: { expected_reply_sha256: '0'.repeat(64) } } },
      { name: 'tool_search', args: { query: 'kanban_show', limit: 1 } },
      { name: 'kanban_show', args: { task_id: 'missing-owned-fixture-card' } },
    ];
    assert.ok(phase <= steps.length + 1, 'Unexpected automatic continuation in deferred fixture');
    call = steps[phase - 1];
  }
  return response(payload.model, call, id);
};
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(piPackage, 'package.json'))).version, '1.4.0');
const searchModule = await import(pathToFileURL(path.join(piPackage, 'dist/extensions/tool-search/tool.js')));
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const catalog = new Map();
const modelsStore = { async read(id) { return catalog.get(id); }, async write(id, value) { catalog.set(id, value); }, async delete(id) { catalog.delete(id); } };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsStore, modelsPath: path.join(home, 'agent/models.json'), allowModelNetwork: false, refreshOnCreate: false });
const model = (await modelRuntime.getAvailable('local')).find(item => item.id === config.model);
assert.ok(model);
const stableDefinition = item => ({ name: item.name, description: item.description, parameters: item.parameters });
async function profile(label, kind, moduleRoot, discovery = 'normal', entries) {
  const extension = path.join(moduleRoot, moduleName);
  const extensions = settingsJson.extensions.filter(filename => !filename.endsWith('/memory-capture.ts'))
    .map(filename => filename.endsWith('/pi-kanban.ts') ? extension : filename);
  const settings = sdk.SettingsManager.inMemory({ ...settingsJson, extensions, retry: { enabled: false }, compaction: { enabled: false } });
  const factory = discovery === 'absent' ? [] : [pi => pi.registerTool({ ...searchModule.createToolSearchToolDefinition({ tools: pi }),
    ...(discovery === 'hidden' ? { exposure: 'hidden' } : {}), defaultActive: false })];
  const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir: path.join(home, 'agent'), settingsManager: settings,
    disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'], extensionFactories: factory, noThemes: true });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const manager = sdk.SessionManager.inMemory(project, undefined, entries);
  const { session } = await sdk.createAgentSession({ cwd: project, agentDir: path.join(home, 'agent'), modelRuntime, model,
    settingsManager: settings, resourceLoader: loader, sessionManager: manager, thinkingLevel: 'off' });
  const cap = { label, kind, discovery, payloads: [], events: [], session };
  session.subscribe(event => cap.events.push(JSON.parse(JSON.stringify(event))));
  await session.bindExtensions({ onError: error => { throw error; } });
  if (kind === 'baseline' && discovery === 'normal') session.setActiveToolsByName([...session.getActiveToolNames(), 'tool_search']);
  cap.initial = session.getActiveToolNames();
  cap.definitions = session.getAllTools().map(stableDefinition);
  if (!entries) {
    const registered = session.extensionRunner.getAllRegisteredTools().find(item => item.definition.name === 'project_admit');
    const admitted = await sdk.wrapRegisteredTool(registered, session.extensionRunner).execute('owned-setup-admit', { project_root: project }, new AbortController().signal);
    assert.equal(admitted.details.ok, true, JSON.stringify(admitted));
  }
  return cap;
}
async function drive(cap) {
  active = cap;
  const timer = setTimeout(() => { void cap.session.abort(); }, 45000);
  try {
    await cap.session.prompt('Show the owned project card list. This is a read-only metadata question and creates no work.');
    cap.entries = [cap.session.sessionManager.getHeader(), ...cap.session.sessionManager.getEntries()];
    cap.final = cap.session.getActiveToolNames();
    assert.ok(cap.events.some(event => event.type === 'agent_settled'), 'Native run must settle');
    assert.ok(!cap.events.some(event => event.type === 'compaction_start'), 'This probe must not generate a summary');
    return cap;
  } finally { clearTimeout(timer); active = undefined; }
}
const tools = payload => payload.tools.map(tool => tool.function.name);
const ended = cap => cap.events.filter(event => event.type === 'tool_execution_end');
const compact = cap => ({ label: cap.label, kind: cap.kind, discovery: cap.discovery, initial: cap.initial, final: cap.final,
  payloads: cap.payloads, events: cap.events, definitions: cap.definitions });
let baselineCap, candidate, absent, hidden, resumedOld, resumedLoaded;
try {
  baselineCap = await drive(await profile('baseline', 'baseline', baseline));
  await baselineCap.session.dispose();
  candidate = await drive(await profile('candidate', 'candidate', source));
  const oldNames = tools(baselineCap.payloads[0].payload), newNames = tools(candidate.payloads[0].payload);
  assert.deepEqual(newNames, oldNames.filter(name => !rare.includes(name)));
  for (const name of rare) assert.ok(!newNames.includes(name));
  assert.ok(newNames.includes('tool_search'));
  assert.ok(newNames.includes('workflow_step'));
  assert.deepEqual(candidate.definitions, baselineCap.definitions, 'Descriptions, parameter schemas and core registrations must remain unchanged');
  const oldSchemas = baselineCap.payloads[0].payload.tools, newSchemas = candidate.payloads[0].payload.tools;
  assert.deepEqual(newSchemas, oldSchemas.filter(tool => !rare.includes(tool.function.name)));
  checks.push('ten-rare-schemas-omitted-from-real-first-request', 'core-definitions-and-remaining-wire-schemas-unchanged');
  const outcomes = ended(candidate);
  const searches = outcomes.filter(event => event.toolName === 'tool_search');
  assert.deepEqual(searches[0].result.details.loaded, ['kanban_list']);
  assert.ok(tools(candidate.payloads[2].payload).includes('kanban_list'), 'Native search must declare the exact tool on the following request');
  const listed = outcomes.find(event => event.toolName === 'kanban_list');
  assert.equal(listed.isError, false);
  assert.equal(listed.result.details.ok, true);
  assert.equal(listed.result.details.action, 'list');
  assert.deepEqual(listed.result.details.result.tasks, []);
  checks.push('native-exact-name-discovery-and-next-request-declaration', 'actual-agent-pipeline-reaches-unchanged-board-handler');
  assert.ok(outcomes.find(event => event.toolName === 'nonexistent_rare_tool_fixture_zzqvx')?.isError);
  assert.ok(searches[1].isError);
  assert.deepEqual(searches[2].result.details.loaded, []);
  assert.deepEqual(tools(candidate.payloads[4].payload), tools(candidate.payloads[6].payload), 'Invalid or unmatched discovery must not activate another rare tool');
  const stale = outcomes.filter(event => event.toolName === 'kanban_list')[1];
  assert.equal(JSON.parse(stale.result.content[0].text).result.stale_cursor, true);
  assert.deepEqual(searches[3].result.details.loaded, ['kanban_show']);
  assert.ok(outcomes.find(event => event.toolName === 'kanban_show')?.isError);
  checks.push('unknown-invocation-and-invalid-or-unmatched-discovery-refused', 'stale-cursor-and-existing-handler-error-refused');
  await candidate.session.dispose();
  resumedOld = await profile('old-active-restored', 'restore', source, 'normal', baselineCap.entries);
  for (const name of rare) assert.ok(resumedOld.initial.includes(name), 'Do not shrink an existing active loadout: ' + name);
  resumedLoaded = await profile('discovered-active-restored', 'restore', source, 'normal', candidate.entries);
  for (const name of ['kanban_list', 'kanban_show']) assert.ok(resumedLoaded.initial.includes(name));
  checks.push('native-restoration-preserves-old-and-newly-discovered-active-tools');
  absent = await drive(await profile('discovery-absent', 'fallback', source, 'absent'));
  hidden = await drive(await profile('discovery-hidden', 'fallback', source, 'hidden'));
  for (const cap of [absent, hidden]) {
    const expected = oldSchemas.filter(tool => tool.function.name !== 'tool_search');
    const actual = cap.payloads[0].payload.tools;
    const byName = values => [...values].sort((a, b) => a.function.name.localeCompare(b.function.name));
    assert.deepEqual(byName(actual), byName(expected), 'Fallback must retain every previous schema unchanged');
    assert.deepEqual(tools(cap.payloads[0].payload).filter(name => !rare.includes(name)),
      oldNames.filter(name => name !== 'tool_search' && !rare.includes(name)), 'Fallback must preserve core relative order');
    assert.ok(ended(cap).find(event => event.toolName === 'kanban_list')?.result.details.ok);
  }
  checks.push('absent-or-hidden-native-discovery-retains-previous-direct-surface');
  assert.deepEqual(watchedHashes(), before, 'Native qualification must preserve maintained home configuration/bindings');
  for (const cap of [baselineCap, candidate, absent, hidden]) { captures.push(compact(cap)); writeJson(cap.label + '.json', compact(cap)); }
  const receipt = { status: 'passed', fixture, checks, source, baseline_source: baseline, home,
    source_sha256: hash(fs.readFileSync(path.join(source, moduleName))), baseline_sha256: hash(fs.readFileSync(path.join(baseline, moduleName))),
    test_sha256: hash(fs.readFileSync(new URL(import.meta.url))),
    initial_schema_bytes: { baseline: Buffer.byteLength(JSON.stringify(oldSchemas)), candidate: Buffer.byteLength(JSON.stringify(newSchemas)),
      removed: Buffer.byteLength(JSON.stringify(oldSchemas)) - Buffer.byteLength(JSON.stringify(newSchemas)) },
    native_fetch_interceptions: captures.reduce((sum, cap) => sum + cap.payloads.length, 0), network_requests: 0, model_inferences: 0,
    removed_environment_names: removedEnvironmentNames,
    elapsed_ms: Date.now() - started,
    limits: 'Synthetic SSE drives actual native request serialization, parsing, tool search, hooks and owned read handlers. No model quality or token/latency savings. Native search is BM25: check returned names; it is not exact-only search or authority. Restoration is in-memory native history, not qualified cold-resume ownership.' };
  writeJson('receipt.json', receipt); console.log(JSON.stringify(receipt, null, 2));
} catch (error) {
  writeJson('failure.json', { status: 'failed', fixture, checks, error: String(error), stack: error.stack,
    captures: [baselineCap, candidate, absent, hidden].filter(Boolean).map(compact) });
  throw error;
} finally {
  active = undefined;
  for (const cap of [baselineCap, candidate, absent, hidden, resumedOld, resumedLoaded]) if (cap) await cap.session.dispose();
  globalThis.fetch = originalFetch;
}
