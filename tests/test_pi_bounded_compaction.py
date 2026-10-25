"""Whole-module bounded compaction controls, with optional actual Pi runtime."""

import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "adapters" / "pi" / "bounded-compaction.ts"
SCRIPT = r'''
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';
const [source,nativePackage=''] = process.argv.slice(1);
let calls=[], stopReason='stop', networkCalls=0;
globalThis.fetch=()=>{networkCalls++;throw Error('Network must not be called by this control');};
const answer=()=>({role:'assistant',content:[{type:'text',text:'Synthetic compact handoff'}],
 api:'openai-completions',provider:'qualification-local',model:'qualification-summary',
 stopReason,timestamp:Date.now(),usage:{input:10,output:5,cacheRead:0,cacheWrite:0,
 totalTokens:15,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}});
let sdk,registry,model;
if(nativePackage){
 assert.equal(JSON.parse(fs.readFileSync(path.join(nativePackage,'package.json'))).version,'1.4.0');
 sdk=await import(pathToFileURL(path.join(nativePackage,'dist/index.js')).href);
 const ai=await import(import.meta.resolve('@earendil-works/pi-ai',pathToFileURL(path.join(nativePackage,'package.json')).href));
 const credentials={async read(){return undefined;},async list(){return[];},async modify(_id,fn){return fn(undefined);},async delete(){}};
 const runtime=await sdk.ModelRuntime.create({credentials,modelsPath:null,allowModelNetwork:false,refreshOnCreate:false});
 runtime.registerProvider('qualification-local',{api:'openai-completions',apiKey:'synthetic-only',
  baseUrl:'http://127.0.0.1:19876/v1',models:[{id:'qualification-summary',name:'Qualification',
  reasoning:true,input:['text'],contextWindow:65536,maxTokens:16384,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}],
  streamSimple(received,context,options){
   calls.push({received,context,options});
   const stream=ai.createAssistantMessageEventStream();stream.end(answer());return stream;
  }});
 registry=new sdk.ModelRegistry(runtime);model=registry.find('qualification-local','qualification-summary');
 assert.ok(model);assert.equal(typeof registry.streamSimple,'function');
}else{
 model={provider:'qualification-local',id:'qualification-summary',baseUrl:'http://127.0.0.1:19876/v1',reasoning:true,maxTokens:16384};
 registry={streamSimple(received,context,options){calls.push({received,context,options});return{async result(){return answer();}};}};
 sdk={async compact(preparation,received,_key,_headers,focus,signal,reasoning,stream,_env,retry){
  assert.equal(reasoning,'off');assert.equal(retry.enabled,false);assert.match(focus,/at most 1500 words/);
  const result=await stream(received,{messages:[{role:'user',content:[{type:'text',text:'Synthetic source'}]}]},
   {maxTokens:20000,signal}).result();
  if(result.stopReason==='length')throw Error('Synthetic native length rejection');
  return{summary:result.content[0].text,firstKeptEntryId:preparation.firstKeptEntryId};
 }};
}
const context=vm.createContext({Buffer,process,URL,console,setTimeout,clearTimeout});
const dependencies={'@earendil-works/pi-coding-agent':sdk,'node:crypto':{createHash},'node:fs':fs,'node:path':path};
const module=new vm.SourceTextModule(stripTypeScriptTypes(fs.readFileSync(source,'utf8')),{context});
await module.link(name=>{const value=dependencies[name];assert.ok(value,'Unexpected import '+name);
 return new vm.SyntheticModule(Object.keys(value),function(){for(const [key,item]of Object.entries(value))this.setExport(key,item);},{context});});
await module.evaluate();
const hooks=new Map(),branch=[];let aborts=0;
const pi={on(name,handler){hooks.set(name,handler);},appendEntry(customType,data){branch.push({type:'custom',customType,data});}};
const selector={provider:model.provider,id:model.id,base_url:model.baseUrl};
assert.throws(()=>module.namespace.registerBoundedCompaction(pi,[{...selector,base_url:'https://example.com/v1'}]),/local endpoint/);
module.namespace.registerBoundedCompaction(pi,[selector]);
const ctx={model,modelRegistry:registry,sessionManager:{getBranch:()=>branch},abort(){aborts++;},ui:{notify(){}}};
await hooks.get('session_start')({},ctx);
const preparation={firstKeptEntryId:'kept-entry',messagesToSummarize:[{role:'user',content:[{type:'text',text:'Synthetic current objective'}],timestamp:Date.now()}],
 turnPrefixMessages:[],isSplitTurn:false,tokensBefore:20000,fileOps:{read:new Set(),written:new Set(),edited:new Set()},
 settings:{enabled:true,reserveTokens:16384,keepRecentTokens:20000}};
const event={preparation,reason:'threshold',signal:new AbortController().signal,customInstructions:'Preserve exact errors'};
const ordinaryReasoning=model.reasoning;
const result=await hooks.get('session_before_compact')(event,ctx);
assert.equal(result.compaction.summary,'Synthetic compact handoff');assert.equal(calls.length,1);
assert.ok(calls[0].options.maxTokens<=8192);assert.ok(!calls[0].options.reasoning||calls[0].options.reasoning==='off');
assert.equal(model.reasoning,ordinaryReasoning);
if(nativePackage){assert.equal(calls[0].options.cacheRetention,'none');assert.match(JSON.stringify(calls[0].context),/at most 1500 words/);}
stopReason='length';const failed=await hooks.get('session_before_compact')(event,ctx);
assert.equal(failed.cancel,true);assert.equal(calls.length,2);assert.equal(aborts,1);
await hooks.get('session_start')({},ctx);
const held=await hooks.get('session_before_compact')(event,ctx);
assert.equal(held.cancel,true);assert.equal(calls.length,2,'Reloaded failure hold must not retry automatically');
stopReason='stop';const manual=await hooks.get('session_before_compact')({...event,reason:'manual'},ctx);
assert.ok(manual.compaction);assert.equal(calls.length,3);
await hooks.get('session_compact')({reason:'manual'},ctx);
assert.equal(branch.at(-1).data.held,false);
const outside={...ctx,model:{...model,id:'unselected-model'}};
assert.equal(await hooks.get('session_before_compact')(event,outside),undefined);assert.equal(calls.length,3);
assert.equal(networkCalls,0);
console.log(JSON.stringify({mode:nativePackage?'actual-pi-1.4-model-runtime':'whole-module-contract',
 summaryRequests:calls.length,networkCalls,realModelCalls:0,heldAfterLength:true,manualRecovery:true}));
'''


class PiBoundedCompactionTests(unittest.TestCase):
    def run_control(self, native_package=""):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for the complete extension control")
        version = subprocess.run([node, "--version"], check=True, capture_output=True, text=True).stdout.strip()
        if tuple(int(part) for part in version.lstrip("v").split(".")[:2]) < (22, 13):
            self.skipTest("Node22.13+ is required for TypeScript stripping")
        result = subprocess.run([node, "--experimental-vm-modules", "--experimental-import-meta-resolve", "--input-type=module", "-e", SCRIPT,
                                 str(SOURCE), native_package], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_whole_module_preserves_cap_failure_hold_and_manual_recovery(self):
        self.assertIn('"whole-module-contract"', self.run_control())

    def test_actual_pi14_compact_and_model_registry_contract(self):
        package = os.environ.get("PI_TEST_NATIVE_PACKAGE")
        if not package:
            self.skipTest("Set PI_TEST_NATIVE_PACKAGE for the actual installed Pi1.4 runtime control")
        self.assertIn('"actual-pi-1.4-model-runtime"', self.run_control(package))


if __name__ == "__main__":
    unittest.main()
