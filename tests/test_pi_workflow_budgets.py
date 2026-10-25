"""Declared workflow budgets and complete extension cancellation, model-free."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from harness.enforcement import validate_contract


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "adapters/pi/project-workflow"
SPEC = importlib.util.spec_from_file_location("everyday_budgets", WORKFLOW / "everyday_workflow.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class PiWorkflowBudgetTests(unittest.TestCase):
    def request(self, root, **fields):
        return {"objective": "One declared operation with its original verifier", "cwd": str(root),
                "action": [sys.executable, "worker.py"], "verify": [sys.executable, "check.py"],
                "outputs": ["result.txt"], **fields}

    def test_default_hour_and_core_limit_specs_preserve_all_budget_layers(self):
        for fields, action, check, outer in (({}, 585, 45, 780),
                                            ({"action_timeout_seconds": 3600, "check_timeout_seconds": 120}, 3600, 120, 3945),
                                            ({"action_timeout_seconds": 86385, "check_timeout_seconds": 86385}, 86385, 86385, 259260)):
            with self.subTest(fields=fields), tempfile.TemporaryDirectory() as directory:
                root, spec_path = helper.prepare(self.request(directory, **fields), WORKFLOW)
                spec = json.loads(spec_path.read_text())
                contract = validate_contract(root, spec)  # Actual existing core cap/schema.
                self.assertEqual(contract["worker"]["timeout_seconds"], action + 15)
                self.assertEqual(contract["verifier"]["timeout_seconds"], check + 15)
                self.assertEqual(contract["verifier"]["negative_control"]["timeout_seconds"], check + 15)
                self.assertEqual(json.loads((spec_path.parent / "action.json").read_text())["timeout"], action)
                self.assertEqual(json.loads((spec_path.parent / "check.json").read_text())["timeout"], check)
                budget = json.loads((spec_path.parent / "plan.json").read_text())["timeout_budget"]
                self.assertEqual(budget, {"action_timeout_seconds": action, "check_timeout_seconds": check,
                                         "worker_timeout_seconds": action + 15, "verifier_timeout_seconds": check + 15,
                                         "outer_timeout_seconds": outer})
                self.assertEqual(spec["retry"]["max_attempts"], 1)

    def test_invalid_and_hidden_budgets_refuse_before_workflow_files(self):
        for key in ("action_timeout_seconds", "check_timeout_seconds"):
            for value in (True, False, None, "3600", 1.5, 0, -1, 86386, 86400, float("inf"), float("nan")):
                with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(ValueError, "1..86385"):
                        helper.prepare(self.request(directory, **{key: value}), WORKFLOW)
                    self.assertFalse((Path(directory) / ".pi-workflow").exists())
        for key in ("_action_timeout", "_check_timeout", "_worker_timeout"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, "hidden timeout overrides"):
                    helper.prepare(self.request(directory, **{key: 1}), WORKFLOW)
                self.assertFalse((Path(directory) / ".pi-workflow").exists())

    def test_action_and_check_can_be_chosen_independently(self):
        self.assertEqual(helper.timeout_budget({"action_timeout_seconds": 3600})["outer_timeout_seconds"], 3795)
        self.assertEqual(helper.timeout_budget({"check_timeout_seconds": 3600})["outer_timeout_seconds"], 7890)
        self.assertEqual(helper.timeout_budget({"action_timeout_seconds": 1, "check_timeout_seconds": 1})["outer_timeout_seconds"], 108)

    def test_complete_extension_schema_timer_refusals_abort_and_owner_pipe(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for the complete extension test")
        version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
        if tuple(map(int, version.split(".")[:2])) < (22, 13):
            self.skipTest("Node22.13+ is required for TypeScript stripping")
        script = r'''
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import { homedir } from 'node:os';
import vm from 'node:vm';
const [source,root] = process.argv.slice(1);
process.env.PI_CODING_AGENT_DIR=path.join(root,'agent');
const skill=path.join(root,'agent/skills/supervised-tasks/SKILL.md');
fs.mkdirSync(path.dirname(skill),{recursive:true});fs.writeFileSync(skill,'Complete installed workflow instructions\n');
const hash=createHash('sha256').update(fs.readFileSync(path.join(path.dirname(source),'everyday_workflow.py'))).digest('hex');
const wrapped={...fs,readFileSync(file,...args){if(path.basename(String(file))==='everyday-runtime.json')
 return JSON.stringify({helper_sha256:hash,runtime:path.join(root,'runtime'),python:'qualified-python'});return fs.readFileSync(file,...args);}};
const timers=[],launches=[];let mode='success';
const execFile=(exe,argv,opts,callback)=>{
 const item={exe,argv,opts,ends:0,request:null};launches.push(item);
 const finish=()=>callback(null,JSON.stringify({status:'supplied_predicate_passed',authority:'tested'}),'');
 return {stdin:{on(){},write(raw){item.request=JSON.parse(raw);if(mode==='success')queueMicrotask(finish);},
   end(){item.ends++;queueMicrotask(()=>callback({code:130},JSON.stringify({status:'cancelled',authority:'none'}),''));}}};
};
const Type=new Proxy({},{get:(_t,key)=>key==='Object'?properties=>({properties}):key==='Optional'?value=>value:
 key==='Integer'?value=>({type:'integer',...value}):()=>({})});
const dependencies={typebox:{Type},'node:child_process':{execFile},'node:fs':wrapped,'node:path':path,
 'node:crypto':{createHash},'node:url':{fileURLToPath},'node:os':{homedir}};
const context=vm.createContext({Buffer,process,console,queueMicrotask,setTimeout(fn,ms){const id={fn,ms,cleared:false};timers.push(id);return id;},clearTimeout(id){id.cleared=true;}});
const module=new vm.SourceTextModule(stripTypeScriptTypes(fs.readFileSync(source,'utf8')),
 {context,initializeImportMeta(meta){meta.url=pathToFileURL(source).href;}});
await module.link(name=>{const values=dependencies[name];assert.ok(values,name);return new vm.SyntheticModule(Object.keys(values),function(){for(const [key,value]of Object.entries(values))this.setExport(key,value);},{context});});
await module.evaluate();const hooks=new Map(),tools=new Map();
const pi={registerTool(tool){tools.set(tool.name,tool);},on(name,handler){if(!hooks.has(name))hooks.set(name,[]);hooks.get(name).push(handler);},
 getAllTools(){return[{name:'read'},{name:'workflow_step'}];},getActiveTools(){return['read','workflow_step'];},setActiveTools(){}};
module.namespace.default(pi);const tool=tools.get('workflow_step');assert.ok(tool);
for(const name of ['action_timeout_seconds','check_timeout_seconds']){
 assert.equal(tool.parameters.properties[name].type,'integer');assert.equal(tool.parameters.properties[name].minimum,1);assert.equal(tool.parameters.properties[name].maximum,86385);}
assert.match(tool.description,/multiple related steps/);
const fire=async(name,event={})=>{let result;for(const handler of hooks.get(name)??[])result=await handler(event,{cwd:root})??result;return result;};
const prompt=await fire('before_agent_start',{systemPrompt:'Base'});assert.match(prompt.systemPrompt,/not an entire-project or session deadline/);
await fire('tool_result',{toolName:'agent_capabilities',details:{ok:true}});
await fire('tool_result',{toolName:'read',input:{path:skill},content:[{type:'text',text:fs.readFileSync(skill,'utf8')}]});
const base={objective:'Useful long operation',cwd:root,action:['python','worker.py'],verify:['python','check.py'],outputs:['output.txt']};
for(const [fields,ms]of [[{},780000],[{action_timeout_seconds:3600,check_timeout_seconds:120},3945000],
 [{action_timeout_seconds:86385,check_timeout_seconds:86385},259260000]]){
 const result=await tool.execute('call',{...base,...fields});assert.equal(result.isError,false);assert.equal(timers.at(-1).ms,ms);assert.ok(timers.at(-1).cleared);assert.equal(launches.at(-1).ends,0);
 for(const [key,value]of Object.entries(fields))assert.equal(launches.at(-1).request[key],value);
}
for(const key of ['action_timeout_seconds','check_timeout_seconds'])for(const value of [null,true,false,'3600',1.5,0,-1,86386,86400,Infinity,NaN]){
 const before=launches.length;const input={...base,[key]:value};const result=await tool.execute('bad',input);
 assert.equal(result.isError,true);assert.equal(launches.length,before);assert.match(JSON.parse(result.content[0].text).reason,/1..86385/);
 assert.equal((await fire('tool_call',{toolName:'workflow_step',input})).block,true);
}
for(const key of ['_action_timeout','_check_timeout','_worker_timeout']){
 const before=launches.length;assert.equal((await tool.execute('hidden',{...base,[key]:1})).isError,true);assert.equal(launches.length,before);
}
const aborted=new AbortController();aborted.abort();const before=launches.length;await tool.execute('cancel',base,aborted.signal);assert.equal(launches.length,before);
mode='pending';const pending=tool.execute('deadline',{...base,action_timeout_seconds:3600});const timer=timers.at(-1);assert.equal(timer.ms,3795000);
assert.equal(launches.at(-1).ends,0);timer.fn();assert.equal((await pending).isError,true);assert.equal(launches.at(-1).ends,1);
const abort=new AbortController();const active=tool.execute('abort',base,abort.signal);abort.abort();assert.equal((await active).isError,true);assert.equal(launches.at(-1).ends,1);
console.log('Declared workflow budgets, fixed timers and existing owner-pipe cancellation passed');
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([node, "--experimental-vm-modules", "--input-type=module", "-e", script,
                                     str(WORKFLOW / "everyday-workflow.ts"), directory],
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("owner-pipe cancellation passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
