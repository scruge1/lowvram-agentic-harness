import { createHash } from 'node:crypto';

// Presentation-only projector. The original native intake object must be
// retained unchanged in tool details by the caller. This grants no authority.
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const bytes=v=>Buffer.byteLength(JSON.stringify(v));
const isObj=v=>v!==null && typeof v==='object' && !Array.isArray(v);
const validInt=(v,d=0)=>{
 if(v===undefined)return d;
 if(!Number.isSafeInteger(v)||v<0)throw Error('Invalid paging integer');
 return v;
};
const cp=v=>Array.from(String(v??''));
const clipped=(v,n=160)=>cp(v).slice(0,n).join('');
function textPage(v,offset=0,limit=1024) {
 offset=validInt(offset);limit=validInt(limit);
 if(limit<1||limit>4096)throw Error('Invalid source page limit');
 const points=cp(v);
 if(offset>points.length)throw Error('Source offset exceeds length');
 const end=Math.min(points.length,offset+limit);
 return {text:points.slice(offset,end).join(''),offset,total_codepoints:points.length,
   sha256:createHash('sha256').update(String(v??'')).digest('hex'),
   next_offset:end<points.length?end:null,truncated:end<points.length,
   offset_unit:'unicode_codepoints'};
}
function items(v,offset,limit,transform) {
 const data=Array.isArray(v)?v:[];
 offset=validInt(offset);limit=validInt(limit);
 if(limit<1||limit>20)throw Error('Page limit out of range 1..20');
 if(offset>data.length)throw Error('Page offset exceeds length');
 const end=Math.min(data.length,offset+limit);
 return {items:data.slice(offset,end).map((x,n)=>transform(x,n+offset)),offset,
   total:data.length,next_offset:end<data.length?end:null,truncated:end<data.length};
}
const toWork=x=>({root:clipped(x?.root),task:clipped(x?.task),source:clipped(x?.source)});
const toPending=x=>({id:clipped(x?.id),source:clipped(x?.source),
 sha256:x?.sha256??null,excerpt:clipped(x?.excerpt,180),
 truncated:Boolean(x?.truncated)||cp(x?.excerpt).length>180});
const toWait=x=>({id:clipped(x?.id),task:clipped(x?.task),status:x?.status??null,
 key:clipped(x?.key),kind:x?.kind??null,trigger:clipped(x?.trigger,160),
 reason:clipped(x?.reason,180)});
const toBound=(x,i)=>({index:i,part_index:x?.part_index??i,task_id:x?.task_id??null,
 status:x?.status??null,kind:x?.kind??null,created:x?.created??null,reused:x?.reused??null});
