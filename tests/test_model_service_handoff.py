"""Read-only handoff guards; status fixtures do not claim deployed ownership.

Optional installed-Pi test parses the generated provider and intercepts actual
native serialization before network. It starts no service and requests no model.
"""
import contextlib
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import home_entry, home_lifecycle, model_service
from harness import model_service_handoff as handoff


@unittest.skipUnless(sys.platform == "linux", "Owned native service handoff is Linux-only")
class HandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="model-handoff-", dir=os.environ.get("MODEL_SERVICE_TEST_ROOT"))
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "future Hôme β"
        self.root = Path(str(self.home) + "-runtimes")
        self.root.mkdir()
        (self.root / "bootstrap-owner").write_text("agent-home-bootstrap/v1:" + str(self.home) + "\n")
        self.state_path = self.root / "state/model-service/service.json"
        self.route = {"schema": model_service.SCHEMA, "status": "running", "home": str(self.home), "storage_root": str(self.root),
                      "pid": 12345, "start_ticks": "67890", "specification_sha256": "1" * 64,
                      "base_url": "http://127.0.0.1:49991/v1", "model_id": "owned-fixture-model", "model": "owned-fixture-model",
                      "context": 4096, "max_output": 32, "transport_profile": "generic"}
        self.rotate("a", "2")
        patch = mock.patch.object(model_service, "status", side_effect=lambda *_: dict(self.route))
        self.status = patch.start()
        self.addCleanup(patch.stop)

    def rotate(self, value, directory):
        key = self.root / "state/model-service" / ("run-" + directory * 32) / "api-key"
        key.parent.mkdir(parents=True)
        key.write_text(value * 64 + "\n")
        key.chmod(0o600)
        self.route["api_key_file"] = str(key)
        self.state = {"schema": model_service.SCHEMA, "home": str(self.home), "storage_root": str(self.root),
                      "pid": self.route["pid"], "start_ticks": self.route["start_ticks"], "key_file": str(key),
                      "specification_sha256": self.route["specification_sha256"], "model": self.route["model_id"],
                      "port": int(self.route["base_url"].split(":")[-1].split("/")[0]),
                      "nonce_sha256": hashlib.sha256(key.read_bytes()).hexdigest()}
        self.save_state()
        self.key = key

    def save_state(self):
        self.state_path.write_text(json.dumps(self.state) + "\n")

    def test_capture_is_serializable_without_key_and_uses_native_env_reference(self):
        value = handoff.capture(self.home)
        encoded = json.dumps(value)
        self.assertNotIn("a" * 64, encoded)
        name = value["binding"]["environment_variable"]
        self.assertTrue(name.startswith("AGENT_HOME_MODEL_KEY_"))
        self.assertEqual(value["provider"]["apiKey"], "$" + name)
        self.assertNotIn("!", value["provider"]["apiKey"])
        self.assertEqual(value["provider"]["baseUrl"], self.route["base_url"])
        self.assertEqual(value["binding"]["transport_profile"], "generic-local")
        self.assertEqual(value["provider"]["models"][0]["maxTokens"], 32)
        self.assertEqual(value["receipt"]["lease_scope"], "pre_home")
        self.assertFalse(self.home.exists())

    def test_launch_reads_fresh_nonce_at_same_owned_endpoint_and_preserves_os_home(self):
        binding = handoff.capture(self.home)["binding"]
        self.route.update(pid=12346, start_ticks="67891")
        self.rotate("b", "3")
        launch = handoff.launch_environment(self.home, binding)
        self.assertNotIn("b" * 64, repr(launch))
        child = launch.apply({"PATH": "/usr/bin:/bin", "HOME": str(Path.home())})
        self.assertEqual(child[binding["environment_variable"]], "b" * 64)
        self.assertEqual(child["HOME"], str(Path.home()))
        self.assertEqual(launch.receipt["service_pid"], 12346)
        self.assertNotIn("b" * 64, json.dumps(launch.receipt))
        with self.assertRaisesRegex(handoff.HandoffError, "operating-system HOME"):
            launch.apply({"HOME": str(self.home)})

    def test_port_or_spec_caps_model_profile_drift_requires_explicit_rebind(self):
        binding = handoff.capture(self.home)["binding"]
        original_route, original_state = dict(self.route), dict(self.state)
        for field, value in (("base_url", "http://127.0.0.1:49992/v1"), ("specification_sha256", "5" * 64),
                             ("context", 8192), ("max_output", 64), ("model_id", "different-model"),
                             ("transport_profile", "llama-cpp-qwen")):
            self.route = dict(original_route, **{field: value})
            self.state = dict(original_state)
            self.state.update(specification_sha256=self.route["specification_sha256"], model=self.route["model_id"],
                              port=int(self.route["base_url"].split(":")[-1].split("/")[0]))
            self.save_state()
            with self.subTest(field=field), self.assertRaisesRegex(handoff.HandoffError, "explicitly rebind"):
                handoff.launch_environment(self.home, binding)

    def test_stopped_service_and_cross_home_binding_refuse(self):
        binding = handoff.capture(self.home)["binding"]
        self.route["status"] = "stopped"
        with self.assertRaisesRegex(handoff.HandoffError, "not ready"):
            handoff.launch_environment(self.home, binding)
        self.route["status"] = "running"
        foreign = copy.deepcopy(binding)
        foreign["home"] = str(self.base / "foreign")
        with self.assertRaisesRegex(handoff.HandoffError, "environment binding differs"):
            handoff.launch_environment(self.home, foreign)

    def test_status_lifetime_race_or_changed_key_snapshot_refuses(self):
        initial = dict(self.route)
        self.status.side_effect = [initial, dict(initial, pid=12346)]
        with self.assertRaisesRegex(handoff.HandoffError, "lifetime changed"):
            handoff.capture(self.home)
        def changed(*_):
            if self.status.call_count % 2 == 0:
                self.key.write_text("b" * 64 + "\n")
            return dict(self.route)
        self.status.reset_mock(side_effect=True)
        self.status.side_effect = changed
        with self.assertRaisesRegex(handoff.HandoffError, "source changed"):
            handoff.capture(self.home)

    def test_nonce_mode_hash_and_alias_refuse_without_reading_other_sources(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(handoff.HandoffError, "private native nonce"):
            handoff.capture(self.home)
        self.key.chmod(0o600)
        self.state["nonce_sha256"] = "0" * 64
        self.save_state()
        with self.assertRaisesRegex(handoff.HandoffError, "owned source binding"):
            handoff.capture(self.home)
        self.state["nonce_sha256"] = hashlib.sha256(self.key.read_bytes()).hexdigest()
        self.save_state()
        outside = self.base / "outside-secret"
        self.key.rename(outside)
        self.key.symlink_to(outside)
        with self.assertRaisesRegex(handoff.HandoffError, "redirected"):
            handoff.capture(self.home)
        self.assertEqual(outside.read_text(), "a" * 64 + "\n")

    def test_restart_options_retain_expected_port_and_never_start_or_reconfigure(self):
        with mock.patch.object(model_service, "start", side_effect=AssertionError("Unexpected start")), \
                mock.patch.object(model_service, "stop", side_effect=AssertionError("Unexpected stop")), \
                mock.patch.object(model_service, "provision", side_effect=AssertionError("Unexpected provision")):
            value = handoff.capture(self.home)
            before = self.state_path.read_bytes()
            self.assertEqual(handoff.restart_options(value["binding"]), {"port": 49991})
            handoff.launch_environment(self.home, value["binding"])
            self.assertEqual(self.state_path.read_bytes(), before)

    def test_foreign_url_or_environment_reference_cannot_escape_binding(self):
        binding = handoff.capture(self.home)["binding"]
        for endpoint in ("https://example.com/v1", "http://127.0.0.1:49991/v1?token=unknown", "http://local:pass@127.0.0.1:49991/v1"):
            with self.assertRaises(handoff.HandoffError):
                handoff.restart_options(dict(binding, base_url=endpoint))
        with self.assertRaisesRegex(handoff.HandoffError, "environment binding differs"):
            handoff.launch_environment(self.home, dict(binding, environment_variable="!unsafe-command"))

    def install_home(self, home=None):
        home = home or self.home
        home.mkdir()
        (home / "state").mkdir()
        config = {"schema": "agent-home/v1", "home": str(home)}
        (home / "home.json").write_text(json.dumps(config))
        installed = home_entry.install(home, guard_source=Path(home_lifecycle.__file__).resolve())
        config["lifecycle_guard_sha256"] = installed["guard_sha256"]
        (home / "home.json").write_text(json.dumps(config))
        return home_entry._load_guard(home, installed["guard_sha256"]), installed["guard_sha256"]

    @contextlib.contextmanager
    def inert_child(self, pass_fds=()):
        # An owned sleeping process tests kernel FD ownership, never a model.
        child = subprocess.Popen([sys.executable, "-I", "-c", "import time;time.sleep(30)"], pass_fds=pass_fds)
        try:
            observed = model_service._process(child.pid)
            self.route.update(pid=child.pid, start_ticks=observed["start_ticks"])
            self.state.update(pid=child.pid, start_ticks=observed["start_ticks"])
            self.save_state()
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)

    def test_created_home_refuses_prior_prehome_process_without_child_read_lease(self):
        proposed = handoff.capture(self.home)
        self.install_home()
        with self.inert_child(), self.assertRaisesRegex(handoff.HandoffError, "pre-home service"):
            handoff.launch_environment(self.home, proposed["binding"])

    def test_parent_only_shared_lease_cannot_qualify_service_child(self):
        guard, pin = self.install_home()
        with guard.lease(self.home, expected_sha256=pin), self.inert_child():
            with self.assertRaisesRegex(handoff.HandoffError, "own home lifecycle READ lease"):
                handoff.capture(self.home)

    def test_child_inherited_read_lease_remains_valid_after_parent_close(self):
        proposed = handoff.capture(self.home)
        guard, pin = self.install_home()
        with contextlib.ExitStack() as stack:
            with guard.lease(self.home, expected_sha256=pin) as held:
                child = stack.enter_context(self.inert_child(held.pass_fds))
            value = handoff.capture(self.home)
            self.assertEqual(value["receipt"]["lease_scope"], "home_shared")
            self.assertEqual(value["receipt"]["home_lock_mode"], "FLOCK ADVISORY READ")
            self.assertEqual(value["receipt"]["service_pid"], child.pid)
            launched = handoff.launch_environment(self.home, proposed["binding"])
            self.assertEqual(launched.receipt["lease_scope"], "home_shared")

    def test_open_descriptor_without_flock_or_exclusive_lock_cannot_qualify(self):
        guard, pin = self.install_home()
        lock = self.home / "state/home-lifecycle.lock"
        with guard.lease(self.home, expected_sha256=pin):
            pass
        descriptor = os.open(lock, os.O_RDWR)
        try:
            with self.inert_child((descriptor,)), self.assertRaisesRegex(handoff.HandoffError, "own home lifecycle READ lease"):
                handoff.capture(self.home)
        finally:
            os.close(descriptor)
        with guard.lease(self.home, expected_sha256=pin, mode="exclusive") as held, self.inert_child(held.pass_fds):
            with self.assertRaisesRegex(handoff.HandoffError, "own home lifecycle READ lease"):
                handoff.capture(self.home)

    def test_other_home_read_lease_and_replaced_lock_inode_cannot_qualify(self):
        guard, pin = self.install_home()
        other = self.base / "other-home"
        other_guard, other_pin = self.install_home(other)
        with guard.lease(self.home, expected_sha256=pin):
            pass
        with other_guard.lease(other, expected_sha256=other_pin) as held, self.inert_child(held.pass_fds):
            with self.assertRaisesRegex(handoff.HandoffError, "own home lifecycle READ lease"):
                handoff.capture(self.home)
        with guard.lease(self.home, expected_sha256=pin) as held, self.inert_child(held.pass_fds):
            lock = self.home / "state/home-lifecycle.lock"
            lock.rename(lock.with_suffix(".saved"))
            lock.touch(mode=0o600)
            with self.assertRaisesRegex(handoff.HandoffError, "own home lifecycle READ lease"):
                handoff.capture(self.home)

    def test_home_creation_during_prehome_capture_is_not_silently_adopted(self):
        def create_during_status(*_):
            if self.status.call_count == 2:
                self.install_home()
            return dict(self.route)
        self.status.side_effect = create_during_status
        with self.assertRaisesRegex(handoff.HandoffError, "pre-home service"):
            handoff.capture(self.home)

    @unittest.skipUnless(os.environ.get("PI_MODEL_SERVICE_TEST_PI_PACKAGE") and os.environ.get("PI_MODEL_SERVICE_TEST_NODE"),
                         "Set installed Pi1.4 and Node for actual zero-network serializer qualification")
    def test_actual_pi_env_reference_and_serializer_with_no_network(self):
        value = handoff.capture(self.home)
        config = self.base / "models.json"
        config.write_text(json.dumps({"providers": {"local": value["provider"]}}))
        code = r'''
import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';
import {pathToFileURL} from 'node:url';import {createHash} from 'node:crypto';
const [pkg,modelsPath,name]=process.argv.slice(1),configured=JSON.parse(fs.readFileSync(modelsPath));
assert.equal(JSON.parse(fs.readFileSync(path.join(pkg,'package.json'))).version,'1.4.0');
const ref=configured.providers.local.apiKey;assert.equal(ref,'$'+name);assert.ok(!ref.startsWith('!'));
const sourceFiles=['dist/core/resolve-config-value.js','dist/core/model-config.js','dist/core/provider-composer.js','dist/core/model-runtime.js'];
const hashes=Object.fromEntries(sourceFiles.map(file=>[file,createHash('sha256').update(fs.readFileSync(path.join(pkg,file))).digest('hex')]));
let expected='a'.repeat(64),attempts=0;
globalThis.fetch=async(input,init)=>{const request=new Request(input,init);assert.equal(request.url,configured.providers.local.baseUrl+'/chat/completions');
assert.equal(request.headers.get('authorization'),'Bearer '+expected);const payload=JSON.parse(await request.text());
assert.equal(payload.model,configured.providers.local.models[0].id);assert.equal(payload.max_tokens??payload.max_completion_tokens,1);
attempts++;throw Object.assign(new Error('OWNED_HANDOFF_NO_NETWORK'),{name:'AbortError'});};
process.env.PI_OFFLINE='1';process.env.PI_SKIP_VERSION_CHECK='1';process.env[name]=expected;
const sdk=await import(pathToFileURL(path.join(pkg,'dist/index.js')));
const credentials={async read(){},async list(){return[];},async modify(_id,fn){return fn(undefined);},async delete(){}};
const store=new Map(),modelsStore={async read(id){return store.get(id);},async write(id,v){store.set(id,v);},async delete(id){store.delete(id);}};
const runtime=await sdk.ModelRuntime.create({credentials,modelsStore,modelsPath,allowModelNetwork:false,refreshOnCreate:false});
const model=runtime.getModel('local',configured.providers.local.models[0].id);assert.ok(model);assert.equal(model.contextWindow,4096);assert.equal(model.maxTokens,32);
const context={messages:[{role:'user',content:'Owned serialization metadata only.',timestamp:1}]};
for(const next of ['a'.repeat(64),'b'.repeat(64)]){expected=next;process.env[name]=next;try{await runtime.completeSimple(model,context,{maxTokens:1,temperature:0});}catch{}}
assert.equal(attempts,2);delete process.env[name];
const resolver=await import(pathToFileURL(path.join(pkg,'dist/core/resolve-config-value.js')));
assert.throws(()=>resolver.resolveConfigValueOrThrow(ref,'Owned qualification',{}));
await assert.rejects(()=>runtime.getAuth(model));assert.equal(attempts,2);
console.log(JSON.stringify({result:'PASS',pi:'1.4.0',serialized_and_intercepted:attempts,provider_http_requests:0,
 model_requests:0,nonce_rotation_resolved:true,missing_env_refused:true,api_key_reference:ref,source_hashes:hashes}));
'''
        env = {key: os.environ[key] for key in ("HOME", "PATH", "LANG") if key in os.environ}
        result = subprocess.run([os.environ["PI_MODEL_SERVICE_TEST_NODE"], "--input-type=module", "--eval", code,
                                 os.environ["PI_MODEL_SERVICE_TEST_PI_PACKAGE"], str(config), value["binding"]["environment_variable"]],
                                cwd=self.base, env=env, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["result"], "PASS")
        self.assertEqual(receipt["provider_http_requests"], 0)
        if os.environ.get("MODEL_SERVICE_HANDOFF_NATIVE_RECEIPT"):
            Path(os.environ["MODEL_SERVICE_HANDOFF_NATIVE_RECEIPT"]).write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
