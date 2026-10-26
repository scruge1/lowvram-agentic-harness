/** Bounded views of existing native child journal data. No writes or authority. */
import { createHash } from 'node:crypto';

export const CHILD_REPLY_BYTES = 12288;
export const childRecordDigest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const byteSize = value => Buffer.byteLength(JSON.stringify(value));
const marker = 'Untrusted child evidence only; no task acceptance, replay or execution permission.';
const relativeLocator = (root, value) => {
  if (typeof value !== 'string') return undefined;
  return value.startsWith(root + '/') || value.startsWith(root + '\\') ? value.slice(root.length + 1) : value;
};

export function childModelReply(result, record) {
  const final = result.messages.at(-1);
  const finalText = final.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
  const characters = Array.from(finalText);
  const all = result.calls.map(call => {
    const host = call.result?.details?.host;
    const row = { name: call.name, is_error: call.isError === true, omitted_fields: [] };
    for (const key of ['status', 'run_id', 'receipt', 'task_spec']) {
      const value = key === 'receipt' || key === 'task_spec' ? relativeLocator(record.project.root, host?.[key]) : host?.[key];
      if (typeof value !== 'string') continue;
      if (value.length > 1024) row.omitted_fields.push(key);
      else row[key] = value;
    }
    if (Array.isArray(call.input?.outputs)) {
      row.outputs = call.input.outputs.slice(0, 8).filter(value => typeof value === 'string' && value.length <= 1024);
      row.outputs_truncated = row.outputs.length !== call.input.outputs.length;
    }
    return row;
  });
  const usage = {};
  for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens']) {
    const values = result.messages.map(message => message.usage?.[key]);
    usage[key] = values.every(value => Number.isFinite(value) && value >= 0) ? values.reduce((sum, value) => sum + value, 0) : null;
  }
  let count = Math.min(20, all.length), end = Math.min(6000, characters.length);
  const view = () => ({ schema: 'pi-managed-child-summary/v1', ok: true,
    record: { call_id: record.id, child_session: record.child_session,
      custom_type: 'pi-managed-child-result/v1', sha256: childRecordDigest(record) },
    project: record.project, card: record.card, parent_card: record.parent_card,
    source: record.source, source_sha256: record.source_sha256, parent_session: record.parent_session,
    model_sha256: result.model_sha256,
    final_text: characters.slice(0, end).join(''), final_text_characters: characters.length,
    final_text_truncated: end !== characters.length,
    calls: all.slice(0, count), calls_total: all.length, calls_truncated: count !== all.length,
    native_reported_usage: usage,
    evidence_complete: false,
    inspect: { tool: 'task_agent_inspect', arguments: { call_id: record.id,
      record_sha256: childRecordDigest(record), offset: 0, max_bytes: CHILD_REPLY_BYTES } },
    inspect_note: 'Follow the supplied next arguments. Full native record remains in parent journal/details.',
    limits: marker });
  let reply = view();
  while (byteSize(reply) > CHILD_REPLY_BYTES && (count || end)) {
    if (count > 3) count--;
    else if (end > 0) end = Math.floor(end / 2);
    else count--;
    reply = view();
  }
  if (byteSize(reply) > CHILD_REPLY_BYTES) throw new Error('Child identity cannot fit12KiB; inspect retained native journal');
  return reply;
}

