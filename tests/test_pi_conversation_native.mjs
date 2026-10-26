/** Actual native conversation/retained-work controls. No model, HTTP or services. */
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1]);
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['source', 'pi-package', 'hermes-python', 'framework-python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
assert.equal(Boolean(options['reference-intake']), Boolean(options['reference-sha256']));
const source = fs.realpathSync(options.source), pkg = fs.realpathSync(options['pi-package']);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-conversation-'));
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const write = (file, value) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n'); };
const envBefore = { ...process.env }, fetchBefore = globalThis.fetch;
for (const name of Object.keys(process.env)) if (!['HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TMP', 'TEMP'].includes(name)) delete process.env[name];
Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' });
let http = 0, sequence = 0;
globalThis.fetch = async () => { http++; throw new Error('Native conversation test forbids HTTP'); };
const sdk = await import(pathToFileURL(path.join(pkg, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg, 'package.json'))).version, '1.4.0');
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const model = { id: 'fixture-no-inference', name: 'No inference', provider: 'fixture-local', api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/v1',
  reasoning: false, input: ['text'], contextWindow: 32768, maxTokens: 4096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const profiles = [], checks = [], trace = [];
function check(name, value, details = {}) { checks.push({ name, passed: Boolean(value), ...details }); assert.ok(value, name); }
function copy(from, to) {
  fs.mkdirSync(to, { recursive: true });
  for (const item of fs.readdirSync(from, { withFileTypes: true })) {
    if (item.name === '__pycache__') continue;
    assert.ok(!item.isSymbolicLink());
    if (item.isDirectory()) copy(path.join(from, item.name), path.join(to, item.name));
    else if (/\.(py|ts|mjs|md|json)$/.test(item.name)) fs.copyFileSync(path.join(from, item.name), path.join(to, item.name));
  }
}
async function profile(label, reference = false, existing) {
  const base = path.join(fixture, label), prior = existing ? fs.realpathSync(existing) : base;
  const runtime = path.join(prior, 'runtime'), agentDir = path.join(prior, 'agent'), project = path.join(prior, 'project');
  fs.mkdirSync(base, { recursive: true });
  if (existing) {
    assert.equal(hash(path.join(runtime, 'adapters/pi/intake/request-intake-138.ts')), hash(path.join(source, 'adapters/pi/intake/request-intake-138.ts')));
    assert.equal(hash(path.join(runtime, 'adapters/pi/project-workflow/pi_kanban.py')), hash(path.join(source, 'adapters/pi/project-workflow/pi_kanban.py')));
    assert.ok(fs.existsSync(path.join(project, '.icm/knowledge-sources.json')));
    const identity = JSON.parse(fs.readFileSync(path.join(project, '.icm/project.json')));
    assert.ok(fs.existsSync(path.join(identity.state_root, 'kanban.db')) && fs.existsSync(path.join(identity.state_root, 'knowledge.db')));
  } else {
    for (const dir of [runtime, agentDir, project]) fs.mkdirSync(dir, { recursive: true });
    for (const name of ['harness', 'ssot', 'adapters/pi']) copy(path.join(source, name), path.join(runtime, name));
  }
  const workflow = path.join(runtime, 'adapters/pi/project-workflow'), intake = path.join(runtime, 'adapters/pi/intake');
  if (reference) {
    assert.equal(hash(options['reference-intake']), options['reference-sha256']);
    fs.copyFileSync(options['reference-intake'], path.join(intake, 'request-intake-138.ts'));
  }
  if (!existing) fs.writeFileSync(path.join(project, 'AGENTS.md'), '# Synthetic native conversation fixture\n\nPreserve approved work and independent holds.\n');
  const binding = path.join(base, 'framework-binding.json');
  const generated = spawnSync(options['framework-python'], ['-B', path.join(intake, 'framework_binding.py'), '--output', binding],
    { encoding: 'utf8', env: process.env, timeout: 30000 });
  assert.equal(generated.status, 0, generated.stderr + generated.stdout);
  const adapter = path.join(base, 'observed-native-board.py'), requests = path.join(base, 'board-requests.jsonl');
  fs.writeFileSync(adapter, `import json,sys,time,runpy,io,contextlib
from pathlib import Path
r=json.load(sys.stdin)
b=Path(__file__).parent
with (b/'board-requests.jsonl').open('a') as f:f.write(json.dumps(r)+'\\n')
if r['action']=='show' and (b/'hold-next-show').exists():
 (b/'show-entered').write_text('entered')
 end=time.monotonic()+15
 while (b/'hold-next-show').exists() and time.monotonic()<end:time.sleep(.01)
 if (b/'hold-next-show').exists():raise TimeoutError('Owned read-only barrier')
sys.path.insert(0,${JSON.stringify(workflow)})
sys.stdin=io.TextIOWrapper(io.BytesIO(json.dumps(r).encode()))
if r['action']=='create' and (b/'lose-next-create').exists():
 captured=io.StringIO()
 with contextlib.redirect_stdout(captured):
  try:runpy.run_path(${JSON.stringify(path.join(workflow, 'pi_kanban.py'))},run_name='__main__')
  except SystemExit as error:
   if error.code not in (0,None):raise
 assert json.loads(captured.getvalue())['ok'] is True
 (b/'lose-next-create').unlink()
 print('Controlled lost reply AFTER real native create',file=sys.stderr)
 raise SystemExit(1)
runpy.run_path(${JSON.stringify(path.join(workflow, 'pi_kanban.py'))},run_name='__main__')
`);
  const environment = { PI_CODING_AGENT_DIR: agentDir, PI_PROJECT_KANBAN_PYTHON: options['hermes-python'], PI_PROJECT_KANBAN_ADAPTER: adapter,
    PI_PROJECT_KANBAN_ADAPTER_SHA256: hash(adapter), PI_PROJECT_STATE_BASE: path.join(prior, 'state/projects'), HERMES_HOME: path.join(prior, 'hermes'),
    PI_PROJECT_CONTEXT_PI_PACKAGE: pkg, PI_FRAMEWORK_BINDING: binding, PI_FRAMEWORK_BINDING_SHA256: JSON.parse(generated.stdout).sha256 };
  Object.assign(process.env, environment);
  const settings = sdk.SettingsManager.inMemory({ extensions: [path.join(workflow, 'pi-kanban.ts')], defaultTools: [], cacheWarming: 'off' });
  const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings, noSkills: true, noPromptTemplates: true,
    noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
  await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
  const sessionFiles = existing ? fs.readdirSync(path.join(agentDir, 'sessions')).filter(name => name.endsWith('.jsonl')) : [];
  if (existing) assert.ok(sessionFiles.length <= 1);
  const oldSession = existing && sessionFiles.length ? path.join(agentDir, 'sessions', sessionFiles[0]) : undefined;
  const before = existing ? { identity_sha256: hash(path.join(project, '.icm/project.json')),
    agents_sha256: hash(path.join(project, 'AGENTS.md')), ssot_sha256: hash(path.join(project, '.icm/workspace/PROJECT-SSOT.md')),
    session_file: oldSession ?? null, session_bytes: oldSession ? fs.readFileSync(oldSession) : undefined,
    session_sha256: oldSession ? hash(oldSession) : null, original_native_session_files: sessionFiles.length,
    board_path: path.join(JSON.parse(fs.readFileSync(path.join(project, '.icm/project.json'))).state_root, 'kanban.db'),
    board_sha256: hash(path.join(JSON.parse(fs.readFileSync(path.join(project, '.icm/project.json'))).state_root, 'kanban.db')),
    knowledge_sha256: hash(path.join(JSON.parse(fs.readFileSync(path.join(project, '.icm/project.json'))).state_root, 'knowledge.db')) } : undefined;
  const manager = oldSession ? sdk.SessionManager.open(oldSession)
    : sdk.SessionManager.create(project, path.join(existing ? base : agentDir, 'sessions'));
  const { session } = await sdk.createAgentSession({ cwd: project, agentDir, settingsManager: settings, resourceLoader: loader,
    sessionManager: manager, modelRuntime, model, thinkingLevel: 'off' });
  const errors = []; await session.bindExtensions({ onError: error => errors.push(String(error)) });
  const p = { label, base, runtime, agentDir, project, environment, loader, settings, manager, session, errors, requests, reference, before };
  profiles.push(p); return p;
}
function activate(p) { Object.assign(process.env, p.environment); }
const snapshot = p => structuredClone([...p.manager.getBranch()].reverse().find(entry => entry.customType === 'pi-request-work-state/v1')?.data);
const calls = p => fs.existsSync(p.requests) ? fs.readFileSync(p.requests, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
async function tool(p, name, input, allowError = false) {
  activate(p); const runner = p.session.extensionRunner, id = 'conversation-' + (++sequence);
  const held = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!held?.block, name + ': ' + held?.reason);
  const found = runner.getAllRegisteredTools().find(item => item.definition.name === name); assert.ok(found, name);
  const raw = await sdk.wrapRegisteredTool(found, runner).execute(id, input, new AbortController().signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...raw, isError: raw.isError === true });
  const value = { ...raw, ...changed }; trace.push({ profile: p.label, name, input, value });
  if (!allowError) assert.ok(!value.isError, JSON.stringify(value)); return value;
}
async function capture(p, text) {
  activate(p); p.manager.appendMessage({ role: 'user', content: [{ type: 'text', text }], timestamp: Date.now() });
  await p.session.extensionRunner.emitInput(text, undefined, 'interactive');
  return [...p.manager.getBranch()].reverse().find(entry => entry.customType === 'pi-request-capture/v1').data.id;
}
async function answer(p, text = 'Controlled ordinary status answer; original work is not complete.') {
  activate(p); p.manager.appendMessage({ role: 'assistant', api: model.api, provider: model.provider, model: model.id, usage: structuredClone(usage),
    content: [{ type: 'text', text }], stopReason: 'stop', timestamp: Date.now() }); p.session.refreshContext();
  const boundary = await p.session.extensionRunner.emitBoundary({ type: 'agent_before_settle', outcome: 'completed' },
    entries => ({ contextEntries: [], contextMessages: [], llmMessages: [], pendingMessages: [], canContinue: entries.length > 0 }));
  trace.push({ profile: p.label, boundary, state: snapshot(p) }); return boundary;
}
async function approved(p) {
  if (!p.admitted) await tool(p, 'project_admit', { project_root: p.project, initialize: true,
    native_authority: 'Owner authorized only this isolated native no-model conversation qualification', target: 'Retain approved fixture task', why: 'Compare ordinary status questions and independent holds' });
  const id = await capture(p, 'Execute only the authorized fixture task A. Retain it until the declared output is verified.');
  await tool(p, 'kanban_intake_route', { source_id: id, parts: [{ kind: 'task', summary: 'Approved task A with useful output still pending', execute: true }] });
  p.task = snapshot(p).queue[0].task; return id;
}
async function reopen(p) {
  activate(p); const file = p.manager.getSessionFile(), before = fs.readFileSync(file);
  await p.session.extensionRunner.emit({ type: 'session_shutdown' }); p.session.dispose();
  p.manager = sdk.SessionManager.open(file); await p.loader.reload();
  const { session } = await sdk.createAgentSession({ cwd: p.project, agentDir: p.agentDir, settingsManager: p.settings, resourceLoader: p.loader,
    sessionManager: p.manager, modelRuntime, model, thinkingLevel: 'off' });
  p.session = session; await session.bindExtensions({ onError: error => p.errors.push(String(error)) });
  check(p.label + '-reopen-preserves-native-history-prefix', fs.readFileSync(file).subarray(0, before.length).equals(before));
}
async function boundaryCase(r) {
  await approved(r);
  const amendment = await capture(r, 'Amend only the approved task A with this reviewed context.');
  fs.writeFileSync(path.join(r.base, 'hold-next-show'), 'read barrier');
  const inFlight = tool(r, 'kanban_intake_route', { source_id: amendment, parts: [{ kind: 'amend', task_id: r.task, summary: 'Owner supplied scoped context for A', execute: true }] }, true);
  const deadline = Date.now() + 10000;
  while (!fs.existsSync(path.join(r.base, 'show-entered')) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(fs.existsSync(path.join(r.base, 'show-entered')));
  await capture(r, 'Status only, before committing any new amendment.'); fs.unlinkSync(path.join(r.base, 'hold-next-show'));
  const raced = await inFlight;
  check('superseded-during-read-validation-does-not-write-amendment', raced.isError === true && !calls(r).some(call => call.action === 'comment'));
}
let failure;
try {
  if (options.case === 'current-intent') {
    assert.ok(options['reference-intake'], 'Bind the exact main63 predecessor');
    const p = await profile('current-intent-differential', true); await approved(p);
    const first = p.task, originalSource = snapshot(p).queue[0].source;
    const approval = await capture(p, 'Owner explicitly approves independent task B now. Keep the older approved task A.');
    const parts = [{ kind: 'task', summary: 'Current approved task B', execute: true }];
    await tool(p, 'kanban_intake_route', { source_id: approval, parts });
    const second = snapshot(p).queue.find(item => item.source === approval).task;
    const selection = () => p.manager.getBranch().findLast(entry => entry.customType === 'pi-kanban-selection/v1').data.task.cardId;
    check('exact-main63-native-counterexample-keeps-stale-A-after-approved-B', selection() === first && first !== second);
    const predecessor = { session_sha256: hash(p.manager.getSessionFile()), intake_sha256: hash(path.join(p.runtime, 'adapters/pi/intake/request-intake-138.ts')) };
    fs.copyFileSync(path.join(source, 'adapters/pi/intake/request-intake-138.ts'), path.join(p.runtime, 'adapters/pi/intake/request-intake-138.ts'));
    await reopen(p);
    await tool(p, 'kanban_intake_route', { source_id: approval, parts });
    check('exact-routed-replay-recovers-current-selection-without-new-card', selection() === second
      && (await tool(p, 'kanban_list', {})).details.result.tasks.length === 2 && snapshot(p).queue.some(item => item.source === originalSource));
    const progress = snapshot(p).progress, queue = JSON.stringify(snapshot(p).queue);
    await capture(p, 'Status only. Answer and keep approved work; unapproved draft D must not start.');
    check('status-question-still-continues-older-approved-queue', (await answer(p)).continue === true
      && JSON.stringify(snapshot(p).queue) === queue && snapshot(p).progress === progress && selection() === second);
    for (const fault of ['none', 'replacement_intent', 'create_lost_reply', 'routed_before_selection']) {
      const id = await capture(p, 'The owner explicitly approves the next isolated fixture task. This original source already gives permission.');
      await tool(p, 'kanban_intake_route', { source_id: id, parts: [{ kind: 'question', summary: 'Controlled erroneous effect-free classification' }] });
      const request = { source_id: id, reclassify_current: true, parts: [{ kind: 'task', summary: 'Approved original-source task ' + fault, execute: true }] };
      const beforeCount = (await tool(p, 'kanban_list', {})).details.result.tasks.length;
      const append = p.manager.appendCustomEntry.bind(p.manager);
      let injected = false;
      if (fault === 'replacement_intent' || fault === 'routed_before_selection') p.manager.appendCustomEntry = (kind, data) => {
        const value = append(kind, data);
        if (!injected && data?.id === id && (fault === 'replacement_intent'
          ? kind === 'pi-request-route-intent/v1' && data.intent.parts.some(part => part.execute)
          : kind === 'pi-request-routed/v1')) { injected = true; throw Error('Controlled crash boundary after native journal append'); }
        return value;
      };
      if (fault === 'create_lost_reply') fs.writeFileSync(path.join(p.base, 'lose-next-create'), 'Controlled post-create lost reply');
      const initial = await tool(p, 'kanban_intake_route', request, fault !== 'none');
      if (fault !== 'none') {
        check(fault + '-retained-injected-failure', initial.isError === true);
        p.manager.appendCustomEntry = append;
        await reopen(p);
        await tool(p, 'kanban_intake_route', request);
      }
      const work = snapshot(p).queue.find(item => item.source === id);
      await tool(p, 'kanban_intake_route', request);
      const branch = p.manager.getBranch();
      check(fault + '-native-correction-recovery-one-card-and-current-selection', work && selection() === work.task
        && (await tool(p, 'kanban_list', {})).details.result.tasks.length === beforeCount + 1
        && branch.some(entry => entry.customType === 'pi-request-classification-correction/v1' && entry.data.id === id)
        && branch.filter(entry => entry.customType === 'pi-request-route-intent/v1' && entry.data.id === id).length === 2);
      const changed = await tool(p, 'kanban_intake_route', { ...request, parts: [{ ...request.parts[0], summary: 'Rewrite frozen effectful intent' }] }, true);
      check(fault + '-effectful-intent-stays-frozen', changed.isError === true);
    }
    const runner = p.session.extensionRunner, ui = runner.getUIContext(); let draft = 'Unsent original owner text';
    runner.setUIContext({ ...ui, getEditorText: () => draft });
    const count = p.manager.getBranch().length;
    check('native-typed-draft-suppresses-bookkeeping-and-preserves-text', !(await answer(p)).continue
      && draft === 'Unsent original owner text' && p.manager.getBranch().length === count + 1); // Only scripted assistant answer.
    draft = ''; await p.session.steer('Queued owner input; no automatic model call.');
    const queuedCount = p.session.pendingMessageCount;
    check('native-queued-input-suppresses-automatic-continuation', queuedCount > 0 && !(await answer(p)).continue && p.session.pendingMessageCount === queuedCount);
    p.session.clearQueue();
    fs.writeFileSync(path.join(p.base, 'hold-next-show'), 'Read-only projection barrier');
    const pending = answer(p), deadline = Date.now() + 10000;
    while (!fs.existsSync(path.join(p.base, 'show-entered')) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
    assert.ok(fs.existsSync(path.join(p.base, 'show-entered')), 'Native projection reached existing show barrier');
    draft = 'Owner typed while retained board projection awaited'; fs.unlinkSync(path.join(p.base, 'hold-next-show'));
    check('native-mid-await-typing-discards-continuation-without-clearing-draft', !(await pending).continue && draft.includes('while retained'));
    runner.setUIContext(ui);
    trace.push({ predecessor, final_intake_sha256: hash(path.join(p.runtime, 'adapters/pi/intake/request-intake-138.ts')),
      limits: 'Old/new source differential and injected native append/lost-reply recovery. UI text uses supported public UI context; no natural editor/model behavior. Final other-handler/core-commit editor race remains open.' });
  } else if (options['boundary-base']) {
    const p = await profile('ready-state-boundary-continuation', false, options['boundary-base']);
    assert.equal(calls(p).filter(call => call.action === 'project_admit').length, 0, 'Do not duplicate an automatic admission');
    await tool(p, 'project_admit', { project_root: p.project });
    p.admitted = true;
    check('one-normal-readonly-admission-no-initialize', calls(p).filter(call => call.action === 'project_admit').length === 1
      && calls(p).find(call => call.action === 'project_admit').initialize === undefined);
    check('ready-state-native-board-starts-with-no-task-replay', (await tool(p, 'kanban_list', {})).details.result.tasks.length === 0);
    await boundaryCase(p);
    check('continuation-preserves-existing-identity-and-instruction-bytes', hash(path.join(p.project, '.icm/project.json')) === p.before.identity_sha256
      && hash(path.join(p.project, 'AGENTS.md')) === p.before.agents_sha256 && hash(path.join(p.project, '.icm/workspace/PROJECT-SSOT.md')) === p.before.ssot_sha256);
    if (p.before.session_file) {
      check('continuation-appends-to-actual-native-history-with-original-prefix', fs.readFileSync(p.before.session_file).subarray(0, p.before.session_bytes.length).equals(p.before.session_bytes));
    } else {
      check('new-native-session-does-not-fabricate-or-rewrite-absent-prior-history', fs.readdirSync(path.join(p.agentDir, 'sessions')).filter(name => name.endsWith('.jsonl')).length === 0
        && p.manager.getSessionFile().startsWith(p.base + path.sep));
    }
    trace.push({ continuation: options['boundary-base'], before: { ...p.before, session_bytes: undefined },
      after_session_sha256: hash(p.manager.getSessionFile()), native_history_scope: p.before.session_file ? 'actual native reopen with original prefix' : 'fresh native session, read-only adoption of existing identity; no prior JSONL existed or was reconstructed', after_board_sha256: hash(p.before.board_path),
      after_tasks: (await tool(p, 'kanban_list', {})).details.result.tasks,
      intake_sha256: hash(path.join(p.runtime, 'adapters/pi/intake/request-intake-138.ts')) });
  } else {
  const q = await profile('question-and-draft');
  const question = await capture(q, 'What does this project do?');
  check('question-without-approved-work-settles-without-forced-tools', !(await answer(q)).continue && calls(q).length === 0);
  const draft = await capture(q, 'Propose a draft plan B for discussion only. Do not implement it.');
  check('draft-without-approved-work-settles-without-card-or-checkpoint', !(await answer(q, 'Controlled draft B, awaiting owner approval.')).continue && calls(q).length === 0);
  let state = (await tool(q, 'kanban_intake_status', {})).details.result;
  check('answer-only-deferral-is-durable-neutral-bookkeeping', state.pending_total === 0 && state.deferred_total === 2 && state.progress === 0 && state.retained_total === 0);
  check('deferred-preview-is-bounded-and-retrievable', state.deferred.every(item => item.excerpt.length <= 160)
    && (await tool(q, 'kanban_intake_status', { source_id: draft })).details.result.source.text.includes('Do not implement'));
  const refused = await tool(q, 'kanban_intake_route', { source_id: draft, parts: [{ kind: 'task', summary: 'Unapproved draft B', execute: true }] }, true);
  check('deferred-old-draft-cannot-authorize-work', refused.isError === true && calls(q).length === 0);
  await reopen(q); state = (await tool(q, 'kanban_intake_status', {})).details.result;
  check('reopen-restores-deferred-captures-and-phase', state.deferred_total === 2 && state.conversation.phase === 'discussion'
    && (await tool(q, 'kanban_intake_status', { source_id: question })).details.result.disposition === 'deferred');

  await tool(q, 'project_admit', { project_root: q.project, initialize: true,
    native_authority: 'Owner authorized fresh approval fixture only', target: 'Bind current approval', why: 'Deferred draft is context only' });
  const approval = await capture(q, 'I now approve implementing the discussed task B in this isolated fixture.');
  await tool(q, 'kanban_intake_route', { source_id: approval, parts: [{ kind: 'task', summary: 'Current approved implementation of draft B', execute: true }] });
  const approvedB = snapshot(q).queue[0];
  const shownB = (await tool(q, 'kanban_show', { task_id: approvedB.task })).details.result.task;
  check('fresh-approval-binds-new-task-to-current-source-not-deferred-draft', approvedB.source === approval
    && shownB.body.includes(approval) && !shownB.body.includes(draft));

  const a = await profile('approved-task-status'); await approved(a);
  const originalQueue = JSON.stringify(snapshot(a).queue), progress = snapshot(a).progress;
  const statusId = await capture(a, 'What is the current status? Answer briefly and keep doing the approved task.');
  const statusBoundary = await answer(a);
  check('approved-A-status-answer-continues-existing-source-bound-task', statusBoundary.continue === true
    && JSON.stringify(snapshot(a).queue) === originalQueue && snapshot(a).progress === progress);
  check('status-answer-does-not-promote-new-task', calls(a).filter(call => call.action === 'create').length === 1
    && (await tool(a, 'kanban_intake_status', { source_id: statusId })).details.result.disposition === 'deferred');
  const routedQuestion = await capture(a, 'What is the status again? This is a question only.');
  await tool(a, 'kanban_intake_route', { source_id: routedQuestion, parts: [{ kind: 'question', summary: 'Status question only; no new work' }] });
  check('explicit-question-routing-does-not-manufacture-progress', snapshot(a).progress === progress && (await answer(a)).continue === true
    && JSON.stringify(snapshot(a).queue) === originalQueue);
  const draftId = await capture(a, 'Draft a possible task B. Discuss it; do not start B or cancel A.');
  check('draft-B-does-not-stop-or-replace-approved-A', (await answer(a, 'Controlled draft B only.')).continue === true
    && JSON.stringify(snapshot(a).queue) === originalQueue && calls(a).filter(call => call.action === 'create').length === 1);
  const pause = await capture(a, 'Pause the approved work while we discuss scope.');
  await tool(a, 'kanban_intake_route', { source_id: pause, control: 'pause', parts: [{ kind: 'control', summary: 'Explicit owner pause for scope discussion' }] });
  check('explicit-pause-remains-independent', !(await answer(a)).continue && snapshot(a).mode === 'paused' && JSON.stringify(snapshot(a).queue) === originalQueue);
  await capture(a, 'What is the paused status?');
  check('ordinary-status-does-not-clear-pause', !(await answer(a)).continue && snapshot(a).mode === 'paused');
  await reopen(a); check('reopen-preserves-explicit-pause-and-approved-work', snapshot(a).mode === 'paused' && JSON.stringify(snapshot(a).queue) === originalQueue);

  const hold = await profile('explicit-scope-hold'); await approved(hold);
  const holdQueue = JSON.stringify(snapshot(hold).queue);
  const holdSource = await capture(hold, 'Hold execution until the owner resolves this scope question.');
  await tool(hold, 'kanban_intake_route', { source_id: holdSource, parts: [{ kind: 'control', summary: 'Explicit scope hold pending owner clarification' }] });
  await tool(hold, 'kanban_work_checkpoint', { disposition: 'blocked', reason: 'Owner requested a real scope hold before execution', resume_trigger: 'Owner explicitly resolves and approves the scoped next action' });
  check('explicit-new-scope-hold-preserves-approved-queue-without-continuation', !(await answer(hold)).continue
    && snapshot(hold).mode === 'blocked' && JSON.stringify(snapshot(hold).queue) === holdQueue);
  await capture(hold, 'What is the status of that scope hold?');
  check('status-answer-does-not-clear-explicit-scope-hold', !(await answer(hold)).continue && snapshot(hold).mode === 'blocked');

  const legacy = await profile('legacy-pending-capture');
  const legacyText = 'Synthetic legacy owner request not yet classified; preserve pending scope.';
  const legacyId = randomUUID();
  legacy.manager.appendCustomEntry('pi-request-capture/v1', { id: legacyId, session: legacy.manager.getSessionId(), text: legacyText,
    source: 'interactive', at: Date.now(), project: null, sha256: createHash('sha256').update(JSON.stringify(legacyText)).digest('hex'), images: 0 });
  await legacy.session.extensionRunner.emit({ type: 'session_tree' });
  await capture(legacy, 'Ordinary status question after loading earlier pending work.');
  check('answer-does-not-retrospectively-hide-legacy-unrouted-request', !(await answer(legacy)).continue
    && (await tool(legacy, 'kanban_intake_status', {})).details.result.pending_total === 1);
  await reopen(legacy);
  check('reopen-preserves-legacy-pending-as-pending', (await tool(legacy, 'kanban_intake_status', { source_id: legacyId })).details.result.disposition === 'pending');

  const u = await profile('uncertain-routing'); await tool(u, 'project_admit', { project_root: u.project, initialize: true,
    native_authority: 'Owner authorized this isolated native routing uncertainty test', target: 'Preserve uncertain routing', why: 'No inference or unrelated board' });
  const uncertain = await capture(u, 'Execute one isolated approved task; preserve uncertain effects.');
  const parts = [{ kind: 'task', summary: 'Approved uncertain fixture task', execute: true }];
  fs.writeFileSync(path.join(u.base, 'lose-next-create'), 'controlled lost reply');
  check('actual-native-create-with-lost-reply-is-retained-failure', (await tool(u, 'kanban_intake_route', { source_id: uncertain, parts }, true)).isError === true);
  await capture(u, 'What happened? Do not replay uncertain effects.');
  check('frozen-uncertain-routing-prevents-continuation', !(await answer(u)).continue);
  state = (await tool(u, 'kanban_intake_status', { source_id: uncertain })).details.result;
  check('uncertain-intent-never-hidden-by-conversation-deferral', state.pending_total === 1 && state.disposition === 'pending' && state.frozen_intent.parts[0].summary === parts[0].summary);
  const changed = await tool(u, 'kanban_intake_route', { source_id: uncertain, parts: [{ ...parts[0], summary: 'Changed uncertain intent' }] }, true);
  check('uncertain-intent-change-refuses-before-replay', changed.isError === true);
  await tool(u, 'kanban_intake_route', { source_id: uncertain, parts });
  const listed = (await tool(u, 'kanban_list', {})).details.result;
  check('exact-existing-route-recovery-creates-no-duplicate-task', listed.tasks.length === 1 && snapshot(u).queue.length === 1);

  const r = await profile('read-validation-boundary'); await boundaryCase(r);

  if (options['reference-intake']) {
    const reference = await profile('exact-discussion-reference', true); await approved(reference);
    const queue = JSON.stringify(snapshot(reference).queue);
    await capture(reference, 'What is the current status? Keep the approved work.');
    const boundary = await answer(reference);
    check('exact-reference-status-question-holds-approved-work', boundary.continue === false
      && JSON.stringify(snapshot(reference).queue) === queue && snapshot(reference).conversation.phase === 'discussion');
  }
  }
  check('all-native-extension-errors-empty', profiles.every(p => p.errors.length === 0), { errors: profiles.map(p => p.errors) });
  check('no-provider-model-http-or-service-actions', http === 0);
} catch (error) { failure = String(error?.stack || error); }
finally {
  for (const p of profiles) { activate(p); await p.session.extensionRunner.emit({ type: 'session_shutdown' }); p.session.dispose(); }
  for (const name of Object.keys(process.env)) if (!(name in envBefore)) delete process.env[name];
  Object.assign(process.env, envBefore); globalThis.fetch = fetchBefore;
  const receipt = { schema: 'pi-conversation-native/v1', status: failure ? 'failed' : 'passed', failure, checks, fixture, source,
    probe_sha256: hash(new URL(import.meta.url)), intake_sha256: hash(path.join(source, 'adapters/pi/intake/request-intake-138.ts')),
    reference_sha256: options['reference-sha256'] ?? null, http_attempts: http, model_calls: 0, service_actions: 0,
    scope: 'Actual native Pi input/committed scripted answer/boundary/reopen; real isolated Hermes and Framework. Test-only same-process runpy shim invokes unchanged native adapter bytes, logs requests, delays read validation and loses one post-create reply. Optional ready-state continuation uses one normal read-only admission without initialization. No session.prompt or live-model conversational behavior claim.' };
  write(path.join(fixture, 'receipt.json'), receipt); write(path.join(fixture, 'trace.json'), trace);
  console.log(JSON.stringify(receipt, null, 2)); process.exitCode = failure ? 1 : 0;
}
