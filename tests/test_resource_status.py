"""Source-level status guards; mocked ownership is not native service proof."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest
from unittest import mock

from harness import model_service_handoff as handoff, resource_status as status


class ResourceStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="resource-status-", dir=os.environ.get("RESOURCE_STATUS_TEST_ROOT"))
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / "home"
        self.home.mkdir()
        self.secret = "SYNTHETIC_PRIVATE_NONCE_DO_NOT_RETURN"
        self.config = {"schema": "agent-home/v1", "home": str(self.home), "apiKey": self.secret}
        self.binding = {"schema": handoff.SCHEMA, "home": str(self.home), "storage_root": str(self.home),
                        "base_url": "http://127.0.0.1:48111/v1", "model_id": "public-fixture",
                        "context": 32768, "max_output": 4096, "transport_profile": "generic-local",
                        "specification_sha256": "1" * 64, "environment_variable": handoff._variable(str(self.home))}
        self.write_config()
        self.entered = self.released = False

        @contextmanager
        def consumer(home):
            self.assertEqual(home, self.home)
            self.entered = True
            try:
                yield ()
            finally:
                self.released = True

        self.patch(status.home_entry, "consumer", side_effect=consumer)
        self.patch(status.hardware_probe, "ram_info", return_value={"total_gb": 64, "available_gb": 21.5})
        self.patch(status, "_cpu_count", return_value=8)
        self.patch(status, "_rss", return_value=123456)
        self.patch(status.model_service, "_home", return_value=self.home)
        self.native = self.patch(status.model_service, "status", return_value={"status": "stopped"})
        self.identity = self.patch(status.model_service, "_identity", return_value={})
        self.patch(status.model_service_handoff, "_home_lease", return_value={"lease_scope": "home_shared"})
        for name in ("start", "stop", "provision", "_mutation"):
            self.patch(status.model_service, name, side_effect=AssertionError("Status must not call mutation: " + name))

    def patch(self, target, name, **kwargs):
        patcher = mock.patch.object(target, name, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def write_config(self):
        (self.home / "home.json").write_text(json.dumps(self.config), encoding="utf-8")

    def owned(self, phase="running"):
        self.config["owned_model_service"] = self.binding
        self.write_config()
        self.native.return_value = {**self.binding, "status": phase, "pid": 12345, "start_ticks": "777",
                                    "api_key_file": self.secret, "Authorization": self.secret, "raw_request": self.secret}
        state = self.home / "state/model-service"
        state.mkdir(parents=True, exist_ok=True)
        (state / "service.json").write_text(json.dumps({"pid": 12345, "start_ticks": "777", "phase": phase, "nonce": self.secret}), encoding="utf-8")

    def test_attached_configuration_never_establishes_owned_process_or_occupancy(self):
        report = status.read_status(self.home)
        self.native.assert_not_called()
        self.assertEqual(report["service"]["status"], "unknown")
        self.assertEqual(report["service"]["mode"], "attached_or_unmanaged")
        self.assertIsNone(report["queue"]["busy"])
        self.assertNotIn("operator_release", report)
        self.assertEqual(report["host_snapshot"]["ram"]["available_gb"], 21.5)
        self.assertTrue(self.entered and self.released)
        self.assertNotIn(self.secret, json.dumps(report))

    def test_owned_running_and_starting_are_whitelisted_snapshots_not_fit_or_busy(self):
        for phase in ("running", "starting"):
            with self.subTest(phase=phase):
                self.owned(phase)
                before = (self.home / "home.json").read_bytes()
                report = status.read_status(self.home)
                self.assertEqual(report["service"]["status"], phase)
                self.assertEqual(report["service"]["rss_bytes"], 123456)
                self.assertTrue(report["service"]["live_process_verified"])
                self.assertEqual(report["fit"], "not_probed")
                self.assertEqual(report["queue"]["state"], "unknown")
                self.assertEqual(report["generative_requests"], 0)
                self.assertFalse(report["operator_release"]["executes"])
                self.assertEqual(report["operator_release"]["arguments"][-1], "stop")
                self.assertNotIn(self.secret, json.dumps(report))
                self.assertNotIn("api_key_file", json.dumps(report))
                self.assertEqual((self.home / "home.json").read_bytes(), before)
        self.assertEqual(self.identity.call_count, 4)

    def test_stopped_owned_binding_and_retained_setup_failure_are_not_current_job_claims(self):
        self.owned()
        self.native.return_value = {"status": "stopped"}
        path = self.home / "state/model-service/setup.json"
        path.write_text(json.dumps({"phase": "failed", "failed_stage": "installing_packages", "error": self.secret,
                                    "provider": {"apiKey": self.secret}}), encoding="utf-8")
        report = status.read_status(self.home)
        self.assertEqual(report["service"]["mode"], "owned_binding")
        self.assertFalse(report["service"]["live_process_verified"])
        self.assertTrue(report["setup"]["historical_record"])
        self.assertEqual(report["setup"]["current_job_or_recovery_success"], "not_established")
        self.assertEqual(report["setup"]["failed_stage"], "installing_packages")
        self.assertNotIn(self.secret, json.dumps(report))

    def test_route_lifetime_and_missing_lease_refuse_with_no_raw_error(self):
        for field, value in (("model_id", "foreign-model"), ("base_url", "http://127.0.0.1:48112/v1"),
                             ("specification_sha256", "2" * 64), ("start_ticks", "different")):
            with self.subTest(field=field):
                self.owned()
                self.native.return_value[field] = value
                report = status.read_status(self.home)
                self.assertEqual(report["service"]["status"], "held")
                self.assertNotIn("operator_release", report)
                self.assertNotIn(self.secret, json.dumps(report))
        self.owned()
        with mock.patch.object(status.model_service_handoff, "_home_lease", side_effect=ValueError(self.secret)):
            report = status.read_status(self.home)
        self.assertEqual(report["service"]["status"], "held")
        self.assertNotIn(self.secret, json.dumps(report))

    def test_retained_recovery_phase_is_not_hidden_by_stopped_or_running_status(self):
        self.owned()
        self.native.return_value = {"status": "stopped", "last_phase": "recovery_required"}
        report = status.read_status(self.home)
        self.assertTrue(report["service"]["needs_owner_inspection"])
        self.assertEqual(report["service"]["last_recorded_phase"], "recovery_required")
        self.owned()
        path = self.home / "state/model-service/service.json"
        current = json.loads(path.read_text(encoding="utf-8"))
        current["phase"] = "recovery_required"
        path.write_text(json.dumps(current), encoding="utf-8")
        report = status.read_status(self.home)
        self.assertEqual(report["service"]["status"], "held")
        self.assertNotIn("operator_release", report)

    def test_lifecycle_refusal_prevents_status_and_host_probe(self):
        with mock.patch.object(status.home_entry, "consumer", side_effect=ValueError("Pending lifecycle operation")):
            with self.assertRaisesRegex(ValueError, "Pending lifecycle"):
                status.read_status(self.home)
        self.native.assert_not_called()
        status.hardware_probe.ram_info.assert_not_called()

    def test_unknown_memory_and_new_gpu_admission_never_trigger_resource_changes(self):
        status.hardware_probe.ram_info.return_value = {"total_gb": float("nan"), "available_gb": float("inf")}
        report = status.read_status(self.home)
        self.assertEqual(report["host_snapshot"]["ram"], {"total_gb": None, "available_gb": None})
        self.assertFalse(report["host_snapshot"]["exclusive_allocation"])
        self.assertEqual(report["new_owned_gpu_start_admission"], "held_no_qualified_atomic_owner_route")

    def test_actual_capabilities_module_wait_projection_is_bounded_and_not_authority(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node22.13+ is required")
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if tuple(int(item) for item in version.lstrip("v").split(".")[:2]) < (22, 13):
            self.skipTest("Node22.13+ is required")
        script = r"""
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import {stripTypeScriptTypes} from 'node:module';
const context=vm.createContext({Buffer,process,console,structuredClone,URL});
const module=new vm.SourceTextModule(stripTypeScriptTypes(fs.readFileSync(process.argv[1],'utf8')),{context});
await module.link(async name=>{const values=name==='typebox'?{Type:new Proxy({},{get:()=>()=>({})})}:await import(name);
 return new vm.SyntheticModule(Object.keys(values),function(){for(const[k,v]of Object.entries(values))this.setExport(k,v);},{context});});await module.evaluate();
