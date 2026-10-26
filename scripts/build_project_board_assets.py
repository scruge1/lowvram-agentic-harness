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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(upstream, node, output):
    upstream, node = Path(upstream).resolve(strict=True), Path(node).resolve(strict=True)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Use a new build output; retain earlier artifacts")
    policy = json.loads((ROOT / "harness/project-board-native.json").read_text(encoding="utf-8"))
    for name, expected in policy["files"].items():
        if digest(upstream / name) != expected:
            raise ValueError("Native source drift: " + name)
    # The small unchanged utility is in the runtime source closure as well as
    # upstream. Permit checkout line endings, never different source text.
    if (ROOT / "adapters/project-board/native-utils.ts").read_text(encoding="utf-8") != (upstream / "web/src/lib/utils.ts").read_text(encoding="utf-8"):
        raise ValueError("The retained native utility source differs from upstream")
    version = subprocess.check_output([str(node), "--version"], text=True, timeout=10).strip()
    if version != "v22.23.2":
        raise ValueError("Use the reviewed managed Node22.23.2")
    vite = upstream / "node_modules/vite/bin/vite.js"
    if not vite.is_file():
        raise ValueError("The locked native web dependency closure is not installed")
    parent = upstream / "web"
    with tempfile.TemporaryDirectory(prefix="project-board-host-", dir=parent) as temporary:
        host = Path(temporary)
        for file in (ROOT / "adapters/project-board").iterdir():
            if file.is_file():
                shutil.copyfile(file, host / file.name)
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
        environment = dict(os.environ, NODE_ENV="production")
        subprocess.run([str(node), str(vite), "build", "--config", str(config)], cwd=upstream,
                       env=environment, check=True, timeout=180)
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
        manifest = {"schema": "project-board-assets/v1", "hermes_commit": policy["commit"],
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
