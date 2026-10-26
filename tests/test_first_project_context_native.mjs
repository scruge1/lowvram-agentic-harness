/** Real preparation/context/serializer; explicit inventory and board fixtures, zero HTTP/model. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) options[process.argv[i].slice(2)] = process.argv[i + 1];
for (const key of ['source', 'pi-package', 'python', 'fixture-parent']) assert.ok(options[key], key);
const source = fs.realpathSync(options.source), pkg = fs.realpathSync(options['pi-package']);
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg, 'package.json'))).version, '1.4.0');
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'first-report-context-'));
const home = path.join(fixture, 'owned home'), start = Date.now();
const script = `import importlib.util,json,os,subprocess,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1]);from harness import home,first_project
h=Path(sys.argv[2]);home.scaffold(h,name='Context qualification',profile='core',base_url='http://127.0.0.1:1/v1',model='synthetic-no-inference',source=Path(sys.argv[1]),offline=True)
c=json.loads((h/'home.json').read_text());c['installed']={'hermes':{'fixture':True}};(h/'home.json').write_text(json.dumps(c))
os.environ['PI_PROJECT_STATE_BASE']=str(h/'state/projects')
s=importlib.util.spec_from_file_location('identity',Path(sys.argv[1])/'adapters/pi/project-workflow/project_identity.py');identity=importlib.util.module_from_spec(s);s.loader.exec_module(identity)
def board(_home,request):
 root=Path(request['project_root']);i,_=identity.initialize_identity(root,native_authority='Explicit synthetic context qualification')
 subprocess.run([sys.executable,'-B',str(Path(sys.argv[1])/'adapters/pi/project-workflow/init_workspace.py'),'--root',str(root/i['workspace_path']),'--target','Synthetic report context','--why','Read-only native instruction delivery','--parent-authority','Synthetic fixture, no operational authority'],check=True,capture_output=True)
 return {'result':{'identity':i},'fixture':True}
facts={'ram_total_gb':32.5,'gpu_vram_mib':None,'storage_total_gb':1000,'configured_model':{'context_tokens':32768,'output_tokens':4096},'fixture_only':True}
with patch.object(home,'check_package',return_value=None),patch.object(home,'board',side_effect=board),patch.object(first_project,'_facts',return_value=facts):prepared=first_project.prepare(h,'report')
print(json.dumps(prepared))`;
const made = spawnSync(options.python, ['-I', '-B', '-c', script, source, home], {
  encoding: 'utf8', timeout: 30000, maxBuffer: 1024 * 1024, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
});
assert.equal(made.status, 0, made.stderr || made.stdout);
const prepared = JSON.parse(made.stdout), project = prepared.project_root;
const identity = JSON.parse(fs.readFileSync(path.join(project, '.icm/project.json')));
const instructions = fs.readFileSync(path.join(project, 'FIRST-PROJECT.md'), 'utf8');
const ssot = path.join(project, '.icm/workspace/PROJECT-SSOT.md');
assert.ok(fs.readFileSync(ssot, 'utf8').includes(instructions));
const extension = path.join(fixture, 'context-only.ts');
fs.writeFileSync(extension, `import {registerProjectContext} from ${JSON.stringify(path.join(home, 'runtime/adapters/pi/context/project-context.ts'))};
export default function(pi){registerProjectContext(pi,{project:()=>(${JSON.stringify({ root: project, projectId: identity.project_id, boardId: identity.board_id })})});}`);
Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PI_PROJECT_CONTEXT_PI_PACKAGE: pkg,
  PI_CODING_AGENT_DIR: path.join(home, 'agent') });
const sdk = await import(pathToFileURL(path.join(pkg, 'dist/index.js')));
const require = createRequire(path.join(pkg, 'package.json'));
const aiPackage = require.resolve.paths('@earendil-works/pi-ai').map(root => path.join(root, '@earendil-works/pi-ai/package.json')).find(file => fs.existsSync(file));
const provider = await import(pathToFileURL(path.join(path.dirname(aiPackage), 'dist/api/openai-completions.js')));
const settings = sdk.SettingsManager.inMemory({ extensions: [extension], defaultTools: [], cacheWarming: 'off' });
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir: path.join(home, 'agent'), settingsManager: settings,
  disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'], noSkills: true, noPromptTemplates: true, noThemes: true });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const catalog = new Map();
const modelsStore = { async read(id) { return catalog.get(id); }, async write(id,value) { catalog.set(id,value); }, async delete(id) { catalog.delete(id); } };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsStore, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const model = { id: 'fixture-no-inference', provider: 'fixture-local', name: 'No inference', api: 'openai-completions',
  baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false, contextWindow: 32768, maxTokens: 4096,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const sessionManager = sdk.SessionManager.inMemory(project);
const { session } = await sdk.createAgentSession({ cwd: project, agentDir: path.join(home, 'agent'), settingsManager: settings,
  resourceLoader: loader, sessionManager, modelRuntime, model, thinkingLevel: 'off' });
const errors = [], checks = [];
await session.bindExtensions({ onError: error => errors.push(error) });
const runner = session.extensionRunner;
const call = () => runner.emitToolCall({ type: 'tool_call', toolCallId: 'inert-action', toolName: 'workflow_step',
  input: { cwd: project, outputs: ['hardware-report.md'] } });
let http = 0, payload;
try {
  assert.equal((await call())?.block, true); checks.push('normal-context-gate-held-before-source-delivery');
  const definition = runner.getAllRegisteredTools().find(item => item.definition.name === 'project_context');
  const result = await sdk.wrapRegisteredTool(definition, runner).execute('context-1', { path: project }, new AbortController().signal);
  assert.ok(!result.isError, JSON.stringify(result));
  const packet = JSON.parse(result.content[0].text), document = packet.documents.find(item => item.path === ssot);
  assert.ok(document); assert.equal(document.role, 'workspace-router'); assert.ok(document.text.includes(instructions));
  assert.equal(packet.remaining_reads.length, 0); checks.push('existing-project-context-delivers-complete-task-and-writer-template');
  assert.equal((await call())?.block, true); checks.push('same-batch-result-does-not-unlock-context-gate');
  const assistant = { role: 'assistant', api: model.api, provider: model.provider, model: model.id, stopReason: 'toolUse', timestamp: Date.now(),
    content: [{ type: 'toolCall', id: 'context-1', name: 'project_context', arguments: { path: project } }] };
  const message = { role: 'toolResult', toolCallId: 'context-1', toolName: 'project_context', content: result.content,
    details: result.details, isError: false, timestamp: Date.now() };
  session.agent.state.messages = [assistant, message]; sessionManager.appendMessage(assistant); sessionManager.appendMessage(message);
  session.agent.getApiKey = () => 'synthetic-not-a-credential';
  session.agent.streamFunction = (selected, context, opts) => provider.stream(selected, context, { ...opts,
    apiKey: 'synthetic-not-a-credential', maxRetries: 0,
    fetch: async () => { http++; throw new Error('FORBIDDEN_HTTP'); },
    onPayload(value) { payload = value; throw new Error('STOP_BEFORE_HTTP'); } });
  await session.agent.continue();
  assert.ok(payload); const serialized = JSON.stringify(payload);
  assert.ok(serialized.includes('Action argv TEMPLATE JSON:')); assert.ok(serialized.includes('hardware-report.md'));
  assert.ok(serialized.includes('first_project.py run launches an agent')); assert.equal(http, 0);
  const taskSection = payload.messages.find(item => JSON.stringify(item).includes('CURRENT_PENDING_REQUEST_ID_FROM_STATUS'));
  assert.ok(taskSection, 'The actual native provider input must include the current-source route template');
  assert.ok(instructions.includes('project_prepare'));
  assert.ok(instructions.includes('kanban_intake_status'));
  const skillArgs = JSON.parse(instructions.split('native read with EXACTLY this JSON: ')[1].split('\n')[0]);
  assert.equal(skillArgs.path, path.join(home, 'agent/skills/supervised-tasks/SKILL.md'));
  assert.ok(serialized.includes('Use amend only for an actual existing board card'));
  checks.push('native-model-input-retains-direct-preparation-exact-skill-and-new-task-template');
  checks.push('actual-native-model-input-contains-task-template-with-zero-http');
  assert.ok(!(await call())?.block); checks.push('unchanged-delivered-normal-context-opens-only-existing-context-gate');
  assert.deepEqual(errors, []); assert.equal(fs.existsSync(path.join(project, 'hardware-report.md')), false);
  fs.writeFileSync(path.join(fixture, 'provider-input.json'), JSON.stringify(payload, null, 2) + '\n');
  const receipt = { ok: true, schema: 'first-report-context-native/v1', checks, fixture, elapsed_ms: Date.now() - start,
    input_sha256: createHash('sha256').update(instructions).digest('hex'), original_manifest_sha256: prepared.manifest_sha256,
    network_requests: http, model_inferences: 0,
    scope: 'Actual prepare/Git/native identity/workspace and Pi1.4 context/serializer. Inventory, package check and board admission are explicit fixtures. No actual Hermes admission, full workflow execution, report body generation or useful model acceptance.' };
  fs.writeFileSync(path.join(fixture, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ ok: true, checks: checks.length, receipt: path.join(fixture, 'receipt.json'), elapsed_ms: receipt.elapsed_ms }));
} catch (error) {
  fs.writeFileSync(path.join(fixture, 'failure.json'), JSON.stringify({ error: String(error.stack || error), checks }, null, 2)); throw error;
} finally { await session.dispose(); }
