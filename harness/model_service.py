"""Explicit home-owned provisioning and lifetime of upstream llama-server.

This reuses bootstrap.download and the native CPU-MoE serving recipe from
SETUP.md/autotune_offload.py. It neither chooses a capable model nor tunes,
evicts, restarts another service, installs drivers or proxies inference.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

from . import bootstrap, hardware_probe, home_entry


SCHEMA = "local-model-service/v1"
PINS = Path(__file__).with_name("model-service-pins.json")
PIDFD_PATH = Path(__file__).resolve().parents[1] / "adapters/pi/project-workflow/native_pidfd.py"
PIDFD_SHA256 = "0bec3bbf24319a07206388771f7f03bb95ae989d00b1fba40959437dae556423"
RESERVE = 2 * 1024 ** 3
# Child handles exist only to reap children started by this Python process.
# Persistent ownership always comes from the bound receipt and kernel lifetime.
_CHILDREN = {}


class ModelServiceError(ValueError):
    pass


def _pidfd():
    """Load only the frozen shared public facade, never an ambient module."""
    bootstrap.safe_file(PIDFD_PATH)
    raw = PIDFD_PATH.read_bytes()
    require(len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == PIDFD_SHA256, "Native pidfd helper byte drift")
    module = types.ModuleType("model_service_native_pidfd")
    module.__file__, module.__package__ = str(PIDFD_PATH), ""
    exec(compile(raw, str(PIDFD_PATH), "exec"), module.__dict__)
    return module


def require(value, message):
    if not value:
        raise ModelServiceError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read(path):
    bootstrap.safe_file(path)
    require(path.stat().st_size <= 2 * 1024 ** 2, "Service metadata exceeds its bound")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "Service metadata must be an object")
    return value


def _bound_home(root):
    marker = root / "bootstrap-owner"
    if marker.is_file():
        bootstrap.safe_file(marker)
        return marker.read_text().strip().removeprefix("agent-home-bootstrap/v1:")
    return str(root)


def _home(value, *, planned=False):
    require(sys.platform == "linux" and platform.machine() in ("x86_64", "AMD64"),
            "Native model service currently requires Linux x86_64")
    home = Path(value).expanduser()
    require(home.is_absolute(), "Select an absolute agent home")
    home = home.resolve(strict=False)
    if (home / "bootstrap-owner").is_file():
        target = _bound_home(home)
        require(home == Path(target + "-runtimes") and Path(target).is_absolute(), "Runtime/home binding differs")
        bootstrap.safe_file(home / "bootstrap-owner")
        return home
    runtime = Path(str(home) + "-runtimes")
    if runtime.exists():
        require(runtime.resolve() == runtime and _bound_home(runtime) == str(home), "Permanent runtime ownership differs")
        bootstrap.safe_file(runtime / "bootstrap-owner")
        return runtime
    if not home.exists():
        require(planned, "Provision the selected home's permanent bootstrap runtimes first")
        return runtime
    require(_read(home / "home.json").get("home") == str(home), "Agent home binding differs")
    return home


@contextlib.contextmanager
def _consumer(root):
    target = Path(_bound_home(root))
    if (target / "home.json").is_file():
        with home_entry.consumer(target) as descriptors:
            yield descriptors
    else:
        # Pre-home setup lives in the permanent, bootstrap-owned sibling.
        # There is no active-home generation yet and no home lease is claimed.
        yield ()


def _within(home, relative, *, create=False):
    target = home / relative
    require(target.is_relative_to(home), "Service path escaped its home")
    current = home
    for part in target.relative_to(home).parts:
        current /= part
        require(not current.is_symlink(), "Service paths must not contain symlinks")
    require(target.resolve() == target, "Service path was redirected")
    if create:
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
    return target


@contextlib.contextmanager
def _mutation(home):
    import fcntl
    root = _within(home, "state/model-service", create=True)
    descriptor = os.open(root / "mutation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield root
    except BlockingIOError as error:
        raise ModelServiceError("Another operation owns this home's model service") from error
    finally:
        os.close(descriptor)


def specification(*, model, backend="cpu", context=32768, max_output=4096,
                  threads=4, batch_threads=4, ram_required_bytes, gpu_uuid=None,
                  min_gpu_free_mb=0, gpu_layers=0, n_cpu_moe=0):
    """Build an explicit artifact/resource selection; never infer model fit."""
    pins = _read(PINS)
    require(model == pins["model"]["id"], "Select an explicit known artifact pin, not a catalog recommendation")
    require(backend in ("cpu", "cuda"), "Select cpu or cuda explicitly")
    runtime = {key: value for key, value in pins["runtime"].items() if key not in ("cpu", "cuda")}
    runtime.update(backend=backend, archives=pins["runtime"][backend])
    return {"schema": SCHEMA, "model": pins["model"], "runtime": runtime,
            "resources": {"context": context, "max_output": max_output, "threads": threads, "batch_threads": batch_threads,
                          "ram_required_bytes": ram_required_bytes, "gpu_uuid": gpu_uuid,
                          "min_gpu_free_mb": min_gpu_free_mb, "gpu_layers": gpu_layers, "n_cpu_moe": n_cpu_moe}}


def _validate(spec):
    require(isinstance(spec, dict) and spec.get("schema") == SCHEMA, "Invalid native service specification")
    model, runtime, resources = (spec.get(name) for name in ("model", "runtime", "resources"))
    require(all(isinstance(item, dict) for item in (model, runtime, resources)), "Incomplete service specification")
    require(runtime.get("platform") == "linux-x86_64" and runtime.get("backend") in ("cpu", "cuda"), "Unsupported native runtime")
    for value in (model, runtime):
        require(isinstance(value.get("revision"), str) and re.fullmatch(r"[a-f0-9]{40}", value["revision"]), "Pin an exact upstream revision")
        require(isinstance(value.get("license"), str) and value["license"], "Record the upstream license")
    require(isinstance(model.get("id"), str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}", model["id"]), "Invalid model alias")
    require(isinstance(runtime.get("archives"), list) and 1 <= len(runtime["archives"]) <= 3, "Select exact native archives")
    artifacts = [model, *runtime["archives"]]
    for artifact in artifacts:
        require(isinstance(artifact, dict), "Invalid artifact")
        require(isinstance(artifact.get("name"), str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,180}", artifact["name"]), "Invalid artifact name")
        require(isinstance(artifact.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"]), "Pin the full artifact SHA256")
        require(type(artifact.get("bytes")) is int and artifact["bytes"] > 0, "Pin the exact artifact byte count")
        require(isinstance(artifact.get("license"), str) and artifact["license"], "Record each artifact license")
        url = artifact.get("url", "")
        require(isinstance(url, str) and url.startswith("https://") and "@" not in url.split("/", 3)[2], "Use credential-free HTTPS artifact URLs")
    require(model["name"].endswith(".gguf") and model["revision"] in model["url"], "Pin a single local GGUF revision")
    for archive in runtime["archives"]:
        require(archive["name"].endswith(".tar.gz") and runtime.get("release", "") in archive["url"], "Pin native release tarballs")
        require(type(archive.get("unpacked_max_bytes")) is int and archive["unpacked_max_bytes"] > 0, "Bound archive expansion")
    bounds = {"context": (1024, 1048576), "max_output": (1, 262144), "threads": (1, 256), "batch_threads": (1, 256),
              "ram_required_bytes": (model["bytes"], 2 ** 50), "gpu_layers": (0, 999),
              "n_cpu_moe": (0, 999), "min_gpu_free_mb": (0, 1000000)}
    for key, (lower, upper) in bounds.items():
        value = resources.get(key)
        require(type(value) is int and lower <= value <= upper, "Invalid explicit resource field: " + key)
    require(resources["max_output"] < resources["context"], "Output must leave context for inputs")
    if runtime["backend"] == "cpu":
        require(resources.get("gpu_uuid") is None and resources["gpu_layers"] == 0 and resources["min_gpu_free_mb"] == 0,
                "CPU service must not request a GPU")
    else:
        require(isinstance(resources.get("gpu_uuid"), str) and re.fullmatch(r"GPU-[a-fA-F0-9-]+", resources["gpu_uuid"]), "Select one explicit GPU UUID")
        require(resources["gpu_layers"] > 0 and resources["min_gpu_free_mb"] > 0, "Declare GPU layers and a free-memory requirement")
    return artifacts


def _artifact(home, artifact):
    return _within(home, "cache/model-service/artifacts") / (artifact["sha256"] + "-" + artifact["name"])


def plan(home, spec):
    """Read-only storage/resource plan. This is not fit or capability acceptance."""
    home = _home(home, planned=True)
    artifacts = _validate(spec)
    # Resolve and check the physical selected volume before producer mkdir/copy.
    for name in ("cache/model-service", "state/model-service"):
        _within(home, name)
    required = sum(item["bytes"] for item in artifacts)
    required += sum(item["unpacked_max_bytes"] for item in spec["runtime"]["archives"]) + RESERVE
    volume = home
    while not volume.exists():
        volume = volume.parent
    available = shutil.disk_usage(volume).free
    return {"schema": SCHEMA, "home": _bound_home(home) if home.exists() else str(home).removesuffix("-runtimes"),
            "storage_root": str(home), "specification_sha256": _digest(spec),
            "default_manifest": {"path": str(PINS), "sha256": bootstrap.sha256(PINS)},
            "specification": spec, "storage": {"physical_root": str(home.resolve()), "free_bytes": available,
                                                "required_free_bytes": required, "sufficient": available >= required},
            "downloads": [{"name": item["name"], "url": item["url"], "bytes": item["bytes"], "sha256": item["sha256"],
                           "destination": str(_artifact(home, item))} for item in artifacts],
            "local_inference": "native local GGUF only; no remote provider or automatic fallback",
            "fit": "not_probed", "task_capability": "not_probed", "gpu_permission": "explicit start required"}


def _copy(source, destination, artifact):
    source = Path(source).expanduser()
    require(source.is_absolute(), "Select an absolute local artifact source")
    bootstrap.safe_file(source)
    require(source.stat().st_size == artifact["bytes"] and bootstrap.sha256(source) == artifact["sha256"], "Local artifact source differs")
    if destination.exists() or destination.is_symlink():
        bootstrap.safe_file(destination)
        require(destination.stat().st_size == artifact["bytes"] and bootstrap.sha256(destination) == artifact["sha256"], "Existing artifact conflicts; preserved")
        return
    partial = destination.with_name(destination.name + ".partial")
    require(not partial.exists() and not partial.is_symlink(), "Existing partial preserved; finish or inspect it explicitly")
    with source.open("rb") as incoming, partial.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=1024 ** 2)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    bootstrap.safe_file(partial)
    require(partial.stat().st_size == artifact["bytes"] and bootstrap.sha256(partial) == artifact["sha256"], "Copied artifact differs; partial preserved")
    os.link(partial, destination)
    partial.unlink()


def _extract(archive, destination, limit):
    """Extract bounded regular files and internal relative symlinks only."""
    destination.mkdir(mode=0o700)
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        require(len(members) <= 20000 and sum(item.size for item in members) <= limit, "Native archive exceeds its expansion bound")
        seen, links = set(), []
        for item in members:
            relative = PurePosixPath(item.name)
            require(not relative.is_absolute() and ".." not in relative.parts and str(relative) not in seen, "Unsafe or duplicate native archive path")
            seen.add(str(relative))
            path = destination / relative
            require(path.resolve().is_relative_to(destination), "Native archive escaped its directory")
            if item.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif item.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(item) as incoming, path.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, length=1024 ** 2)
                path.chmod(item.mode & 0o755)
            elif item.issym():
                require(not PurePosixPath(item.linkname).is_absolute(), "Native archive contains an absolute link")
                path.parent.mkdir(parents=True, exist_ok=True)
                links.append((path, item.linkname))
            else:
                raise ModelServiceError("Native archive contains a special file or hard link")
        for path, target in links:
            require((path.parent / target).resolve().is_relative_to(destination), "Native library link escaped its directory")
            path.symlink_to(target)
        for path, _ in links:
            require(path.resolve(strict=True).is_relative_to(destination), "Native library link escaped or is dangling")


def _inventory(root):
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            require(path.resolve(strict=True).is_relative_to(root), "Native runtime link escaped")
            result.append({"path": relative, "link": os.readlink(path)})
        elif path.is_file():
            result.append({"path": relative, "bytes": path.stat().st_size, "sha256": bootstrap.sha256(path)})
    return result


def _environment(home, runtime, spec):
    paths = sorted({str(path.parent) for path in runtime.rglob("*.so*") if path.is_file()})
    binaries = [path for path in (runtime / "0").rglob("llama-server") if path.is_file()]
    require(len(binaries) == 1, "Native backend directory is ambiguous")
    backend = spec["runtime"]["backend"]
    return {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
            "XDG_CACHE_HOME": str(home / "cache"), "TMPDIR": str(home / "cache/model-service/tmp"),
            "LD_LIBRARY_PATH": os.pathsep.join(paths), "GGML_BACKEND_DL_PATH": str(binaries[0].parent),
            "CUDA_VISIBLE_DEVICES": spec["resources"]["gpu_uuid"] if backend == "cuda" else "",
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "GGML_VK_VISIBLE_DEVICES": ""}


def _load(home, *, verify=True):
    root = _within(home, "state/model-service")
    receipt = _read(root / "provision.json")
    spec = receipt.get("specification")
    _validate(spec)
    require(receipt.get("home") == _bound_home(home) and receipt.get("storage_root") == str(home)
            and receipt.get("specification_sha256") == _digest(spec), "Provision receipt binding differs")
    runtime = _within(home, "cache/model-service/runtime-" + _digest(spec))
    binary = runtime / receipt["binary_relative"]
    require(binary.resolve().is_relative_to(runtime) and binary.name == "llama-server", "Native binary escaped its runtime")
    bootstrap.safe_file(binary)
    if verify:
        require(_inventory(runtime) == receipt["runtime_files"], "Native runtime bytes changed")
        model = _artifact(home, spec["model"])
        bootstrap.safe_file(model)
        require(model.stat().st_size == spec["model"]["bytes"] and bootstrap.sha256(model) == spec["model"]["sha256"], "Model bytes changed")
    return receipt, runtime, binary


def _inspect(binary, option, env, home):
    # Native llama.cpp version/help writes to stderr on accepted releases.
    result = subprocess.run([str(binary), option], cwd=home, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=20, check=False)
    require(result.returncode == 0 and len(result.stdout) <= 131072, "Native inspection failed or exceeded its bound")
    return result.stdout.strip()


def provision(home, spec, *, allow_download=False, sources=None):
    """Copy explicit local artifacts or download explicitly permitted pins."""
    home = _home(home)
    report = plan(home, spec)
    artifacts, sources = _validate(spec), sources or {}
    require(set(sources).issubset({item["name"] for item in artifacts}), "Unknown local artifact source")
    for artifact in artifacts:
        require(allow_download or artifact["name"] in sources or _artifact(home, artifact).is_file(),
                "Missing artifact; select a verified local source or explicitly allow its download")
    with _consumer(home), _mutation(home) as state:
        existing = state / "provision.json"
        if existing.exists():
            receipt, _, _ = _load(home)
            require(receipt["specification_sha256"] == _digest(spec), "A different native selection is already provisioned; preserve it")
            return receipt
        require(report["storage"]["sufficient"], "Insufficient space on the selected physical home volume")
        _within(home, "cache/model-service/artifacts", create=True)
        _within(home, "cache/model-service/tmp", create=True)
        env = {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        for artifact in artifacts:
            destination = _artifact(home, artifact)
            if artifact["name"] in sources:
                _copy(sources[artifact["name"]], destination, artifact)
            else:
                bootstrap.download(artifact["url"], destination, artifact["sha256"], artifact["bytes"], env=env)
        runtime = _within(home, "cache/model-service/runtime-" + _digest(spec))
        require(not runtime.exists(), "Unreceipted native runtime retained; inspect it before another provision")
        stage = Path(tempfile.mkdtemp(prefix="native-stage-", dir=runtime.parent))
        for index, artifact in enumerate(spec["runtime"]["archives"]):
            _extract(_artifact(home, artifact), stage / str(index), artifact["unpacked_max_bytes"])
        binaries = [path for path in (stage / "0").rglob("llama-server") if path.is_file() and not path.is_symlink()]
        require(len(binaries) == 1, "Native archive must contain exactly one llama-server")
        relative = binaries[0].relative_to(stage).as_posix()
        os.rename(stage, runtime)
        binary = runtime / relative
        # Version/help inspection never exposes a GPU, even for a CUDA package.
        env = _environment(home, runtime, spec)
        env["CUDA_VISIBLE_DEVICES"] = ""
        version = _inspect(binary, "--version", env, home)
        help_text = _inspect(binary, "--help", env, home)
        require(spec["runtime"]["revision"][:7] in version, "Native version does not match the pinned source")
        require(all(name in help_text for name in ("--n-cpu-moe", "--api-key-file", "--fit", "--no-warmup")), "Native serving flags are unavailable")
        receipt = {"schema": SCHEMA, "home": _bound_home(home), "storage_root": str(home), "specification": spec, "specification_sha256": _digest(spec),
                   "binary_relative": relative, "runtime_files": _inventory(runtime), "native_version": version,
                   "fit": "not_probed", "task_capability": "not_probed"}
        bootstrap.publish_json(existing, receipt)
        return receipt


def _boot():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def _argv(home, spec, binary, port, key_file):
    resources = spec["resources"]
    return [str(binary), "--model", str(_artifact(home, spec["model"])), "--alias", spec["model"]["id"],
            "--host", "127.0.0.1", "--port", str(port), "--api-key-file", str(key_file),
            "--ctx-size", str(resources["context"]), "--predict", str(resources["max_output"]),
            "--parallel", "1", "--threads", str(resources["threads"]), "--threads-batch", str(resources["batch_threads"]),
            "--n-cpu-moe", str(resources["n_cpu_moe"]), "--n-gpu-layers", str(resources["gpu_layers"]),
            "--device", "CUDA0" if spec["runtime"]["backend"] == "cuda" else "none",
            "--fit", "off", "--no-warmup", "--no-context-shift", "--jinja"]


def _state(home, value):
    receipt, _, binary = _load(home, verify=False)
    require(value.get("schema") == SCHEMA and value.get("home") == _bound_home(home)
            and value.get("storage_root") == str(home), "Service home binding differs")
    require(value.get("specification_sha256") == receipt["specification_sha256"], "Service selection differs")
    key = Path(value.get("key_file", ""))
    require(key.is_absolute() and key.name == "api-key" and re.fullmatch(r"run-[a-f0-9]{32}", key.parent.name)
            and key.parent.parent == home / "state/model-service" and key.resolve() == key, "Service nonce path escaped")
    bootstrap.safe_file(key)
    info = key.stat()
    require(info.st_uid == os.getuid() and info.st_nlink == 1 and info.st_mode & 0o077 == 0 and info.st_size == 65,
            "Service nonce must be a private owned regular file")
    require(hashlib.sha256(key.read_bytes()).hexdigest() == value.get("nonce_sha256"), "Service nonce changed")
    port = value.get("port")
    require(type(port) is int and 1024 <= port <= 65535, "Service port differs")
    require(value.get("model") == receipt["specification"]["model"]["id"]
            and value.get("argv") == _argv(home, receipt["specification"], binary, port, key), "Service native argv differs")
    require(value.get("pid") is None or type(value["pid"]) is int and value["pid"] > 1, "Invalid native PID")
    return value


def _process(pid):
    directory = Path("/proc") / str(pid)
    try:
        fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in ("Z", "X"):
            return None
        return {"start_ticks": fields[19], "uid": directory.stat().st_uid,
                "argv": [os.fsdecode(part) for part in (directory / "cmdline").read_bytes().split(b"\0") if part],
                "exe": str(Path(os.readlink(directory / "exe")).resolve()), "cwd": str(Path(os.readlink(directory / "cwd")).resolve())}
    except (FileNotFoundError, ProcessLookupError):
        return None


def _identity(home, state, pid):
    observed = _process(pid)
    checks = {"present": observed is not None, "boot": state["boot_id"] == _boot()}
    if observed:
        checks.update(uid=observed["uid"] == os.getuid(), cwd=observed["cwd"] == str(home),
                      argv=observed["argv"] == state["argv"], exe=observed["exe"] == state["argv"][0])
    if not all(checks.values()):
        error = ModelServiceError("Native process ownership differs (" + ",".join(key for key, value in checks.items() if not value)
                                  + "); no process will be signaled")
        # Linux can expose an empty cmdline during the initial exec transition.
        # Only initial startup may wait for it, with every other field exact.
        error.empty_initial_argv = bool(observed and not observed["argv"]
                                        and all(value for key, value in checks.items() if key != "argv"))
        raise error
    if state.get("start_ticks"):
        require(observed["start_ticks"] == state["start_ticks"], "Native process PID was reused")
    return observed


def _recover(home, state):
    """Recover only the exact retained nonce-bearing argv after parent death."""
    _state(home, state)
    if state.get("pid"):
        return state if _process(state["pid"]) else None
    matches = []
    for item in Path("/proc").iterdir():
        if not item.name.isdigit():
            continue
        try:
            if item.stat().st_uid != os.getuid():
                continue
            observed = _process(int(item.name))
            if observed and observed["argv"] == state["argv"]:
                _identity(home, state, int(item.name))
                matches.append({**state, "pid": int(item.name), "start_ticks": observed["start_ticks"]})
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    require(len(matches) <= 1, "Multiple matching native processes; inspect retained state")
    return matches[0] if matches else None


def _listener(pid, port):
    sockets = set()
    for fd in (Path("/proc") / str(pid) / "fd").iterdir():
        try:
            link = os.readlink(fd)
            if link.startswith("socket:["):
                sockets.add(link[8:-1])
        except FileNotFoundError:
            pass
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        fields = line.split()
        if fields[1] == f"0100007F:{port:04X}" and fields[3] == "0A" and fields[9] in sockets:
            return True
    return False


def _request(state, route):
    # Never send a nonce to another listener, even if its health response is OK.
    require(_listener(state["pid"], state["port"]), "The native PID does not own the loopback listener")
    key = Path(state["key_file"])
    bootstrap.safe_file(key)
    raw = key.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == state["nonce_sha256"], "Service nonce changed")
    request = urllib.request.Request(f"http://127.0.0.1:{state['port']}" + route,
                                     headers={"Authorization": "Bearer " + raw.decode().strip()})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=2) as response:
        value = response.read(65537)
    require(len(value) <= 65536, "Native status response exceeds its bound")
    return json.loads(value)


def _ready(home, state):
    _identity(home, state, state["pid"])
    models = _request(state, "/v1/models")
    require(isinstance(models, dict) and any(item.get("id") == state["model"] for item in models.get("data", []) if isinstance(item, dict)), "Native model alias differs")
    return _request(state, "/health").get("status") == "ok"


def status(home):
    home = _home(home)
    file = _within(home, "state/model-service/service.json")
    if not file.exists():
        return {"schema": SCHEMA, "home": _bound_home(home), "storage_root": str(home), "status": "stopped"}
    state = _read(file)
    require(state.get("home") == _bound_home(home) and state.get("storage_root") == str(home) and state.get("schema") == SCHEMA, "Service home binding differs")
    _state(home, state)
    current = _recover(home, state) if state.get("phase") != "stopped" else None
    if current is None:
        return {"schema": SCHEMA, "home": _bound_home(home), "storage_root": str(home), "status": "stopped", "last_phase": state.get("phase")}
    _identity(home, current, current["pid"])
    receipt, _, _ = _load(home, verify=False)
    spec = receipt["specification"]
    try:
        ready = _ready(home, current)
    except (OSError, ValueError, urllib.error.URLError):
        ready = False
    return {"schema": SCHEMA, "home": _bound_home(home), "storage_root": str(home), "status": "running" if ready else "starting",
            "pid": current["pid"], "start_ticks": current["start_ticks"], "model": current["model"],
            "model_id": current["model"], "context": spec["resources"]["context"], "max_output": spec["resources"]["max_output"],
            "transport_profile": spec["model"].get("transport_profile", "generic"),
            "base_url": f"http://127.0.0.1:{current['port']}/v1", "api_key_file": current["key_file"],
            "specification_sha256": current["specification_sha256"], "fit": "not_probed", "task_capability": "not_probed"}


def _resources(spec, *, allow_gpu):
    resources = spec["resources"]
    available = hardware_probe.ram_info().get("available_gb")
    require(available is not None and available * 1e9 >= resources["ram_required_bytes"], "Declared free system RAM is unavailable")
    if spec["runtime"]["backend"] == "cpu":
        return
    require(allow_gpu, "GPU start requires explicit permission for the declared UUID/resource plan")
    raise ModelServiceError("GPU execution is held pending a qualified atomic resource-owner admission route; idle/UUID facts alone do not grant ownership")


def _signal(home, state, number):
    native = _pidfd()
    descriptor = native.pidfd_open(state["pid"], 0)
    try:
        _identity(home, state, state["pid"])
        native.pidfd_send_signal(descriptor, number)
    finally:
        os.close(descriptor)


def _stop(home, state, timeout=15):
    _state(home, state)
    if state.get("phase") == "stopped":
        return {"schema": SCHEMA, "home": _bound_home(home), "storage_root": str(home), "status": "stopped"}
    current = _recover(home, state)
    if current:
        _signal(home, current, signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while _process(current["pid"]) and time.monotonic() < deadline:
            time.sleep(0.05)
        if _process(current["pid"]):
            _signal(home, current, signal.SIGKILL)
            deadline = time.monotonic() + 5
            while _process(current["pid"]) and time.monotonic() < deadline:
                time.sleep(0.05)
        require(not _process(current["pid"]), "Owned native process did not settle; retained for inspection")
        child = _CHILDREN.pop(current["pid"], None)
        if child is not None:
            child.wait(timeout=5)
        else:
            try:
                os.waitpid(current["pid"], os.WNOHANG)
            except ChildProcessError:
                pass
    final = {**state, "phase": "stopped"}
    bootstrap.publish_json(home / "state/model-service/service.json", final)
    return {"schema": SCHEMA, "home": _bound_home(home), "storage_root": str(home), "status": "stopped"}


def stop(home):
    home = _home(home)
    with _consumer(home), _mutation(home) as root:
        file = root / "service.json"
        if not file.exists():
            return {"schema": SCHEMA, "home": _bound_home(home), "storage_root": str(home), "status": "stopped"}
        state = _read(file)
        require(state.get("home") == _bound_home(home) and state.get("storage_root") == str(home) and state.get("schema") == SCHEMA, "Service home binding differs")
        return _stop(home, state)


def start(home, *, allow_gpu=False, port=0, startup_timeout=120):
    """Launch only this home's selected native process; never replace a listener."""
    import fcntl
    home = _home(home)
    require(type(port) is int and (port == 0 or 1024 <= port <= 65535), "Select port0 or an unprivileged loopback port")
    require(1 <= startup_timeout <= 600, "Bound startup timeout to 1..600 seconds")
    with _consumer(home) as inherited, _mutation(home) as root:
        pidfd_backend = _pidfd().require_support()
        existing = status(home)
        if existing["status"] == "running":
            return existing
        require(existing["status"] == "stopped", "Own native process is already starting; inspect or stop it")
        receipt, runtime, binary = _load(home)
        spec = receipt["specification"]
        _resources(spec, allow_gpu=allow_gpu)
        descriptor = os.open(root / "service.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        process = None
        state = None
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ModelServiceError("An owned native process retains the service lease") from error
            # Reservation prevents probing an existing listener. Native binding
            # is checked against its actual socket inode after release/spawn.
            reservation = socket.socket()
            try:
                reservation.bind(("127.0.0.1", port))
                selected_port = reservation.getsockname()[1]
            finally:
                reservation.close()
            run = root / ("run-" + secrets.token_hex(16))
            run.mkdir(mode=0o700)
            key_file = run / "api-key"
            raw = (secrets.token_hex(32) + "\n").encode()
            with key_file.open("xb") as key:
                key.write(raw)
            key_file.chmod(0o600)
            argv = _argv(home, spec, binary, selected_port, key_file)
            state = {"schema": SCHEMA, "home": _bound_home(home), "storage_root": str(home), "phase": "starting", "argv": argv, "boot_id": _boot(),
                     "pid": None, "start_ticks": None, "model": spec["model"]["id"], "port": selected_port,
                     "key_file": str(key_file), "nonce_sha256": hashlib.sha256(raw).hexdigest(),
                     "pidfd_backend": pidfd_backend, "pidfd_helper_sha256": PIDFD_SHA256,
                     "specification_sha256": receipt["specification_sha256"], "log": str(run / "native.log")}
            bootstrap.publish_json(root / "service.json", state)
            deadline = time.monotonic() + startup_timeout
            with (run / "native.log").open("xb") as output:
                process = subprocess.Popen(argv, cwd=home, env=_environment(home, runtime, spec), stdin=subprocess.DEVNULL,
                                           stdout=output, stderr=subprocess.STDOUT, pass_fds=(*inherited, descriptor), start_new_session=True)
            _CHILDREN[process.pid] = process
            exec_deadline = min(deadline, time.monotonic() + 1)
            while True:
                try:
                    observed = _identity(home, state, process.pid)
                    break
                except ModelServiceError as error:
                    if not getattr(error, "empty_initial_argv", False) or process.poll() is not None or time.monotonic() >= exec_deadline:
                        raise
                    time.sleep(0.01)
            state.update(pid=process.pid, start_ticks=observed["start_ticks"])
            bootstrap.publish_json(root / "service.json", state)
            while time.monotonic() < deadline:
                require(process.poll() is None, "Native server exited during startup; inspect retained native.log")
                try:
                    ready = _ready(home, state)
                except (OSError, ValueError, urllib.error.URLError):
                    ready = False
                if ready:
                    lock = root / "service.lock"
                    require(any(os.readlink(fd) == str(lock) for fd in (Path("/proc") / str(process.pid) / "fd").iterdir()),
                            "Native server did not retain its inherited lifetime lease")
                    state["phase"] = "running"
                    bootstrap.publish_json(root / "service.json", state)
                    return status(home)
                time.sleep(0.1)
            raise ModelServiceError("Native server startup deadline exceeded; inspect retained native.log")
        except BaseException as error:
            if state is not None:
                state["last_start_failure"] = type(error).__name__ + ": " + str(error)
                bootstrap.publish_json(root / "service.json", state)
                try:
                    _stop(home, state)
                except (OSError, ValueError) as cleanup_error:
                    state.update(phase="recovery_required", cleanup_error=str(cleanup_error))
                    bootstrap.publish_json(root / "service.json", state)
            if process is not None and process.poll() is not None:
                process.wait(timeout=5)
                _CHILDREN.pop(process.pid, None)
            raise
        finally:
            # No LOCK_UN: a surviving native child retains this open-description.
            os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("plan", "provision"):
        selected = sub.add_parser(name, allow_abbrev=False)
        selected.add_argument("--specification", required=True)
        if name == "provision":
            selected.add_argument("--allow-download", action="store_true")
            selected.add_argument("--source", action="append", default=[], metavar="ARTIFACT=ABSOLUTE_PATH")
    selected = sub.add_parser("start", allow_abbrev=False)
    selected.add_argument("--allow-gpu", action="store_true")
    selected.add_argument("--port", type=int, default=0)
    selected.add_argument("--startup-timeout", type=int, default=120)
    sub.add_parser("status", allow_abbrev=False)
    sub.add_parser("stop", allow_abbrev=False)
    args = parser.parse_args(argv)
    try:
        if args.action in ("plan", "provision"):
            spec = _read(Path(args.specification).expanduser().resolve(strict=True))
            if args.action == "plan":
                result = plan(args.home, spec)
            else:
                sources = {}
                for item in args.source:
                    require("=" in item, "Use ARTIFACT=ABSOLUTE_PATH")
                    name, value = item.split("=", 1)
                    require(name not in sources, "Specify each local source once")
                    sources[name] = value
                result = provision(args.home, spec, allow_download=args.allow_download, sources=sources)
        elif args.action == "start":
            result = start(args.home, allow_gpu=args.allow_gpu, port=args.port, startup_timeout=args.startup_timeout)
        else:
            result = globals()[args.action](args.home)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(json.dumps({"schema": SCHEMA, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
