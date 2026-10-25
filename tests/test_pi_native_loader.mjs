/** Model-free native Pi loader qualification. Dependencies are supplied explicitly. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
const startedAt = Date.now();
for (let index = 2; index < process.argv.length; index += 2) {
  const name = process.argv[index];
  assert.ok(name?.startsWith('--') && process.argv[index + 1], 'Use --name value arguments');
  options[name.slice(2)] = process.argv[index + 1];
}
for (const name of ['pi-package', 'workflow', 'python', 'fixture-parent']) {
  assert.ok(options[name], `Missing --${name}`);
}
const source = fs.realpathSync(options.workflow);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-native-loader-'));
const agentDir = path.join(fixture, 'agent');
const project = path.join(fixture, 'project');
const projectScope = path.join(project, 'nested');
const workflow = path.join(fixture, 'workflow');
fs.mkdirSync(agentDir);
fs.mkdirSync(project);
fs.mkdirSync(projectScope);
fs.writeFileSync(path.join(project, 'AGENTS.md'), '# Native fixture project\n\nRetain the owner outcome and use the admitted workspace.\n');
fs.writeFileSync(path.join(projectScope, 'AGENTS.md'), '# Nested fixture scope\n\nKeep the declared artifact and exact independent check together.\n');
fs.mkdirSync(workflow);
const hash = (file) => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const json = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
const names = ['agent-capabilities.ts', 'system-tool-knowledge.ts', 'pi-kanban.ts', 'everyday-workflow.ts'];
for (const name of fs.readdirSync(source)) {
  if (/\.(ts|py|mjs)$/.test(name)) fs.copyFileSync(path.join(source, name), path.join(workflow, name));
}
const intake = path.join(fixture, 'intake');
fs.mkdirSync(intake);
for (const name of fs.readdirSync(path.join(source, '../intake'))) {
  if (/\.(ts|py)$/.test(name)) fs.copyFileSync(path.join(source, '../intake', name), path.join(intake, name));
}
const context = path.join(fixture, 'context');
fs.mkdirSync(context);
for (const name of fs.readdirSync(path.join(source, '../context'))) {
  if (/\.(ts|py)$/.test(name)) fs.copyFileSync(path.join(source, '../context', name), path.join(context, name));
}
const backend = path.join(fixture, 'fixture-board.py');
fs.writeFileSync(backend, `import json,sys
from pathlib import Path
import subprocess
sys.path.insert(0,str(Path(__file__).with_name('workflow')))
from project_identity import initialize_identity
r=json.load(sys.stdin)
action=r['action']
root=r.get('project_root','')
store=Path(__file__).with_name('fixture-board.json')
state=json.loads(store.read_text()) if store.exists() else {'tasks':{'unadmitted-card':{'id':'unadmitted-card','status':'ready','title':'Unadmitted fixture','body':'','priority':0}},'comments':{},'keys':{}}
state.setdefault('parents',{})
state.setdefault('children',{})
def shown(id):
 task=dict(state['tasks'][id])
 if Path(__file__).with_name('task-blocked').exists(): task['status']='blocked'
 return {'task':task,'parents':state['parents'].get(id,[]),'comments':state['comments'].get(id,[])}
def node(id):
 task=shown(id)['task']
 ids=state['children'].get(id,[])
 return {'id':id,'status':task['status'],'child_ids':ids,'children':[node(child) for child in ids],'prerequisites':state['parents'].get(id,[])}
if action=='project_admit':
 identity,_=initialize_identity(Path(root),native_authority=r.get('native_authority'))
 workspace=Path(root)/identity['workspace_path']
 if not workspace.exists():
  subprocess.run([sys.executable,str(Path(__file__).with_name('workflow')/'init_workspace.py'),'--root',str(workspace),'--target','Native fixture','--why','Qualify native context without a model','--parent-authority','Explicit fixture qualification'],check=True,capture_output=True)
 if Path(__file__).with_name('project-drift').exists(): identity['board_id']='changed-board'
 result={'project_root':root,'identity':identity}
elif action=='show':
 result=shown(r['task_id'])
elif action=='create':
 key=r.get('idempotency_key','')
 id=state['keys'].get(key)
 if not id:
  id='fixture-card-'+str(len(state['tasks']))
  state['tasks'][id]={'id':id,'title':r['title'],'body':r.get('body',''),'status':r.get('initial_status','triage'),'priority':r.get('priority',0)}
  if key: state['keys'][key]=id
 result=shown(id)
elif action=='comment':
 state['comments'].setdefault(r['task_id'],[]).append({'body':r['comment']})
 result=shown(r['task_id'])
elif action=='hierarchy':
 result={'root':node(r['task_id']),'truncated':False}
elif action=='decompose':
 ids=[]
 for child in r['children']:
  id='fixture-card-'+str(len(state['tasks']))
  state['tasks'][id]={'id':id,'title':child['title'],'body':child.get('body',''),'status':'ready','priority':0}
  ids.append(id)
 state['children'][r['task_id']]=ids
 state['parents'][r['task_id']]=ids
 state['tasks'][r['task_id']]['status']='todo'
 result={'root':node(r['task_id']),'truncated':False}
elif action=='move':
 state['tasks'][r['task_id']]['status']={'block':'blocked','unblock':'ready','complete':'done'}[r['transition']]
 result=shown(r['task_id'])
else: result={'results':[]}
store.write_text(json.dumps(state))
print(json.dumps({'schema':'pi-kanban-result/v1','ok':True,'action':action,'result':result}))
`);
const toolHelper = path.join(fixture, 'fixture-tool-query.py');
fs.writeFileSync(toolHelper, "import json; print(json.dumps({'ok':True,'results':[]}))\n");
const skill = path.join(agentDir, 'skills', 'supervised-tasks', 'SKILL.md');
fs.mkdirSync(path.dirname(skill), { recursive: true });
fs.writeFileSync(skill, '# Supervised tasks\n\nUse a declared action, output and independent check.\n');
json(path.join(workflow, 'everyday-runtime.json'), {
  python: options.python, runtime: fixture,
  runtime_manifest_sha256: '0'.repeat(64), engine_sha256: '0'.repeat(64),
  helper_sha256: hash(path.join(workflow, 'everyday_workflow.py')),
});
const boardAdapter = options['board-python'] ? path.join(workflow, 'pi_kanban.py') : backend;
Object.assign(process.env, {
  PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PI_CODING_AGENT_DIR: agentDir,
  PI_PROJECT_KANBAN_PYTHON: options['board-python'] || options.python, PI_PROJECT_KANBAN_ADAPTER: boardAdapter,
  PI_PROJECT_KANBAN_ADAPTER_SHA256: hash(boardAdapter),
  PI_PROJECT_STATE_BASE: path.join(fixture, 'project-state'), HERMES_HOME: path.join(fixture, 'hermes-home'),
  PI_PROJECT_CONTEXT_PI_PACKAGE: fs.realpathSync(options['pi-package']),
  PI_SYSTEM_TOOL_PYTHON: options.python, PI_SYSTEM_TOOL_HELPER: toolHelper,
  PI_SYSTEM_TOOL_HELPER_SHA256: hash(toolHelper),
  PI_SYSTEM_TOOL_DATABASE: path.join(fixture, 'fixture-tools.sqlite'),
});
if (options['framework-python']) {
  const binding = path.join(fixture, 'framework-binding.json');
  const generated = spawnSync(options['framework-python'], ['-B', path.join(intake, 'framework_binding.py'), '--output', binding],
    { encoding: 'utf8', env: process.env, timeout: 30000 });
  assert.equal(generated.status, 0, generated.stdout + generated.stderr);
  const value = JSON.parse(generated.stdout);
  assert.equal(value.ok, true);
  process.env.PI_FRAMEWORK_BINDING = binding;
  process.env.PI_FRAMEWORK_BINDING_SHA256 = value.sha256;
}
const sdk = await import(pathToFileURL(path.join(fs.realpathSync(options['pi-package']), 'dist/index.js')));
const settings = sdk.SettingsManager.inMemory({
  extensions: names.map((name) => path.join(workflow, name)),
  defaultTools: ['read', 'ls', 'find', 'grep'], cacheWarming: 'off',
});
const loader = new sdk.DefaultResourceLoader({
  cwd: project, agentDir, settingsManager: settings,
  noSkills: true, noPromptTemplates: true, noThemes: true,
  disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'],
});
await loader.reload();
const loaded = loader.getExtensions();
assert.deepEqual(loaded.errors, [], 'Actual native resource loader reported errors');
assert.equal(loaded.extensions.length, names.length, 'Every selected extension must load');
const extensionTools = loaded.extensions.flatMap((extension) => [...extension.tools.keys()]);
for (const name of ['agent_capabilities', 'system_tool_query', 'project_admit', 'kanban_select', 'workflow_step',
  'project_context', 'kanban_intake_status', 'kanban_intake_route', 'kanban_work_checkpoint', 'kanban_dependency_resolve']) {
  assert.ok(extensionTools.includes(name), `Native tool not registered: ${name}`);
}
const sessionManager = sdk.SessionManager.inMemory(project);
const model = {
  id: 'fixture-no-inference', name: 'No inference fixture', api: 'openai-completions',
  provider: 'fixture-local', baseUrl: 'http://127.0.0.1:1/v1', reasoning: false,
  input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow: 32768, maxTokens: 4096,
};
const { session } = await sdk.createAgentSession({
  cwd: project, agentDir, settingsManager: settings, resourceLoader: loader,
  sessionManager, model, thinkingLevel: 'off',
});
const errors = [];
await session.bindExtensions({ onError: (error) => errors.push(error) });
let calls = 0;
let lastToolMessage;
async function tool(name, input, allowError = false) {
  const runner = session.extensionRunner;
  const id = `probe-${++calls}`;
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!blocked?.block, `${name} blocked: ${blocked?.reason}`);
  const registered = runner.getAllRegisteredTools().find((item) => item.definition.name === name);
  const native = registered ? sdk.wrapRegisteredTool(registered, runner) : sdk.createReadTool(project);
  const result = await native.execute(id, input, new AbortController().signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id,
    toolName: name, input, ...result, isError: result.isError === true });
  const final = { ...result, ...changed };
  lastToolMessage = { role: 'toolResult', toolCallId: id, toolName: name,
    content: structuredClone(final.content), details: structuredClone(final.details),
    isError: final.isError === true, timestamp: Date.now() };
  if (!allowError) assert.ok(!final.isError, `${name} returned an error: ${JSON.stringify(final)}`);
  return final;
}
async function admission() {
  return session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: 'admission',
    toolName: 'workflow_step', input: { objective: 'Fixture only', cwd: projectScope, required_skills: [] } });
}
async function status() { return (await tool('kanban_intake_status', {})).details.result; }
async function capture(text, source = 'interactive') {
  await session.extensionRunner.emitInput(text, undefined, source);
  return (await status()).pending.at(-1)?.id;
}
async function route(text, parts, control) {
  const source_id = await capture(text);
  assert.ok(source_id, 'Native input must create a captured source');
  return tool('kanban_intake_route', { source_id, parts, ...(control ? { control } : {}) });
}
const contextDeliveries = [];
async function loadContext(checkSameBatch = false) {
  const documents = [];
  for (let count = 0; count < 32; count++) {
    const observed = await tool('project_context', { path: projectScope });
    const message = structuredClone(lastToolMessage);
    assert.equal(observed.details.scope, projectScope, 'Use the actual nested project scope');
    assert.ok(Buffer.byteLength(observed.content[0].text) <= 32768, 'Context delivery must stay bounded');
    if (checkSameBatch && count === 0) {
      const beforeDelivery = await admission();
      assert.equal(beforeDelivery?.block, true, 'Reading context in the same tool batch must not unlock execution');
      assert.match(beforeDelivery.reason, /context/i);
    }
    documents.push(...observed.details.documents);
    const consumed = await session.extensionRunner.emitContext([message]);
    assert.ok(consumed.some((entry) => entry.role === 'toolResult'
      && entry.toolCallId === message.toolCallId && entry.content[0].text === message.content[0].text),
      'The exact returned context body must pass through the actual later context hook');
    if (!observed.details.remaining_reads.length) break;
    assert.ok(count < 31, 'Context did not finish within the bounded fixture read count');
  }
  const repeated = await tool('project_context', { path: projectScope });
  assert.deepEqual(repeated.details.documents, [], 'Native-injected or unchanged delivered context must not be repeated');
  assert.deepEqual(repeated.details.remaining_reads, []);
  const prompt = session.extensionRunner.createContext().getSystemPrompt();
  const native = loader.getAgentsFiles().agentsFiles.filter((entry) => entry.path.startsWith(project + path.sep)
    && prompt.includes(entry.path) && prompt.includes(entry.content));
  for (const injected of native) assert.ok(!documents.some((document) => document.path === injected.path),
    'Exact native-injected instructions must not be emitted again by project_context');
  contextDeliveries.push({ delivered: documents.length, native_injected: native.length,
    repeated_documents: repeated.details.documents.length });
  return documents;
}
async function discover(includeContext = true) {
  await tool('agent_capabilities', {});
  await tool('system_tool_query', { terms: 'fixture' });
  await tool('project_knowledge_query', { terms: 'fixture' });
  // Explicit memory fixture, without starting MCP processes or a model.
  await session.extensionRunner.emitToolResult({ type: 'tool_result', toolCallId: 'fixture-memory',
    toolName: 'validated_memory_query', input: {}, content: [],
    details: { schema: 'validated-memory-query/v1', results: [], reason: 'no_current_provenanced_result', fixture: true }, isError: false });
  await tool('read', { path: skill });
  if (includeContext) await loadContext();
}
async function settle() {
  return session.extensionRunner.emitBoundary({ type: 'agent_before_settle', outcome: 'completed' },
    (entries) => ({ contextEntries: [], contextMessages: [], llmMessages: [], pendingMessages: [], canContinue: entries.length > 0 }));
}
const extraChecks = [];
try {
  const beforeStart = await session.extensionRunner.emitBeforeAgentStart(
    { messageType: 'user', prompt: 'Fixture startup', images: [] },
    { cwd: project, tools: [], forceSystemPrompt: 'Fixture system prompt' });
  assert.match(beforeStart.systemPromptOptions.forceSystemPrompt, /Everyday work:/,
    'Native startup must include the supervised-work policy');
  assert.equal((await admission())?.block, true, 'Unselected work must fail closed');
  await tool('project_admit', { project_root: project, initialize: true,
    native_authority: 'Explicit isolated native package qualification; no product or model workload',
    target: 'Disposable native adapter fixture', why: 'Verify exported Pi, board and intake composition without inference' });
  const unadmitted = await tool('kanban_create', { title: 'Unadmitted native fixture card', initial_status: 'ready' });
  const unadmittedId = unadmitted.details.result.task.id;
  const ownerText = 'Create a fixture artifact and verify its exact content. Keep its root outcome open until verified.';
  const sourceId = await capture(ownerText);
  assert.ok(sourceId, 'Native owner input must be captured');
  assert.equal((await admission())?.block, true, 'Unrouted owner input must block execution');
  const fullSource = (await tool('kanban_intake_status', { source_id: sourceId })).details.result.source;
  assert.equal(fullSource.text, ownerText, 'Exact native source text must survive capture');
  const routed = await tool('kanban_intake_route', { source_id: sourceId,
    parts: [{ kind: 'task', summary: ownerText, execute: true }] });
  const taskA = routed.details.result.bound[0].task_id;
  assert.ok(taskA, 'Routing must bind an actual fixture card');
  const replay = await tool('kanban_intake_route', { source_id: sourceId,
    parts: [{ kind: 'task', summary: ownerText, execute: true }] });
  assert.equal(replay.details.result.replay, true, 'Exact routing replay must not create duplicate work');
  assert.equal((await admission())?.block, true, 'Selection must not bypass discovery');
  await discover(false);
  assert.equal((await admission())?.block, true, 'Routing must preserve the old selection and refuse its unrelated scope');
  await tool('kanban_select', { task_id: taskA });
  const contextDocuments = await loadContext(true);
  assert.ok(contextDocuments.some((document) => document.path === path.join(projectScope, 'AGENTS.md')),
    'The nested directory instructions must reach native model-input context');
  const firstAdmission = await admission();
  assert.ok(!firstAdmission?.block, 'Ready work must be admitted without a Codex adviser: ' + JSON.stringify({
    admission: firstAdmission, intake: await status(), bound_task: taskA,
    selection: sessionManager.getBranch().filter((entry) => entry.type === 'custom'
      && entry.customType === 'pi-kanban-selection/v1').at(-1)?.data,
  }));
  await tool('kanban_select', { task_id: unadmittedId });
  assert.equal((await admission())?.block, true, 'A manually selected ready card must not inherit unrelated source authority');
  await tool('kanban_select', { task_id: taskA });
  assert.ok(!(await admission())?.block, 'Returning to the exact source-bound card must restore admission');
  const selection = sessionManager.getBranch().filter((entry) => entry.type === 'custom'
    && entry.customType === 'pi-kanban-selection/v1').at(-1);
  assert.equal(selection?.data?.task?.cardId, taskA, 'Native journal must retain selection');
  const beforePeer = (await status()).pending_total;
  await session.extensionRunner.emitInput('Peer message is not owner approval', undefined, 'extension');
  assert.equal((await status()).pending_total, beforePeer, 'Extension input must not become fresh owner scope');
  extraChecks.push('native-source-capture', 'unrouted-input-refusal', 'idempotent-source-routing', 'peer-source-refusal', 'unadmitted-selection-refusal');
  extraChecks.push('hierarchical-project-context', 'same-batch-context-refusal', 'unchanged-context-deduplication');
  if (options['framework-python']) {
    const boundary = await settle();
    assert.equal(boundary.continue, true, 'Actual Framework helper must retain authorized ready work');
    assert.ok(boundary.entries.some((entry) => entry.customType === 'pi-work-continuation/v1'));
    extraChecks.push('real-framework-native-settlement');
  }
  await tool('kanban_move', { task_id: taskA, transition: 'block', reason: 'Native negative control' });
  assert.equal((await admission())?.block, true, 'Live blocked state must override retained selection');
  await tool('kanban_move', { task_id: taskA, transition: 'unblock', reason: 'End native negative control' });
  await session.reload();
  assert.equal((await admission())?.block, true, 'Reload must recheck discovery even with restored selection');
  await discover();
  assert.ok(!(await admission())?.block, 'Reload must restore the validated project and card without a new selection');
  assert.equal((await status()).retained_total, 1, 'Native reload must retain the original source-bound outcome');
  const compound = await route('Complete the fixture compound outcome through its contained leaf.',
    [{ kind: 'task', summary: 'Fixture compound outcome', execute: true, expandable: true }]);
  const compoundRoot = compound.details.result.bound[0].task_id;
  const decomposition = await tool('kanban_decompose', { task_id: compoundRoot,
    children: [{ title: 'Contained fixture leaf', body: 'Produce the exact fixture artifact and verify it' }] });
  const child = decomposition.details.result.root.children[0].id;
  await tool('kanban_select', { task_id: child });
  assert.ok(!(await admission())?.block, 'Contained ready child must inherit its explicit source-bound root scope');
  await tool('kanban_select', { task_id: taskA });
  extraChecks.push('contained-child-source-inheritance');
  await route('Pause this work until I explicitly resume it.', [{ kind: 'control', summary: 'Explicit owner pause' }], 'pause');
  assert.equal((await status()).mode, 'paused');
  assert.equal((await admission())?.block, true, 'Owner pause must block task execution');
  await route('What is its current status?', [{ kind: 'question', summary: 'Status question only' }]);
  assert.equal((await status()).mode, 'paused', 'Ordinary input must not clear a pause');
  await session.reload();
  assert.equal((await status()).mode, 'paused', 'Reload must preserve the explicit owner pause');
  assert.equal((await settle()).continue, false, 'Paused settlement must not inject continuation');
  await route('Resume the authorized fixture work.', [{ kind: 'control', summary: 'Explicit owner resume' }], 'resume');
  await discover();
  assert.ok(!(await admission())?.block);
  extraChecks.push('native-pause', 'ordinary-input-preserves-pause', 'reload-preserves-pause', 'paused-settlement-quiet', 'explicit-resume');
  const waited = await tool('kanban_work_checkpoint', { disposition: 'waiting', wait_scope: 'task', waiting_for: 'peer',
    reason: 'Fixture task A needs an external result', resume_trigger: 'Exact fixture dependency is verified' });
  const waitA = waited.details.result.wait_id;
  assert.ok(waitA);
  assert.equal((await admission())?.block, true, 'A task dependency must block its selected task');
  const other = await route('Also perform the independent fixture task B.',
    [{ kind: 'task', summary: 'Independent fixture B', execute: true }]);
  const taskB = other.details.result.bound[0].task_id;
  await tool('kanban_select', { task_id: taskB });
  assert.ok(!(await admission())?.block, 'Independent source-bound work must remain available during task A wait');
  await tool('kanban_dependency_resolve', { wait_id: waitA, evidence: 'Fixture dependency A observed complete' });
  extraChecks.push('task-wait-refusal', 'independent-task-during-wait', 'exact-wait-resolution');
  const receipt = path.join(project, 'fixture-result.json');
  const receiptWait = await tool('kanban_work_checkpoint', { disposition: 'waiting', wait_scope: 'task', waiting_for: 'external',
    reason: 'Wait for the exact fixture job', resume_trigger: 'Job fixture-job is complete',
    receipt: { path: receipt, equals: { job_id: 'fixture-job', status: 'complete' } } });
  const waitB = receiptWait.details.result.wait_id;
  const premature = await tool('kanban_dependency_resolve', { wait_id: waitB, evidence: 'Unverified free text' }, true);
  assert.equal(premature.isError, true, 'Free text must not resolve a missing registered receipt');
  // Pause before the event so this no-model probe cannot request inference.
  await route('Pause while the external fixture job settles.', [{ kind: 'control', summary: 'Pause before receipt event' }], 'pause');
  json(receipt + '.new', { job_id: 'fixture-job', status: 'complete' });
  fs.renameSync(receipt + '.new', receipt);
  const receiptDeadline = Date.now() + 5000;
  let receiptStatus;
  while (Date.now() < receiptDeadline) {
    receiptStatus = await status();
    if (receiptStatus.task_waits.some((wait) => wait.id === waitB && wait.status === 'resolved')) break;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  const resolved = receiptStatus.task_waits.find((wait) => wait.id === waitB);
  assert.equal(resolved?.status, 'resolved', 'Native file event must verify the exact atomic receipt');
  assert.equal(resolved.notice, undefined, 'Paused receipt must not send a continuation notification');
  assert.equal(session.pendingMessageCount, 0, 'Paused receipt must not queue model input');
  assert.equal(receiptStatus.mode, 'paused', 'Receipt must preserve the explicit owner pause');
  extraChecks.push('receipt-missing-refusal', 'atomic-receipt-event', 'receipt-preserves-pause', 'receipt-no-model-wakeup');
  const rawShell = await session.extensionRunner.emitToolCall({ type: 'tool_call',
    toolCallId: 'raw-shell', toolName: 'bash', input: { command: 'echo bypass' } });
  assert.equal(rawShell?.block, true, 'Raw shell must remain gated after reload');
  await route('Resume the fixture after its dependency proof.', [{ kind: 'control', summary: 'Explicit resume after receipt proof' }], 'resume');
  assert.ok(!(await admission())?.block, 'Completed receipt and explicit resume must preserve usable work');
  if (options['board-python']) {
    const identityPath = path.join(project, '.icm/project.json');
    const identity = JSON.parse(fs.readFileSync(identityPath, 'utf8'));
    identity.board_id = 'changed-board';
    json(identityPath, identity);
  } else fs.writeFileSync(path.join(fixture, 'project-drift'), 'changed identity');
  await session.reload();
  const drift = await admission();
  assert.equal(drift?.block, true, 'Changed project identity must refuse saved navigation');
  assert.match(drift?.reason, /admi(t|ssion)|Select the project task/i, 'Changed identity must leave no executable selection');
  if (options['board-python']) {
    const refused = await tool('project_admit', { project_root: project }, true);
    assert.equal(refused.isError, true, 'Actual backend must independently refuse the changed project identity');
    extraChecks.push('real-board-identity-refusal');
  }
  assert.deepEqual(errors, [], 'Native lifecycle must report no extension errors');
  console.log(JSON.stringify({ status: 'passed', fixture, pi_version: JSON.parse(
    fs.readFileSync(path.join(options['pi-package'], 'package.json'), 'utf8')).version,
    extension_count: loaded.extensions.length, registered_tools: extensionTools.sort(),
    checks: ['native-loader', 'native-sdk-session', 'native-startup-policy', 'required-tools', 'no-adviser-admission',
      'discovery-refusal', 'live-card-refusal', 'native-journal', 'reload-discovery-refusal',
      'reload-selection-restore', 'raw-shell-refusal', 'identity-drift-refusal', ...extraChecks], model_calls: 0,
    framework_native: Boolean(options['framework-python']),
    board_native: Boolean(options['board-python']),
    project_context_document_counts: contextDeliveries,
    elapsed_ms: Date.now() - startedAt,
    limits: 'Actual Pi loader/session; optional actual Framework and isolated Hermes board. Memory readiness is explicit fixture data. No memory health, task execution, unpaused model wakeup or model quality claim.' }, null, 2));
} finally {
  session.dispose();
}
