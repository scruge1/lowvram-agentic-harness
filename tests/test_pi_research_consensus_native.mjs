/** Actual Pi1.4 registered tool + guarded cached scorer; zero provider/model calls. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import childProcess from 'node:child_process';
import { syncBuiltinESMExports } from 'node:module';
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
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-research-consensus-'));
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
    else if (/\.(py|ts|mjs|md)$/.test(name) || ['claude-memory-patch.json', 'model-service-pins.json'].includes(entry.name)) {
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
const corpus = py(`import json;from pathlib import Path;from harness import research_mining as m,research_runtime as r
i=json.loads(sys.argv[1]);p={'project_id':i['project_id'],'board_id':i['board_id'],'canonical_root':i['canonical_root']};s=r.ArtifactStore(i['state_root'],p);identity=r.digest((Path(i['canonical_root'])/'.icm/project.json').read_bytes())
def mine(url,query='How does the method work?',field='method',quote='sustained hypothesis experiment execution revision loop',status='ok',partial=False,empty=False,pages=1):
 sources=[]
 for n in range(pages):
  page=url if pages==1 else url+'/page-'+str(n)
  sources.append(s.put({'schema':'project-research-artifact/v1','project':p,'action':'fetch','payload':{'ok':True,'status':'ok','requested_url':page,'response':{'final_url':page,'cleaned_text_full':quote+' source marker '+page}}}))
 fields=[field]+(['other'+str(n) for n in range(8)] if partial else [])
 plan=m.prepare({'query':query,'artifact_ids':sources,'extraction_schema':fields},s,{'provider':'local','id':'synthetic-no-inference'},r.text_view,r.wire,r.digest)
 pid=s.put({'schema':'project-research-artifact/v1','project':p,'identity_sha256':identity,'action':'mine_plan','payload':{'ok':True,'status':'prepared',**plan}})
 rows=[] if empty else [{'field':field,'claim':quote,'relevance':3,'confidence':1.0,'evidence_span':quote}]
 payload=m.finish(plan,[{'source':n,'shard':0,'status':status,'text':json.dumps({'claims':rows}) if status=='ok' else ''} for n in range(pages)]);payload['plan_artifact_id']=pid
 return s.put({'schema':'project-research-artifact/v1','project':p,'identity_sha256':identity,'action':'mine','payload':payload})
good=mine('https://github.com/example/a');bad=s.get(good);bad['payload']['claims'][0]['evidence_start']+=1
print(json.dumps({'good':good,'second':mine('https://example.readthedocs.io/b'),'empty':mine('https://example.org/empty',empty=True),'failed':mine('https://example.org/failure',status='model_error'),'partial':mine('https://example.org/partial',partial=True),'other':mine('https://example.org/other',query='Different research question'),'bad_span':s.put(bad),'batches':[mine('https://batch'+str(n)+'.example.org/source',pages=3) for n in range(32)],'numeric':[mine('https://example.org/'+str(n),query='Memory?',field='memory',quote='Memory capacity is '+str(n)+' GiB.') for n in (32,64)]}))`, [JSON.stringify(identities[0])]);
let providerCalls = 0;
const oldFetch = globalThis.fetch;
globalThis.fetch = async () => { providerCalls++; throw new Error('Consensus must never call a provider'); };
const originalSpawn = childProcess.spawn;
let abortAfterClose;
childProcess.spawn = (...args) => {
  const child = originalSpawn(...args), controller = abortAfterClose;
  if (controller && args[1]?.includes(path.join(runtime, 'harness/research_runtime.py')))
    // Attach after the production close handler: invoke has resolved and
    // removed its abort listener, but execute's await has not resumed yet.
    child.once('spawn', () => child.once('close', () => controller.abort()));
  return child;
};
syncBuiltinESMExports();
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
assert.equal(JSON.parse(fs.readFileSync(path.join(piPackage, 'package.json'))).version, '1.4.0');
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
const input = { action: 'consensus', artifact_ids: [corpus.good, corpus.second] };
try {
  assert.equal((await tool(input)).isError, true); checks.push('unselected-project-refused');
  select(identities[0]);
  let result = await tool(input);
  assert.equal(result.isError, false, JSON.stringify(result));
  assert.equal(result.details.complete, true); assert.equal(result.details.consensus_established, false);
  assert.equal(result.details.cluster_count, 1); assert.equal(result.details.input_claims, 2);
  const artifact = result.details.artifact_id;
  checks.push('actual-native-tool-installed-guarded-consensus-helper');
  result = await tool({ action: 'read', artifact_id: artifact, limit: 8192 });
  assert.match(result.details.text, /claim_indices/); assert.match(result.details.text, /evidence_span/);
  assert.match(result.details.text, /lexical-jaccard/); checks.push('cached-source-attribution-and-explicit-policy-method');
  assert.equal((await tool({ ...input, artifact_ids: [corpus.good, corpus.good] })).isError, true);
  checks.push('duplicate-artifact-input-refused');
  assert.equal((await tool({ ...input, artifact_ids: [] })).isError, true); checks.push('empty-corpus-refused');
  assert.equal((await tool({ ...input, artifact_ids: [corpus.good, corpus.other] })).isError, true);
  checks.push('mixed-topic-input-refused');
  for (const [ids, status] of [[[corpus.failed], 'all_failed'], [[corpus.partial], 'partial_coverage'],
    [[corpus.good, corpus.failed], 'partial_coverage']]) {
    result = await tool({ ...input, artifact_ids: ids });
    assert.equal(result.isError, true); assert.equal(result.details.status, status);
    assert.equal(result.details.coverage_complete, false); assert.equal(result.details.consensus_established, false);
    checks.push('native-' + status + '-whole-input-coverage-retained');
  }
  result = await tool({ ...input, artifact_ids: [corpus.empty] });
  assert.equal(result.details.status, 'no_relevant_claims'); assert.equal(result.details.coverage_complete, true);
  assert.equal(result.isError, true); checks.push('healthy-no-relevance-distinct-from-operational-failure');
  result = await tool({ ...input, artifact_ids: [corpus.good, corpus.empty] });
  assert.equal(result.isError, false); assert.equal(result.details.coverage_complete, true);
  checks.push('healthy-empty-and-useful-batches-combine-without-erasing-coverage');
  result = await tool({ ...input, artifact_ids: corpus.batches });
  assert.equal(result.isError, false); assert.equal(result.details.input_count, 32); assert.equal(result.details.input_claims, 96);
  checks.push('normal-tool-combines-thirty-two-batches-ninety-six-synthetic-pages');
  result = await tool({ ...input, artifact_ids: corpus.numeric });
  assert.equal(result.isError, false); assert.equal(result.details.cluster_count, 2);
  const numeric = await tool({ action: 'read', artifact_id: result.details.artifact_id, limit: 8192 });
  assert.match(numeric.details.text, /32 GiB/); assert.match(numeric.details.text, /64 GiB/);
  checks.push('numeric-variants-not-merged-or-averaged');
  assert.equal((await tool({ ...input, artifact_ids: [corpus.bad_span] })).isError, true);
  assert.equal((await tool({ ...input, artifact_ids: [seeded.artifact_id] })).isError, true);
  checks.push('stored-span-tamper-and-non-mining-input-refused');
  select(identities[1]); assert.equal((await tool(input)).isError, true); select(identities[0]);
  checks.push('foreign-project-mining-refused');
  const abort = new AbortController(); abort.abort();
  assert.equal((await tool(input, abort.signal)).isError, true); checks.push('preaborted-consensus-refused');

  const helper = path.join(runtime, 'harness/research_runtime.py'), bytes = fs.readFileSync(helper);
  const marker = path.join(fixture, 'consensus-entered'), release = path.join(fixture, 'consensus-release');
  const wrapper = `request = json.loads(raw)\n        if request.get('action') == 'consensus':\n            Path(${JSON.stringify(marker)}).write_text('entered')\n            while not Path(${JSON.stringify(release)}).exists(): __import__('time').sleep(0.01)\n        result = ResearchRuntime(args.home).execute(request)`;
  const changed = bytes.toString().replace('result = ResearchRuntime(args.home).execute(json.loads(raw))', wrapper);
  assert.notEqual(changed, bytes.toString());
  const member = manifest.find(x => x.path === 'harness/research_runtime.py');
  function rebind(value) {
    fs.writeFileSync(helper, value); member.sha256 = digest(helper);
    write(path.join(runtime, 'runtime-manifest.json'), { files: manifest });
    const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
    config.runtime_manifest_sha256 = digest(path.join(runtime, 'runtime-manifest.json')); write(path.join(home, 'home.json'), config);
    process.env.PI_WEB_RESEARCH_HELPER_SHA256 = member.sha256;
  }
  rebind(changed);
  try {
    const operation = tool(input), began = Date.now();
    while (!fs.existsSync(marker) && Date.now() - began < 5000) await new Promise(resolve => setTimeout(resolve, 10));
    assert.ok(fs.existsSync(marker), 'The real guarded helper must reach its explicit test-only entry barrier');
    sessionManager.appendCustomEntry('synthetic-input-during-consensus', {});
    fs.writeFileSync(release, 'release'); result = await operation;
    assert.equal(result.isError, true); assert.match(result.details.reason, /admission changed.*delivery held/);
    checks.push('last-await-admission-epoch-delivery-held');
  } finally { fs.writeFileSync(release, 'release'); rebind(bytes); }
  const completed = () => py(`import json;from pathlib import Path
p=Path(sys.argv[1])/'research/artifacts';rows=[json.loads(f.read_text()) for f in p.glob('*.json')];print(json.dumps(sum(x.get('action')=='consensus' and x['payload'].get('status')=='scored' for x in rows)))`, [identities[0].state_root]);
  const boundaries = [];
  const late = new AbortController(), beforeLate = completed();
  abortAfterClose = late;
  result = await tool({ ...input, artifact_ids: [corpus.second] }, late.signal); abortAfterClose = undefined;
  boundaries.push({ case: 'abort_after_helper_close', aborted: late.signal.aborted, isError: result.isError,
    status: result.details.status, completed_before: beforeLate, completed_after: completed() });

  const scorer = path.join(runtime, 'harness/research_consensus.py'), scorerBytes = fs.readFileSync(scorer);
  const delayed = scorerBytes.toString().replace(/^(def score\([^\r\n]*\):)\r?$/m,
    (_match, header) => header + "\n    __import__('time').sleep(2.2)");
  assert.notEqual(delayed, scorerBytes.toString());
  const scorerMember = manifest.find(x => x.path === 'harness/research_consensus.py');
  const bindScorer = value => {
    fs.writeFileSync(scorer, value); scorerMember.sha256 = digest(scorer);
    write(path.join(runtime, 'runtime-manifest.json'), { files: manifest });
    const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json')));
    config.runtime_manifest_sha256 = digest(path.join(runtime, 'runtime-manifest.json')); write(path.join(home, 'home.json'), config);
  };
  bindScorer(delayed);
  try {
    const before = completed(), began = Date.now();
    result = await tool({ ...input, artifact_ids: [corpus.good], timeout: 2 });
    boundaries.push({ case: 'delayed_productive_scoring', isError: result.isError, status: result.details.status,
      elapsed_ms: Date.now() - began, completed_before: before, completed_after: completed() });
  } finally { bindScorer(scorerBytes); }
  write(path.join(fixture, 'final-boundaries.json'), { boundaries,
    scope: 'Actual helper close/abort order and explicit copied-scorer2.2s delay with declared2s productive budget; no model/provider.' });
  assert.equal(boundaries[0].aborted, true);
  assert.equal(boundaries[0].isError, true, JSON.stringify(boundaries));
  assert.equal(boundaries[0].status, 'cancelled');
  assert.equal(boundaries[0].completed_after, beforeLate + 1, 'Late cancellation must preserve the already-published bound artifact');
  assert.equal(boundaries[1].isError, true, JSON.stringify(boundaries));
  assert.equal(boundaries[1].status, 'deadline');
  assert.equal(boundaries[1].completed_after, boundaries[1].completed_before, 'Expired productive scoring cannot publish success');
  checks.push('post-helper-abort-holds-delivery-preserves-committed-data', 'productive-deadline-excludes-cleanup-reserve');
  assert.equal(providerCalls, 0); assert.deepEqual(errors, []);
  checks.push('zero-provider-requests-no-chat-as-embedder');
  write(path.join(fixture, 'receipt.json'), { schema: 'pi-research-consensus-native-qualification/v1', ok: true,
    checks, fixture, elapsed_ms: Date.now() - start, source_files: manifest, trace, borrowed_python: borrowedPython,
    provider_requests: providerCalls, model_inferences: 0,
    instrumentation: { original_helper_sha256: sha(bytes), barrier_helper_sha256: sha(Buffer.from(changed)),
      original_scorer_sha256: sha(scorerBytes), delayed_scorer_sha256: sha(Buffer.from(delayed)),
      scope: 'Copied-helper pre-operation barrier, copied-scorer2.2s entry delay and child-close abort observer; no provider or model.' },
    scope: 'Actual Pi1.4 registered tool and installed guarded scoring helper over synthetic cached producer artifacts. No inference, fetch/search, embedding, fresh package install, normal intake or useful full research-journey acceptance.' });
  console.log(JSON.stringify({ ok: true, checks: checks.length, fixture, receipt: path.join(fixture, 'receipt.json'), elapsed_ms: Date.now() - start }));
} catch (error) {
  write(path.join(fixture, 'failure.json'), { ok: false, checks, error: String(error.stack || error), trace, source_files: manifest }); throw error;
} finally { abortAfterClose = undefined; childProcess.spawn = originalSpawn; syncBuiltinESMExports(); globalThis.fetch = oldFetch; await session.dispose(); }
