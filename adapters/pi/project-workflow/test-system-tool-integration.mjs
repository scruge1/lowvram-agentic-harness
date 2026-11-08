import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';
import { projectToolQuery } from './system-tool-query-projection.mjs';

const sha = value => createHash('sha256').update(value).digest('hex');
const directory = mkdtempSync(join(tmpdir(), 'pi-system-tool-fixture-'));
const source = new URL('./system-tool-knowledge.ts', import.meta.url);
const helper = join(directory, 'tool_helper.py');
const database = join(directory, 'tool.db');
writeFileSync(helper, '# synthetic source-bound backend, intentionally never executed\n');
writeFileSync(database, 'synthetic backend fixture\n');
process.env.PI_SYSTEM_TOOL_PYTHON = 'synthetic-python';
process.env.PI_SYSTEM_TOOL_HELPER = helper;
process.env.PI_SYSTEM_TOOL_DATABASE = database;
process.env.PI_SYSTEM_TOOL_HELPER_SHA256 = sha(readFileSync(helper));

const entries = Array.from({ length: 50 }, (_, index) => ({
  kind:'skill', name:'public-capability-' + index, lifecycle:'installed',
  usable_for_planning:true, path:'sample/source/' + index, source_file:'skills/' + index,
  source_line:index + 1, source_sha256:'b'.repeat(64), record_sha256: sha(String(index)),
  matched_term_count:1, description:'Verified, source-addressable capability '.repeat(4)
}));
const raw = { schema:'synthetic-rig-catalog/v1', ok:true, authority:'retrieval_only',
  query:'model', manifest_sha256:'a'.repeat(64), results:entries };
const rawHash = sha(JSON.stringify(raw));
const calls = [];
let malformedNext = false;
function spawn(_exe, argv, opts) {
  calls.push({argv,opts});
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = () => {};
  queueMicrotask(() => {
    child.stdout.emit('data', Buffer.from(JSON.stringify(malformedNext ? {ok:true, results:'invalid'} : raw)));
    malformedNext = false;
    child.emit('close', 0);
  });
  return child;
}
const Type = { Object:x=>x, String:()=>({}), Optional:x=>x, Integer:()=>({}) };
const values = {
  'typebox': { Type },
  'node:child_process': { spawn },
  'node:crypto': { createHash },
  'node:fs': { readFileSync },
  './system-tool-query-projection.mjs': { projectToolQuery },
};
const ctx = vm.createContext({ process, Buffer, URL, setTimeout, clearTimeout, console });
const mod = new vm.SourceTextModule(stripTypeScriptTypes(readFileSync(source, 'utf8')), {
  context:ctx, identifier:source.href, initializeImportMeta(meta) { meta.url=source.href; }
});
try {
  await mod.link(spec => {
    const obj = values[spec];
    assert.ok(obj, 'unexpected module dependency ' + spec);
    return new vm.SyntheticModule(Object.keys(obj), function () {
      for(const [name,value] of Object.entries(obj)) this.setExport(name,value);
    }, { context:ctx });
  });
  await mod.evaluate();
  const tools = {};
  mod.namespace.default({ registerTool(tool) { tools[tool.name] = tool; } });
  assert.deepEqual(Object.keys(tools).sort(), ['system_tool_query','system_tool_status']);
  const first = await tools.system_tool_query.execute('first',{terms:'model',limit:50,items_limit:20},undefined);
  assert.equal(first.isError, undefined);
  assert.equal(first.details.results.length, 50);
  const page = JSON.parse(first.content[0].text);
  assert.equal(page.view,'bounded_tool_research');
  assert.equal(page.raw_reply_sha256,rawHash);
  assert.ok(Buffer.byteLength(first.content[0].text) <= 4096);
  assert.ok(page.results.length > 0 && page.next_offset > 0);
  const second = await tools.system_tool_query.execute('next',{
    terms:'model',limit:50,items_limit:20,items_offset:page.next_offset,
    expected_reply_sha256:page.raw_reply_sha256
  },undefined);
  assert.equal(JSON.parse(second.content[0].text).stale_cursor,undefined);
  assert.equal(second.details.results.length,50);
  const stale = await tools.system_tool_query.execute('stale',{
    terms:'model',limit:50,items_offset:5,expected_reply_sha256:'0'.repeat(64)
  },undefined);
  assert.equal(JSON.parse(stale.content[0].text).stale_cursor,true);
  assert.equal(stale.details.results.length,50);
  assert.equal(calls.length,3);
  malformedNext = true;
  const malformed = await tools.system_tool_query.execute('invalid',{terms:'model',limit:5},undefined);
  assert.equal(malformed.isError,true,'malformed backend output cannot become full model-visible JSON');
  assert.match(malformed.content[0].text,/malformed/);
  assert.equal(calls.length,4);
  assert.ok(calls.every(c=>c.argv[0]==='-B' && c.opts.stdio[0]==='ignore'));
  writeFileSync(helper,'tampered fixture\n');
  const rejected = await tools.system_tool_query.execute('drift',{terms:'model',limit:5},undefined);
  assert.equal(rejected.isError,true);
  assert.match(rejected.content[0].text,/drift/);
  assert.equal(calls.length,4,'source drift must refuse before invoking backend');
  console.log(JSON.stringify({result:'PASS', checks:13, backend_rows:50,
    model_bytes:Buffer.byteLength(first.content[0].text),
    full_bytes:Buffer.byteLength(JSON.stringify(raw)), hash_bound:true,
    backend_preserved:true, stale_refused:true, helper_drift_refused:true, real_model_calls:0}));
} finally {
  rmSync(directory, {recursive:true, force:true});
}
