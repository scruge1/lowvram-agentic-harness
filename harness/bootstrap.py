"""Finish native runtime provisioning, then invoke the existing home installer.

install.sh owns the pre-Python step. Runtime paths are permanent: installed
virtual environments retain references to this managed Python installation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import types


NODE_VERSION = "22.23.2"
NODE_NAME = "node-v22.23.2-linux-x64"
NODE_URL = "https://nodejs.org/download/release/v22.23.2/" + NODE_NAME + ".tar.xz"
NODE_SHA256 = "d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307"
NODE_BYTES = 31058332
PYTHON_KEY = "cpython-3.12.13-linux-x86_64-gnu"
UV_SHA256 = "1db18b5e76fa645a7f3865773139bdec8e2d46adbdbb35e7410b34fa8015ccd2"
RESERVE = 2 * 1024 ** 3
SOURCE = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    # install.sh uses isolated Python; import only this complete checkout.
    sys.path.insert(0, str(SOURCE))
LOCAL_CPU_MEMORY = 20 * 1024 ** 3
LOCAL_CPU_STORAGE = 20 * 1024 ** 3
NATIVE_PIDFD_SOURCE = "adapters/pi/project-workflow/native_pidfd.py"
NATIVE_PIDFD_SHA256 = "0bec3bbf24319a07206388771f7f03bb95ae989d00b1fba40959437dae556423"


class BootstrapError(ValueError):
    pass


def require(value, message):
    if not value:
        raise BootstrapError(message)


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def safe_file(path):
    require(path.is_file() and not path.is_symlink() and path.resolve() == path,
            "Runtime input is missing or redirected: " + str(path))


def publish_json(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(name, path)


def command(argv, *, env, timeout=60, cwd=None):
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                            timeout=timeout, check=False)
    require(result.returncode == 0, "Native command failed; retained state: " + " ".join(map(str, argv[:2]))
            + ": " + (result.stderr or result.stdout)[-2000:])
    return result.stdout.strip()


def owned_environment(root, node=None):
    # Explicit native tools and OS certificate stores; no inherited provider,
    # proxy, Python import, uv mirror, Node preload or shell-profile settings.
    value = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
             "TMPDIR": str(root / "tmp"), "XDG_CACHE_HOME": str(root / "cache"),
             "PIP_CACHE_DIR": str(root / "cache/pip"), "npm_config_cache": str(root / "cache/npm"),
             "NODE_COMPILE_CACHE": str(root / "cache/node"), "PYTHONDONTWRITEBYTECODE": "1",
             "UV_CACHE_DIR": str(root / "cache/uv"), "UV_PYTHON_CACHE_DIR": str(root / "cache/python")}
    if node is not None:
        value["PATH"] = str(node.parent) + os.pathsep + value["PATH"]
    return value


def process_api_preflight(source=SOURCE):
    """Probe this interpreter through the exact canonical public-pidfd facade.

    Signal zero targets only this process; the helper closes its self pidfd.
    No system interpreter, PID signal fallback or global monkeypatch is used.
    """
    require(sys.platform == "linux", "Managed process ownership requires Linux")
    source = Path(source).absolute()
    require(source.resolve(strict=True) == source, "Process-API source root is redirected")
    helper = source / NATIVE_PIDFD_SOURCE
    safe_file(helper)
    raw = helper.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == NATIVE_PIDFD_SHA256, "Canonical process-API helper byte drift")
    module = types.ModuleType("bootstrap_native_pidfd")
    module.__file__, module.__package__ = str(helper), ""
    exec(compile(raw, str(helper), "exec"), module.__dict__)
    try:
        selected = module.require_support()
    except OSError as error:
        raise BootstrapError("Managed Python process-API preflight failed before package installation: " + str(error)) from error
    require(isinstance(selected, dict) and set(selected) == {"pidfd_open", "pidfd_send_signal"}
            and all(value in {"python", "libc"} for value in selected.values()),
            "Managed Python process-API support is unavailable; package installation was not started")
    return {"schema": "bootstrap-process-api/v1", "python": sys.executable,
            "python_version": platform.python_version(), "source": str(helper),
            "source_sha256": NATIVE_PIDFD_SHA256, "backend": selected,
            "probe": "self pidfd, signal zero, descriptor closed"}


def download(url, destination, expected_sha256, expected_bytes, *, env, runner=command):
    """Native curl resume; exact size/hash gate promotion, never overwrite conflict.

    This transfers the accepted private download recipe's conflict/resume/hash/
    free-space rules, not its Rig paths, six-service queue or model selection.
    """
    if destination.exists() or destination.is_symlink():
        safe_file(destination)
        require(destination.stat().st_size == expected_bytes and sha256(destination) == expected_sha256,
                "Existing final download conflicts; original preserved")
        return destination
    partial = destination.with_name(destination.name + ".partial")
    if partial.exists() or partial.is_symlink():
        safe_file(partial)
        require(partial.stat().st_size <= expected_bytes, "Oversized partial preserved")
    require(shutil.disk_usage(destination.parent).free >= expected_bytes + RESERVE,
            "Download would cross the runtime free-space reserve")
    if not partial.exists() or partial.stat().st_size != expected_bytes:
        runner(["/usr/bin/curl", "-q", "--fail", "--silent", "--show-error", "--location",
                "--continue-at", "-", "--connect-timeout", "20", "--max-time", "600",
                "--max-filesize", str(expected_bytes), "--proto", "=https", "--proto-redir", "=https",
                "--noproxy", "*", "--output", str(partial), url], env=env, timeout=620)
    safe_file(partial)
    require(partial.stat().st_size == expected_bytes and sha256(partial) == expected_sha256,
            "Downloaded size/hash differs; failed partial retained")
    os.link(partial, destination)  # Atomic, absent-only promotion.
    partial.unlink()
    return destination


def extract_node(archive, root, *, env):
    target = root / NODE_NAME
    require(not target.exists() and not target.is_symlink(), "Existing Node tree needs its retained receipt; not overwritten")
    stage = Path(tempfile.mkdtemp(prefix="node-stage-", dir=root))
    with tarfile.open(archive, "r:xz") as stream:
        members = stream.getmembers()
        require(len(members) <= 10000, "Node archive entry count exceeds its bound")
        for item in members:
            name = PurePosixPath(item.name)
            require(not name.is_absolute() and ".." not in name.parts and name.parts[0] == NODE_NAME,
                    "Unexpected native Node archive path")
            require(item.isfile() or item.isdir() or item.issym() or item.islnk(), "Special Node archive file refused")
            if item.issym() or item.islnk():
                resolved = (stage / name.parent / item.linkname).resolve() if item.issym() else (stage / item.linkname).resolve()
                require(resolved.is_relative_to(stage / NODE_NAME), "Node archive link escapes its prefix")
    command(["/usr/bin/tar", "-xJf", str(archive), "--no-same-owner", "--no-same-permissions", "-C", str(stage)], env=env)
    require(not target.exists(), "Node destination appeared concurrently; candidate retained")
    os.rename(stage / NODE_NAME, target)
    return target


def inventory(prefix):
    require(prefix.is_dir() and prefix.resolve() == prefix, "Runtime prefix is missing or redirected")
    files = []
    for path in sorted(prefix.rglob("*")):
        relative = path.relative_to(prefix).as_posix()
        if path.is_symlink():
            require(path.resolve().is_relative_to(prefix), "Runtime symlink escapes its prefix")
            files.append({"path": relative, "link": os.readlink(path)})
        elif path.is_file():
            files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
        else:
            require(path.is_dir(), "Special runtime file refused")
    require(len(files) <= 20000, "Runtime inventory exceeds its bound")
    return files


def provision(home, root):
    require(sys.platform == "linux" and platform.machine() == "x86_64", "Linux x64 bootstrap required")
    require(home.is_absolute() and home.resolve() == home and root == Path(str(home) + "-runtimes")
            and root.resolve() == root, "Use the reviewed exact home/runtime binding")
    safe_file(root / "bootstrap-owner")
    require((root / "bootstrap-owner").read_text().strip() == "agent-home-bootstrap/v1:" + str(home), "Runtime ownership differs")
    expected_python = root / "python" / PYTHON_KEY / "bin/python3.12"
    require(Path(sys.executable).absolute() == expected_python and platform.python_version() == "3.12.13",
            "Use this bootstrap's exact managed Python")
    for name in ("downloads", "cache", "tmp", "python", "bin"):
        path = root / name
        require(path.is_dir() and path.resolve() == path, "Owned runtime subdirectory differs")
    process_api = process_api_preflight()
    env = owned_environment(root)
    safe_file(root / "bin/uv")
    require(command([str(root / "bin/uv"), "--version"], env=env).split()[:2] == ["uv", "0.11.25"], "Native uv version differs")
    uv_archive = root / "downloads/uv-0.11.25.tar.gz"
    safe_file(uv_archive)
    require(sha256(uv_archive) == UV_SHA256, "uv archive drift")
    archive = download(NODE_URL, root / "downloads" / (NODE_NAME + ".tar.xz"), NODE_SHA256, NODE_BYTES, env=env)
    receipt_file = root / "runtime-receipt.json"
    target = root / NODE_NAME
    if target.exists() or target.is_symlink():
        safe_file(receipt_file)
        require(receipt_file.stat().st_size <= 8 * 1024 * 1024, "Runtime receipt exceeds its bound")
        prior = json.loads(receipt_file.read_text())
        require(prior.get("home") == str(home) and prior.get("runtime_root") == str(root)
                and prior.get("node", {}).get("files") == inventory(target), "Existing Node runtime drift; original retained")
        require(prior.get("python", {}).get("sha256") == sha256(expected_python), "Managed Python drift")
    else:
        extract_node(archive, root, env=env)
    node = target / "bin/node"
    safe_file(node)
    npm = target / "lib/node_modules/npm/bin/npm-cli.js"
    safe_file(npm)
    env = owned_environment(root, node)
    require(command([str(node), "--version"], env=env) == "v" + NODE_VERSION, "Native Node version differs")
    npm_version = command([str(node), str(npm), "--version"], env=env)
    receipt = {"schema": "agent-home-bootstrap/v1", "home": str(home), "runtime_root": str(root),
               "observed_at": datetime.now(timezone.utc).isoformat(), "status": "runtimes_installed",
               "qualification": "native_runtime_versions_only; no agent/model/server acceptance",
               "uv": {"version": "0.11.25", "path": str(root / "bin/uv"), "sha256": sha256(root / "bin/uv"), "archive_sha256": UV_SHA256},
               "python": {"version": "3.12.13", "build": "20260623", "key": PYTHON_KEY,
                          "path": str(expected_python), "sha256": sha256(expected_python)},
               "node": {"version": NODE_VERSION, "path": str(node), "sha256": sha256(node),
                        "runtime_root": str(target), "npm_version": npm_version, "files": inventory(target)},
               "downloads": [{"url": NODE_URL, "bytes": NODE_BYTES, "sha256": NODE_SHA256}],
               "source": str(SOURCE), "process_api": process_api, "changes": [str(root)], "not_provisioned": ["model_weights", "model_server", "OS_packages", "drivers", "GPU_jobs"]}
    if not receipt_file.exists():
        publish_json(receipt_file, receipt)
    return receipt, env


def installer_command(receipt, arguments, *, resume=False):
    forbidden = ("--home", "--python312", "--managed-node", "--source")
    require(all(not any(value == key or value.startswith(key + "=") for key in forbidden) for value in arguments),
            "Do not override bootstrap-owned installer bindings")
    require(not resume or not arguments, "Resume uses the existing home configuration; omit initial install options")
    return [receipt["python"]["path"], "-B", "-m", "harness.home", "--home", receipt["home"],
            "resume-install" if resume else "install", "--python312", receipt["python"]["path"],
            "--managed-node", receipt["node"]["path"], *arguments]


def local_cpu_options(arguments):
    """Keep this finite candidate distinct from arbitrary installer overrides."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False, exit_on_error=False)
    parser.add_argument("--profile", choices=("agent", "pi", "full"), default="agent")
    parser.add_argument("--name", default="Owner")
    require(sum(value == "--profile" or value.startswith("--profile=") for value in arguments) <= 1
            and sum(value == "--name" or value.startswith("--name=") for value in arguments) <= 1,
            "Supply each local CPU install option once")
    try:
        options, unknown = parser.parse_known_args(arguments)
    except argparse.ArgumentError as error:
        raise BootstrapError("Invalid local CPU option: " + str(error)) from error
    require(not unknown, "--local-cpu accepts only --profile agent|pi|full and --name; omit endpoint/model/budget/offline/resume overrides")
    require(options.name.strip() and not any(char in options.name for char in "\r\n\0"), "Use a nonempty one-line owner name")
    return options


