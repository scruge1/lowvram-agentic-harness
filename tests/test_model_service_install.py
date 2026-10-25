"""Exercise installed model metadata and fail before creating an incomplete home."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness import home


class ModelServiceInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="model-service-install-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.target = self.base / "agent home"

    def scaffold(self, source):
        return home.scaffold(self.target, source=source, profile="core", offline=True,
                             base_url="http://127.0.0.1:8080/v1", model="fixture-model")

    def sparse_source(self):
        source = self.base / "incomplete-source"
        (source / "harness").mkdir(parents=True)
        # Explicit incomplete fixture; it must fail before template processing.
        (source / "harness/model_service.py").write_text("# incomplete fixture\n")
        return source

    def test_installed_module_loads_its_exact_static_data_without_checkout_imports(self):
        self.scaffold(home.ROOT)
        relative = "harness/model-service-pins.json"
        copied = self.target / "runtime" / relative
        original = home.ROOT / relative
        self.assertEqual(copied.read_bytes(), original.read_bytes())
        manifest = json.loads((self.target / "runtime/runtime-manifest.json").read_text())
        records = {row["path"]: row["sha256"] for row in manifest["files"]}
        self.assertEqual(records[relative], hashlib.sha256(copied.read_bytes()).hexdigest())
        # Run outside the checkout and put the installed package first. Retain
        # this interpreter's standard-library environment on embedded Windows.
        code = ("import json,sys;sys.path.insert(0,sys.argv[1]);"
                "from harness import model_service as m;"
                "pins=json.loads(m.PINS.read_text());"
                "s=m.specification(model=pins['model']['id'],backend='cpu',context=4096,"
                "max_output=32,threads=2,batch_threads=2,ram_required_bytes=12*1024**3);"
                "print(json.dumps({'module':m.__file__,'pins':str(m.PINS),'model':s['model']['id']}))")
        result = subprocess.run([sys.executable, "-B", "-c", code, str(self.target / "runtime")],
                                cwd=self.base, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(Path(value["module"]).resolve(), self.target / "runtime/harness/model_service.py")
        self.assertEqual(Path(value["pins"]).resolve(), copied)
        self.assertEqual(value["model"], json.loads(original.read_text())["model"]["id"])

    def test_missing_model_data_refuses_before_home_creation(self):
        source = self.sparse_source()
        with self.assertRaisesRegex(home.HomeError, "model-service-pins.json"):
            self.scaffold(source)
        self.assertFalse(self.target.exists())

    @unittest.skipIf(os.name == "nt", "Native symlink control needs no Windows elevation")
    def test_redirected_model_data_refuses_without_touching_target(self):
        source = self.sparse_source()
        external = self.base / "external.json"
        raw = b'{"preserve":"external bytes"}\n'
        external.write_bytes(raw)
        (source / "harness/model-service-pins.json").symlink_to(external)
        with self.assertRaisesRegex(home.HomeError, "model-service-pins.json"):
            self.scaffold(source)
        self.assertFalse(self.target.exists())
        self.assertEqual(external.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
