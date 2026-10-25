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
import { createHash } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import { EventEmitter } from 'node:events';
import vm from 'node:vm';
const requests = [], tasks = new Map([['task-1', { id:'task-1',status:'ready',parents:[] }],
  ['task-2', { id:'task-2',status:'ready',parents:[] }]]);
let board = 'board-1';
const spawn = () => {
  const child = new EventEmitter();
  child.stdout = new EventEmitter(); child.stderr = new EventEmitter(); child.stdin = new EventEmitter();
  child.kill = () => {};
  child.stdin.end = raw => queueMicrotask(() => {
    const request = JSON.parse(raw); requests.push(request);
    let result = {};
    if (request.action === 'project_admit') result = { project_root:request.project_root,
      identity:{ project_id:'project-1',board_id:board } };
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
  'node:crypto':{createHash}, 'node:fs':{readFileSync},
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
const discover = async(memory='native') => {
  await fire('tool_result',{toolName:'agent_capabilities',details:{ok:true,snapshot:{}}});
  await fire('tool_result',{toolName:'system_tool_query',details:{ok:true,results:[]}});
  if(memory==='native') await fire('tool_result',{toolName:'mcp__mempalace__mempalace_search'});
  else await fire('tool_result',{toolName:'validated_memory_query',details:{schema:'validated-memory-query/v1',results:[],reason:memory==='sensitive'?'sensitive_query':'no_current_provenanced_result'}});
  await fire('tool_result',{toolName:'project_knowledge_query',details:{ok:true}});
};
const admit = () => invoke('project_admit',{project_root:'/project'});
const execute = () => fire('tool_call',{toolName:'workflow_step'});
assert.equal((await execute()).block,true);
await admit(); await invoke('kanban_create',{title:'Owner-authorized task'}); await discover();
assert.equal(await execute(),undefined); // No adviser call or consultation-created card.
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
        result = subprocess.run(
            [node, "--experimental-vm-modules", "--input-type=module", "-e", script],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("selection contract passed", result.stdout)

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
