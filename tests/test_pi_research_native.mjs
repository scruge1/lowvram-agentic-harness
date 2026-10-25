/** Actual Pi1.4 + installed helper; synthetic cached evidence, no network/model. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i].startsWith('--') && process.argv[i + 1]);
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const key of ['source', 'pi-package', 'research-python', 'fixture-parent']) assert.ok(options[key], `Missing --${key}`);
assert.equal(process.platform, 'linux', 'This probe uses an explicit read-only environment alias');
const start = Date.now();
const source = fs.realpathSync(options.source);
const piPackage = fs.realpathSync(options['pi-package']);
const borrowedPython = path.resolve(options['research-python']);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-research-native-'));
const home = path.join(fixture, 'home');
const runtime = path.join(home, 'runtime');
const agentDir = path.join(home, 'agent');
const project = path.join(fixture, 'project with spaces');
const second = path.join(fixture, 'second project');
for (const dir of [runtime, agentDir, project, second, path.join(home, 'envs'), path.join(home, 'state')]) fs.mkdirSync(dir, { recursive: true });
const sha = value => createHash('sha256').update(value).digest('hex');
const digest = file => sha(fs.readFileSync(file));
const write = (file, value) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(value) + '\n'); };
const manifest = [];
function copy(relative) {
  for (const entry of fs.readdirSync(path.join(source, relative), { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue;
    assert.ok(!entry.isSymbolicLink());
    const name = path.join(relative, entry.name);
    if (entry.isDirectory()) copy(name);
    else if (/\.(py|ts|mjs|md)$/.test(name)) {
      const destination = path.join(runtime, name);
      fs.mkdirSync(path.dirname(destination), { recursive: true }); fs.copyFileSync(path.join(source, name), destination);
      manifest.push({ path: name.split(path.sep).join('/'), sha256: digest(destination) });
    }
  }
}
for (const dir of ['harness', 'ssot', 'adapters/pi']) copy(dir);
for (const name of ['pi-task-worker.py', 'pi_native_events.py']) {
  const destination = path.join(runtime, name);
  fs.copyFileSync(path.join(runtime, 'adapters/pi/project-workflow', name), destination);
  manifest.push({ path: name, sha256: digest(destination) });
}
write(path.join(runtime, 'runtime-manifest.json'), { files: manifest });
write(path.join(home, 'home.json'), { schema: 'agent-home/v1', home,
  selected_packages: { research: 'native-fixture-readonly-alias' },
  runtime_manifest_sha256: digest(path.join(runtime, 'runtime-manifest.json')),
  validated_registry_sha256: sha(Buffer.alloc(0)), bounded_compaction_sha256: sha(Buffer.from('{}')) });
// No dependency install/doctor claim: only executable alias in this fixture.
fs.symlinkSync(path.dirname(path.dirname(borrowedPython)), path.join(home, 'envs/research'), 'dir');
const python = path.join(home, 'envs/research/bin/python');
function py(script, args = []) {
  const result = spawnSync(python, ['-I', '-B', '-c', `import sys;sys.path.insert(0,${JSON.stringify(runtime)});` + script, ...args], {
    cwd: home, encoding: 'utf8', timeout: 30000, maxBuffer: 4 * 1024 * 1024,
    env: { ...process.env, PI_PROJECT_STATE_BASE: path.join(home, 'state/projects'), PYTHONDONTWRITEBYTECODE: '1' },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout); return JSON.parse(result.stdout);
}
const guardBinding = py(`import json;from pathlib import Path;from harness import home_entry
h=Path(sys.argv[1]);b=home_entry.install(h);c=json.loads((h/'home.json').read_text());c['lifecycle_guard_sha256']=b['guard_sha256'];(h/'home.json').write_text(json.dumps(c));print(json.dumps(b))`, [home]);
const identities = py(`import importlib.util,json;from pathlib import Path
s=importlib.util.spec_from_file_location('identity',Path(sys.path[0])/'adapters/pi/project-workflow/project_identity.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
print(json.dumps([m.initialize_identity(Path(p))[0] for p in sys.argv[1:]]))`, [project, second]);
const text = 'SYNTHETIC_PUBLIC_RESEARCH_73 漢字🙂\n\t"\\\x01 '.repeat(2400);
const textFile = path.join(fixture, 'synthetic-text.txt'); fs.writeFileSync(textFile, text);
const seeded = py(`import json;from pathlib import Path;from harness import research_runtime as r
i=json.loads(sys.argv[1]);p={'project_id':i['project_id'],'board_id':i['board_id'],'canonical_root':i['canonical_root']}
t=Path(sys.argv[2]).read_text();v={'schema':'project-research-artifact/v1','project':p,'action':'fetch','authority':r.AUTHORITY,'payload':{'ok':True,'status':'ok','response':{'cleaned_text_full':t,'raw_content_base64':'HOST_ONLY_BINARY','cleaned_text':'short'}}}
print(json.dumps({'artifact_id':r.ArtifactStore(i['state_root'],p).put(v),'text_sha256':r.digest(t.encode())}))`, [JSON.stringify(identities[0]), textFile]);
Object.assign(process.env, py(`import json;from pathlib import Path;from harness.home import environment;print(json.dumps(environment(Path(sys.argv[1]))))`, [home]),
  { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PI_CODING_AGENT_DIR: agentDir });
Object.assign(process.env, py(`import json,hashlib;from pathlib import Path;from harness import home_entry
h=Path(sys.argv[1]);p=str(h/'envs/research/bin/python');c=home_entry.guarded_command(h,[p,'-I','-B',str(h/'runtime/harness/research_runtime.py'),'--home',str(h)],python=p);raw=json.dumps(c);print(json.dumps({'PI_WEB_RESEARCH_COMMAND':raw,'PI_WEB_RESEARCH_COMMAND_SHA256':hashlib.sha256(raw.encode()).hexdigest()}))`, [home]));
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
const settings = sdk.SettingsManager.inMemory({ extensions: [path.join(runtime, 'adapters/pi/research/research-tools.ts')], cacheWarming: 'off', defaultTools: [] });
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
  noSkills: true, noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const sessionManager = sdk.SessionManager.inMemory(project);
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const { session } = await sdk.createAgentSession({ cwd: project, agentDir, resourceLoader: loader, settingsManager: settings,
  sessionManager, modelRuntime, thinkingLevel: 'off', model: { id: 'fixture-no-inference', name: 'No inference', provider: 'fixture-local', api: 'openai-completions',
    baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false, contextWindow: 32768, maxTokens: 4096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } } });
const errors = [], checks = [], trace = [];
await session.bindExtensions({ onError: error => errors.push(error) });
let sequence = 0;
let instrumentation = null;
const select = identity => sessionManager.appendCustomEntry('pi-kanban-selection/v1', { project: { root: identity.canonical_root, projectId: identity.project_id, boardId: identity.board_id }, task: null, boardAdmissionFailed: false });
async function tool(input, signal = new AbortController().signal) {
  const runner = session.extensionRunner;
  const id = `research-native-${++sequence}`;
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: 'web_research', input });
  assert.ok(!blocked?.block, JSON.stringify(blocked));
  const registered = runner.getAllRegisteredTools().find(item => item.definition.name === 'web_research');
  assert.ok(registered, 'Actual tool must register');
  const value = await sdk.wrapRegisteredTool(registered, runner).execute(id, input, signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: 'web_research', input, ...value, isError: value.isError === true });
  const result = { ...value, ...changed };
  assert.ok(Buffer.byteLength(result.content[0].text) <= 12288);
  assert.equal(result.content[0].text.includes('HOST_ONLY_BINARY'), false);
  trace.push({ input, result }); return result;
}
const read = { action: 'read', artifact_id: seeded.artifact_id, limit: 8192 };
try {
  assert.equal((await tool(read)).isError, true); checks.push('native-unselected-project-refused');
  select(identities[0]);
  let result = await tool(read); assert.equal(result.isError, false);
  assert.equal(result.details.text_sha256, seeded.text_sha256);
  assert.equal(result.details.content_scope, 'full_extraction');
  assert.equal(result.details.authority, 'untrusted_source_evidence');
  checks.push('actual-pi-tool-executes-isolated-installed-helper', 'actual-home-load-environment-manifest-and-interpreter', 'native-bounded-model-projection-no-base64');
  let recovered = result.details.text, offset = result.details.next_offset;
  while (offset !== null) {
    result = await tool({ ...read, offset }); assert.equal(result.isError, false);
    assert.equal(result.details.window_sha256, sha(Buffer.from(result.details.text)));
    recovered += result.details.text;
    assert.ok(result.details.next_offset === null || result.details.next_offset > offset); offset = result.details.next_offset;
  }
  assert.equal(recovered, text); checks.push('actual-native-unicode-full-evidence-cursor-recovery');
  await session.reload(); assert.equal((await tool(read)).isError, false); checks.push('native-reload-current-journal-selection');
  const metadata = await tool({ ...read, view: 'metadata' });
  assert.equal(metadata.isError, false); assert.equal(metadata.details.text.includes('SYNTHETIC_PUBLIC_RESEARCH_73'), false);
  checks.push('cached-provenance-view-redacts-body-and-binary');
  select(identities[1]); assert.equal((await tool(read)).isError, true); checks.push('foreign-project-artifact-refused'); select(identities[0]);
  const pointer = path.join(project, '.icm/project.json'), old = fs.readFileSync(pointer);
  write(pointer, { ...identities[0], board_id: 'project:wrong' });
  assert.equal((await tool(read)).isError, true); fs.writeFileSync(pointer, old); checks.push('native-current-identity-drift-refused');
  const helper = path.join(runtime, 'harness/research_runtime.py'), helperBytes = fs.readFileSync(helper);
  fs.appendFileSync(helper, '\n# drift\n'); assert.equal((await tool(read)).isError, true); fs.writeFileSync(helper, helperBytes);
  checks.push('configured-helper-byte-drift-refused');
  const sourceFile = path.join(runtime, 'harness/web_research.py'), sourceBytes = fs.readFileSync(sourceFile);
  fs.appendFileSync(sourceFile, '\n# drift\n'); assert.equal((await tool(read)).isError, true); fs.writeFileSync(sourceFile, sourceBytes);
  checks.push('other-runtime-manifest-source-drift-refused-before-optional-import');
  const abort = new AbortController(); abort.abort(); assert.equal((await tool(read, abort.signal)).isError, true);
  checks.push('pre-aborted-native-execution-refused');
  assert.equal((await tool({ ...read, artifact_id: 'sha256:' + '0'.repeat(64) })).isError, true); checks.push('missing-evidence-fails-normally');
  const command = process.env.PI_WEB_RESEARCH_COMMAND, commandSha = process.env.PI_WEB_RESEARCH_COMMAND_SHA256;
  delete process.env.PI_WEB_RESEARCH_COMMAND;
  assert.match((await tool(read)).details.reason, /requires.*lifecycle command/); process.env.PI_WEB_RESEARCH_COMMAND = command;
  process.env.PI_WEB_RESEARCH_COMMAND_SHA256 = '0'.repeat(64);
  assert.match((await tool(read)).details.reason, /command binding changed/); process.env.PI_WEB_RESEARCH_COMMAND_SHA256 = commandSha;
  checks.push('integrated-home-requires-exact-raw-command-hash');

  // Explicit test-only pre-import marker/barrier around the unchanged helper.
  // It makes refusal ordering and lease lifetime deterministic without a model,
  // browser, long network request, or replacement research implementation.
  const marker = path.join(fixture, 'helper-entered'), release = path.join(fixture, 'release-helper');
  const prefix = `\nimport os as _test_os,time as _test_time\nif _test_os.environ.get('PI_RESEARCH_TEST_BARRIER')=='1':\n    open(${JSON.stringify(marker)},'w').close()\n    while not _test_os.path.exists(${JSON.stringify(release)}): _test_time.sleep(0.02)\n`;
  const instrumented = helperBytes.toString().replace(/from __future__ import annotations\r?\n/, 'from __future__ import annotations\n' + prefix);
  assert.notEqual(instrumented, helperBytes.toString()); fs.writeFileSync(helper, instrumented);
  const instrumentedFile = path.join(fixture, 'instrumented-research-runtime.py'); fs.writeFileSync(instrumentedFile, instrumented);
  instrumentation = { original_helper_sha256: sha(helperBytes), instrumented_sha256: digest(instrumentedFile), retained_source: instrumentedFile,
    scope: 'Explicit test-only pre-import marker/barrier, followed by unchanged production helper body.' };
  const helperBinding = manifest.find(item => item.path === 'harness/research_runtime.py'); helperBinding.sha256 = digest(helper);
  const updateManifest = () => {
    write(path.join(runtime, 'runtime-manifest.json'), { files: manifest });
    const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
    config.runtime_manifest_sha256 = digest(path.join(runtime, 'runtime-manifest.json')); write(path.join(home, 'home.json'), config);
  };
  updateManifest(); process.env.PI_WEB_RESEARCH_HELPER_SHA256 = helperBinding.sha256;
  process.env.PI_RESEARCH_TEST_BARRIER = '1';
  const pending = path.join(home, 'state/updates/pending-activation.json'); write(pending, {});
  assert.match((await tool(read)).details.reason, /Pending activation blocks normal entry/);
  assert.equal(fs.existsSync(marker), false); fs.unlinkSync(pending); checks.push('pending-activation-refused-before-helper-import-marker');
  const guardLoad = `import importlib.util;from pathlib import Path\ns=importlib.util.spec_from_file_location('owned_guard',${JSON.stringify(path.join(home, 'home-lifecycle.py'))});m=importlib.util.module_from_spec(s);__import__('sys').modules[s.name]=m;s.loader.exec_module(m)\n`;
  const exclusive = spawn(python, ['-I', '-B', '-c', guardLoad + `with m.lease(Path(${JSON.stringify(home)}),expected_sha256=${JSON.stringify(guardBinding.guard_sha256)},mode='exclusive'):\n print('ready',flush=True)\n input()\n`], { stdio: ['pipe', 'pipe', 'pipe'], env: process.env });
  let leaseErrors = '';
  exclusive.stderr.on('data', bytes => { leaseErrors += bytes; });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Exclusive fixture lease did not start: ' + leaseErrors)), 5000);
    exclusive.stdout.once('data', bytes => { clearTimeout(timer); assert.match(bytes.toString(), /ready/); resolve(); });
    exclusive.once('error', reject);
  });
  try { assert.match((await tool(read)).details.reason, /home is busy/); assert.equal(fs.existsSync(marker), false); }
  finally { exclusive.stdin.end('\n'); await new Promise(resolve => exclusive.once('close', resolve)); }
  checks.push('exclusive-update-refused-before-helper-import-marker');
  const operation = tool(read);
  try {
    const began = Date.now();
    while (!fs.existsSync(marker) && Date.now() - began < 5000) await new Promise(resolve => setTimeout(resolve, 20));
    assert.ok(fs.existsSync(marker), 'Guarded actual helper must enter test-only pre-import barrier');
    const busy = py(guardLoad + `import json\ntry:\n with m.lease(Path(${JSON.stringify(home)}),expected_sha256=${JSON.stringify(guardBinding.guard_sha256)},mode='exclusive'): print(json.dumps({'busy':False}))\nexcept m.LeaseBusy: print(json.dumps({'busy':True}))\n`);
    assert.equal(busy.busy, true);
  } finally { fs.writeFileSync(release, 'release'); assert.equal((await operation).isError, false); }
  checks.push('active-guarded-helper-holds-lifetime-shared-lease-through-delivery');
  delete process.env.PI_RESEARCH_TEST_BARRIER;
  fs.writeFileSync(helper, helperBytes); helperBinding.sha256 = digest(helper); updateManifest(); process.env.PI_WEB_RESEARCH_HELPER_SHA256 = helperBinding.sha256;
  assert.equal((await tool(read)).isError, false); checks.push('normal-uninstrumented-helper-resumes-after-lease-controls');
  assert.deepEqual(errors, []);
  write(path.join(fixture, 'receipt.json'), { schema: 'pi-research-native-qualification/v1', ok: true, checks, fixture,
    elapsed_ms: Date.now() - start, source_files: manifest, trace, borrowed_python: borrowedPython, lifecycle_guard: guardBinding, instrumentation,
    scope: 'Actual Pi SDK and full installed-helper/bootstrap path with explicit native-selection and synthetic cached-evidence fixtures. No coordinator/intake admission, network fetch/search/render, fresh dependency install, browser execution or model call is claimed.' });
  console.log(JSON.stringify({ ok: true, checks: checks.length, fixture, receipt: path.join(fixture, 'receipt.json'), elapsed_ms: Date.now() - start }));
} catch (error) {
  write(path.join(fixture, 'failure.json'), { ok: false, checks, error: String(error.stack || error), trace, source_files: manifest }); throw error;
} finally { session.dispose(); }
