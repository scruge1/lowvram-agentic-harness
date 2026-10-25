"""Create a private agent home without changing existing profiles.

The bootstrap uses only the standard library. Optional tools are installed in
home-owned environments. Package installation never grants task authority.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import shutil
import shlex
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agent-home/v1"
REQUIRED_TEMPLATES = (
    "AGENTS.md", "CLAUDE.md", "gitignore.template", "agent/AGENTS.md",
    "agent/APPEND_SYSTEM.md", "agent/prompts/personalize.md",
    "agent/skills/supervised-tasks/SKILL.md", "context/startup-index.md",
    "context/profile.md", "context/current.md", "context/lessons.md",
)
PINS = {
    "pi": "@earendil-works/pi-coding-agent@1.4.0",
    "hermes": "hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git@866332bfb52c46e543143b2620a9aeee8bce9c77",
    "mempalace": "mempalace==3.11.0",
    "framework": "agent-framework-core==1.21.0",
    "harness2": "harness2 @ git+https://github.com/google-research/harness2.git@1cfe254e8d25b15f37048c3730134686abe60335",
    "bun": "bun@1.4.4",
    "claude-mem": "claude-mem@13.29.0",
    "deepseek": "@deepseek-ai/dsh@0.2.1-rc.2",
}
PROFILES = {
    "core": (),
    "pi": ("pi", "hermes", "mempalace", "framework"),
    "full": tuple(PINS),
}
NPM_NAMES = {"pi": "@earendil-works/pi-coding-agent", "claude-mem": "claude-mem", "deepseek": "@deepseek-ai/dsh", "bun": "bun"}
DIST_NAMES = {"hermes": "hermes-agent", "mempalace": "mempalace", "framework": "agent-framework-core", "harness2": "harness2"}
GIT_SOURCES = {
    "hermes": ("https://github.com/NousResearch/hermes-agent.git", "866332bfb52c46e543143b2620a9aeee8bce9c77"),
    "harness2": ("https://github.com/google-research/harness2.git", "1cfe254e8d25b15f37048c3730134686abe60335"),
}


class HomeError(ValueError):
    """A setup prerequisite or owned-home check failed."""


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def write_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def run(argv, *, cwd, env=None, input=None, timeout=900):
    """Retain complete command output privately; show bounded failure details."""
    log_root = Path(cwd) / "logs"
    log_root.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=log_root, prefix="command-", suffix=".log", delete=False) as log, \
            tempfile.NamedTemporaryFile(dir=log_root, prefix="command-", suffix=".stderr.log", delete=False) as errors:
        with tempfile.TemporaryFile() as request:
            request.write((input or "").encode("utf-8"))
            request.seek(0)
            child = subprocess.Popen([str(arg) for arg in argv], cwd=cwd, env=env,
                                     stdin=request, stdout=log, stderr=errors,
                                     shell=False)
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                child.kill()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    raise HomeError(f"Timed out; child settlement unknown. Inspect {log.name}")
                raise HomeError(f"Timed out; descendant state unknown. Inspect {log.name}; do not blindly replay.")
        log.flush()
        errors.flush()
        with open(log.name, "rb") as reader:
            data = reader.read(4 * 1024 * 1024 + 1)
        with open(errors.name, "rb") as reader:
            error_data = reader.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024 or len(error_data) > 4 * 1024 * 1024:
        raise HomeError(f"Command output exceeds delivery limit; complete log retained: {log.name}")
    output = data.decode("utf-8", errors="replace")
    if child.returncode:
        tail = (output + error_data.decode("utf-8", errors="replace"))[-4000:]
        raise HomeError(f"Command failed ({child.returncode}): {argv[0]}\n{tail}\nLogs: {log.name}, {errors.name}")
    return output


def executable(environment, name="python"):
    return environment / ("Scripts" if os.name == "nt" else "bin") / (name + (".exe" if os.name == "nt" else ""))


def endpoint(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HomeError("Use an HTTP(S) model endpoint without credentials, query or fragment.")
    if parsed.hostname != "localhost":
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as error:
            raise HomeError("Use localhost or a numeric local/LAN/Tailscale address for the local model.") from error
        networks = ("10.0.0.0/8", "127.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "::1/128")
        if not any(address in ipaddress.ip_network(network) for network in networks):
            raise HomeError("The model endpoint must use owner-selected local hardware.")
    return value.rstrip("/")


def source_files(source):
    paths = []
    for name in ("harness", "ssot", "adapters/pi"):
        for file in sorted((source / name).rglob("*")):
            if file.is_file() and (file.suffix in {".py", ".ts", ".md"} or file.name == ".gitignore") and "__pycache__" not in file.parts:
                if file.is_symlink() or not file.resolve().is_relative_to(source.resolve()):
                    raise HomeError(f"Source escaped checkout: {file}")
                paths.append(file)
    if not (source / "adapters/pi/project-workflow/pi_kanban.py").is_file():
        raise HomeError("Use the complete repository checkout; adapter sources are required.")
    return paths


def environment(home):
    value = dict(os.environ)
    # Keep existing user HOME intact. Pi has a supported independent agentDir.
    value.update({
        "AGENT_HOME": str(home), "AGENT_HOME_PYTHON": sys.executable,
        "PI_PROJECT_CONTEXT_PI_PACKAGE": str(home / "packages/pi/node_modules/@earendil-works/pi-coding-agent"),
        "PI_CODING_AGENT_DIR": str(home / "agent"),
        "PI_PROJECT_STATE_BASE": str(home / "state/projects"),
        "PI_PROJECT_KANBAN_PYTHON": str(executable(home / "envs/hermes")),
        "PI_PROJECT_KANBAN_ADAPTER": str(home / "runtime/adapters/pi/project-workflow/pi_kanban.py"),
        "PI_PROJECT_KANBAN_ADAPTER_SHA256": digest(home / "runtime/adapters/pi/project-workflow/pi_kanban.py"),
        "PI_SYSTEM_TOOL_PYTHON": sys.executable,
        "PI_SYSTEM_TOOL_HELPER": str(home / "runtime/adapters/pi/project-workflow/tool_knowledge.py"),
        "PI_SYSTEM_TOOL_HELPER_SHA256": digest(home / "runtime/adapters/pi/project-workflow/tool_knowledge.py"),
        "PI_SYSTEM_TOOL_DATABASE": str(home / "state/tool-knowledge.sqlite"),
        "PYTHONPATH": str(home / "runtime"),
        "HF_HOME": str(home / "cache/huggingface"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "CLAUDE_MEM_ONLINE_OPTIN": "false",
        "CLAUDE_MEM_DATA_DIR": str(home / "memory/claude-mem"),
        "HERMES_HOME": str(home / "state/hermes"),
        "BUN_INSTALL_CACHE_DIR": str(home / "cache/bun"),
        "MEMPALACE_CONFIG_DIR": str(home / "state/mempalace-config"),
        "MEMPALACE_PALACE_PATH": str(home / "memory/palace"),
        "PI_VALIDATED_MEMORY_PYTHON": str(executable(home / "envs/mempalace")),
        "PI_VALIDATED_MEMORY_HELPER": str(home / "runtime/adapters/pi/memory/validated_memory_query.py"),
        "PI_VALIDATED_MEMORY_POLICY": str(home / "runtime/adapters/pi/memory/memory_retrieval_policy.py"),
        "PI_VALIDATED_MEMORY_REGISTRY": str(home / "state/validated-memory.jsonl"),
        "PI_MEMORY_CAPTURE_PYTHON": str(executable(home / "envs/mempalace")),
        "PI_MEMORY_CAPTURE_HELPER": str(home / "runtime/adapters/pi/memory-capture/capture.py"),
        "PI_MEMORY_CAPTURE_CLI": str(home / "bin/mempalace"),
        "PI_MEMORY_RUNTIME_WRAPPER": str(home / "runtime/harness/memory_runtime.py"),
        "PI_BOUNDED_COMPACTION_CONFIG": str(home / "state/bounded-compaction.json"),
    })
    config = json.loads((home / "home.json").read_text(encoding="utf-8"))
    if config.get("framework_binding_sha256"):
        value["PI_FRAMEWORK_BINDING"] = str(home / "state/framework-binding.json")
        value["PI_FRAMEWORK_BINDING_SHA256"] = config["framework_binding_sha256"]
    for field in ("HELPER", "POLICY"):
        value["PI_VALIDATED_MEMORY_" + field + "_SHA256"] = digest(Path(value["PI_VALIDATED_MEMORY_" + field]))
    value["PI_VALIDATED_MEMORY_REGISTRY_SHA256"] = config["validated_registry_sha256"]
    value["PI_MEMORY_CAPTURE_HELPER_SHA256"] = digest(Path(value["PI_MEMORY_CAPTURE_HELPER"]))
    value["PI_MEMORY_RUNTIME_WRAPPER_SHA256"] = digest(Path(value["PI_MEMORY_RUNTIME_WRAPPER"]))
    value["PI_BOUNDED_COMPACTION_CONFIG_SHA256"] = config["bounded_compaction_sha256"]
    return value


def scaffold(home, *, source=ROOT, profile="full", base_url, model, name="Owner", offline=False,
             context_window=8192, max_output=2048):
    home = home.expanduser().resolve(strict=False)
    source = source.resolve(strict=True)
    if home.is_symlink() or home.resolve() in {Path.home().resolve(), Path(home.anchor)}:
        raise HomeError("Choose a new dedicated agent-home directory.")
    if home.exists():
        raise HomeError("Target already exists. Use doctor; installation never overwrites a home.")
    if home.resolve().is_relative_to(source) or source.is_relative_to(home.resolve()):
        raise HomeError("Agent home and installer source must be separate trees.")
    base_url = endpoint(base_url)
    if not isinstance(model, str) or not model.strip() or any(c in model for c in "\r\n"):
        raise HomeError("Provide the exact model ID from your local server.")
    if profile not in PROFILES:
        raise HomeError("Unknown installation profile.")
    if type(context_window) is not int or context_window < 4096 or type(max_output) is not int or not 128 <= max_output <= context_window // 2:
        raise HomeError("Supply a context window of at least4096 and an output limit between128 and half the context.")
    files = source_files(source)
    templates = source / "harness/templates/agent-home"
    missing = [name for name in REQUIRED_TEMPLATES if not (templates / name).is_file()]
    if missing:
        raise HomeError("Agent-home templates are missing from the selected source: " + ", ".join(missing))
    if not shutil.which("git"):
        raise HomeError("Git is required. Install Git before creating an agent home.")
    parent = home.parent
    while not parent.exists():
        parent = parent.parent
    minimum = 64 * 1024**2 if offline or profile == "core" else 4 * 1024**3
    if shutil.disk_usage(parent).free < minimum:
        raise HomeError(f"Destination needs at least {minimum // 1024**2} MiB free before setup.")
    # Validate all inputs before the first write. Failed partial homes are retained.
    home.mkdir(parents=True, mode=0o700)
    for directory in ("agent/prompts", "agent/skills/supervised-tasks", "context", "projects", "memory/imports", "memory/initial-source", "memory/claude-mem", "state/mempalace-config", "logs", "cache", "envs", "packages", "bin"):
        (home / directory).mkdir(parents=True, mode=0o700, exist_ok=True)
    runtime = home / "runtime"
    manifest = []
    for file in files:
        relative = file.relative_to(source)
        target = runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
        manifest.append({"path": relative.as_posix(), "sha256": digest(target)})
    workflow = runtime / "adapters/pi/project-workflow"
    for guard_name in ("pi-task-worker.py", "pi_native_events.py"):
        file = workflow / guard_name
        if file.is_file():
            shutil.copyfile(file, runtime / guard_name)
            manifest.append({"path": guard_name, "sha256": digest(runtime / guard_name)})
    write_json(runtime / "runtime-manifest.json", {"files": manifest})
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        memory_port = reservation.getsockname()[1]
    configuration = {
        "schema": SCHEMA, "home": str(home), "profile": profile,
        "base_url": base_url, "model": model, "name": name,
        "context_window": context_window, "max_output": max_output,
        "model_capability_acceptance": "not_probed",
        "selected_packages": {key: PINS[key] for key in PROFILES[profile]},
        "runtime_manifest_sha256": digest(runtime / "runtime-manifest.json"),
        "installed": {}, "native_acceptance": "not_run",
        "personalization": "pending_current_agent_review",
        "validated_registry_sha256": hashlib.sha256(b"").hexdigest(),
        "claude_memory_port": memory_port,
    }
    write_json(home / "state/bounded-compaction.json", {
        "schema": "pi-bounded-compaction/v1",
        "models": [{"provider": "local", "id": model, "base_url": base_url}],
    })
    configuration["bounded_compaction_sha256"] = digest(home / "state/bounded-compaction.json")
    write_json(home / "home.json", configuration)
    write_json(home / "memory/claude-mem/settings.json", {
        "CLAUDE_MEM_DATA_DIR": str(home / "memory/claude-mem"),
        "CLAUDE_MEM_PROVIDER": "openai-compatible",
        "CLAUDE_MEM_OPENAI_COMPAT_PRESET": "custom",
        "CLAUDE_MEM_OPENAI_COMPAT_BASE_URL": base_url,
        "CLAUDE_MEM_OPENAI_COMPAT_MODEL": model,
        "CLAUDE_MEM_OPENAI_COMPAT_API_KEY": "local",
        "CLAUDE_MEM_OPENAI_COMPAT_API_KEYS": "",
        "CLAUDE_MEM_QUOTA_FALLBACK_PROVIDER": "", "CLAUDE_MEM_QUOTA_FALLBACK_MODEL": "",
        "CLAUDE_MEM_CLOUD_SYNC_TOKEN": "", "CLAUDE_MEM_ONLINE_OPTIN": "false",
        "CLAUDE_MEM_CHROMA_ENABLED": "false", "CLAUDE_MEM_TRANSCRIPTS_ENABLED": "false",
        "CLAUDE_MEM_WORKER_HOST": "127.0.0.1", "CLAUDE_MEM_WORKER_PORT": str(memory_port),
        "CLAUDE_MEM_REDACT_ENABLED": "true",
    })
    (home / "state/validated-memory.jsonl").write_bytes(b"")
    write_json(workflow / "everyday-runtime.json", {
        "python": sys.executable, "runtime": str(runtime),
        "runtime_manifest_sha256": configuration["runtime_manifest_sha256"],
        "engine_sha256": digest(runtime / "harness/enforcement.py"),
        "helper_sha256": digest(workflow / "everyday_workflow.py"),
    })
    # Unsupported process owners get inspection tools only; no enforcement claim.
    extensions = [str(workflow / "agent-capabilities.ts"), str(workflow / "system-tool-knowledge.ts")]
    if profile != "core":
        extensions.append(str(workflow / "pi-kanban.ts"))
        extensions.append(str(runtime / "adapters/pi/memory/validated-memory-query.ts"))
        if platform.system() == "Linux":
            extensions.append(str(workflow / "everyday-workflow.ts"))
            extensions.append(str(runtime / "adapters/pi/memory-capture.ts"))
        extensions.append(str(runtime / "adapters/pi/bounded-compaction.ts"))
        if profile == "full":
            extensions.append(str(runtime / "adapters/pi/claude-memory.ts"))
    write_json(home / "agent/settings.json", {
        "defaultProvider": "local", "defaultModel": model,
        "enabledModels": ["local/*"], "defaultThinkingLevel": "off",
        "defaultTools": ["read", "ls", "find", "grep"],
        "extensions": extensions, "defaultProjectTrust": "ask",
        "cacheWarming": "off",
        "compaction": {"enabled": True, "reserveTokens": max_output,
                       "keepRecentTokens": min(4096, context_window // 4)},
    })
    write_json(home / "agent/models.json", {"providers": {"local": {
        "baseUrl": base_url, "api": "openai-completions", "apiKey": "local",
        "models": [{"id": model, "input": ["text"], "contextWindow": context_window, "maxTokens": max_output}],
    }}})
    memory_python = executable(home / "envs/mempalace")
    memory_wrapper = runtime / "harness/memory_runtime.py"
    write_json(home / "agent/mcp.json", {"mcpServers": {"mempalace": {
        "command": str(memory_python), "args": ["-B", str(memory_wrapper), "--home", str(home), "mcp"],
        "enabled": profile != "core", "exposure": "direct",
        "env": {"HF_HOME": str(home / "cache/huggingface"),
                "MEMPALACE_CONFIG_DIR": str(home / "state/mempalace-config"),
                "MEMPALACE_PALACE_PATH": str(home / "memory/palace")},
    }}})
    for file in templates.rglob("*"):
        if file.is_file():
            relative = file.relative_to(templates)
            target = home / (".gitignore" if relative.as_posix() == "gitignore.template" else relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            text = file.read_text(encoding="utf-8").replace("{{OWNER}}", name).replace("{{HOME}}", home.as_posix())
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
    catalog = home / "state/capabilities.jsonl"
    entries = [
        {"name": "workflow_step", "description": "Supervised file action with independent predicate and negative control; Linux process owner required."},
        {"name": "project_admit", "description": "Select project identity, local Hermes Kanban board and knowledge."},
        {"name": "kanban_select", "description": "Resume an existing source-bound work card; selection is not authority."},
        {"name": "mempalace", "description": "Local session memory retrieval through the configured MCP server; hits are guidance."},
        {"name": "supervised-tasks", "description": "Installed skill for declared file work and complete saved-failure recovery."},
        {"name": "validated_memory_query", "description": "Recall only reviewed safe summaries bound to exact current source bytes; empty registry abstains."},
        {"name": "claude_memory_search", "description": "Full profile local Claude-mem SQLite keyword history; package installation does not prove fresh capture."},
        {"name": "kanban_intake_route", "description": "Route every distinct native request aspect before execution; retain original source and owner outcome."},
        {"name": "kanban_work_checkpoint", "description": "Retain ready work, explicit pauses and exact dependency waits without false project completion."},
    ]
    catalog.write_text("".join(json.dumps(item) + "\n" for item in entries), encoding="utf-8")
    run([sys.executable, workflow / "tool_knowledge.py", "--database", home / "state/tool-knowledge.sqlite", "build", catalog], cwd=home)
    # A Python entry point avoids shell interpolation of names and paths.
    launcher = (
        "import os, sys\nfrom pathlib import Path\n"
        "root = Path(__file__).resolve().parent\n"
        "sys.path.insert(0, str(root / 'runtime'))\n"
        "from harness.home import main\n"
        "raise SystemExit(main(['--home', str(root), *sys.argv[1:]]))\n"
    )
    (home / "agent-home.py").write_text(launcher, encoding="utf-8")
    run(["git", "init", "--quiet", str(home)], cwd=home)
    # No automatic add/commit: even personalized guidance can contain private data.
    return configuration


def load(home):
    home = home.expanduser().resolve(strict=True)
    config = json.loads((home / "home.json").read_text(encoding="utf-8"))
    if config.get("schema") != SCHEMA or Path(config["home"]).resolve() != home:
        raise HomeError("Agent home identity changed; do not silently rebind stored paths.")
    return home, config


def save_status(home, config):
    target = home / "home.json"
    old = target.read_bytes()
    fd, name = tempfile.mkstemp(prefix="home.json.", suffix=".candidate", dir=home)
    candidate = Path(name)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    if target.read_bytes() != old:
        candidate.unlink()
        raise HomeError("Concurrent agent-home configuration change.")
    # Keep the single predecessor until another managed operation replaces it.
    backup = target.with_name("home.json.previous")
    if backup.exists():
        backup.unlink()
    backup.write_bytes(old)
    os.replace(candidate, target)


def package_artifacts(home, key, npm_name=None):
    if key in NPM_NAMES:
        prefix = home / "packages" / key
        package_name = npm_name or NPM_NAMES[key]
        paths = [prefix / "package-lock.json", prefix / "node_modules" / package_name / "package.json"]
        if key == "claude-mem":
            paths.append(prefix / "node_modules/claude-mem/plugin/scripts/worker-service.cjs")
        if key == "pi":
            paths.extend([prefix / "node_modules" / package_name / relative for relative in (
                "dist/core/tools/path-utils.js", "dist/utils/tools-manager.js")])
        if key == "bun":
            manifest = json.loads(paths[1].read_text(encoding="utf-8"))
            binary = "bin/bun" if package_name.startswith("@oven/bun-linux-") else manifest["bin"]["bun"] if isinstance(manifest["bin"], dict) else manifest["bin"]
            paths.append((prefix / "node_modules" / package_name / binary).resolve(strict=True))
    else:
        python = executable(home / "envs" / key)
        code = (
            "import importlib.metadata as m,json;from pathlib import Path;"
            "d=m.distribution(" + repr(DIST_NAMES[key]) + ");"
            "print(json.dumps([str(d._path/'METADATA'),str(d._path/'direct_url.json')]))"
        )
        paths = [Path(p) for p in json.loads(run([python, "-c", code], cwd=home)) if Path(p).exists()]
        paths.append(python)
    return [{"path": str(path), "sha256": digest(path)} for path in paths]


def check_package(home, key, record):
    artifacts = record.get("artifacts", [])
    if not artifacts:
        return "package identity was not recorded: " + key
    for item in artifacts:
        path = Path(item["path"])
        if not path.is_relative_to(home) or not path.is_file() or digest(path) != item["sha256"]:
            return "installed package missing or changed: " + key
    return None


def install_packages(home, config, python312=None):
    if not PROFILES[config["profile"]]:
        return
    if platform.system() != "Linux":
        raise HomeError("The pinned Hermes board and process owner require Linux. Use the core scaffold on this platform.")
    python = python312 or sys.executable
    version = run([python, "-c", "import sys; print('.'.join(map(str,sys.version_info[:3])))"], cwd=home).strip()
    if tuple(map(int, version.split(".")[:2])) != (3, 12):
        raise HomeError("The complete stack requires Python 3.12. Supply --python312; the core supports Python 3.9+.")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    node = shutil.which("node")
    if not npm or not node:
        raise HomeError("Install Node 22.19+ and npm before the Pi profile.")
    node_version = run([node, "--version"], cwd=home).strip().lstrip("v")
    if tuple(map(int, node_version.split("."))) < (22, 19, 0):
        raise HomeError("Pi requires Node 22.19 or newer.")
    bun_package = None
    if "bun" in PROFILES[config["profile"]]:
        arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "aarch64", "arm64": "aarch64"}.get(platform.machine().lower())
        if arch is None:
            raise HomeError("This Bun distribution is qualified only for Linux x64/aarch64.")
        libc = run([node, "-p", "process.report.getReport().header.glibcVersionRuntime || 'musl'"], cwd=home).strip()
        bun_package = "@oven/bun-linux-" + arch + ("-musl" if libc == "musl" else "")
    env = environment(home)
    env["PIP_CACHE_DIR"] = str(home / "cache/pip")
    env["npm_config_cache"] = str(home / "cache/npm")
    temporary = home / "cache/tmp"
    temporary.mkdir(exist_ok=True)
    env["TMPDIR"] = str(temporary)
    for key in PROFILES[config["profile"]]:
        if key in config["installed"]:
            problem = check_package(home, key, config["installed"][key])
            if problem:
                raise HomeError(problem + "; inspect the retained environment before repair.")
            continue
        print(f"Installing {key}: {PINS[key]}", flush=True)
        npm_name = None
        if key in NPM_NAMES:
            prefix = home / "packages" / key
            prefix.mkdir(exist_ok=True)
            # npm.cmd is a Windows command script. Invoke npm's JS CLI directly.
            npm_cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
            command = [node, npm_cli] if npm_cli.is_file() else [npm]
            npm_name = bun_package if key == "bun" else NPM_NAMES[key]
            requirement = npm_name + "@" + PINS["bun"].rsplit("@", 1)[1] if key == "bun" else PINS[key]
            output = run([*command, "install", "--prefix", prefix, "--save-exact", "--no-audit", "--no-fund", "--prefer-offline", requirement], cwd=home, env=env)
            actual = json.loads((prefix / "node_modules" / npm_name / "package.json").read_text())["version"]
        else:
            target = home / "envs" / key
            if not executable(target).exists():
                run([python, "-m", "venv", str(target)], cwd=home, env=env)
            requirement = PINS[key]
            if key in GIT_SOURCES:
                url, commit = GIT_SOURCES[key]
                checkout = home / "packages" / (key + "-source")
                if not checkout.exists():
                    checkout.mkdir()
                    run(["git", "init", "--quiet", str(checkout)], cwd=home, env=env)
                # Fetch one exact source object. Install the verified checkout
                # directly; pip's local clone does not handle shallow roots.
                run(["git", "-C", checkout, "fetch", "--depth", "1", url, commit], cwd=home, env=env)
                run(["git", "-C", checkout, "checkout", "--detach", commit], cwd=home, env=env)
                observed = run(["git", "-C", checkout, "rev-parse", "HEAD"], cwd=home, env=env).strip()
                if observed != commit:
                    raise HomeError("Fetched source commit mismatch: " + key)
                requirement = str(checkout)
            install_args = ["--editable", requirement] if key == "hermes" else [requirement]
            output = run([executable(target), "-m", "pip", "install", *install_args], cwd=home, env=env)
            actual = run([executable(target), "-m", "pip", "freeze"], cwd=home, env=env)
            (target / "installed-freeze.txt").write_text(actual, encoding="utf-8")
            run([executable(target), "-m", "pip", "check"], cwd=home, env=env)
        (home / "logs" / f"install-{key}.log").write_text(output, encoding="utf-8")
        config["installed"][key] = {"requested": PINS[key], "observed": actual,
                                    "artifacts": package_artifacts(home, key, npm_name), "npm_name": npm_name,
                                    "running": "not_started", "acceptance": "not_run"}
        save_status(home, config)
    memory_python = executable(home / "envs/mempalace")
    memory_wrapper = home / "runtime/harness/memory_runtime.py"
    if not config.get("memory_runtime"):
        config["memory_runtime"] = json.loads(run([memory_python, "-B", memory_wrapper,
                                                  "--home", home, "--bind"], cwd=home, env=env))
        save_status(home, config)
    shim = home / "bin/mempalace"
    expected_shim = "#!/bin/sh\nexec " + shlex.join([str(memory_python), "-B", str(memory_wrapper),
                                                    "--home", str(home), "cli", "--"]) + ' "$@"\n'
    if not shim.exists():
        with shim.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(expected_shim)
        shim.chmod(0o700)
    if shim.is_symlink() or shim.read_text(encoding="utf-8") != expected_shim:
        raise HomeError("Managed memory CLI changed; inspect before recovery.")
    config["memory_cli_sha256"] = digest(shim)
    save_status(home, config)
    binding = home / "state/framework-binding.json"
    if not config.get("framework_binding_sha256"):
        result = json.loads(run([executable(home / "envs/framework"), "-B",
                                 home / "runtime/adapters/pi/intake/framework_binding.py",
                                 "--verify" if binding.exists() else "--output", binding], cwd=home, env=env))
        config["framework_binding_sha256"] = result["sha256"]
        save_status(home, config)
    # Initializing a new empty palace must never inspect the user's existing one.
    if not (home / "state/mempalace-initialization.json").exists():
        run([shim, "init", "--yes", "--no-llm",
             "--palace", str(home / "memory/palace"), str(home / "memory/initial-source")],
            cwd=home, env=env, input="n\n")
        (home / "memory/palace").mkdir(exist_ok=True)
        write_json(home / "state/mempalace-initialization.json", {
            "status": "configured", "palace": str(home / "memory/palace"),
            "source": str(home / "memory/initial-source"), "semantic_acceptance": "not_run",
        })
    if not (home / "state/board-installation.json").exists():
        result = board(home, {"action": "project_admit", "project_root": str(home), "initialize": True,
                              "native_authority": "Owner requested this fresh agent-home installation.",
                              "target": "Maintain this private agent home", "why": "Retain configuration, context and project routing"})
        write_json(home / "state/board-installation.json", result)


def board(home, request):
    env = environment(home)
    raw = run([env["PI_PROJECT_KANBAN_PYTHON"], "-B", env["PI_PROJECT_KANBAN_ADAPTER"]],
              cwd=home, env=env, input=json.dumps(request), timeout=60)
    value = json.loads(raw)
    if not value.get("ok"):
        raise HomeError("Board rejected the request: " + str(value.get("error")))
    return value


def doctor(home):
    home, config = load(home)
    failures, pending = [], []
    runtime = home / "runtime"
    manifest = runtime / "runtime-manifest.json"
    if digest(manifest) != config["runtime_manifest_sha256"]:
        failures.append("runtime manifest changed")
    for item in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        path = (runtime / item["path"]).resolve()
        if not path.is_relative_to(runtime) or not path.is_file() or digest(path) != item["sha256"]:
            failures.append("runtime source changed: " + item["path"])
    for key in PROFILES[config["profile"]]:
        if key not in config["installed"]:
            failures.append("package not installed: " + key)
        else:
            problem = check_package(home, key, config["installed"][key])
            if problem:
                failures.append(problem)
    if config["profile"] != "core" and "framework" in config["installed"]:
        binding = home / "state/framework-binding.json"
        if not binding.is_file() or digest(binding) != config.get("framework_binding_sha256"):
            failures.append("Framework target binding missing or changed")
    if config["profile"] != "core" and "mempalace" in config["installed"]:
        if not config.get("memory_runtime") or not (home / "bin/mempalace").is_file() \
                or digest(home / "bin/mempalace") != config.get("memory_cli_sha256"):
            failures.append("memory runtime/cache binding missing or changed")
    registry = home / "state/validated-memory.jsonl"
    if not registry.is_file() or digest(registry) != config.get("validated_registry_sha256"):
        failures.append("validated memory registry changed without reviewed promotion")
    compaction = home / "state/bounded-compaction.json"
    if not compaction.is_file() or digest(compaction) != config.get("bounded_compaction_sha256"):
        failures.append("bounded compaction selectors changed without reviewed configuration")
    if platform.system() != "Linux":
        pending.append("Linux process ownership is unavailable; inspection profile only")
    if config["profile"] != "core":
        marker = home / "state/board-installation.json"
        if not marker.is_file():
            failures.append("native Hermes board initialization not verified")
        elif not any("hermes" in error for error in failures):
            try:
                before = json.loads(marker.read_text(encoding="utf-8"))
                current = board(home, {"action": "status", "project_root": str(home)})
                expected = before["result"]["identity"]["board_id"]
                if current["result"].get("board_id") != expected:
                    failures.append("native board identity changed")
            except (HomeError, KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
                failures.append("native board readback failed: " + str(error))
    pending.extend(["current-agent personalization", "local model request", "memory search/write/readback",
                    "native positive and refusal hook checks", "root-outcome acceptance on this host"])
    return {"schema": SCHEMA, "status": "failed" if failures else "scaffolded",
            "home": str(home), "failures": failures, "pending_acceptance": pending,
            "authority": "none", "running": "not_observed"}


def launch(home, args, project_root=None):
    home, config = load(home)
    report = doctor(home)
    if report["failures"]:
        raise HomeError("Run doctor and resolve installation failures before launch.")
    node = shutil.which("node")
    cli = home / "packages/pi/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
    if not node or not cli.is_file():
        raise HomeError("Pi is not installed in this home.")
    cwd = home
    if project_root is not None:
        cwd = (home / "projects" / project_root).resolve(strict=True)
        board(home, {"action": "project_admit", "project_root": str(cwd)})
    palace(home, "start")
    # Explicit provider/model and fresh isolated profile prevent ambient defaults.
    return subprocess.call([node, str(cli), "--provider", "local", "--model", config["model"], *args], cwd=cwd, env=environment(home))


def palace(home, operation):
    home, config = load(home)
    if "mempalace" not in config["installed"] or check_package(home, "mempalace", config["installed"]["mempalace"]):
        raise HomeError("Install and verify MemPalace before managing its hub.")
    wrapper = home / "runtime/harness/memory_runtime.py"
    output = run([executable(home / "envs/mempalace"), "-B", wrapper,
                  "--home", home, "hub-" + operation], cwd=home, env=environment(home), timeout=75)
    return json.loads(output)


def project(home, name):
    home, config = load(home)
    if "hermes" not in config["installed"] or check_package(home, "hermes", config["installed"]["hermes"]):
        raise HomeError("Install and verify the Pi profile before creating a project board.")
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in name):
        raise HomeError("Use a project name with letters, digits, hyphens or underscores.")
    root = home / "projects" / name
    if root.exists():
        raise HomeError("Project already exists; preserve its identity and board.")
    root.mkdir(mode=0o700)
    (root / "AGENTS.md").write_text("# Project instructions\n\nRead the agent home's instructions and this project's .icm/workspace/ACTIVE-CHECKPOINT.md.\nKeep the owner outcome, source evidence, failures and next action current.\n", encoding="utf-8")
    (root / ".gitignore").write_text(".env\n.env.*\n!.env.example\n.icm/project.json\n.icm/workspace/artifacts/\n.pi-workflow/\n.enforcement/\n.ssot/\n", encoding="utf-8")
    run(["git", "init", "--quiet", str(root)], cwd=home)
    return board(home, {"action": "project_admit", "project_root": str(root), "initialize": True,
                        "native_authority": "Owner explicitly created this project using agent-home project.",
                        "target": name, "why": "Keep project source, instructions, board and verified work together"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install")
    install.add_argument("--source", type=Path, default=ROOT)
    install.add_argument("--profile", choices=PROFILES, default="full")
    install.add_argument("--base-url")
    install.add_argument("--model")
    install.add_argument("--name", default="Owner")
    install.add_argument("--python312")
    install.add_argument("--context-window", type=int, default=8192, help="Actual server context limit; default8192 is an unprobed conservative configuration")
    install.add_argument("--max-output", type=int, default=2048)
    install.add_argument("--offline", action="store_true", help="Create files only; do not install optional packages")
    commands.add_parser("doctor")
    resume = commands.add_parser("resume-install")
    resume.add_argument("--python312")
    start = commands.add_parser("start")
    start.add_argument("--project", type=Path)
    start.add_argument("pi_args", nargs=argparse.REMAINDER)
    new = commands.add_parser("project")
    new.add_argument("name")
    memory = commands.add_parser("memory")
    memory.add_argument("operation", choices=("start", "stop", "status", "search"))
    memory.add_argument("--query")
    palace_command = commands.add_parser("palace", help="Manage this home's native MemPalace single-writer hub")
    palace_command.add_argument("operation", choices=("start", "stop", "status"))
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            home = args.home or Path(input("New agent-home directory: ").strip())
            url = args.base_url or input("Local OpenAI-compatible endpoint [http://127.0.0.1:8080/v1]: ").strip() or "http://127.0.0.1:8080/v1"
            model = args.model or input("Exact local model ID: ").strip()
            config = scaffold(home, source=args.source, profile=args.profile, base_url=url, model=model,
                              name=args.name, offline=args.offline, context_window=args.context_window, max_output=args.max_output)
            home = Path(config["home"])
            if not args.offline:
                install_packages(home, config, args.python312)
            print(json.dumps(doctor(home), indent=2))
            return 0 if args.offline or not doctor(home)["failures"] else 1
        if args.home is None:
            raise HomeError("Supply --home or use the installed agent-home.py launcher.")
        if args.command == "doctor":
            result = doctor(args.home)
            print(json.dumps(result, indent=2))
            return 1 if result["failures"] else 0
        if args.command == "resume-install":
            home, config = load(args.home)
            install_packages(home, config, args.python312)
            result = doctor(home)
            print(json.dumps(result, indent=2))
            return 1 if result["failures"] else 0
        if args.command == "start":
            return launch(args.home, args.pi_args, args.project)
        if args.command == "project":
            print(json.dumps(project(args.home, args.name), indent=2))
            return 0
        if args.command == "palace":
            print(json.dumps(palace(args.home, args.operation), indent=2))
            return 0
        if args.command == "memory":
            from harness.claude_memory import invoke
            result = invoke(args.home, args.operation, event=args.query)
            print(json.dumps(result, indent=2))
            return 1 if result.get("status") == "stop_unconfirmed" else 0
    except (HomeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error), "authority": "none"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
