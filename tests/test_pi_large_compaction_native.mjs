import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

// Run only with explicitly supplied test package and owned disposable parent.
const [packageInput, parentInput] = process.argv.slice(2);
assert(packageInput && parentInput, 'Usage: node test_pi_large_compaction_native.mjs PI_PACKAGE FIXTURE_PARENT');
const packageDir = fs.realpathSync(packageInput);
const parent = fs.realpathSync(parentInput);
assert.equal(JSON.parse(fs.readFileSync(path.join(packageDir, 'package.json'), 'utf8')).version, '1.4.0');
assert(fs.statSync(parent).isDirectory());
const native = await import(pathToFileURL(path.join(packageDir, 'dist/index.js')).href);
const root = fs.mkdtempSync(path.join(parent, 'pi-large-context-fixture-'));
const agentDir=path.join(root,'agent');
const cwd=path.join(root,'project');
const sessionDir=path.join(root,'sessions');
const extDir=path.join(agentDir,'extensions');
for(const d of [agentDir,cwd,sessionDir,extDir])fs.mkdirSync(d,{recursive:true});
const receipt=path.join(root,'hook-receipt.jsonl');
const summary='SYNTHETIC_COMPACT_SUMMARY; preserve accepted scope, independent verification, and current task';
fs.writeFileSync(path.join(extDir,'large-session-receipt.mjs'),`
import { appendFileSync } from 'node:fs';
export default function(pi) {
 pi.on('session_before_compact', async event => {
  appendFileSync(${JSON.stringify(receipt)}, JSON.stringify({kind:'before',entries:event.branchEntries.length,selected_to_keep:event.preparation.firstKeptEntryId})+'\\n');
  return {compaction:{summary:${JSON.stringify(summary)},firstKeptEntryId:event.preparation.firstKeptEntryId,tokensBefore:event.preparation.tokensBefore,details:{synthetic:true}}};
 });
 pi.on('session_compact', async event => {
  appendFileSync(${JSON.stringify(receipt)}, JSON.stringify({kind:'after',entry_type:event.compactionEntry.type,reason:event.reason})+'\\n');
 });
}
`);
const sm=native.SessionManager.create(cwd,sessionDir);
const now=Date.now();
for(let i=0;i<1200;i++){
 const message={role: i%2?'assistant':'user',timestamp:now+i,
  content:[{type:'text',text:'Synthetic long-lived project session turn '+i+'; requirement '+(i%17)+
  ' source checks and exact context are required before completion. '.repeat(5)}]};
 if(i%2) {
  Object.assign(message,{provider:'offline',model:'summary-fixture',api:'openai-completions',
   stopReason:'stop',usage:{input:0,output:0,totalTokens:0,
   cost:{input:0,output:0,total:0}}});
 }
 sm.appendMessage(message);
}
const originalFile=sm.getSessionFile();
assert(originalFile && fs.existsSync(originalFile));
const beforeBytes=fs.readFileSync(originalFile);
const beforeEntries=sm.getEntries().length;
const cred={async read(){return undefined},async list(){return[]},async modify(_id,fn){return fn(undefined)},async delete(){}};
const mr=await native.ModelRuntime.create({credentials:cred,modelsPath:null,
 allowModelNetwork:false,refreshOnCreate:false});
const model={provider:'fixture-offline',id:'synthetic',name:'Synthetic',
 api:'openai-completions',baseUrl:'http://127.0.0.1:19876/v1',
 reasoning:false,input:['text'],contextWindow:65536,maxTokens:16384,
 cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
const settings=native.SettingsManager.inMemory({
 defaultTools:[],defaultThinkingLevel:'off',
 extensions:[path.join(extDir,'large-session-receipt.mjs')],
 compaction:{enabled:true,reserveTokens:8192,keepRecentTokens:2000}
});
const {session,extensionsResult}=await native.createAgentSession({cwd,agentDir,sessionManager:sm,
 modelRuntime:mr,settingsManager:settings,model,
 noTools:'all',thinkingLevel:'off'});
assert.equal(extensionsResult?.extensions?.length, 1, 'Single test-only compaction hook must load');
assert.deepEqual(extensionsResult?.errors, [], 'Reject any extension startup failure');
let status='unknown',result,error;
try {result=await session.compact();status='success';}
catch(e){error=String(e);status='failure';}
const afterBytes=fs.readFileSync(originalFile);
const entries=sm.getEntries();
const receiptContent=fs.existsSync(receipt)?fs.readFileSync(receipt,'utf8'):'';
const report={status,error,root,original_file:originalFile,original_bytes:beforeBytes.length,
 after_bytes:afterBytes.length,append_only:afterBytes.subarray(0,beforeBytes.length).equals(beforeBytes),
 messages_before:beforeEntries,messages_after:entries.length,
 compaction_records:entries.filter(x=>x.type==='compaction').length,
 summary_saved:entries.some(x=>x.type==='compaction'&&x.summary===summary),
 event_receipt:receiptContent.trim().split(/\r?\n/).filter(Boolean).map(x=>JSON.parse(x)),
 model_calls:0,synthetic_summary:true,
 projection_summary:JSON.stringify(sm.buildSessionProjection()).includes('SYNTHETIC_COMPACT_SUMMARY')
};
fs.writeFileSync(path.join(root,'report.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));
if(session.dispose)await session.dispose();
assert.equal(status, 'success', error || 'Pi compact() failed');
assert.equal(beforeEntries, 1200);
assert.equal(report.append_only, true, 'Native session history must remain an unchanged prefix');
assert.equal(report.compaction_records, 1);
assert.equal(report.summary_saved, true);
assert.equal(report.projection_summary, true);
assert.ok(receiptContent.includes('"kind":"before"'));
assert.ok(receiptContent.includes('"kind":"after"'));
assert.equal(report.model_calls, 0, 'No network/model calls in this gate');
