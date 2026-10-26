/** Actual Pi 1.4 + installed Harness2 deterministic demo. Explicit owned QA home. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].slice(2)] = process.argv[i + 1];
for (const key of ['home', 'pi-package', 'python', 'receipt']) assert.ok(args[key], key);
const home = fs.realpathSync(args.home), pkg = fs.realpathSync(args['pi-package']);
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg, 'package.json'))).version, '1.4.0');
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const configPath = path.join(home, 'home.json'), originalConfig = fs.readFileSync(configPath);
const envResult = spawnSync(args.python, ['-I', '-B', '-c',
  'import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from harness.home import environment;print(json.dumps(environment(Path(sys.argv[2]))))',
  path.join(home, 'runtime'), home], { encoding: 'utf8', timeout: 30000 });
assert.equal(envResult.status, 0, envResult.stderr);
const homeEnv = JSON.parse(envResult.stdout);
const originalEnv = { ...process.env };
Object.assign(process.env, homeEnv, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1' });
const sdk = await import(pathToFileURL(path.join(pkg, 'dist/index.js')));
const settings = sdk.SettingsManager.inMemory({ extensions: [path.join(home, 'runtime/adapters/pi/lab/harness-lab.ts')],
  defaultTools: [], cacheWarming: 'off' });
const loader = new sdk.DefaultResourceLoader({ cwd: home, agentDir: path.join(home, 'agent'), settingsManager: settings,
  noSkills: true, noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const catalog = new Map();
const modelsStore = { async read(id) { return catalog.get(id); }, async write(id, value) { catalog.set(id, value); }, async delete(id) { catalog.delete(id); } };
const runtime = await sdk.ModelRuntime.create({ credentials, modelsStore, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const checks = [], started = Date.now();
let session, http = 0, failure;
const originalFetch = globalThis.fetch;
globalThis.fetch = async () => { http++; throw new Error('FORBIDDEN_HTTP'); };
const lease = () => {
  const config = JSON.parse(fs.readFileSync(configPath));
  const result = spawnSync(args.python, ['-s', '-B', path.join(home, 'home-lifecycle.py'), '--home', home,
    '--expected-sha256', config.lifecycle_guard_sha256, '--mode', 'exclusive', '--', args.python, '-I', '-c', 'print("EX_RELEASED")'],
  { encoding: 'utf8', timeout: 15000 });
  assert.equal(result.status, 0, result.stdout + result.stderr);
};
try {
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const model = { id: 'synthetic-no-inference', provider: 'fixture-local', name: 'No inference', api: 'openai-completions',
    baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false, contextWindow: 32768, maxTokens: 4096,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
  ({ session } = await sdk.createAgentSession({ cwd: home, agentDir: path.join(home, 'agent'), resourceLoader: loader,
    settingsManager: settings, sessionManager: sdk.SessionManager.inMemory(home), modelRuntime: runtime, model, thinkingLevel: 'off' }));
  await session.bindExtensions({ onError: error => { throw error; } });
  const runner = session.extensionRunner;
  const definition = runner.getAllRegisteredTools().find(item => item.definition.name === 'harness_lab');
  assert.ok(definition); checks.push('actual-pi14-registers-optional-lab');
  const tool = sdk.wrapRegisteredTool(definition, runner);
  const call = (action, signal = new AbortController().signal) => tool.execute('lab-' + action, { action }, signal);
  if (args['parent-loss-worker'] === 'true') {
    const runs = path.join(home, 'state/harness-lab/runs');
    const before = new Set(fs.existsSync(runs) ? fs.readdirSync(runs) : []);
    void call('demo');
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const added = fs.existsSync(runs) ? fs.readdirSync(runs).filter(name => !before.has(name)) : [];
      if (added.length) {
        fs.writeFileSync(args.receipt, JSON.stringify({ schema: 'harness-lab-parent-loss-start/v1',
          phase: 'native-helper-run-started-before-parent-exit', run: path.join(runs, added[0]),
          provider_http: http, node_pid: process.pid }) + '\n');
        // The external canonical owner verifies descendant settlement and EX.
        process.exit(0);
      }
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    throw new Error('Native demo never began; parent-loss control was not reached.');
  }
  let result = await call('status');
  assert.ok(!result.isError, JSON.stringify(result));
  assert.equal(result.details.components.harness2.commit, '1cfe254e8d25b15f37048c3730134686abe60335');
  assert.ok(result.details.components.harness2.verified_code_files > 2);
  checks.push('actual-pinned-package-source-and-artifact-status');
  result = await call('experiment'); assert.ok(result.isError); assert.match(JSON.stringify(result), /held/);
  checks.push('experiment-refused-without-model-or-demo-dispatch');
  result = await call('demo');
  assert.ok(!result.isError, JSON.stringify(result));
  assert.equal(result.details.checks['ledger-1'].agg.expected, 'Total: 85.15');
  assert.equal(result.details.checks['ledger-2'].seq.expected, 'Total: 20.25');
  assert.ok(fs.existsSync(path.join(result.details.run, 'stdout.log')));
  assert.ok(fs.existsSync(path.join(result.details.run, 'stderr.log')));
  assert.equal(JSON.parse(fs.readFileSync(path.join(result.details.run, 'result.json'))).ok, true);
  checks.push('actual-native-both-mode-demo-independent-signed-answer-checks-and-retained-logs');
  lease(); checks.push('normal-demo-releases-home-lease-after-settlement');
  const config = JSON.parse(originalConfig); config.profile = 'agent'; fs.writeFileSync(configPath, JSON.stringify(config));
  try { result = await call('demo'); assert.ok(result.isError); assert.match(JSON.stringify(result), /full-profile/); }
  finally { fs.writeFileSync(configPath, originalConfig); }
  checks.push('optional-profile-refuses-before-helper-dispatch');
  const labRuns = path.join(home, 'state/harness-lab/runs');
  const before = new Set(fs.readdirSync(labRuns));
  const controller = new AbortController();
  const pending = call('demo', controller.signal);
  const limit = Date.now() + 15000;
  while (Date.now() < limit && fs.readdirSync(labRuns).every(name => before.has(name)))
    await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(fs.readdirSync(labRuns).some(name => !before.has(name)), 'Abort only after actual diagnostic run begins');
  controller.abort();
  result = await pending; assert.ok(result.isError); assert.match(JSON.stringify(result), /cancelled/);
  lease(); checks.push('active-demo-abort-awaits-canonical-owned-descendant-settlement-and-ex-lease');
  assert.equal(http, 0); checks.push('zero-provider-http-no-model-requests');
} catch (error) { failure = String(error.stack || error); }
finally {
  fs.writeFileSync(configPath, originalConfig);
  if (session) session.dispose();
  globalThis.fetch = originalFetch;
  for (const key of Object.keys(process.env)) if (!(key in originalEnv)) delete process.env[key];
  Object.assign(process.env, originalEnv);
  fs.writeFileSync(args.receipt, JSON.stringify({ schema: 'harness-lab-native-qualification/v1', ok: !failure,
    checks, failure, elapsed_ms: Date.now() - started, provider_http: http, scope: 'isolated source adoption; copied public component dependencies; no fresh-install or model-quality claim',
    helper_sha256: hash(path.join(home, 'runtime/adapters/pi/lab/harness_lab.py')),
    extension_sha256: hash(path.join(home, 'runtime/adapters/pi/lab/harness-lab.ts')), home_config_conserved: fs.readFileSync(configPath).equals(originalConfig) }, null, 2) + '\n');
}
if (failure) throw new Error(failure);
console.log(JSON.stringify({ ok: true, checks, receipt: args.receipt }));
