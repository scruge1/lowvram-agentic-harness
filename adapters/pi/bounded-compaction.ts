import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { compact } from '@earendil-works/pi-coding-agent';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { isAbsolute } from 'node:path';

type Selector = { provider: string; id: string; base_url: string };
const ENTRY = 'pi-compaction-policy/v1';
const MAX_SUMMARY_TOKENS = 8192;
const FOCUS = 'Produce a compact engineering handoff, at most 1500 words. Keep the current user goal, decisions, active files, exact error messages, unresolved blockers, pending verification, next action, and critical safety boundaries. Collapse completed chronology into short pointers. Do not copy the old summary verbatim or preserve obsolete active state. Full session history remains on disk; this summary is a working index, not the archive.';

function localEndpoint(value: string) {
  const url = new URL(value);
  const host = url.hostname.toLowerCase();
  const octets = host.split('.').map(Number);
  const ipv4 = octets.length === 4 && octets.every(n => Number.isInteger(n) && n >= 0 && n <= 255);
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(host)
    || ipv4 && (octets[0] === 10 || octets[0] === 127
      || octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31
      || octets[0] === 192 && octets[1] === 168
      || octets[0] === 100 && octets[1] >= 64 && octets[1] <= 127);
  if (!local || !['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
    throw new Error('Bounded compaction selectors require an exact local endpoint without credentials or query');
  return url.href.replace(/\/$/, '');
}

function validateSelectors(models: Selector[]): Selector[] {
  if (!Array.isArray(models) || !models.length || models.length > 64)
    throw new Error('Bounded compaction needs a bounded nonempty model selector list');
  const seen = new Set<string>();
  return models.map(model => {
    if (!model || JSON.stringify(Object.keys(model).sort()) !== JSON.stringify(['base_url', 'id', 'provider'])
        || ![model.id, model.provider].every(value => typeof value === 'string' && value.length > 0
          && value.length <= 256 && !/[\x00-\x1f\x7f]/.test(value)) || typeof model.base_url !== 'string')
      throw new Error('Invalid bounded compaction model selector');
    const selected = { provider: model.provider, id: model.id, base_url: localEndpoint(model.base_url) };
    const key = JSON.stringify(selected);
    if (seen.has(key)) throw new Error('Duplicate bounded compaction selector');
    seen.add(key);
    return selected;
  });
}

export function registerBoundedCompaction(pi: ExtensionAPI, models: Selector[]) {
  const selected = validateSelectors(models);
  let held = false;
  const applies = (ctx: any) => {
    const model = ctx.model;
    if (!model) return false;
    try {
      const endpoint = localEndpoint(model.baseUrl);
      return selected.some(item => item.provider === model.provider && item.id === model.id && item.base_url === endpoint);
    } catch { return false; }
  };
  const restore = (_event: any, ctx: any) => {
    const saved = [...ctx.sessionManager.getBranch()].reverse().find(
      (entry: any) => entry.type === 'custom' && entry.customType === ENTRY);
    held = saved?.data?.held === true;
  };
  pi.on('session_start', restore);
  pi.on('session_tree', restore);
  pi.on('session_before_compact', async (event: any, ctx: any) => {
    if (!applies(ctx)) return;
    if (held && event.reason !== 'manual') {
      ctx.ui?.notify?.('Automatic compaction is held after a failed summary. Run /compact to recover before continuing work.', 'warning');
      ctx.abort();
      return { cancel: true };
    }
    const stream = (model: any, context: any, options: any) =>
      ctx.modelRegistry.streamSimple(model, context, {
        ...options,
        maxTokens: Math.min(options?.maxTokens ?? model.maxTokens ?? MAX_SUMMARY_TOKENS, MAX_SUMMARY_TOKENS),
      });
    try {
      // Preserve native preparation, parser, length-stop rejection and commit.
      // Only this summary uses reasoning off; ordinary work is unchanged.
      const result = await compact(event.preparation, ctx.model, undefined, undefined,
        [FOCUS, event.customInstructions].filter(Boolean).join('\n'), event.signal,
        'off', stream, undefined, { enabled: false });
      return { compaction: result };
    } catch (error) {
      if (!event.signal.aborted) {
        held = true;
        pi.appendEntry(ENTRY, { held: true, error: String(error) });
        ctx.ui?.notify?.('Bounded compaction failed; automatic retries are held. Original history is intact. ' + String(error), 'error');
      }
      ctx.abort();
      return { cancel: true };
    }
  });
  pi.on('session_compact', (_event: any, ctx: any) => {
    if (!applies(ctx)) return;
    held = false;
    pi.appendEntry(ENTRY, { held: false, reasoning: 'off', target_words: 1500,
      max_summary_tokens: MAX_SUMMARY_TOKENS, provider: ctx.model.provider, model: ctx.model.id });
  });
  pi.on('session_compact_failed', (event: any, ctx: any) => {
    if (!applies(ctx) || event.aborted) return;
    held = true;
    pi.appendEntry(ENTRY, { held: true, error: event.errorMessage });
    ctx.ui?.notify?.('Compaction failed. Work is stopped and automatic retries are held; original history is intact. Repair then run /compact.', 'error');
    ctx.abort();
  });
}

export default function (pi: ExtensionAPI) {
  const filename = process.env.PI_BOUNDED_COMPACTION_CONFIG;
  const expected = process.env.PI_BOUNDED_COMPACTION_CONFIG_SHA256;
  if (!filename || !isAbsolute(filename) || !expected || !/^[a-f0-9]{64}$/.test(expected))
    throw new Error('Set PI_BOUNDED_COMPACTION_CONFIG and its SHA256 before loading bounded compaction');
  const raw = readFileSync(filename);
  if (raw.length > 64 * 1024 || createHash('sha256').update(raw).digest('hex') !== expected)
    throw new Error('Bounded compaction configuration byte drift');
  const config = JSON.parse(raw.toString('utf8'));
  if (!config || JSON.stringify(Object.keys(config).sort()) !== JSON.stringify(['models', 'schema'])
      || config.schema !== 'pi-bounded-compaction/v1') throw new Error('Invalid bounded compaction configuration');
  registerBoundedCompaction(pi, config.models);
}
