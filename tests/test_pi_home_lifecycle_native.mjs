/** Actual managed Pi + owned native hub; borrowed dependencies, zero model HTTP. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as http from 'node:http';
import * as path from 'node:path';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1], 'Use --name value arguments');
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['source', 'pi-package', 'donor-home', 'python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
assert.equal(process.platform, 'linux', 'Native lifecycle qualification requires Linux');
const source = fs.realpathSync(options.source), donor = fs.realpathSync(options['donor-home']);
const python = path.resolve(options.python), piPackage = fs.realpathSync(options['pi-package']);
assert.ok(fs.statSync(python).isFile());
assert.ok(piPackage.startsWith(donor + path.sep));
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-home-lifecycle-'));
const started = Date.now(), home = path.join(fixture, 'owned agent ü home');
const sha = value => createHash('sha256').update(value).digest('hex'), hash = file => sha(fs.readFileSync(file));
const writeJson = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
const checks = [], commands = [], failures = [];
const donorConfig = JSON.parse(fs.readFileSync(path.join(donor, 'home.json')));
const watched = new Set(['home.json', 'runtime/runtime-manifest.json', 'agent/settings.json', 'agent/models.json', 'agent/mcp.json']);
for (const key of ['pi', 'hermes', 'mempalace', 'framework']) for (const artifact of donorConfig.installed[key].artifacts) watched.add(path.relative(donor, artifact.path));
const donorHashes = () => Object.fromEntries([...watched].sort().map(name => [name, hash(path.join(donor, name))]));
const donorBefore = donorHashes(), modelRequests = [];
const tripwire = http.createServer((request, response) => {
  modelRequests.push({ method: request.method, url: request.url }); response.writeHead(503); response.end('MODEL_HTTP_FORBIDDEN');
});
await new Promise(resolve => tripwire.listen(0, '127.0.0.1', resolve));
const endpoint = `http://127.0.0.1:${tripwire.address().port}/v1`;
const baseEnv = { ...process.env, PATH: path.dirname(process.execPath) + path.delimiter + process.env.PATH,
  PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PYTHONDONTWRITEBYTECODE: '1', CUDA_VISIBLE_DEVICES: '' };
const owner = path.join(source, 'adapters/pi/project-workflow/pi-task-worker.py');
function start(argv, { env = baseEnv, guarded = true, timeout = 120000 } = {}) {
  const actual = guarded ? [python, '-B', owner, '--guard', ...argv] : argv;
  const child = spawn(actual[0], actual.slice(1), { cwd: fixture, env: { ...env, PI_TASK_TIMEOUT: String(Math.ceil(timeout / 1000)) }, stdio: ['pipe', 'pipe', 'pipe'] });
  let stdout = '', stderr = '', expired = false;
  const timer = setTimeout(() => { expired = true; guarded ? child.stdin.end() : child.kill('SIGTERM'); }, timeout);
  child.stdout.on('data', data => { stdout += data; }); child.stderr.on('data', data => { stderr += data; }); child.stdin.on('error', () => {});
  const done = new Promise((resolve, reject) => {
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', (code, signal) => {
      clearTimeout(timer); child.stdin.end(); const value = { argv, guarded, code, signal, stdout, stderr, expired };
      commands.push(value); resolve(value);
    });
  });
  if (!guarded) child.stdin.end();
  return { child, done };
}
async function run(argv, options) { return await start(argv, options).done; }
async function waitFor(predicate, description, timeout = 45000) {
  const deadline = Date.now() + timeout;
  while (!predicate()) { assert.ok(Date.now() < deadline, description); await new Promise(resolve => setTimeout(resolve, 20)); }
}

// Reuse the C1 qualification's real, byte-verified four-dependency bootstrap.
// No install is permitted: normal install_packages may only skip verified keys
// and perform its normal binding, empty-palace and native board postphase.
const provision = path.join(fixture, 'provision.py');
fs.writeFileSync(provision, `import json,os,sys
from pathlib import Path
source,donor,home=map(Path,sys.argv[1:4]);url=sys.argv[4]
sys.path.insert(0,str(source))
from harness import home as module
config=module.scaffold(home,source=source,profile='pi',base_url=url,model='lifecycle-no-model',name='LifecycleOwner',offline=True)
assert config.get('lifecycle_guard_sha256') and config.get('lifecycle_launcher_sha256')
for key in ('hermes','mempalace','framework'):os.symlink(donor/'envs'/key,home/'envs'/key,target_is_directory=True)
os.symlink(donor/'packages/pi',home/'packages/pi',target_is_directory=True)
original=json.loads((donor/'home.json').read_text());aliases=[]
assert set(module.PROFILES['pi'])=={'pi','hermes','mempalace','framework'}
for key in module.PROFILES['pi']:
 record={'requested':module.PINS[key],'observed':original['installed'][key]['observed'],'artifacts':module.package_artifacts(home,key),'npm_name':original['installed'][key].get('npm_name'),'running':'not_started','acceptance':'borrowed_exact_dependency_fixture'}
 for item in record['artifacts']:
  p=Path(item['path'])
  if not p.is_relative_to(home):
   assert p.is_relative_to(donor),str(p)
   alias=home/p.relative_to(donor);assert alias.is_file() and os.path.samefile(alias,p)
   aliases.append({'observed':str(p),'home_alias':str(alias),'sha256':item['sha256']});item['path']=str(alias)
 config['installed'][key]=record
 assert module.check_package(home,key,record) is None
module.save_status(home,config)
original_run=module.run;postphase=[]
def no_install(argv,**kwargs):
 words=[str(value) for value in argv]
 if 'install' in words and any(value in words for value in ('pip','npm','npm.cmd')):raise ValueError('Package installation forbidden')
 postphase.append(words);return original_run(argv,**kwargs)
module.run=no_install
module.install_packages(home,config)
report=module.doctor(home);assert report['failures']==[],report
result={'home':str(home),'doctor':report,'aliases':aliases,'postphase':postphase}
(home/'state/borrowed-dependency-qualification.json').write_text(json.dumps(result,indent=2)+'\\n')
print(json.dumps(result))
`);
const exclusive = path.join(fixture, 'exclusive.py');
fs.writeFileSync(exclusive, `import hashlib,json,sys,types
from pathlib import Path
home=Path(sys.argv[1]);config=json.loads((home/'home.json').read_text());file=home/'home-lifecycle.py';raw=file.read_bytes()
assert hashlib.sha256(raw).hexdigest()==config['lifecycle_guard_sha256']
module=types.ModuleType('native_exclusive_probe');module.__file__=str(file);module.__package__=''
exec(compile(raw,str(file),'exec'),module.__dict__)
try:
 with module.lease(home,expected_sha256=config['lifecycle_guard_sha256'],mode='exclusive'):print(json.dumps({'exclusive':True}))
except (OSError,ValueError) as error:print(str(error),file=sys.stderr);raise SystemExit(1)
`);
async function exclusiveProbe(expected) {
  const result = await run([python, '-B', exclusive, home]);
  assert.equal(result.code, expected, result.stderr + result.stdout);
  if (expected) assert.match(result.stderr, /busy/); else assert.equal(JSON.parse(result.stdout).exclusive, true);
  return result;
}
async function palace(operation) {
  const result = await run([python, '-B', path.join(home, 'agent-home.py'), 'palace', operation], { guarded: false, timeout: 90000 });
  assert.equal(result.code, 0, result.stderr + result.stdout); return JSON.parse(result.stdout);
}
const auditDir = path.join(fixture, 'audit-startup'); fs.mkdirSync(auditDir);
fs.writeFileSync(path.join(auditDir, 'sitecustomize.py'), `import json,os,sys
file=os.environ.get('LIFECYCLE_IMPORT_AUDIT')
if file:
 def record(value):
  with open(file,'a',encoding='utf-8') as stream:stream.write(json.dumps({'pid':os.getpid(),**value})+'\\n')
 record({'kind':'startup'})
 def observe(event,args):
  if event=='import' and args and str(args[0]).startswith('harness'):record({'kind':'import','module':args[0]})
 sys.addaudithook(observe)
`);
const observer = path.join(fixture, 'lifecycle-observer.ts');
fs.writeFileSync(observer, `import * as fs from 'node:fs';
export default function(pi:any){pi.registerCommand('qualification-lifecycle',{description:'Owned lifecycle observation; no model or work dispatch.',handler:async(args:string,ctx:any)=>{
 const deadline=Date.now()+25000;
 while(!pi.getAllTools().some((t:any)=>t.name==='mcp__mempalace__mempalace_search')&&Date.now()<deadline)await new Promise(r=>setTimeout(r,20));
 const fd=Number(process.env.AGENT_HOME_LIFECYCLE_FD);
 const report={pid:process.pid,fd,fd_inode:fs.fstatSync(fd).ino,fd_info:fs.readFileSync('/proc/self/fdinfo/'+fd,'utf8'),cwd:ctx.cwd,model:ctx.model,system_prompt:ctx.getSystemPrompt(),active_tools:pi.getActiveTools(),registered_tools:pi.getAllTools().map((t:any)=>t.name),session_file:ctx.sessionManager.getSessionFile()};
 fs.writeFileSync(process.env.LIFECYCLE_NATIVE_REPORT!,JSON.stringify(report,null,2)+'\\n');
 const holdUntil=Date.now()+45000;
 while(!fs.existsSync(process.env.LIFECYCLE_NATIVE_RELEASE!)&&Date.now()<holdUntil)await new Promise(r=>setTimeout(r,20));
 if(!fs.existsSync(process.env.LIFECYCLE_NATIVE_RELEASE!))throw Error('Owned native release timed out');
}});}
`);
let nativeProcess = null, pendingHash = null, config = null, nativeReport = null, hubReceipt = null;
const release = path.join(fixture, 'native-release'), reportPath = path.join(fixture, 'native-report.json');
const auditPositive = path.join(fixture, 'imports-positive.jsonl'), auditPending = path.join(fixture, 'imports-pending.jsonl');
const pendingFile = path.join(home, 'state/updates/pending-activation.json');
try {
  const prepared = await run([python, '-B', provision, source, donor, home, endpoint], { timeout: 180000 });
  assert.equal(prepared.code, 0, prepared.stderr + prepared.stdout.slice(-2500));
  config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
  assert.equal(hash(path.join(home, 'home-lifecycle.py')), config.lifecycle_guard_sha256);
  assert.equal(hash(path.join(home, 'agent-home.py')), config.lifecycle_launcher_sha256);
  checks.push('normal-fresh-profile-pi-binds-stable-guard-and-entry-pins');
  const settingsFile = path.join(home, 'agent/settings.json'), settings = JSON.parse(fs.readFileSync(settingsFile));
  settings.extensions.push(observer); writeJson(settingsFile, settings);
  assert.equal((await palace('status')).status, 'stopped'); await exclusiveProbe(0);
  checks.push('stopped-owned-home-admits-exclusive-lease');
  assert.equal((await palace('start')).status, 'running'); await exclusiveProbe(1);
  hubReceipt = JSON.parse(fs.readFileSync(path.join(home, 'state/mempalace-hub/owner.json')));
  assert.equal(hubReceipt.home, home); assert.equal(hubReceipt.palace, path.join(home, 'memory/palace'));
  checks.push('actual-owned-native-hub-alone-retains-shared-lifetime');
  const command = path.join(home, 'bin/harness-agent');
  nativeProcess = start([command, '--offline', '--print', '/qualification-lifecycle'], { env: { ...baseEnv, PYTHONPATH: auditDir,
    LIFECYCLE_IMPORT_AUDIT: auditPositive, LIFECYCLE_NATIVE_REPORT: reportPath, LIFECYCLE_NATIVE_RELEASE: release }, timeout: 90000 });
  await waitFor(() => fs.existsSync(reportPath) || nativeProcess.child.exitCode !== null, 'Actual native Pi command did not report its lifecycle');
  if (!fs.existsSync(reportPath)) {
    const early = await nativeProcess.done;
    assert.fail('Actual Pi exited before observer: ' + early.stderr + early.stdout);
  }
  nativeReport = JSON.parse(fs.readFileSync(reportPath));
  assert.equal(nativeReport.fd_inode, fs.statSync(path.join(home, 'state/home-lifecycle.lock')).ino);
  assert.match(nativeReport.fd_info, /FLOCK\s+ADVISORY\s+READ/);
  assert.equal(nativeReport.cwd, home); assert.equal(nativeReport.model.id, 'lifecycle-no-model');
  for (const tool of ['workflow_step', 'project_context', 'kanban_intake_route', 'validated_memory_query']) assert.ok(nativeReport.active_tools.includes(tool), tool);
  assert.ok(nativeReport.registered_tools.includes('mcp__mempalace__mempalace_search'));
  assert.ok(nativeReport.system_prompt.includes('LifecycleOwner'));
  const positiveAudit = fs.readFileSync(auditPositive, 'utf8').trim().split('\n').map(text => JSON.parse(text));
  assert.ok(positiveAudit.some(event => event.kind === 'startup'));
  assert.ok(positiveAudit.some(event => event.kind === 'import' && event.module === 'harness.home'));
  await exclusiveProbe(1);
  checks.push('actual-managed-pi-inherits-its-read-flock-with-native-tools-and-prompt', 'startup-audit-observes-normal-runtime-import');
  fs.writeFileSync(release, 'release owned command\n');
  const finished = await nativeProcess.done; nativeProcess = null;
  assert.equal(finished.code, 0, finished.stderr + finished.stdout);
  assert.equal((await palace('status')).status, 'running'); await exclusiveProbe(1);
  checks.push('pi-exit-leaves-independent-owned-hub-lease-held');
  assert.equal((await palace('stop')).status, 'stopped'); await exclusiveProbe(0);
  checks.push('normal-owned-hub-stop-releases-last-shared-consumer');
  fs.mkdirSync(path.dirname(pendingFile), { recursive: true });
  writeJson(pendingFile, { schema: 'owned-native-pending-fixture/v1', home, reason: 'Verify normal entry refuses before runtime import' }); pendingHash = hash(pendingFile);
  const absentReport = path.join(fixture, 'must-not-have-native-report.json');
  const denied = await run([command, '--offline', '--print', '/qualification-lifecycle'], { env: { ...baseEnv, PYTHONPATH: auditDir,
    LIFECYCLE_IMPORT_AUDIT: auditPending, LIFECYCLE_NATIVE_REPORT: absentReport, LIFECYCLE_NATIVE_RELEASE: release } });
  assert.equal(denied.code, 1); assert.match(denied.stderr, /Pending activation/); assert.ok(!fs.existsSync(absentReport));
  const pendingAudit = fs.readFileSync(auditPending, 'utf8').trim().split('\n').map(text => JSON.parse(text));
  assert.ok(pendingAudit.some(event => event.kind === 'startup'));
  assert.ok(!pendingAudit.some(event => event.kind === 'import' && event.module === 'harness.home'));
  assert.equal(hash(pendingFile), pendingHash); fs.unlinkSync(pendingFile); pendingHash = null;
  assert.equal((await palace('status')).status, 'stopped'); await exclusiveProbe(0);
  checks.push('actual-pending-managed-entry-refuses-before-runtime-import-pi-or-hub');
  assert.equal(modelRequests.length, 0); assert.deepEqual(donorHashes(), donorBefore);
  checks.push('zero-model-http-through-actual-tripwire', 'donor-package-runtime-and-profile-hashes-unchanged');
} catch (error) { failures.push(String(error?.stack ?? error)); }
finally {
  if (nativeProcess) {
    fs.writeFileSync(release, 'cleanup owned command\n');
    try { await nativeProcess.done; } catch (error) { failures.push('Native cleanup: ' + error); }
  }
  if (pendingHash && fs.existsSync(pendingFile)) {
    if (hash(pendingFile) === pendingHash) fs.unlinkSync(pendingFile); else failures.push('Pending fixture changed; preserved without unlink');
  }
  if (config) {
    try { await palace('stop'); } catch (error) { failures.push('Owned hub cleanup: ' + error); }
  }
  await new Promise(resolve => tripwire.close(resolve));
  if (modelRequests.length) failures.push('Unexpected model HTTP: ' + JSON.stringify(modelRequests));
  if (JSON.stringify(donorHashes()) !== JSON.stringify(donorBefore)) failures.push('Donor artifact drift');
  const sourceFiles = ['harness/home.py', 'harness/memory_runtime.py', 'harness/home_entry.py', 'harness/home_lifecycle.py'];
  const receipt = { status: failures.length ? 'failed' : 'passed', fixture, elapsed_ms: Date.now() - started, checks, failures,
    source, source_files: Object.fromEntries(sourceFiles.map(name => [name, hash(path.join(source, name))])), test_sha256: hash(process.argv[1]),
    pi_package: piPackage, pi_version: JSON.parse(fs.readFileSync(path.join(piPackage, 'package.json'))).version,
    pi_cli_sha256: hash(path.join(piPackage, 'dist/cli.js')), home, configuration: config, native_report: reportPath, hub_receipt: hubReceipt,
    audit_positive: auditPositive, audit_pending: auditPending, model_requests: modelRequests, donor_before: donorBefore, donor_after: donorHashes(),
    limits: 'Actual managed Pi CLI, real native owned hub and existing doctor/binding/board helpers in one fresh owned profile-pi home. Four dependencies borrowed through byte-verified donor aliases; no install. One command observer and read-only Python startup audit observe lifecycle without model input. No activation/rollback, generative behavior, private palace, unmanaged direct Pi, legacy-home enforcement or Windows native runtime claim.' };
  writeJson(path.join(fixture, 'commands.json'), commands); writeJson(path.join(fixture, 'receipt.json'), receipt);
  console.log(JSON.stringify(receipt, null, 2)); process.exitCode = failures.length ? 1 : 0;
}
