import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { projectToolQuery } from './system-tool-query-projection.mjs';

const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const rows = Array.from({ length: 80 }, (_, i) => ({
  kind: 'skill', name: 'portable-agent-capability-' + i,
  lifecycle: 'installed', usable_for_planning: i % 3 === 0,
  path: 'adapters/skills/test-' + i + '.md', source_file: 'skills/index-' + i,
  source_line: i + 1, source_sha256: 'a'.repeat(64), record_sha256: 'b'.repeat(63) + i % 10,
  matched_term_count: 4, description: 'A source-attributed test skill with bounded metadata '.repeat(5)
}));
const raw = { schema: 'system-tool-catalog/v1', ok: true, authority: 'retrieval_only',
  query: 'agentic coding', manifest_sha256: 'a'.repeat(64), results: rows };
const before = JSON.stringify(raw), sha = digest(raw);
const received = [];
let offset = 0, pages = 0;
do {
  const page = projectToolQuery(raw, { items_offset: offset, items_limit: 20, expected_reply_sha256: sha });
  assert.ok(Buffer.byteLength(JSON.stringify(page), 'utf8') <= 4096);
  assert.equal(page.raw_reply_sha256, sha);
  assert.equal(page.backend_result_count, 80);
  assert.equal(page.authority, 'retrieval_only');
  assert.equal(page.stale_cursor, undefined);
  assert.ok(page.results.length > 0, 'a valid page should make progress');
  received.push(...page.results);
  pages++;
  if (!page.has_more) break;
  assert.ok(Number.isSafeInteger(page.next_offset) && page.next_offset > offset);
  offset = page.next_offset;
  assert.ok(pages < 80, 'pagination must terminate');
} while (true);
assert.equal(received.length, rows.length);
assert.deepEqual(received.map(v => v.index), rows.map((_, i) => i));
assert.ok(received.every((v, i) => v.source_sha256 === rows[i].source_sha256));
assert.equal(JSON.stringify(raw), before, 'projection cannot mutate original data');
const stale = projectToolQuery(raw, { items_offset: 4, expected_reply_sha256: '0'.repeat(64) });
assert.equal(stale.stale_cursor, true);
assert.equal(stale.results.length, 0);
assert.ok(/restart/i.test(stale.recovery));
assert.throws(() => projectToolQuery(raw, { items_offset: 1000 }), /offset/i);
assert.throws(() => projectToolQuery(raw, { items_offset: -1 }), /nonnegative/i);
assert.throws(() => projectToolQuery(raw, { items_limit: 0 }), /1\.\.20/);
assert.deepEqual(projectToolQuery({ ok: false, error: 'refused' }), { ok: false, error: 'refused' });
assert.equal(projectToolQuery({ ...raw, results: [] }).backend_result_count, 0);
const src = readFileSync(new URL('./system-tool-query-projection.mjs', import.meta.url));
assert.equal(createHash('sha256').update(src).digest('hex'),
  '495fdcab0a1587241e149fb1aec22984abccfeea3b21efa28df051e2c760359a');
// Runtime extension wiring must keep full backend evidence and expose cursor pins.
const integration = readFileSync(new URL('./system-tool-knowledge.ts', import.meta.url), 'utf8');
for (const needle of ['projectToolQuery(value, options)', 'details: value',
                       'expected_reply_sha256', 'items_offset', 'items_limit',
                       'system_tool_query model projection source drift']) {
  assert.ok(integration.includes(needle), 'missing integration contract: ' + needle);
}
console.log(JSON.stringify({ result: 'PASS', tests: 'bounded_paging,sha_pin,lossless_backend,stale_refusal,error_preservation,source_pin,extension_wiring',
  result_count: received.length, pages,
  raw_bytes: Buffer.byteLength(before), first_page_bytes: Buffer.byteLength(JSON.stringify(projectToolQuery(raw))) }));
