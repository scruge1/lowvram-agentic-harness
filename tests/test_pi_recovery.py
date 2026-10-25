"""Failure inspection and corrective-plan admission through the exported adapter."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "adapters" / "pi" / "project-workflow"
SPEC = importlib.util.spec_from_file_location("everyday_recovery", WORKFLOW / "everyday_workflow.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def recovery():
    return {"source_run_id": "0" * 32, "failure_class": "tool_interface",
            "changed_assumption": "Inspect the actual response body instead",
            "new_evidence": "The failed call saved a complete error response",
            "expected_observation": "The response identifies the unsupported argument",
            "stop_condition": "Stop if the actual response cannot establish that cause"}


class PiRecoveryTests(unittest.TestCase):
    def test_invalid_recovery_refuses_before_creating_workflow_files(self):
        with tempfile.TemporaryDirectory() as directory:
            request = {"cwd": directory, "objective": "Correct the observed failure",
                       "action": [sys.executable, "worker.py"], "verify": [sys.executable, "check.py"],
                       "outputs": ["result.txt"], "recovery": {"source_run_id": "wrong"}}
            with self.assertRaisesRegex(ValueError, "Recovery"):
                helper.prepare(request)
            self.assertFalse((Path(directory) / ".pi-workflow").exists())

    def test_plan_retains_the_exact_source_run_and_new_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            request = {"cwd": directory, "objective": "Correct the observed failure",
                       "action": [sys.executable, "worker.py"], "verify": [sys.executable, "check.py"],
                       "outputs": ["result.txt"], "recovery": recovery()}
            _, spec = helper.prepare(request)
            plan = json.loads((spec.parent / "plan.json").read_text())
            self.assertEqual(plan["recovery"], request["recovery"])
            self.assertEqual(plan["retry"], "no automatic replay")

    def test_complete_extension_rejects_stale_unread_and_unmatched_recovery(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for the complete extension control")
        version = subprocess.run([node, "--version"], check=True, capture_output=True, text=True).stdout.strip()
        if tuple(int(part) for part in version.lstrip("v").split(".")[:2]) < (22, 13):
            self.skipTest("Node22.13+ is required for TypeScript stripping")
        script = r'''
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import { homedir } from 'node:os';
import vm from 'node:vm';
const [source, root] = process.argv.slice(1);
process.env.PI_CODING_AGENT_DIR = path.join(root,'agent');
const skill = path.join(process.env.PI_CODING_AGENT_DIR,'skills','supervised-tasks','SKILL.md');
fs.mkdirSync(path.dirname(skill),{recursive:true});fs.writeFileSync(skill,'Reviewed workflow instructions\n');
const helper=path.join(path.dirname(source),'everyday_workflow.py');
const helperHash=createHash('sha256').update(fs.readFileSync(helper)).digest('hex');
const wrappedFs={...fs,readFileSync(file,...args){
  if(path.basename(String(file))==='everyday-runtime.json')return JSON.stringify({helper_sha256:helperHash,runtime:path.join(root,'runtime')});
  return fs.readFileSync(file,...args);
}};
const type=new Proxy({},{get:()=>()=>({})});
const deps={typebox:{Type:type},'node:child_process':{execFile(){throw Error('Unexpected action launch')}},
 'node:fs':wrappedFs,'node:path':path,'node:crypto':{createHash},'node:url':{fileURLToPath},'node:os':{homedir}};
const context=vm.createContext({Buffer,process,console,setTimeout,clearTimeout});
const module=new vm.SourceTextModule(stripTypeScriptTypes(fs.readFileSync(source,'utf8')),
 {context,initializeImportMeta(meta){meta.url=pathToFileURL(source).href;}});
await module.link(specifier=>{const values=deps[specifier];assert.ok(values,'Unexpected import '+specifier);
 return new vm.SyntheticModule(Object.keys(values),function(){for(const [key,value]of Object.entries(values))this.setExport(key,value);},{context});});
await module.evaluate();
const hooks=new Map(),tools=new Map();
const pi={on(name,handler){if(!hooks.has(name))hooks.set(name,[]);hooks.get(name).push(handler);},
 registerTool(tool){tools.set(tool.name,tool);},getAllTools(){return[{name:'read'},{name:'workflow_step'}];},
 getActiveTools(){return['read','workflow_step'];},setActiveTools(){}};
module.namespace.default(pi);
const ctx={cwd:root};
const fire=async(name,event={})=>{let result;for(const handler of hooks.get(name)??[])result=await handler(event,ctx)??result;return result;};
const read=async(file,extra={})=>fire('tool_result',{toolName:'read',input:{path:file},content:[{type:'text',text:fs.readFileSync(file,'utf8')}],...extra});
await fire('session_start');
await fire('tool_result',{toolName:'agent_capabilities',details:{ok:true}});await read(skill);
const run='0'.repeat(32),failure=path.join(root,'.enforcement/runs',run,'final.json');
fs.mkdirSync(path.dirname(failure),{recursive:true});
const fail=async()=>fire('tool_result',{toolName:'workflow_step',details:{ok:false,host:{task_root:root,run_id:run}}});
const call=async(input={},toolCallId='attempt-1')=>fire('tool_call',{toolName:'workflow_step',toolCallId,input});
const recovery={source_run_id:run,failure_class:'tool_interface',changed_assumption:'Inspect the actual response body instead',
 new_evidence:'Saved exact failure body identifies unsupported argument',expected_observation:'Response contains a specific unsupported field',
 stop_condition:'Stop if the actual body cannot establish that cause'};
fs.writeFileSync(failure,JSON.stringify({run_id:run,status:'failed'}));await fail();
assert.match((await call()).reason,/complete saved failure/);
await read(failure,{details:{truncation:{}}});assert.ok((await call({recovery})).block);
fs.writeFileSync(failure,'invalid JSON');await read(failure);assert.ok((await call({recovery})).block);
fs.writeFileSync(failure,JSON.stringify({run_id:'f'.repeat(32)}));await read(failure);assert.ok((await call({recovery})).block);
fs.writeFileSync(failure,JSON.stringify({run_id:run,status:'failed'}));await read(failure);
assert.match((await call()).reason,/not evidence-bound/);
assert.ok((await call({recovery:{...recovery,source_run_id:'f'.repeat(32)}})).block);
assert.ok((await call({recovery:{...recovery,new_evidence:'try again'}})).block);
assert.equal(await call({recovery}),undefined);
await fire('tool_result',{toolName:'workflow_step',toolCallId:'different-call',input:{recovery},
 details:{ok:true,host:{status:'supplied_predicate_passed',run_id:'1'.repeat(32)}}});
assert.ok((await call()).block,'Unrelated success cannot clear the failure');
await fire('tool_result',{toolName:'workflow_step',toolCallId:'attempt-1',input:{recovery},
 details:{ok:true,host:{status:'supplied_predicate_passed',run_id:'1'.repeat(32)}}});
assert.equal(await call(),undefined,'Matching host-verified recovery clears the inspected failure');
await fail();await read(failure);
fs.writeFileSync(failure,JSON.stringify({run_id:run,status:'failed',reason:'Updated evidence'}));
assert.match((await call({recovery})).reason,/source changed/);
assert.match((await call({recovery})).reason,/complete saved failure/);
await read(failure);assert.equal(await call({recovery}),undefined,'Exact new inspection restores recovery admission');
console.log('Complete failure recovery extension controls passed');
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([node, "--experimental-vm-modules", "--input-type=module", "-e", script,
                                     str(WORKFLOW / "everyday-workflow.ts"), directory],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("recovery extension controls passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
