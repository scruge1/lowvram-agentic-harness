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
let decisions=0;
const Type=new Proxy({},{get:()=>()=>({})});
const dependencies={typebox:{Type},'node:crypto':{createHash,randomUUID},
 './read-loop-079.ts':{registerReadLoopGuard:()=>({warning:()=>''})},
 './dependency-receipts-138.ts':{checkedReceipt:()=>{},inspectReceipt:()=>({verified:false}),watchReceipt:()=>()=>{},blockedTaskIds:()=>new Set()},
 './retained-packet-138.ts':{workKey:x=>x.root+'\0'+x.task,nativeCompletionOrder:()=>new Map(),cancelledSelection:async()=>false,
  buildRetainedPacket:async input=>({tasks:input.state.queue.map(x=>({id:x.task,source:x.source,status:'ready'})),anchors:[],excluded:[],coverage:{complete:true,truncated:false,missing:[]}})},
 './decision-bridge-138.ts':{packetDigest:digest,decideRetainedWork:async packet=>{decisions++;return packet.tasks.length?{decision:'continue',selected:{task:packet.tasks[0].id,source:packet.tasks[0].source,action:'continue'}}:{decision:'queue_complete'};}}};
const context=vm.createContext({Buffer,process,console,structuredClone,setTimeout,clearTimeout});
const module=new vm.SourceTextModule(stripTypeScriptTypes(fs.readFileSync(file,'utf8')),{context});
await module.link(name=>{const values=dependencies[name];assert.ok(values,'Unexpected dependency '+name);
 return new vm.SyntheticModule(Object.keys(values),function(){for(const [key,value]of Object.entries(values))this.setExport(key,value);},{context});});
await module.evaluate();
const hooks=new Map(),tools=new Map(),entries=[],calls=[];
let project=null,selected=null,loseCreate=false;
const pi={on(name,fn){if(!hooks.has(name))hooks.set(name,[]);hooks.get(name).push(fn);},registerTool(tool){tools.set(tool.name,tool);},registerCommand(){},
 appendEntry(customType,data){entries.push({type:'custom',customType,data:structuredClone(data)});}};
const call=async request=>{calls.push(request);if(request.action==='create'&&loseCreate){loseCreate=false;throw Error('Controlled failed reply');}
 return{ok:true,result:request.action==='create'?{task:{id:'A',status:'ready'}}:{task:{id:request.task_id,status:'ready'},comments:[]}};};
module.namespace.registerRequestIntake(pi,{project:()=>project,task:()=>selected,failed:()=>false,select:id=>selected=id,call});
const ctx={cwd:'/owned-fixture',sessionManager:{getSessionId:()=> 'unit-only-session',getBranch:()=>entries},ui:{setStatus(){},notify(){}}};
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


if __name__ == "__main__":
    unittest.main()
