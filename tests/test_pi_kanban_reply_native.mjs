/** Actual Pi/Hermes reply projection. All board data is synthetic and fixture-owned. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i]?.startsWith('--') && process.argv[i + 1], 'Use --name value arguments');
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['pi-package', 'source', 'python', 'fixture-parent']) assert.ok(options[name], `Missing --${name}`);
const started = Date.now(), source = fs.realpathSync(options.source), piPackage = fs.realpathSync(options['pi-package']);
const python = path.resolve(options.python); // Keep the caller's selected virtual environment.
const fixture = fs.mkdtempSync(path.join(fs.realpathSync(options['fixture-parent']), 'pi-kanban-reply-'));
const runtime = path.join(fixture, 'runtime'), agentDir = path.join(fixture, 'agent'), project = path.join(fixture, 'project');
for (const directory of [runtime, agentDir, project]) fs.mkdirSync(directory);
const sha = value => createHash('sha256').update(value).digest('hex');
const digest = file => sha(fs.readFileSync(file));
const jsonHash = value => sha(JSON.stringify(value));
const bytes = value => Buffer.byteLength(value);
const ordered = value => Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])])) : value;
const rowHash = value => jsonHash(ordered(value));
const writeJson = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
const sourceFiles = [];
function copyTree(relative) {
  for (const item of fs.readdirSync(path.join(source, relative), { withFileTypes: true })) {
    if (item.name === '__pycache__') continue;
    const name = path.join(relative, item.name);
    assert.ok(!item.isSymbolicLink(), `Source symlink is not admitted: ${name}`);
    if (item.isDirectory()) copyTree(name);
    else if (/\.(py|ts|mjs|md)$/.test(item.name)) {
      const target = path.join(runtime, name); fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(path.join(source, name), target);
      sourceFiles.push({ path: name.split(path.sep).join('/'), sha256: digest(target) });
    }
  }
}
copyTree('adapters/pi');
writeJson(path.join(fixture, 'source-manifest.json'), sourceFiles);
const workflow = path.join(runtime, 'adapters/pi/project-workflow');
const adapter = path.join(workflow, 'pi_kanban.py');
const projector = path.join(workflow, 'kanban-reply-projector.mjs');
assert.ok(fs.existsSync(projector), 'Copy the frozen projector and native wrapper before qualification');
const agentsText = '# Synthetic native reply fixture\n\nPreserve exact host details and distinct dependency and containment edges.\n';
fs.writeFileSync(path.join(project, 'AGENTS.md'), agentsText);
Object.assign(process.env, { PI_OFFLINE: '1', PI_SKIP_VERSION_CHECK: '1', PI_CODING_AGENT_DIR: agentDir,
  PI_PROJECT_KANBAN_PYTHON: python, PI_PROJECT_KANBAN_ADAPTER: adapter,
  PI_PROJECT_KANBAN_ADAPTER_SHA256: digest(adapter), PI_PROJECT_STATE_BASE: path.join(fixture, 'project-state'),
  HERMES_HOME: path.join(fixture, 'hermes-home'), PI_PROJECT_CONTEXT_PI_PACKAGE: piPackage });
let frameworkBinding;
if (options['framework-python']) {
  frameworkBinding = path.join(fixture, 'framework-binding.json');
  const generated = spawnSync(options['framework-python'], ['-B', path.join(runtime, 'adapters/pi/intake/framework_binding.py'), '--output', frameworkBinding],
    { encoding: 'utf8', env: process.env, timeout: 30000 });
  assert.equal(generated.status, 0, generated.stdout + generated.stderr);
  const result = JSON.parse(generated.stdout); assert.equal(result.ok, true);
  process.env.PI_FRAMEWORK_BINDING = frameworkBinding; process.env.PI_FRAMEWORK_BINDING_SHA256 = result.sha256;
} else {
  delete process.env.PI_FRAMEWORK_BINDING; delete process.env.PI_FRAMEWORK_BINDING_SHA256;
}
const sdk = await import(pathToFileURL(path.join(piPackage, 'dist/index.js')));
const require = createRequire(path.join(piPackage, 'package.json'));
// pi-ai publishes an import-only root. Use Node's dependency search locations
// to locate its manifest without pretending it has a CommonJS root export.
const aiManifest = require.resolve.paths('@earendil-works/pi-ai')
  .map(directory => path.join(directory, '@earendil-works/pi-ai/package.json')).find(file => fs.existsSync(file));
assert.ok(aiManifest, 'The selected actual Pi package must resolve its own pi-ai dependency');
const aiMetadata = JSON.parse(fs.readFileSync(aiManifest, 'utf8'));
assert.equal(aiMetadata.name, '@earendil-works/pi-ai'); assert.equal(aiMetadata.version, '1.4.0');
const aiDist = path.join(path.dirname(aiManifest), 'dist');
const providerFile = path.join(aiDist, 'api/openai-completions.js');
const { convertMessages } = await import(pathToFileURL(providerFile));
const settings = sdk.SettingsManager.inMemory({ extensions: [path.join(workflow, 'pi-kanban.ts')],
  defaultTools: ['read', 'ls', 'find', 'grep'], cacheWarming: 'off' });
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
  noSkills: true, noPromptTemplates: true, noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'] });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const sessionManager = sdk.SessionManager.inMemory(project);
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const model = { id: 'fixture-no-inference', name: 'No inference', provider: 'fixture-local', api: 'openai-completions',
  baseUrl: 'http://127.0.0.1:1/v1', input: ['text'], reasoning: false, contextWindow: 32768, maxTokens: 4096,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const { session } = await sdk.createAgentSession({ cwd: project, agentDir, resourceLoader: loader,
  settingsManager: settings, sessionManager, modelRuntime, model, thinkingLevel: 'off' });
const errors = []; await session.bindExtensions({ onError: error => errors.push(error) });
const checks = [], trace = [], metrics = [];
let sequence = 0, lastMessage;
function measure(name, input, result, id, timestamp = Date.now()) {
  const assistant = { role: 'assistant', api: model.api, provider: model.provider, model: model.id,
    content: [{ type: 'toolCall', id, name, arguments: input }], stopReason: 'toolUse', timestamp };
  const message = { role: 'toolResult', toolCallId: id, toolName: name, content: result.content,
    details: result.details, isError: result.isError === true, timestamp };
  // convertToLlm retains host details. The actual provider serializer drops them.
  // Serialize both content versions with exactly the same call, model, options
  // and timestamps. Compare content to content and envelope to envelope.
  const serialize = content => {
    const nativeMessages = sdk.convertToLlm([assistant, { ...message, content }]);
    const converted = convertMessages(model, { messages: nativeMessages }, {});
    const wire = converted.find(item => item.role === 'tool' && item.tool_call_id === id);
    assert.ok(wire, 'Actual installed OpenAI-compatible serializer must produce the native tool message');
    assert.equal(Object.hasOwn(wire, 'details'), false);
    return wire;
  };
  const wire = serialize(result.content);
  const backendBaseline = result.details?.schema === 'pi-kanban-result/v1';
  const baselineWire = serialize(backendBaseline ? [{ type: 'text', text: JSON.stringify(result.details) }] : result.content);
  assert.equal(wire.content, result.content.filter(block => block.type === 'text').map(block => block.text).join('\n'));
  const baselineContent = bytes(baselineWire.content), projectedContent = bytes(wire.content);
  const baselineEnvelope = bytes(JSON.stringify(baselineWire)), projectedEnvelope = bytes(JSON.stringify(wire));
  const comparison = { baseline: backendBaseline ? 'JSON.stringify(full unchanged backend reply)' : 'unchanged native tool content',
    baseline_content_bytes: baselineContent, projected_content_bytes: projectedContent,
    baseline_serialized_tool_bytes: baselineEnvelope, projected_serialized_tool_bytes: projectedEnvelope,
    content_ratio: baselineContent / projectedContent, serialized_tool_ratio: baselineEnvelope / projectedEnvelope,
    content_reduction_percent: 100 * (1 - projectedContent / baselineContent),
    serialized_tool_reduction_percent: 100 * (1 - projectedEnvelope / baselineEnvelope) };
  return { assistant, message, wire, baselineWire, comparison };
}
async function tool(name, input, allowFailure = false) {
  const runner = session.extensionRunner, id = `reply-native-${++sequence}`;
  const blocked = await runner.emitToolCall({ type: 'tool_call', toolCallId: id, toolName: name, input });
  assert.ok(!blocked?.block, `${name} blocked: ${blocked?.reason}`);
  const item = runner.getAllRegisteredTools().find(value => value.definition.name === name);
  const wrapped = item ? sdk.wrapRegisteredTool(item, runner) : sdk.createReadTool(project);
  const raw = await wrapped.execute(id, input, new AbortController().signal);
  const changed = await runner.emitToolResult({ type: 'tool_result', toolCallId: id, toolName: name, input, ...raw, isError: raw.isError === true });
  const result = { ...raw, ...changed };
  const serialized = measure(name, input, result, id); lastMessage = serialized.message;
  sessionManager.appendMessage(serialized.assistant); sessionManager.appendMessage(serialized.message);
  const metric = { name, content_bytes: bytes(serialized.wire.content), serialized_tool_bytes: bytes(JSON.stringify(serialized.wire)),
    details_bytes: bytes(JSON.stringify(result.details) ?? 'null'), details_sha256: jsonHash(result.details ?? null),
    tool_call_id: id, timestamp: serialized.message.timestamp, matched_comparison: serialized.comparison };
  metrics.push(metric); trace.push({ name, input, ...metric, isError: result.isError === true });
  if (['kanban_show', 'kanban_list', 'kanban_select', 'kanban_create', 'kanban_comment', 'kanban_move', 'kanban_decompose', 'kanban_hierarchy'].includes(name)
      && !result.isError) assert.ok(metric.content_bytes <= 12288, `${name} model content exceeded 12KiB`);
  if (!allowFailure) assert.ok(!result.isError, `${name} failed: ${JSON.stringify(result.content).slice(0, 600)}`);
  return result;
}
function rawAdapter(request) {
  const result = spawnSync(python, ['-B', adapter], { input: JSON.stringify({ project_root: project, ...request }),
    encoding: 'utf8', env: process.env, timeout: 30000, maxBuffer: 2 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr + result.stdout.slice(0, 300));
  const reply = JSON.parse(result.stdout); assert.equal(reply.ok, true); return reply;
}
const view = result => JSON.parse(result.content[0].text);
async function show(id, options = {}) { return tool('kanban_show', { task_id: id, view: options }); }
async function textPages(id, options, select, expected, hash) {
  let offset = 0, text = '';
  do {
    const result = view(await show(id, { ...options, expected_reply_sha256: hash,
      ...(options.task_field || options.comment_id !== undefined ? { offset } : { body_offset: offset }) }));
    const page = select(result.result);
    assert.equal(page.offset, offset); assert.equal(page.offset_unit, 'unicode_codepoints');
    assert.equal(page.sha256, sha(expected)); assert.equal(page.total_codepoints, Array.from(expected).length);
    assert.ok(!page.text.includes('\uFFFD')); text += page.text;
    if (page.next_offset === null) break;
    assert.ok(page.next_offset > offset); offset = page.next_offset;
  } while (offset <= 100000);
  assert.equal(text, expected);
}
try {
  await tool('project_admit', { project_root: project, initialize: true,
    native_authority: 'Owner authorized disposable native bounded-reply qualification',
    target: 'Synthetic Pi board replies', why: 'Verify model content without changing real projects or invoking inference' });
  const status = await tool('kanban_status', {});
  assert.deepEqual(view(status), status.details, 'Unrelated native status replies must keep their original content');
  checks.push('unrelated-status-content-unchanged');
  const body = '😀é界\n'.repeat(1200).trimEnd(), title = 'Synthetic retained card ' + '界'.repeat(140);
  const made = await tool('kanban_create', { title, body, idempotency_key: 'native-large-card', initial_status: 'ready' });
  const task = made.details.result.task.id;
  assert.equal(view(made).result.acknowledged, true);
  const again = await tool('kanban_create', { title, body, idempotency_key: 'native-large-card', initial_status: 'ready' });
  assert.equal(again.details.result.task.id, task);
  const comments = [];
  for (let i = 0; i < 12; i++) {
    const text = (`PUBLIC_SYNTHETIC_AUDIT_${i}:` + 'audit '.repeat(1250)).trimEnd();
    comments.push(text);
    const result = await tool('kanban_comment', { task_id: task, comment: text });
    const acknowledgement = view(result);
    assert.equal(acknowledgement.result.history_included, false);
    assert.equal(acknowledgement.result.acknowledged, true);
    assert.ok(!result.content[0].text.includes('PUBLIC_SYNTHETIC_AUDIT_'));
    assert.deepEqual(result.details.result.comments.map(item => item.body), comments);
  }
  const raw = rawAdapter({ action: 'show', task_id: task });
  const fullBytes = bytes(JSON.stringify(raw)); assert.ok(fullBytes > 77 * 1024, `Need >77KiB backend fixture, got ${fullBytes}`);
  const reply = await show(task), projected = view(reply), hash = projected.raw_reply_sha256;
  assert.deepEqual(reply.details, raw); assert.equal(hash, jsonHash(raw));
  assert.equal(rowHash(reply.details.result.task), rowHash(raw.result.task));
  assert.deepEqual(reply.details.result.comments.map(item => item.body), comments);
  writeJson(path.join(fixture, 'full-backend-reply.json'), raw);
  checks.push('actual-hermes-large-reply-over-77kib', 'default-native-model-content-at-most-12kib',
    'actual-provider-serializer-excludes-host-details', 'full-host-reply-task-hash-and-all-comments-unchanged',
    'bounded-mutation-acknowledgements', 'actual-create-idempotence');
  await textPages(task, {}, result => result.body, body, hash);
  await textPages(task, { comment_id: raw.result.comments[0].id }, result => result.comment.body, comments[0], hash);
  await textPages(task, { task_field: 'body' }, result => result.field.value, JSON.stringify(body), hash);
  let before, ids = [];
  do {
    const result = view(await show(task, { expected_reply_sha256: hash, ...(before === undefined ? {} : { before_id: before }) })).result;
    ids.push(...result.comments.map(item => item.id)); before = result.comment_page.next_before_id;
  } while (before !== null);
  assert.deepEqual(ids, raw.result.comments.map(item => item.id).sort((a, b) => b - a));
  checks.push('unicode-body-pages-reconstruct-exactly', 'selected-comment-pages-reconstruct-exactly',
    'top-level-json-field-pages-reconstruct-exactly', 'comment-id-pages-recover-complete-history-once');
  await tool('kanban_comment', { task_id: task, comment: 'Public synthetic mutation invalidates a prior snapshot cursor.' });
  const stale = view(await show(task, { expected_reply_sha256: hash }));
  assert.equal(stale.result.stale_cursor, true); assert.notEqual(stale.raw_reply_sha256, hash);
  checks.push('stale-show-snapshot-refused');
  const dependantIds = [];
  for (let i = 0; i < 21; i++) {
    const result = await tool('kanban_create', { title: `Synthetic dependant ${i}`, parents: [task], body: 'Only fixture dependency metadata.' });
    dependantIds.push(result.details.result.task.id);
  }
  const relationsRaw = rawAdapter({ action: 'show', task_id: task });
  let relationOffset = 0, dependantPages = [], prerequisitePages = [];
  do {
    const page = view(await show(task, { relation_offset: relationOffset, expected_reply_sha256: jsonHash(relationsRaw) })).result;
    dependantPages.push(...page.dependent_tasks.ids); prerequisitePages.push(...page.prerequisites.ids);
    assert.match(page.relation_semantics, /not decomposition containment/);
    relationOffset = page.dependent_tasks.next_offset;
  } while (relationOffset !== null);
  assert.deepEqual(dependantPages, relationsRaw.result.children); assert.equal(dependantPages.length, 21);
  assert.deepEqual(prerequisitePages, relationsRaw.result.parents);
  const rootMade = await tool('kanban_create', { title: 'Synthetic hierarchy root', body: 'Retain decomposition containment.', initial_status: 'triage' });
  const root = rootMade.details.result.task.id;
  const childSpecs = Array.from({ length: 12 }, (_, i) => ({ title: `Level one ${i} ` + '界'.repeat(150),
    body: 'Synthetic hierarchy only.', ...(i === 0 ? { expandable: true } : {}), ...(i === 1 ? { parents: [0] } : {}) }));
  const decomposed = await tool('kanban_decompose', { task_id: root, children: childSpecs });
  const firstChild = decomposed.details.result.root.children[0].id;
  await tool('kanban_decompose', { task_id: firstChild, children: Array.from({ length: 12 }, (_, i) => ({
    title: `Level two ${i} ` + '界'.repeat(150), body: 'Synthetic nested leaf.' })) });
  const hierarchyRaw = rawAdapter({ action: 'hierarchy', task_id: root, depth: 12 });
  const flatten = node => [node, ...node.children.flatMap(flatten)];
  const expectedNodes = flatten(hierarchyRaw.result.root);
  let hierarchyOffset = 0, nodes = [], hierarchyPageCount = 0;
  do {
    const result = view(await tool('kanban_hierarchy', { task_id: root, depth: 12,
      view: { hierarchy_offset: hierarchyOffset, expected_reply_sha256: jsonHash(hierarchyRaw) } })).result;
    assert.equal(result.backend_truncated, false); assert.match(result.relation_semantics, /containment/);
    nodes.push(...result.nodes); hierarchyOffset = result.next_offset; hierarchyPageCount++;
  } while (hierarchyOffset !== null);
  assert.ok(hierarchyPageCount > 1, 'Synthetic hierarchy must exercise view pagination');
  assert.deepEqual(nodes.map(node => node.id), expectedNodes.map(node => node.id));
  for (let i = 0; i < nodes.length; i++) {
    assert.deepEqual(nodes[i].prerequisites.ids, expectedNodes[i].prerequisites);
    assert.deepEqual(nodes[i].child_ids.ids, expectedNodes[i].child_ids);
  }
  const depthLimited = view(await tool('kanban_hierarchy', { task_id: root, depth: 1 }));
  assert.equal(depthLimited.result.backend_truncated, true);
  checks.push('show-prerequisite-and-dependant-relation-pages', 'actual-hierarchy-pages-preserve-node-and-edge-identity',
    'backend-hierarchy-truncation-distinct-from-view-pagination');
  await tool('kanban_select', { task_id: task });
  const listRaw = rawAdapter({ action: 'list', limit: 100 });
  let listOffset = 0, listed = [], listPageCount = 0;
  do {
    const result = view(await tool('kanban_list', { limit: 100, view: { items_offset: listOffset, items_limit: 7,
      expected_reply_sha256: jsonHash(listRaw) } })).result;
    assert.equal(result.selected.id, task); listed.push(...result.tasks.map(item => item.id));
    listOffset = result.next_offset; listPageCount++;
  } while (listOffset !== null);
  assert.ok(listPageCount > 1); assert.deepEqual(listed, listRaw.result.tasks.map(item => item.id));
  checks.push('hash-pinned-list-pages-recover-all-backend-task-ids');
  const read = await tool('read', { path: path.join(project, 'AGENTS.md') });
  assert.equal(read.content[0].text, agentsText);
  const context = await tool('project_context', { path: project });
  assert.equal(context.details.ok, true); assert.ok(!context.content[0].text.includes('bounded_summary'));
  await session.extensionRunner.emitContext([structuredClone(lastMessage)]);
  checks.push('native-read-and-project-context-raw-delivery-unchanged');
  const ownerText = 'Complete only the synthetic retained native reply task. This is queue completion, not root-outcome acceptance.';
  await session.extensionRunner.emitInput(ownerText, undefined, 'interactive');
  const pending = (await tool('kanban_intake_status', {})).details.result.pending;
  const routeInput = { source_id: pending.at(-1).id, parts: [{ kind: 'task', summary: ownerText, execute: true }] };
  const routed = await tool('kanban_intake_route', routeInput);
  const retainedTask = routed.details.result.bound[0].task_id;
  assert.equal((await tool('kanban_intake_route', routeInput)).details.result.replay, true);
  await tool('kanban_select', { task_id: retainedTask });
  const completed = await tool('kanban_move', { task_id: retainedTask, transition: 'complete', summary: 'Exact synthetic queue scope is finished.' });
  assert.equal(view(completed).result.history_included, false);
  assert.equal(completed.details.result.task.status, 'done');
  const completedRaw = rawAdapter({ action: 'show', task_id: retainedTask });
  assert.deepEqual(completed.details.result.task, completedRaw.result.task);
  const { createJiti } = require('jiti');
  const jiti = createJiti(path.join(piPackage, 'package.json'));
  const { nativeCompletionOrder } = await jiti.import(path.join(runtime, 'adapters/pi/intake/retained-packet-138.ts'));
  const witness = nativeCompletionOrder(sessionManager.getBranch()).get(retainedTask);
  assert.ok(witness); assert.equal(witness.row_sha256, rowHash(completedRaw.result.task));
  checks.push('source-bound-intake-routing-remains-idempotent', 'native-terminal-completion-witness-keeps-full-task-row-hash');
  if (frameworkBinding) {
    const checkpoint = await tool('kanban_work_checkpoint', { disposition: 'complete', reason: 'Exact synthetic retained leaf completed; no root acceptance claim.' });
    assert.equal(checkpoint.details.result.mode, 'complete');
    const decision = sessionManager.getBranch().filter(entry => entry.type === 'custom' && entry.customType === 'pi-work-decision/v1').at(-1);
    assert.equal(decision.data.decision, 'queue_complete'); assert.equal(decision.data.authority, 'retained_queue_only_not_root_acceptance');
    checks.push('actual-framework-retained-queue-completion-preserves-authority-boundary');
  }
  assert.deepEqual(errors, []); assert.equal(session.pendingMessageCount, 0);
  const defaultMetric = metrics.find(item => item.name === 'kanban_show');
  const receipt = { status: 'passed', fixture, checks, pi_version: JSON.parse(fs.readFileSync(path.join(piPackage, 'package.json'))).version,
    source_manifest_sha256: digest(path.join(fixture, 'source-manifest.json')), native_probe_sha256: digest(new URL(import.meta.url)),
    projector_sha256: digest(projector), coordinator_sha256: digest(path.join(workflow, 'pi-kanban.ts')),
    provider_serializer_sha256: digest(providerFile), full_backend_reply_bytes: fullBytes,
    default_model_content_bytes: defaultMetric.content_bytes, default_serialized_native_tool_bytes: defaultMetric.serialized_tool_bytes,
    default_matched_comparison: defaultMetric.matched_comparison,
    sdk_convert_to_llm_sha256: digest(path.join(piPackage, 'dist/core/messages.js')),
    comparison_model: model, comparison_provider_options: {},
    default_host_details_bytes: defaultMetric.details_bytes, full_task_row_sha256: rowHash(raw.result.task),
    full_reply_sha256: hash, completion_witness_row_sha256: witness.row_sha256,
    framework_native: Boolean(frameworkBinding), framework_binding_sha256: frameworkBinding ? digest(frameworkBinding) : null,
    model_calls: 0, remote_pushes: 0, elapsed_ms: Date.now() - started,
    limits: 'Actual native Pi, real fixture Hermes and actual provider serialization. Host details retain full data and backend 1MiB transport cap remains. No inference, live board, dispatcher, service or root-outcome acceptance. Tool-call journal entries are fixture-driven, not model-generated.' };
  writeJson(path.join(fixture, 'metrics.json'), metrics); writeJson(path.join(fixture, 'native-trace.json'), trace);
  writeJson(path.join(fixture, 'receipt.json'), receipt); console.log(JSON.stringify(receipt, null, 2));
} catch (error) {
  writeJson(path.join(fixture, 'native-trace.json'), trace);
  writeJson(path.join(fixture, 'failure.json'), { status: 'failed', fixture, checks, error: String(error?.stack || error),
    native_probe_sha256: digest(new URL(import.meta.url)), projector_sha256: digest(projector), elapsed_ms: Date.now() - started });
  console.error(JSON.stringify({ status: 'failed', fixture, failure_receipt: path.join(fixture, 'failure.json') }));
  throw error;
} finally {
  session.dispose();
}