def local_cpu_plan(home, *, profile="agent"):
    """Authoritative read-only candidate plan from the existing native pin file."""
    from harness import hardware_probe, home as factory, model_service
    require(home.is_absolute() and home.resolve() == home and not home.exists() and not home.is_symlink(),
            "Local CPU setup requires a new canonical absolute home")
    require(not home.is_relative_to(SOURCE) and not SOURCE.is_relative_to(home), "Installer source and home must be separate trees")
    require(all((SOURCE / "harness/templates/agent-home" / name).is_file() for name in factory.REQUIRED_TEMPLATES),
            "Required home templates are missing; no model transfer was started")
    require(profile in {"agent", "pi", "full"}, "Select agent, pi or the explicit full candidate")
    if profile == "full":
        factory.owned_full_sources(SOURCE)
    pins = json.loads(model_service.PINS.read_text(encoding="utf-8"))
    spec = model_service.specification(model=pins["model"]["id"], backend="cpu", context=32768, max_output=4096,
                                       threads=8, batch_threads=8, ram_required_bytes=LOCAL_CPU_MEMORY)
    report = model_service.plan(home, spec)
    available = hardware_probe.ram_info().get("available_gb")
    report["memory"] = {"available_gb": available, "required_bytes": LOCAL_CPU_MEMORY,
                        "sufficient": available is not None and available * 1e9 >= LOCAL_CPU_MEMORY}
    affinity = getattr(os, "sched_getaffinity", None)
    cpus = len(affinity(0)) if affinity is not None else os.cpu_count()
    report["cpu"] = {"available_logical_cpus": cpus, "source": "process_affinity" if affinity is not None else "os_cpu_count",
                     "required": 8, "sufficient": cpus is not None and cpus >= 8, "exclusive_reservation": False}
    report["storage"]["required_free_bytes"] = max(LOCAL_CPU_STORAGE, report["storage"]["required_free_bytes"])
    report["storage"]["sufficient"] = report["storage"]["free_bytes"] >= report["storage"]["required_free_bytes"]
    report["scope"] = "CPU candidate; no task-quality, speed, GPU-fit or vision acceptance"
    report["additional_downloads"] = "Pinned agent packages, browser and first-use embeddings; total bytes unknown before resolution"
    if profile == "full":
        report["full_bundle"] = {"selected_packages": {key: factory.PINS[key] for key in factory.PROFILES["full"]},
                                 "observer": "Existing Pi input, tool-result and agent-settled capture hooks; foreground worker retains a shared home lease until explicit memory stop",
                                 "experimental_labs": ["harness2", "deepseek"],
                                 "acceptance": "candidate; complete owned full install, authenticated capture, nonce rotation and useful recall remain unqualified"}
    return report


