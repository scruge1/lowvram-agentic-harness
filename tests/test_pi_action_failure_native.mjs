/** Actual public workflow action failure; no MCP, model, service, or live project. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1], 'Use --name value arguments');
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['source', 'pi-package', 'python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
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
for (const name of ['pi-task-worker.py', 'pi_native_events.py']) {
  fs.copyFileSync(path.join(workflow, name), path.join(runtime, name));
  manifest.push({ path: name, sha256: hash(path.join(runtime, name)) });
}
writeJson(path.join(runtime, 'runtime-manifest.json'), { files: manifest });
writeJson(path.join(workflow, 'everyday-runtime.json'), { python, runtime,
  runtime_manifest_sha256: hash(path.join(runtime, 'runtime-manifest.json')),
  engine_sha256: hash(path.join(runtime, 'harness/enforcement.py')),
  helper_sha256: hash(path.join(workflow, 'everyday_workflow.py')) });
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
assert.equal(readJson(path.join(piPackage, 'package.json')).version, '1.4.0');
const trace = [], checks = [], cases = [], sessions = [];
const check = (name, condition, details = {}) => {
  checks.push({ name, passed: Boolean(condition), ...details }); assert.ok(condition, name);
};
const initialEnv = { ...process.env };
let sequence = 0;
async function profile(label) {
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
    PI_PROJECT_STATE_BASE: path.join(base, 'project-state'), HERMES_HOME: path.join(base, 'hermes-home'),
    PI_PROJECT_CONTEXT_PI_PACKAGE: piPackage, PI_SYSTEM_TOOL_PYTHON: python, PI_SYSTEM_TOOL_HELPER: queryHelper,
    PI_SYSTEM_TOOL_HELPER_SHA256: hash(queryHelper), PI_SYSTEM_TOOL_DATABASE: path.join(base, 'fixture-tools.sqlite') });
  const settings = sdk.SettingsManager.inMemory({ extensions: ['agent-capabilities.ts', 'system-tool-knowledge.ts',
    'pi-kanban.ts', 'everyday-workflow.ts'].map(name => path.join(workflow, name)),
    defaultTools: ['read', 'ls', 'find', 'grep'], cacheWarming: 'off' });
  const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
    noSkills: true, noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
  await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
  const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
  const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
  const sessionManager = sdk.SessionManager.inMemory(project);
  const { session } = await sdk.createAgentSession({ cwd: project, agentDir, resourceLoader: loader, settingsManager: settings,
    sessionManager, modelRuntime, thinkingLevel: 'off', model: { id: 'fixture-no-inference', name: 'No inference',
      provider: 'fixture-local', api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false,
      contextWindow: 32768, maxTokens: 4096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } } });
  const errors = []; await session.bindExtensions({ onError: error => errors.push(error) });
  const p = { label, base, project, agentDir, skill, session, sessionManager, errors }; sessions.push(p);
  assert.ok(!session.extensionRunner.getAllRegisteredTools().some(item => item.definition.name.startsWith('mcp__')));
  await tool(p, 'project_admit', { project_root: project, initialize: true,
    native_authority: 'Owner authorized isolated public workflow action-status qualification',
    target: 'Qualify action failure and independent predicate handling', why: 'Prove actual host/controller/tool results without inference' });
  await session.extensionRunner.emitInput('Qualify only this isolated workflow action-status fixture. Do not infer root acceptance or run other work.', undefined, 'interactive');
  const pending = (await tool(p, 'kanban_intake_status', {})).details.result.pending;
  await tool(p, 'kanban_intake_route', { source_id: pending.at(-1).id,
    parts: [{ kind: 'task', summary: 'Qualify the isolated workflow action status and independent predicate', execute: true }] });
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
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!blocked?.block, `${name} blocked: ${blocked?.reason}`);
  const item = runner.getAllRegisteredTools().find(value => value.definition.name === name);
  const wrapped = item ? sdk.wrapRegisteredTool(item, runner) : sdk.createReadTool(p.project);
  const raw = await wrapped.execute(id, input, new AbortController().signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...raw, isError: raw.isError === true });
  const result = { ...raw, ...changed };
  p.lastMessage = { role: 'toolResult', toolCallId: id, toolName: name, content: structuredClone(result.content),
    details: structuredClone(result.details), isError: result.isError === true, timestamp: Date.now() };
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
  const host = result.details.host, finalPath = path.join(p.project, '.enforcement/runs', host.run_id, 'final.json');
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
try {
  await executeCase('action-fails-valid-output', 7, 'accepted fixture\n', false);
  await executeCase('ordinary-success', 0, 'accepted fixture\n', true);
  await executeCase('predicate-fails', 0, 'rejected fixture\n', false);
} catch (error) {
  checks.push({ name: 'qualification-execution', passed: false, error: String(error?.stack || error) });
} finally {
  for (const p of sessions) if (!p.closed) { await p.session.extensionRunner.emit({ type: 'session_shutdown' }); p.session.dispose(); }
  for (const key of Object.keys(process.env)) if (!(key in initialEnv)) delete process.env[key];
  Object.assign(process.env, initialEnv);
  const receipt = { schema: 'pi-action-failure-native/v1', status: checks.every(item => item.passed) ? 'passed' : 'failed',
    checks, cases, fixture, source, pi_version: readJson(path.join(piPackage, 'package.json')).version,
    native_probe_sha256: hash(new URL(import.meta.url)), runtime_manifest_sha256: hash(path.join(runtime, 'runtime-manifest.json')),
    source_hashes: Object.fromEntries(['harness/enforcement.py', 'adapters/pi/project-workflow/everyday_workflow.py',
      'adapters/pi/project-workflow/everyday-workflow.ts', 'adapters/pi/project-workflow/pi-task-worker.py']
      .map(name => [name, hash(path.join(runtime, name))])), model_calls: 0, mcp_calls: 0, hub_operations: 0, observer_events: 0,
    elapsed_ms: Date.now() - started,
    limits: 'Three isolated synthetic project fixtures, actual Pi/Hermes/context/owned host workflow and real subprocesses. Explicit validated-memory readiness fixture; no memory or model qualification. Verifier counter writes only fixture instrumentation outside the project. Failed-action predicate is run standalone only after proving workflow did not execute it. No private/live board, production profile, MCP, hub or root-product acceptance.' };
  writeJson(path.join(fixture, 'native-trace.json'), trace); writeJson(path.join(fixture, 'receipt.json'), receipt);
  console.log(JSON.stringify(receipt, null, 2)); process.exitCode = receipt.status === 'passed' ? 0 : 1;
}
