/** Actual installed coordinator/research tools and public network; no model. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(process.argv[i].startsWith('--') && process.argv[i + 1]);
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const key of ['home', 'project', 'receipt-dir']) assert.ok(options[key], `Missing --${key}`);
const home = fs.realpathSync(options.home), project = fs.realpathSync(options.project);
const destination = fs.realpathSync(options['receipt-dir']);
assert.equal(fs.realpathSync(process.env.AGENT_HOME), home);
assert.ok(project.startsWith(home + path.sep + 'projects' + path.sep), 'Use an owned qualification project');
const started = Date.now(), checks = [], trace = [];
const sha = value => createHash('sha256').update(value).digest('hex');
const read = name => JSON.parse(fs.readFileSync(path.join(home, name)));
const config = read('home.json');
assert.equal(config.profile, 'agent');
assert.deepEqual(Object.keys(config.installed).sort(), ['framework', 'hermes', 'mempalace', 'pi', 'research']);
const watched = ['home.json', 'agent/settings.json', 'agent/models.json', 'home-lifecycle.py', 'agent-home.py'];
const bindings = () => Object.fromEntries(watched.map(name => [name, sha(fs.readFileSync(path.join(home, name)))]));
const before = bindings();
process.env.PI_OFFLINE = '1'; process.env.PI_SKIP_VERSION_CHECK = '1';
const sdk = await import(pathToFileURL(path.join(home, 'packages/pi/node_modules/@earendil-works/pi-coding-agent/dist/index.js')));
const agentDir = path.join(home, 'agent');
const settings = sdk.SettingsManager.create(project, agentDir);
const loader = new sdk.DefaultResourceLoader({ cwd: project, agentDir, settingsManager: settings,
  noThemes: true, disabledBuiltinExtensions: ['mcp', 'codemode'] });
await loader.reload(); assert.deepEqual(loader.getExtensions().errors, []);
const credentials = { async read() {}, async list() { return []; }, async modify(_id, fn) { return fn(undefined); }, async delete() {} };
const store = new Map();
const modelsStore = { async read(id) { return store.get(id); }, async write(id, value) { store.set(id, value); }, async delete(id) { store.delete(id); } };
const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsStore, modelsPath: path.join(agentDir, 'models.json'),
  allowModelNetwork: false, refreshOnCreate: false });
const model = (await modelRuntime.getAvailable('local')).find(value => value.id === config.model);
assert.ok(model);
const sessionManager = sdk.SessionManager.inMemory(project);
const { session } = await sdk.createAgentSession({ cwd: project, agentDir, settingsManager: settings,
  resourceLoader: loader, sessionManager, modelRuntime, model, thinkingLevel: 'off' });
const errors = [];
await session.bindExtensions({ onError: value => errors.push(value) });
let sequence = 0;
async function invoke(name, input) {
  const item = session.extensionRunner.getAllRegisteredTools().find(value => value.definition.name === name);
  assert.ok(item, `Actual native registration missing: ${name}`);
  const began = Date.now();
  const output = await sdk.wrapRegisteredTool(item, session.extensionRunner).execute(
    `installed-research-${++sequence}`, input, new AbortController().signal);
  trace.push({ name, input, elapsed_ms: Date.now() - began, output });
  return output;
}
function bounded(output) {
  assert.ok(Buffer.byteLength(JSON.stringify(output.details)) <= 12 * 1024);
  assert.equal(output.details.authority, 'untrusted_source_evidence');
  assert.ok(!JSON.stringify(output.content).includes('raw_content_base64'));
  assert.ok(!JSON.stringify(output.content).includes('content_base64'));
}
try {
  const admitted = await invoke('project_admit', { project_root: project });
  assert.ok(!admitted.isError, JSON.stringify(admitted));
  const selection = sessionManager.getBranch().findLast(item => item.type === 'custom' && item.customType === 'pi-kanban-selection/v1');
  assert.equal(selection?.data?.project?.root, project);
  checks.push('actual-installed-coordinator-admission-and-native-selection');

  const search = await invoke('web_research', { action: 'search', query: 'Python unittest documentation', max_results: 3, timeout: 20 });
  bounded(search);
  if (!search.isError && search.details.ok) checks.push('actual-installed-duckduckgo-search');
  else checks.push('duckduckgo-search-not-accepted');

  const fetched = await invoke('web_research', { action: 'fetch', url: 'https://docs.python.org/3/library/unittest.html', timeout: 20 });
  bounded(fetched);
  assert.ok(!fetched.isError && fetched.details.ok, JSON.stringify(fetched));
  assert.equal(fetched.details.content_scope, 'full_extraction');
  checks.push('actual-installed-public-fetch-and-bounded-view');
  let text = fetched.details.text, offset = fetched.details.next_offset, pages = 0;
  while (offset !== null) {
    assert.ok(++pages <= 100, 'Unexpected static evidence window count');
    const page = await invoke('web_research', { action: 'read', artifact_id: fetched.details.artifact_id, offset, limit: 8192 });
    bounded(page); assert.ok(!page.isError && page.details.cached);
    assert.equal(page.details.source_status, fetched.details.source_status);
    assert.equal(page.details.window_sha256, sha(Buffer.from(page.details.text)));
    assert.ok(page.details.next_offset === null || page.details.next_offset > offset);
    text += page.details.text; offset = page.details.next_offset;
  }
  assert.equal(sha(Buffer.from(text)), fetched.details.text_sha256);
  assert.match(text, /unittest/i);
  const projectId = selection.data.project.projectId;
  const artifact = path.join(home, 'state/projects', projectId, 'research/artifacts', fetched.details.artifact_sha256 + '.json');
  const artifactBytes = fs.readFileSync(artifact);
  assert.equal(sha(artifactBytes), fetched.details.artifact_sha256);
  const source = JSON.parse(artifactBytes).payload.response;
  assert.equal(sha(Buffer.from(source.raw_content_base64, 'base64')), source.raw_content_sha256);
  assert.equal(source.cleaned_text_full, text);
  checks.push('full-static-evidence-preserved-and-recovered-with-cached-windows', 'host-raw-source-sha256-readback');

  const rendered = await invoke('web_research', { action: 'render', url: 'https://www.python-httpx.org' });
  bounded(rendered);
  assert.ok(!rendered.isError && rendered.details.ok, JSON.stringify(rendered));
  assert.equal(rendered.details.content_scope, 'captured_browser_window');
  assert.match(rendered.details.text, /HTTPX/);
  checks.push('actual-installed-chromium-public-render-with-capture-scope');
  const metadata = await invoke('web_research', { action: 'read', artifact_id: rendered.details.artifact_id, view: 'metadata' });
  bounded(metadata); assert.ok(!metadata.isError && metadata.details.cached);
  assert.ok(!metadata.details.text.includes('content_base64'));
  checks.push('installed-browser-provenance-cache-without-source-body-dump');
  assert.deepEqual(bindings(), before);
  assert.deepEqual(errors, []);
  assert.equal(session.pendingMessageCount, 0);
  checks.push('maintained-bindings-unchanged-and-no-model-prompt');
  const receipt = { status: search.isError || !search.details.ok ? 'PARTIAL_SEARCH_FAILED' : 'PASS',
    home, project, checks, elapsed_ms: Date.now() - started, model_calls: 0,
    native_extensions: loader.getExtensions().extensions.length,
    source_statuses: { search: search.details.source_status, fetch: fetched.details.source_status, render: rendered.details.source_status },
    static_chars: text.length, cached_pages: pages, installed_packages: Object.keys(config.installed),
    limitations: 'Scripted actual registered tool invocation after real coordinator admission, no model-driven research, general source corroboration or first-task acceptance. Browser scope is the captured window.' };
  fs.writeFileSync(path.join(destination, 'research-network-receipt.json'), JSON.stringify(receipt, null, 2) + '\n', { flag: 'wx' });
  console.log(JSON.stringify(receipt));
} finally {
  fs.writeFileSync(path.join(destination, 'research-network-trace.json'), JSON.stringify(trace, null, 2) + '\n', { flag: 'wx' });
  session.dispose();
}