/** Current-branch data only; callers supply trusted current project/session. */
export function inspectChildRecord(branch, project, currentSession, params) {
  const allowed = new Set(['call_id', 'record_sha256', 'offset', 'max_bytes']);
  if (!params || Object.keys(params).some(key => !allowed.has(key))
      || typeof params.call_id !== 'string' || !params.call_id || params.call_id.length > 256
      || params.record_sha256 !== undefined && !/^[a-f0-9]{64}$/.test(params.record_sha256)
      || params.offset !== undefined && (!Number.isSafeInteger(params.offset) || params.offset < 0)
      || params.max_bytes !== undefined && (!Number.isInteger(params.max_bytes) || params.max_bytes < 1024 || params.max_bytes > CHILD_REPLY_BYTES))
    throw new Error('Invalid child inspection selector or bounds');
  if (params.offset !== undefined && !params.record_sha256) throw new Error('Bind paging to record_sha256 before supplying offset');
  if (!project || typeof currentSession !== 'string' || !currentSession) throw new Error('Admit the original project before child inspection');
  const rows = branch.filter(entry => entry.type === 'custom'
    && ['pi-managed-child-start/v1', 'pi-managed-child-result/v1'].includes(entry.customType)
    && entry.data?.id === params.call_id
    && entry.data.project?.root === project.root && entry.data.project?.projectId === project.projectId
    && entry.data.project?.boardId === project.boardId);
  const entry = params.record_sha256 ? rows.findLast(row => childRecordDigest(row.data) === params.record_sha256) : rows.at(-1);
  if (!entry) throw new Error('No matching child record in this native branch/project; preserve selector and inspect source');
  const source = branch.findLast(row => row.type === 'custom' && row.customType === 'pi-request-capture/v1'
    && row.data?.id === entry.data.source)?.data;
  const intent = branch.findLast(row => row.type === 'custom' && row.customType === 'pi-request-route-intent/v1'
    && row.data?.id === entry.data.source)?.data?.intent;
  if (typeof source?.text !== 'string' || source.sha256 !== entry.data.source_sha256
      || childRecordDigest(source.text) !== source.sha256 || intent?.project?.root !== project.root
      || intent?.project?.projectId !== project.projectId || intent?.project?.boardId !== project.boardId)
    throw new Error('Child record source is missing or changed in this native branch/project');
  const raw = JSON.stringify(entry.data), bytes = Buffer.byteLength(raw);
  if (bytes > 300 * 1024 || typeof entry.data.parent_session !== 'string') throw new Error('Child record is malformed or exceeds its retained bound');
  const characters = Array.from(raw), offset = params.offset ?? 0;
  if (offset > characters.length) throw new Error('Child record offset exceeds its exact length');
  const maximum = params.max_bytes ?? CHILD_REPLY_BYTES;
  const digest = childRecordDigest(entry.data);
  const envelope = end => ({ schema: 'pi-managed-child-inspection/v1', record: {
    call_id: entry.data.id, custom_type: entry.customType, child_session: entry.data.child_session ?? null,
    sha256: digest, project: entry.data.project, card: entry.data.card,
    source: entry.data.source, source_sha256: entry.data.source_sha256,
    origin_parent_session: entry.data.parent_session, current_parent_session: currentSession,
    historical_session: entry.data.parent_session !== currentSession,
    historical_data: true, latest_record_for_call: entry === rows.at(-1) },
    offset, end_offset: end, total_characters: characters.length, total_bytes: bytes,
    next_offset: end < characters.length ? end : null,
    next: end < characters.length ? { tool: 'task_agent_inspect', arguments: {
      call_id: entry.data.id, record_sha256: digest, offset: end, max_bytes: maximum } } : null,
    data: characters.slice(offset, end).join(''),
    window_sha256: createHash('sha256').update(characters.slice(offset, end).join('')).digest('hex'),
    complete_record: offset === 0 && end === characters.length,
    truncated: end < characters.length, scope: 'one_native_record_window_not_whole_history', limits: marker });
  if (!params.record_sha256) {
    const metadata = { ...envelope(0), data: '', next_offset: 0, complete_record: false, truncated: true,
      requires_record_sha256: true };
    if (byteSize(metadata) > maximum) throw new Error('Child inspection metadata exceeds max_bytes');
    return metadata;
  }
  // JSON escaping and UTF-8 widths both count toward the actual model envelope.
  // Offsets use Unicode code points; pages never split a surrogate/code point.
  let low = offset, high = Math.min(characters.length, offset + maximum);
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (byteSize(envelope(middle)) <= maximum) low = middle;
    else high = middle - 1;
  }
  const reply = envelope(low);
  if (byteSize(reply) > maximum || low === offset && offset < characters.length)
    throw new Error('Child inspection identity/window exceeds max_bytes');
  return reply;
}
