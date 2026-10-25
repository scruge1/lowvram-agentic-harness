import { createHash } from 'node:crypto';
const ACTIONS = new Set(['show','list','comment','move','create','decompose','hierarchy']);
const MAX = 12 * 1024;
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const bytes = value => Buffer.byteLength(JSON.stringify(value));
const integer = (value, fallback = 0) => value === undefined ? fallback : (() => {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error('Paging values must be nonnegative safe integers');
  return value;
})();
function textPage(value, offset = 0, limit = 2048) {
  const source = String(value ?? ''), points = Array.from(source); offset = integer(offset);
  if (offset > points.length) throw new Error('Text offset exceeds codepoint length');
  let low = 0, high = Math.min(points.length - offset, limit);
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (bytes(points.slice(offset,offset + mid).join('')) <= limit) low = mid; else high = mid - 1;
  }
  const end = offset + low;
  return { text: points.slice(offset,end).join(''), offset, total_codepoints: points.length,
    sha256: createHash('sha256').update(source).digest('hex'), truncated: end < points.length,
    next_offset: end < points.length ? end : null, offset_unit: 'unicode_codepoints' };
}
function summary(task) {
  return { id: task?.id ?? null, title: textPage(task?.title,0,1024).text, title_truncated:textPage(task?.title,0,1024).truncated, status: task?.status ?? null,
    priority: task?.priority ?? null };
}
function relationPage(values, offset) {
  const all = Array.isArray(values) ? values : []; offset = integer(offset);
  // Shared relation_offset may exceed the shorter of two relation arrays.
  return { ids: all.slice(offset,offset + 20), offset, total: all.length,
    next_offset: offset + 20 < all.length ? offset + 20 : null, truncated: offset + 20 < all.length };
}
function numericComments(comments) {
  const items = Array.isArray(comments) ? [...comments] : [];
  const ids = new Set();
  for (const item of items) {
    if (!Number.isSafeInteger(item.id) || item.id < 0 || ids.has(item.id)) throw new Error('Comments need unique stable numeric IDs');
    ids.add(item.id);
  }
  return items.sort((a,b) => b.id - a.id);
}
function omittedKeys(value, kept) { return Object.keys(value ?? {}).filter(key => !kept.includes(key)); }
/** Pure model view only. The wrapper MUST keep details === original value. */
export function projectKanbanReply(value, options = {}) {
  if (!value || !ACTIONS.has(value.action)) return value;
  for(const key of ['before_id','comment_id','offset','body_offset','items_offset','list_offset','items_limit','hierarchy_offset','relation_offset']) if(options[key]!==undefined) integer(options[key]);
  const rawHash = hash(value), max = Math.min(MAX,Math.max(1024,integer(options.max_bytes,MAX)));
  const out = { schema: value.schema === 'pi-kanban-result/v1' ? value.schema : 'unknown', ok: value.ok, action: value.action, view: 'bounded_summary',
    raw_reply_sha256: rawHash, provenance: 'Host details retain the unchanged backend reply; summary is not permission or acceptance.',
    omitted_reply_fields: omittedKeys(value,['schema','ok','action','result']), result: {} };
  const finish = () => {
    if (bytes(out) <= max) return out;
    // Never fall back to the complete raw result, even for an unexpected schema.
    return { schema: value.schema === 'pi-kanban-result/v1' ? value.schema : 'unknown', ok: value.ok, action: value.action, view: 'bounded_summary', raw_reply_sha256: rawHash,
      truncated: true, reason: 'Summary metadata exceeds byte budget; narrow the requested page.',
      retrieval: { task_id: textPage(value.result?.task?.id ?? value.result?.root?.id ?? '',0,192).text,
        body_offset: options.body_offset ?? 0, comment_id: options.comment_id ?? null, offset: options.offset ?? 0,
        items_offset: options.items_offset ?? options.list_offset ?? 0, hierarchy_offset: options.hierarchy_offset ?? 0 }, max_bytes: max };
  };
  if (options.expected_reply_sha256 !== undefined && options.expected_reply_sha256 !== rawHash) {
    out.result = { error: 'Raw reply changed; restart paging with the new hash.', stale_cursor: true }; return finish();
  }
  const r = value.result ?? {};
  if (value.ok !== true) {out.result={error:textPage(value.error ?? r.error ?? 'Backend operation failed',0,1024)};return finish();}
  if (value.action === 'show') {
    out.result = { task: summary(r.task), body: textPage(r.task?.body,options.body_offset,2048),
      prerequisites: relationPage(r.parents,options.relation_offset),
      dependent_tasks: relationPage(r.children,options.relation_offset),
      relation_semantics: 'show parents are prerequisite tasks; show children are dependants, not decomposition containment.',
      omitted_result_fields: omittedKeys(r,['task','parents','children','comments']),
      omitted_task_fields: omittedKeys(r.task,['id','title','status','priority','body']) };
    if(options.task_field !== undefined) {
      if(typeof options.task_field !== 'string' || options.task_field.length > 256) throw new Error('task_field must be a bounded top-level field name');
      const name=options.task_field, found=r.task != null && Object.hasOwn(r.task,name);
      const field=found ? r.task[name] : undefined;
      out.result={task_id:r.task?.id,field_view_only:true,field:found ? {name,source_type:field === null ? 'null' : Array.isArray(field) ? 'array' : typeof field,
        serialization:'JSON value, including quotes for strings',value:textPage(JSON.stringify(field) ?? 'null',options.offset,2048)} : {name,not_found:true}};
      return finish();
    }
    const comments = numericComments(r.comments);
    if (options.comment_id !== undefined) {
      const wanted = integer(options.comment_id), item = comments.find(c => c.id === wanted);
      out.result.comment = item ? { id: item.id, author: textPage(item.author,0,100).text,
        created_at: item.created_at, body: textPage(item.body,options.offset,1024) } : { id: wanted, not_found: true };
      out.result.comment_count = comments.length;
    } else {
      const before = options.before_id === undefined ? Infinity : integer(options.before_id);
      const eligible = comments.filter(c => c.id < before), page = eligible.slice(0,3);
      out.result.comments = page.map(c => ({ id: c.id, author: textPage(c.author,0,100).text,
        created_at: c.created_at, body: textPage(c.body,0,1024) }));
      out.result.comment_page = { total: comments.length, eligible: eligible.length, returned: page.length,
        order: 'numeric_id_desc', before_id: Number.isFinite(before) ? before : null,
        next_before_id: eligible.length > page.length ? page.at(-1).id : null, truncated: eligible.length > page.length };
    }
  } else if (value.action === 'list') {
    const tasks = Array.isArray(r.tasks) ? r.tasks : [], offset = integer(options.items_offset ?? options.list_offset), limit=integer(options.items_limit,20);
    if(limit<1 || limit>20) throw new Error('items_limit must be from 1 through 20');
    if (offset > tasks.length) throw new Error('List offset exceeds returned population');
    out.result = { tasks: [], backend_returned: tasks.length, backend_count: r.count, offset,
      next_offset: null, truncated: false, items_limit:limit, retrieval: 'Use kanban_show(task_id) for details. Offset applies to this hash-pinned backend list.',
      omitted_result_fields: omittedKeys(r,['tasks','count']) };
    for (let i=offset;i<Math.min(tasks.length,offset+limit);i++) {
      out.result.tasks.push(summary(tasks[i]));
      if (bytes(out) > max - 500) { out.result.tasks.pop();out.result.next_offset=i;out.result.truncated=true;break; }
    }
    if(out.result.next_offset === null && offset+out.result.tasks.length<tasks.length){out.result.next_offset=offset+out.result.tasks.length;out.result.truncated=true;}
    out.result.has_more=out.result.next_offset !== null;
    if (options.selected_task_id !== undefined) {
      const selected=tasks.find(t => t.id === options.selected_task_id);
      out.result.selected = selected ? summary(selected) : { id: options.selected_task_id, not_in_backend_result: true };
      out.result.selected_on_page = out.result.tasks.some(t => t.id === options.selected_task_id);
    }
  } else if (value.action === 'hierarchy' || value.action === 'decompose') {
    const nodes=[];
    const walk = node => { if (!node) return; nodes.push(node);for (const child of node.children ?? []) walk(child); };
    walk(r.root); const offset=integer(options.hierarchy_offset);
    if (offset>nodes.length) throw new Error('Hierarchy offset exceeds returned nodes');
    out.result = { root_id:r.root?.id, nodes:[], offset, returned_population:nodes.length,
      backend_truncated:r.truncated ?? null, backend_nodes_returned:r.nodes_returned ?? null,
      next_offset:null, truncated:false, relation_semantics:'prerequisites are dependency edges; child_ids are decomposition containment.',
      omitted_result_fields:omittedKeys(r,['root','truncated','nodes_returned']) };
    for(let i=offset;i<nodes.length;i++) {
      const n=nodes[i];out.result.nodes.push({...summary(n),prerequisites:relationPage(n.prerequisites,options.relation_offset),child_ids:relationPage(n.child_ids,options.relation_offset)});
      if(bytes(out)>max-100){out.result.nodes.pop();out.result.next_offset=i;out.result.truncated=true;break;}
    }
  } else {
    const comments=numericComments(r.comments), newest=comments[0];
    out.result = { acknowledged:true, task:summary(r.task),
      comment_ref_semantics:'Latest observed numeric comment ID; concurrent writes mean it is not proof this action created that comment.',
      last_comment_ref:newest ? {id:newest.id,created_at:newest.created_at,author:textPage(newest.author,0,100).text} : null,
      history_included:false, retrieval:'Use kanban_show(task_id); acknowledgement does not accept the root outcome.',
      omitted_result_fields:omittedKeys(r,['task']), omitted_task_fields:omittedKeys(r.task,['id','title','status','priority']) };
  }
  return finish();
}
