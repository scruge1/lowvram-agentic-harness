/** Actual Pi ModelRuntime -> AgentSession -> OpenAI serializer; no network. */
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
for (const name of ['source', 'pi-package', 'python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
const started = Date.now(), source = fs.realpathSync(options.source), piPackage = fs.realpathSync(options['pi-package']);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-model-profiles-'));
const sha = value => createHash('sha256').update(value).digest('hex');
const writeJson = (name, value) => fs.writeFileSync(path.join(fixture, name), JSON.stringify(value, null, 2) + '\n');
const prompt = 'PUBLIC_PROFILE_WIRE_ONLY: inspect supplied public hardware facts and save the requested report.';
const checks = [], captures = [], environment = { ...process.env, PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1' };
const originalFetch = globalThis.fetch;
let active;
// Trap the final Request after the real OpenAI SDK serializes it. This trap never
// calls the original fetch and cannot open a network connection.
globalThis.fetch = async (input, init) => {
  assert.ok(active, 'An unexpected request occurred outside the current native session');
  const request = new Request(input, init);
  const body = await request.text();
  active.fetches.push({ url: request.url, method: request.method, body_sha256: sha(body), payload: JSON.parse(body) });
  throw Object.assign(new Error('PROFILE_WIRE_TEST_TRANSPORT_ABORT'), { name: 'AbortError' });
};
process.env.PI_OFFLINE = '1';
process.env.PI_SKIP_VERSION_CHECK = '1';
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(piPackage, 'package.json'))).version, '1.4.0');
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };

async function capture(profile) {
  const home = path.join(fixture, profile);
  const scaffold = spawnSync(options.python, ['-B', '-c',
    'import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from harness.home import scaffold;print(json.dumps(scaffold(Path(sys.argv[2]),source=Path(sys.argv[1]),profile="pi",base_url="http://127.0.0.1:9/v1",model="qwen3.8-27b-q8-0",name="PublicProfileOwner",offline=True,context_window=32768,max_output=4096,model_profile=sys.argv[3])))',
    source, home, profile], { cwd: fixture, env: environment, encoding: 'utf8', timeout: 30000 });
  assert.equal(scaffold.status, 0, scaffold.stderr + scaffold.stdout);
  const agentDir = path.join(home, 'agent');
  const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
  const modelsPath = path.join(agentDir, 'models.json');
  const modelsJson = JSON.parse(fs.readFileSync(modelsPath));
  const settingsJson = JSON.parse(fs.readFileSync(path.join(agentDir, 'settings.json')));
  const before = sha(fs.readFileSync(modelsPath));
  assert.equal(settingsJson.defaultThinkingLevel, 'off');
  const store = new Map();
  const modelsStore = { async read(id) { return store.get(id); }, async write(id, value) { store.set(id, value); }, async delete(id) { store.delete(id); } };
  const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsStore, modelsPath,
    allowModelNetwork: false, refreshOnCreate: false });
  const available = await modelRuntime.getAvailable('local');
  const model = available.find(value => value.id === config.model);
  assert.ok(model, 'The native runtime must parse and authenticate the generated local definition');
  assert.equal(model.provider, 'local');
  assert.equal(model.contextWindow, 32768);
  assert.equal(model.maxTokens, 4096);
  // Keep both sessions' request contents identical. Harness hooks and MCP are
  // covered separately; this test isolates the native transport profile.
  const result = { profile, home, config: { model: config.model, context_window: config.context_window, max_output: config.max_output },
    definition: modelsJson.providers.local.models[0], model, payloads: [], fetches: [], errors: [] };
  active = result;
  const settings = sdk.SettingsManager.inMemory({ ...settingsJson, retry: { enabled: false } });
  const loader = new sdk.DefaultResourceLoader({ cwd: fixture, agentDir, settingsManager: settings,
    noExtensions: true, noThemes: true, noSkills: true, noPromptTemplates: true,
    disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'],
    systemPromptOverride: () => 'Native model transport qualification. Do not execute a tool.',
    agentsFilesOverride: () => ({ agentsFiles: [] }),
    extensionFactories: [pi => pi.on('before_provider_request', event => {
      result.payloads.push(JSON.parse(JSON.stringify(event.payload)));
    })] });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const { session } = await sdk.createAgentSession({ cwd: fixture, agentDir, modelRuntime, model,
    settingsManager: settings, resourceLoader: loader, sessionManager: sdk.SessionManager.inMemory(fixture),
    thinkingLevel: settingsJson.defaultThinkingLevel });
  const timer = setTimeout(() => { void session.abort(); }, 15000);
  try {
    await session.bindExtensions({ onError: error => result.errors.push(String(error)) });
    assert.equal(session.thinkingLevel, 'off');
    result.active_tools = session.getActiveToolNames();
    result.default_tools = settingsJson.defaultTools;
    try { await session.prompt(prompt); } catch (error) { result.prompt_error = String(error); }
    assert.equal(result.payloads.length, 1, 'One native onPayload callback must precede transport');
    assert.equal(result.fetches.length, 1, 'Only one attempted transport, intercepted before network');
    assert.equal(result.fetches[0].url, 'http://127.0.0.1:9/v1/chat/completions');
    assert.deepEqual(result.fetches[0].payload, result.payloads[0], 'The final serialized body must match the native payload callback');
    assert.equal(result.payloads[0].model, config.model);
    assert.equal(result.payloads[0].max_tokens ?? result.payloads[0].max_completion_tokens, 4096);
    assert.ok(result.payloads[0].messages.some(message => JSON.stringify(message).includes(prompt)));
    assert.deepEqual(result.errors, []);
    assert.equal(sha(fs.readFileSync(modelsPath)), before, 'Native parsing/request must preserve generated model definitions');
  } finally {
    clearTimeout(timer);
    await session.dispose();
    active = undefined;
  }
  captures.push(result);
  writeJson(profile + '.json', result);
  checks.push(profile + '-actual-runtime-session-serializer-and-fetch-trap');
  return result;
}

