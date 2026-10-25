/** Real managed command -> native Pi command handler; borrowed deps, no model. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import * as fs from 'node:fs';
import * as http from 'node:http';
import * as path from 'node:path';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1], 'Use --name value arguments');
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const key of ['source', 'pi-package', 'donor-home', 'python', 'fixture-parent']) assert.ok(options[key], `Missing --${key}`);
assert.equal(process.platform, 'linux', 'Actual board, memory and process-owner qualification requires Linux');
const started = Date.now(), source = fs.realpathSync(options.source), donor = fs.realpathSync(options['donor-home']);
const piPackage = fs.realpathSync(options['pi-package']), python = path.resolve(options.python);
assert.ok(piPackage.startsWith(donor + path.sep));
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'managed-launch-native-'));
const sha = value => createHash('sha256').update(value).digest('hex'), hash = file => sha(fs.readFileSync(file));
const writeJson = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
const checks = [], commands = [], homes = [], hubs = [], bindings = [];
const donorConfig = JSON.parse(fs.readFileSync(path.join(donor, 'home.json')));
const watchedDonor = ['home.json', 'agent/settings.json', 'agent/mcp.json', 'agent/models.json', 'runtime/runtime-manifest.json'];
for (const key of ['pi', 'hermes', 'mempalace', 'framework']) for (const item of donorConfig.installed[key].artifacts)
  if (!watchedDonor.includes(path.relative(donor, item.path))) watchedDonor.push(path.relative(donor, item.path));
const donorHashes = () => Object.fromEntries(watchedDonor.map(name => [name, hash(path.join(donor, name))]));
const beforeDonor = donorHashes();
const requests = [];
const tripwire = http.createServer((request, response) => {
  requests.push({ method: request.method, url: request.url }); response.writeHead(503); response.end('QUALIFICATION_FORBIDS_MODEL_HTTP');
});
await new Promise(resolve => tripwire.listen(0, '127.0.0.1', resolve));
const endpoint = `http://127.0.0.1:${tripwire.address().port}/v1`;
const baseEnv = { ...process.env, PATH: path.dirname(process.execPath) + path.delimiter + process.env.PATH,
  PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' };
const guard = path.join(source, 'adapters/pi/project-workflow/pi-task-worker.py');
async function run(argv, { cwd = fixture, env = baseEnv, guarded = true, timeout = 120000, input } = {}) {
  const actual = guarded ? [python, '-B', guard, '--guard', ...argv] : argv;
  const result = await new Promise((resolve, reject) => {
    const child = spawn(actual[0], actual.slice(1), { cwd, env: { ...env, PI_TASK_TIMEOUT: String(Math.ceil(timeout / 1000)) }, stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '', stderr = '', expired = false;
    const timer = setTimeout(() => { expired = true; guarded ? child.stdin.end() : child.kill('SIGTERM'); }, timeout);
    child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', (code, signal) => { clearTimeout(timer); child.stdin.end(); resolve({ code, signal, stdout, stderr, expired }); });
    child.stdin.on('error', () => {});
    if (!guarded) child.stdin.end(input);
  });
  commands.push({ argv, cwd, guarded, ...result }); return result;
}
const provision = path.join(fixture, 'provision.py');
fs.writeFileSync(provision, `import copy,hashlib,importlib.metadata,json,os,sys\nfrom pathlib import Path\nsource,donor,home,base_url,model,name=map(str,sys.argv[1:])\nsource=Path(source);donor=Path(donor);home=Path(home)\nsys.path.insert(0,str(source))\nfrom harness import home as module\nconfig=module.scaffold(home,source=source,profile='pi',base_url=base_url,model=model,name=name,offline=True)\nfor key in ['hermes','mempalace','framework']:\n os.symlink(donor/'envs'/key,home/'envs'/key,target_is_directory=True)\nos.symlink(donor/'packages/pi',home/'packages/pi',target_is_directory=True)\noriginal=json.loads((donor/'home.json').read_text());aliases=[]\nfor key in module.PROFILES['pi']:\n record={'requested':module.PINS[key],'observed':original['installed'][key]['observed'],'artifacts':module.package_artifacts(home,key),'npm_name':original['installed'][key].get('npm_name'),'running':'not_started','acceptance':'borrowed_exact_dependency_fixture'}\n for item in record['artifacts']:\n  p=Path(item['path'])\n  if not p.is_relative_to(home):\n   if not p.is_relative_to(donor):raise ValueError('Dependency metadata outside both explicit fixture homes: '+str(p))\n   alias=home/p.relative_to(donor)\n   assert alias.is_file() and os.path.samefile(alias,p)\n   aliases.append({'observed':str(p),'selected_home_alias':str(alias),'sha256':item['sha256']})\n   item['path']=str(alias)\n config['installed'][key]=record\n assert module.check_package(home,key,record) is None\nmodule.save_status(home,config)\n# The normal post-install phase may run only after every dependency is verified.\n# Refuse an unexpected package installation rather than changing any software.\nobserved=[];original_run=module.run\ndef checked_run(argv,**kwargs):\n words=[str(x) for x in argv]\n if 'install' in words and any(x in words for x in ['pip','npm','npm.cmd']):raise RuntimeError('Package installation forbidden in borrowed-dependency qualification')\n observed.append(words)\n return original_run(argv,**kwargs)\nmodule.run=checked_run\nmodule.install_packages(home,config)\nreport=module.doctor(home)\nassert report['failures']==[],report\n(home/'state/borrowed-dependency-qualification.json').write_text(json.dumps({'donor':str(donor),'aliases':aliases,'post_install_commands':observed,'doctor':report},indent=2)+'\\n')\nprint(json.dumps({'home':str(home),'doctor':report,'aliases':aliases,'post_install_commands':observed}))\n`);
const observer = path.join(fixture, 'binding-observer.ts');
fs.writeFileSync(observer, `import * as fs from 'node:fs';\nexport default function(pi:any){\n pi.registerCommand('qualification-binding',{description:'Read-only owned fixture binding observation; no model or work dispatch.',handler:async(args:string,ctx:any)=>{\n  const deadline=Date.now()+25000;\n  while(!pi.getAllTools().some((t:any)=>t.name==='mcp__mempalace__mempalace_search') && Date.now()<deadline)await new Promise(r=>setTimeout(r,20));\n  const names=['HOME','AGENT_HOME','PI_CODING_AGENT_DIR','PI_CODING_AGENT_SESSION_DIR','PI_PROJECT_STATE_BASE','HERMES_HOME','MEMPALACE_PALACE_PATH','MEMPALACE_CONFIG_DIR','PI_VALIDATED_MEMORY_REGISTRY','PI_MEMORY_RUNTIME_WRAPPER'];\n  const report={cwd:ctx.cwd,model:ctx.model,system_prompt:ctx.getSystemPrompt(),session_file:ctx.sessionManager.getSessionFile(),session_dir:ctx.sessionManager.getSessionDir(),session_header:ctx.sessionManager.getHeader(),active_tools:pi.getActiveTools(),registered_tools:pi.getAllTools().map((t:any)=>t.name),environment:Object.fromEntries(names.map(n=>[n,process.env[n]??null])),args};\n  fs.writeFileSync(process.env.NATIVE_BINDING_REPORT!,JSON.stringify(report,null,2)+'\\n');\n }});\n}\n`);
const pythonHelper = path.join(fixture, 'fixture-helper.py');
fs.writeFileSync(pythonHelper, `import json,sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom harness import home as h\nhome=Path(sys.argv[2]);operation=sys.argv[3]\nif operation=='hub':result=h.palace(home,sys.argv[4])\nelif operation=='project':\n root=Path(sys.argv[4]);root.mkdir();(root/'AGENTS.md').write_text('# Owned native launch project\\n\\nKeep this exact admitted root and its source-bound outcome.\\n')\n result=h.board(home,{'action':'project_admit','project_root':str(root),'initialize':True,'native_authority':'Owner authorized a disposable managed-launch fixture','target':'Exact native launch binding','why':'Verify project selection without model work'})\nelif operation=='doctor':result=h.doctor(home)\nelse:raise ValueError(operation)\nprint(json.dumps(result))\n`);
async function helper(home, operation, ...args) {
  const result = await run([python, '-B', pythonHelper, source, home, operation, ...args], { guarded: operation !== 'hub', timeout: 90000 });
  assert.equal(result.code, 0, result.stderr + result.stdout.slice(-1500)); return JSON.parse(result.stdout);
}
async function ownHome(name, model, owner) {
  const home = path.join(fixture, name);
  const result = await run([python, '-B', provision, source, donor, home, endpoint, model, owner], { timeout: 180000 });
  assert.equal(result.code, 0, result.stderr + result.stdout.slice(-1800));
  const configuration = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
  const settingsPath = path.join(home, 'agent/settings.json'), settings = JSON.parse(fs.readFileSync(settingsPath));
  settings.extensions.push(observer); writeJson(settingsPath, settings);
  const info = { home, model, owner, configuration, command: path.join(home, 'bin/harness-agent') }; homes.push(info);
  assert.equal((await helper(home, 'doctor')).failures.length, 0);
  const state = await helper(home, 'hub', 'status'); assert.equal(state.status, 'stopped');
  const started = await helper(home, 'hub', 'start'); assert.equal(started.status, 'running'); assert.equal(started.owned, true); hubs.push(home);
  return info;
}
let bindingNumber = 0;
async function invoke(info, cwd, args = [], expectedCwd = info.home, extraEnv = {}) {
  const reportFile = path.join(fixture, `binding-${++bindingNumber}.json`);
  const result = await run([info.command, ...args, '--offline', '--print', '/qualification-binding'],
    { cwd, env: { ...baseEnv, ...extraEnv, NATIVE_BINDING_REPORT: reportFile }, timeout: 90000 });
  assert.equal(result.code, 0, result.stderr + result.stdout); assert.ok(fs.existsSync(reportFile), 'Actual CLI command handler did not run');
  const report = JSON.parse(fs.readFileSync(reportFile));
  assert.equal(report.cwd, expectedCwd); assert.equal(report.environment.HOME, process.env.HOME);
  assert.equal(report.environment.AGENT_HOME, info.home); assert.equal(report.environment.PI_CODING_AGENT_DIR, path.join(info.home, 'agent'));
  assert.equal(report.environment.MEMPALACE_PALACE_PATH, path.join(info.home, 'memory/palace'));
  assert.equal(report.environment.PI_VALIDATED_MEMORY_REGISTRY, path.join(info.home, 'state/validated-memory.jsonl'));
  assert.equal(report.session_dir, report.environment.PI_CODING_AGENT_SESSION_DIR);
  assert.equal(report.session_header.cwd, expectedCwd); assert.equal(report.model.provider, 'local'); assert.equal(report.model.id, info.model);
  assert.ok(report.system_prompt.includes(fs.readFileSync(path.join(info.home, 'agent/AGENTS.md'), 'utf8').trim()));
  if (expectedCwd === info.home) assert.ok(report.system_prompt.includes(info.owner));
  else assert.ok(report.system_prompt.includes(fs.readFileSync(path.join(expectedCwd, 'AGENTS.md'), 'utf8').trim()));
  assert.ok(report.system_prompt.includes(fs.readFileSync(path.join(info.home, 'agent/APPEND_SYSTEM.md'), 'utf8').trim()));
  for (const name of ['agent_capabilities', 'workflow_step', 'project_context', 'kanban_intake_route', 'validated_memory_query']) assert.ok(report.active_tools.includes(name));
  assert.ok(report.registered_tools.includes('mcp__mempalace__mempalace_search'));
  assert.equal(requests.length, 0, 'An unexpected provider request reached the inert tripwire');
  bindings.push({ report: reportFile, cwd, args, native_session_dir: report.session_dir, native_session_file: report.session_file,
    system_prompt_sha256: sha(report.system_prompt), prompt_scope: expectedCwd === info.home ? 'home-owner-and-agent-instructions' : 'selected-home-router-and-project-instructions',
    active_tools: report.active_tools, registered_tools: report.registered_tools });
  return report;
}
try {
  const a = await ownHome('Home α with spaces', 'fixture-model-a', 'NativeOwnerA');
  const b = await ownHome('Home B', 'fixture-model-b', 'NativeOwnerB');
  checks.push('two-source-scaffolds-with-byte-verified-borrowed-dependencies-and-real-doctor');
  const unrelated = path.join(fixture, 'unrelated cwd'); fs.mkdirSync(unrelated);
  const project = path.join(fixture, 'Project β with spaces'); await helper(a.home, 'project', project);
  const nested = path.join(project, 'nested'); fs.mkdirSync(nested);
  await invoke(a, a.home); await invoke(a, unrelated); await invoke(a, nested, [], project);
  await invoke(a, unrelated, ['--project', project], project);
  await invoke(b, unrelated, ['--provider', 'local', '--model', b.model]);
  await invoke(a, unrelated, [], a.home, { AGENT_HOME: b.home, PI_CODING_AGENT_DIR: path.join(b.home, 'agent'), MEMPALACE_PALACE_PATH: path.join(b.home, 'memory/palace') });
  checks.push('actual-managed-command-home-and-unrelated-cwd-land-in-bound-home', 'actual-managed-command-nearest-and-explicit-project-bind-exact-root',
    'unicode-and-space-paths-reach-real-native-prompt-tools-and-memory-bindings', 'multiple-homes-and-conflicting-environment-remain-home-bound');
  assert.notEqual(bindings[0].native_session_dir, bindings[2].native_session_dir);
  assert.notEqual(bindings[0].native_session_dir, bindings[4].native_session_dir);
  checks.push('native-session-directories-separate-project-and-home-identities');
  for (const [name, args] of [
    ['different-home-selector', ['--home', b.home, '--status']],
    ['unknown-project', ['--project', unrelated, '--status']],
    ['provider-override', ['--provider', 'other', '--offline', '--print', '/qualification-binding']],
    ['model-override', ['--model', b.model, '--offline', '--print', '/qualification-binding']],
    ['profile-disable', ['--no-extensions', '--offline', '--print', '/qualification-binding']],
    ['resume', ['--continue', '--offline', '--print', '/qualification-binding']],
    ['session-override', ['--session-dir', unrelated, '--offline', '--print', '/qualification-binding']],
    ['unqualified-rpc', ['--mode', 'rpc']],
  ]) {
    const reportFile = path.join(fixture, `refused-${name}.json`);
    const result = await run([a.command, ...args], { cwd: unrelated, env: { ...baseEnv, NATIVE_BINDING_REPORT: reportFile } });
    assert.notEqual(result.code, 0, name); assert.ok(!fs.existsSync(reportFile)); assert.equal(requests.length, 0);
    checks.push(`normal-command-refuses-${name}`);
  }
  const wrong = path.join(fixture, 'wrong project'); fs.mkdirSync(path.join(wrong, '.icm'), { recursive: true });
  const identity = JSON.parse(fs.readFileSync(path.join(project, '.icm/project.json'))); fs.writeFileSync(path.join(wrong, '.icm/project.json'), JSON.stringify(identity));
  const wrongHash = hash(path.join(wrong, '.icm/project.json'));
  const refused = await run([a.command, '--project', wrong, '--offline', '--print', '/qualification-binding'], { cwd: unrelated });
  assert.notEqual(refused.code, 0); assert.equal(hash(path.join(wrong, '.icm/project.json')), wrongHash);
  checks.push('wrong-project-identity-refused-with-original-bytes-preserved');
  const sharedBin = path.join(fixture, 'explicit command bin'); fs.mkdirSync(sharedBin);
  const oldPi = '#!/bin/sh\nexit 37\n'; fs.writeFileSync(path.join(sharedBin, 'pi'), oldPi, { mode: 0o700 });
  const install = await run([python, '-B', path.join(a.home, 'agent-home.py'), 'command', 'install', '--bin-dir', sharedBin, '--name', 'agent-a', '--default-pi']);
  assert.equal(install.code, 1, install.stderr); assert.equal(JSON.parse(install.stdout).status, 'collision');
  assert.equal(fs.readFileSync(path.join(sharedBin, 'pi'), 'utf8'), oldPi);
  const named = { ...a, command: path.join(sharedBin, 'agent-a') }; await invoke(named, unrelated);
  checks.push('explicit-command-registration-preserves-existing-pi-and-launches-named-home');
  const terminatorReport = path.join(fixture, 'binding-terminator.json');
  const literal = await run([a.command, '--offline', '--print', '--', '/qualification-binding --model not-a-selector'],
    { cwd: unrelated, env: { ...baseEnv, NATIVE_BINDING_REPORT: terminatorReport } });
  assert.equal(literal.code, 0, literal.stderr); const literalReport = JSON.parse(fs.readFileSync(terminatorReport));
  assert.equal(literalReport.model.id, a.model); assert.equal(literalReport.args, '--model not-a-selector'); assert.equal(requests.length, 0);
  checks.push('actual-native-end-of-options-is-positional-with-managed-model-preserved');
  assert.deepEqual(donorHashes(), beforeDonor); checks.push('donor-runtime-package-and-profile-hashes-unchanged', 'zero-provider-http-with-actual-tripwire');
} catch (error) {
  checks.push({ failed: true, error: String(error?.stack || error) });
} finally {
  for (const home of hubs.reverse()) try { assert.equal((await helper(home, 'hub', 'stop')).status, 'stopped'); }
  catch (error) { checks.push({ failed: true, cleanup: home, error: String(error) }); }
  await new Promise(resolve => tripwire.close(resolve));
  const failures = checks.filter(item => typeof item !== 'string');
  const receipt = { status: failures.length ? 'failed' : 'passed', fixture, checks, bindings,
    managed_source_sha256: hash(path.join(source, 'harness/managed_launch.py')), home_source_sha256: hash(path.join(source, 'harness/home.py')),
    native_probe_sha256: hash(new URL(import.meta.url)), pi_cli_sha256: hash(path.join(piPackage, 'dist/cli.js')),
    native_session_source_sha256: hash(path.join(piPackage, 'dist/core/agent-session.js')),
    native_print_source_sha256: hash(path.join(piPackage, 'dist/modes/print-mode.js')),
    observer_sha256: hash(observer), borrowed_donor: donor, donor_hashes_before: beforeDonor, donor_hashes_after: donorHashes(),
    provider_http: requests.length, provider_requests: requests, model_calls: 0, package_installs: 0, commits: 0, pushes: 0,
    elapsed_ms: Date.now() - started,
    limits: 'Actual normal managed command, exact installed Pi CLI and native command handler. Two owned profile-pi homes borrow byte-verified dependencies; normal post-install/doctor/memory/board helpers run without mocks or installs. One test-only command observer is added to owned settings. Project launches load the selected home instruction router and global posture plus project instructions; referred personalization files are not assumed eagerly injected. This is binding qualification, not fresh package installation, generative model quality, worker execution, Windows native runtime or resume acceptance. RPC/session resume remain refused. Real private/donor palace was not queried; only new empty owned palaces used. No shared Pi/model reload or donor configuration changes.' };
  writeJson(path.join(fixture, 'commands.json'), commands); writeJson(path.join(fixture, 'receipt.json'), receipt);
  console.log(JSON.stringify(receipt, null, 2)); process.exitCode = failures.length ? 1 : 0;
}
