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
const start=row('pi-managed-child-start/v1',identity),result=row('pi-managed-child-result/v1',identity);
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
assert.deepEqual(pending([row('pi-managed-child-start/v1',{...identity,project:{root:'/other/project'}})]),[]);
assert.throws(()=>pending([row('pi-managed-child-start/v1',{})]),/Invalid managed-child/);
console.log(JSON.stringify({checks:12,scope:'actual journal reducer, no alternate ledger or permission classifier'}));
"""
        result = subprocess.run(
            [node, "--disable-warning=ExperimentalWarning", "--input-type=module", "-e", script,
             str(ROOT / "adapters/pi/intake/request-intake-138.ts")],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["checks"], 12)


if __name__ == "__main__":
    unittest.main()
