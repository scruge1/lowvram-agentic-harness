/** Actual Pi1.4 lifecycle and child payloads; synthetic SSE, zero model/HTTP. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1]);
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['source', 'pi-package', 'python', 'fixture-parent']) assert.ok(options[name], name);
const source = fs.realpathSync(options.source), pkg = fs.realpathSync(options['pi-package']);
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg, 'package.json'))).version, '1.4.0');
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-observer-summary-'));
const project = path.join(fixture, 'project'), agentDir = path.join(fixture, 'agent'), home = path.join(fixture, 'home');
const fake = path.join(fixture, 'transport', 'harness');
for (const dir of [project, agentDir, home, fake]) fs.mkdirSync(dir, { recursive: true });
fs.writeFileSync(path.join(project, 'fixture.txt'), 'Current synthetic read result.\n');
fs.writeFileSync(path.join(fake, '__init__.py'), '');
fs.writeFileSync(path.join(fake, 'claude_memory.py'), `import json,sys\nfrom pathlib import Path\nargs=sys.argv[1:];home=Path(args[args.index('--home')+1]);payload=sys.stdin.read()\nwith (home/'calls.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'event':args[-1],'payload':json.loads(payload) if payload else None})+'\\n')\nprint(json.dumps({'status':'synthetic_transport_only'}))\n`);
const extension = path.join(fixture, 'claude-memory.ts');
fs.copyFileSync(path.join(source, 'adapters/pi/claude-memory.ts'), extension);
const savedEnv = { ...process.env };
Object.assign(process.env, { AGENT_HOME: home, AGENT_HOME_PYTHON: options.python,
  PYTHONPATH: path.dirname(fake), PI_CODING_AGENT_DIR: agentDir, PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1' });
const sdk = await import(pathToFileURL(path.join(pkg, 'dist/index.js')));
const require = createRequire(path.join(pkg, 'package.json'));
const aiPackage = require.resolve.paths('@earendil-works/pi-ai').map(root => path.join(root, '@earendil-works/pi-ai/package.json')).find(file => fs.existsSync(file));
const provider = await import(pathToFileURL(path.join(path.dirname(aiPackage), 'dist/api/openai-completions.js')));
let mode = 'current', http = 0, syntheticRequests = 0, sequence = 0;
const checks = [], errors = [], events = [];
const settings = sdk.SettingsManager.inMemory({ extensions: [extension], defaultTools: ['read'], cacheWarming: 'off',
  retry: { enabled: false }, compaction: { enabled: false } });
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
  disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'], noSkills: true, noPromptTemplates: true, noThemes: true,
  extensionFactories: [pi => {
    pi.on('message_end', event => {
      if (event.message.role !== 'assistant') return;
      if (event.message.content.some(part => part.type === 'toolCall')) return;
      if (mode === 'empty') return { message: { ...event.message, content: [{ type: 'thinking', thinking: 'NEVER_FORWARD_THOUGHTS' }] } };
      if (mode === 'error') return { message: { ...event.message, stopReason: 'error', errorMessage: 'Synthetic failure',
        content: [{ type: 'text', text: 'NEVER_FORWARD_FAILED_BODY' }] } };
      if (mode === 'current') return { message: { ...event.message, content: [
        { type: 'thinking', thinking: 'NEVER_FORWARD_THOUGHTS' },
        { type: 'text', text: 'Actual current replacement.' }, { type: 'text', text: 'Second plain block.' }] } };
    });
    pi.on('agent_settled', (event, ctx) => events.push({ aborted: event.aborted, session: ctx.sessionManager.getSessionId() }));
  }] });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const model = { id: 'fixture-no-inference', provider: 'fixture-local', name: 'No inference', api: 'openai-completions',
  baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false, contextWindow: 32768, maxTokens: 4096,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const modelsPath = path.join(fixture, 'models.json');
fs.writeFileSync(modelsPath, JSON.stringify({ providers: { 'fixture-local': {
  api: model.api, baseUrl: model.baseUrl, apiKey: 'synthetic-not-a-credential', models: [model] } } }));
const store = new Map();
const modelsStore = { async read(id) { return store.get(id); }, async write(id, value) { store.set(id, value); }, async delete(id) { store.delete(id); } };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsStore, modelsPath, allowModelNetwork: false, refreshOnCreate: false });
const manager = sdk.SessionManager.create(project, path.join(fixture, 'sessions'));
manager.appendMessage({ role: 'assistant', content: [{ type: 'text', text: 'NEVER_FORWARD_OLD_HISTORY' }],
  api: model.api, provider: model.provider, model: model.id, stopReason: 'stop', timestamp: Date.now() });
const { session } = await sdk.createAgentSession({ cwd: project, agentDir, settingsManager: settings, resourceLoader: loader,
  sessionManager: manager, modelRuntime, model, tools: ['read'], thinkingLevel: 'off' });
await session.bindExtensions({ onError: error => errors.push(String(error)) });
const previousFetch = globalThis.fetch;
globalThis.fetch = async () => { http++; throw new Error('FORBIDDEN_HTTP'); };
session.agent.getApiKey = () => 'synthetic-not-a-credential';
session.agent.streamFunction = (selected, context, opts) => provider.stream(selected, context, { ...opts,
  apiKey: 'synthetic-not-a-credential', maxRetries: 0,
  fetch: async (_input, init) => {
    syntheticRequests++;
    const request = JSON.parse(init.body), last = request.messages.at(-1);
    const call = mode === 'current' && last.role !== 'tool';
    const delta = call ? { role: 'assistant', tool_calls: [{ index: 0, id: `read-${++sequence}`, type: 'function',
      function: { name: 'read', arguments: JSON.stringify({ path: path.join(project, 'fixture.txt') }) } }] }
      : { role: 'assistant', content: 'Raw current provider body.' };
    const id = `fixture-${syntheticRequests}`;
    const chunks = [{ id, object: 'chat.completion.chunk', created: 0, model: model.id,
      choices: [{ index: 0, delta, finish_reason: null }] }, { id, object: 'chat.completion.chunk', created: 0, model: model.id,
      choices: [{ index: 0, delta: {}, finish_reason: call ? 'tool_calls' : 'stop' }] }];
    return new Response(chunks.map(value => 'data: ' + JSON.stringify(value) + '\n\n').join('') + 'data: [DONE]\n\n',
      { headers: { 'content-type': 'text/event-stream' } });
  } });
const calls = () => fs.readFileSync(path.join(home, 'calls.jsonl'), 'utf8').trim().split('\n').map(line => JSON.parse(line));
const summaries = () => calls().filter(call => call.event === 'summarize');
try {
  await session.prompt('Read fixture.txt and report only the current result.');
  assert.equal(summaries().length, 1);
  const summary = summaries()[0].payload;
  assert.equal(summary.last_assistant_message, 'Actual current replacement.\nSecond plain block.');
  assert.equal(summary.sessionId, manager.getSessionId()); assert.equal(summary.cwd, project);
  assert.ok(!JSON.stringify(summary).includes('NEVER_FORWARD_'));
  const persisted = manager.getBranch().filter(entry => entry.type === 'message' && entry.message.role === 'assistant').at(-1).message;
  assert.equal(persisted.content.filter(part => part.type === 'text').map(part => part.text).join('\n'), summary.last_assistant_message);
  checks.push('final-hook-replacement-exact-current-plain-text-and-session');
  assert.equal(calls().filter(call => call.event === 'session-init').length, 1);
  assert.equal(calls().filter(call => call.event === 'observation').length, 1);
  checks.push('existing-native-input-and-read-observation-preserved');
  mode = 'empty';
  await session.prompt('Current run has no plain assistant text.');
  assert.equal(summaries().length, 1);
  assert.ok(manager.getBranch().some(entry => entry.type === 'custom' && entry.customType === 'claude-memory-capture/v1' && entry.data.status === 'held'));
  checks.push('empty-current-text-held-no-old-history-or-thoughts-fallback');
  mode = 'error';
  await session.prompt('Current run ends in a synthetic assistant error.');
  assert.equal(summaries().length, 1);
  checks.push('failed-current-assistant-text-held');
  // Exercise the supported event boundary directly as well as real prompt
  // lifecycle above. No fabricated persisted assistant message is introduced.
  await session.extensionRunner.emit({ type: 'agent_start' });
  await session.extensionRunner.emit({ type: 'agent_settled', aborted: true });
  assert.equal(summaries().length, 1);
  checks.push('explicit-aborted-boundary-never-enqueues-summary');
  const originalSession = manager.getSessionId(), originalFile = manager.getSessionFile();
  await session.extensionRunner.emit({ type: 'agent_start' });
  manager.newSession();
  await session.extensionRunner.emit({ type: 'agent_settled', aborted: false });
  assert.equal(summaries().length, 1);
  checks.push('session-drift-before-settlement-held');
  const queuedSession = manager.getSessionId(), args = { path: 'original-current-tool-input' };
  await session.extensionRunner.emit({ type: 'tool_execution_start', toolName: 'read', toolCallId: 'queued-binding', args });
  const response = { content: [{ type: 'text', text: 'original-current-tool-response' }] };
  const pending = session.extensionRunner.emit({ type: 'tool_execution_end', toolName: 'read', toolCallId: 'queued-binding', result: response, isError: false });
  args.path = 'MUTATED_AFTER_ENQUEUE'; response.content[0].text = 'MUTATED_AFTER_ENQUEUE'; manager.newSession();
  await pending;
  const queued = calls().filter(call => call.event === 'observation').at(-1).payload;
  assert.equal(queued.sessionId, queuedSession); assert.equal(queued.cwd, project);
  assert.equal(queued.toolInput.path, 'original-current-tool-input');
  assert.equal(queued.toolResponse.content[0].text, 'original-current-tool-response');
  checks.push('queued-session-cwd-and-payload-snapshot-preserved');
  assert.deepEqual(errors, []); assert.equal(http, 0);
  const result = { ok: true, fixture, checks, http, syntheticRequests,
    session_id: originalSession, session_file: originalFile,
    extension_sha256: createHash('sha256').update(fs.readFileSync(extension)).digest('hex'),
    limits: 'Actual Pi1.4 prompt/read/final-message persistence/settlement and Python child payload capture. Synthetic foreground SSE and inert child transport; zero HTTP/model/Claude-mem/Bun generation or target adoption. Abort case is direct native event-boundary control.' };
  fs.writeFileSync(path.join(fixture, 'result.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
} finally {
  await session.extensionRunner.emit({ type: 'session_shutdown' }); await session.dispose();
  globalThis.fetch = previousFetch;
  for (const key of Object.keys(process.env)) if (!(key in savedEnv)) delete process.env[key];
  Object.assign(process.env, savedEnv);
}
