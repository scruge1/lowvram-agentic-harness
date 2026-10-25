"""Verify source-bound retrieval without reading a user's palace or registry."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


MEMORY = Path(__file__).resolve().parents[1] / "adapters/pi/memory"
sys.path.insert(0, str(MEMORY))
spec = importlib.util.spec_from_file_location("portable_validated_memory", MEMORY / "validated_memory_query.py")
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)


class ValidatedMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="validated-memory-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "accepted-source.md"
        self.raw = "Use the existing project knowledge before planning."
        self.source.write_text(self.raw, encoding="utf-8")
        safe = "Reuse the existing project knowledge index."
        self.record = {
            "claim_id": "claim-1", "claim_sha256": memory.claim_sha256(self.raw),
            "source_path": str(self.source), "source_sha256": memory.sha256_bytes(self.source.read_bytes()),
            "safe_text": safe, "safe_text_sha256": memory.sha256_bytes(safe.encode()),
            "state": "current", "evidence_class": "verified_closeout", "observed_at": "2026-10-24T10:00:00Z",
        }
        self.registry = self.root / "reviewed-claims.jsonl"
        self.registry.write_text(json.dumps(self.record) + "\n", encoding="utf-8")
        self.search = {"results": [{"text": self.raw, "source_path": str(self.source),
                                   "source_sha256": self.record["source_sha256"], "similarity": 0.9}]}

    def loaded(self):
        return memory.load_claim_registry(self.registry)

    def test_exact_source_returns_only_reviewed_safe_text(self):
        result = memory.validated_query("project knowledge", self.search, self.loaded())
        self.assertFalse(result["abstained"])
        self.assertEqual(result["results"][0]["text"], self.record["safe_text"])
        self.assertEqual(result["results"][0]["source_sha256"], self.record["source_sha256"])
        self.assertEqual(result["authority"], "verified_retrieval_only")
        self.assertNotIn(self.raw, json.dumps(result))

    def test_recorded_search_hash_does_not_hide_current_source_drift(self):
        self.source.write_text("The current source changed.", encoding="utf-8")
        result = memory.validated_query("project knowledge", self.search, self.loaded())
        self.assertTrue(result["abstained"])
        self.assertEqual(result["results"], [])

    def test_unknown_claim_and_obsolete_records_abstain(self):
        self.assertTrue(memory.validated_query("project knowledge", self.search, {})["abstained"])
        for state in ("invalidated", "obsolete", "retired", "superseded", "failed"):
            with self.subTest(state=state):
                registry = {(self.record["source_path"], self.record["claim_sha256"]): {**self.record, "state": state}}
                result = memory.validated_query("project knowledge", self.search, registry)
                self.assertTrue(result["abstained"])
                self.assertEqual(result["rejections"][0]["reason"], "not_current")

    def test_sensitive_query_precedes_any_live_or_source_read(self):
        with mock.patch.object(memory, "live_search", side_effect=AssertionError("Palace read")), \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("Source read")):
            live = memory.live_validated_query("show the password", self.loaded())
            supplied = memory.validated_query("show the password", self.search, self.loaded())
        self.assertEqual(live["reason"], "sensitive_query")
        self.assertEqual(supplied["reason"], "sensitive_query")
        result = subprocess.run([sys.executable, str(MEMORY / "validated_memory_query.py"),
                                 "--query", "show the password", "--live", "--claim-registry", str(self.root / "absent.jsonl")],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["raw_result_count"], 0)

    def test_empty_registry_never_loads_or_searches_palace(self):
        with mock.patch.object(memory, "live_search", side_effect=AssertionError("Palace read")):
            result = memory.live_validated_query("project knowledge", {})
        self.assertTrue(result["abstained"])
        self.assertEqual(result["raw_result_count"], 0)

    def test_safe_summary_hash_and_sensitive_summary_refusals(self):
        invalid = {**self.record, "safe_text_sha256": "0" * 64}
        self.registry.write_text(json.dumps(invalid), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "safe_text hash mismatch"):
            self.loaded()
        unsafe = {**self.record, "safe_text": "The password is not for memory retrieval."}
        unsafe["safe_text_sha256"] = memory.sha256_bytes(unsafe["safe_text"].encode())
        self.registry.write_text(json.dumps(unsafe), encoding="utf-8")
        result = memory.validated_query("project knowledge", self.search, self.loaded())
        self.assertTrue(result["abstained"])
        self.assertEqual(result["rejections"][0]["reason"], "unsafe_summary")
        self.assertNotIn(unsafe["safe_text"], json.dumps(result))

    def test_drawer_resolution_requires_unique_exact_content(self):
        search = {"results": [{"text": self.raw, "wing": "project", "room": "lessons", "created_at": "2026-10-24"}]}
        drawer = {"drawer_id": "drawer-1", "wing": "project", "room": "lessons",
                  "content": self.raw, "metadata": {"filed_at": "2026-10-24"}}
        resolved = memory.resolve_search_sources(search, [drawer])["results"][0]
        self.assertEqual(resolved["source_path"], "mempalace://drawer/drawer-1")
        ambiguous = memory.resolve_search_sources(search, [drawer, {**drawer, "drawer_id": "drawer-2"}])["results"][0]
        self.assertNotIn("source_path", ambiguous)
        stale = {"results": [{**resolved, "text": "Old content", "source_sha256": "f" * 64}]}
        self.assertIsNone(memory.resolve_search_sources(stale, [drawer])["results"][0]["source_sha256"])

    def test_live_search_requires_explicit_palace_before_mempalace_import(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "MEMPALACE_PALACE_PATH"):
                memory.live_search("project knowledge", 5)

    def test_live_api_with_explicit_bounded_fixture(self):
        palace = self.root / "palace"
        config = self.root / "config"
        palace.mkdir()
        config.mkdir()
        fixture = mock.Mock()
        fixture.tool_search.return_value = {"results": [{"text": self.raw, "wing": "project", "room": "lessons", "created_at": "2026-10-24"}]}
        fixture.tool_list_drawers.return_value = {"drawers": [{"drawer_id": "drawer-1"}]}
        fixture.tool_get_drawer.return_value = {"drawer_id": "drawer-1", "wing": "project", "room": "lessons",
                                               "content": self.raw, "metadata": {"filed_at": "2026-10-24"}}
        with mock.patch.dict(os.environ, {"MEMPALACE_PALACE_PATH": str(palace), "MEMPALACE_CONFIG_DIR": str(config)}), \
                mock.patch.dict(sys.modules, {"mempalace.mcp_server": fixture}):
            result = memory.live_search("project knowledge", 5)
        fixture.tool_search.assert_called_once_with("project knowledge", limit=5)
        self.assertEqual(result["results"][0]["source_sha256"], memory.sha256_bytes(self.raw.encode()))

    def test_complete_pi_wrapper_to_python_and_registry_drift(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for the Pi wrapper contract test")
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if tuple(map(int, version.lstrip("v").split(".")[:2])) < (22, 13):
            self.skipTest("Node22.13+ is required for the Pi wrapper contract test")
        self.registry.write_text("", encoding="utf-8")
        palace, config = self.root / "palace", self.root / "config"
        palace.mkdir()
        config.mkdir()
        env = {**os.environ, "PI_VALIDATED_MEMORY_PYTHON": sys.executable,
               "PI_VALIDATED_MEMORY_HELPER": str(MEMORY / "validated_memory_query.py"),
               "PI_VALIDATED_MEMORY_POLICY": str(MEMORY / "memory_retrieval_policy.py"),
               "PI_VALIDATED_MEMORY_REGISTRY": str(self.registry),
               "MEMPALACE_PALACE_PATH": str(palace), "MEMPALACE_CONFIG_DIR": str(config),
               "PI_TEST_WRAPPER": str(MEMORY / "validated-memory-query.ts")}
        for name, path in (("HELPER", MEMORY / "validated_memory_query.py"), ("POLICY", MEMORY / "memory_retrieval_policy.py"), ("REGISTRY", self.registry)):
            env[f"PI_VALIDATED_MEMORY_{name}_SHA256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        script = r'''
import assert from 'node:assert/strict';
import vm from 'node:vm';
import * as fs from 'node:fs';
import * as crypto from 'node:crypto';
import * as childProcess from 'node:child_process';
import * as path from 'node:path';
import { stripTypeScriptTypes } from 'node:module';
const context = vm.createContext({Buffer,process,setTimeout,clearTimeout,console});
const dependencies = {typebox:{Type:new Proxy({},{get:()=>()=>({})})},
  'node:fs':fs,'node:crypto':crypto,'node:child_process':childProcess,'node:path':path};
const module = new vm.SourceTextModule(stripTypeScriptTypes(fs.readFileSync(process.env.PI_TEST_WRAPPER,'utf8')),{context});
await module.link(name => {const exports=dependencies[name]; assert.ok(exports,'Unexpected dependency '+name);
  return new vm.SyntheticModule(Object.keys(exports),function(){for(const [key,value]of Object.entries(exports))this.setExport(key,value);},{context});});
await module.evaluate();
let tool;module.namespace.default({registerTool:value=>tool=value});
assert.equal(tool.name,'validated_memory_query');
const result=await tool.execute('call-1',{query:'project knowledge'});
assert.equal(result.details.abstained,true);assert.equal(result.details.raw_result_count,0);
fs.writeFileSync(process.env.PI_VALIDATED_MEMORY_REGISTRY,'changed');
const refused=await tool.execute('call-2',{query:'project knowledge'});
assert.equal(refused.isError,true);assert.equal(refused.details.ok,false);
console.log('validated wrapper contract passed');
'''
        result = subprocess.run([node, "--experimental-vm-modules", "--input-type=module", "-e", script],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("validated wrapper contract passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