const row=(customType,data)=>({type:'custom',customType,data});const secret='SYNTHETIC_SECRET_IN_PRIVATE_WAIT_REASON';
const wait={root:'/owned/project',id:'wait1',task:'task1',kind:'resource',status:'waiting',reason:secret,trigger:secret};
const rows=[row('pi-kanban-selection/v1',{project:{root:'/owned/project'}}),row('pi-request-work-state/v1',{progress:7,mode:'paused',task_waits:[wait,{...wait,id:'foreign',root:'/foreign'},{...wait,id:'user',kind:'user'},{...wait,id:'resolved',status:'resolved'}]})];
const before=JSON.stringify(rows);let report=module.namespace.resourceWaits(rows);assert.equal(report.count,1);assert.equal(report.rows[0].wait_id,'wait1');
assert.equal(JSON.stringify(rows),before);assert.ok(!JSON.stringify(report).includes(secret));assert.match(report.limits,/does not verify/);
rows[1].data.task_waits=Array.from({length:14},(_,i)=>({...wait,id:'wait'+i}));report=module.namespace.resourceWaits(rows);
assert.equal(report.count,14);assert.equal(report.rows.length,8);assert.equal(report.truncated,true);assert.equal(module.namespace.resourceWaits([]).count,0);
"""
        file = Path(__file__).resolve().parents[1] / "adapters/pi/project-workflow/agent-capabilities.ts"
        result = subprocess.run([node, "--experimental-vm-modules", "--input-type=module", "-e", script, str(file)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
