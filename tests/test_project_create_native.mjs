/** Actual Pi runner/tool wrappers and Hermes/factory; no provider HTTP or model. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let index = 2; index < process.argv.length; index += 2) options[process.argv[index].slice(2)] = process.argv[index + 1];
for (const name of ['home', 'python', 'output']) assert.ok(options[name] && path.isAbsolute(options[name]), name);
assert.equal(process.platform, 'linux');
const home = fs.realpathSync(options.home), output = options.output, base = path.dirname(output);
assert.ok(!fs.existsSync(output));
const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
assert.equal(config.name, 'ProjectCreateQualificationOwner');
assert.equal(config.profile, 'pi');
assert.ok(fs.existsSync(path.join(home, 'state/borrowed-dependency-qualification.json')));
assert.ok(!fs.existsSync(path.join(home, 'state/mempalace-hub/owner.json')));
const hash = raw => createHash('sha256').update(raw).digest('hex');
const watched = ['home.json', 'agent/settings.json', 'agent/models.json', 'runtime/runtime-manifest.json'];
const before = Object.fromEntries(watched.map(name => [name, hash(fs.readFileSync(path.join(home, name)))]));
const checks = [], events = [], http = [];
const check = (name, condition) => { assert.ok(condition, name); checks.push(name); };
const allowed = new Set(['HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TMP', 'TEMP']);
const removedEnvironmentNames = Object.keys(process.env).filter(name => !allowed.has(name));
for (const name of removedEnvironmentNames) delete process.env[name];
const setup = `import json,sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1]+'/runtime')\nfrom harness import home\nprint(json.dumps(home.environment(Path(sys.argv[1]))))\n`;
const environment = spawnSync(options.python, ['-B', '-c', setup, home], { encoding: 'utf8', timeout: 30000 });
assert.equal(environment.status, 0, environment.stderr);
Object.assign(process.env, JSON.parse(environment.stdout), { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' });
const previousFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => { http.push({ url: String(url), method: init?.method ?? 'GET' }); throw new Error('Native project fixture forbids provider HTTP'); };
const packageDir = path.join(home, 'packages/pi/node_modules/@earendil-works/pi-coding-agent');
assert.equal(JSON.parse(fs.readFileSync(path.join(packageDir, 'package.json'))).version, '1.4.0');
const sdk = await import(pathToFileURL(path.join(packageDir, 'dist/index.js')));
const settingsJson = JSON.parse(fs.readFileSync(path.join(home, 'agent/settings.json')));
const settings = sdk.SettingsManager.inMemory({ ...settingsJson, retry: { enabled: false }, compaction: { enabled: false }, cacheWarming: 'off' });
const loader = new sdk.DefaultResourceLoader({ cwd: home, agentDir: path.join(home, 'agent'), settingsManager: settings,
  disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'], noThemes: true });
await loader.reload();
assert.deepEqual(loader.getExtensions().errors, []);
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const catalog = new Map();
const modelsStore = { async read(id) { return catalog.get(id); }, async write(id, value) { catalog.set(id, value); }, async delete(id) { catalog.delete(id); } };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsStore, modelsPath: path.join(home, 'agent/models.json'), allowModelNetwork: false, refreshOnCreate: false });
const model = (await modelRuntime.getAvailable('local')).find(item => item.id === config.model);
assert.ok(model);
const { session } = await sdk.createAgentSession({ cwd: home, agentDir: path.join(home, 'agent'), modelRuntime, model,
  settingsManager: settings, resourceLoader: loader, sessionManager: sdk.SessionManager.inMemory(home), thinkingLevel: 'off' });
await session.bindExtensions({ onError: error => { throw error; } });
const runner = session.extensionRunner;
let number = 0, activeController;
const selection = () => [...session.sessionManager.getBranch()].reverse().find(item => item.type === 'custom' && item.customType === 'pi-kanban-selection/v1')?.data;
async function tool(name, input, allowError = false, signal = new AbortController().signal) {
  const id = 'project-create-' + (++number);
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!blocked?.block, name + ' blocked: ' + blocked?.reason);
  const registered = runner.getAllRegisteredTools().find(item => item.definition.name === name);
  assert.ok(registered, name);
  const result = await sdk.wrapRegisteredTool(registered, runner).execute(id, input, signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...result, isError: result.isError === true });
  const final = { ...result, ...changed };
  events.push({ name, input, result: final });
  if (!allowError) assert.ok(!final.isError, JSON.stringify(final));
  return final;
}
const blockedExecution = () => runner.emitToolCall({ type: 'tool_call', toolCallId: 'must-hold', toolName: 'workflow_step', input: {
  objective: 'This action must never execute', cwd: home, action: [options.python, '-c', 'raise SystemExit(99)'],
  verify: [options.python, '-c', 'raise SystemExit(99)'], outputs: ['must-not-exist.txt'] } });
const git = (root, ...args) => spawnSync('git', ['-C', root, ...args], { encoding: 'utf8' });
const protectedProject = root => Object.fromEntries(['AGENTS.md', '.gitignore', '.icm/project.json', '.git/HEAD', '.git/config'].map(name => [name, hash(fs.readFileSync(path.join(root, name)))]));
const exclusive = () => spawnSync(options.python, ['-B', '-c', `import json,sys\nfrom pathlib import Path\nh=Path(sys.argv[1]);sys.path.insert(0,str(h/'runtime'))\nfrom harness import home_entry\nc=json.loads((h/'home.json').read_text());g=home_entry._load_guard(h,c['lifecycle_guard_sha256'])\nwith g.lease(h,expected_sha256=c['lifecycle_guard_sha256'],mode='exclusive'):print('exclusive')\n`, home], { encoding: 'utf8', timeout: 15000 });
let failure;
try {
  const definition = runner.getAllRegisteredTools().find(item => item.definition.name === 'project_create').definition;
  assert.deepEqual(Object.keys(definition.parameters.properties), ['name']);
  assert.equal(definition.parameters.additionalProperties, false);
  check('name-only actual native schema', true);
  check('file execution held before any selection', (await blockedExecution())?.block === true);
  const a = await tool('project_create', { name: 'alpha' });
  const alpha = path.join(home, 'projects/alpha'), aid = a.details.result.identity;
  check('first creation selects trusted native identity without task', selection().project.root === alpha && selection().task === null);
  check('new Git and instructions', git(alpha, 'rev-parse', '--show-toplevel').stdout.trim() === alpha && fs.existsSync(path.join(alpha, 'AGENTS.md')) && fs.existsSync(path.join(alpha, '.gitignore')));
  check('new Git is unborn', git(alpha, 'rev-parse', '--verify', 'HEAD').status !== 0);
  check('empty board has no automatic ready work', (await tool('kanban_list', {})).details.result.count === 0);
  check('new selection still holds execution', (await blockedExecution())?.block === true);
  const card = (await tool('kanban_create', { title: 'Owned isolation fixture', initial_status: 'triage' })).details.result.task;
  await tool('kanban_select', { task_id: card.id });
  const b = await tool('project_create', { name: 'beta' });
  const beta = path.join(home, 'projects/beta'), bid = b.details.result.identity;
  check('second project resets selected task and isolates identity/state', selection().task === null && aid.project_id !== bid.project_id && aid.board_id !== bid.board_id && aid.state_root !== bid.state_root);
  check('second board is empty', (await tool('kanban_list', {})).details.result.count === 0);
  check('foreign card refuses', (await tool('kanban_show', { task_id: card.id }, true)).isError === true);
  check('file execution remains held after second creation', (await blockedExecution())?.block === true);
  const original = protectedProject(alpha);
  check('collision refuses instead of reinitializing', (await tool('project_create', { name: 'alpha' }, true)).isError === true);
  assert.deepEqual(protectedProject(alpha), original);
  check('failed creation clears project/task selection', selection().project === null && selection().task === null && selection().boardAdmissionFailed);
  for (const input of [{ name: '../escape' }, { name: 'extra', project_root: base }, { name: 'extra', native_authority: 'not accepted' }]) {
    check('unsafe/extra arguments refuse: ' + JSON.stringify(Object.keys(input)), (await tool('project_create', input, true)).isError === true);
  }
  const outside = path.join(base, 'outside'); fs.mkdirSync(outside);
  process.env.GIT_DIR = outside;
  try { check('Git override refuses before Git effects', (await tool('project_create', { name: 'git-override' }, true)).isError === true && !fs.existsSync(path.join(home, 'projects/git-override')) && fs.readdirSync(outside).length === 0); }
  finally { delete process.env.GIT_DIR; }
  const projects = path.join(home, 'projects'), retained = path.join(home, 'projects-retained');
  fs.renameSync(projects, retained); fs.symlinkSync(outside, projects, 'dir');
  try { check('redirected managed parent refuses', (await tool('project_create', { name: 'symlink-escape' }, true)).isError === true && fs.readdirSync(outside).length === 0); }
  finally { fs.unlinkSync(projects); fs.renameSync(retained, projects); }
  const partial = path.join(home, 'projects/partial');
  const idCode = `import sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1]+'/runtime/adapters/pi/project-workflow')\nfrom project_identity import _project_id\nprint(_project_id(Path(sys.argv[2])))\n`;
  const identifier = spawnSync(options.python, ['-B', '-c', idCode, home, partial], { encoding: 'utf8', timeout: 10000 });
  assert.equal(identifier.status, 0, identifier.stderr);
  fs.mkdirSync(path.join(home, 'state/projects', identifier.stdout.trim(), 'kanban.db'), { recursive: true });
  const partialResult = await tool('project_create', { name: 'partial' }, true);
  check('real board failure preserves partial Git/instructions and holds selection', partialResult.isError && fs.existsSync(path.join(partial, '.git')) && fs.existsSync(path.join(partial, 'AGENTS.md')) && selection().project === null);
  check('partial cannot be recreated', (await tool('project_create', { name: 'partial' }, true)).isError === true);
  check('incomplete native board cannot be cleanly adopted', (await tool('project_admit', { project_root: partial }, true)).isError === true);
  const external = path.join(base, 'external'); fs.mkdirSync(external); fs.writeFileSync(path.join(external, 'AGENTS.md'), '# Existing external project\n');
  await tool('project_admit', { project_root: external, initialize: true, native_authority: 'Owned inert native fixture', target: 'Existing external adoption', why: 'Verify no implicit Git setup' });
  const externalIdentity = hash(fs.readFileSync(path.join(external, '.icm/project.json')));
  await tool('project_admit', { project_root: external });
  check('external default adoption unchanged', selection().project.root === external && !fs.existsSync(path.join(external, '.git')) && !fs.existsSync(path.join(external, '.gitignore')) && hash(fs.readFileSync(path.join(external, '.icm/project.json'))) === externalIdentity);
  const actualGit = spawnSync('which', ['git'], { encoding: 'utf8' }).stdout.trim(); assert.ok(actualGit);
  const fakeBin = path.join(base, 'blocking-git'), marker = path.join(base, 'blocking-git.json'); fs.mkdirSync(fakeBin);
  fs.writeFileSync(path.join(fakeBin, 'git'), '#!/usr/bin/python3\nimport json,os,time\nfrom pathlib import Path\nPath(' + JSON.stringify(marker) + ').write_text(json.dumps({"pid":os.getpid()}))\ntime.sleep(60)\nos.execv(' + JSON.stringify(actualGit) + ',[' + JSON.stringify(actualGit) + ',*__import__("sys").argv[1:]])\n', { mode: 0o700 });
  const previousPath = process.env.PATH; process.env.PATH = fakeBin + path.delimiter + previousPath;
  try {
    activeController = new AbortController();
    const pending = tool('project_create', { name: 'cancelled' }, true, activeController.signal);
    const deadline = Date.now() + 15000;
    while (!fs.existsSync(marker) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
    assert.ok(fs.existsSync(marker), 'Fault-injected Git must actually start');
    check('existing lifecycle EX refuses during creation', exclusive().status !== 0);
    activeController.abort(); const cancelled = await pending;
    check('owner cancellation returns failure with preserved partial directory', cancelled.isError && fs.existsSync(path.join(home, 'projects/cancelled/AGENTS.md')) && selection().project === null);
    let settled = false;
    for (let index = 0; index < 100; index++) { if (exclusive().status === 0) { settled = true; break; } await new Promise(resolve => setTimeout(resolve, 100)); }
    check('guard cancellation settles and releases actual home lease', settled);
  } finally { process.env.PATH = previousPath; activeController?.abort(); }
  assert.deepEqual(protectedProject(alpha), original);
  check('no provider HTTP or model request', http.length === 0);
  check('own memory hub stayed stopped', !fs.existsSync(path.join(home, 'state/mempalace-hub/owner.json')));
  assert.deepEqual(Object.fromEntries(watched.map(name => [name, hash(fs.readFileSync(path.join(home, name)))])), before);
  check('home/config/runtime bytes preserved', true);
} catch (error) { failure = String(error?.stack ?? error); throw error; }
finally {
  activeController?.abort();
  await session.dispose(); globalThis.fetch = previousFetch;
  fs.writeFileSync(output, JSON.stringify({ schema: 'native-project-create/v1', checks, failure, http,
    removedEnvironmentNames, events, scope: 'Actual Pi public runner events/tool wrappers, existing factory/Git/Hermes, borrowed verified dependencies. No provider/model, no live home or palace, no normal-CLI inference claim.' }, null, 2));
}
console.log(JSON.stringify({ checks: checks.length, providerHTTP: http.length, output }));
