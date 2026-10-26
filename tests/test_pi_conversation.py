"""Conversation state controls on the complete module; native proof is separate."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "adapters/pi/intake/request-intake-138.ts"
SCRIPT = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { stripTypeScriptTypes } from 'node:module';
import { createHash, randomUUID } from 'node:crypto';
const [file, which] = process.argv.slice(1);
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
let decisions=0,onProjection,typed='',queued=false,editorError=false,crashAt;
const Type=new Proxy({},{get:()=>()=>({})});
const dependencies={typebox:{Type},'node:crypto':{createHash,randomUUID},
 './read-loop-079.ts':{registerReadLoopGuard:()=>({warning:()=>''})},
 './dependency-receipts-138.ts':{checkedReceipt:()=>{},inspectReceipt:()=>({verified:false}),watchReceipt:()=>()=>{},blockedTaskIds:()=>new Set()},
 './retained-packet-138.ts':{workKey:x=>x.root+'\0'+x.task,nativeCompletionOrder:()=>new Map(),cancelledSelection:async()=>false,
  buildRetainedPacket:async input=>{if(onProjection){const fn=onProjection;onProjection=undefined;await fn();}return {tasks:input.state.queue.map(x=>({id:x.task,source:x.source,status:'ready'})),anchors:[],excluded:[],coverage:{complete:true,truncated:false,missing:[]}};}},
 './decision-bridge-138.ts':{packetDigest:digest,decideRetainedWork:async packet=>{decisions++;return packet.tasks.length?{decision:'continue',selected:{task:packet.tasks[0].id,source:packet.tasks[0].source,action:'continue'}}:{decision:'queue_complete'};}}};
const context=vm.createContext({Buffer,process,console,structuredClone,setTimeout,clearTimeout});
const module=new vm.SourceTextModule(stripTypeScriptTypes(fs.readFileSync(file,'utf8')),{context});
await module.link(name=>{const values=dependencies[name];assert.ok(values,'Unexpected dependency '+name);
 return new vm.SyntheticModule(Object.keys(values),function(){for(const [key,value]of Object.entries(values))this.setExport(key,value);},{context});});
await module.evaluate();
const hooks=new Map(),tools=new Map(),entries=[],calls=[];
let project=null,selected=null,loseCreate=false;
const pi={on(name,fn){if(!hooks.has(name))hooks.set(name,[]);hooks.get(name).push(fn);},registerTool(tool){tools.set(tool.name,tool);},registerCommand(){},
 appendEntry(customType,data){entries.push({type:'custom',customType,data:structuredClone(data)});
  if(crashAt===customType){crashAt=undefined;throw Error('Controlled failure after native append');}}};
const created=new Map();
const call=async request=>{calls.push(request);if(request.action==='create'&&loseCreate){loseCreate=false;throw Error('Controlled failed reply');}
 if(request.action==='create'&&!created.has(request.idempotency_key))created.set(request.idempotency_key,String.fromCharCode(65+created.size));
 return{ok:true,result:request.action==='create'?{task:{id:created.get(request.idempotency_key),status:'ready'}}:{task:{id:request.task_id,status:'ready'},comments:[]}};};
module.namespace.registerRequestIntake(pi,{project:()=>project,task:()=>selected,failed:()=>false,select:id=>selected=id,call});
const ctx={cwd:'/owned-fixture',sessionManager:{getSessionId:()=> 'unit-only-session',getBranch:()=>entries},hasPendingMessages:()=>queued,
 ui:{setStatus(){},notify(){},getEditorText(){if(editorError)throw Error('Editor unavailable');return typed;}}};
const fire=async(name,event={})=>{let value;for(const fn of hooks.get(name)??[])value=await fn(event,ctx)??value;return value;};
const tool=async(name,input)=>tools.get(name).execute('unit',input,undefined,undefined,ctx);
const state=async()=> (await tool('kanban_intake_status',{})).details.result;
const capture=async text=>{await fire('input',{text,source:'interactive'});return entries.findLast(x=>x.customType==='pi-request-capture/v1').data.id;};
const settle=()=>fire('agent_before_settle',{outcome:'completed',continue:false,context:{pendingMessages:[]}});
await fire('session_start');
if(which==='question'){
 const q=await capture('What does this do?');assert.equal(await settle(),undefined);
 const draft=await capture('Draft B only; no implementation.');assert.equal(await settle(),undefined);
 let value=await state();assert.equal(value.pending_total,0);assert.equal(value.deferred_total,2);assert.equal(value.progress,0);assert.equal(value.retained_total,0);
 assert.equal(calls.length,0);assert.equal(decisions,0);assert.ok(value.deferred.every(x=>x.excerpt.length<=160));
 assert.equal((await tool('kanban_intake_status',{source_id:q})).details.result.source.text,'What does this do?');
 assert.equal((await tool('kanban_intake_route',{source_id:draft,parts:[{kind:'task',summary:'Unapproved B',execute:true}]})).isError,true);
 await fire('session_tree');value=await state();assert.equal(value.deferred_total,2);assert.equal(value.conversation.phase,'discussion');assert.equal(calls.length,0);
}else if(which==='approved'){
 project={root:'/owned-fixture',projectId:'p',boardId:'b'};
 const id=await capture('Owner approves only A.');await tool('kanban_intake_route',{source_id:id,parts:[{kind:'task',summary:'Approved task A',execute:true}]});
 const before=await state(),queue=JSON.stringify(before.queue);await capture('Status? Keep doing A.');
 const boundary=await settle();assert.equal(boundary.continue,true);let value=await state();assert.equal(JSON.stringify(value.queue),queue);assert.equal(value.progress,before.progress);
 assert.equal(calls.filter(x=>x.action==='create').length,1);assert.equal(value.deferred_total,1);
 const routedQuestion=await capture('Another status question, explicitly classified as question.');
 await tool('kanban_intake_route',{source_id:routedQuestion,parts:[{kind:'question',summary:'Status only, no new work'}]});
 assert.equal((await state()).progress,before.progress,'Routing a question must not manufacture progress');
 assert.equal((await settle()).continue,true);
 const pause=await capture('Explicit owner pause.');await tool('kanban_intake_route',{source_id:pause,control:'pause',parts:[{kind:'control',summary:'Pause now'}]});
 assert.equal(await settle(),undefined);await capture('Paused status?');assert.equal(await settle(),undefined);assert.equal((await state()).mode,'paused');
}else if(which==='uncertain'){
 project={root:'/owned-fixture',projectId:'p',boardId:'b'};loseCreate=true;
 const id=await capture('Approved task with uncertain routing.');const parts=[{kind:'task',summary:'Approved A',execute:true}];
 assert.equal((await tool('kanban_intake_route',{source_id:id,parts})).isError,true);
 await capture('What happened?');assert.equal(await settle(),undefined);
 let value=(await tool('kanban_intake_status',{source_id:id})).details.result;
 assert.equal(value.pending_total,1);assert.equal(value.disposition,'pending');assert.equal(value.frozen_intent.parts[0].summary,'Approved A');
 assert.equal((await tool('kanban_intake_route',{source_id:id,parts:[{...parts[0],summary:'Different intent'}]})).isError,true);
 assert.equal(calls.filter(x=>x.action==='create').length,1);assert.equal(decisions,0);
}else if(which==='legacy'){
 const text='Synthetic legacy pending request';const id=randomUUID();entries.push({type:'custom',customType:'pi-request-capture/v1',data:{id,text,source:'interactive',session:'unit-only-session',sha256:digest(text),images:0}});
 await fire('session_tree');await capture('Ordinary question');await settle();let value=await state();assert.equal(value.pending_total,1);assert.equal(value.deferred_total,1);
 assert.equal((await tool('kanban_intake_status',{source_id:id})).details.result.disposition,'pending');
 entries.push({type:'custom',customType:'pi-request-discussion/v1',data:{id,source_sha256:'0'.repeat(64),disposition:'deferred'}});
 await fire('session_tree');assert.equal((await state()).pending_total,1,'Wrong source hash cannot defer legacy input');
}else if(which==='selection'){
 project={root:'/owned-fixture',projectId:'p',boardId:'b'};
 const a=await capture('Owner approves A.');const pa=[{kind:'task',summary:'Approved A',execute:true}];
 await tool('kanban_intake_route',{source_id:a,parts:pa});assert.equal(selected,'A');
 const b=await capture('Owner now approves B; keep older A.');const pb=[{kind:'task',summary:'Approved B',execute:true}];
 await tool('kanban_intake_route',{source_id:b,parts:pb});assert.equal(selected,'B','Fresh approval must replace stale navigation');
 assert.equal((await state()).queue.length,2);assert.equal(created.size,2);
 await tool('kanban_intake_route',{source_id:a,parts:pa});assert.equal(selected,'B','Old exact retry must not steal current navigation');
 selected='stale';await fire('session_tree');await tool('kanban_intake_route',{source_id:b,parts:pb});
 assert.equal(selected,'B');assert.equal(created.size,2,'Exact retry after routed-before-selection must not create again');
 const before=(await state()).progress;const q=await capture('Status only.');
 await tool('kanban_intake_route',{source_id:q,parts:[{kind:'question',summary:'Status'}]});
 assert.equal(selected,'B');assert.equal((await state()).progress,before);assert.equal((await state()).queue.length,2);
 assert.equal((await settle()).continue,true,'Older approval queue remains available, no focus-stop');
}else if(which==='correction'){
 project={root:'/owned-fixture',projectId:'p',boardId:'b'};
 const id=await capture('Owner explicitly approves execution of C.');
 await tool('kanban_intake_route',{source_id:id,parts:[{kind:'question',summary:'Controlled mistaken classification'}]});
 const p=[{kind:'task',summary:'Original approved C',execute:true}];const request={source_id:id,reclassify_current:true,parts:p};
 assert.equal((await tool('kanban_intake_route',request)).isError,undefined);assert.equal(created.size,1);assert.equal(selected,'A');
 assert.equal(entries.filter(x=>x.customType==='pi-request-classification-correction/v1').length,1);
 await tool('kanban_intake_route',request);assert.equal(created.size,1);
 assert.equal((await tool('kanban_intake_route',{...request,parts:[{...p[0],summary:'Rewrite effectful intent'}]})).isError,true);
 for(const point of ['pi-request-route-intent/v1','pi-request-routed/v1']){
  const source=await capture('Owner explicitly approves this independent fixture action.');
  await tool('kanban_intake_route',{source_id:source,parts:[{kind:'control',summary:'Controlled effect-free misclassification'}]});
  const retry={source_id:source,reclassify_current:true,parts:[{kind:'task',summary:'Approved action '+point,execute:true}]};
  crashAt=point;assert.equal((await tool('kanban_intake_route',retry)).isError,true);
  await fire('session_tree');assert.equal((await tool('kanban_intake_route',retry)).isError,undefined);
  const size=created.size;await tool('kanban_intake_route',retry);assert.equal(created.size,size);
  assert.equal(selected,(await state()).queue.at(-1).task);
 }
 const stale=await capture('Owner approved this action, but a newer source supersedes this classification.');
 await tool('kanban_intake_route',{source_id:stale,parts:[{kind:'question',summary:'Mistaken'}]});
 await capture('Current status only.');assert.equal((await tool('kanban_intake_route',{source_id:stale,reclassify_current:true,parts:p})).isError,true);
 const foreign=await capture('Owner approved action within original identity only.');await tool('kanban_intake_route',{source_id:foreign,parts:[{kind:'control',summary:'Mistaken'}]});
 project={...project,boardId:'different'};assert.equal((await tool('kanban_intake_route',{source_id:foreign,reclassify_current:true,parts:p})).isError,true);
}else if(which==='typing'){
 project={root:'/owned-fixture',projectId:'p',boardId:'b'};const id=await capture('Owner approves A.');
 await tool('kanban_intake_route',{source_id:id,parts:[{kind:'task',summary:'Approved A',execute:true}]});
 const before=JSON.stringify(await state()),count=entries.length;
 typed='Unsent owner draft';assert.equal(await settle(),undefined);assert.equal(typed,'Unsent owner draft');assert.equal(entries.length,count);assert.equal(JSON.stringify(await state()),before);
 typed='';queued=true;assert.equal(await settle(),undefined);assert.equal(entries.length,count);queued=false;
 editorError=true;assert.equal(await settle(),undefined);assert.equal(entries.length,count);editorError=false;
 const requests=(await state()).requests,decisionsBefore=entries.filter(x=>x.customType==='pi-work-decision/v1').length;
 onProjection=()=>{typed='Typed during awaited retained projection';};assert.equal(await settle(),undefined);
 assert.equal((await state()).requests,requests);assert.equal(entries.filter(x=>x.customType==='pi-work-decision/v1').length,decisionsBefore);
 assert.equal(typed,'Typed during awaited retained projection');
}else throw Error('Unknown unit case');
await fire('session_shutdown');console.log('Conversation state control passed: '+which);
"""


class ConversationModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("Node is required for the complete module control")
        version = subprocess.run([cls.node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
        if tuple(int(part) for part in version.lstrip("v").split(".")[:2]) < (22, 13):
            raise unittest.SkipTest("Node22.13+ is required for TypeScript stripping")

    def run_case(self, name):
        result = subprocess.run([self.node, "--experimental-vm-modules", "--input-type=module", "-e", SCRIPT, str(SOURCE), name],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_answer_only_deferral_and_reload_need_no_board_or_framework(self):
        self.run_case("question")

    def test_status_answer_preserves_and_continues_approved_work(self):
        self.run_case("approved")

    def test_frozen_uncertain_route_is_not_deferred_or_replayed(self):
        self.run_case("uncertain")

    def test_legacy_pending_and_wrong_hash_remain_pending(self):
        self.run_case("legacy")

    def test_fresh_current_approval_selection_and_exact_replay(self):
        self.run_case("selection")

    def test_same_source_effect_free_correction_and_append_recovery(self):
        self.run_case("correction")

    def test_queued_typed_and_mid_await_input_suppress_automatic_work(self):
        self.run_case("typing")


if __name__ == "__main__":
    unittest.main()
