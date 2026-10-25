import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "adapters" / "pi" / "project-workflow"


def load(name):
    spec = importlib.util.spec_from_file_location(name, WORKFLOW / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(WORKFLOW))
project_identity = load("project_identity")
project_knowledge = load("project_knowledge")
project_skill_candidate = load("project_skill_candidate")
tool_knowledge = load("tool_knowledge")


class PiProjectWorkflowTests(unittest.TestCase):
    def test_native_selection_without_adviser_and_reload_refusals(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for the Pi extension contract test")
        version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
        if tuple(int(part) for part in version.lstrip("v").split(".")[:2]) < (22, 13):
            self.skipTest("Node 22.13+ is required to strip TypeScript for this contract test")
        # Execute the complete extension, with explicit native-API/backend fixtures.
        # This tests coordinator behavior; it does not qualify a live Pi/Hermes host.
        script = r'''
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import { EventEmitter } from 'node:events';
import vm from 'node:vm';
const requests = [], tasks = new Map([['task-1', { id:'task-1',status:'ready',parents:[] }],
  ['task-2', { id:'task-2',status:'ready',parents:[] }]]);
let board = 'board-1', createFailure = false, createMalformed = false, createPending = false, ownerCloses = 0;
const creations = [];
const spawn = (_python, argv = [], options = {}) => {
  const child = new EventEmitter();
  child.stdout = new EventEmitter(); child.stderr = new EventEmitter(); child.stdin = new EventEmitter();
  child.kill = () => {};
  const creation = argv.find(value => value.startsWith('--name='));
  if (creation) {
    const name = creation.slice('--name='.length);
    creations.push({name,argv,options});
    child.stdin.end = () => { ownerCloses += 1; };
    if (!createPending) queueMicrotask(() => {
      const root = createMalformed ? '/wrong-project' : join(process.env.AGENT_HOME,'projects',name);
      const value = createFailure ? {schema:'pi-kanban-result/v1',ok:false,error:'Synthetic partial creation failure'}
        : {schema:'pi-kanban-result/v1',ok:true,action:'project_create',result:{project_root:root,
          identity:{project_id:'created-'+name,board_id:'board-'+name}},limits:['Fixture only']};
      child.stdout.emit('data',Buffer.from(JSON.stringify(value))); child.emit('close',createFailure?2:0);
    });
    return child;
  }
  child.stdin.end = raw => queueMicrotask(() => {
    const request = JSON.parse(raw); requests.push(request);
    let result = {};
    if (request.action === 'project_admit') {
      const managed = request.project_root.startsWith(join(process.env.AGENT_HOME,'projects'));
      const name = managed ? request.project_root.split(/[\\/]/).at(-1) : undefined;
      result = { project_root:request.project_root,
        identity:{ project_id:managed?'created-'+name:'project-1',board_id:managed?'board-'+name:board } };
    }
    if (request.action === 'show') {
      const task = tasks.get(request.task_id);
      if (!task) { child.stdout.emit('data',Buffer.from(JSON.stringify({schema:'pi-kanban-result/v1',ok:false,error:'missing card'}))); child.emit('close',1); return; }
      result = { task:{id:task.id,status:task.status},parents:task.parents };
    }
    if (request.action === 'create') result = { task:{id:'task-1',status:'ready'} };
    child.stdout.emit('data',Buffer.from(JSON.stringify({schema:'pi-kanban-result/v1',ok:true,result})));
    child.emit('close',0);
  });
  return child;
};
const context = vm.createContext({ Buffer,process,setTimeout,clearTimeout,console });
const type = new Proxy({}, {get:() => () => ({})});
const { projectKanbanReply } = await import(process.env.PI_TEST_PROJECTOR);
const dependencies = {
  typebox:{Type:type}, 'node:child_process':{spawn},
  'node:crypto':{createHash}, 'node:fs':{readFileSync}, 'node:path':{join},
  '../intake/request-intake-138.ts': {registerRequestIntake() { /* Separate native intake qualification. */ }},
  '../context/project-context.ts': {registerProjectContext() { /* Separate native context qualification. */ }},
  './kanban-reply-projector.mjs': {projectKanbanReply}
};
const source = stripTypeScriptTypes(readFileSync(process.env.PI_TEST_EXTENSION,'utf8'));
const module = new vm.SourceTextModule(source,{context});
await module.link(specifier => {
  const exports = dependencies[specifier]; assert.ok(exports,'Unexpected import '+specifier);
  return new vm.SyntheticModule(Object.keys(exports),function(){for(const [key,value] of Object.entries(exports)) this.setExport(key,value);},{context});
});
await module.evaluate();
const branch = [], hooks = new Map(), tools = new Map();
const pi = {
  on(name,handler) { if(!hooks.has(name))hooks.set(name,[]); hooks.get(name).push(handler); },
  registerTool(tool){ tools.set(tool.name,tool); },
  appendEntry(customType,data){ branch.push({type:'custom',customType,data:structuredClone(data)}); }
};
module.namespace.default(pi);
const ctx = {sessionManager:{getBranch:()=>branch,getSessionId:()=> 'session-1'},ui:{notify(){}}};
const fire = async(name,event={}) => {let result;for(const h of hooks.get(name)??[]) result = await h(event,ctx)??result;return result;};
const invoke = async(name,input) => {
  const response = await tools.get(name).execute('call-'+name,input,undefined);
  await fire('tool_result',{toolName:name,toolCallId:'call-'+name,input,...response});
  return response;
};
// Pi1.4 retains the native MCP CallToolResult in structuredContent. MemPalace
// serializes its search envelope as one JSON text block inside that result.
const nativeSearchText = text => {
  const content = [{type:'text',text}];
  return {toolName:'mcp__mempalace__mempalace_search',content,
    details:{server:'mempalace',tool:'mempalace_search'},structuredContent:{content}};
};
const nativeSearch = value => nativeSearchText(JSON.stringify(value));
const discover = async(memory='native') => {
  await fire('tool_result',{toolName:'agent_capabilities',details:{ok:true,snapshot:{}}});
  await fire('tool_result',{toolName:'system_tool_query',details:{ok:true,results:[]}});
  if(memory==='native') await fire('tool_result',nativeSearch({query:'fixture',filters:{},total_before_filter:0,results:[]}));
  else if(memory!=='none') await fire('tool_result',{toolName:'validated_memory_query',details:{schema:'validated-memory-query/v1',results:[],reason:memory==='sensitive'?'sensitive_query':'no_current_provenanced_result'}});
  await fire('tool_result',{toolName:'project_knowledge_query',details:{ok:true}});
};
const admit = () => invoke('project_admit',{project_root:'/project'});
const execute = () => fire('tool_call',{toolName:'workflow_step'});
assert.equal((await execute()).block,true);
await admit(); await invoke('kanban_create',{title:'Owner-authorized task'});
let held = await execute();
for (const name of ['agent_capabilities','system_tool_query','validated_memory_query','project_knowledge_query'])
  assert.ok(held.reason.includes(name),'all unobserved prerequisites must be actionable: '+name);
await fire('tool_result',{toolName:'agent_capabilities',details:{ok:true,snapshot:{}}});
held = await execute();
assert.equal(held.block,true);
assert.equal(held.reason.includes('agent_capabilities'),false,'do not repeat an already completed capability observation');
assert.ok(held.reason.includes('system_tool_query'));
await fire('tool_result',{toolName:'system_tool_query',details:{ok:true,results:[]}});
held = await execute();
assert.equal(held.reason.includes('system_tool_query'),false);
assert.ok(held.reason.includes('validated_memory_query'));
await fire('tool_result',nativeSearch({query:'fixture',filters:{},total_before_filter:0,results:[]}));
held = await execute();
assert.equal(held.reason.includes('validated_memory_query'),false);
assert.ok(held.reason.includes('project_knowledge_query'));
await fire('tool_result',{toolName:'project_knowledge_query',details:{ok:true}});
assert.equal(await execute(),undefined);
await admit(); held = await execute();
assert.ok(held.reason.includes('agent_capabilities'),'readmission must invalidate completed discovery');
await discover();
assert.equal(await execute(),undefined); // No adviser call or consultation-created card.
const emptySearch = nativeSearch({query:'fixture',filters:{},total_before_filter:0,results:[]});
const memoryCases = [
  ['semantic error without isError',nativeSearch({error:'wing contains invalid path characters'}),false],
  ['error envelope with results array',nativeSearch({error:'Search error: synthetic failure',results:[]}),false],
  ['malformed native JSON',nativeSearchText('{"results": ['),false],
  ['unknown payload',nativeSearch({query:'fixture',count:0}),false],
  ['null payload',nativeSearch(null),false],
  ['array payload',nativeSearch([]),false],
  ['outer MCP error',{...emptySearch,isError:true},false],
  ['raw MCP error',{...emptySearch,structuredContent:{...emptySearch.structuredContent,isError:true}},false],
  ['successful empty search',emptySearch,true],
  ['document text containing error',nativeSearch({query:'fixture',results:[
    {id:'drawer-1',content:'Stored code example: {"error":"synthetic reported error"}'}]}),true],
  ['full raw result survives model-view limit',{...emptySearch,content:[{type:'text',text:'[limited model-facing output]'}]},true],
  ['native text fallback without structured result',{...emptySearch,structuredContent:undefined},true],
];
for (const [label,event,accepted] of memoryCases) {
  await fire('session_start'); await discover('none');
  assert.equal((await execute()).block,true,label+': missing memory still holds admission');
  await fire('tool_result',event);
  const result = await execute();
  if(accepted) assert.equal(result,undefined,label+': observed search should satisfy readiness');
  else assert.equal(result?.block,true,label+': failed/unknown search must leave readiness closed');
}
console.log('canonical memory guard cases passed: '+memoryCases.length);
await fire('session_start'); await discover('sensitive'); assert.equal((await execute()).block,true);
await discover('validated'); assert.equal(await execute(),undefined); // An empty reviewed registry is a valid observed abstention.
await fire('input',{source:'interactive',text:'Continue this task'});
assert.equal(await execute(),undefined); // A new input preserves navigation.
await invoke('kanban_create',{title:'Another queued task'});
assert.equal(branch.at(-1).data.task.cardId,'task-1'); // Creation does not replace selection.
await invoke('kanban_select',{task_id:'task-2'});
assert.equal(branch.at(-1).data.task.cardId,'task-2');
await fire('session_start');
assert.equal((await execute()).block,true); // Reload invalidates discovery readiness.
await discover(); assert.equal(await execute(),undefined);
tasks.get('task-2').status='done'; assert.equal((await execute()).block,true);
tasks.get('task-2').status='ready'; tasks.get('task-2').parents=['task-1']; tasks.get('task-1').status='blocked';
assert.equal((await execute()).block,true); // Stored prerequisites are checked live.
tasks.get('task-1').status='done'; assert.equal(await execute(),undefined);
board='different-board'; await fire('session_tree'); await discover();
assert.equal((await execute()).block,true); // Stale board identity cannot restore permission.
board='board-1'; await admit(); await invoke('kanban_select',{task_id:'task-2'}); tasks.delete('task-2');
await fire('session_start'); await discover(); assert.equal((await execute()).block,true);
assert.equal(requests.filter(x=>x.action==='consultation_admit').length,0);
console.log('selection contract passed');
// Pure coordinator fixture: no Git/helper/Hermes deployment is claimed here.
tasks.get('task-1').status='ready'; await admit(); await invoke('kanban_select',{task_id:'task-1'}); await discover();
assert.equal(await execute(),undefined);
assert.equal(await fire('tool_call',{toolName:'project_create',input:{name:'new-one'}}),undefined);
assert.equal((await execute()).block,true,'creation starts with old selection held');
const created = await invoke('project_create',{name:'new-one'});
assert.equal(created.isError,undefined);
let selected = branch.at(-1).data;
assert.equal(selected.project.root,join(process.env.AGENT_HOME,'projects','new-one'));
assert.equal(selected.task,null); assert.equal(selected.boardAdmissionFailed,false);
assert.equal((await execute()).block,true,'creation never selects a ready task');
tasks.set('new-task',{id:'new-task',status:'ready',parents:[]}); await invoke('kanban_select',{task_id:'new-task'});
const missing = (await execute()).reason;
for (const name of ['agent_capabilities','system_tool_query','validated_memory_query','project_knowledge_query']) assert.ok(missing.includes(name));
createFailure=true; assert.equal((await invoke('project_create',{name:'partial'})).isError,true); createFailure=false;
selected=branch.at(-1).data; assert.equal(selected.project,null);assert.equal(selected.task,null);assert.equal(selected.boardAdmissionFailed,true);
const beforeExtra=creations.length;
assert.equal((await invoke('project_create',{name:'extra',project_root:'/arbitrary'})).isError,true);
assert.equal(creations.length,beforeExtra,'unknown args refuse before helper');
createMalformed=true;assert.equal((await invoke('project_create',{name:'wrong-root'})).isError,true);createMalformed=false;
createPending=true;
const owner = new AbortController(), pending = tools.get('project_create').execute('cancelled',{name:'cancelled'},owner.signal);
owner.abort();assert.equal((await pending).isError,true);createPending=false;
assert.equal(creations.at(-1).options.env.PI_TASK_TIMEOUT,'90');assert.ok(ownerCloses>=4);
await admit();assert.equal(branch.at(-1).data.project.root,'/project','external adoption remains available');
assert.equal(requests.at(-1).initialize,undefined,'default adoption does not initialize');
console.log('project creation coordinator cases passed');
'''
        adapter = WORKFLOW / "pi_kanban.py"
        env = {
            **os.environ,
            "PI_PROJECT_KANBAN_PYTHON": sys.executable,
            "PI_PROJECT_KANBAN_ADAPTER": str(adapter),
            "PI_PROJECT_KANBAN_ADAPTER_SHA256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
            "PI_TEST_EXTENSION": str(WORKFLOW / "pi-kanban.ts"),
            "PI_TEST_PROJECTOR": (WORKFLOW / "kanban-reply-projector.mjs").as_uri(),
        }
        selected_root = os.environ.get("PROJECT_CREATE_TEST_ROOT")
        if selected_root is None and os.name == "nt" and Path("E:/").is_dir():
            selected_root = "E:/"
        managed = tempfile.TemporaryDirectory(prefix="project-create-vm-", dir=selected_root)
        self.addCleanup(managed.cleanup)
        managed_home = Path(managed.name).resolve() / "home"
        helper = managed_home / "runtime/adapters/pi/project-workflow/project_create.py"
        helper.parent.mkdir(parents=True)
        helper.write_text("# Explicit VM transport fixture only\n", encoding="utf-8")
        manifest = managed_home / "runtime/runtime-manifest.json"
        manifest.write_text(json.dumps({"files": [{"path": "adapters/pi/project-workflow/project_create.py",
                                                 "sha256": hashlib.sha256(helper.read_bytes()).hexdigest()}]}), encoding="utf-8")
        (managed_home / "home.json").write_text(json.dumps({"schema": "agent-home/v1", "home": str(managed_home),
                                                          "runtime_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}), encoding="utf-8")
        env.update(AGENT_HOME=str(managed_home), AGENT_HOME_PYTHON=sys.executable)
        result = subprocess.run(
            [node, "--experimental-vm-modules", "--input-type=module", "-e", script],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("canonical memory guard cases passed: 12", result.stdout)
        self.assertIn("selection contract passed", result.stdout)
        self.assertIn("project creation coordinator cases passed", result.stdout)

    def test_export_has_no_private_host_binding(self):
        forbidden = (r"/home/[^/\s]+", r"[A-Za-z]:\\Users\\[^\\\s]+",
                     r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+\b")
        for path in WORKFLOW.iterdir():
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for value in forbidden:
                    self.assertNotRegex(text, value, f"private binding in {path.name}")

    def test_workspace_initializer_is_source_pinned(self):
        initializer = WORKFLOW / "init_workspace.py"
        self.assertEqual(
            hashlib.sha256(initializer.read_bytes()).hexdigest(),
            "1cd480bd692001fa8d56775496d723c6ff937c1b306ddd66c1c6f343ec90c6b9",
        )

    def test_hyphenated_skill_candidate_is_immutable_and_searchable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            identity, created = project_identity.initialize_identity(
                root, native_authority="test fixture only"
            )
            self.assertTrue(created)
            closeout_path = root / ".icm" / "workspace" / "wiki" / "task-closeouts" / "task-1.json"
            closeout_path.parent.mkdir(parents=True)
            closeout = {
                "schema": "pi-project-closeout/v1",
                "project_id": identity["project_id"],
                "task_id": "task-1",
                "authority": "verified_lesson_guidance_only",
                "receipt": {
                    "status": "accepted",
                    "authority_cap": "tested",
                    "sha256": "a" * 64,
                },
            }
            closeout_bytes = (json.dumps(closeout, sort_keys=True) + "\n").encode()
            closeout_path.write_bytes(closeout_bytes)
            request = {
                "name": "verified-project-closeout",
                "description": "Reuse an accepted project closeout.",
                "closeout_path": str(closeout_path),
                "closeout_sha256": hashlib.sha256(closeout_bytes).hexdigest(),
                "triggers": ["A verified project task needs reusable guidance."],
                "steps": ["Read the source closeout and its receipt binding."],
                "verification": ["Confirm the closeout and skill hashes."],
                "stop_conditions": ["Stop when the source closeout differs."],
            }
            result = project_skill_candidate.compile_candidate(root, request)
            self.assertEqual(result["promotion_state"], "project_local_candidate")
            self.assertEqual(result["authority"], "guidance_only")
            query = project_knowledge.query(root, "verified-project-closeout", 10)
            paths = {item["path"] for item in query["results"]}
            self.assertIn(".icm/skills/verified-project-closeout/SKILL.md", paths)
            self.assertIn(".icm/skills/verified-project-closeout/candidate.json", paths)
            with self.assertRaises(project_skill_candidate.SkillCandidateError):
                project_skill_candidate.compile_candidate(
                    root, {**request, "description": "Changed content."}
                )

    def test_runtime_configuration_uses_explicit_hashes(self):
        extension = (WORKFLOW / "everyday-workflow.ts").read_text(encoding="utf-8")
        helper = (WORKFLOW / "everyday_workflow.py").read_text(encoding="utf-8")
        self.assertIn("configuration.runtime_manifest_sha256", extension)
        self.assertIn("configuration.engine_sha256", extension)
        self.assertNotIn("ENGINE_SHA =", helper)
        self.assertNotIn("RUNTIME_SHA =", helper)

    def test_system_tool_catalog_is_hash_bound_and_searchable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "capabilities.jsonl"
            source.write_text(
                json.dumps({"name": "browser-probe", "kind": "script", "when_to_use": "Inspect browser pages", "path": "scripts/browser.py"}) + "\n",
                encoding="utf-8",
            )
            database = root / "tools.db"
            built = tool_knowledge.build(database, [source])
            result = tool_knowledge.query(database, "browser inspect", 5)
            self.assertEqual(result["results"][0]["name"], "browser-probe")
            self.assertEqual(result["results"][0]["source_sha256"], built["sources"][0]["sha256"])
            self.assertEqual(tool_knowledge.status(database)["manifest_sha256"], built["manifest_sha256"])

    def test_system_tool_catalog_marks_retired_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "history.jsonl"
            source.write_text(
                json.dumps({"name": "old-graph", "kind": "script", "description": "temporal knowledge graph", "path": "old.py"}) + "\n",
                encoding="utf-8",
            )
            lifecycle = root / "lifecycle.jsonl"
            lifecycle.write_text(
                json.dumps({"name": "old-retirement", "kind": "tool-lifecycle", "target_path": "old.py", "lifecycle": "retired", "description": "retired temporal graph"}) + "\n",
                encoding="utf-8",
            )
            database = root / "tools.db"
            tool_knowledge.build(database, [source, lifecycle])
            result = tool_knowledge.query(database, "temporal knowledge graph", 5)["results"][0]
            self.assertEqual(result["lifecycle"], "retired")
            self.assertFalse(result["usable_for_planning"])


if __name__ == "__main__":
    unittest.main()