export function projectIntakeModelView(value,opts={}) {
 if(!isObj(value))return value;
 const state=isObj(value.state)?value.state:value;
 if(!isObj(state)||!Array.isArray(state.queue)||typeof state.mode!=='string'){
  // The native intake tool also returns small reconciliation and replay
  // receipts without a queue. Never expand a large non-status payload into
  // the model context; full exact bytes remain accessible in tool details.
  if(bytes(value)<=3072 && Object.keys(opts).length===0)return value;
  return {schema:'pi-intake-model-view/v1',view:'NON_STATUS_BOUNDED',
   raw_reply_sha256:hash(value),authority:'PRESENTATION_ONLY_NOT_APPROVAL',
   source_id:value.source_id??null,
   imported_total:Array.isArray(value.imported)?value.imported.length:null,
   remaining:value.remaining??null,replay:value.replay===true,
   original_in_host_details:true,
   recovery:'Full native result retained in tool details; inspect exact source with kanban_intake_status. Never repeat a mutation to recover its display.'};
 }
 for(const [key,values] of [
  ['queue',state.queue],['pending',state.pending],['wait',state.task_waits],['bound',value.bound]]) {
  const size=Array.isArray(values)?values.length:0;
  const offset=validInt(opts[key+'_offset']);
  const limit=validInt(opts[key+'_limit'],8);
  if(offset>size||limit<1||limit>20)throw Error('Invalid '+key+' page');
 }
 // Keep existing small replies byte-for-byte unchanged, unless a pinned page was requested.
 if(bytes(value)<=3072 && Object.keys(opts).length===0)return value;
 const digest=hash(value);
 const base={schema:'pi-intake-model-view/v1',view:'BOUNDED_SOURCE_PAGED',
   raw_reply_sha256:digest,source_id:value.source_id??value.source?.id??null,
   authority:'PRESENTATION_ONLY_NOT_APPROVAL',
   retrieval:'Use kanban_intake_status with pinned source_id, source_offset or queue_offset to recover omitted source/state. Native result remains unmodified in host tool details.',
   state:{mode:state.mode,reason:clipped(state.reason,650),
     next_action:clipped(state.next_action,420),wait_kind:state.wait?.kind??null,
     resume_trigger:clipped(state.wait?.trigger,400),
     selected_conversation:state.conversation??null,question_return:state.question_return??null,
     retained_total:state.retained_total??state.queue.length,
     pending_total:state.pending_total??(state.pending?.length??0),
     deferred_total:state.deferred_total??null},
   pagination:{source_offset:validInt(opts.source_offset),queue_offset:validInt(opts.queue_offset),
     pending_offset:validInt(opts.pending_offset),wait_offset:validInt(opts.wait_offset),
     bound_offset:validInt(opts.bound_offset)}};
 if(opts.expected_reply_sha256!==undefined&&opts.expected_reply_sha256!==digest)
   return {...base,stale_cursor:true,pages_invalid:true,
     error:'Live intake state changed. Restart paging; do not repeat native mutations.'};
 const render=(lim)=>{
  // An explicitly requested source page outranks incidental retained queue
  // presentation. Otherwise a 4KiB valid text page could be swallowed by a
  // 6KiB combined status fallback and become impossible to retrieve.
  const focusedSource=isObj(value.source);
  const view=focusedSource ? {...base,
    queue:{total:state.queue.length,fetch:'kanban_intake_status with no source_id'},
    pending:{total:state.pending?.length??0},
    waits:{total:state.task_waits?.length??0},
    bound:{total:value.bound?.length??0}} :
    {...base,queue:items(state.queue,opts.queue_offset,opts.queue_limit??lim.queue,toWork),
    pending:items(state.pending,opts.pending_offset,opts.pending_limit??lim.pending,toPending),
    waits:items(state.task_waits,opts.wait_offset,opts.wait_limit??lim.wait,toWait),
    bound:items(value.bound,opts.bound_offset,opts.bound_limit??lim.bound,toBound)};
  if(isObj(value.source)){
   const source=value.source;
   const paged=textPage(source.text,opts.source_offset,opts.source_limit??lim.source);
   if(opts.expected_source_sha256 && opts.expected_source_sha256!==paged.sha256) {
     view.source={id:source.id??null,stale_source:true,
       error:'Captured source has changed; restart source paging.'};
   } else {
     view.source={id:source.id??null,capture_sha256:source.sha256??null,
       source_text:paged,source:source.source??null,timestamp:source.at??null};
   }
   if(value.frozen_intent)view.frozen_intent={part_count:value.frozen_intent.parts?.length??0,
     control:value.frozen_intent.control??null,original_in_host_details:true};
  }
  if(value.wait_id)view.wait_id=value.wait_id;
  return view;
 };
 let out=render({queue:8,pending:4,wait:4,bound:16,source:2048});
 if(bytes(out)<=6144)return out;
 out=render({queue:4,pending:2,wait:2,bound:8,source:1024});
 if(bytes(out)<=6144)return out;
 return {...base,truncated:true,reason:'Model view exceeds 6KiB; retrieve a narrower exact page.',
   queue_total:state.queue.length,pending_total:state.pending?.length??0,
   bound_total:value.bound?.length??0,source_available:isObj(value.source)};
}
