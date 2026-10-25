import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

const options = {};
for (let index = 2; index < process.argv.length; index += 2) {
  assert(process.argv[index]?.startsWith('--') && process.argv[index + 1], 'Use --name value arguments');
  options[process.argv[index].slice(2)] = process.argv[index + 1];
}
for (const name of ['pi-package', 'context', 'fixture-parent']) assert(options[name], 'Missing --' + name);
const piPackage = fs.realpathSync(options['pi-package']);
const contextSource = fs.realpathSync(options.context);
const { loadExtensions } = await import(pathToFileURL(path.join(piPackage, 'dist/core/extensions/loader.js')).href);
const { ExtensionRunner } = await import(pathToFileURL(path.join(piPackage, 'dist/core/extensions/runner.js')).href);
const { createReadTool, createGrepTool } = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')).href);

const base = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'native-context-fixture-'));
const selectedWrapper = path.join(base, 'context-wrapper.ts');
const agentDir = path.join(base, 'agent');
fs.mkdirSync(agentDir);
process.env.PI_CODING_AGENT_DIR = agentDir;
process.env.PI_PROJECT_CONTEXT_PI_PACKAGE = piPackage;
process.env.PI_PROJECT_STATE_BASE = path.join(base, 'state');
const project = path.join(base, 'project');
fs.mkdirSync(project);
const selectionFile = path.join(base, 'selection.json');
const identity = { canonical_root: project, project_id: 'fixture-project', board_id: 'fixture-board', workspace_path: '.icm/workspace' };
fs.writeFileSync(selectionFile, JSON.stringify({ root: project, projectId: identity.project_id, boardId: identity.board_id }));
fs.mkdirSync(path.join(project, '.icm/workspace'), { recursive: true });
fs.writeFileSync(path.join(project, '.icm/project.json'), JSON.stringify(identity));
for (const name of ['AGENTS.md', 'PROJECT-SSOT.md', 'ACTIVE-CHECKPOINT.md'])
  fs.writeFileSync(path.join(project, '.icm/workspace', name), '# Fixture ' + name + '\nUse the reviewed project route.\n');
fs.writeFileSync(selectedWrapper, `import { readFileSync } from 'node:fs';
import { registerProjectContext } from ${JSON.stringify(path.join(contextSource, 'project-context.ts'))};
export default function(pi) { registerProjectContext(pi, { project: () => JSON.parse(readFileSync(${JSON.stringify(selectionFile)}, 'utf8')) }); }
`);
const entries = [], checks = [];
let ext, loaded, runner, prompt = '', serial = 0;
const ctx = { cwd: project, getSystemPrompt: () => prompt,
  sessionManager: { getBranch: () => entries, getSessionId: () => 'context-native-fixture' },
  ui: { setStatus() {}, notify() {} } };
async function emit(name, event = {}) {
  const out = [];
  for (const handler of ext.handlers.get(name) ?? []) out.push(await handler(event, ctx));
  return out;
}
async function load() {
  if (ext) await emit('session_shutdown');
  loaded = await loadExtensions([selectedWrapper], agentDir);
  assert.deepEqual(loaded.errors, []);
  ext = loaded.extensions[0];
  loaded.runtime.appendEntry = (customType, data) => entries.push({ type: 'custom', customType, data: structuredClone(data) });
  loaded.runtime.sendMessage = () => { throw Error('No model wake is allowed in this fixture'); };
  runner = new ExtensionRunner(loaded.extensions, loaded.runtime, project, ctx.sessionManager, {});
  runner.getSystemPromptFn = () => prompt;
  await emit('session_start');
}
async function call(name, args = {}) {
  const id = 'context-call-' + (++serial);
  const result = await ext.tools.get(name).definition.execute(id, args, undefined, undefined, ctx);
  await emit('tool_result', { toolName: name, toolCallId: id, input: args,
    content: result.content, details: result.details, isError: result.isError });
  return { id, result };
}
function ok(value) { assert(!value.result.isError, JSON.stringify(value.result)); return value.result.details; }
async function deliver(value, override = {}) {
  await emit('context', { messages: [{ role: 'toolResult', toolCallId: value.id,
    content: value.result.content, isError: false, ...override }] });
}
async function context(target = project) {
  const result = await call('project_context', { path: target });
  ok(result); await deliver(result); return result;
}
async function gate(name, input) {
  const result = await runner.emitToolCall({ type: 'tool_call', toolName: name,
    toolCallId: 'gate-' + (++serial), input });
  return result?.block ? [result] : [];
}
const readGate = target => gate('read', { path: target });
const scope = name => path.join(project, name);