def install_local_cpu(receipt, arguments):
    """Compose existing provision/start/capture/factory APIs without replay."""
    from harness import model_service, model_service_handoff, model_service_setup
    options = local_cpu_options(arguments)
    home, root = Path(receipt["home"]), Path(receipt["runtime_root"])
    report = local_cpu_plan(home, profile=options.profile)
    require(report["cpu"]["sufficient"], "Local CPU setup requires at least 8 available affinity/logical CPUs before model transfer")
    require(report["memory"]["sufficient"], "Local CPU setup requires at least 20 GiB available system RAM before model transfer")
    require(report["storage"]["sufficient"], "Local CPU setup requires at least 20 GiB free on the selected volume before model transfer")
    target = root / "installer-handoff.json"
    require(not target.exists() and not target.is_symlink(), "Prior installer handoff exists; inspect its evidence instead of replaying local CPU setup")
    operation = {"schema": "agent-home-bootstrap-handoff/v1", "home": str(home), "mode": "local_cpu",
                 "plan": report, "automatic_replay": False, "claim": "factory/protocol only; model task capability remains separate"}
    def phase(value):
        operation["phase"] = value
        publish_json(target, operation)
    try:
        phase("provisioning_model")
        model_service.provision(home, report["specification"], allow_download=True)
        phase("starting_pre_home")
        model_service.start(home, startup_timeout=120)
        phase("capturing_pre_home")
        selection = model_service_handoff.capture(home)
        phase("creating_home")
        result = model_service_setup.create(home, selection=selection, source=SOURCE, profile=options.profile, name=options.name,
                                            python312=receipt["python"]["path"], managed_node=Path(receipt["node"]["path"]))
        operation.update(result=result, exit_code=0)
        phase("complete")
        print(json.dumps(result, indent=2), flush=True)
        print("Managed command: " + str(home / "bin/harness-agent"), flush=True)
        return 0
    except BaseException as error:
        operation.update(failed_stage=operation["phase"], error=type(error).__name__ + ": " + str(error), exit_code=1,
                         recovery="Preserve this handoff and state/model-service receipts. Inspect native status; use explicit service stop/recovery and doctor/resume-install for a partial home. Do not replay uncertain setup.")
        phase("failed")
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--runtimes-only", action="store_true")
    parser.add_argument("--resume-install", action="store_true")
    parser.add_argument("--local-cpu", action="store_true")
    parser.add_argument("--confirmed", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--plan", action="store_true", help="Read-only authoritative local CPU plan")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        if args.local_cpu:
            require(not args.runtimes_only and not args.resume_install, "Local CPU setup cannot mix runtime-only or resume modes")
            options = local_cpu_options(arguments)
            report = local_cpu_plan(args.home, profile=options.profile)
            print(json.dumps(report, indent=2), flush=True)
            if args.plan:
                return 0
            require(args.confirmed, "Review install.sh --local-cpu --plan, then confirm through install.sh or its --yes option")
            require(report["cpu"]["sufficient"] and report["memory"]["sufficient"] and report["storage"]["sufficient"],
                    "Local CPU setup requires at least 8 available affinity/logical CPUs, 20 GiB available RAM and 20 GiB free storage")
        else:
            require(not args.plan, "Use install.sh --plan for the pre-Python runtime plan")
        receipt, env = provision(args.home, args.runtime_root)
        print(json.dumps({"status": receipt["status"], "runtime_root": receipt["runtime_root"],
                          "python": receipt["python"]["path"], "node": receipt["node"]["path"],
                          "process_api": receipt["process_api"],
                          "receipt": str(args.runtime_root / "runtime-receipt.json")}), flush=True)
        if args.runtimes_only:
            return 0
        if args.local_cpu:
            return install_local_cpu(receipt, arguments)
        if args.home.exists():
            require(args.resume_install, "Home exists; preserve it and use explicit --resume-install without initial install options")
            config = json.loads((args.home / "home.json").read_text())
            require(config.get("schema") == "agent-home/v1" and config.get("home") == str(args.home), "Existing home identity differs")
        else:
            require(not args.resume_install, "There is no existing home to resume")
        command_args = installer_command(receipt, arguments, resume=args.resume_install)
        # The existing installer retains its prompts, package pins and receipts.
        # HOME stays real; PATH is changed only for this owned child process.
        result = subprocess.run(command_args, cwd=SOURCE, env=env, check=False)
        publish_json(args.runtime_root / "installer-handoff.json", {"schema": "agent-home-bootstrap-handoff/v1",
                     "home": str(args.home), "argv": command_args, "exit_code": result.returncode,
                     "claim": "installer_exit_only; task/model acceptance remains separate"})
        return result.returncode
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"schema": "agent-home-bootstrap/v1", "status": "refused", "error": str(error),
                          "recovery": "Preserve the owned runtime directory and failed partials; correct the stated conflict."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