try {
  const generic = await capture('generic-local');
  const corrected = await capture('llama-cpp-qwen');
  assert.equal(generic.model.reasoning, false);
  assert.equal(corrected.model.reasoning, true);
  assert.equal(corrected.model.compat.thinkingFormat, 'qwen-chat-template');
  assert.equal(corrected.model.compat.supportsReasoningEffort, true);
  assert.equal(Object.hasOwn(generic.payloads[0], 'chat_template_kwargs'), false);
  assert.deepEqual(corrected.payloads[0].chat_template_kwargs, { enable_thinking: false, preserve_thinking: true });
  checks.push('generic-omits-qwen-thinking-control', 'explicit-profile-serializes-thinking-off');
  const { reasoning, compat, ...correctedDefinition } = corrected.definition;
  assert.deepEqual(correctedDefinition, generic.definition);
  assert.deepEqual(corrected.config, generic.config);
  assert.deepEqual(corrected.default_tools, generic.default_tools);
  assert.deepEqual(corrected.active_tools, generic.active_tools);
  // Native openai-completions.js:905 selects developer for reasoning models.
  // Preserve instruction contents and user roles; assert this exact native role
  // transition rather than concealing it in a general payload normalization.
  assert.equal(generic.payloads[0].messages[0].role, 'system');
  assert.equal(corrected.payloads[0].messages[0].role, 'developer');
  assert.deepEqual(corrected.payloads[0].messages[0].content, generic.payloads[0].messages[0].content);
  assert.deepEqual(corrected.payloads[0].messages.slice(1), generic.payloads[0].messages.slice(1));
  const { chat_template_kwargs, messages: correctedMessages, ...correctedPayload } = corrected.payloads[0];
  const { messages: genericMessages, ...genericPayload } = generic.payloads[0];
  assert.deepEqual(correctedPayload, genericPayload);
  checks.push('native-reasoning-model-developer-instruction-role-with-same-content',
    'model-caps-user-messages-task-defaults-and-other-payload-fields-preserved');
  const receipt = { status: 'passed', fixture, checks, elapsed_ms: Date.now() - started,
    source, test_sha256: sha(fs.readFileSync(new URL(import.meta.url))),
    source_sha256: Object.fromEntries(['harness/model_profiles.py', 'harness/home.py'].map(name => [name, sha(fs.readFileSync(path.join(source, name)))])),
    captured_payloads: captures.map(value => ({ profile: value.profile,
      on_payload_sha256: sha(JSON.stringify(value.payloads[0])),
      final_body_sha256: value.fetches[0].body_sha256,
      instruction_role: value.payloads[0].messages[0].role,
      chat_template_kwargs: value.payloads[0].chat_template_kwargs ?? null })),
    payload_differences: ['chat_template_kwargs', 'messages[0].role'],
    attempted_transports: captures.reduce((sum, value) => sum + value.fetches.length, 0),
    network_requests: 0, model_inferences: 0,
    limits: 'New synthetic generations captured before network. The earlier failed real run payload remains unknown. This test proves native transport serialization, not model quality or hardware fit.' };
  writeJson('receipt.json', receipt);
  console.log(JSON.stringify(receipt, null, 2));
} catch (error) {
  writeJson('failure.json', { status: 'failed', fixture, checks, error: String(error), stack: error.stack });
  throw error;
} finally {
  globalThis.fetch = originalFetch;
}