await load();
fs.writeFileSync(scope('AGENTS.md'), '# Project\nUse the existing workspace router.\n');
for (const name of ['a', 'b']) {
  fs.mkdirSync(scope(name));
  fs.writeFileSync(scope(name + '/AGENTS.md'), '# Topic ' + name + '\nApply only to topic ' + name + '.\n');
  fs.writeFileSync(scope(name + '/source.txt'), name + '\n');
}
fs.writeFileSync(scope('source.txt'), 'root\n');
fs.writeFileSync(scope('.ignore'), '!**\n');
const checkpoint = scope('.icm/workspace/ACTIVE-CHECKPOINT.md');
fs.writeFileSync(checkpoint, '# Current\nFixture active.\n' + Array.from({ length: 120 }, (_, i) => 'Line ' + i).join('\n'));
assert((await readGate(scope('source.txt'))).length);
assert.equal((await readGate(scope('AGENTS.md'))).length, 0);
checks.push('Project source waits for instructions; instruction files remain readable');

const first = await call('project_context', { path: project });
const initial = ok(first);
assert(Buffer.byteLength(first.result.content[0].text) <= 32768);
assert(!JSON.stringify(initial).includes('Apply only to topic a'));
const head = initial.documents.find(x => x.role === 'current-checkpoint-head');
assert(head.excerpt && Buffer.byteLength(head.text) <= 4096 && head.text.split('\n').length <= 64);
assert((await readGate(scope('source.txt'))).length, 'Tool completion alone must not admit work');
await deliver(first, { content: [{ type: 'text', text: 'path-only claim' }] });
assert((await readGate(scope('source.txt'))).length);
const second = await call('project_context', { path: project }); ok(second);
await deliver(second, { isError: true });
assert((await readGate(scope('source.txt'))).length);
const third = await call('project_context', { path: project }); ok(third); await deliver(third);
assert.equal((await readGate(scope('source.txt'))).length, 0);
checks.push('Bounded source bytes must reach later model context; same-round, changed and failed results do not admit work');

const actualGrep = await createGrepTool(project).execute('actual-grep', { path: project, pattern: '^a$', glob: 'source.txt' }, undefined, undefined, ctx);
assert(actualGrep.content.some(x => x.type === 'text' && x.text.includes('a/source.txt')));
assert((await gate('grep', { path: project, pattern: '^a$', glob: 'source.txt' })).length);
assert.equal((await gate('grep', { path: scope('source.txt'), pattern: '.' })).length, 0);
checks.push('Actual recursive native grep reaches child files; the gate requires child context or actionable narrowing');

assert((await readGate(scope('a/source.txt'))).length);
const a = await context(scope('a/source.txt'));
assert.deepEqual(ok(a).documents.map(x => path.basename(path.dirname(x.path))), ['a']);
assert.equal((await readGate(scope('a/source.txt'))).length, 0);
assert((await readGate(scope('b/source.txt'))).length);
assert(!JSON.stringify(ok(a)).includes('Apply only to topic b'));
await context(scope('b'));
assert.equal((await readGate(scope('b/source.txt'))).length, 0);
checks.push('Child instructions load on demand; siblings are not scanned or implicitly admitted');

