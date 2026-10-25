/** Scripted native skill use and real stdlib reuse; no model or shared project. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1], 'Use --name value arguments');
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['source', 'pi-package', 'python', 'framework-python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
assert.equal(process.platform, 'linux', 'The existing process owner requires Linux');
const started = Date.now(), source = fs.realpathSync(options.source), python = path.resolve(options.python);
const piPackage = fs.realpathSync(options['pi-package']);
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-reuse-first-'));
const runtime = path.join(fixture, 'runtime'), agentDir = path.join(fixture, 'agent'), project = path.join(fixture, 'project');
for (const directory of [runtime, agentDir, project]) fs.mkdirSync(directory);
const sha = value => createHash('sha256').update(value).digest('hex'), hash = file => sha(fs.readFileSync(file));
const writeJson = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
const files = [];
function copyTree(relative) {
  for (const item of fs.readdirSync(path.join(source, relative), { withFileTypes: true })) {
    if (item.name === '__pycache__') continue;
    const name = path.join(relative, item.name); assert.ok(!item.isSymbolicLink());
    if (item.isDirectory()) copyTree(name);
    else if (/\.(py|ts|mjs|md)$/.test(item.name)) {
      const target = path.join(runtime, name); fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(path.join(source, name), target); files.push({ path: name.split(path.sep).join('/'), sha256: hash(target) });
    }
  }
}
for (const directory of ['harness', 'ssot', 'adapters/pi']) copyTree(directory);
const workflow = path.join(runtime, 'adapters/pi/project-workflow');
for (const name of ['pi-task-worker.py', 'pi_native_events.py']) {
  fs.copyFileSync(path.join(workflow, name), path.join(runtime, name)); files.push({ path: name, sha256: hash(path.join(runtime, name)) });
}
writeJson(path.join(runtime, 'runtime-manifest.json'), { files });
writeJson(path.join(workflow, 'everyday-runtime.json'), { python, runtime,
  runtime_manifest_sha256: hash(path.join(runtime, 'runtime-manifest.json')),
  engine_sha256: hash(path.join(runtime, 'harness/enforcement.py')), helper_sha256: hash(path.join(workflow, 'everyday_workflow.py')) });
const templateAgent = path.join(source, 'harness/templates/agent-home/agent');
fs.cpSync(path.join(templateAgent, 'skills'), path.join(agentDir, 'skills'), { recursive: true });
const posture = fs.readFileSync(path.join(templateAgent, 'APPEND_SYSTEM.md'), 'utf8').replaceAll('{{HOME}}', fixture).replaceAll('{{OWNER}}', 'FixtureOwner');
fs.writeFileSync(path.join(agentDir, 'APPEND_SYSTEM.md'), posture);
const skill = path.join(agentDir, 'skills/reuse-first-engineering/SKILL.md');
const reference = path.join(agentDir, 'skills/reuse-first-engineering/references/reuse-and-comparison.md');
const skillText = fs.readFileSync(skill, 'utf8'), referenceText = fs.readFileSync(reference, 'utf8');
fs.writeFileSync(path.join(project, 'AGENTS.md'), '# Synthetic source reuse task\n\nKeep the full inventory CLI outcome and independent acceptance criteria.\n');
const data = 'sku,description,qty,unit_price\nA-1,"Widget, small",2,3.50\nB-2,"He said ""yes""",1,0.10\nC-3,"line one\nline two",0,99.99\nD-4,café,3,1.20\n';
fs.writeFileSync(path.join(project, 'input.csv'), data);
const expectedRows = [
  { sku: 'A-1', description: 'Widget, small', qty: '2', unit_price: '3.50' },
  { sku: 'B-2', description: 'He said "yes"', qty: '1', unit_price: '0.10' },
  { sku: 'C-3', description: 'line one\nline two', qty: '0', unit_price: '99.99' },
  { sku: 'D-4', description: 'café', qty: '3', unit_price: '1.20' },
];
writeJson(path.join(project, 'weaker-result.json'), data.trim().split('\n').slice(1).map(line => line.split(',')));
const provenanceCode = `import csv,_csv,sys,json,hashlib\nfrom pathlib import Path\np=Path(csv.__file__)\nprint(json.dumps({'implementation':'CPython csv.DictReader','python':sys.version,'module':str(p),'module_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'parser_origin':_csv.__spec__.origin,'interpreter':str(Path(sys.executable).resolve()),'interpreter_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),'license':'Python Software Foundation License Version 2','documentation':'https://docs.python.org/3.12/library/csv.html','license_source':'https://docs.python.org/3.12/license.html'}))\n`;
const probe = spawnSync(python, ['-B', '-c', provenanceCode], { encoding: 'utf8', timeout: 30000 });
assert.equal(probe.status, 0, probe.stderr); const provenance = JSON.parse(probe.stdout);
assert.ok(path.isAbsolute(provenance.module)); assert.ok(provenance.module_sha256.match(/^[a-f0-9]{64}$/));
writeJson(path.join(fixture, 'dependency-provenance.json'), provenance);
const baselineVerifier = path.join(fixture, 'verify-baseline.py');
fs.writeFileSync(baselineVerifier, `import json,sys\nfrom pathlib import Path\np=Path(sys.argv[1])\ntry:\n actual=json.loads(p.read_text())\nexcept (OSError,ValueError):\n raise SystemExit(1)\nexpected=json.loads(${JSON.stringify(JSON.stringify(expectedRows))})\nraise SystemExit(0 if actual==expected else 1)\n`);
const adapterSource = `"""Inventory adapter using unmodified CPython csv; PSF License Version 2.\nReference: https://docs.python.org/3.12/library/csv.html\n"""\nimport argparse,csv,hashlib,json,sys\nfrom decimal import Decimal\nfrom pathlib import Path\np=argparse.ArgumentParser()\np.add_argument('input')\np.add_argument('output')\na=p.parse_args()\nwith open(a.input,encoding='utf-8',newline='') as f:\n rows=list(csv.DictReader(f,strict=True))\nitems=[]\ntotal=Decimal('0')\nfor row in rows:\n quantity=int(row['qty'])\n price=Decimal(row['unit_price'])\n subtotal=quantity*price\n total+=subtotal\n items.append({'sku':row['sku'],'description':row['description'],'quantity':quantity,'subtotal':format(subtotal,'.2f')})\nresult={'items':items,'total':format(total,'.2f'),'provenance':{'module':'csv','source':csv.__file__,'sha256':hashlib.sha256(Path(csv.__file__).read_bytes()).hexdigest(),'python':sys.version}}\nPath(a.output).write_text(json.dumps(result,ensure_ascii=False)+'\\n',encoding='utf-8')\n`;
const expectedItems = [
  { sku: 'A-1', description: 'Widget, small', quantity: 2, subtotal: '7.00' },
  { sku: 'B-2', description: 'He said "yes"', quantity: 1, subtotal: '0.10' },
  { sku: 'C-3', description: 'line one\nline two', quantity: 0, subtotal: '0.00' },
  { sku: 'D-4', description: 'café', quantity: 3, subtotal: '3.60' },
];
const adapterVerifier = path.join(fixture, 'verify-inventory.py');
fs.writeFileSync(adapterVerifier, `import ast,json,subprocess,sys,tempfile\nfrom pathlib import Path\np=Path('inventory.json');script=Path('inventory_cli.py')\ntry:\n result=json.loads(p.read_text());source=script.read_text()\nexcept (OSError,ValueError):\n raise SystemExit(1)\nexpected=json.loads(${JSON.stringify(JSON.stringify(expectedItems))})\nassert result['items']==expected and result['total']=='10.70'\nassert result['provenance']['module']=='csv' and result['provenance']['sha256']==${JSON.stringify(provenance.module_sha256)}\nassert any(isinstance(n,ast.Import) and any(a.name=='csv' for a in n.names) for n in ast.walk(ast.parse(source)))\nwith tempfile.TemporaryDirectory(dir=${JSON.stringify(fixture)}) as d:\n root=Path(d);input=root/'second.csv';output=root/'second.json'\n input.write_text('sku,description,qty,unit_price\\nE-5,"green, large",4,0.25\\n',encoding='utf-8')\n good=subprocess.run([sys.executable,'-B',str(script.resolve()),str(input),str(output)],capture_output=True,text=True)\n assert good.returncode==0,good.stderr\n second=json.loads(output.read_text())\n assert second['items']==[{'sku':'E-5','description':'green, large','quantity':4,'subtotal':'1.00'}] and second['total']=='1.00'\n input.write_text('sku,description,qty,unit_price\\nZ,"unfinished,1,1.00\\n',encoding='utf-8');output.unlink()\n bad=subprocess.run([sys.executable,'-B',str(script.resolve()),str(input),str(output)],capture_output=True,text=True)\n assert bad.returncode!=0 and not output.exists()\n print(json.dumps({'independent_literal_cases':5,'malformed_csv_rejected':True,'negative_exit':bad.returncode,'negative_stderr':bad.stderr}))\n`);
const docsVerifier = path.join(fixture, 'verify-docs.py');
fs.writeFileSync(docsVerifier, "from pathlib import Path\np=Path('USAGE.md')\nraise SystemExit(0 if p.is_file() and 'inventory_cli.py input.csv inventory.json' in p.read_text() and 'CPython csv' in p.read_text() else 1)\n");
const integrationVerifier = path.join(fixture, 'verify-integration.py');
fs.writeFileSync(integrationVerifier, `import hashlib,json,subprocess,sys\nfrom pathlib import Path\np=Path('integration.json')\nif not p.is_file():raise SystemExit(1)\nr=json.loads(p.read_text())\nassert r['files']=={n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in ['baseline.json','inventory_cli.py','inventory.json','USAGE.md']}\nassert subprocess.run([sys.executable,'-B',${JSON.stringify(adapterVerifier)}]).returncode==0\nassert subprocess.run([sys.executable,'-B',${JSON.stringify(docsVerifier)}]).returncode==0\n`);
const catalog = path.join(fixture, 'explicit-tool-fixture.py'); fs.writeFileSync(catalog, "import json;print(json.dumps({'ok':True,'results':[],'fixture':True}))\n");
Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PI_CODING_AGENT_DIR: agentDir,
  PI_PROJECT_KANBAN_PYTHON: python, PI_PROJECT_KANBAN_ADAPTER: path.join(workflow, 'pi_kanban.py'),
  PI_PROJECT_KANBAN_ADAPTER_SHA256: hash(path.join(workflow, 'pi_kanban.py')),
  PI_PROJECT_STATE_BASE: path.join(fixture, 'board-state'), HERMES_HOME: path.join(fixture, 'hermes-home'),
  PI_PROJECT_CONTEXT_PI_PACKAGE: piPackage, PI_SYSTEM_TOOL_PYTHON: python, PI_SYSTEM_TOOL_HELPER: catalog,
  PI_SYSTEM_TOOL_HELPER_SHA256: hash(catalog), PI_SYSTEM_TOOL_DATABASE: path.join(fixture, 'tool-fixture.sqlite') });
const binding = path.join(fixture, 'framework-binding.json');
const generated = spawnSync(options['framework-python'], ['-B', path.join(runtime, 'adapters/pi/intake/framework_binding.py'), '--output', binding],
  { env: process.env, encoding: 'utf8', timeout: 30000 });
assert.equal(generated.status, 0, generated.stdout + generated.stderr);
process.env.PI_FRAMEWORK_BINDING = binding; process.env.PI_FRAMEWORK_BINDING_SHA256 = JSON.parse(generated.stdout).sha256;
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
const settings = sdk.SettingsManager.inMemory({ extensions: ['agent-capabilities.ts', 'system-tool-knowledge.ts', 'pi-kanban.ts', 'everyday-workflow.ts'].map(name => path.join(workflow, name)),
  defaultTools: ['read', 'ls', 'find', 'grep'], cacheWarming: 'off' });
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
  noThemes: true, noPromptTemplates: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const skills = loader.getSkills(); assert.deepEqual(skills.diagnostics.filter(item => item.type === 'error'), []);
assert.ok(skills.skills.some(item => item.name === 'reuse-first-engineering' && fs.realpathSync(item.filePath) === skill));
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const sessionManager = sdk.SessionManager.inMemory(project);
const model = { id: 'fixture-no-inference', name: 'No inference', api: 'openai-completions', provider: 'fixture-local',
  baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false, contextWindow: 32768, maxTokens: 4096,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const { session } = await sdk.createAgentSession({ cwd: project, agentDir, settingsManager: settings,
  resourceLoader: loader, sessionManager, modelRuntime, model, thinkingLevel: 'off' });
const errors = []; await session.bindExtensions({ onError: error => errors.push(error) });
const checks = [], trace = [], hostRuns = []; let sequence = 0, lastMessage;
async function tool(name, input, allowError = false) {
  const runner = session.extensionRunner, id = `reuse-native-${++sequence}`;
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!blocked?.block, `${name} blocked: ${blocked?.reason}`);
  const item = runner.getAllRegisteredTools().find(value => value.definition.name === name);
  const wrapped = item ? sdk.wrapRegisteredTool(item, runner) : sdk.createReadTool(project);
  const raw = await wrapped.execute(id, input, new AbortController().signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...raw, isError: raw.isError === true });
  const result = { ...raw, ...changed };
  lastMessage = { role: 'toolResult', toolCallId: id, toolName: name, content: result.content, details: result.details,
    isError: result.isError === true, timestamp: Date.now() };
  sessionManager.appendMessage({ role: 'assistant', api: model.api, provider: model.provider, model: model.id,
    content: [{ type: 'toolCall', id, name, arguments: input }], stopReason: 'toolUse', timestamp: Date.now() });
  sessionManager.appendMessage(lastMessage); trace.push({ id, name, input, result });
  if (!allowError) assert.ok(!result.isError, `${name} failed: ${JSON.stringify(result.content).slice(0, 700)}`);
  return result;
}
async function context() {
  for (let i = 0; i < 32; i++) {
    const result = await tool('project_context', { path: project }); await session.extensionRunner.emitContext([structuredClone(lastMessage)]);
    if (!result.details.remaining_reads.length) return;
  }
  assert.fail('Context read bound exceeded');
}
async function admission(input) {
  return session.extensionRunner.emitToolCall({ type: 'tool_call', toolCallId: `admission-${++sequence}`, toolName: 'workflow_step', input });
}
function plan(objective, code, verify, outputs, selected = true) {
  return { objective, cwd: project, action: [python, '-B', '-c', code], verify: [python, '-B', verify, ...(verify === baselineVerifier ? ['baseline.json'] : [])], outputs,
    ...(selected ? { required_skills: ['reuse-first-engineering'] } : {}) };
}
async function step(input) {
  const result = await tool('workflow_step', input); assert.equal(result.details.host.status, 'supplied_predicate_passed');
  hostRuns.push(result.details.host.run_id); return result;
}
async function route(text, parts) {
  await session.extensionRunner.emitInput(text, undefined, 'interactive');
  const pending = (await tool('kanban_intake_status', {})).details.result.pending;
  return tool('kanban_intake_route', { source_id: pending.at(-1).id, parts });
}
try {
  assert.ok(loader.getAppendSystemPromptSources().some(item => fs.realpathSync(item.path) === path.join(agentDir, 'APPEND_SYSTEM.md')));
  assert.ok(session.systemPrompt.includes(posture.trim())); assert.ok(session.systemPrompt.includes('reuse-first-engineering'));
  assert.ok(!session.systemPrompt.includes('An import,\nreal executable call or unchanged source dependency is reuse.'));
  assert.ok(!session.systemPrompt.includes('Moving code into a plugin while its old service still runs is not consolidation.'));
  checks.push('actual-native-posture-loaded', 'native-skill-metadata-discovered-without-bulk-body-or-reference');
  await tool('project_admit', { project_root: project, initialize: true, native_authority: 'Owner authorized isolated reuse-first qualification',
    target: 'Inventory CSV CLI with reliable quoting, totals and usage', why: 'Reuse the installed Python CSV implementation through the existing workflow' });
  const rootText = 'Deliver an inventory CSV CLI using an existing implementation. Preserve commas, quotes, embedded newlines and Unicode; calculate exact decimal totals; reject malformed input; include verified usage. Keep the known-good baseline and finish integration. Do not replace CSV with a custom parser.';
  const routed = await route(rootText, [{ kind: 'task', summary: rootText, execute: true, expandable: true }]);
  const root = routed.details.result.bound[0].task_id;
  const split = await tool('kanban_decompose', { task_id: root, children: [
    { title: 'Reuse CSV and qualify the inventory CLI', body: 'Use CPython csv, preserve edge cases and baseline; verify exact totals.' },
    { title: 'Write and verify independent CLI usage', body: 'Document the actual invoked CLI and retained Python attribution.' },
  ] });
  const [implementation, docs] = split.details.result.root.children.map(item => item.id);
  await tool('kanban_select', { task_id: implementation }); await tool('agent_capabilities', {});
  await tool('system_tool_query', { terms: 'CSV existing Python library' }); await tool('project_knowledge_query', { terms: 'inventory CSV reuse' });
  await session.extensionRunner.emitToolResult({ type: 'tool_result', toolCallId: 'explicit-validated-fixture', toolName: 'validated_memory_query', input: {}, content: [],
    details: { schema: 'validated-memory-query/v1', results: [], reason: 'no_current_provenanced_result', fixture: true }, isError: false });
  await tool('read', { path: path.join(agentDir, 'skills/supervised-tasks/SKILL.md') }); await context();
  const referenceCode = "import csv,json;from pathlib import Path\nwith open('input.csv',encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f,strict=True))\nPath('baseline.json').write_text(json.dumps(rows,ensure_ascii=False)+'\\n',encoding='utf-8')\n";
  const referencePlan = plan('Run the existing CPython CSV reference before adaptation', referenceCode, baselineVerifier, ['baseline.json']);
  const held = await admission(referencePlan); assert.equal(held?.block, true); assert.match(held.reason, /reuse-first-engineering/);
  const mainRead = await tool('read', { path: skill }); assert.equal(mainRead.content[0].text, skillText);
  const referenceLines = referenceText.split('\n'), start = referenceLines.indexOf('## Compare the real result'), end = referenceLines.indexOf('## Integrate and continue');
  assert.ok(start >= 0 && end > start);
  const sectionRead = await tool('read', { path: reference, offset: start + 1, limit: end - start });
  assert.ok(sectionRead.content[0].text.includes('Define\nthe expected result independently of either implementation.'));
  assert.ok(!sectionRead.content[0].text.includes('## Establish actual reuse'));
  await tool('read', { path: provenance.module });
  checks.push('selected-skill-required-before-host-action', 'native-selected-skill-and-one-targeted-reference-section-read', 'real-existing-cpython-source-inspected');
  await step(referencePlan); const baselineHash = hash(path.join(project, 'baseline.json'));
  const weaker = spawnSync(python, ['-B', baselineVerifier, 'weaker-result.json'], { cwd: project, encoding: 'utf8', timeout: 30000 });
  assert.equal(weaker.status, 1); assert.equal(hash(path.join(project, 'baseline.json')), baselineHash);
  checks.push('real-reference-run-before-adaptation', 'independent-weaker-candidate-rejected-with-best-baseline-preserved');
  await route('Could writing a new CSV parser be more interesting?', [{ kind: 'question', summary: 'Method question only; no replacement scope authorized' }]);
  const rootAfterQuestion = await tool('kanban_show', { task_id: root });
  assert.ok(rootAfterQuestion.details.result.task.body.includes(rootText));
  assert.equal((await tool('kanban_intake_status', {})).details.result.retained_total, 1);
  checks.push('novelty-question-preserves-root-outcome-and-constraints');
  await step(plan('Adapt the existing CSV library into the requested CLI',
    `from pathlib import Path;import subprocess,sys\nPath('inventory_cli.py').write_text(${JSON.stringify(adapterSource)},encoding='utf-8')\nraise SystemExit(subprocess.run([sys.executable,'-B','inventory_cli.py','input.csv','inventory.json']).returncode)`,
    adapterVerifier, ['inventory_cli.py', 'inventory.json']));
  assert.equal(JSON.parse(fs.readFileSync(path.join(project, 'inventory.json'))).provenance.sha256, provenance.module_sha256);
  checks.push('actual-library-import-and-version-bound-provenance', 'independent-quoting-newline-unicode-zero-decimal-and-malformed-cases');
  await tool('kanban_move', { task_id: implementation, transition: 'block', reason: 'Wait for the independent edge-case check after documentation; other work is ready.' });
  await tool('kanban_select', { task_id: docs });
  assert.ok(!(await admission(plan('Write CLI usage', 'pass', docsVerifier, ['USAGE.md'])))?.block);
  const usage = '# Inventory usage\n\nRun: python inventory_cli.py input.csv inventory.json\n\nUses unmodified CPython csv (PSF License Version 2). Input is UTF-8 with normal CSV quoting.\n';
  await step(plan('Complete independent useful documentation while a leaf is blocked', `from pathlib import Path\nPath('USAGE.md').write_text(${JSON.stringify(usage)},encoding='utf-8')`, docsVerifier, ['USAGE.md']));
  await tool('kanban_move', { task_id: docs, transition: 'complete', summary: 'Actual CLI invocation and CSV attribution verified.' });
  const premature = await tool('kanban_work_checkpoint', { disposition: 'complete', reason: 'Check root completion while a required leaf is held.' }, true);
  assert.equal(premature.isError, true); checks.push('blocked-dependency-keeps-independent-authorized-work-available');
  const checked = spawnSync(python, ['-B', adapterVerifier], { cwd: project, encoding: 'utf8', timeout: 30000 });
  writeJson(path.join(fixture, 'independent-edge-check.json'), { exit_code: checked.status, stdout: checked.stdout, stderr: checked.stderr });
  assert.equal(checked.status, 0, checked.stderr);
  await tool('kanban_move', { task_id: implementation, transition: 'unblock', reason: 'Actual independent edge-case check passed; exact receipt retained.' });
  await tool('kanban_move', { task_id: implementation, transition: 'complete', summary: 'CLI and independent literal edge cases verified; baseline unchanged.' });
  const beforeIntegration = await tool('kanban_work_checkpoint', { disposition: 'complete', reason: 'Check completion after child work, before root integration.' }, true);
  assert.equal(beforeIntegration.isError, true); assert.ok((await tool('kanban_show', { task_id: root })).details.result.task.body.includes(rootText));
  checks.push('completed-child-queue-does-not-accept-unfinished-root-integration');
  await tool('kanban_select', { task_id: root });
  await step(plan('Verify and retain complete inventory CLI integration',
    "import hashlib,json;from pathlib import Path\nnames=['baseline.json','inventory_cli.py','inventory.json','USAGE.md']\nPath('integration.json').write_text(json.dumps({'files':{n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in names}})+'\\n')",
    integrationVerifier, ['integration.json']));
  assert.equal(hash(path.join(project, 'baseline.json')), baselineHash);
  await tool('kanban_move', { task_id: root, transition: 'complete', summary: 'All original CLI, negative, attribution, usage and integration criteria independently checked.' });
  await tool('kanban_work_checkpoint', { disposition: 'complete', reason: 'Retained fixture queue finished; no broader product acceptance claim.' });
  const decision = sessionManager.getBranch().filter(item => item.type === 'custom' && item.customType === 'pi-work-decision/v1').at(-1);
  assert.equal(decision.data.decision, 'queue_complete'); assert.equal(decision.data.authority, 'retained_queue_only_not_root_acceptance');
  checks.push('next-root-integration-completed-through-existing-host', 'framework-queue-completion-keeps-root-acceptance-boundary');
  for (const run of hostRuns) {
    const final = JSON.parse(fs.readFileSync(path.join(project, '.enforcement/runs', run, 'final.json')));
    assert.equal(final.status, 'accepted'); assert.equal(final.attempts[0].negative_control_exit_code, 0);
  }
  assert.deepEqual(errors, []); assert.equal(session.pendingMessageCount, 0);
  const readPaths = trace.filter(item => item.name === 'read').map(item => item.input.path);
  assert.ok(!readPaths.includes(path.join(agentDir, 'skills/source-control/SKILL.md')));
  const receipt = { status: 'passed', fixture, checks, root_task: root, root_source_text: rootText, host_runs: hostRuns,
    baseline_sha256: baselineHash, dependency: provenance, native_probe_sha256: hash(new URL(import.meta.url)),
    runtime_manifest_sha256: hash(path.join(runtime, 'runtime-manifest.json')), posture_sha256: hash(path.join(agentDir, 'APPEND_SYSTEM.md')),
    skill_sha256: hash(skill), reference_sha256: hash(reference), discovered_skill_names: skills.skills.map(item => item.name),
    main_skill_bytes_read: Buffer.byteLength(mainRead.content[0].text), reference_section_bytes_read: Buffer.byteLength(sectionRead.content[0].text),
    reference_read_window: { offset: start + 1, limit: end - start }, selected_read_paths: readPaths,
    elapsed_ms: Date.now() - started, model_calls: 0, provider_http: 0, commits: 0, pushes: 0,
    limits: 'Scripted actual Pi native discovery/read/context/intake, real existing CPython reuse and guarded host execution with independent literal oracles. Catalog/memory readiness are explicit fixtures. No spontaneous model selection, reasoning quality, general engineering superiority, live project, shared dispatch, package installation or installed-home adoption claim.' };
  writeJson(path.join(fixture, 'native-trace.json'), trace); writeJson(path.join(fixture, 'receipt.json'), receipt); console.log(JSON.stringify(receipt, null, 2));
} catch (error) {
  writeJson(path.join(fixture, 'native-trace.json'), trace); writeJson(path.join(fixture, 'failure.json'), { status: 'failed', fixture, checks,
    error: String(error?.stack || error), native_probe_sha256: hash(new URL(import.meta.url)), elapsed_ms: Date.now() - started });
  console.error(JSON.stringify({ fixture, failure_receipt: path.join(fixture, 'failure.json') })); throw error;
} finally {
  await session.extensionRunner.emit({ type: 'session_shutdown' }); session.dispose();
}
