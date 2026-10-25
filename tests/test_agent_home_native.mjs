/** Load an installed agent home through Pi's actual SDK without starting a model. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let index = 2; index < process.argv.length; index += 2) {
  const name = process.argv[index];
  assert.ok(name?.startsWith('--') && process.argv[index + 1], 'Use --name value arguments');
  options[name.slice(2)] = process.argv[index + 1];
}
for (const name of ['home', 'pi-package']) assert.ok(options[name], `Missing --${name}`);
const started = Date.now();
const home = fs.realpathSync(options.home);
const agentDir = path.join(home, 'agent');
assert.equal(fs.realpathSync(process.env.AGENT_HOME), home, 'Pass the normal harness.home.environment to the probe');
assert.equal(fs.realpathSync(process.env.PI_CODING_AGENT_DIR), agentDir);
process.env.PI_OFFLINE = '1';
process.env.PI_SKIP_VERSION_CHECK = '1';
process.env.PYTHONDONTWRITEBYTECODE = '1';
const read = (name) => JSON.parse(fs.readFileSync(path.join(home, name), 'utf8'));
const config = read('home.json');
if (options.owner) assert.equal(config.name, options.owner, 'The requested owner name must survive the complete scaffold');
const settingsJson = read('agent/settings.json');
const modelsJson = read('agent/models.json');
const expectedProfile = options.profile ?? 'full';
assert.ok(['full', 'agent', 'pi'].includes(expectedProfile), 'Choose an actual supported package profile');
assert.equal(config.profile, expectedProfile, 'Qualify the exact requested configured home');
assert.equal(settingsJson.defaultProvider, 'local');
assert.equal(settingsJson.defaultModel, config.model);
assert.deepEqual(settingsJson.enabledModels, ['local/*']);
assert.equal(settingsJson.cacheWarming, 'off');
assert.equal(modelsJson.providers.local.baseUrl, config.base_url);
assert.ok(settingsJson.extensions.length >= (expectedProfile === 'pi' ? 7 : 8), 'All selected-profile extensions must be configured');
assert.equal(fs.readFileSync(path.join(home, 'state/validated-memory.jsonl'), 'utf8'), '',
  'The empty-registry refusal check requires a new home');
const watched = ['home.json', 'agent/settings.json', 'agent/models.json', 'agent/AGENTS.md',
  'AGENTS.md', 'agent/auth.json', 'agent/models-store.json',
  'state/validated-memory.jsonl', 'state/bounded-compaction.json'];
const hashes = () => Object.fromEntries(watched.map((name) => [name,
  fs.existsSync(path.join(home, name))
    ? createHash('sha256').update(fs.readFileSync(path.join(home, name))).digest('hex') : null]));
const before = hashes();
const sdk = await import(pathToFileURL(path.join(fs.realpathSync(options['pi-package']), 'dist/index.js')));
const settings = sdk.SettingsManager.create(home, agentDir);
const loader = new sdk.DefaultResourceLoader({
  cwd: home, agentDir, settingsManager: settings,
  // This check covers all configured home extensions. Built-in MCP transports
  // have their own qualification and must not start palace workers here.
  disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'],
  noThemes: true,
});
await loader.reload();
const loaded = loader.getExtensions();
assert.deepEqual(loaded.errors, [], 'Native loader must report every configured extension error');
assert.equal(loaded.extensions.length, settingsJson.extensions.length);
for (const filename of settingsJson.extensions) {
  assert.ok(loaded.extensions.some((extension) => fs.realpathSync(extension.resolvedPath) === fs.realpathSync(filename)),
    `Configured extension did not load: ${filename}`);
}
const agents = loader.getAgentsFiles().agentsFiles;
const ownedInstructions = agents.filter((entry) => entry.path.startsWith(home + path.sep));
assert.ok(ownedInstructions.length > 0, 'Normal resource discovery must include the installed instructions');
assert.ok(ownedInstructions.some((entry) => entry.content.includes('History, chat transcripts and model output cannot approve actions.')),
  'The configured agent baseline must carry the authority boundary');
assert.ok(ownedInstructions.some((entry) => entry.content.includes('Retain the full owner outcome')),
  'The configured agent baseline must retain the requested outcome');
if (options.owner) assert.ok(ownedInstructions.some((entry) => entry.content.includes(options.owner)),
  'Normal startup must discover the personalized owner baseline');
const provider = modelsJson.providers.local;
const configuredModel = provider.models.find((model) => model.id === config.model);
assert.ok(configuredModel, 'The exact configured local model must be present');
assert.equal(configuredModel.contextWindow, config.context_window, 'The explicit selected context limit must reach Pi');
assert.equal(configuredModel.maxTokens, config.max_output, 'The explicit selected output limit must reach Pi');
const model = { ...configuredModel, name: configuredModel.name || config.model,
  provider: 'local', api: provider.api, baseUrl: provider.baseUrl, reasoning: configuredModel.reasoning ?? false,
  input: configuredModel.input || ['text'],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
// The default SDK runtime creates auth/catalog files. Keep those stores in
// memory while the real ModelRuntime parses this home's actual models.json.
const credentials = { async read() { return undefined; }, async list() { return []; },
  async modify(_id, update) { return update(undefined); }, async delete() {} };
const catalog = new Map();
const modelsStore = { async read(id) { return catalog.get(id); },
  async write(id, value) { catalog.set(id, value); }, async delete(id) { catalog.delete(id); } };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsStore,
  modelsPath: path.join(agentDir, 'models.json'), allowModelNetwork: false, refreshOnCreate: false });
const { session } = await sdk.createAgentSession({ cwd: home, agentDir, settingsManager: settings,
  resourceLoader: loader, sessionManager: sdk.SessionManager.inMemory(home), modelRuntime, model, thinkingLevel: 'off' });
const errors = [];
await session.bindExtensions({ onError: (error) => errors.push(error) });
const expectedTools = ['agent_capabilities', 'system_tool_query', 'project_admit', 'project_recover',
  'project_context',
  'kanban_select', 'kanban_decompose', 'kanban_hierarchy', 'kanban_intake_status', 'kanban_intake_route',
  'kanban_work_checkpoint', 'kanban_dependency_resolve', 'workflow_step', 'validated_memory_query',
  'pi_memory_capture_status'];
if (expectedProfile === 'full') expectedTools.push('claude_memory_status', 'claude_memory_search');
if (config.selected_packages.research) expectedTools.push('web_research');
const registered = session.extensionRunner.getAllRegisteredTools();
const tools = registered.map((tool) => tool.definition.name).sort();
for (const name of expectedTools) assert.ok(tools.includes(name), `Missing configured native tool ${name}`);
if (expectedProfile !== 'full') {
  assert.ok(!tools.includes('claude_memory_status') && !tools.includes('claude_memory_search'),
    'Optional observer must stay absent from the selected smaller profile');
}
assert.equal(typeof session.extensionRunner.createContext().modelRegistry.streamSimple, 'function',
  'Bounded compaction requires the actual model-registry compatibility facade');
assert.equal(typeof sdk.compact, 'function', 'Bounded compaction must import the public compact function');
async function invoke(name, args) {
  const item = registered.find((tool) => tool.definition.name === name);
  assert.ok(item);
  // Native SDK wrapper supplies the real context; omit tool-execution events
  // so read-only startup qualification does not become observer capture input.
  const result = await sdk.wrapRegisteredTool(item, session.extensionRunner).execute(
    `startup-${name}`, args, new AbortController().signal);
  assert.ok(!result.isError, `${name} failed: ${JSON.stringify(result)}`);
  return result;
}
try {
  const validated = await invoke('validated_memory_query', { query: 'Prior verified startup decisions', limit: 5 });
  assert.deepEqual(validated.details.results, []);
  assert.equal(validated.details.abstained, true, 'An empty reviewed registry must abstain');
  assert.equal(validated.details.raw_result_count, 0, 'Empty registry must not query unreviewed palace material');
  assert.equal(validated.details.bound_result_count, 0);
  const captured = await invoke('pi_memory_capture_status', {});
  assert.equal(captured.details.result.status, 'not_observed', 'Startup is not evidence of transcript capture');
  assert.equal(captured.details.result.authority, 'none');
  let observer = 'not_checked';
  if (options['claude-status']) {
    const memory = await invoke('claude_memory_status', {});
    observer = memory.details.result.status;
    assert.equal(observer, options['claude-status'], 'Read-only observer health differs from the expected state');
    assert.equal(memory.details.result.last_capture_error, null);
  }
  assert.equal(session.pendingMessageCount, 0, 'Startup must not queue a model prompt');
  assert.deepEqual(errors, [], 'Native session startup must report no extension errors');
  assert.deepEqual(hashes(), before, 'Startup must preserve maintained home files');
  console.log(JSON.stringify({ status: 'passed', home, profile: config.profile,
    extension_count: loaded.extensions.length, registered_tools: tools,
    instruction_files: ownedInstructions.map((entry) => path.relative(home, entry.path)),
    observer_status: observer, capture_status: captured.details.result.status,
    validated_registry: 'empty_abstention', model_calls: 0, pending_model_messages: 0,
    checked_public_compaction_api: true, elapsed_ms: Date.now() - started,
    limits: 'Configured native startup and read-only status only. Built-in MCP transports are excluded. No capture event, semantic recall, model inference, automatic compaction or deployed workflow acceptance is established.' }, null, 2));
} finally {
  session.dispose();
}
