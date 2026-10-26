"""Build the small native Kanban host from a fresh, locked upstream workspace.

First run upstream's `npm ci --workspace web --ignore-scripts` in an owned copy.
This compiler does not install packages or write an agent home. Keep its output
and source/dependency qualification separate from normal-home adoption.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HOST_FILES = ("entry.js", "style.css", "index.html", "native-utils.ts", "NOTICE.md", "HERMES-LICENSE.txt")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_source_identity(upstream, expected_commit):
    """Use the actual pinned checkout, including transitive workspace source."""
    upstream = Path(upstream).resolve(strict=True)
    def git(*arguments):
        result = subprocess.run(["git", *arguments], cwd=upstream, capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError("Use the exact clean native Git checkout; source inspection failed")
        return result.stdout
    if Path(os.fsdecode(git("rev-parse", "--show-toplevel")).strip()).resolve() != upstream:
        raise ValueError("Native source must be its actual Git checkout root")
    commit = os.fsdecode(git("rev-parse", "HEAD")).strip()
    if commit != expected_commit:
        raise ValueError("Native Git HEAD differs from the pinned commit")
    git("diff", "--quiet", "--ignore-submodules=none", "--")
    git("diff", "--cached", "--quiet", "--ignore-submodules=none", "--")
    # Deliberately omit --exclude-standard: ignored files can still be new
    # source. Only dependency installations and pip metadata are exempt.
    exclusions = ("/node_modules/", "/web/node_modules/", "/hermes_agent.egg-info/")
    untracked = git("ls-files", "--others", "-z", *["--exclude=" + name for name in exclusions])
    if untracked:
        raise ValueError("Untracked native source exists; inspect it before building")
    return {"commit": commit, "tree": os.fsdecode(git("rev-parse", "HEAD^{tree}")).strip(),
            "tracked_source": "clean", "untracked_exclusions": list(exclusions),
            "license_sha256": digest(upstream / "LICENSE"),
            "dependency_scope": "Git binds workspace source; installed npm dependencies require their separate locked-install qualification"}


def build(upstream, node, output, *, pass_fds=(), environment=None):
    upstream, node = Path(upstream).resolve(strict=True), Path(node).resolve(strict=True)
    output = Path(output).absolute()
    environment = dict(os.environ if environment is None else environment, NODE_ENV="production")
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    if output.exists() or output.is_symlink():
        raise ValueError("Use a new build output; retain earlier artifacts")
    policy = json.loads((ROOT / "harness/project-board-native.json").read_text(encoding="utf-8"))
    source_identity = native_source_identity(upstream, policy["commit"])
    for name, expected in policy["files"].items():
        if digest(upstream / name) != expected:
            raise ValueError("Native source drift: " + name)
    # The small unchanged utility is in the runtime source closure as well as
    # upstream. Permit checkout line endings, never different source text.
    if (ROOT / "adapters/project-board/native-utils.ts").read_text(encoding="utf-8") != (upstream / "web/src/lib/utils.ts").read_text(encoding="utf-8"):
        raise ValueError("The retained native utility source differs from upstream")
    version = subprocess.check_output([str(node), "--version"], text=True, timeout=10, pass_fds=pass_fds, env=environment).strip()
    if version != "v22.23.2":
        raise ValueError("Use the reviewed managed Node22.23.2")
    vite = upstream / "node_modules/vite/bin/vite.js"
    if not vite.is_file():
        raise ValueError("The locked native web dependency closure is not installed")
    parent = upstream / "web"
    with tempfile.TemporaryDirectory(prefix="project-board-host-", dir=parent) as temporary:
        host = Path(temporary)
        host_sources = {}
        for name in HOST_FILES:
            file = ROOT / "adapters/project-board" / name
            if file.is_symlink() or not file.is_file():
                raise ValueError("Host source is missing or redirected: " + name)
            host_sources[name] = digest(file)
            shutil.copyfile(file, host / name)
        shutil.copyfile(upstream / "web/src/lib/utils.ts", host / "native-utils.ts")
        shutil.copyfile(upstream / "web/src/index.css", host / "native-theme.css")
        native = (upstream / "plugins/kanban/dashboard/dist/index.js").read_text(encoding="utf-8")
        replacements = {
            "if (!boardData) return undefined;": "if (!boardData || SDK.readOnly) return undefined;",
            "h(OrchestrationPanel, null)": "SDK.readOnly ? null : h(OrchestrationPanel, null)",
            "h(WorkerLogSection, { taskId: t.id, boardSlug: props.boardSlug })":
                'SDK.readOnly ? h("p", {className: "text-xs text-muted-foreground"}, "Worker logs are not exposed by this read view.") : h(WorkerLogSection, { taskId: t.id, boardSlug: props.boardSlug })',
            'data ? h("div", { className: "hermes-kanban-drawer-comment-foot" },':
                '!SDK.readOnly && data ? h("div", { className: "hermes-kanban-drawer-comment-foot" },',
        }
        adapted = native
        for marker, replacement in replacements.items():
            if adapted.count(marker) != 1:
                raise ValueError("Native entry changed; review the read-only adaptation: " + marker)
            adapted = adapted.replace(marker, replacement)
        (host / "native-board.js").write_text(adapted, encoding="utf-8")
        shutil.copyfile(upstream / "plugins/kanban/dashboard/dist/style.css", host / "native-board.css")
        config = host / "vite.config.mjs"
        config.write_text("import {defineConfig} from 'vite';\nimport tailwindcss from '@tailwindcss/vite';\n"
                          "export default defineConfig({root:" + json.dumps(str(host)) + ",publicDir:false,plugins:[tailwindcss()],"
                          "build:{emptyOutDir:false,outDir:" + json.dumps(str(output)) + ",sourcemap:false}});\n", encoding="utf-8")
        subprocess.run([str(node), str(vite), "build", "--config", str(config)], cwd=upstream,
                       env=environment, check=True, timeout=180, pass_fds=pass_fds)
        (output / "native-board.js").write_text(adapted, encoding="utf-8")
        files = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob("*")) if p.is_file()}
        notices = output / "notices"
        notices.mkdir()
        shutil.copyfile(upstream / "LICENSE", notices / "hermes-MIT.txt")
        # Preserve dependency licences from the actual locked build, including
        # design-system/font notices; no private paths enter the manifest.
        for file in (upstream / "node_modules").rglob("*"):
            if file.is_file() and not file.is_symlink() and file.name.lower().startswith(("license", "licence", "copyright")):
                relative = file.relative_to(upstream / "node_modules")
                target = notices / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
        files.update({p.relative_to(output).as_posix(): digest(p) for p in sorted(notices.rglob("*")) if p.is_file()})
    # The temporary host is gone before this second source check. A changed
    # generation leaves retained partial output without an admissible manifest.
    if native_source_identity(upstream, policy["commit"]) != source_identity:
        raise ValueError("Native source generation changed while building")
    if {name: digest(ROOT / "adapters/project-board" / name) for name in HOST_FILES} != host_sources:
        raise ValueError("Host source generation changed while building")
    manifest = {"schema": "project-board-assets/v1", "hermes_commit": source_identity["commit"],
                    "upstream_source": source_identity,
                    "host_source_files": host_sources, "builder_sha256": digest(Path(__file__)),
                    "native_source_files": policy["files"], "native_readonly_adaptation":
                        "Disable websocket, orchestration, unavailable worker-log request and comment composer; manual reload is explicit",
                    "bridge_source_sha256": digest(ROOT / "adapters/project-board/entry.js"),
                    "node_version": version, "node_sha256": digest(node), "files": files,
                    "scope": "Fresh owned static build; package/installer/target adoption and visual acceptance are separate"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(args.upstream, args.node, args.output)
    print(json.dumps({"hermes_commit": value["hermes_commit"], "assets": len(value["files"]), "scope": value["scope"]}))
