/** Deferred MCP discovery and current project gates; synthetic owned palace only. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1], 'Use --name value arguments');
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['source', 'pi-package', 'home', 'python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
const started = Date.now(), source = fs.realpathSync(options.source), home = fs.realpathSync(options.home);
const piPackage = fs.realpathSync(options['pi-package']), python = path.resolve(options.python);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-mcp-exposure-'));
const sha = value => createHash('sha256').update(value).digest('hex');
const hash = file => sha(fs.readFileSync(file));
const writeJson = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
const watched = ['home.json', 'agent/settings.json', 'agent/mcp.json', 'agent/models.json', 'agent/auth.json',
  'agent/models-store.json', 'runtime/runtime-manifest.json', 'state/framework-binding.json', 'state/validated-memory.jsonl'];
const hashes = () => Object.fromEntries(watched.map(name => [name, fs.existsSync(path.join(home, name)) ? hash(path.join(home, name)) : null]));
const before = hashes(), checks = [], trace = [], measurements = [], profiles = [];
const check = (name, passed, evidence = {}) => {
  const item = { name, passed: Boolean(passed), ...evidence }; checks.push(item);
  writeJson(path.join(fixture, 'progress.json'), { fixture, checks });
  if (!passed) console.error(JSON.stringify({ qualification_checkpoint: item, fixture }));
};
const homeSettings = JSON.parse(fs.readFileSync(path.join(home, 'agent/settings.json')));
const homeModels = JSON.parse(fs.readFileSync(path.join(home, 'agent/models.json')));
const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
assert.equal(config.home, home); assert.equal(config.profile, 'full');
const originalMcp = JSON.parse(fs.readFileSync(path.join(home, 'agent/mcp.json')));
assert.ok(['direct', 'deferred'].includes(originalMcp.mcpServers.mempalace.exposure), 'Keep the exact accepted production exposure unchanged');
const query = options.query || 'SYNTHETIC_ORCHARD_CAPTURE_73';
const expectedBody = options['expected-body'] || 'VISIBLE_RECALL_BODY_COBALT_9421';
// This helper reads configuration only. Keep the user's true HOME unchanged.
const envRead = spawnSync(python, ['-B', '-c', 'import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from harness.home import environment;print(json.dumps(environment(Path(sys.argv[2]))))', source, home],
  { encoding: 'utf8', timeout: 30000 });
assert.equal(envRead.status, 0, envRead.stderr);
const normalEnvironment = JSON.parse(envRead.stdout);
Object.assign(process.env, normalEnvironment, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' });
// Generate the candidate with the existing installer, without package installs.
// Its extensions, prompt, catalog and description are the current source. Only
// the actual dependency and synthetic-palace transport come from the old home.
const candidate = path.join(fixture, 'source-candidate');
const scaffolded = spawnSync(python, ['-B', '-c',
  'import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from harness.home import scaffold;print(json.dumps(scaffold(Path(sys.argv[2]),source=Path(sys.argv[1]),profile="full",base_url=sys.argv[3],model=sys.argv[4],name=sys.argv[5],offline=True,context_window=int(sys.argv[6]),max_output=int(sys.argv[7]))))',
  source, candidate, config.base_url, config.model, config.name, String(config.context_window), String(config.max_output)],
  { env: process.env, encoding: 'utf8', timeout: 30000 });
assert.equal(scaffolded.status, 0, scaffolded.stderr + scaffolded.stdout.slice(-1000));
const candidateSettings = JSON.parse(fs.readFileSync(path.join(candidate, 'agent/settings.json')));
const candidateMcp = JSON.parse(fs.readFileSync(path.join(candidate, 'agent/mcp.json'))).mcpServers.mempalace;
assert.equal(candidateMcp.exposure, 'deferred');
assert.ok(candidateMcp.description === undefined || typeof candidateMcp.description === 'string');
const memoryPython = path.join(home, 'envs/mempalace/bin/python'), memoryWrapper = path.join(home, 'runtime/harness/memory_runtime.py');
function hub(operation) {
  const result = spawnSync(memoryPython, ['-B', memoryWrapper, '--home', home, `hub-${operation}`],
    { env: process.env, encoding: 'utf8', timeout: 75000 });
  assert.equal(result.status, 0, result.stderr + result.stdout.slice(-1000));
  const value = JSON.parse(result.stdout); trace.push({ hub: operation, result: value }); return value;
}
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(piPackage, 'package.json'))).version, '1.4.0');
const require = createRequire(path.join(piPackage, 'package.json'));
const aiManifest = require.resolve.paths('@earendil-works/pi-ai')
  .map(directory => path.join(directory, '@earendil-works/pi-ai/package.json')).find(file => fs.existsSync(file));
assert.ok(aiManifest); const aiDist = path.join(path.dirname(aiManifest), 'dist');
const { normalizeContext } = await import(pathToFileURL(path.join(aiDist, 'utils/transcript.js')));
const provider = await import(pathToFileURL(path.join(aiDist, 'api/openai-completions.js')));
const { loadMcpConfig } = await import(pathToFileURL(path.join(piPackage, 'dist/extensions/mcp/config.js')));
const selectedModel = homeModels.providers.local.models.find(model => model.id === config.model);
assert.ok(selectedModel);
const model = { ...selectedModel, name: selectedModel.name || config.model, provider: 'local', api: 'openai-completions',
  baseUrl: homeModels.providers.local.baseUrl, input: ['text'], reasoning: false,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
async function makeProfile(label, exposure, cwd, agentDir, extensions) {
  process.env.PI_CODING_AGENT_DIR = agentDir;
  const errors = [], notifications = [];
  const settings = sdk.SettingsManager.inMemory({ ...candidateSettings, extensions, cacheWarming: 'off' });
  const mcp = sdk.createMcpExtension({ credentials,
    loadConfig(ctx) {
      const loaded = loadMcpConfig({ agentDir: path.join(home, 'agent'), cwd: ctx.cwd, projectTrusted: ctx.isProjectTrusted() });
      return { ...loaded, servers: loaded.servers.map(entry => entry.name === 'mempalace'
        ? { ...entry, config: { ...entry.config, exposure, description: candidateMcp.description,
          env: { ...entry.config.env, CUDA_VISIBLE_DEVICES: '' } } } : entry) };
    }, updateConfig() { throw new Error('Qualification never changes MCP configuration'); } });
  const loader = new sdk.DefaultResourceLoader({ cwd, agentDir, settingsManager: settings,
    extensionFactories: [sdk.createCodemodeExtension(), sdk.createToolSearchExtension(), mcp],
    disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'], noSkills: true, noPromptTemplates: true, noThemes: true });
  await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
  const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
  const sessionManager = sdk.SessionManager.inMemory(cwd);
  const { session } = await sdk.createAgentSession({ cwd, agentDir, settingsManager: settings,
    resourceLoader: loader, sessionManager, modelRuntime, model, thinkingLevel: 'off' });
  await session.bindExtensions({ onError: error => errors.push(error) });
  const profile = { label, exposure, cwd, session, sessionManager, loader, errors, notifications, closed: false };
  profiles.push(profile);
  // The native command waits for this plugin's own startup connection promise.
  const commandContext = session.extensionRunner.createCommandContext();
  commandContext.ui.notify = (message, type) => notifications.push({ message, type });
  await session.extensionRunner.getCommand('mcp').handler('', commandContext);
  const memTools = session.extensionRunner.getAllRegisteredTools().filter(item => item.definition.name.startsWith('mcp__mempalace__'));
  assert.equal(memTools.length, 47, `${label} must connect the installed47-tool MCP server`);
  return profile;
}
async function close(profile) {
  if (profile.closed) return; profile.closed = true;
  await profile.session.extensionRunner.emit({ type: 'session_shutdown' }); profile.session.dispose();
}
let callSequence = 0;
async function tool(profile, name, input, allowError = false) {
  const runner = profile.session.extensionRunner, id = `mcp-native-${++callSequence}`;
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!blocked?.block, `${name} blocked: ${blocked?.reason}`);
  const item = runner.getAllRegisteredTools().find(value => value.definition.name === name);
  const wrapped = item ? sdk.wrapRegisteredTool(item, runner) : sdk.createReadTool(profile.cwd);
  let raw;
  try { raw = await wrapped.execute(id, input, new AbortController().signal); }
  catch (error) {
    trace.push({ profile: profile.label, name, input, thrown: String(error) });
    if (allowError) return { thrown: String(error) };
    throw error;
  }
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...raw, isError: raw.isError === true });
  const result = { ...raw, ...changed };
  profile.lastMessage = { role: 'toolResult', toolCallId: id, toolName: name, content: result.content,
    details: result.details, isError: result.isError === true, timestamp: Date.now() };
  trace.push({ profile: profile.label, name, input, result });
  if (!allowError) assert.ok(!result.isError, `${name}: ${JSON.stringify(result.content).slice(0, 500)}`);
  return result;
}
async function measureSchemas(profile) {
  let payload, http = 0;
  const context = normalizeContext({ systemPrompt: profile.session.agent.state.systemPrompt,
    messages: [{ role: 'user', content: 'Tool schema measurement only.', timestamp: 0 }], tools: profile.session.agent.state.tools });
  const stream = provider.stream(model, context, { apiKey: 'local', maxTokens: 1, maxRetries: 0,
    fetch: async () => { http++; throw new Error('FORBIDDEN_PROVIDER_HTTP'); },
    onPayload(value) { payload = value; throw new Error('MEASUREMENT_STOP_BEFORE_HTTP'); } });
  await stream.result(); assert.ok(payload); assert.equal(http, 0);
  assert.equal(payload.tools.length, profile.session.getActiveToolNames().length);
  const value = { profile: profile.label, active_tools: profile.session.getActiveToolNames().sort(),
    active_count: payload.tools.length, provider_schema_bytes: Buffer.byteLength(JSON.stringify(payload.tools)), provider_http: http };
  measurements.push(value); return value;
}
const required = ['agent_capabilities', 'system_tool_query', 'project_admit', 'project_context', 'project_knowledge_query',
  'kanban_intake_status', 'kanban_intake_route', 'kanban_work_checkpoint', 'workflow_step'];
function requiredActive(profile) { return required.every(name => profile.session.getActiveToolNames().includes(name)); }
async function discover(profile, name = 'mcp__mempalace__mempalace_search') {
  const result = await tool(profile, 'tool_search', { query: name, limit: 1 });
  assert.deepEqual(result.details.loaded, [name]); assert.ok(profile.session.getActiveToolNames().includes(name)); return result;
}
const current = path.join(fixture, 'current'); fs.mkdirSync(current);
const copied = [];
function copyTree(relative) {
  for (const item of fs.readdirSync(path.join(source, relative), { withFileTypes: true })) {
    if (item.name === '__pycache__') continue;
    const name = path.join(relative, item.name); assert.ok(!item.isSymbolicLink());
    if (item.isDirectory()) copyTree(name);
    else if (/\.(py|ts|mjs|md)$/.test(item.name)) {
      const target = path.join(current, name); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.copyFileSync(path.join(source, name), target);
      copied.push({ path: name.split(path.sep).join('/'), sha256: hash(target) });
    }
  }
}
copyTree('adapters/pi'); writeJson(path.join(fixture, 'source-manifest.json'), copied);
const workflow = path.join(current, 'adapters/pi/project-workflow');
writeJson(path.join(workflow, 'everyday-runtime.json'), { python, runtime: current, runtime_manifest_sha256: '0'.repeat(64),
  engine_sha256: '0'.repeat(64), helper_sha256: hash(path.join(workflow, 'everyday_workflow.py')) });
async function gateProfile(label, exposure) {
  const project = path.join(fixture, label), agentDir = path.join(fixture, label + '-agent'); fs.mkdirSync(project); fs.mkdirSync(agentDir);
  fs.writeFileSync(path.join(project, 'AGENTS.md'), '# Synthetic deferred MCP gate fixture\n\nRetain the explicit owner outcome.\n');
  const skill = path.join(agentDir, 'skills/supervised-tasks/SKILL.md'); fs.mkdirSync(path.dirname(skill), { recursive: true });
  fs.writeFileSync(skill, fs.readFileSync(path.join(source, 'harness/templates/agent-home/agent/skills/supervised-tasks/SKILL.md'), 'utf8').replaceAll('{{HOME}}', project));
  Object.assign(process.env, normalEnvironment, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', CUDA_VISIBLE_DEVICES: '',
    PI_CODING_AGENT_DIR: agentDir, PI_PROJECT_KANBAN_PYTHON: python,
    PI_PROJECT_KANBAN_ADAPTER: path.join(workflow, 'pi_kanban.py'), PI_PROJECT_KANBAN_ADAPTER_SHA256: hash(path.join(workflow, 'pi_kanban.py')),
    PI_PROJECT_STATE_BASE: path.join(project, 'board-state'), HERMES_HOME: path.join(project, 'hermes-home'),
    PI_SYSTEM_TOOL_PYTHON: python, PI_SYSTEM_TOOL_HELPER: path.join(candidate, 'runtime/adapters/pi/project-workflow/tool_knowledge.py'),
    PI_SYSTEM_TOOL_HELPER_SHA256: hash(path.join(candidate, 'runtime/adapters/pi/project-workflow/tool_knowledge.py')),
    PI_SYSTEM_TOOL_DATABASE: path.join(candidate, 'state/tool-knowledge.sqlite') });
  const profile = await makeProfile(label, exposure, project, agentDir,
    ['agent-capabilities.ts', 'system-tool-knowledge.ts', 'pi-kanban.ts', 'everyday-workflow.ts'].map(name => path.join(workflow, name)));
  profile.project = project; profile.skill = skill;
  await tool(profile, 'project_admit', { project_root: project, initialize: true,
    native_authority: 'Owner authorized isolated native MCP qualification', target: 'Synthetic readiness gates', why: 'Verify discovery is distinct from memory retrieval' });
  await profile.session.extensionRunner.emitInput('Inspect only the synthetic native MCP readiness task. Do not execute a worker or accept the root outcome.', undefined, 'interactive');
  const pending = (await tool(profile, 'kanban_intake_status', {})).details.result.pending;
  await tool(profile, 'kanban_intake_route', { source_id: pending.at(-1).id,
    parts: [{ kind: 'task', summary: 'Qualify synthetic memory readiness without worker execution', execute: true }] });
  return profile;
}
async function nonMemoryReadiness(profile) {
  await tool(profile, 'agent_capabilities', {}); await tool(profile, 'system_tool_query', { terms: 'memory MCP' });
  await tool(profile, 'project_knowledge_query', { terms: 'native memory readiness' }); await tool(profile, 'read', { path: profile.skill });
  for (let i = 0; i < 32; i++) {
    const result = await tool(profile, 'project_context', { path: profile.project });
    await profile.session.extensionRunner.emitContext([structuredClone(profile.lastMessage)]);
    if (!result.details.remaining_reads.length) return;
  }
  assert.fail('Project context did not finish within its existing bound');
}
async function admission(profile) {
  const result = await profile.session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: `admission-${++callSequence}`, toolName: 'workflow_step',
    input: { objective: 'Admission only; no worker executed', cwd: profile.project,
      action: [python, '-c', 'raise SystemExit(0)'], verify: [python, '-c', 'raise SystemExit(0)'], outputs: ['not-created.txt'] } });
  trace.push({ profile: profile.label, admission: result || { block: false } }); return result;
}
let startedHub = false;
try {
  const status = hub('status'); assert.ok(['stopped', 'running'].includes(status.status));
  if (status.status === 'stopped') { const running = hub('start'); assert.equal(running.status, 'running'); assert.equal(running.owned, true); startedHub = true; }
  Object.assign(process.env, normalEnvironment, { PI_PROJECT_KANBAN_PYTHON: python,
    PI_PROJECT_KANBAN_ADAPTER: path.join(candidate, 'runtime/adapters/pi/project-workflow/pi_kanban.py'),
    PI_PROJECT_KANBAN_ADAPTER_SHA256: hash(path.join(candidate, 'runtime/adapters/pi/project-workflow/pi_kanban.py')) });
  const direct = await makeProfile('current-source-eight-direct', 'direct', home, path.join(candidate, 'agent'), candidateSettings.extensions);
  const directMeasurement = await measureSchemas(direct);
  check('all-eight-current-source-extensions-native-direct-baseline', requiredActive(direct), { count: directMeasurement.active_count });
  check('current-generated-posture-reaches-actual-session-prompt', direct.session.systemPrompt.includes(fs.readFileSync(path.join(candidate, 'agent/APPEND_SYSTEM.md'), 'utf8').trim()));
  await close(direct);
  const deferred = await makeProfile('current-source-eight-deferred', 'deferred', home, path.join(candidate, 'agent'), candidateSettings.extensions);
  const deferredMeasurement = await measureSchemas(deferred);
  check('deferred-keeps47-registered-and-custom-gates-active', requiredActive(deferred));
  check('deferred-reduces-matched-provider-schema-bytes', deferredMeasurement.provider_schema_bytes < directMeasurement.provider_schema_bytes,
    { baseline: directMeasurement.provider_schema_bytes, deferred: deferredMeasurement.provider_schema_bytes });
  await discover(deferred); const loadedMeasurement = await measureSchemas(deferred);
  check('exact-name-discovery-adds-only-canonical-search', loadedMeasurement.active_count === deferredMeasurement.active_count + 1);
  await close(deferred);
  for (const exposure of ['deferred', 'direct']) {
    const profile = await gateProfile(`current-gates-${exposure}`, exposure); await nonMemoryReadiness(profile);
    check(`${exposure}-memory-required-before-discovery`, (await admission(profile))?.block === true);
    if (exposure === 'deferred') await discover(profile);
    check(`${exposure}-metadata-discovery-does-not-count-memory`, (await admission(profile))?.block === true);
    const statusName = 'mcp__mempalace__mempalace_status'; if (exposure === 'deferred') await discover(profile, statusName);
    await tool(profile, statusName, {});
    check(`${exposure}-different-real-MCP-tool-does-not-count-search`, (await admission(profile))?.block === true);
    const missing = await tool(profile, 'mcp__mempalace__mempalace_search', {}, true);
    check(`${exposure}-actual-SDK-or-MCP-error-does-not-unlock`, Boolean(missing.thrown || missing.isError) && (await admission(profile))?.block === true,
      { result: missing });
    const bad = await tool(profile, 'mcp__mempalace__mempalace_search', { query, wing: '../invalid-synthetic-wing', limit: 5 }, true);
    const errorText = (bad.content || []).filter(block => block.type === 'text').map(block => block.text).join('\n');
    const afterError = await admission(profile);
    check(`${exposure}-real-search-error-payload-does-not-unlock`, Boolean(bad.thrown || bad.isError || /"error"\s*:/.test(errorText)) && afterError?.block === true,
      { result: bad, admission: afterError || { block: false } });
    // Reset the readiness flags after the negative case, so positive retrieval
    // is independently responsible for opening the next admission.
    await profile.session.reload();
    await profile.session.extensionRunner.getCommand('mcp').handler('', profile.session.extensionRunner.createCommandContext());
    await nonMemoryReadiness(profile);
    if (exposure === 'deferred' && !profile.session.getActiveToolNames().includes('mcp__mempalace__mempalace_search')) await discover(profile);
    check(`${exposure}-fresh-memory-required-after-error-reset`, (await admission(profile))?.block === true);
    const found = await tool(profile, 'mcp__mempalace__mempalace_search', { query, wing: 'pi-sessions', limit: 5 });
    check(`${exposure}-canonical-search-recalls-distinct-synthetic-body`, JSON.stringify(found.content).includes(expectedBody));
    check(`${exposure}-actual-memory-search-opens-ready-gate`, !(await admission(profile))?.block);
    if (exposure === 'deferred') {
      await profile.session.reload();
      await profile.session.extensionRunner.getCommand('mcp').handler('', profile.session.extensionRunner.createCommandContext());
      check('reload-keeps-required-custom-gates-active', requiredActive(profile));
      check('reload-resets-discovery-before-admission', (await admission(profile))?.block === true);
      await nonMemoryReadiness(profile);
      check('reloaded-active-search-alone-does-not-count-memory', (await admission(profile))?.block === true);
      if (!profile.session.getActiveToolNames().includes('mcp__mempalace__mempalace_search')) await discover(profile);
      await tool(profile, 'mcp__mempalace__mempalace_search', { query, wing: 'pi-sessions', limit: 5 });
      check('reload-real-search-restores-admission', !(await admission(profile))?.block);
      await profile.session.extensionRunner.getCommand('mcp').handler('reconnect mempalace', profile.session.extensionRunner.createCommandContext());
      if (!profile.session.getActiveToolNames().includes('mcp__mempalace__mempalace_search')) await discover(profile);
      const reconnected = await tool(profile, 'mcp__mempalace__mempalace_search', { query, wing: 'pi-sessions', limit: 5 });
      check('native-reconnect-search-and-custom-gates-work', JSON.stringify(reconnected.content).includes(expectedBody) && requiredActive(profile));
    }
    check(`${exposure}-native-extension-errors-visible`, profile.errors.length === 0, { errors: profile.errors }); await close(profile);
  }
} catch (error) {
  checks.push({ name: 'qualification-execution', passed: false, unknown: true, error: String(error?.stack || error) });
} finally {
  for (const profile of profiles) try { await close(profile); } catch (error) { check('native-MCP-shutdown', false, { error: String(error) }); }
  if (startedHub) try { check('exact-owned-hub-stopped', hub('stop').status === 'stopped'); } catch (error) { check('exact-owned-hub-stopped', false, { error: String(error) }); }
  check('home-configuration-hashes-unchanged', JSON.stringify(hashes()) === JSON.stringify(before), { before, after: hashes() });
  const failed = checks.filter(item => !item.passed);
  const receipt = { schema: 'pi-mcp-exposure-native/v1', status: failed.length ? 'failed' : 'passed', fixture,
    checks, measurements, source_manifest_sha256: hash(path.join(fixture, 'source-manifest.json')), native_probe_sha256: hash(new URL(import.meta.url)),
    provider_serializer_sha256: hash(path.join(aiDist, 'api/openai-completions.js')), model, provider_http: measurements.reduce((n, item) => n + item.provider_http, 0),
    model_calls: 0, workers_executed: 0, observer_hooks_emitted: 0, query, expected_body: expectedBody, elapsed_ms: Date.now() - started,
    candidate_mcp: { exposure: candidateMcp.exposure, description: candidateMcp.description },
    candidate_runtime_manifest_sha256: hash(path.join(candidate, 'runtime/runtime-manifest.json')),
    source_environment_sha256: hash(path.join(source, 'harness/home.py')),
    candidate_settings_sha256: hash(path.join(candidate, 'agent/settings.json')),
    candidate_mcp_config_sha256: hash(path.join(candidate, 'agent/mcp.json')),
    candidate_prompt_sha256: hash(path.join(candidate, 'agent/APPEND_SYSTEM.md')),
    scope: 'Current-source offline scaffold eight-extension schema and prompt qualification plus copied current four-extension project/intake/memory gates; unchanged installed home dependencies and synthetic-palace transport are borrowed in memory. This is not a fresh package install. Real native MCP and CPU retrieval only. No private palace, model HTTP, inference, observer input, production configuration edits or workflow execution. Gate-profile input reaches only four project extensions. Provider onPayload stops before HTTP.' };
  writeJson(path.join(fixture, 'native-trace.json'), trace); writeJson(path.join(fixture, 'receipt.json'), receipt);
  console.log(JSON.stringify(receipt, null, 2)); process.exitCode = failed.length ? 1 : 0;
}