const savedInstructions = fs.readFileSync(scope('AGENTS.md'));
const longInstructions = '# Project instructions\n' + 'Use scoped local rules.\n'.repeat(3000);
fs.writeFileSync(scope('AGENTS.md'), longInstructions);
const truncated = await createReadTool(project).execute('actual-truncated-read', { path: scope('AGENTS.md') }, undefined, undefined, ctx);
assert(truncated.details?.truncation, 'The native read must actually truncate this fixture');
await emit('tool_result', { toolName: 'read', toolCallId: 'actual-truncated-read', input: { path: scope('AGENTS.md') }, ...truncated });
await deliver({ id: 'actual-truncated-read', result: truncated });
assert((await readGate(scope('source.txt'))).length);
const windows = [];
for (let i = 0; i < 16 && (await readGate(scope('source.txt'))).length; i++) {
  const value = await context();
  const part = ok(value).documents.find(d => d.path === scope('AGENTS.md'));
  assert(part?.range && Buffer.byteLength(value.result.content[0].text) <= 32768);
  windows.push(part.text);
}
assert.equal(windows.join(''), longInstructions);
assert.equal((await readGate(scope('source.txt'))).length, 0);
const embeddedBom = 'x'.repeat(8192) + '\uFEFF' + 'y'.repeat(10000);
fs.writeFileSync(scope('AGENTS.md'), embeddedBom);
const bomWindows = [];
for (let i = 0; i < 8 && (await readGate(scope('source.txt'))).length; i++) {
  const value = await context();
  const part = ok(value).documents.find(d => d.path === scope('AGENTS.md'));
  assert(part?.range); bomWindows.push(part.text);
}
assert.equal(bomWindows.join(''), embeddedBom);
assert.equal((await readGate(scope('source.txt'))).length, 0);
checks.push('A U+FEFF at a later UTF-8 window boundary is preserved without byte loss or duplication');
fs.writeFileSync(scope('AGENTS.md'), 'x'.repeat(131073));
assert((await call('project_context', { path: project })).result.isError);
assert.equal((await readGate(scope('AGENTS.md'))).length, 0);
fs.writeFileSync(scope('AGENTS.md'), savedInstructions); await context();
checks.push('A genuinely native-truncated instruction read cannot admit work; bounded sequential source windows recover oversized instructions');

fs.appendFileSync(scope('a/AGENTS.md'), 'Changed requirement.\n');
assert((await readGate(scope('a/source.txt'))).length);
await context(scope('a'));
assert.equal((await readGate(scope('a/source.txt'))).length, 0);
fs.appendFileSync(checkpoint, '\nHistorical tail append.\n');
assert.equal((await readGate(scope('source.txt'))).length, 0);
fs.writeFileSync(checkpoint, fs.readFileSync(checkpoint, 'utf8').replace('Fixture active.', 'Fixture current changed.'));
assert((await readGate(scope('source.txt'))).length);
await context();
checks.push('Changed instruction/current bytes invalidate admission; archive-only tail growth does not');

const savedCheckpoint = fs.readFileSync(checkpoint);
fs.writeFileSync(checkpoint, '\uFEFF# Current\n' + '🂡'.repeat(5000) + '\n' + 'Historical archive\n'.repeat(70000));
const largeHead = ok(await context()).documents.find(x => x.role === 'current-checkpoint-head');
assert(largeHead.source_bytes > 1024 * 1024 && largeHead.excerpt);
assert(Buffer.byteLength(largeHead.text) <= 4096 && !largeHead.text.includes('\uFFFD'));
assert(largeHead.text.startsWith('# Current\n'));
fs.writeFileSync(checkpoint, savedCheckpoint); await context();
checks.push('Large checkpoint archives stay outside the4KiB view; BOM and UTF-8 cutoffs retain valid source text');

