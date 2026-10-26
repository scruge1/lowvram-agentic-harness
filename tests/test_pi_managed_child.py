import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManagedChildContractTests(unittest.TestCase):
    def test_actual_module_model_binding_and_invalid_requests(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node22.13+ is required")
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if tuple(int(item) for item in version.lstrip("v").split(".")[:2]) < (22, 13):
            self.skipTest("Node22.13+ is required")
        script = r"""
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync } from 'node:fs';
import { join } from 'node:path';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';
let code = readFileSync(process.argv[1], 'utf8').replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
code = stripTypeScriptTypes(code) + '\nglobalThis.api={childModelBinding,runManagedChild};';
const sandbox = { createHash, readFileSync, realpathSync, join, Buffer, process,
  AbortController, setTimeout, clearTimeout };
vm.createContext(sandbox); vm.runInContext(code, sandbox);
const api = sandbox.api;
const model = { provider:'local',api:'openai-completions',id:'fixture',baseUrl:'http://127.0.0.1:1/v1',headers:{'x-route':'private-value'} };
const first = api.childModelBinding(model);
assert.match(first,/^[a-f0-9]{64}$/);
assert.ok(!first.includes('private-value'));
for (const field of ['headers','compat','baseUrl','contextWindow','maxTokens']) {
  const changed = { ...model, [field]:field==='headers'?{'x-route':'other'}:'changed' };
  assert.notEqual(api.childModelBinding(changed),first,field);
}
assert.throws(()=>api.childModelBinding({...model,provider:'foreign'}),/owned local model/);
assert.throws(()=>api.childModelBinding({...model,api:'unknown'}),/owned local model/);
for (const params of [{task:'',timeout_seconds:60},{task:'x',timeout_seconds:0},
  {task:'x',timeout_seconds:86386},{task:'x',timeout_seconds:1.2},
  {task:'x',timeout_seconds:60,provider:'foreign'},{task:'x'.repeat(4001),timeout_seconds:60}]) {
  await assert.rejects(api.runManagedChild({}, {}, 'fixture', params, {}, new AbortController().signal,()=>{}),/bounded task/);
}
console.log(JSON.stringify({checks:15,scope:'whole-module source contract; no SDK/model/provider invocation'}));
"""
        result = subprocess.run(
            [node, "--disable-warning=ExperimentalWarning", "--input-type=module", "-e", script,
             str(ROOT / "adapters/pi/project-workflow/managed-child.ts")],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["checks"], 15)


    def test_actual_intake_child_journal_recovery(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node22.13+ is required")
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if tuple(int(item) for item in version.lstrip("v").split(".")[:2]) < (22, 13):
            self.skipTest("Node22.13+ is required")
        script = r"""
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import vm from 'node:vm';
let code=readFileSync(process.argv[1],'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
code=stripTypeScriptTypes(code)+'\nglobalThis.check=unresolvedChildCalls;';
const sandbox={createHash};vm.createContext(sandbox);vm.runInContext(code,sandbox);
const project={root:'/owned/project',projectId:'p',boardId:'b'};
const identity={id:'same-native-id',project,card:'child',parent_card:'root',source:'source',source_sha256:'a'.repeat(64),parent_session:'parent'};
const row=(customType,data)=>({type:'custom',customType,data});
const start=row('pi-managed-child-start/v1',identity),result=row('pi-managed-child-result/v1',{...identity,state:'returned'});
const pending=rows=>Array.from(sandbox.check(rows,project.root));
assert.deepEqual(pending([start]),[identity.id]);
assert.deepEqual(pending([start,result]),[]);
assert.deepEqual(pending([result,start]),[identity.id]);
assert.deepEqual(pending([start,{...result,data:{...identity,card:'foreign'}}]),[identity.id]);
const resume=(root=project.root,source='interactive')=>[
 row('pi-request-capture/v1',{id:'resume',project:{root},source}),
 row('pi-request-route-intent/v1',{id:'resume',intent:{project:{root},control:'resume'}}),
 row('pi-request-routed/v1',{id:'resume',control:'resume'})];
assert.deepEqual(pending([start,...resume()]),[]);
assert.deepEqual(pending([...resume(),start]),[identity.id]);
assert.deepEqual(pending([start,...resume('/other/project')]),[identity.id]);
assert.deepEqual(pending([start,...resume(project.root,'extension')]),[identity.id]);
assert.deepEqual(pending([start,...resume(project.root,'historical-unverified')]),[identity.id]);
assert.deepEqual(pending([start,row('pi-request-work-state/v1',{mode:'running'})]),[identity.id]);
for(const state of ['failed','deadline','cancelled','delivery_held','unknown',undefined])
 assert.deepEqual(pending([start,row('pi-managed-child-result/v1',{...identity,state})]),[identity.id]);
assert.deepEqual(pending([start,row('pi-managed-child-result/v1',{...identity,state:'failed'}),...resume()]),[]);
assert.deepEqual(pending([row('pi-managed-child-start/v1',{...identity,project:{root:'/other/project'}})]),[]);
assert.throws(()=>pending([row('pi-managed-child-start/v1',{})]),/Invalid managed-child/);
console.log(JSON.stringify({checks:19,scope:'actual journal reducer, no alternate ledger or permission classifier'}));
"""
        result = subprocess.run(
            [node, "--disable-warning=ExperimentalWarning", "--input-type=module", "-e", script,
             str(ROOT / "adapters/pi/intake/request-intake-138.ts")],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["checks"], 19)


    def test_bounded_projection_and_exact_journal_windows(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node22.13+ is required")
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if tuple(int(item) for item in version.lstrip("v").split(".")[:2]) < (22, 13):
            self.skipTest("Node22.13+ is required")
        script = r"""
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const {childModelReply,inspectChildRecord,childRecordDigest,CHILD_REPLY_BYTES}=await import(pathToFileURL(process.argv[1]));
const project={root:'/owned/project',projectId:'p',boardId:'b'},sourceText='Synthetic original owner scope';
const sourceHash=childRecordDigest(sourceText),rawOnly='RAW_RETAINED_ONLY_🙂\n'.repeat(1500);
const messages=[{role:'assistant',content:[{type:'thinking',thinking:'Private intermediate fixture text'},{type:'text',text:'Actual final δ🙂\n'.repeat(1200)}],usage:{input:11,output:7,cacheRead:0,cacheWrite:0,totalTokens:18}}];
const calls=Array.from({length:30},(_,i)=>({name:'workflow_step',isError:false,input:{outputs:['result-'+i+'.txt']},result:{content:[{type:'text',text:i===0?rawOnly:'Fixture outcome'}],details:{host:{status:'supplied_predicate_passed',run_id:'run'+i,receipt:'/owned/project/.icm/receipt-'+i+'.json',task_spec:'/owned/project/.icm/task-'+i+'.json'}}}}));
const result={messages,calls,model_sha256:'b'.repeat(64)};
const record={id:'call',project,card:'child',parent_card:'root',source:'s',source_sha256:sourceHash,parent_session:'parent',child_session:'child-session',state:'returned',...result};
const copy=JSON.stringify(record),summary=childModelReply(result,record);
assert.ok(Buffer.byteLength(JSON.stringify(summary))<=CHILD_REPLY_BYTES);
assert.ok(summary.final_text.startsWith('Actual final'));
assert.ok(summary.final_text_truncated&&summary.calls_truncated&&!summary.evidence_complete);
assert.ok(summary.calls.length>0);
assert.equal(summary.calls[0].receipt,'.icm/receipt-0.json');assert.deepEqual(summary.calls[0].outputs,['result-0.txt']);
assert.equal(summary.native_reported_usage.input,11);assert.equal(summary.native_reported_usage.output,7);
assert.ok(!JSON.stringify(summary).includes('RAW_RETAINED_ONLY')&&!JSON.stringify(summary).includes('Private intermediate'));
assert.equal(JSON.stringify(record),copy);assert.equal(summary.record.sha256,childRecordDigest(record));
assert.equal(summary.inspect.tool,'task_agent_inspect');assert.equal(summary.inspect.arguments.record_sha256,summary.record.sha256);
const entry={type:'custom',customType:'pi-managed-child-result/v1',data:record};
const branch=[{type:'custom',customType:'pi-request-capture/v1',data:{id:'s',text:sourceText,sha256:sourceHash}},{type:'custom',customType:'pi-request-route-intent/v1',data:{id:'s',intent:{project}}},entry];
const metadata=inspectChildRecord(branch,project,'new-parent',{call_id:'call'});
assert.ok(metadata.requires_record_sha256&&metadata.record.historical_session&&metadata.record.historical_data&&!metadata.complete_record);
let offset=0,assembled='',pages=0;
do {
 const page=inspectChildRecord(branch,project,'parent',{call_id:'call',record_sha256:summary.record.sha256,offset,max_bytes:4096});
 assert.ok(Buffer.byteLength(JSON.stringify(page))<=4096);
 assert.equal(page.window_sha256,createHash('sha256').update(page.data).digest('hex'));
 assert.equal(page.offset,offset);assert.equal(page.scope,'one_native_record_window_not_whole_history');
 assembled+=page.data;offset=page.next_offset;if(offset!==null){assert.equal(page.next.arguments.offset,offset);assert.equal(page.next.arguments.record_sha256,summary.record.sha256);}assert.ok(++pages<400);
}while(offset!==null);
assert.ok(pages>1);assert.equal(assembled,copy);assert.equal(createHash('sha256').update(assembled).digest('hex'),summary.record.sha256);
assert.throws(()=>inspectChildRecord(branch,{...project,root:'/foreign'},'parent',{call_id:'call'}),/No matching/);
assert.throws(()=>inspectChildRecord(branch,project,'parent',{call_id:'call',record_sha256:'0'.repeat(64),offset:0}),/No matching/);
for(const extra of [{offset:0},{record_sha256:summary.record.sha256,offset:-1},{max_bytes:12289},{file:'/private/auth'}])assert.throws(()=>inspectChildRecord(branch,project,'parent',{call_id:'call',...extra}));
const changed=structuredClone(branch);changed[0].data.text+='changed';assert.throws(()=>inspectChildRecord(changed,project,'parent',{call_id:'call'}),/source is missing or changed/);
const stale=structuredClone(branch);stale.at(-1).data.state='changed';assert.throws(()=>inspectChildRecord(stale,project,'parent',{call_id:'call',record_sha256:summary.record.sha256,offset:0}),/No matching/);
console.log(JSON.stringify({pages,scope:'actual pure projection/inspection; bounded Unicode windows and full retained record unchanged'}));
"""
        result = subprocess.run(
            [node, "--input-type=module", "-e", script,
             str(ROOT / "adapters/pi/project-workflow/child-reply.mjs")],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertGreater(json.loads(result.stdout)["pages"], 1)


if __name__ == "__main__":
    unittest.main()
