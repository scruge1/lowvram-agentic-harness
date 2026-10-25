/** Actual Pi1.4 nested read calls and serialized provider input; zero HTTP. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1]);
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['source', 'pi-package', 'python', 'fixture-parent']) assert.ok(options[name], name);
const source = fs.realpathSync(options.source), pkg = fs.realpathSync(options['pi-package']);
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg, 'package.json'))).version, '1.4.0');
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-project-prepare-'));
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const runtime = path.join(fixture, 'runtime'), agentDir = path.join(fixture, 'agent');
fs.cpSync(path.join(source, 'adapters/pi'), runtime, { recursive: true, filter: file => !file.includes('__pycache__') });
fs.mkdirSync(agentDir);
const workflow = path.join(runtime, 'project-workflow'), memory = path.join(runtime, 'memory');
fs.writeFileSync(path.join(workflow, 'everyday-runtime.json'), JSON.stringify({ python: options.python, runtime,
  runtime_manifest_sha256: '0'.repeat(64), engine_sha256: '0'.repeat(64),
  helper_sha256: hash(path.join(workflow, 'everyday_workflow.py')) }));
const project = path.join(fixture, 'project'), second = path.join(fixture, 'second');
for (const root of [project, second]) {
  fs.mkdirSync(root); fs.writeFileSync(path.join(root, 'AGENTS.md'), '# Synthetic project\n\nKeep the exact owner output.\n');
}
const catalogSource = path.join(fixture, 'catalog-source.md');
fs.writeFileSync(catalogSource, '# Synthetic capability\n\nUse existing CSV parsing.\n');
const catalog = path.join(fixture, 'catalog.py'), database = path.join(fixture, 'catalog.sqlite');
fs.writeFileSync(database, 'Synthetic catalog identity; not an actual search database.\n');
fs.writeFileSync(catalog, `import hashlib,json,sys\nfrom pathlib import Path\np=Path(${JSON.stringify(catalogSource)})\nprint(json.dumps({'ok':True,'query':sys.argv[sys.argv.index('query')+1],'results':[{'source_file':str(p),'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'description':p.read_text()}]}))\n`);
const backend = path.join(fixture, 'board.py');
fs.writeFileSync(backend, `import hashlib,json,subprocess,sys\nfrom pathlib import Path\nsys.path.insert(0,${JSON.stringify(workflow)})\nfrom project_identity import initialize_identity\nr=json.load(sys.stdin);a=r['action'];root=Path(r['project_root'])\nwith Path(__file__).with_name('calls.jsonl').open('a') as f:f.write(json.dumps(r)+'\\n')\nif a=='project_admit':\n identity,_=initialize_identity(root,native_authority=r.get('native_authority'));w=root/identity['workspace_path']\n if not w.exists():subprocess.run([sys.executable,${JSON.stringify(path.join(workflow, 'init_workspace.py'))},'--root',str(w),'--target','Synthetic preparation','--why','Native read-only delivery qualification','--parent-authority','Explicit synthetic qualification'],check=True,capture_output=True)\n result={'project_root':str(root),'identity':identity}\nelif a=='show':result={'task':{'id':r['task_id'],'status':'ready'},'parents':[]}\nelif a=='knowledge_query':\n p=root/'AGENTS.md';result={'query':r['terms'],'results':[{'path':'AGENTS.md','sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'snippet':p.read_text()}]}\nelse:result={}\nprint(json.dumps({'ok':True,'schema':'pi-kanban-result/v1','action':a,'result':result}))\n`);
const registry = path.join(fixture, 'claims.jsonl'); fs.writeFileSync(registry, '');
for (const dir of ['palace', 'palace-config']) fs.mkdirSync(path.join(fixture, dir));
Object.assign(process.env, {
  PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PI_CODING_AGENT_DIR: agentDir,
  PI_PROJECT_KANBAN_PYTHON: options.python, PI_PROJECT_KANBAN_ADAPTER: backend, PI_PROJECT_KANBAN_ADAPTER_SHA256: hash(backend),
  PI_PROJECT_CONTEXT_PI_PACKAGE: pkg, PI_SYSTEM_TOOL_PYTHON: options.python,
  PI_SYSTEM_TOOL_HELPER: catalog, PI_SYSTEM_TOOL_HELPER_SHA256: hash(catalog), PI_SYSTEM_TOOL_DATABASE: database,
  PI_VALIDATED_MEMORY_PYTHON: options.python, PI_VALIDATED_MEMORY_HELPER: path.join(memory, 'validated_memory_query.py'),
  PI_VALIDATED_MEMORY_POLICY: path.join(memory, 'memory_retrieval_policy.py'), PI_VALIDATED_MEMORY_REGISTRY: registry,
  PI_VALIDATED_MEMORY_HELPER_SHA256: hash(path.join(memory, 'validated_memory_query.py')),
  PI_VALIDATED_MEMORY_POLICY_SHA256: hash(path.join(memory, 'memory_retrieval_policy.py')), PI_VALIDATED_MEMORY_REGISTRY_SHA256: hash(registry),
  MEMPALACE_PALACE_PATH: path.join(fixture, 'palace'), MEMPALACE_CONFIG_DIR: path.join(fixture, 'palace-config'),
});
delete process.env.PI_MEMORY_RUNTIME_WRAPPER; delete process.env.AGENT_HOME;
const sdk = await import(pathToFileURL(path.join(pkg, 'dist/index.js')));
const require = createRequire(path.join(pkg, 'package.json'));
const aiPackage = require.resolve.paths('@earendil-works/pi-ai').map(root => path.join(root, '@earendil-works/pi-ai/package.json')).find(file => fs.existsSync(file));
const provider = await import(pathToFileURL(path.join(path.dirname(aiPackage), 'dist/api/openai-completions.js')));
let mode = '', controller, sequence = 0, http = 0, payload, lastMessage;
const events = [], checks = [], inputs = [];
const observer = pi => {
  pi.on('context', event => {
    fs.writeFileSync(path.join(fixture, 'last-context.json'), JSON.stringify(event.messages, null, 2));
  });
  pi.on('tool_call', event => {
    events.push({ type: 'call', name: event.toolName, id: event.toolCallId, parent: event.parentToolCallId, input: event.input });
    if (mode === 'abort' && event.toolName === 'system_tool_query') controller.abort();
  });
  pi.on('tool_result', event => {
    events.push({ type: 'result', name: event.toolName, id: event.toolCallId, parent: event.parentToolCallId });
    if (mode === 'replace-child' && event.toolName === 'system_tool_query') return { content: [{ type: 'text', text: '{"ok":false,"results":[],"replacement":true}' }] };
    if (mode === 'tamper-capability' && event.toolName === 'agent_capabilities') {
      const value = JSON.parse(event.content[0].text); value.active_tools = [];
      return { content: [{ type: 'text', text: JSON.stringify(value) }] };
    }
    if (mode === 'large' && event.toolName === 'system_tool_query') return { content: [{ type: 'text', text: JSON.stringify({ ok: true, results: [], body: 'x'.repeat(70000) }) }] };
    if (mode === 'replace-outer' && event.toolName === 'project_prepare') return { content: [{ type: 'text', text: '{"replaced":true}' }] };
  });
};
const settings = sdk.SettingsManager.inMemory({ extensions: [path.join(workflow, 'agent-capabilities.ts'),
  path.join(workflow, 'system-tool-knowledge.ts'), path.join(workflow, 'pi-kanban.ts'),
  path.join(memory, 'validated-memory-query.ts'), path.join(workflow, 'everyday-workflow.ts')],
  defaultTools: ['read', 'ls', 'find', 'grep'], cacheWarming: 'off' });
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
  extensionFactories: [sdk.createCodemodeExtension(), sdk.createToolSearchExtension(), observer],
  disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'], noSkills: true, noPromptTemplates: true, noThemes: true });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const model = { id: 'fixture-no-inference', provider: 'fixture-local', name: 'No inference', api: 'openai-completions',
  baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false, contextWindow: 32768, maxTokens: 4096,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const sessionManager = sdk.SessionManager.inMemory(project);
const { session } = await sdk.createAgentSession({ cwd: project, agentDir, settingsManager: settings, resourceLoader: loader,
  sessionManager, modelRuntime, model, thinkingLevel: 'off' });
const errors = []; await session.bindExtensions({ onError: error => errors.push(error) });
const assistant = (id, name, args) => ({ role: 'assistant', api: model.api, provider: model.provider, model: model.id,
  content: [{ type: 'toolCall', id, name, arguments: args }], stopReason: 'toolUse', timestamp: Date.now() });
async function tool(name, args) {
  const id = `prepare-${++sequence}`, runner = session.extensionRunner;
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input: args });
  assert.ok(!blocked?.block, blocked?.reason);
  controller = new AbortController();
  session.agent.state.messages = [assistant(id, name, args)];
  sessionManager.appendMessage(assistant(id, name, args));
  const item = runner.getAllRegisteredTools().find(value => value.definition.name === name); assert.ok(item);
  const raw = await sdk.wrapRegisteredTool(item, runner).execute(id, args, controller.signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input: args,
    ...raw, isError: raw.isError === true });
  const result = { ...raw, ...changed };
  lastMessage = { role: 'toolResult', toolCallId: id, toolName: name, content: result.content,
    details: result.details, isError: result.isError === true, timestamp: Date.now() };
  session.agent.state.messages = [...session.agent.state.messages, lastMessage];
  sessionManager.appendMessage(lastMessage);
  return result;
}
async function held(pattern) {
  const result = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: `check-${++sequence}`,
    toolName: 'codex_plan_consult', input: {} });
  if (pattern) { assert.equal(result?.block, true); assert.match(result.reason, pattern); }
  else assert.ok(!result?.block, result?.reason);
}
async function deliver() {
  payload = undefined;
  session.agent.getApiKey = () => 'synthetic-not-a-credential';
  session.agent.streamFunction = (selected, context, opts) => provider.stream(selected, context, { ...opts,
    apiKey: 'synthetic-not-a-credential', maxRetries: 0,
    fetch: async () => { http++; throw new Error('FORBIDDEN_HTTP'); },
    onPayload(value) { payload = value; throw new Error('STOP_BEFORE_HTTP'); } });
  await session.agent.continue();
  assert.ok(payload, 'Real agent context conversion must reach provider serialization'); assert.equal(http, 0);
  inputs.push(payload);
  fs.writeFileSync(path.join(fixture, 'provider-inputs.json'), JSON.stringify(inputs, null, 2) + '\n');
}
async function reset() {
  mode = '';
  await tool('project_admit', { project_root: project, initialize: true, native_authority: 'Explicit isolated synthetic qualification',
    target: 'Preparation packet', why: 'Deliver current sources without granting execution authority' });
  await session.extensionRunner.emit({ type: 'session_tree' });
}
try {
  await reset();
  assert.ok(session.getActiveToolNames().includes('tool_search'));
  const rare = session.extensionRunner.getAllRegisteredTools().find(item => item.definition.name === 'kanban_show');
  assert.equal(rare.definition.exposure, 'deferred');
  const activeBefore = session.getActiveToolNames();
  const result = await tool('project_prepare', { query: 'CSV parsing' });
  assert.ok(!result.isError, JSON.stringify(result));
  const packet = JSON.parse(result.content[0].text); assert.equal(packet.complete, true);
  const compact = JSON.parse(packet.sections.find(section => section.tool === 'agent_capabilities').content);
  assert.equal(compact.schema, 'pi-capability-summary/v1');
  assert.ok(!JSON.stringify(packet).includes('source_info'), 'Do not expand the full capability snapshot into model context');
  assert.equal(packet.sections.length, 5); assert.ok(Buffer.byteLength(result.content[0].text) <= 65536);
  const children = events.filter(event => event.type === 'call' && event.parent === lastMessage.toolCallId);
  assert.deepEqual(children.map(event => event.name), ['project_context', 'agent_capabilities', 'system_tool_query', 'validated_memory_query', 'project_knowledge_query']);
  assert.ok(children.every(event => event.id.startsWith(lastMessage.toolCallId + '/')));
  assert.deepEqual(session.getActiveToolNames(), activeBefore, 'Preparation must not activate tools');
  await held(/agent_capabilities/); // A sibling call in the same batch remains held.
  await deliver(); await held();
  const snapshots = fs.readFileSync(path.join(fixture, 'calls.jsonl'), 'utf8').trim().split('\n').map(JSON.parse)
    .filter(call => call.action === 'capability_snapshot');
  assert.equal(snapshots.length, 1); assert.equal(snapshots[0].snapshot.schema, 'pi-native-capabilities/v1');
  assert.ok(snapshots[0].snapshot.configured_tools.every(tool => 'source_info' in tool));
  const serialized = JSON.stringify(payload);
  assert.ok(serialized.includes('Synthetic capability')); assert.ok(serialized.includes('Keep the exact owner output.'));
  assert.ok(serialized.includes('no_current_provenanced_result'));
  checks.push('native-fixed-children-default-deferred-configuration', 'unchanged-active-tools', 'same-batch-held',
    'actual-agent-provider-input-delivers-bodies', 'zero-http-empty-validated-registry',
    'actual-everyday-compact-capabilities-preserved-host-snapshot-bound');

  for (const failure of ['replace-outer', 'replace-child', 'tamper-capability', 'large', 'abort']) {
    await reset(); mode = failure;
    const changed = await tool('project_prepare', { query: 'CSV parsing' });
    if (failure === 'abort') assert.equal(changed.isError, true);
    await deliver();
    await held(failure === 'replace-child' || failure === 'large' ? /system_tool_query/ : /agent_capabilities/);
    checks.push(failure + '-held');
  }
  await reset(); await tool('project_prepare', { query: 'my API key' }); await deliver();
  await held(/validated lessons/); checks.push('sensitive-abstention-held');
  await reset(); await tool('project_prepare', { query: 'CSV parsing' }); controller.abort();
  await deliver(); await held(/agent_capabilities/); checks.push('abort-before-delivery-held');
  await reset(); await tool('project_prepare', { query: 'CSV parsing' });
  fs.appendFileSync(catalogSource, 'Changed before delivery.\n'); await deliver(); await held(/agent_capabilities/);
  checks.push('retrieved-source-drift-held');
  await reset(); await tool('project_prepare', { query: 'CSV parsing' });
  fs.appendFileSync(registry, '\n'); await deliver(); await held(/agent_capabilities/); fs.writeFileSync(registry, '');
  checks.push('registry-drift-held');
  await reset(); await tool('project_prepare', { query: 'CSV parsing' });
  await session.extensionRunner.emit({ type: 'session_tree' }); await deliver(); await held(/agent_capabilities/);
  checks.push('session-reload-held');
  await reset(); await tool('project_prepare', { query: 'CSV parsing' });
  const old = structuredClone(lastMessage);
  await tool('project_admit', { project_root: second, initialize: true,
    native_authority: 'Explicit isolated synthetic qualification', target: 'Second project', why: 'Reject old preparation' });
  sessionManager.appendMessage(old); session.agent.state.messages = [...session.agent.state.messages, old];
  await deliver(); await held(/agent_capabilities/); checks.push('project-change-held');
  await reset();
  const instructions = path.join(project, 'AGENTS.md'), original = fs.readFileSync(instructions);
  fs.writeFileSync(instructions, '# Long synthetic instructions\n\n' + 'Retain the exact checked output.\n'.repeat(700));
  const window = await tool('project_prepare', { query: 'CSV parsing' });
  const contextSection = JSON.parse(window.content[0].text).sections.find(section => section.tool === 'project_context');
  assert.equal(JSON.parse(window.content[0].text).complete, false);
  assert.equal(contextSection.status, 'partial');
  assert.ok(JSON.parse(contextSection.content).remaining_reads.includes(instructions));
  await deliver(); await held();
  const contextHold = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'partial-context-read',
    toolName: 'read', input: { path: path.join(project, 'output.txt') } });
  assert.equal(contextHold?.block, true); assert.match(contextHold.reason, /project_context/);
  fs.writeFileSync(instructions, original); checks.push('remaining-context-windows-still-held');
  assert.equal(http, 0); assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(fixture, 'result.json'), JSON.stringify({ ok: true, checks, http,
    actual_child_events: events.filter(event => event.parent), provider_inputs: inputs.length,
    limits: 'Actual Pi1.4 native nested calls and pre-HTTP provider serialization with explicit synthetic board/catalog and empty validated registry. No inference, provider HTTP, private data or production adoption.' }, null, 2) + '\n');
  console.log(JSON.stringify({ ok: true, fixture, checks, http, provider_inputs: inputs.length }));
} finally { await session.extensionRunner.emit({ type: 'session_shutdown' }); session.dispose(); }