await emit('session_compact');
const fakeRead = async (file, text, isError = false) => {
  const id = 'read-' + (++serial);
  const event = { toolName: 'read', toolCallId: id, input: { path: file },
    content: [{ type: 'text', text }], isError };
  await emit('tool_result', event);
  return { id, result: event };
};
for (const doc of ok(await call('project_context', { path: project })).documents) {
  // Do not deliver project_context; qualify the ordinary native read result path instead.
  let value = await fakeRead(doc.path, doc.text.slice(0, 7)); await deliver(value);
  assert((await readGate(scope('source.txt'))).length);
  value = await fakeRead(doc.path, doc.text, true); await deliver(value);
  assert((await readGate(scope('source.txt'))).length);
  value = await fakeRead(doc.path, doc.text);
  assert((await readGate(scope('source.txt'))).length);
  await deliver(value);
}
assert.equal((await readGate(scope('source.txt'))).length, 0);
checks.push('Full native read evidence works; failed and partial reads cannot substitute');

const identityBefore = JSON.parse(fs.readFileSync(selectionFile, 'utf8'));
await load();
assert((await readGate(scope('source.txt'))).length);
await context();
assert.equal((await readGate(scope('source.txt'))).length, 0);
assert.deepEqual(JSON.parse(fs.readFileSync(selectionFile, 'utf8')), identityBefore);
checks.push('Reload requires fresh delivery and does not rewrite the supplied project identity');

prompt = scope('AGENTS.md') + '\n' + fs.readFileSync(scope('AGENTS.md'), 'utf8');
await emit('session_tree');
const native = ok(await context());
assert(!native.documents.some(x => x.path === scope('AGENTS.md')));
prompt = scope('AGENTS.md'); await emit('session_tree');
assert(ok(await context()).documents.some(x => x.path === scope('AGENTS.md')));
prompt = '';
checks.push('Native-injected exact bytes count; a native locator without body does not');

// This fixture supplies identity only. The separate coordinator tests own admission.
await context();
const rootAction = { cwd: project, action: 'printf fixture', verify: 'test -d .', outputs: [] };
assert.equal((await gate('run_step', rootAction)).length, 0);
assert((await gate('run_step', { ...rootAction, cwd: scope('a') })).length);
assert((await gate('workflow_step', { ...rootAction, outputs: ['a/new/sub/result.txt'] })).some(x => x.reason.includes('project context')));
await context(scope('a'));
assert.equal((await gate('run_step', { ...rootAction, cwd: scope('a') })).length, 0);
assert((await gate('run_step', { ...rootAction, cwd: base })).length);
checks.push('Declared execution cwd and output subtrees require their context; outside-project execution is refused');

fs.symlinkSync(base, scope('escape'));
assert((await gate('run_step', { ...rootAction, cwd: scope('escape') })).length);
fs.mkdirSync(scope('bad'));
fs.writeFileSync(path.join(base, 'outside-instructions.md'), '# Outside\n');
fs.symlinkSync(path.join(base, 'outside-instructions.md'), scope('bad/AGENTS.md'));
fs.writeFileSync(scope('bad/source.txt'), 'fixture\n');
assert((await readGate(scope('bad/source.txt'))).length);
const identityFile = scope('.icm/project.json');
const originalIdentity = fs.readFileSync(identityFile);
const badIdentity = JSON.parse(originalIdentity); badIdentity.board_id += '-wrong';
fs.writeFileSync(identityFile, JSON.stringify(badIdentity));
assert((await readGate(scope('source.txt'))).length);
assert((await call('project_context', { path: project })).result.isError);
assert.equal((await readGate(identityFile)).length, 0);
assert.equal((await readGate(scope('AGENTS.md'))).length, 0);
fs.writeFileSync(identityFile, originalIdentity);
checks.push('Symlink escape and mismatched project/board identity fail closed');

const router = scope('.icm/workspace/PROJECT-SSOT.md');
fs.renameSync(router, router + '.fixture-held');
assert((await readGate(scope('source.txt'))).length);
assert.equal((await readGate(scope('AGENTS.md'))).length, 0);
assert.equal((await readGate(checkpoint)).length, 0);
fs.renameSync(router + '.fixture-held', router);
checks.push('Broken identity or missing workspace routes cannot deadlock native instruction/recovery inspection');

