import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {projectKanbanReply as project} from '../adapters/pi/project-workflow/kanban-reply-projector.mjs';
// Contract fixtures retained for reviewed source generation a956e2bb98ce1731.
const digest=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const length=v=>Buffer.byteLength(JSON.stringify(v));
const tests=[];const test=(name,fn)=>tests.push([name,fn]);
const base=(action='show')=>({schema:'pi-kanban-result/v1',ok:true,action,result:{task:{id:'t_root',title:'Root',status:'running',body:'body',priority:1,completion_contract:'CONFIDENTIAL CONTRACT'},parents:['t_prereq'],children:['t_dependent'],comments:[]},limits:['No acceptance authority.']});
const freeze=x=>{if(x&&typeof x==='object'){Object.freeze(x);for(const v of Object.values(x))freeze(v);}return x;};
test('pure projection leaves complete host details and unrelated fields unchanged',()=>{
 const raw=freeze(base());const before=JSON.stringify(raw);const reply={content:[{text:JSON.stringify(project(raw))}],details:raw};
 assert.equal(reply.details,raw);assert.equal(JSON.stringify(raw),before);assert.equal(reply.details.result.task.completion_contract,'CONFIDENTIAL CONTRACT');assert.equal(project(raw).raw_reply_sha256,digest(raw));
});
test('unrelated actions return the exact object',()=>{const raw=base('knowledge_query');assert.equal(project(raw),raw);});
test('latest3 comments use stable numeric descending IDs and explicit metadata',()=>{
 const raw=base();raw.result.comments=[8,2,9,3,5].map(id=>({id,body:'comment'+id,author:'a',created_at:id}));const out=project(raw);assert.deepEqual(out.result.comments.map(x=>x.id),[9,8,5]);assert.equal(out.result.comment_page.next_before_id,5);assert.equal(out.result.comment_page.total,5);
});
test('tiny and large histories recover every comment ID exactly once',()=>{
 for(const count of [0,1,2,3,4,347]){const raw=base();raw.result.comments=Array.from({length:count},(_,i)=>({id:i+1,body:'audit'.repeat(1000),author:'a'}));let before,seen=[];
 do{const out=project(raw,{before_id:before});assert.ok(length(out)<=12288);seen.push(...out.result.comments.map(c=>c.id));before=out.result.comment_page.next_before_id??undefined;}while(before!==undefined);
 assert.deepEqual(seen,Array.from({length:count},(_,i)=>count-i));}
});
test('codepoint body paging reconstructs Unicode and exact hash',()=>{
 const raw=base();const text='😀é界\n'.repeat(1800);raw.result.task.body=text;let offset=0,seen='';
 while(true){const out=project(raw,{body_offset:offset});const p=out.result.body;assert.equal(p.offset_unit,'unicode_codepoints');assert.equal(p.sha256,createHash('sha256').update(text).digest('hex'));assert.ok(!p.text.includes('\uFFFD'));seen+=p.text;if(p.next_offset===null)break;assert.ok(p.next_offset>offset);offset=p.next_offset;}
 assert.equal(seen,text);
});
test('direct oversized comment paging reconstructs Unicode without unrelated history',()=>{
 const raw=base();const text='🎯漢字\u0000'.repeat(1500);raw.result.comments=[{id:41,body:text,author:'author'},{id:42,body:'SECRET UNRELATED BODY'}];let offset=0,seen='';
 while(true){const out=project(raw,{comment_id:41,offset});const p=out.result.comment.body;assert.equal(out.result.comment.id,41);assert.ok(!JSON.stringify(out).includes('SECRET UNRELATED'));seen+=p.text;if(p.next_offset===null)break;assert.ok(p.next_offset>offset);offset=p.next_offset;}
 assert.equal(seen,text);
});
test('100 long Unicode list titles page without losing IDs and retain selected task',()=>{
 const raw=base('list');raw.result={count:100,tasks:Array.from({length:100},(_,i)=>({id:'t_'+i,title:'😀'.repeat(200),status:'ready',body:'CONFIDENTIAL BODY'}))};let offset=0,ids=[];
 while(true){const out=project(raw,{items_offset:offset,items_limit:20,selected_task_id:'t_99'});assert.ok(length(out)<=12288);assert.equal(out.result.selected.id,'t_99');assert.ok(!JSON.stringify(out).includes('CONFIDENTIAL BODY'));ids.push(...out.result.tasks.map(x=>x.id));if(!out.result.has_more)break;assert.ok(out.result.next_offset>offset);offset=out.result.next_offset;}
 assert.deepEqual(ids,raw.result.tasks.map(t=>t.id));
});
test('list paging detects raw snapshot drift',()=>{const raw=base('list');raw.result={count:1,tasks:[{id:'t_1'}]};const old=project(raw).raw_reply_sha256;raw.result.tasks.push({id:'t_2'});assert.equal(project(raw,{expected_reply_sha256:old}).result.stale_cursor,true);});
test('mutations expose acknowledgement and comment ref without private historic content',()=>{
 for(const action of ['comment','move','create']){const raw=base(action);raw.result.task.body='SECRET TASK';raw.result.comments=[{id:1,body:'SECRET OLD'},{id:2,body:'SECRET NEW'}];const out=project(raw);assert.equal(out.result.last_comment_ref.id,2);assert.equal(out.result.acknowledged,true);assert.ok(!JSON.stringify(out).includes('SECRET'));assert.equal(out.result.history_included,false);}
});
test('prerequisites and containment remain different even on budget-truncated hierarchy',()=>{
 const raw=base('hierarchy');raw.result={root:{id:'root',title:'root',status:'todo',prerequisites:['outside'],child_ids:['child'],children:[{id:'child',title:'child',status:'ready',prerequisites:['other'],child_ids:[],children:[]}]},truncated:true,nodes_returned:2};const out=project(raw);assert.deepEqual(out.result.nodes[0].prerequisites.ids,['outside']);assert.deepEqual(out.result.nodes[0].child_ids.ids,['child']);assert.equal(out.result.backend_truncated,true);assert.match(out.result.relation_semantics,/containment/);
});
test('large hierarchy pages preserve all node IDs',()=>{
 const raw=base('decompose');raw.result={root:{id:'r',title:'root',child_ids:Array.from({length:100},(_,i)=>'c'+i),prerequisites:[],children:Array.from({length:100},(_,i)=>({id:'c'+i,title:'界'.repeat(200),prerequisites:['p'],child_ids:[],children:[]}))},nodes_returned:101,truncated:false};let offset=0,ids=[];
 while(true){const out=project(raw,{hierarchy_offset:offset});assert.ok(length(out)<=12288);ids.push(...out.result.nodes.map(n=>n.id));if(out.result.next_offset===null)break;assert.ok(out.result.next_offset>offset);offset=out.result.next_offset;}
 assert.deepEqual(ids,['r',...Array.from({length:100},(_,i)=>'c'+i)]);
});
test('relation offsets preserve exact IDs despite unequal array lengths',()=>{const raw=base();raw.result.parents=Array.from({length:45},(_,i)=>'p'+i);const out=project(raw,{relation_offset:20});assert.deepEqual(out.result.prerequisites.ids,raw.result.parents.slice(20,40));assert.deepEqual(out.result.dependent_tasks.ids,[]);assert.equal(out.result.prerequisites.next_offset,40);});
test('oversized fallback never leaks full raw output or exceeds byte cap',()=>{const raw=base();raw.schema='SECRET'.repeat(50000);raw.result.task.status='PRIVATE'.repeat(40000);const out=project(raw);assert.ok(length(out)<=12288);assert.equal(out.truncated,true);assert.ok(!JSON.stringify(out).includes('SECRET'));assert.ok(!JSON.stringify(out).includes('PRIVATE'));});
test('failed backend never receives success acknowledgement',()=>{const raw=base('move');raw.ok=false;raw.error='failure';const out=project(raw);assert.equal(out.ok,false);assert.equal(out.result.acknowledged,undefined);assert.equal(out.result.error.text,'failure');});
test('invalid cursor and duplicate comment IDs rejected explicitly',()=>{const raw=base();assert.throws(()=>project(raw,{body_offset:-1}));raw.result.comments=[{id:1},{id:1}];assert.throws(()=>project(raw),/unique stable/);});
test('fallback respects small cap and rejects unrelated unbounded cursor values',()=>{const raw=base();raw.result.task.status='private'.repeat(40000);assert.ok(length(project(raw,{max_bytes:1024}))<=1024);assert.throws(()=>project(raw,{hierarchy_offset:'SECRET'.repeat(10000)}),/safe integers/);});
test('top-level omitted JSON task fields reconstruct through Unicode codepoint pages',()=>{
 const raw=base();raw.result.task.result={content:'😀漢字\n'.repeat(1800),nested:{allowed:true}};let offset=0,seen='';
 while(true){const out=project(raw,{task_field:'result',offset});assert.ok(length(out)<=12288);assert.equal(out.result.field.source_type,'object');const page=out.result.field.value;seen+=page.text;if(page.next_offset===null)break;assert.ok(page.next_offset>offset);offset=page.next_offset;}
 assert.deepEqual(JSON.parse(seen),raw.result.task.result);
 for(const name of ['title','last_failure_error','completion_contract']){raw.result.task[name]='😀 value';const out=project(raw,{task_field:name});assert.equal(JSON.parse(out.result.field.value.text),'😀 value');}
});
test('field-only reads omit unrelated task body, comments and oversized metadata',()=>{
 const raw=base();raw.result.task.status='unrelated status '.repeat(5000);raw.result.task.body='UNRELATED BODY '.repeat(10000);
 raw.result.comments=[{id:1,body:'UNRELATED COMMENT '.repeat(10000)}];
 const out=project(freeze(raw),{task_field:'completion_contract'});
 assert.equal(out.result.task_id,'t_root');assert.equal(out.result.field_view_only,true);
 assert.equal(JSON.parse(out.result.field.value.text),'CONFIDENTIAL CONTRACT');
 assert.ok(!JSON.stringify(out).includes('UNRELATED'));assert.ok(length(out)<=12288);
});
test('large mutation acknowledgements keep complete immutable host task and comment history',()=>{
 for(const action of ['comment','move','create']){
  const raw=base(action);raw.result.task.result={payload:'retained output '.repeat(20000)};
  raw.result.comments=Array.from({length:1000},(_,i)=>({id:i+1,body:'retained historical comment '.repeat(100)}));
  const original=JSON.stringify(raw),taskHash=digest(raw.result.task);freeze(raw);
  const reply={content:[{type:'text',text:JSON.stringify(project(raw))}],details:raw};
  assert.equal(reply.details,raw);assert.equal(JSON.stringify(raw),original);assert.equal(digest(reply.details.result.task),taskHash);
  assert.equal(reply.details.result.comments.length,1000);assert.ok(Buffer.byteLength(reply.content[0].text)<=12288);
  assert.equal(JSON.parse(reply.content[0].text).result.history_included,false);
 }
});
test('cursor bounds reject invalid safe integers and missing comments are explicit',()=>{
 const raw=base();
 for(const name of ['before_id','comment_id','offset','body_offset','items_offset','list_offset','items_limit','hierarchy_offset','relation_offset'])
  for(const value of [-1,0.5,Number.MAX_SAFE_INTEGER+1,NaN,Infinity,'1',null])assert.throws(()=>project(raw,{[name]:value}),/safe integers/);
 assert.throws(()=>project(raw,{body_offset:1000}),/exceeds codepoint length/);
 assert.equal(project(raw,{comment_id:999}).result.comment.not_found,true);
 const failed=base('move');failed.ok=false;failed.error='unavailable '.repeat(10000);
 assert.equal(project(failed).result.acknowledged,undefined);assert.ok(length(project(failed))<=12288);
});
test('task_field uses own top-level properties only without path or prototype traversal',()=>{
 const raw=base();raw.result.task.result={private:'retained'};
 for(const name of ['missing','result.private','__proto__','constructor','toString']){const out=project(raw,{task_field:name});assert.equal(out.result.field.not_found,true);}
 raw.result.task.null_field=null;assert.equal(project(raw,{task_field:'null_field'}).result.field.source_type,'null');
 assert.throws(()=>project(raw,{task_field:42}),/top-level/);
});
let failures=0;const results=[];
for(const[name,fn]of tests){try{fn();results.push({name,passed:true});console.log('PASS '+name);}catch(e){failures++;results.push({name,passed:false,error:String(e.stack)});console.error('FAIL '+name+' '+e.stack);}}
const source=fileURLToPath(new URL('../adapters/pi/project-workflow/kanban-reply-projector.mjs',import.meta.url));const raw=readFileSync(source);const receipt={tests:results,passed:results.length-failures,failed:failures,node:process.version,source:{path:source,bytes:raw.length,sha256:createHash('sha256').update(raw).digest('hex')},scope:'Synthetic CPU fixtures only. No backend, board, live wrapper or agent changes. Bound applies to projected model reply, not backend transport/host details.'};
console.log(JSON.stringify(receipt));process.exitCode=failures?1:0;
