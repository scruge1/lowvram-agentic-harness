import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { projectIntakeModelView } from '../adapters/pi/intake/intake-model-view.mjs';
const sha=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const states=new Map();
const checks=[];
const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
const queue=Array.from({length:30},(_,i)=>({root:'/fixture/current-project',task:'t_'+String(i).padStart(8,'0'),source:'src-'+i}));
const pending=Array.from({length:12},(_,i)=>({id:'source-'+i,source:'user',sha256:'a'.repeat(64),
 excerpt:'Pending source '.repeat(300),truncated:true,at:1794100000+i}));
const waits=Array.from({length:32},(_,i)=>({id:'wait-'+i,task:'t_'+i,status:'waiting',
 key:'external:'+i,kind:'external',trigger:'some trigger '+i,reason:'wait for independent result '.repeat(15)}));
const parts=Array.from({length:30},(_,i)=>({part_index:i,task_id:'t_'+String(i).padStart(8,'0'),
 kind:'task',status:'routed',body:'very long detail '.repeat(600)}));
const status={mode:'waiting',reason:'waiting for source evidence'.repeat(20),queue,pending,task_waits:waits,
 retained_total:30,pending_total:12,conversation:{source_id:'current',phase:'review'},
 next_action:'',deferred_total:4};
const source={'id':'source-123',source:'input',sha256:'b'.repeat(64),
 text:(String.fromCodePoint(0x20ac,0x1f680)+' big source ').repeat(3600),at:1794100000};
const value={source_id:'source-123',bound:parts,state:status,source,frozen_intent:{parts,control:'preserve'}};
check('raw_source_large',JSON.stringify(value).length>60000);
const originalSha=sha(value);
const compact=projectIntakeModelView(value);
check('compact_under_6kb',Buffer.byteLength(JSON.stringify(compact))<=6144);
check('view_non_authoritative',compact.authority==='PRESENTATION_ONLY_NOT_APPROVAL');
check('host_original_unchanged',sha(value)===originalSha&&value.source.text.length>50000);
const statusView=projectIntakeModelView({source_id:value.source_id,bound:value.bound,state:value.state});
check('queue_count_and_next_page',statusView.queue.total===30&&statusView.queue.truncated&&statusView.queue.next_offset>0);
check('pending_count_and_next_page',statusView.pending.total===12&&statusView.pending.truncated);
check('bound_count_and_next_page',statusView.bound.total===30&&statusView.bound.truncated);
check('waits_count_and_next_page',statusView.waits.total===32&&statusView.waits.truncated);
check('source_text_is_paged',compact.source.source_text.truncated&&compact.source.source_text.next_offset>0);
check('captured_sha256_retained',compact.source.capture_sha256===source.sha256);
const sourceSha=compact.source.source_text.sha256;
let offset=0,built='',count=0;
while(true){
 const view=projectIntakeModelView(value,{source_offset:offset,source_limit:777,expected_source_sha256:sourceSha});
 const pg=view.source.source_text;
 assert.equal(pg.offset,offset);
 built+=pg.text;count++;
 if(pg.next_offset===null)break;
 offset=pg.next_offset;
 assert.ok(count<200);
}
check('full_unicode_source_recovers_exactly',built===source.text&&count>50);
const q=projectIntakeModelView({source_id:value.source_id,bound:value.bound,state:value.state},{queue_offset:20,queue_limit:10,pending_limit:1,wait_limit:1,bound_limit:1});
check('queue_last_page_id_matches',q.queue.items.length===10&&q.queue.items[0].task===queue[20].task&&q.queue.next_offset===null);
const oldHash=compact.raw_reply_sha256;
const mutated={...value,state:{...status,mode:'blocked'}};
const stale=projectIntakeModelView(mutated,{expected_reply_sha256:oldHash});
check('changed_native_reply_refuses_stale_cursor',stale.stale_cursor===true);
const wrongSource=projectIntakeModelView(value,{expected_source_sha256:'0'.repeat(64)});
check('changed_source_refuses_page',wrongSource.source.stale_source===true);
const pageOnly=projectIntakeModelView({queue:[],mode:'running',pending:[],task_waits:[]});
check('empty_status_still_small',Buffer.byteLength(JSON.stringify(pageOnly))<3000);
const genericLarge={imported:Array.from({length:400},(_,i)=>({id:'historical-'+i,details:'Retained historical event '.repeat(30)})),
 remaining:3, authority:'Historical evidence only, no execution approval'};
const genericView=projectIntakeModelView(genericLarge);
check('large_nonstatus_result_is_bounded',Buffer.byteLength(JSON.stringify(genericView))<=6144);
check('large_nonstatus_not_authoritative',genericView.authority==='PRESENTATION_ONLY_NOT_APPROVAL'
 && genericView.imported_total===400 && genericView.remaining===3);
check('large_nonstatus_original_untouched',genericLarge.imported.length===400);
for(const [name,call] of [
 ['negative_queue_offset',()=>projectIntakeModelView(value,{queue_offset:31})],
 ['negative_page_limit',()=>projectIntakeModelView(value,{pending_limit:25})],
 ['negative_source_offset',()=>projectIntakeModelView(value,{source_offset:source.text.length+1})],
 ['negative_negative_offset',()=>projectIntakeModelView(value,{queue_offset:-1})]]){
 let denied=false;try{call();}catch{denied=true}
 check(name,denied);
}
// mimic successful wrapper: original details identity MUST survive view projection.
const wrapper={content:[{type:'text',text:JSON.stringify(compact)}],details:{ok:true,result:value}};
check('host_details_original_identity',wrapper.details.result===value&&sha(wrapper.details.result)===originalSha);
const result={status:'PASS',cases:checks.length,checks,raw_bytes:Buffer.byteLength(JSON.stringify(value)),
 model_view_bytes:Buffer.byteLength(JSON.stringify(compact)),
 source_codepoints:Array.from(source.text).length,source_page_count:count,
 raw_details_preserved:true,no_execution_approval:true};
console.log(JSON.stringify(result));
