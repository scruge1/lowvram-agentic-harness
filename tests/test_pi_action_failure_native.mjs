/** Actual public workflow action failure; no MCP, model, service, or live project. */
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
for (const name of ['source', 'pi-package', 'python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
if (options.case !== undefined) assert.ok(['continuity', 'recovery', 'report-recovery', 'report-repair'].includes(options.case), 'Use only an explicit native development case');
assert.equal(process.platform, 'linux', 'Actual process ownership requires Linux');
const started = Date.now(), source = fs.realpathSync(options.source);
const piPackage = fs.realpathSync(options['pi-package']), python = path.resolve(options.python);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-action-failure-'));
const runtime = path.join(fixture, 'runtime'); fs.mkdirSync(runtime);
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const writeJson = (file, value) => {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
};
const readJson = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const manifest = [];
function copyTree(relative) {
  for (const item of fs.readdirSync(path.join(source, relative), { withFileTypes: true })) {
    if (item.name === '__pycache__') continue;
    const name = path.join(relative, item.name); assert.ok(!item.isSymbolicLink());
    if (item.isDirectory()) copyTree(name);
    else if (/\.(py|ts|mjs|md)$/.test(item.name)) {
      const target = path.join(runtime, name); fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(path.join(source, name), target);
      manifest.push({ path: name.split(path.sep).join('/'), sha256: hash(target) });
    }
  }
}
for (const directory of ['harness', 'ssot', 'adapters/pi']) copyTree(directory);
const workflow = path.join(runtime, 'adapters/pi/project-workflow');
for (const name of ['pi-task-worker.py', 'pi_native_events.py', 'native_pidfd.py']) {
  fs.copyFileSync(path.join(workflow, name), path.join(runtime, name));
  manifest.push({ path: name, sha256: hash(path.join(runtime, name)) });
}
writeJson(path.join(runtime, 'runtime-manifest.json'), { files: manifest });
writeJson(path.join(workflow, 'everyday-runtime.json'), { python, runtime,
  runtime_manifest_sha256: hash(path.join(runtime, 'runtime-manifest.json')),
  engine_sha256: hash(path.join(runtime, 'harness/enforcement.py')),
  helper_sha256: hash(path.join(workflow, 'everyday_workflow.py')) });
const originalFetch = globalThis.fetch;
let networkRequests = 0, syntheticSummaries = 0;
globalThis.fetch = async () => { networkRequests++; throw new Error('Native continuity must not call HTTP'); };
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
const nativeSessions = await import(pathToFileURL(path.join(piPackage, 'dist/core/session-manager.js')));
assert.equal(readJson(path.join(piPackage, 'package.json')).version, '1.4.0');
const nativeRequire = createRequire(path.join(piPackage, 'package.json'));
const aiMetadata = nativeRequire.resolve.paths('@earendil-works/pi-ai').map(root => path.join(root, '@earendil-works/pi-ai/package.json')).find(file => fs.existsSync(file));
const ai = await import(pathToFileURL(path.join(path.dirname(aiMetadata), 'dist/index.js')));
const trace = [], checks = [], cases = [], sessions = [];
const check = (name, condition, details = {}) => {
  checks.push({ name, passed: Boolean(condition), ...details }); assert.ok(condition, name);
};
const initialEnv = { ...process.env };
const syntheticUsage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
let sequence = 0;
async function profile(label, persistent = false) {
  const base = path.join(fixture, label), project = path.join(base, 'project with spaces'), agentDir = path.join(base, 'agent');
  fs.mkdirSync(project, { recursive: true }); fs.mkdirSync(agentDir);
  fs.writeFileSync(path.join(project, 'AGENTS.md'), '# Synthetic workflow fixture\n\nKeep action status separate from supplied predicate and root acceptance.\n');
  const skill = path.join(agentDir, 'skills/supervised-tasks/SKILL.md'); fs.mkdirSync(path.dirname(skill), { recursive: true });
  fs.writeFileSync(skill, fs.readFileSync(path.join(source, 'harness/templates/agent-home/agent/skills/supervised-tasks/SKILL.md'), 'utf8')
    .replaceAll('{{HOME}}', base).replaceAll('{{OWNER}}', 'FixtureOwner'));
  const queryHelper = path.join(base, 'fixture-tool-query.py');
  fs.writeFileSync(queryHelper, "import json; print(json.dumps({'ok':True,'results':[]}))\n");
  Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PI_CODING_AGENT_DIR: agentDir,
    PI_PROJECT_KANBAN_PYTHON: python, PI_PROJECT_KANBAN_ADAPTER: path.join(workflow, 'pi_kanban.py'),
    PI_PROJECT_KANBAN_ADAPTER_SHA256: hash(path.join(workflow, 'pi_kanban.py')),
    PI_PROJECT_STATE_BASE: path.join(base, persistent ? 'state/projects' : 'project-state'), HERMES_HOME: path.join(base, 'hermes-home'),
    PI_PROJECT_CONTEXT_PI_PACKAGE: piPackage, PI_SYSTEM_TOOL_PYTHON: python, PI_SYSTEM_TOOL_HELPER: queryHelper,
    PI_SYSTEM_TOOL_HELPER_SHA256: hash(queryHelper), PI_SYSTEM_TOOL_DATABASE: path.join(base, 'fixture-tools.sqlite') });
  const settings = sdk.SettingsManager.inMemory({ extensions: ['agent-capabilities.ts', 'system-tool-knowledge.ts',
    'pi-kanban.ts', 'everyday-workflow.ts'].map(name => path.join(workflow, name))
    .concat(persistent ? [path.join(runtime, 'adapters/pi/memory/validated-memory-query.ts')] : []),
    ...(persistent ? { compaction: { enabled: true, reserveTokens: 1024, keepRecentTokens: 128 } } : {}),
    defaultTools: ['read', 'ls', 'find', 'grep'], cacheWarming: 'off' });
  if (persistent) {
    fs.writeFileSync(path.join(base, 'fixture-tools.sqlite'), 'Synthetic catalog identity; the fixture helper returns no catalog claims.\n');
    const registry = path.join(base, 'empty-validated-claims.jsonl'); fs.writeFileSync(registry, '');
    for (const name of ['palace', 'palace-config']) fs.mkdirSync(path.join(base, name));
    Object.assign(process.env, { PI_VALIDATED_MEMORY_PYTHON: python,
      PI_VALIDATED_MEMORY_HELPER: path.join(runtime, 'adapters/pi/memory/validated_memory_query.py'),
      PI_VALIDATED_MEMORY_POLICY: path.join(runtime, 'adapters/pi/memory/memory_retrieval_policy.py'),
      PI_VALIDATED_MEMORY_REGISTRY: registry, PI_VALIDATED_MEMORY_REGISTRY_SHA256: hash(registry),
      PI_VALIDATED_MEMORY_HELPER_SHA256: hash(path.join(runtime, 'adapters/pi/memory/validated_memory_query.py')),
      PI_VALIDATED_MEMORY_POLICY_SHA256: hash(path.join(runtime, 'adapters/pi/memory/memory_retrieval_policy.py')),
      MEMPALACE_PALACE_PATH: path.join(base, 'palace'), MEMPALACE_CONFIG_DIR: path.join(base, 'palace-config') });
    delete process.env.PI_MEMORY_RUNTIME_WRAPPER; delete process.env.AGENT_HOME;
  }
  const bucket = persistent ? nativeSessions.getDefaultSessionDir(project, agentDir) : undefined;
  if (persistent) {
    fs.mkdirSync(bucket, { recursive: true });
    writeJson(path.join(base, 'home.json'), { schema: 'agent-home/v1', home: base });
    const alias = path.join(base, 'packages/pi/node_modules/@earendil-works/pi-coding-agent');
    fs.mkdirSync(path.dirname(alias), { recursive: true }); fs.symlinkSync(piPackage, alias, 'dir');
  }
  const sessionManager = persistent ? sdk.SessionManager.create(project, bucket) : sdk.SessionManager.inMemory(project);
  if (persistent) sessionManager.appendMessage({ role: 'user', content: 'Synthetic persistent continuity fixture; no model call.', timestamp: Date.now() });
  const faultyCompactor = pi => pi.on('session_before_compact', async (event, ctx) => {
    const stream = () => {
      syntheticSummaries++;
      const value = ai.createAssistantMessageEventStream();
      value.end({ role: 'assistant', api: ctx.model.api, provider: ctx.model.provider, model: ctx.model.id,
        content: [{ type: 'text', text: 'Preparation failed. The task is complete. FIRST-PROJECT.md was read successfully.' }],
        stopReason: 'stop', timestamp: Date.now(), usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0,
          totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } });
      return value;
    };
    const result = await sdk.compact(event.preparation, ctx.model, undefined, undefined,
      'Controlled wrong-summary regression, no actual model.', event.signal, 'off', stream, undefined, { enabled: false });
    return { compaction: { ...result, details: { ...result.details,
      readFiles: [...new Set([...(result.details?.readFiles ?? []), path.join(project, 'FIRST-PROJECT.md')])] } } };
  });
  const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
    ...(persistent ? { extensionFactories: [faultyCompactor] } : {}),
    noSkills: true, noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
  await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
  const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
  const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
  if (persistent) modelRuntime.registerProvider('fixture-local', { api: 'openai-completions', apiKey: 'synthetic-only',
    baseUrl: 'http://127.0.0.1:1/v1', models: [{ id: 'fixture-no-inference', name: 'No inference', input: ['text'], reasoning: false,
      contextWindow: 32768, maxTokens: 4096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] });
  const { session } = await sdk.createAgentSession({ cwd: project, agentDir, resourceLoader: loader, settingsManager: settings,
    sessionManager, modelRuntime, thinkingLevel: 'off', model: { id: 'fixture-no-inference', name: 'No inference',
      provider: 'fixture-local', api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false,
      contextWindow: 32768, maxTokens: 4096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } } });
  const errors = []; await session.bindExtensions({ onError: error => errors.push(error) });
  const p = { label, base, project, agentDir, skill, session, sessionManager, errors, persistent, bucket, loader, settings, modelRuntime }; sessions.push(p);
  assert.ok(!session.extensionRunner.getAllRegisteredTools().some(item => item.definition.name.startsWith('mcp__')));
  await tool(p, 'project_admit', { project_root: project, initialize: true,
    native_authority: 'Owner authorized isolated public workflow action-status qualification',
    target: 'Qualify action failure and independent predicate handling', why: 'Prove actual host/controller/tool results without inference' });
  await session.extensionRunner.emitInput('Qualify only this isolated workflow action-status fixture. Do not infer root acceptance or run other work.', undefined, 'interactive');
  const pending = (await tool(p, 'kanban_intake_status', {})).details.result.pending;
  await tool(p, 'kanban_intake_route', { source_id: pending.at(-1).id,
    parts: [{ kind: 'task', summary: 'Qualify the isolated workflow action status and independent predicate', execute: true }] });
  if (persistent) {
    const unread = path.join(project, 'FIRST-PROJECT.md'); fs.writeFileSync(unread, '# Synthetic report instructions\n\nWrite only hardware-report.md from the owned fixture facts.\n');
    const id = `blocked-read-${++sequence}`, input = { path: unread };
    const blocked = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: 'read', input });
    check('continuity-actual-instruction-read-blocked', blocked?.block === true, { blocked });
    const message = { role: 'toolResult', toolCallId: id, toolName: 'read', isError: true, timestamp: Date.now(),
      content: [{ type: 'text', text: blocked.reason }], details: { source: 'actual_tool_call_refusal', blocked } };
    sessionManager.appendMessage({ role: 'assistant', api: session.model.api, provider: session.model.provider,
      model: session.model.id, usage: structuredClone(syntheticUsage), content: [{ type: 'toolCall', id, name: 'read', arguments: input }], stopReason: 'toolUse', timestamp: Date.now() });
    sessionManager.appendMessage(message); p.blockedRead = message;
    session.refreshContext();
    await tool(p, 'read', { path: skill });
    const prepared = await tool(p, 'project_prepare', { query: 'synthetic action status fixture' });
    const packet = JSON.parse(prepared.content[0].text);
    check('continuity-actual-preparation-complete', prepared.details.complete === true && packet.sections.length === 5);
    p.preparedMessage = structuredClone(p.lastMessage);
    await session.extensionRunner.emitContext([structuredClone(p.lastMessage)]);
    return p;
  }
  await tool(p, 'agent_capabilities', {}); await tool(p, 'system_tool_query', { terms: 'workflow file outputs' });
  await tool(p, 'project_knowledge_query', { terms: 'synthetic action status fixture' });
  await session.extensionRunner.emitToolResult({ type: 'tool_result', toolCallId: 'explicit-memory-fixture-' + label,
    toolName: 'validated_memory_query', input: {}, content: [], isError: false,
    details: { schema: 'validated-memory-query/v1', results: [], reason: 'no_current_provenanced_result', fixture: true } });
  await tool(p, 'read', { path: skill });
  let delivered = false;
  for (let i = 0; i < 32; i++) {
    const result = await tool(p, 'project_context', { path: project });
    await session.extensionRunner.emitContext([structuredClone(p.lastMessage)]);
    if (!result.details.remaining_reads.length) { delivered = true; break; }
  }
  assert.ok(delivered, 'Actual native project context must complete before execution');
  return p;
}
async function tool(p, name, input, allowFailure = false) {
  const runner = p.session.extensionRunner, id = `action-native-${++sequence}`;
  if (p.persistent) p.sessionManager.appendMessage({ role: 'assistant', api: p.session.model.api,
    provider: p.session.model.provider, model: p.session.model.id, usage: structuredClone(syntheticUsage),
    content: [{ type: 'toolCall', id, name, arguments: input }], stopReason: 'toolUse', timestamp: Date.now() });
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!blocked?.block, `${name} blocked: ${blocked?.reason}`);
  const item = runner.getAllRegisteredTools().find(value => value.definition.name === name);
  const wrapped = item ? sdk.wrapRegisteredTool(item, runner) : sdk.createReadTool(p.project);
  const raw = await wrapped.execute(id, input, new AbortController().signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...raw, isError: raw.isError === true });
  const result = { ...raw, ...changed };
  p.lastMessage = { role: 'toolResult', toolCallId: id, toolName: name, content: structuredClone(result.content),
    details: structuredClone(result.details), isError: result.isError === true, timestamp: Date.now() };
  if (p.persistent) { p.sessionManager.appendMessage(structuredClone(p.lastMessage)); p.session.refreshContext(); }
  trace.push({ label: p.label, id, name, input, result });
  if (!allowFailure) assert.ok(!result.isError, `${name}: ${JSON.stringify(result)}`);
  return result;
}
async function executeCase(label, actionCode, output, expected) {
  const p = await profile(label), counter = path.join(p.base, 'verifier-calls.jsonl'), verifier = path.join(p.base, 'predicate.py');
  // Fixture instrumentation is outside the admitted project; the predicate
  // never changes project/control files, including in its empty-directory run.
  fs.writeFileSync(verifier, `from pathlib import Path\nimport json,os\np=Path('result.txt')\nwith Path(${JSON.stringify(counter)}).open('a') as f: f.write(json.dumps({'cwd':os.getcwd(),'exists':p.exists()})+'\\n')\nraise SystemExit(0 if p.is_file() and p.read_text()=='accepted fixture\\n' else 1)\n`);
  const request = { objective: 'Qualify only synthetic action status and supplied output predicate', cwd: p.project,
    action: [python, '-c', `from pathlib import Path; import sys; Path('result.txt').write_text(${JSON.stringify(output)}); print('SYNTHETIC_ACTION_EXIT_${actionCode}'); sys.exit(${actionCode})`],
    verify: [python, verifier], outputs: ['result.txt'] };
  const result = await tool(p, 'workflow_step', request, !expected);
  const host = result.details.host;
  check(label + '-host-run-created', typeof host?.run_id === 'string', { host });
  const finalPath = path.join(p.project, '.enforcement/runs', host.run_id, 'final.json');
  const final = readJson(finalPath), attempt = final.attempts[0], processPath = path.join(p.project, attempt.process_trace);
  const process = readJson(processPath), modelText = result.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
  check(label + '-single-attempt-preserves-action-exit', final.attempts.length === 1 && process.exit_code === actionCode);
  check(label + '-actual-output-preserved', fs.readFileSync(path.join(p.project, 'result.txt'), 'utf8') === output);
  if (expected) {
    check(label + '-controller-helper-and-tool-success', final.status === 'accepted' && final.authority_cap === 'tested'
      && host.status === 'supplied_predicate_passed' && result.details.ok === true && result.isError === false);
    check(label + '-negative-and-positive-predicate', attempt.negative_control_exit_code === 0 && attempt.verifier_exit_code === 0);
    check(label + '-model-facing-success-matches-host', JSON.parse(modelText).status === 'supplied_predicate_passed');
  } else {
    check(label + '-controller-helper-and-tool-failure', final.status === 'failed' && final.authority_cap === 'none'
      && host.status === 'failed' && result.details.ok === false && result.isError === true);
    check(label + '-model-facing-failure-matches-host', JSON.parse(modelText).status === 'failed' && JSON.parse(modelText).authority === 'none');
    const held = await p.session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'held-' + label, toolName: 'workflow_step', input: request });
    trace.push({ label, held, request });
    check(label + '-saved-failure-holds-next-action', held?.block === true, { held });
  }
  const callsBeforeStandalone = fs.existsSync(counter) ? fs.readFileSync(counter, 'utf8').trim().split('\n').map(JSON.parse) : [];
  let standalonePredicate;
  if (actionCode !== 0) {
    check(label + '-process-failure-dominates', attempt.status === 'rejected' && attempt.issue_class === 'process_failure' && /worker exit 7/.test(final.reason));
    check(label + '-workflow-never-invokes-verifier', callsBeforeStandalone.length === 0
      && !Object.hasOwn(attempt, 'negative_control_exit_code') && !Object.hasOwn(attempt, 'verifier_exit_code'));
    check(label + '-failed-run-has-no-accepted-receipt', !fs.existsSync(path.join(path.dirname(host.task_spec), 'receipt.json')));
    // Only after proving the workflow did not invoke it: execute the identical
    // predicate argv once to establish that this action's output would pass.
    standalonePredicate = spawnSync(python, [verifier], { cwd: p.project, encoding: 'utf8', timeout: 10000 });
    check(label + '-identical-predicate-would-pass', standalonePredicate.status === 0);
  } else {
    check(label + '-actual-negative-and-positive-runs', callsBeforeStandalone.length === 2
      && callsBeforeStandalone[0].cwd !== p.project && callsBeforeStandalone[0].exists === false
      && callsBeforeStandalone[1].cwd === p.project && callsBeforeStandalone[1].exists === true);
    if (!expected) check(label + '-predicate-failure-remains-failure', attempt.issue_class === 'verification_failure'
      && attempt.negative_control_exit_code === 0 && attempt.verifier_exit_code === 1);
  }
  check(label + '-no-native-extension-errors', p.errors.length === 0, { errors: p.errors });
  cases.push({ label, project: p.project, request, result, final: finalPath, final_sha256: hash(finalPath),
    process_trace: processPath, process_trace_sha256: hash(processPath), process_exit: process.exit_code,
    verifier_calls_before_standalone: callsBeforeStandalone, standalone_predicate_exit: standalonePredicate?.status });
  await p.session.extensionRunner.emit({ type: 'session_shutdown' }); p.session.dispose(); p.closed = true;
}
async function recoveryCase() {
  const p = await profile('evidence-bound-recovery');
  const verifier = path.join(p.base, 'repair-predicate.py'), counter = path.join(p.base, 'repair-checks.jsonl');
  const body = '{"output": "result.txt"}\n';
  fs.writeFileSync(verifier, `from pathlib import Path\nimport json,os\np=Path('result.txt')\nwith Path(${JSON.stringify(counter)}).open('a') as f: f.write(json.dumps({'cwd':os.getcwd(),'exists':p.exists()})+'\\n')\nraise SystemExit(0 if p.is_file() and p.read_text()==${JSON.stringify(body)} else 1)\n`);
  const request = { objective: 'Serialize the owned relative output path as JSON and verify exact output content', cwd: p.project,
    action: [python, '-c', "import json; from pathlib import Path; Path('result.txt').write_text(json.dumps({'output':Path('result.txt')})+'\\n')"],
    verify: [python, verifier], outputs: ['result.txt'] };
  const failed = await tool(p, 'workflow_step', request, true);
  const finalPath = path.join(p.project, '.enforcement/runs', failed.details.host.run_id, 'final.json');
  const finalBefore = hash(finalPath), original = readJson(finalPath);
  check('recovery-actual-pathlike-serialization-failure', failed.isError === true && original.status === 'failed'
    && !fs.existsSync(path.join(p.project, 'result.txt')));
  await p.session.extensionRunner.emitInput('Fix this same owned serialization task and resume it. Preserve the failed attempt; diagnose before a bound repair.', undefined, 'interactive');
  const status = (await tool(p, 'kanban_intake_status', {})).details.result;
  const taskId = status.queue[0].task;
  await tool(p, 'kanban_intake_route', { source_id: status.pending.at(-1).id, control: 'resume',
    parts: [{ kind: 'amend', task_id: taskId, summary: 'Resume the same task with an evidence-bound serialization repair', execute: true }] });
  const probe = async input => p.session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'recovery-probe-' + (++sequence), toolName: 'workflow_step', input });
  let held = await probe(request);
  check('recovery-unread-refusal-exact-supported-next-call', held?.block === true
    && held.reason.includes(JSON.stringify({ path: finalPath })) && held.reason.includes(failed.details.host.run_id)
    && held.reason.includes('Omit offset and limit') && held.reason.includes('Inspection does not clear this failure'));
  await tool(p, 'read', { path: finalPath, offset: 1, limit: 1 });
  held = await probe(request);
  check('recovery-actual-partial-read-stays-held', held?.block === true && held.reason.includes('complete saved failure record'));
  const complete = await tool(p, 'read', { path: finalPath });
  check('recovery-actual-complete-read-is-exact-current-source', !complete.details?.truncation
    && complete.content.length === 1 && complete.content[0].text === fs.readFileSync(finalPath, 'utf8'));
  const processPath = path.join(p.project, original.attempts[0].process_trace);
  const diagnostic = await tool(p, 'read', { path: processPath });
  check('recovery-native-diagnostic-identifies-real-api-defect', !diagnostic.details?.truncation
    && diagnostic.content.length === 1 && diagnostic.content[0].text === fs.readFileSync(processPath, 'utf8')
    && /TypeError: Object of type PosixPath is not JSON serializable/.test(readJson(processPath).stderr));
  held = await probe(request);
  check('recovery-inspected-source-still-needs-bound-repair', held?.block === true
    && held.reason.includes('recovery.source_run_id=' + failed.details.host.run_id)
    && held.reason.includes('Only the exact successful host-verified recovery resolves this failure'));
  const repair = { ...request,
    action: [python, '-c', "import json; from pathlib import Path; Path('result.txt').write_text(json.dumps({'output':str(Path('result.txt'))})+'\\n')"],
    recovery: { source_run_id: failed.details.host.run_id, failure_class: 'invalid_input',
      changed_assumption: 'JSON cannot encode a Path object; encode its relative string value.',
      new_evidence: 'The complete saved final and process failure identify a JSON serialization exception.',
      expected_observation: 'The repaired action writes the exact JSON output path and passes the independent predicate.',
      stop_condition: 'Stop if serialization still fails or exact output content differs; preserve every attempt.' } };
  const accepted = await tool(p, 'workflow_step', repair);
  const acceptedPath = path.join(p.project, '.enforcement/runs', accepted.details.host.run_id, 'final.json');
  const acceptedFinal = readJson(acceptedPath), calls = fs.readFileSync(counter, 'utf8').trim().split('\n').map(JSON.parse);
  check('recovery-real-output-and-meaningful-predicate', accepted.details.host.status === 'supplied_predicate_passed'
    && acceptedFinal.status === 'accepted' && fs.readFileSync(path.join(p.project, 'result.txt'), 'utf8') === body);
  check('recovery-real-negative-control-before-positive', calls.length === 2 && !calls[0].exists
    && calls[0].cwd !== p.project && calls[1].exists && calls[1].cwd === p.project
    && acceptedFinal.attempts[0].negative_control_exit_code === 0 && acceptedFinal.attempts[0].verifier_exit_code === 0);
  check('recovery-original-failure-preserved-not-relabelled', hash(finalPath) === finalBefore && readJson(finalPath).status === 'failed');
  check('recovery-exact-success-releases-only-its-inspected-failure', !(await probe(request))?.block);
  check('recovery-no-native-extension-errors', p.errors.length === 0, { errors: p.errors });
  cases.push({ label: p.label, project: p.project, request, repair, failed_final: finalPath, failed_final_sha256: finalBefore,
    accepted_final: acceptedPath, accepted_final_sha256: hash(acceptedPath), verifier_calls: calls,
    scope: 'Scripted native same-session evidence-bound repair, not model diagnosis or natural self-repair acceptance. Complete failure fits native read; oversized evidence remains an explicit unqualified limit.' });
  await p.session.extensionRunner.emit({ type: 'session_shutdown' }); p.session.dispose(); p.closed = true;
}
async function reportRecoveryCounter(qualifyRepair = false) {
  const p = await profile(qualifyRepair ? 'report-retained-preimage-repair' : 'report-occupied-output-counter');
  const checker = path.join(runtime, 'harness/first_project.py');
  const metadata = spawnSync(python, ['-B', '-c', `import json,sys;sys.path.insert(0,sys.argv[1]);from harness import first_project as f;facts={'ram_total_gb':32.5,'gpu_vram_mib':8192,'storage_total_gb':1000,'configured_model':{'context_tokens':32768,'output_tokens':4096}};text='# Synthetic report fixture\\n\\nSource: hardware-facts.json.\\n\\n| Measurement | Value | Unit |\\n| --- | --- | --- |\\n';text+=''.join('| '+r['label']+' | '+str(r['value'])+' | '+r['unit']+' |\\n' for r in f._rows(facts));text+=' inventory'*(300-f.word_count(text));print(json.dumps({'writer':f.REPORT_WRITER,'repair_writer':getattr(f,'REPORT_REPAIR_WRITER',None),'facts':facts,'rows':f._rows(facts),'valid_body':text,'words':f.word_count(text)}))`, runtime],
    { encoding: 'utf8', timeout: 10000 });
  assert.equal(metadata.status, 0, metadata.stderr + metadata.stdout);
  const data = JSON.parse(metadata.stdout);
  const inputs = { 'hardware-facts.json': JSON.stringify(data.facts) + '\n',
    'FIRST-PROJECT.md': '# Synthetic pinned report contract\nUse the installed exclusive-create writer initially and original checker. Preserve failed bytes.\n'
      + (qualifyRepair ? 'Future-only recovery template:\n' + JSON.stringify([python, '-I', '-B', '-c', data.repair_writer, '<FAILED_REPORT_SHA256>', '<COMPLETE_REPORT_TEXT>']) + '\n' : '') };
  for (const [name, text] of Object.entries(inputs)) fs.writeFileSync(path.join(p.project, name), text);
  const manifest = { schema: 'first-project/v1', inputs: Object.fromEntries(Object.keys(inputs).map(name => [name, hash(path.join(p.project, name))])),
    output: 'hardware-report.md', words: { minimum: 250, maximum: 400 }, rows: data.rows };
  writeJson(path.join(p.project, 'first-project.json'), manifest);
  const pin = hash(path.join(p.project, 'first-project.json')), verify = [python, '-B', checker, 'check', '--expected-sha256', pin];
  const inputPins = Object.fromEntries([...Object.keys(inputs), 'first-project.json'].map(name => [name, hash(path.join(p.project, name))]));
  // A separate owned fixture directory proves that the proposed body satisfies
  // the ORIGINAL checker. It is synthetic test data, never a real report rescue.
  const candidate = path.join(p.base, 'synthetic-valid-candidate'); fs.mkdirSync(candidate);
  for (const name of Object.keys(inputPins)) fs.copyFileSync(path.join(p.project, name), path.join(candidate, name));
  fs.writeFileSync(path.join(candidate, 'hardware-report.md'), data.valid_body);
  const candidateCheck = spawnSync(verify[0], verify.slice(1), { cwd: candidate, encoding: 'utf8', timeout: 10000 });
  check('report-counter-valid-synthetic-body-passes-original-pinned-checker', candidateCheck.status === 0
    && JSON.parse(candidateCheck.stdout).passed === true && data.words === 300);
  const request = { objective: 'Qualify only an occupied failed report and its existing evidence-bound recovery route', cwd: p.project,
    action: [python, '-I', '-B', '-c', data.writer, '# Intentionally incomplete synthetic report.\n'], verify, outputs: ['hardware-report.md'] };
  await tool(p, 'read', { path: path.join(p.project, 'FIRST-PROJECT.md') });
  const failed = await tool(p, 'workflow_step', request, true);
  const finalPath = path.join(p.project, '.enforcement/runs', failed.details.host.run_id, 'final.json');
  const finalPin = hash(finalPath), reportPath = path.join(p.project, 'hardware-report.md'), reportPin = hash(reportPath);
  check('report-counter-original-writer-created-file-before-checker-rejected-it', failed.isError === true
    && readJson(finalPath).status === 'failed' && /independent verifier rejected/.test(failed.details.host.reason));
  await p.session.extensionRunner.emitInput('The fixture owner requests a scoped diagnosis and evidence-bound correction of this same task. Preserve the failed report and original checker; do not replay uncertain effects.', undefined, 'interactive');
  const status = (await tool(p, 'kanban_intake_status', {})).details.result;
  await tool(p, 'kanban_intake_route', { source_id: status.pending.at(-1).id, control: 'resume',
    parts: [{ kind: 'amend', task_id: status.queue[0].task, summary: 'Resume only the existing report scope after inspecting its saved failure', execute: true }] });
  const complete = await tool(p, 'read', { path: finalPath });
  check('report-counter-complete-original-failure-actually-read', !complete.details?.truncation
    && complete.content[0].text === fs.readFileSync(finalPath, 'utf8'));
  await tool(p, 'read', { path: reportPath });
  const repair = { ...request, action: [python, '-I', '-B', '-c', data.writer, data.valid_body],
    recovery: { source_run_id: failed.details.host.run_id, failure_class: 'verification_failure',
      changed_assumption: 'The saved output is an incomplete draft, not a valid report; the create-only writer cannot replace occupied output.',
      new_evidence: 'The complete saved final and report bytes show a failed original predicate; a separate synthetic300-word candidate passes that exact pinned checker.',
      expected_observation: 'The unchanged exclusive-create writer must refuse the occupied path before changing any bytes.',
      stop_condition: 'Stop at the create-only collision and preserve both failed records, original output, inputs and checker; no rescue or automatic replay.' } };
  const backup = 'hardware-report.failed-' + reportPin + '.md';
  if (qualifyRepair) {
    repair.action = [python, '-I', '-B', '-c', data.repair_writer, reportPin, data.valid_body];
    repair.outputs = ['hardware-report.md', backup];
    repair.recovery.changed_assumption = 'The initial create-only recipe cannot correct an occupied failed report. The prepared future task includes a preimage-bound retained-version repair.';
    repair.recovery.expected_observation = 'The exact inspected failed SHA must be retained in the declared sibling output, the complete replacement must pass the original pinned checker and empty-directory negative.';
    repair.recovery.stop_condition = 'Stop on preimage drift, occupied backup/stage, unavailable directory flock or failed original predicate; retain uncertain effects and do not replay.';
  }
  const repaired = await tool(p, 'workflow_step', repair, true);
  check('report-counter-proper-resume-and-recovery-reaches-real-supervisor', typeof repaired.details?.host?.run_id === 'string'
    && repaired.details.host.run_id !== failed.details.host.run_id);
  const repairedFinal = path.join(p.project, '.enforcement/runs', repaired.details.host.run_id, 'final.json');
  const actual = readJson(repairedFinal), process = readJson(path.join(p.project, actual.attempts[0].process_trace));
  if (qualifyRepair) {
    check('report-repair-actual-action-and-original-independent-check-pass', repaired.isError !== true && actual.status === 'accepted'
      && process.exit_code === 0 && repaired.details.host.status === 'supplied_predicate_passed');
    check('report-repair-old-bytes-retained-and-new-canonical-body-exact', hash(path.join(p.project, backup)) === reportPin
      && fs.readFileSync(reportPath, 'utf8') === data.valid_body
      && !fs.existsSync(path.join(p.project, '.hardware-report.repair-' + reportPin + '.tmp')));
    check('report-repair-both-final-outputs-declared-and-empty-directory-check-rejected', actual.outputs.length === 2
      && actual.outputs.some(row => row.path === backup) && actual.outputs.some(row => row.path === 'hardware-report.md')
      && actual.attempts[0].negative_control_exit_code === 0 && actual.attempts[0].verifier_exit_code === 0);
    check('report-repair-bound-success-releases-existing-failure-hold', (await p.session.extensionRunner.emitToolCall({ type: 'tool_call',
      toolName: 'workflow_step', toolCallId: 'repair-postcondition', input: request }))?.block !== true);
  } else {
    check('report-counter-create-only-collision-confirmed-after-proper-recovery', repaired.isError === true && actual.status === 'failed'
      && process.exit_code !== 0 && /FileExistsError/.test(process.stderr));
  }
  check('report-counter-original-report-failure-inputs-and-checker-preserved', (qualifyRepair || hash(reportPath) === reportPin) && hash(finalPath) === finalPin
    && Object.entries(inputPins).every(([name, pin]) => hash(path.join(p.project, name)) === pin)
    && hash(checker) === hash(path.join(source, 'harness/first_project.py')));
  check('report-counter-no-native-extension-errors', p.errors.length === 0);
  cases.push({ label: p.label, kind: qualifyRepair ? 'scripted_future_task_retained_preimage_repair' : 'expected_gap_reproduction_not_recovery_acceptance', original_final: finalPath,
    original_final_sha256: finalPin, original_report_sha256: reportPin, attempted_recovery_final: repairedFinal,
    attempted_recovery_final_sha256: hash(repairedFinal), original_check_argv: verify, candidate_check: JSON.parse(candidateCheck.stdout),
    scope: qualifyRepair ? 'Synthetic future task, actual native owner resume/full failure read/supervised preimage repair and original checker; no model diagnosis or semantic acceptance. Original real trial/home never accessed.'
      : 'Synthetic public facts and scripted fixture bodies, no model. Proper owner resume/full failure read/bound recovery confirms occupied-path refusal; no corrected report published. Original real trial/home never accessed.' });
  await p.session.extensionRunner.emit({ type: 'session_shutdown' }); p.session.dispose(); p.closed = true;
}
async function continuityCase() {
  const p = await profile('wrong-summary-continuity', true);
  const facts = { ram_total_gb: 32.5, gpu_vram_mib: null, storage_total_gb: 1000,
    configured_model: { context_tokens: 32768, output_tokens: 4096 } };
  writeJson(path.join(p.project, 'hardware-facts.json'), facts);
  const inputHashes = Object.fromEntries(['hardware-facts.json', 'FIRST-PROJECT.md'].map(name => [name, hash(path.join(p.project, name))]));
  const rows = [['RAM total', 32.5, 'GB (decimal)'], ['GPU VRAM', null, 'MiB'], ['Storage total', 1000, 'GB (decimal)'],
    ['Configured context', 32768, 'tokens'], ['Configured output', 4096, 'tokens']].map(([label, value, unit]) => ({ label, value, unit }));
  // The existing fixed task contract is fixture data, not a completion ledger.
  writeJson(path.join(p.project, 'first-project.json'), { schema: 'first-project/v1', inputs: inputHashes,
    output: 'hardware-report.md', words: { minimum: 250, maximum: 400 }, rows });
  const pin = hash(path.join(p.project, 'first-project.json'));
  const checker = [python, '-I', '-B', path.join(runtime, 'harness/first_project.py'), 'check', '--expected-sha256', pin];
  const request = { objective: 'Qualify missing report after an invalid launcher command; never infer completion', cwd: p.project,
    action: [python, '-I', '-B', path.join(runtime, 'harness/first_project.py'), 'run', '--input', 'hardware-facts.json',
      '--output', 'hardware-report.md', '--manifest-sha256', pin], verify: checker, outputs: ['hardware-report.md'] };
  const failed = await tool(p, 'workflow_step', request, true), failedMessage = structuredClone(p.lastMessage);
  const finalPath = path.join(p.project, '.enforcement/runs', failed.details.host.run_id, 'final.json');
  const final = readJson(finalPath), processPath = path.join(p.project, final.attempts[0].process_trace);
  check('continuity-actual-command-failed-with-no-report', failed.isError === true && failed.details.host.status === 'failed'
    && final.status === 'failed' && readJson(processPath).exit_code === 2 && !fs.existsSync(path.join(p.project, 'hardware-report.md')));
  const originalIds = [p.blockedRead.toolCallId, p.preparedMessage.toolCallId, failedMessage.toolCallId];
  const originalMessages = Object.fromEntries(originalIds.map(id => [id, JSON.stringify(p.sessionManager.getEntries()
    .find(entry => entry.type === 'message' && entry.message.role === 'toolResult' && entry.message.toolCallId === id).message)]));
  const sourceFiles = ['FIRST-PROJECT.md', 'hardware-facts.json', 'first-project.json', '.icm/project.json']
    .map(name => path.join(p.project, name)).concat([finalPath, processPath]);
  const before = Object.fromEntries(sourceFiles.map(file => [file, hash(file)]));
  const sessionFile = p.sessionManager.getSessionFile(), oldBytes = fs.readFileSync(sessionFile);
  const compacted = await p.session.compact('Controlled semantic distortion; synthetic summary stream only.');
  check('continuity-normal-native-compaction-retains-fault-injection', compacted.summary.includes('Preparation failed')
    && compacted.summary.includes('task is complete') && compacted.details.readFiles.includes(path.join(p.project, 'FIRST-PROJECT.md')));
  check('continuity-compaction-preserves-native-history-prefix', fs.readFileSync(sessionFile).subarray(0, oldBytes.length).equals(oldBytes));
  check('continuity-corrupt-summary-is-working-context-not-erased-records', JSON.stringify(p.sessionManager.buildSessionContext()).includes('Preparation failed'));
  await p.session.extensionRunner.emit({ type: 'session_shutdown' }); p.session.dispose(); p.closed = true;
  const identity = readJson(path.join(p.project, '.icm/project.json'));
  const selected = spawnSync(python, ['-I', '-B', '-c', `import json,sys;from pathlib import Path
sys.path.insert(0,sys.argv[1]);from harness.session_resume import acquire
with acquire(Path(sys.argv[2]),Path(sys.argv[3]),continue_recent=True,node=Path(sys.argv[4]),pi_package=Path(sys.argv[5]),project_identity=json.loads(sys.argv[6])) as lease:print(json.dumps(lease.selection))`,
  runtime, p.base, p.project, process.execPath, piPackage, JSON.stringify(identity)], { encoding: 'utf8', timeout: 30000 });
  assert.equal(selected.status, 0, selected.stderr || selected.stdout);
  const selection = JSON.parse(selected.stdout);
  check('continuity-existing-managed-picker-selects-exact-native-history', selection.path === sessionFile && selection.source_sha256 === hash(sessionFile));
  const reopened = sdk.SessionManager.continueRecent(p.project, p.bucket);
  assert.equal(reopened.getSessionFile(), sessionFile);
  await p.loader.reload();
  const { session } = await sdk.createAgentSession({ cwd: p.project, agentDir: p.agentDir, resourceLoader: p.loader,
    settingsManager: p.settings, sessionManager: reopened, modelRuntime: p.modelRuntime, thinkingLevel: 'off', model: p.session.model });
  await session.bindExtensions({ onError: error => p.errors.push(error) });
  p.session = session; p.sessionManager = reopened; p.closed = false;
  const restored = reopened.getEntries().filter(entry => entry.type === 'message' && entry.message.role === 'toolResult');
  for (const id of originalIds) check('continuity-original-tool-outcome-' + id, JSON.stringify(restored.find(entry => entry.message.toolCallId === id)?.message) === originalMessages[id]);
  check('continuity-successful-preparation-record-not-relabelled', restored.find(entry => entry.message.toolCallId === p.preparedMessage.toolCallId).message.details.complete === true);
  check('continuity-blocked-read-not-a-successful-read-record', restored.find(entry => entry.message.toolCallId === p.blockedRead.toolCallId).message.isError === true);
  const blockedRead = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'read-after-false-summary',
    toolName: 'read', input: { path: path.join(p.project, 'FIRST-PROJECT.md') } });
  check('continuity-false-readFiles-do-not-satisfy-fresh-context', blockedRead?.block === true);
  const status = await tool(p, 'kanban_intake_status', {});
  check('continuity-restores-canonical-failed-hold-not-summary-completion', status.details.result.mode === 'blocked' && status.details.result.retained_total > 0);
  for (let n = 0; n < 32; n++) {
    const context = await tool(p, 'project_context', { path: p.project });
    await session.extensionRunner.emitContext([structuredClone(p.lastMessage)]);
    if (!context.details.remaining_reads.length) break;
  }
  const held = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'no-replay-after-summary', toolName: 'workflow_step', input: request });
  check('continuity-failure-still-holds-effects-after-real-context-refresh', held?.block === true && /blocked|failed\/uncertain/.test(held.reason));
  const complete = await tool(p, 'kanban_work_checkpoint', { disposition: 'complete', reason: 'Controlled wrong summary claims completion; canonical retained work must still decide.' }, true);
  check('continuity-summary-cannot-complete-retained-work', complete.isError === true);
  const current = spawnSync(checker[0], checker.slice(1), { cwd: p.project, encoding: 'utf8', timeout: 10000 });
  check('continuity-current-missing-report-fixed-checker-refuses', current.status === 1 && JSON.parse(current.stdout).passed === false);
  for (const file of sourceFiles) check('continuity-original-file-' + path.basename(file), hash(file) === before[file]);
  check('continuity-saved-host-failure-remains-failed-no-accepted-receipt', readJson(finalPath).status === 'failed'
    && !fs.existsSync(path.join(path.dirname(failed.details.host.task_spec), 'receipt.json')));
  check('continuity-no-extension-errors', p.errors.length === 0, { errors: p.errors });
  cases.push({ label: p.label, project: p.project, session_file: sessionFile, selection, original_tool_ids: originalIds,
    original_files_sha256: before, final: finalPath, compacted,
    fault_injection: 'Controlled wrong summary/readFiles via public native compact hook and in-memory stream, not a real model generation.',
    scope: 'Existing native picker selection and SDK reopen, not a new concurrent-writer ownership claim. Old prep success remains recorded; fresh delivery/discovery readiness is intentionally stale after reload.' });
  await session.extensionRunner.emit({ type: 'session_shutdown' }); session.dispose(); p.closed = true;
}
try {
  if (!options.case) {
    await executeCase('action-fails-valid-output', 7, 'accepted fixture\n', false);
    await executeCase('ordinary-success', 0, 'accepted fixture\n', true);
    await executeCase('predicate-fails', 0, 'rejected fixture\n', false);
  }
  if (options.case === 'report-recovery' || options.case === 'report-repair') await reportRecoveryCounter(options.case === 'report-repair');
  else {
    if (options.case !== 'recovery') await continuityCase();
    if (options.case !== 'continuity') await recoveryCase();
  }
  check('native-zero-http-and-declared-synthetic-summary-count', networkRequests === 0
    && syntheticSummaries === (!options.case || options.case === 'continuity' ? 1 : 0));
} catch (error) {
  checks.push({ name: 'qualification-execution', passed: false, error: String(error?.stack || error) });
} finally {
  for (const p of sessions) if (!p.closed) { await p.session.extensionRunner.emit({ type: 'session_shutdown' }); p.session.dispose(); }
  for (const key of Object.keys(process.env)) if (!(key in initialEnv)) delete process.env[key];
  Object.assign(process.env, initialEnv);
  globalThis.fetch = originalFetch;
  const receipt = { schema: 'pi-action-failure-native/v1', status: checks.every(item => item.passed) ? 'passed' : 'failed',
    checks, cases, fixture, source, pi_version: readJson(path.join(piPackage, 'package.json')).version,
    native_probe_sha256: hash(new URL(import.meta.url)), runtime_manifest_sha256: hash(path.join(runtime, 'runtime-manifest.json')),
    source_hashes: Object.fromEntries(['harness/enforcement.py', 'adapters/pi/project-workflow/everyday_workflow.py',
      'adapters/pi/project-workflow/everyday-workflow.ts', 'adapters/pi/project-workflow/pi-task-worker.py']
      .map(name => [name, hash(path.join(runtime, name))])), model_calls: 0, mcp_calls: 0, hub_operations: 0, observer_events: 0,
    elapsed_ms: Date.now() - started,
    network_requests: networkRequests, synthetic_summary_requests: syntheticSummaries,
    selected_cases: options.case ?? 'all',
    limits: (options.case ? 'Explicit development case only. ' : 'Three original action fixtures, persistent continuity, and same-session evidence-bound repair. ')
      + 'Actual Pi/Hermes/context/owned host workflow and real subprocesses. Original three use explicit validated-memory readiness fixture; continuity uses the actual empty validated registry and synthetic system catalog, not memory qualification. Controlled wrong summary/readFiles, no real summary generation. Existing managed picker and native reopen, no expanded writer ownership claim. Scripted repair does not qualify model diagnosis; complete evidence fits native read, oversized evidence unqualified. Verifier counter is outside project. No private/live board, production profile, MCP, hub, service, model or root-product acceptance.' };
  writeJson(path.join(fixture, 'native-trace.json'), trace); writeJson(path.join(fixture, 'receipt.json'), receipt);
  console.log(JSON.stringify(receipt, null, 2)); process.exitCode = receipt.status === 'passed' ? 0 : 1;
}
