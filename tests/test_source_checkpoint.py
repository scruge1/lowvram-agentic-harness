"""Real isolated Git controls for reviewed source milestones and verifier."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "harness/source_checkpoint.py"
SPEC = importlib.util.spec_from_file_location("source_checkpoint_fixture", SOURCE)
checkpoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checkpoint)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextlib.contextmanager
def cwd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@unittest.skipUnless(shutil.which("git"), "Git is required")
class SourceCheckpointTests(unittest.TestCase):
    def setUp(self):
        selected = os.environ.get("SOURCE_CHECKPOINT_TEST_ROOT")
        if not selected and os.name == "nt" and Path("E:/").is_dir():
            selected = "E:/"
        self.temp = tempfile.TemporaryDirectory(prefix="source-checkpoint-", dir=selected)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        environment = mock.patch.dict(os.environ, {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        environment.start()
        self.addCleanup(environment.stop)
        self.git("init", "-q", "-b", "work")
        for name, value in (("user.name", "Synthetic fixture"), ("user.email", "fixture@example.test"),
                            ("commit.gpgsign", "false"), ("core.autocrlf", "false"),
                            ("core.hooksPath", str(self.base / "no-hooks"))):
            self.git("config", name, value)
        self.artifacts = self.project / checkpoint.BASE
        self.artifacts.mkdir(parents=True)
        self.source = self.project / "source.py"
        self.source.write_bytes(b'print("reviewed public source")\n')
        self.inventory = self.artifacts / "reviewed.json"
        self.write_inventory()

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.project), *args], capture_output=True, check=True)
        return result.stdout.decode().strip()

    def write_inventory(self, files=None):
        files = files or [self.source]
        self.inventory.write_text(json.dumps({"safe_files": [{"path": str(file), "sha256": sha(file)} for file in files],
                                              "excluded": []}), encoding="utf-8")

    def args(self, operation="owned-milestone"):
        return ["--project-root", str(self.project), "--task-ref", "kanban:fixture-owned-task",
                "--message", "Save reviewed source milestone", "--operation", operation,
                "--inventory", str(self.inventory), sha(self.inventory)]

    def invoke(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = checkpoint.main(arguments)
        return result, out.getvalue(), err.getvalue()

    def commit(self, arguments=None):
        code, out, err = self.invoke(arguments or self.args())
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def receipt(self, operation="owned-milestone"):
        return self.artifacts / operation / "admission.json"

    def verify(self, path=None):
        path = path or self.receipt()
        with cwd(self.project):
            return self.invoke(["--verify", str(path.relative_to(self.project))])

    def baseline(self):
        unrelated = self.project / "dirty.py"
        unrelated.write_text("original\n")
        self.git("add", "--", "dirty.py")
        self.git("commit", "-q", "-m", "Fixture baseline")
        return unrelated

    def push_options(self, remote=None):
        remote = remote or self.base / "remote.git"
        if not remote.exists():
            subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        self.git("remote", "add", "origin", str(remote))
        return ["--push-remote", "origin", "--expected-push-url", str(remote), "--expected-branch", "work"]

    def test_unborn_first_commit_and_readonly_verifier(self):
        result = self.commit()
        self.assertEqual(result["state"], "reviewed-source-committed-local")
        self.assertEqual(self.git("show", "HEAD:source.py") + "\n", self.source.read_text())
        self.assertEqual(self.git("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD"), "source.py")
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD"), "work")
        before = self.git("status", "--porcelain"), self.receipt().read_bytes()
        code, out, err = self.verify()
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["verified"])
        self.assertFalse(json.loads(out)["remote_verified"])
        self.assertEqual(before, (self.git("status", "--porcelain"), self.receipt().read_bytes()))

    def test_unrelated_dirty_work_remains_unchanged(self):
        unrelated = self.baseline()
        unrelated.write_text("another owner's retained work\n")
        before = unrelated.read_bytes()
        self.commit()
        self.assertEqual(unrelated.read_bytes(), before)
        self.assertEqual(self.git("diff", "--name-only"), "dirty.py")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        self.assertEqual(self.verify()[0], 0)

    def test_occupied_index_refuses_before_mutation(self):
        unrelated = self.baseline()
        before = self.git("rev-parse", "HEAD")
        unrelated.write_text("staged owner work\n")
        self.git("add", "--", "dirty.py")
        staged = self.git("diff", "--cached", "--binary")
        code, _, err = self.invoke(self.args())
        self.assertEqual(code, 2)
        self.assertIn("Existing staged work", err)
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(self.git("diff", "--cached", "--binary"), staged)
        self.assertFalse(self.receipt().parent.exists())

    def test_wrong_inventory_location_precedes_git_and_operation_creation(self):
        outside = self.base / "reviewed.json"
        outside.write_bytes(self.inventory.read_bytes())
        args = self.args()
        args[-2] = str(outside)
        with mock.patch.object(checkpoint, "git", side_effect=AssertionError("Git must not run")):
            code, _, err = self.invoke(args)
        self.assertEqual(code, 2)
        self.assertIn("no operation was created", err)
        self.assertFalse(self.receipt().parent.exists())

    def test_missing_inventory_precedes_git(self):
        args = self.args()
        args[-2] = str(self.artifacts / "missing.json")
        with mock.patch.object(checkpoint, "git", side_effect=AssertionError("Git must not run")):
            self.assertEqual(self.invoke(args)[0], 2)

    def test_inventory_and_source_hash_drift_refuse_whole_checkpoint(self):
        args = self.args()
        self.inventory.write_text(self.inventory.read_text() + "\n")
        self.assertEqual(self.invoke(args)[0], 2)
        self.assertFalse(self.receipt().parent.exists())
        args = self.args()
        self.source.write_text("unreviewed change\n")
        code, _, err = self.invoke(args)
        self.assertEqual(code, 2)
        self.assertIn("candidate changed", err)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_source_escape_and_nested_repository_refused(self):
        outside = self.base / "outside.py"
        outside.write_text("outside\n")
        self.write_inventory([outside])
        self.assertEqual(self.invoke(self.args())[0], 2)
        vendor = self.project / "vendor"
        vendor.mkdir()
        subprocess.run(["git", "init", "-q", str(vendor)], check=True)
        nested = vendor / "file.py"
        nested.write_text("vendor\n")
        self.write_inventory([nested])
        code, _, err = self.invoke(self.args())
        self.assertEqual(code, 2)
        self.assertIn("Nested/vendor", err)
        self.assertFalse(self.receipt().parent.exists())

    def test_symlink_source_and_inventory_escape_refused(self):
        outside = self.base / "outside.py"
        outside.write_text("outside\n")
        alias = self.project / "alias.py"
        try:
            alias.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Creating symlinks is not permitted")
        self.write_inventory([alias])
        self.assertEqual(self.invoke(self.args())[0], 2)
        inventory_alias = self.artifacts / "alias.json"
        external_inventory = self.base / "outside.json"
        external_inventory.write_bytes(self.inventory.read_bytes())
        inventory_alias.symlink_to(external_inventory)
        args = self.args()
        args[-2] = str(inventory_alias)
        with mock.patch.object(checkpoint, "git", side_effect=AssertionError("Git must not run")):
            self.assertEqual(self.invoke(args)[0], 2)

    def test_stage_race_preserves_new_owner_bytes_and_prepared_index(self):
        original_git = checkpoint.git
        original_source = self.source.read_bytes()
        def drift(root, *args, **kwargs):
            value = original_git(root, *args, **kwargs)
            if args[0] == "add":
                self.source.write_text("concurrent owner work\n")
            return value
        with mock.patch.object(checkpoint, "git", side_effect=drift):
            code, _, err = self.invoke(self.args())
        self.assertEqual(code, 2)
        self.assertIn("Source drift after staging", err)
        self.assertEqual(self.source.read_text(), "concurrent owner work\n")
        self.assertEqual(checkpoint.git(self.project, "show", ":source.py"), original_source)
        self.assertIsNone(checkpoint.head(self.project))
        self.assertEqual(json.loads(self.receipt().read_text())["state"], "prepared")

    def test_existing_operation_is_never_replayed(self):
        self.commit()
        before = self.receipt().read_bytes(), self.git("rev-parse", "HEAD")
        self.assertEqual(self.invoke(self.args())[0], 2)
        self.assertEqual(before, (self.receipt().read_bytes(), self.git("rev-parse", "HEAD")))

    def test_missing_receipt_from_empty_nongit_directory_exits_one_without_writes(self):
        empty = self.base / "empty"
        empty.mkdir()
        with cwd(empty), mock.patch.object(checkpoint, "git", side_effect=AssertionError("Git must not run")):
            code, _, err = self.invoke(["--verify", str(checkpoint.BASE / "absent/admission.json")])
        self.assertEqual(code, 1)
        self.assertIn("missing", err)
        self.assertEqual(list(empty.iterdir()), [])

    def test_verifier_checks_real_bytes_and_does_not_trust_receipt_success(self):
        self.commit()
        original = self.receipt().read_bytes()
        self.source.write_text("changed since checkpoint\n")
        self.assertEqual(self.verify()[0], 1)
        self.source.write_bytes(b'print("reviewed public source")\n')
        record = json.loads(original)
        record["files"] = {"invented.py": "0" * 64}
        self.receipt().write_text(json.dumps(record))
        self.assertEqual(self.verify()[0], 1)
        self.receipt().write_bytes(original)
        self.assertEqual(self.verify()[0], 0)

    def test_verifier_refuses_later_head_and_absolute_receipt(self):
        self.commit()
        with cwd(self.project):
            self.assertEqual(self.invoke(["--verify", str(self.receipt())])[0], 1)
        other = self.project / "later.py"
        other.write_text("later owned source\n")
        self.git("add", "--", "later.py")
        self.git("commit", "-q", "-m", "Later source")
        self.assertEqual(self.verify()[0], 1)

    def test_optional_exact_bare_push_and_readback(self):
        options = self.push_options()
        result = self.commit(self.args() + options)
        self.assertEqual(result["state"], "reviewed-source-committed-and-remote-verified")
        remote = Path(options[3])
        found = subprocess.check_output(["git", "--git-dir", str(remote), "rev-parse", "refs/heads/work"]).decode().strip()
        self.assertEqual(found, result["commit"])
        code, out, err = self.verify()
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["remote_verified"])

    def test_push_does_not_follow_unpublished_annotated_tags(self):
        self.baseline()
        self.git("tag", "-a", "unpublished-owner-tag", "-m", "Other milestone; not requested for delivery")
        self.git("config", "push.followTags", "true")
        options = self.push_options()
        result = self.commit(self.args() + options)
        remote = Path(options[3])
        refs = subprocess.check_output(["git", "--git-dir", str(remote), "for-each-ref", "--format=%(refname)"]).decode().splitlines()
        self.assertEqual(refs, ["refs/heads/work"])
        self.assertEqual(result["state"], "reviewed-source-committed-and-remote-verified")

    def pre_push_drift(self, commit_change):
        hooks = self.base / "hooks"
        hooks.mkdir()
        self.git("config", "core.hooksPath", str(hooks))
        hook = hooks / "pre-push"
        script = "#!/bin/sh\nprintf '%s\\n' 'changed by synthetic pre-push hook' > source.py\n"
        if commit_change:
            script += 'git add -- source.py\ngit commit --only --quiet -m "Synthetic hook commit" -- source.py\n'
        hook.write_bytes(script.encode())
        hook.chmod(0o755)
        options = self.push_options()
        code, _, err = self.invoke(self.args() + options)
        self.assertEqual(code, 2, "Producer accepted source changed by a real pre-push hook: " + err)
        receipt = json.loads(self.receipt().read_text())
        self.assertEqual(receipt["state"], "local-source-admission-remote-pending")
        self.assertEqual(self.source.read_text(), "changed by synthetic pre-push hook\n")
        remote = Path(options[3])
        delivered = subprocess.check_output(["git", "--git-dir", str(remote), "rev-parse", "refs/heads/work"]).decode().strip()
        self.assertEqual(delivered, receipt["commit"])
        if commit_change:
            self.assertNotEqual(self.git("rev-parse", "HEAD"), receipt["commit"])

    def test_pre_push_worktree_drift_retains_pending_receipt(self):
        self.pre_push_drift(commit_change=False)

    def test_pre_push_head_drift_retains_pending_receipt(self):
        self.pre_push_drift(commit_change=True)

    def test_push_group_destination_and_branch_refusals_precede_mutation(self):
        self.assertEqual(self.invoke(self.args() + ["--push-remote", "origin"])[0], 2)
        options = self.push_options()
        for index, wrong in ((3, str(self.base / "wrong.git")), (5, "main")):
            altered = options.copy()
            altered[index] = wrong
            self.assertEqual(self.invoke(self.args() + altered)[0], 2)
        self.assertFalse(self.receipt().parent.exists())

    def test_push_failure_retains_commit_pending_receipt_without_replay(self):
        missing = self.base / "missing.git"
        self.git("remote", "add", "origin", str(missing))
        options = ["--push-remote", "origin", "--expected-push-url", str(missing), "--expected-branch", "work"]
        code, _, err = self.invoke(self.args() + options)
        self.assertEqual(code, 2)
        self.assertIn("Git push failed", err)
        receipt = json.loads(self.receipt().read_text())
        self.assertEqual(receipt["state"], "local-source-admission-remote-pending")
        self.assertEqual(receipt["commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(self.verify()[0], 1)
        self.assertEqual(self.invoke(self.args() + options)[0], 2)
        self.assertEqual(self.git("rev-parse", "HEAD"), receipt["commit"])

    def test_remote_race_after_commit_refuses_push_and_retains_local_commit(self):
        options = self.push_options()
        original_git = checkpoint.git
        def drift(root, *args, **kwargs):
            value = original_git(root, *args, **kwargs)
            if args[0] == "commit":
                self.git("remote", "set-url", "origin", str(self.base / "unexpected.git"))
            return value
        with mock.patch.object(checkpoint, "git", side_effect=drift):
            self.assertEqual(self.invoke(self.args() + options)[0], 2)
        receipt = json.loads(self.receipt().read_text())
        self.assertEqual(receipt["commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(receipt["state"], "local-source-admission-remote-pending")

    def test_unsafe_remote_urls_and_optimized_python_cannot_bypass_guards(self):
        for value in ("ext::sh -c anything", "https://token@example.test/repo", "https://u:p@example.test/repo",
                      "ssh://u:p@example.test/repo", "https://example.test/repo?token=value"):
            with self.subTest(url=value), self.assertRaises(ValueError):
                checkpoint.safe_push_url(value)
        args = self.args()
        args[-1] = "0" * 64
        result = subprocess.run([sys.executable, "-O", "-B", str(SOURCE), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.receipt().parent.exists())


if __name__ == "__main__":
    unittest.main()
