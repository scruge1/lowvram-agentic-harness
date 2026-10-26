/** Actual Pi1.4 child/parent tools + native Hermes + supervisor; synthetic SSE, zero network/model. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1]);
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['source', 'pi-package', 'python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
assert.equal(process.platform, 'linux');
const started = Date.now(), source = fs.realpathSync(options.source), pkg = fs.realpathSync(options['pi-package']);
const python = path.resolve(options.python); // Preserve the selected virtual environment executable path.
const fixture = options.prepared ? fs.realpathSync(options.prepared) : fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-managed-child-'));
assert.ok(fixture.startsWith(fs.realpathSync(options['fixture-parent']) + path.sep));
const home = path.join(fixture, 'home'), project = path.join(fixture, 'project');
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const write = (file, value) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n'); };
const originalEnv = { ...process.env }, originalFetch = globalThis.fetch;
for (const key of Object.keys(process.env)) if (!['HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TMP', 'TEMP'].includes(key)) delete process.env[key];
Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' });
const setup = spawnSync(python, ['-B', '-c', `import sys,json\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom harness.home import scaffold,environment\nh=Path(sys.argv[2]);(None if sys.argv[3]=='prepared' else scaffold(h,source=Path(sys.argv[1]),profile='pi',base_url='http://127.0.0.1:1/v1',model='managed-child-fixture',name='ChildFixtureOwner',offline=True))\nprint(json.dumps(environment(h)))`, source, home, options.prepared ? 'prepared' : 'fresh'],
  { encoding: 'utf8', timeout: 30000 });
assert.equal(setup.status, 0, setup.stderr + setup.stdout);
Object.assign(process.env, JSON.parse(setup.stdout), { PI_PROJECT_KANBAN_PYTHON: python, PI_PROJECT_CONTEXT_PI_PACKAGE: pkg });
const piAlias = path.join(home, 'packages/pi');
if (!options.prepared) { fs.mkdirSync(path.dirname(piAlias), { recursive: true }); fs.symlinkSync(path.resolve(pkg, '../../..'), piAlias, 'dir'); }
assert.equal(fs.realpathSync(piAlias), path.resolve(pkg, '../../..'));
const runtime = path.join(home, 'runtime'), workflow = path.join(runtime, 'adapters/pi/project-workflow'), agentDir = path.join(home, 'agent');
if (!options.prepared) { fs.mkdirSync(project); fs.writeFileSync(path.join(project, 'AGENTS.md'), '# Child fixture\nPreserve parent scope. No root acceptance from child text.\n'); }
const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
const modelsFile = path.join(agentDir, 'models.json'), settingsFile = path.join(agentDir, 'settings.json');
const models = JSON.parse(fs.readFileSync(modelsFile)); models.providers.local.apiKey = '$MANAGED_CHILD_FIXTURE_KEY'; if (!options.prepared) write(modelsFile, models);
process.env.MANAGED_CHILD_FIXTURE_KEY = 'synthetic-test-only';
const settingsBody = JSON.parse(fs.readFileSync(settingsFile));
const names = ['agent-capabilities.ts', 'system-tool-knowledge.ts', 'pi-kanban.ts', 'everyday-workflow.ts'];
settingsBody.extensions = names.map(name => path.join(workflow, name));
settingsBody.cacheWarming = 'off'; settingsBody.retry = { enabled: false }; settingsBody.compaction = { enabled: false }; if (!options.prepared) write(settingsFile, settingsBody);
// This is a scaffolded SDK fixture with supplied dependency references, not a
// fresh install, deployed managed CLI or real-provider delegation acceptance.
const watched = [path.join(home, 'home.json'), modelsFile, settingsFile, path.join(home, 'state/validated-memory.jsonl')];
const protectedBefore = Object.fromEntries(watched.map(file => [file, hash(file)]));
const sdk = await import(pathToFileURL(path.join(pkg, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg, 'package.json'))).version, '1.4.0');
const modelRuntime = await sdk.ModelRuntime.create({ modelsPath: modelsFile, authPath: path.join(agentDir, 'auth.json'), allowModelNetwork: false, refreshOnCreate: false });
const model = (await modelRuntime.getAvailable('local')).find(value => value.id === config.model); assert.ok(model);
const settings = sdk.SettingsManager.inMemory(settingsBody);
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings, noThemes: true,
  disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const manager = options.prepared ? sdk.SessionManager.open(options.session) : sdk.SessionManager.create(project);
const { session } = await sdk.createAgentSession({ cwd: project, agentDir, modelRuntime, model, settingsManager: settings,
  resourceLoader: loader, sessionManager: manager, thinkingLevel: 'off' });
const errors = []; await session.bindExtensions({ onError: error => errors.push(String(error)) });
const checks = [], trace = [], payloads = [];
let sequence = 0, phase = 0, scenario = 'positive', control, onRequest;
const check = (name, value) => { checks.push({ name, passed: Boolean(value) }); assert.ok(value, name); };
async function tool(name, input, allowError = false, signal = new AbortController().signal) {
  const runner = session.extensionRunner, id = 'managed-child-' + ++sequence;
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  if (blocked?.block) { if (allowError) return { isError: true, blocked }; throw new Error(`${name}: ${blocked.reason}`); }
  const registered = runner.getAllRegisteredTools().find(item => item.definition.name === name);
  const wrapped = registered ? sdk.wrapRegisteredTool(registered, runner) : sdk.createReadTool(project);
  if (name === 'task_agent') {
    // The supported nested-tool runner requires an issuing parent assistant.
    // This is explicit synthetic native input, not a real model output or owner source.
    manager.appendMessage({ role: 'assistant', api: model.api, provider: model.provider, model: model.id,
      content: [{ type: 'toolCall', id, name, arguments: input }], stopReason: 'toolUse', timestamp: Date.now(),
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } });
    session.refreshContext();
  }
  const raw = await wrapped.execute(id, input, signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...raw, isError: raw.isError === true });
  const value = { ...raw, ...changed }; trace.push({ name, input, value });
  if (!allowError) assert.ok(!value.isError, JSON.stringify(value));
  return value;
}
const latest = name => [...manager.getBranch()].reverse().find(entry => entry.customType === name)?.data;
async function route(text, parts, control) {
  await session.extensionRunner.emitInput(text, undefined, 'interactive');
  const pending = (await tool('kanban_intake_status', {})).details.result.pending;
  return tool('kanban_intake_route', { source_id: pending.at(-1).id, parts, ...(control ? { control } : {}) });
}
async function discover() {
  await tool('agent_capabilities', {}); await tool('system_tool_query', { terms: 'workflow file outputs' });
  await tool('project_knowledge_query', { terms: 'managed child fixture' });
  // Explicit memory-result fixture; no palace/MCP service or query is run.
  await session.extensionRunner.emitToolResult({ type: 'tool_result', toolCallId: 'synthetic-memory', toolName: 'validated_memory_query', input: {}, content: [],
    details: { schema: 'validated-memory-query/v1', results: [], reason: 'no_current_provenanced_result', fixture: true }, isError: false });
  await tool('read', { path: path.join(agentDir, 'skills/supervised-tasks/SKILL.md') });
  const held = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'child-context-negative', toolName: 'task_agent', input: { task: 'Context negative only', timeout_seconds: 60 } });
  check('child-parent-context-required', held?.block === true && /context/i.test(held.reason));
  for (let i = 0; i < 32; i++) {
    const value = await tool('project_context', { path: project });
    await session.extensionRunner.emitContext([{ role: 'toolResult', toolCallId: 'context-' + sequence, toolName: 'project_context', content: value.content, details: value.details, isError: false, timestamp: Date.now() }]);
    // Native context proof is keyed by its actual toolCallId.
    const id = 'managed-child-' + sequence;
    await session.extensionRunner.emitContext([{ role: 'toolResult', toolCallId: id, toolName: 'project_context', content: value.content, details: value.details, isError: false, timestamp: Date.now() }]);
    if (!value.details.remaining_reads.length) return;
  }
  throw new Error('Fixture context did not settle');
}
const request = name => ({ objective: 'Create only the declared child fixture output and check exact bytes', cwd: project,
  action: [python, '-c', `from pathlib import Path;Path(${JSON.stringify(name)}).write_text('child fixture accepted'+chr(10))`],
  verify: [python, '-c', `from pathlib import Path;raise SystemExit(0 if Path(${JSON.stringify(name)}).is_file() and Path(${JSON.stringify(name)}).read_text()=='child fixture accepted'+chr(10) else 1)`], outputs: [name] });
function sse(payload, call) {
  const id = 'synthetic-' + sequence + '-' + phase;
  const delta = call ? { role: 'assistant', tool_calls: [{ index: 0, id, type: 'function', function: { name: call.name, arguments: JSON.stringify(call.args) } }] }
    : { role: 'assistant', content: 'Child fixture returned; parent must verify root outcome.' };
  return new Response([{ id, model: payload.model, choices: [{ index: 0, delta, finish_reason: null }] },
    { id, model: payload.model, usage: { prompt_tokens: 11, completion_tokens: 7, total_tokens: 18 }, choices: [{ index: 0, delta: {}, finish_reason: call ? 'tool_calls' : 'stop' }] }]
    .map(value => 'data: ' + JSON.stringify(value) + '\n\n').join('') + 'data: [DONE]\n\n', { headers: { 'content-type': 'text/event-stream' } });
}
globalThis.fetch = async (input, init) => {
  const req = new Request(input, init), payload = JSON.parse(await req.text());
  assert.equal(req.url, 'http://127.0.0.1:1/v1/chat/completions');
  assert.equal(req.headers.get('authorization'), 'Bearer synthetic-test-only');
  const declared = payload.tools.map(tool => tool.function.name);
  for (const name of ['task_agent', 'project_create', 'project_admit', 'kanban_select', 'kanban_move', 'kanban_intake_route', 'bash', 'write', 'edit']) assert.ok(!declared.includes(name), name);
  assert.ok(declared.includes('workflow_step') && declared.includes('read'));
  payloads.push({ scenario, phase, payload });
  if (onRequest) await onRequest();
  let call;
  if (scenario === 'unknown' && phase === 0) call = { name: 'task_agent', args: { task: 'Forbidden recursion', timeout_seconds: 30 } };
  else if (phase === 0 && scenario === 'parent_loss') call = { name: 'workflow_step', args: lossRequest() };
  else if (phase === 0) call = { name: 'read', args: { path: path.join(project, 'AGENTS.md') } };
  else if (phase === 1 && scenario === 'positive') call = { name: 'workflow_step', args: request('child-result.txt') };
  phase++; return sse(payload, call);
};
async function child(kind, signal) { scenario = kind; phase = 0; return tool('task_agent', { task: 'Produce only child-result.txt through the existing guarded workflow; no root acceptance.', timeout_seconds: 60 }, true, signal); }
function lossRequest() {
  return { objective: 'Hold an owned synthetic action to verify parent-loss cleanup only', cwd: project,
    action: [python, '-c', "import os,json,time;from pathlib import Path;p=Path('/proc/self/stat');Path('parent-loss-action.json').write_text(json.dumps({'pid':os.getpid(),'start_ticks':p.read_text().rsplit(')',1)[1].split()[19]}));time.sleep(120);Path('late-child-output.txt').write_text('unexpected')"],
    verify: [python, '-c', "from pathlib import Path;raise SystemExit(0 if Path('late-child-output.txt').is_file() else 1)"],
    outputs: ['parent-loss-action.json', 'late-child-output.txt'] };
}
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const procState = pid => { try { const fields = fs.readFileSync(`/proc/${pid}/stat`, 'utf8').split(')').at(-1).trim().split(/\s+/); return { start_ticks: fields[19], state: fields[0], ppid: fields[1] }; } catch { return undefined; } };
const ticks = pid => procState(pid)?.start_ticks;
const stillRunning = item => { const p = procState(item.pid); return p?.start_ticks === item.start_ticks && !['Z', 'X'].includes(p.state); };
function descendants(pid, result = []) {
  let children = [];
  try { children = fs.readFileSync(`/proc/${pid}/task/${pid}/children`, 'utf8').trim().split(/\s+/).filter(Boolean); } catch {}
  for (const child of children) { assert.ok(result.length < 64); result.push({ pid: child, start_ticks: ticks(child) }); descendants(child, result); }
  return result;
}
async function parentLoss() {
  const admission = `import sys,json,os\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom harness import home_entry,session_resume\nh=Path(sys.argv[2]);p=Path(sys.argv[3]);node=Path(sys.argv[4]);pkg=Path(sys.argv[5]);identity=json.loads((p/'.icm/project.json').read_text())\nwith home_entry.consumer(h) as fds,session_resume.acquire(h,p,node=node,pi_package=pkg,project_identity=identity) as bucket:\n for fd in (*fds,*bucket.pass_fds):os.set_inheritable(fd,True)\n os.environ['AGENT_HOME_LIFECYCLE_FD']=str(fds[0])\n os.execv(str(node),[str(node),*sys.argv[6:]])\n`;
  const log = fs.openSync(path.join(fixture, 'parent-loss-owner.log'), 'wx');
  const owner = spawn(python, ['-s', '-B', '-c', admission, runtime, home, project, process.execPath, pkg,
    path.resolve(process.argv[1]), '--source', source, '--pi-package', pkg, '--python', python,
    '--fixture-parent', options['fixture-parent'], '--prepared', fixture, '--session', manager.getSessionFile()],
  { cwd: project, env: process.env, stdio: ['ignore', log, log] });
  fs.closeSync(log);
  const exited = new Promise(resolve => owner.once('exit', (code, signal) => resolve({ code, signal })));
  const marker = path.join(project, 'parent-loss-action.json');
  const until = Date.now() + 60000;
  while (!fs.existsSync(marker) && owner.exitCode === null && owner.signalCode === null && Date.now() < until) await pause(25);
  check('owned-parent-real-guarded-action-active', fs.existsSync(marker));
  const identity = { pid: owner.pid, start_ticks: ticks(owner.pid) }, owned = descendants(owner.pid), action = JSON.parse(fs.readFileSync(marker));
  check('owned-parent-descendant-identified', owned.some(item => Number(item.pid) === action.pid && item.start_ticks === action.start_ticks));
  const locks = `import sys,json\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom harness import home_entry,session_resume\nh=Path(sys.argv[2]);p=Path(sys.argv[3]);guard=home_entry._load_guard(h,json.loads((h/'home.json').read_text())['lifecycle_guard_sha256']);result={}\nfor name in ['home','bucket']:\n try:\n  lease=guard.lease(h,expected_sha256=json.loads((h/'home.json').read_text())['lifecycle_guard_sha256'],mode='exclusive') if name=='home' else session_resume.acquire(h,p,node=Path(sys.argv[4]),pi_package=Path(sys.argv[5]),project_identity=json.loads((p/'.icm/project.json').read_text()))\n  with lease:pass\n  result[name]='available'\n except (ValueError,BlockingIOError):result[name]='busy'\nprint(json.dumps(result))\n`;
  const status = () => { const r = spawnSync(python, ['-B', '-c', locks, runtime, home, project, process.execPath, pkg], { encoding: 'utf8', timeout: 10000 }); assert.equal(r.status, 0, r.stderr); return JSON.parse(r.stdout); };
  const before = status(); check('parent-inherited-home-and-bucket-leases', before.home === 'busy' && before.bucket === 'busy');
  const signalCode = `import sys,importlib.util,hashlib,signal\nfrom pathlib import Path\np=Path(sys.argv[1]);assert hashlib.sha256(p.read_bytes()).hexdigest()==sys.argv[2]\ns=importlib.util.spec_from_file_location('owned_pidfd',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\npid=int(sys.argv[3]);start=Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[19];assert start==sys.argv[4]\nfd=m.pidfd_open(pid)\ntry:\n assert Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[19]==start\n m.pidfd_send_signal(fd,signal.SIGKILL)\nfinally:import os;os.close(fd)\n`;
  const facade = path.join(workflow, 'native_pidfd.py');
  const killed = spawnSync(python, ['-B', '-c', signalCode, facade, hash(facade), String(owner.pid), identity.start_ticks], { encoding: 'utf8', timeout: 10000 });
  assert.equal(killed.status, 0, killed.stderr);
  const outcome = await Promise.race([exited, pause(10000).then(() => { throw new Error('Exact owned parent did not exit'); })]);
  const settlement = Date.now() + 10000;
  while (owned.some(stillRunning) && Date.now() < settlement) await pause(25);
  const remaining = owned.filter(stillRunning), after = status(), kernel_states = owned.map(item => ({ ...item, current: procState(item.pid) ?? null }));
  write(path.join(fixture, 'parent-loss.json'), { identity, action, owned, outcome, remaining, kernel_states, before, after,
    scope: 'Native SDK restored parent in owned fixture, inherited real home/bucket leases, actual nested guarded action; exact PIDFD SIGKILL. No actual inference or whole managed CLI claim.' });
  check('parent-loss-descendants-settled', remaining.length === 0);
  check('parent-loss-no-late-output', !fs.existsSync(path.join(project, 'late-child-output.txt')));
  check('parent-loss-home-and-bucket-released', after.home === 'available' && after.bucket === 'available');
  check('parent-loss-native-start-retained', fs.readFileSync(manager.getSessionFile(), 'utf8').includes('pi-managed-child-start/v1'));
  const historyHash = hash(manager.getSessionFile()), opened = sdk.SessionManager.open(manager.getSessionFile());
  const restoredManager = sdk.SessionManager.inMemory(project, undefined, [opened.getHeader(), ...opened.getEntries()]);
  const restoredSettings = sdk.SettingsManager.inMemory(settingsBody);
  const restoredLoader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: restoredSettings, noThemes: true,
    disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
  await restoredLoader.reload(); assert.deepEqual(restoredLoader.getExtensions().errors, []);
  const { session: restored } = await sdk.createAgentSession({ cwd: project, agentDir, modelRuntime, model,
    resourceLoader: restoredLoader, settingsManager: restoredSettings, sessionManager: restoredManager });
  await restored.bindExtensions({ onError: error => { throw Error(String(error)); } });
  let restoreId = 0;
  const restoredTool = async (name, input) => {
    const id = 'restored-read-' + ++restoreId, item = restored.extensionRunner.getAllRegisteredTools().find(value => value.definition.name === name);
    const result = await sdk.wrapRegisteredTool(item, restored.extensionRunner).execute(id, input, new AbortController().signal);
    if (name === 'project_context') await restored.extensionRunner.emitContext([{ role: 'toolResult', toolCallId: id,
      toolName: name, ...result, timestamp: Date.now() }]);
    return result;
  };
  try {
    const initial = (await restoredTool('kanban_intake_status', {})).details.result;
    check('actual-reopen-unsettled-child-held', initial.mode === 'blocked' && initial.reason.includes('Unsettled in-memory child'));
    // A model's work checkpoint cannot stand in for fresh owner permission.
    await restoredTool('kanban_work_checkpoint', { disposition: 'continue', reason: 'Controlled checkpoint cannot clear lost-child authority', next_action: 'Inspect retained lost-child evidence only' });
    for (let i = 0; i < 32; i++) {
      const result = await restoredTool('project_context', { path: project });
      if (!result.details.remaining_reads.length) break;
      assert.ok(i < 31);
    }
    const held = await restored.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'restored-effect-negative', toolName: 'workflow_step', input: request('must-not-run.txt') });
    check('checkpoint-cannot-clear-crash-uncertainty', held?.block === true && /unsettled/i.test(held.reason));
    const boundary = await restored.extensionRunner.emitBoundary({ type: 'agent_before_settle', outcome: 'completed' },
      entries => ({ contextEntries: [], contextMessages: [], llmMessages: [], pendingMessages: [], canContinue: entries.length > 0 }));
    check('unsettled-child-no-automatic-continuation', boundary.continue === false);
    await restored.extensionRunner.emitInput('The fixture owner inspected the retained start and partial output evidence. Resume only the original declared synthetic scope; do not replay uncertain effects.', undefined, 'interactive');
    const sourceId = (await restoredTool('kanban_intake_status', {})).details.result.pending.at(-1).id;
    await restoredTool('kanban_intake_route', { source_id: sourceId, parts: [{ kind: 'control', summary: 'Explicit fixture owner resume after lost-child inspection' }], control: 'resume' });
    check('fresh-owner-resume-clears-only-uncertainty-hold', (await restoredTool('kanban_intake_status', {})).details.result.mode === 'running');
    check('reopen-original-history-conserved', hash(manager.getSessionFile()) === historyHash && !fs.existsSync(path.join(project, 'must-not-run.txt')));
  } finally { await restored.abort(); restored.dispose(); }
}
try {
  if (options.prepared) { await discover(); await child('parent_loss'); throw new Error('Owned parent-loss fixture was not killed while its action was active'); }
  await tool('project_admit', { project_root: project, initialize: true, native_authority: 'Owner authorized disposable model-free native child qualification', target: 'Native child fixture', why: 'Source/card/tool and lifetime checks without inference' });
  const routed = await route('Prepare one existing contained child for this synthetic output and verify it. No other project work.', [{ kind: 'task', summary: 'Contained managed child fixture', execute: true, expandable: true }]);
  const root = routed.details.result.bound[0].task_id;
  const decomposition = await tool('kanban_decompose', { task_id: root, children: [{ title: 'Operational child fixture', body: 'Write the declared synthetic output and check it' }] });
  const card = decomposition.details.result.root.children[0].id;
  await tool('kanban_select', { task_id: card }); await discover();
  const selection = JSON.stringify(latest('pi-kanban-selection/v1')), captures = manager.getBranch().filter(entry => entry.customType === 'pi-request-capture/v1').length;
  if (options.case !== 'lifetime') {
  const positive = await child('positive');
  check('native-parent-tool-and-sdk-child-success', positive.details?.ok === true && !positive.isError);
  check('actual-parent-supervisor-output', fs.readFileSync(path.join(project, 'child-result.txt'), 'utf8') === 'child fixture accepted\n');
  check('same-selected-hierarchy-card', JSON.stringify(latest('pi-kanban-selection/v1')) === selection && positive.details.card === card && positive.details.parent_card === root);
  check('child-text-not-captured-as-owner', manager.getBranch().filter(entry => entry.customType === 'pi-request-capture/v1').length === captures);
  const retained = latest('pi-managed-child-result/v1');
  check('parent-journal-retains-child-messages-tools-and-usage', retained.state === 'returned' && retained.calls.length === 2 && retained.messages.length === 3 && retained.messages.every(message => message.usage));
  check('in-memory-child-no-disk-history', !retained.child_session || !fs.readdirSync(path.dirname(manager.getSessionFile())).some(name => name.includes(retained.child_session)));
  check('parent-native-journal-is-persistent', fs.existsSync(manager.getSessionFile()));
  check('no-duplicate-capture-or-memory-write', Object.entries(protectedBefore).every(([file, expected]) => hash(file) === expected));
  const rootState = (await tool('kanban_show', { task_id: root })).details.result.task.status;
  check('child-completion-does-not-accept-root', rootState !== 'done' && retained.acceptance === 'untrusted_child_result_not_root_acceptance');
  check('no-provider-key-in-child-record', !JSON.stringify(retained).includes('synthetic-test-only'));
  const afterReturn = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'completed-child-admission', toolName: 'workflow_step', input: request('not-executed.txt') });
  check('matching-final-result-does-not-hold-normal-work', !afterReturn?.block);
  if (options.case !== 'positive') {
  const unknown = await child('unknown');
  check('recursive-tool-not-available', unknown.isError === true && latest('pi-managed-child-result/v1').toolResults.some(result => result.isError) && !unknown.details?.calls?.some(call => call.name === 'task_agent') && payloads.filter(value => value.scenario === 'unknown').every(value => !value.payload.tools.some(tool => tool.function.name === 'task_agent')));
  await route('Resume only the same declared synthetic child after inspecting the retained unknown-tool fixture outcome.', [{ kind: 'control', summary: 'Explicit fixture resume' }], 'resume');
  for (const kind of ['model_drift', 'config_drift', 'input_drift', 'provider_override']) {
    const originalSettings = fs.readFileSync(settingsFile), originalHeaders = model.headers;
    onRequest = async () => {
      if (kind === 'provider_override') modelRuntime.registerProvider('local', { api: 'openai-completions', apiKey: '$MANAGED_CHILD_FIXTURE_KEY', baseUrl: 'http://127.0.0.1:2/v1', models: models.providers.local.models });
      if (kind === 'model_drift') model.headers = { 'x-synthetic-route': 'changed' };
      if (kind === 'config_drift') fs.appendFileSync(settingsFile, ' ');
      if (kind === 'input_drift') await session.extensionRunner.emitInput('Synthetic new owner question during child transport. It grants no extra work.', undefined, 'interactive');
    };
    const held = await child(kind); onRequest = undefined;
    if (kind === 'provider_override') modelRuntime.unregisterProvider('local');
    model.headers = originalHeaders; fs.writeFileSync(settingsFile, originalSettings);
    check(kind + '-held', held.isError === true && latest('pi-managed-child-result/v1').state !== 'returned');
    await route('Resume only the original synthetic child after inspecting this retained negative fixture outcome.', [{ kind: 'control', summary: 'Explicit fixture resume' }], 'resume');
  }
  control = new AbortController(); onRequest = async () => { control.abort(); }; const aborted = await child('abort', control.signal); onRequest = undefined;
  check('native-child-abort-held', aborted.isError === true && latest('pi-managed-child-result/v1').state !== 'returned');
  // Abort is an uncertain task result and retains the normal intake failure hold.
  check('no-automatic-replay-after-abort', (await child('positive')).isError === true);
  check('sdk-errors-empty', errors.length === 0);
  await route('Resume only the original declared fixture after the retained abort control; no automatic replay.', [{ kind: 'control', summary: 'Explicit fixture resume for owned parent-loss qualification' }], 'resume');
  }
  }
  if (options.case !== 'positive') {
  manager.appendMessage({ role: 'user', content: 'Controlled native lifetime fixture under the existing captured source. No new task or scope.', timestamp: Date.now() });
  session.refreshContext();
  await session.abort(); session.dispose();
  await parentLoss();
  }
} finally {
  await session.abort(); session.dispose(); globalThis.fetch = originalFetch;
  write(path.join(fixture, options.prepared ? 'parent-loss-child-receipt.json' : 'receipt.json'), { scope: 'Actual Pi1.4 native SDK and registered parent tools, actual Hermes/supervisor; synthetic SSE and explicit memory fixture. No real provider, managed CLI or child inference claim. Parent-loss proves only its recorded owned SDK/guard fixture; in-memory children cannot resume.', source, fixture,
    source_sha256: Object.fromEntries(['adapters/pi/project-workflow/managed-child.ts', 'adapters/pi/project-workflow/pi-kanban.ts', 'adapters/pi/intake/request-intake-138.ts'].map(name => [name, hash(path.join(source, name))])),
    checks, trace, payloads, elapsed_seconds: (Date.now() - started) / 1000, actual_network_requests: 0 });
  for (const name of Object.keys(process.env)) if (!(name in originalEnv)) delete process.env[name]; Object.assign(process.env, originalEnv);
  console.log(JSON.stringify({ fixture, checks: checks.length, elapsed_seconds: (Date.now() - started) / 1000 }));
}
