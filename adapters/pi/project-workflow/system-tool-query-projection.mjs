import { createHash } from 'node:crypto';
const digest = (value) => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const bytes = (value) => Buffer.byteLength(JSON.stringify(value), 'utf8');
const clip = (value, max=200) => {
  const s=String(value ?? '');
  const chars=Array.from(s);
  return { text: chars.slice(0,max).join(''), truncated: chars.length>max,
    source_chars: chars.length, sha256: createHash('sha256').update(s).digest('hex') };
};
function integer(value,fallback) {
  if(value===undefined) return fallback;
  if(!Number.isSafeInteger(value) || value<0) throw new Error('Pagination must use nonnegative safe integers');
  return value;
}
export function projectToolQuery(value,options={}) {
  if(!value || value.ok!==true || !Array.isArray(value.results)) return value;
  const max=Math.min(6144,Math.max(2048,integer(options.max_bytes,4096)));
  const offset=integer(options.items_offset,0),count=integer(options.items_limit,8);
  if(count<1 || count>20) throw new Error('items_limit must be 1..20');
  if(offset>value.results.length) throw new Error('offset exceeds returned population');
  const raw_reply_sha256=digest(value);
  const result={schema:value.schema,ok:true,authority:value.authority,
    view:'bounded_tool_research',query:clip(value.query,160),manifest_sha256:value.manifest_sha256,
    raw_reply_sha256,backend_result_count:value.results.length,
    offset,items_limit:count,results:[],next_offset:null,has_more:false,
    scope:'Catalogue evidence is historical retrieval, not API signature or best implementation verification.',
    recovery:'Use a narrowed terms query and read cited exact source path before implementation. Backend full data remains in tool details; no source is lost.'};
  if(options.expected_reply_sha256!==undefined && options.expected_reply_sha256!==raw_reply_sha256) {
    result.stale_cursor=true;
    result.recovery='Result bytes changed. Restart search/paging from offset 0, do not silently combine old and new results.';
    return result;
  }
  for(let idx=offset;idx<Math.min(value.results.length,offset+count);idx++) {
    const item=value.results[idx];
    const row={
      index:idx,kind:clip(item.kind,48).text,name:clip(item.name,110).text,
      lifecycle:clip(item.lifecycle,48).text,usable_for_planning:item.usable_for_planning===true,
      path:clip(item.path,260),source_file:clip(item.source_file,260),
      source_line:item.source_line,source_sha256:item.source_sha256,record_sha256:item.record_sha256,
      matched_term_count:item.matched_term_count,
      description:clip(item.description,150),
    };
    result.results.push(row);
    if(bytes(result)>max-380) {
      result.results.pop();
      result.next_offset=idx;
      result.has_more=true;
      break;
    }
  }
  if(result.next_offset===null && offset+result.results.length<value.results.length) {
    result.next_offset=offset+result.results.length;
    result.has_more=true;
  }
  if(bytes(result)>max) {
    result.results=[];
    result.next_offset=offset;
    result.has_more=offset<value.results.length;
    result.recovery='Source metadata itself exceeded page budget. Narrow the query; do not infer zero matches.';
  }
  return result;
}
