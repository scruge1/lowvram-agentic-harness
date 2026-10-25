/** Real Pi workflow/Git composition; no model, service, or external repository. */
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
for (const name of ['pi-package', 'source', 'python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
assert.equal(process.platform, 'linux', 'Native workflow process ownership requires Linux');
const started = Date.now();
const source = fs.realpathSync(options.source);
const python = path.resolve(options.python); // Preserve the selected virtual environment.
const piPackage = fs.realpathSync(options['pi-package']);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-source-checkpoint-'));
const runtime = path.join(fixture, 'runtime');
const agentDir = path.join(fixture, 'agent');
const project = path.join(fixture, 'project with spaces');
const remote = path.join(fixture, 'unused-remote.git');
fs.mkdirSync(runtime); fs.mkdirSync(agentDir); fs.mkdirSync(project);
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const digest = (file) => sha(fs.readFileSync(file));
const writeJson = (file, value) => {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
};
const manifest = [];
function copyTree(relative) {
  for (const item of fs.readdirSync(path.join(source, relative), { withFileTypes: true })) {
    if (item.name === '__pycache__') continue;
    const name = path.join(relative, item.name);
    assert.ok(!item.isSymbolicLink(), `Source symlink is not an admitted runtime file: ${name}`);
    if (item.isDirectory()) copyTree(name);
    else if (/\.(py|ts|md)$/.test(item.name)) {
      const target = path.join(runtime, name);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(path.join(source, name), target);
      manifest.push({ path: name.split(path.sep).join('/'), sha256: digest(target) });
    }
  }
}
for (const directory of ['harness', 'ssot', 'adapters/pi']) copyTree(directory);
const workflow = path.join(runtime, 'adapters/pi/project-workflow');
for (const name of ['pi-task-worker.py', 'pi_native_events.py']) {
  fs.copyFileSync(path.join(workflow, name), path.join(runtime, name));
  manifest.push({ path: name, sha256: digest(path.join(runtime, name)) });
}
writeJson(path.join(runtime, 'runtime-manifest.json'), { files: manifest });
writeJson(path.join(workflow, 'everyday-runtime.json'), {
  python, runtime, runtime_manifest_sha256: digest(path.join(runtime, 'runtime-manifest.json')),
  engine_sha256: digest(path.join(runtime, 'harness/enforcement.py')),
  helper_sha256: digest(path.join(workflow, 'everyday_workflow.py')),
});
const sourceHelper = path.join(runtime, 'harness/source_checkpoint.py');
assert.ok(fs.existsSync(sourceHelper), 'The reviewed source-checkpoint core must exist');
const skillFiles = {};
for (const name of ['supervised-tasks', 'source-control']) {
  const template = path.join(source, 'harness/templates/agent-home/agent/skills', name, 'SKILL.md');
  const target = path.join(agentDir, 'skills', name, 'SKILL.md');
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, fs.readFileSync(template, 'utf8').replaceAll('{{HOME}}', fixture).replaceAll('{{OWNER}}', 'FixtureOwner'));
  skillFiles[name] = target;
}
const postureTemplate = path.join(source, 'harness/templates/agent-home/agent/APPEND_SYSTEM.md');
const posturePath = path.join(agentDir, 'APPEND_SYSTEM.md');
const postureText = fs.readFileSync(postureTemplate, 'utf8')
  .replaceAll('{{HOME}}', fixture).replaceAll('{{OWNER}}', 'FixtureOwner');
fs.writeFileSync(posturePath, postureText);
const git = (...args) => {
  const result = spawnSync('git', ['--literal-pathspecs', '-C', project, ...args], {
    encoding: 'utf8', env: { ...process.env, GIT_TERMINAL_PROMPT: '0', GIT_OPTIONAL_LOCKS: '0' }, timeout: 30000,
  });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
};
let initialized = spawnSync('git', ['init', '--quiet', '--template=', '--initial-branch=native-source-task', project], { encoding: 'utf8' });
assert.equal(initialized.status, 0, initialized.stderr);
initialized = spawnSync('git', ['init', '--quiet', '--bare', '--template=', remote], { encoding: 'utf8' });
assert.equal(initialized.status, 0, initialized.stderr);
git('config', 'user.name', 'Native Fixture');
git('config', 'user.email', 'native-fixture@example.invalid');
git('config', 'core.autocrlf', 'false');
git('remote', 'add', 'origin', remote);
fs.writeFileSync(path.join(project, '.gitignore'), '.icm/\n.pi-workflow/\n.enforcement/\n');
fs.writeFileSync(path.join(project, 'AGENTS.md'), '# Native source fixture\n\nPreserve the source-bound outcome and unrelated Git work.\n');
const sourceFile = path.join(project, 'source.py');
fs.writeFileSync(sourceFile, 'VALUE = 1\n');
const unrelatedFiles = ['unrelated-dirty.py', 'unrelated-staged.py'];
for (const name of unrelatedFiles) fs.writeFileSync(path.join(project, name), 'BASELINE = 1\n');
git('add', '--', '.gitignore', 'AGENTS.md', 'source.py', ...unrelatedFiles);
git('commit', '--quiet', '-m', 'Create isolated native fixture');
const beforeHead = git('rev-parse', 'HEAD').trim();
for (const name of unrelatedFiles) fs.writeFileSync(path.join(project, name), 'UNRELATED = 2\n');
git('add', '--', 'unrelated-staged.py');
const unrelatedBytes = Object.fromEntries(unrelatedFiles.map((name) => [name, fs.readFileSync(path.join(project, name), 'utf8')]));
const originalIndex = git('ls-files', '--stage', '--', ...unrelatedFiles);
const stagedBefore = git('diff', '--cached', '--name-only', '-z');
const checkpointBase = '.icm/workspace/artifacts/source-control';
const inventory = path.join(project, checkpointBase, 'reviewed.json');
const expectedSource = 'VALUE = 42\n';
const sourceVerifier = path.join(fixture, 'verify-source.py');
fs.writeFileSync(sourceVerifier, `from pathlib import Path\nimport sys\np=Path('source.py')\nraise SystemExit(0 if p.is_file() and p.read_text()==${JSON.stringify(expectedSource)} else 1)\n`);
const catalogHelper = path.join(fixture, 'fixture-tool-query.py');
fs.writeFileSync(catalogHelper, "import json; print(json.dumps({'ok':True,'results':[]}))\n");
Object.assign(process.env, {
  PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PI_CODING_AGENT_DIR: agentDir,
  PI_PROJECT_KANBAN_PYTHON: python,
  PI_PROJECT_KANBAN_ADAPTER: path.join(workflow, 'pi_kanban.py'),
  PI_PROJECT_KANBAN_ADAPTER_SHA256: digest(path.join(workflow, 'pi_kanban.py')),
  PI_PROJECT_STATE_BASE: path.join(fixture, 'project-state'), HERMES_HOME: path.join(fixture, 'hermes-home'),
  PI_PROJECT_CONTEXT_PI_PACKAGE: piPackage,
  PI_SYSTEM_TOOL_PYTHON: python, PI_SYSTEM_TOOL_HELPER: catalogHelper,
  PI_SYSTEM_TOOL_HELPER_SHA256: digest(catalogHelper), PI_SYSTEM_TOOL_DATABASE: path.join(fixture, 'fixture-tools.sqlite'),
});
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
const extensionNames = ['agent-capabilities.ts', 'system-tool-knowledge.ts', 'pi-kanban.ts', 'everyday-workflow.ts'];
const settings = sdk.SettingsManager.inMemory({ extensions: extensionNames.map((name) => path.join(workflow, name)),
  defaultTools: ['read', 'ls', 'find', 'grep'], cacheWarming: 'off' });
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
  noSkills: true, noPromptTemplates: true, noThemes: true,
  disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
await loader.reload();
assert.deepEqual(loader.getExtensions().errors, []);
const sessionManager = sdk.SessionManager.inMemory(project);
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const { session } = await sdk.createAgentSession({ cwd: project, agentDir, resourceLoader: loader,
  settingsManager: settings, sessionManager, modelRuntime, thinkingLevel: 'off', model: {
    id: 'fixture-no-inference', name: 'No inference', provider: 'fixture-local', api: 'openai-completions',
    baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false,
    contextWindow: 32768, maxTokens: 4096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  } });
const errors = [];
await session.bindExtensions({ onError: (error) => errors.push(error) });
let sequence = 0, lastMessage;
const trace = [];
const checks = [];
function assertPostureDelivery() {
  assert.ok(loader.getAppendSystemPromptSources().some((entry) => fs.realpathSync(entry.path) === posturePath),
    'Normal Pi resource discovery must select the copied public APPEND_SYSTEM.md');
  assert.ok(loader.getAppendSystemPrompt().some((text) => text.trim() === postureText.trim()),
    'The normal loader must retain the complete rendered public posture');
  assert.ok(session.systemPrompt.includes(postureText.trim()),
    'Actual session.systemPrompt must contain the complete normally loaded public posture');
  const prompt = session.systemPrompt.replace(/\s+/g, ' ');
  for (const clause of [
    'Separate questions, suggestions and agent proposals from permission to change files or expand the task.',
    'Compare matched cases, fields, request bytes and option order.',
    'Publish measured results from their actual receipts;',
    'Read current tool and model metadata before claiming capability or health.',
    'Read the nearest project and topic instructions when entering that scope.',
    'Keep unrelated context unloaded.',
  ]) assert.ok(prompt.includes(clause), `Actual native prompt is missing public posture clause: ${clause}`);
}
async function tool(name, input, allowFailure = false) {
  const runner = session.extensionRunner, id = `source-native-${++sequence}`;
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!blocked?.block, `${name} blocked: ${blocked?.reason}`);
  const registered = runner.getAllRegisteredTools().find((item) => item.definition.name === name);
  const wrapped = registered ? sdk.wrapRegisteredTool(registered, runner) : sdk.createReadTool(project);
  const raw = await wrapped.execute(id, input, new AbortController().signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...raw, isError: raw.isError === true });
  const result = { ...raw, ...changed };
  lastMessage = { role: 'toolResult', toolCallId: id, toolName: name, content: structuredClone(result.content),
    details: structuredClone(result.details), isError: result.isError === true, timestamp: Date.now() };
  trace.push({ id, name, input, result });
  if (!allowFailure) assert.ok(!result.isError, `${name} failed: ${JSON.stringify(result)}`);
  return result;
}
async function context() {
  for (let count = 0; count < 32; count++) {
    const result = await tool('project_context', { path: project });
    await session.extensionRunner.emitContext([structuredClone(lastMessage)]);
    if (!result.details.remaining_reads.length) return;
  }
  assert.fail('Fixture context exceeded its read bound');
}
async function discover(loadSourceSkill = false, loadContext = true) {
  await tool('agent_capabilities', {});
  await tool('system_tool_query', { terms: 'source checkpoint Git' });
  await tool('project_knowledge_query', { terms: 'source checkpoint' });
  await session.extensionRunner.emitToolResult({ type: 'tool_result', toolCallId: 'explicit-memory-fixture',
    toolName: 'mcp__mempalace__mempalace_search', input: {}, content: [], details: { ok: true, fixture: true }, isError: false });
  await tool('read', { path: skillFiles['supervised-tasks'] });
  if (loadSourceSkill) await tool('read', { path: skillFiles['source-control'] });
  if (loadContext) await context();
}
async function route(text, parts, control) {
  await session.extensionRunner.emitInput(text, undefined, 'interactive');
  const pending = (await tool('kanban_intake_status', {})).details.result.pending;
  return tool('kanban_intake_route', { source_id: pending.at(-1).id, parts, ...(control ? { control } : {}) });
}
function plan(operation, recovery) {
  const relative = `${checkpointBase}/${operation}/admission.json`;
  return { objective: 'Save one reviewed local source milestone', cwd: project,
    action: [python, '-B', sourceHelper, '--project-root', project, '--task-ref', taskRef,
      '--message', 'Save reviewed native source milestone', '--operation', operation,
      '--inventory', inventory, digest(inventory)],
    verify: [python, '-B', sourceHelper, '--verify', relative], outputs: [relative],
    ...(recovery ? { recovery } : {}) }; // Intentionally omit required_skills.
}
async function held(input, reason) {
  const before = { head: git('rev-parse', 'HEAD'), index: git('ls-files', '--stage'),
    steps: fs.existsSync(path.join(project, '.pi-workflow')) ? fs.readdirSync(path.join(project, '.pi-workflow')).length : 0 };
  const result = await session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: `held-${++sequence}`, toolName: 'workflow_step', input });
  assert.equal(result?.block, true, `Expected native refusal: ${JSON.stringify(result)}`);
  assert.match(result.reason, reason);
  assert.equal(git('rev-parse', 'HEAD'), before.head);
  assert.equal(git('ls-files', '--stage'), before.index);
  assert.equal(fs.existsSync(path.join(project, '.pi-workflow')) ? fs.readdirSync(path.join(project, '.pi-workflow')).length : 0, before.steps);
  trace.push({ held: true, input, reason: result.reason });
}
let taskRef;
try {
  assertPostureDelivery();
  checks.push('normal-loader-public-posture-source-and-bytes', 'actual-session-public-posture-clauses');
  await tool('project_admit', { project_root: project, initialize: true,
    native_authority: 'Owner requested isolated native source checkpoint qualification',
    target: 'Verify scoped source milestones', why: 'Exercise actual native gates and Git with no model' });
  const admitted = await route('Update source.py to the reviewed value and save a local source checkpoint. Preserve unrelated work. Do not push.',
    [{ kind: 'task', summary: 'Update one source file and save its local reviewed milestone', execute: true }]);
  const task = admitted.details.result.bound[0].task_id;
  taskRef = `pi-session:${sessionManager.getSessionId()}/task:${task}`;
  await discover();
  const edited = await tool('workflow_step', { objective: 'Write the exact reviewed source content', cwd: project,
    action: [python, '-c', `from pathlib import Path; Path('source.py').write_text(${JSON.stringify(expectedSource)})`],
    verify: [python, sourceVerifier], outputs: ['source.py'] });
  assert.equal(edited.details.host.status, 'supplied_predicate_passed');
  const reviewed = await tool('read', { path: sourceFile });
  assert.equal(reviewed.content[0].text, expectedSource);
  writeJson(inventory, { safe_files: [{ path: sourceFile, sha256: digest(sourceFile) }] });
  checks.push('native-source-edit-host-receipt', 'native-exact-source-read', 'explicit-file-task-session-inventory');
  await held(plan('before-skill'), /source-control/);
  await tool('read', { path: skillFiles['source-control'] });
  checks.push('source-control-skill-required-when-omitted');
  const wrongRoot = plan('wrong-root');
  wrongRoot.action[wrongRoot.action.indexOf('--project-root') + 1] = fixture;
  await held(wrongRoot, /project|root|cwd/i);
  const wrongVerify = plan('wrong-verifier');
  wrongVerify.verify = [python, '-c', 'raise SystemExit(0)'];
  await held(wrongVerify, /verif/i);
  const wrongOutput = plan('wrong-output'); wrongOutput.outputs = ['wrong-receipt.json'];
  await held(wrongOutput, /output|receipt/i);
  checks.push('wrong-project-before-mutation', 'wrong-verifier-before-mutation', 'wrong-receipt-output-before-mutation');
  await session.reload();
  assertPostureDelivery();
  checks.push('public-posture-delivery-survives-native-reload');
  await discover(true, false);
  await held(plan('before-context'), /context/i);
  await context();
  checks.push('reload-context-required-before-checkpoint');
  await session.extensionRunner.emitInput('What changed before the checkpoint?', undefined, 'interactive');
  await held(plan('unrouted'), /rout|pending/i);
  const sourceStatus = (await tool('kanban_intake_status', {})).details.result;
  await tool('kanban_intake_route', { source_id: sourceStatus.pending.at(-1).id,
    parts: [{ kind: 'question', summary: 'Status question only' }] });
  await route('Pause before saving source.', [{ kind: 'control', summary: 'Explicit fixture owner pause' }], 'pause');
  await held(plan('paused'), /paused/i);
  await route('What is the current status?', [{ kind: 'question', summary: 'A question preserves the pause' }]);
  await held(plan('still-paused'), /paused/i);
  await route('Resume the authorized local source checkpoint.', [{ kind: 'control', summary: 'Explicit owner resume' }], 'resume');
  checks.push('unrouted-input-refusal', 'owner-pause-refusal', 'ordinary-question-preserves-pause');
  const failed = await tool('workflow_step', plan('occupied-index'), true);
  assert.equal(failed.isError, true, 'Occupied index must refuse before commit');
  assert.equal(git('rev-parse', 'HEAD').trim(), beforeHead);
  assert.equal(git('ls-files', '--stage', '--', ...unrelatedFiles), originalIndex);
  assert.equal(git('diff', '--cached', '--name-only', '-z'), stagedBefore);
  assert.ok(!fs.existsSync(path.join(project, checkpointBase, 'occupied-index')));
  for (const name of unrelatedFiles) assert.equal(fs.readFileSync(path.join(project, name), 'utf8'), unrelatedBytes[name]);
  checks.push('occupied-index-refusal-without-operation', 'occupied-index-and-dirty-bytes-preserved');
  await held(plan('uninspected-failure'), /failed|blocked|inspect/i);
  const sourceRun = failed.details.host.run_id;
  const finalFailure = path.join(project, '.enforcement/runs', sourceRun, 'final.json');
  await tool('read', { path: finalFailure });
  // Fixture-owner coordination only; this is not an agent reset or an actual user's index.
  git('restore', '--staged', '--', 'unrelated-staged.py');
  assert.equal(git('diff', '--cached', '--name-only', '-z'), '');
  const coordinatedIndex = git('ls-files', '--stage', '--', ...unrelatedFiles);
  await route('The fixture owner coordinated and unstaged unrelated work. Resume only the reviewed source checkpoint, with exact failed-run recovery evidence.',
    [{ kind: 'amend', task_id: task, summary: 'Recover the refused checkpoint after explicit index coordination', execute: true }], 'resume');
  await held(plan('missing-recovery'), /recover|failure|inspect/i);
  const recovery = { source_run_id: sourceRun, failure_class: 'external_state',
    changed_assumption: 'The fixture owner cleared only the unrelated staged entry after the occupied-index refusal.',
    new_evidence: 'Actual git diff --cached is empty; the original refused run and unrelated working bytes remain preserved.',
    expected_observation: 'One local commit contains only source.py at its reviewed SHA256 and the exact configured task reference.',
    stop_condition: 'Stop on staged work, changed reviewed bytes, unexpected Git paths or any unverified delivery.' };
  const operation = 'native-local-milestone';
  const saved = await tool('workflow_step', plan(operation, recovery));
  assert.equal(saved.details.host.status, 'supplied_predicate_passed');
  const receiptPath = path.join(project, checkpointBase, operation, 'admission.json');
  const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
  const commit = git('rev-parse', 'HEAD').trim();
  assert.notEqual(commit, beforeHead);
  assert.equal(receipt.schema, 'source-checkpoint/v1');
  assert.equal(receipt.state, 'reviewed-source-committed-local');
  assert.equal(receipt.commit, commit); assert.equal(receipt.before_head, beforeHead);
  assert.equal(receipt.task_ref, taskRef); assert.equal(receipt.project_root, project);
  assert.equal(receipt.git_root, project); assert.equal(receipt.branch, 'native-source-task');
  assert.deepEqual(receipt.changed_paths, ['source.py']);
  assert.deepEqual(receipt.files, { 'source.py': sha(Buffer.from(expectedSource)) });
  assert.equal(git('show', commit + ':source.py'), expectedSource);
  assert.equal(git('rev-list', '--parents', '-n', '1', commit).trim(), commit + ' ' + beforeHead);
  for (const name of unrelatedFiles) assert.equal(fs.readFileSync(path.join(project, name), 'utf8'), unrelatedBytes[name]);
  assert.equal(git('ls-files', '--stage', '--', ...unrelatedFiles), coordinatedIndex);
  assert.equal(git('diff', '--cached', '--name-only', '-z'), '');
  const readback = spawnSync(python, ['-B', sourceHelper, '--verify', `${checkpointBase}/${operation}/admission.json`],
    { cwd: project, encoding: 'utf8', env: { PATH: process.env.PATH, LANG: 'C.UTF-8' }, timeout: 30000 });
  assert.equal(readback.status, 0, readback.stderr);
  const verified = JSON.parse(readback.stdout);
  assert.equal(verified.commit, commit); assert.equal(verified.remote_verified, false);
  const remoteRefs = spawnSync('git', ['--git-dir', remote, 'for-each-ref', '--format=%(objectname)'], { encoding: 'utf8' });
  assert.equal(remoteRefs.status, 0, remoteRefs.stderr); assert.equal(remoteRefs.stdout, '');
  checks.push('failure-inspection-and-explicit-bound-recovery', 'actual-local-commit-and-tree-readback',
    'selected-task-session-reference', 'unrelated-working-and-index-entries-preserved', 'local-only-no-implicit-remote-proof');
  const receiptHash = digest(receiptPath);
  const replay = await tool('workflow_step', plan(operation), true);
  assert.equal(replay.isError, true, 'Replaying a saved operation must fail');
  assert.equal(git('rev-parse', 'HEAD').trim(), commit); assert.equal(digest(receiptPath), receiptHash);
  checks.push('operation-replay-refusal-preserves-commit-and-receipt');
  assert.deepEqual(errors, [], 'Native extension failures must not be hidden');
  assert.equal(session.pendingMessageCount, 0);
  const result = { status: 'passed', fixture, pi_version: JSON.parse(fs.readFileSync(path.join(piPackage, 'package.json'))).version,
    checks, local_commit: commit, before_head: beforeHead, source_receipt: receiptPath,
    source_receipt_sha256: receiptHash, source_helper_sha256: digest(sourceHelper),
    public_posture_source: postureTemplate, loaded_posture_source: posturePath,
    public_posture_sha256: digest(postureTemplate), rendered_posture_sha256: digest(posturePath),
    native_probe_sha256: digest(new URL(import.meta.url)),
    runtime_manifest_sha256: digest(path.join(runtime, 'runtime-manifest.json')),
    task_ref: taskRef, model_calls: 0, remote_pushes: 0, elapsed_ms: Date.now() - started,
    limits: 'Actual Pi gates, host workflow and isolated real Git. Memory readiness is fixture data; task/session text is caller context, not authenticated ownership or all-session attribution. No external push or root product acceptance.' };
  writeJson(path.join(fixture, 'native-trace.json'), trace);
  writeJson(path.join(fixture, 'native-session.json'), sessionManager.getBranch());
  writeJson(path.join(fixture, 'receipt.json'), result);
  console.log(JSON.stringify(result, null, 2));
} finally {
  session.dispose();
}