await context();
const secondProject = path.join(base, 'second-project');
fs.mkdirSync(path.join(secondProject, '.icm/workspace'), { recursive: true });
const secondIdentity = { ...identity, canonical_root: secondProject, project_id: 'second-project', board_id: 'second-board' };
fs.writeFileSync(path.join(secondProject, '.icm/project.json'), JSON.stringify(secondIdentity));
for (const name of ['AGENTS.md', 'PROJECT-SSOT.md', 'ACTIVE-CHECKPOINT.md'])
  fs.writeFileSync(path.join(secondProject, '.icm/workspace', name), '# Second project ' + name + '\n');
fs.writeFileSync(path.join(secondProject, 'AGENTS.md'), '# Second project\nUse only second-project context.\n');
fs.writeFileSync(path.join(secondProject, 'source.txt'), 'second project\n');
fs.writeFileSync(selectionFile, JSON.stringify({ root: secondProject, projectId: secondIdentity.project_id, boardId: secondIdentity.board_id }));
assert((await readGate(path.join(secondProject, 'source.txt'))).length);
const secondContext = ok(await context(secondProject));
assert(secondContext.documents.some(doc => doc.text.includes('Use only second-project context.')));
assert(!secondContext.documents.some(doc => doc.path.startsWith(project + path.sep)));
assert.equal((await readGate(path.join(secondProject, 'source.txt'))).length, 0);
fs.writeFileSync(selectionFile, JSON.stringify(identityBefore));
assert.equal((await readGate(scope('source.txt'))).length, 0);
checks.push('Project switches keep source delivery scoped to exact project roots and identities');

const firstHint = (await emit('before_agent_start', { systemPrompt: 'Fixture base.' })).find(r => r?.systemPrompt?.includes('Project context: use project_context'));
assert(firstHint);
const repeatedHints = await emit('before_agent_start', { systemPrompt: firstHint.systemPrompt });
assert(!repeatedHints.some(r => (r?.systemPrompt?.split('Project context: use project_context').length ?? 0) > 2));
checks.push('Repeated startup processing does not duplicate the context policy');
await emit('session_shutdown');
const wrongPackage = path.join(base, 'wrong-pi-package');
fs.mkdirSync(path.join(wrongPackage, 'dist/core/tools'), { recursive: true });
fs.mkdirSync(path.join(wrongPackage, 'dist/utils'), { recursive: true });
fs.copyFileSync(path.join(piPackage, 'package.json'), path.join(wrongPackage, 'package.json'));
for (const name of ['dist/core/tools/path-utils.js', 'dist/utils/tools-manager.js'])
  fs.copyFileSync(path.join(piPackage, name), path.join(wrongPackage, name));
fs.appendFileSync(path.join(wrongPackage, 'dist/core/tools/path-utils.js'), '\n// changed native helper\n');
process.env.PI_PROJECT_CONTEXT_PI_PACKAGE = wrongPackage;
const drifted = await loadExtensions([selectedWrapper], agentDir);
assert(drifted.errors.some(error => String(error.error).includes('native API source drift')));
delete process.env.PI_PROJECT_CONTEXT_PI_PACKAGE;
const missingBinding = await loadExtensions([selectedWrapper], agentDir);
assert(missingBinding.errors.some(error => String(error.error).includes('PI_PROJECT_CONTEXT_PI_PACKAGE')));
process.env.PI_PROJECT_CONTEXT_PI_PACKAGE = piPackage;
checks.push('Missing package bindings and changed internal native API bytes fail at the actual extension loader');
const report = { passed: true, checks, fixture_root: base, native_extension_loader: true,
  fixture_identity_binding: true, native_tool_call_runner: true,
  controlled_hook_events: true, model_inference_tested: false,
  wrapper_path: selectedWrapper,
  wrapper_sha256: createHash('sha256').update(fs.readFileSync(selectedWrapper)).digest('hex'),
  source_sha256: createHash('sha256').update(fs.readFileSync(path.join(contextSource, 'project-context.ts'))).digest('hex') };
fs.writeFileSync(path.join(base, 'test-result.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report));
