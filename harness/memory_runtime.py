"""Run home-owned MemPalace with a bound CPU cache and its native writer hub.

The upstream registry and palace lock are small metadata in real ~/.mempalace.
The palace, model cache, hub receipt and log stay in the selected agent home.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
from importlib import metadata
import json
import os
from pathlib import Path
import runpy
import secrets
import select
import signal
import subprocess
import sys
import tempfile
import time
from urllib import request


SCHEMA = "memory-runtime/v1"
HUB_SCHEMA = "memory-hub/v1"
HUB_START_SECONDS = 45.0
HUB_STOP_SECONDS = 10.0
ONNX_MODULE = "chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2"
ONNX_SOURCE = "chromadb/utils/embedding_functions/onnx_mini_lm_l6_v2.py"
HELPERS = {
    "capture": ("adapters/pi/memory-capture/capture.py",),
    "validated": ("adapters/pi/memory/validated_memory_query.py",
                  "adapters/pi/memory/memory_retrieval_policy.py"),
    "verify": ("adapters/pi/memory-capture/verify.py", "adapters/pi/memory-capture/capture.py"),
}


class MemoryRuntimeError(ValueError):
    pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_home(home: Path) -> tuple[Path, dict, dict]:
    if not home.is_absolute():
        raise MemoryRuntimeError("Use an explicit absolute agent home")
    home = home.resolve(strict=True)
    config = json.loads((home / "home.json").read_text(encoding="utf-8"))
    if config.get("schema") != "agent-home/v1" or Path(config.get("home", "")).resolve() != home:
        raise MemoryRuntimeError("Agent home identity differs")
    runtime = home / "runtime"
    manifest = runtime / "runtime-manifest.json"
    if digest(manifest) != config.get("runtime_manifest_sha256"):
        raise MemoryRuntimeError("Agent runtime manifest byte drift")
    records = {}
    for item in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        relative = item["path"]
        if relative in records:
            raise MemoryRuntimeError("Duplicate runtime source binding")
        records[relative] = item["sha256"]
    wrapper = checked_source(home, records, "harness/memory_runtime.py")
    if Path(__file__).resolve(strict=True) != wrapper:
        raise MemoryRuntimeError("Run the memory wrapper installed in this agent home")
    return home, config, records


def checked_source(home: Path, records: dict, relative: str) -> Path:
    runtime = (home / "runtime").resolve(strict=True)
    source = (runtime / relative).resolve(strict=True)
    if not source.is_relative_to(runtime) or not source.is_file() or digest(source) != records.get(relative):
        raise MemoryRuntimeError("Memory runtime source byte drift: " + relative)
    return source


def build_binding(home: Path) -> dict:
    """Observe installed identities without importing Chroma or MemPalace."""
    mempalace = metadata.version("mempalace")
    if mempalace != "3.11.0":
        raise MemoryRuntimeError("The qualified MemPalace package is 3.11.0")
    chroma = metadata.distribution("chromadb")
    source = Path(chroma.locate_file(ONNX_SOURCE)).resolve(strict=True)
    python = Path(sys.executable).absolute()
    return {"schema": SCHEMA, "python": str(python), "python_sha256": digest(python),
            "mempalace_version": mempalace, "chromadb_version": chroma.version,
            "onnx_source": {"path": str(source), "sha256": digest(source)},
            "cache_directory": str(home / "cache/chroma/onnx_models/all-MiniLM-L6-v2")}


def prepare_runtime(home: Path, binding: dict) -> None:
    # Compare the complete expected structure, paths, package versions and bytes
    # before importing the class whose default ignores HF_HOME and XDG_CACHE_HOME.
    if not isinstance(binding, dict) or binding != build_binding(home):
        raise MemoryRuntimeError("MemPalace environment or model-cache binding drift")
    if any(name == "mempalace" or name.startswith("mempalace.") for name in sys.modules):
        raise MemoryRuntimeError("Bind the memory cache before importing MemPalace")
    os.environ.update({
        "MEMPALACE_CONFIG_DIR": str(home / "state/mempalace-config"),
        "MEMPALACE_PALACE_PATH": str(home / "memory/palace"),
        "MEMPALACE_EMBEDDING_MODEL": "minilm", "MEMPALACE_EMBEDDING_DEVICE": "cpu",
        "MEMPALACE_EMBEDDING_THREADS": "2", "CUDA_VISIBLE_DEVICES": "",
        "MEMPALACE_HUB_FORWARD": "1", "ANONYMIZED_TELEMETRY": "False",
        "MEMPALACE_CLI_WRITE_ROUTING": "direct", "MEMPALACE_HOOK_WRITE_ROUTING": "direct",
        "MEMPALACE_WRITE_ROUTING": "direct",
        "HF_HOME": str(home / "cache/huggingface"),
        "HF_HUB_CACHE": str(home / "cache/huggingface/hub"),
        "XDG_CACHE_HOME": str(home / "cache"),
    })
    # This home has exactly one native writer owner. Do not inherit an external
    # backend, read-only switch, unsafe lease bypass, HTTP token or TLS binding.
    os.environ["MEMPALACE_BACKEND"] = "chroma"
    for name in ("MEMPALACE_MCP_ALLOW_PEER_WRITER", "MEMPALACE_MCP_READ_ONLY",
                 "MEMPALACE_MCP_HTTP_TOKEN", "MEMPALACE_MCP_TLS_CERT", "MEMPALACE_MCP_TLS_KEY",
                 "MEMPALACE_MCP_HTTP_ALLOW_INSECURE_NO_TOKEN"):
        os.environ.pop(name, None)
    onnx = importlib.import_module(ONNX_MODULE)
    origin = Path(onnx.__file__).resolve(strict=True)
    if origin != Path(binding["onnx_source"]["path"]) or digest(origin) != binding["onnx_source"]["sha256"]:
        raise MemoryRuntimeError("Chroma ONNX module origin differs from its binding")
    cls = onnx.ONNXMiniLM_L6_V2
    if cls.MODEL_NAME != "all-MiniLM-L6-v2":
        raise MemoryRuntimeError("Chroma default embedding model identity differs")
    # This changes only this process. No installed source, HOME, global Python
    # hooks or private palace is modified. MemPalace's subclass inherits it.
    cls.DOWNLOAD_PATH = Path(binding["cache_directory"])


def require_linux() -> None:
    if sys.platform != "linux" or not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise MemoryRuntimeError("The owned memory hub requires Linux with pidfd support")


def hub_directory(home: Path) -> Path:
    directory = home / "state/mempalace-hub"
    if not directory.resolve().is_relative_to(home):
        raise MemoryRuntimeError("Memory hub state must remain in the selected home")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


@contextlib.contextmanager
def hub_lock(home: Path):
    require_linux()
    import fcntl

    fd = os.open(hub_directory(home) / "lifecycle.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MemoryRuntimeError("Another memory hub lifecycle operation is running; retry when it finishes") from exc
        yield
    finally:
        os.close(fd)


def hub_fingerprint(config: dict) -> str:
    value = {"runtime_manifest_sha256": config["runtime_manifest_sha256"],
             "memory_runtime": config["memory_runtime"]}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def hub_command(home: Path, nonce: str) -> list[str]:
    return [str(Path(sys.executable).absolute()), "-B", str(home / "runtime/harness/memory_runtime.py"),
            "--home", str(home), "hub-run", "--", nonce]


def process_identity(pid: int) -> dict | None:
    """Bind a Linux process to a boot, start tick, UID, executable and argv."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise MemoryRuntimeError("Invalid memory hub process identity")
    proc = Path("/proc") / str(pid)
    try:
        fields = (proc / "stat").read_text().rsplit(") ", 1)[1].split()
        if fields[0] in {"Z", "X"}:
            return None
        return {"pid": pid, "uid": proc.stat().st_uid,
                "start_ticks": int(fields[19]),
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "python_real": str((proc / "exe").resolve(strict=True)),
                "command": (proc / "cmdline").read_bytes().rstrip(b"\0").decode().split("\0")}
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (OSError, IndexError, ValueError) as exc:
        raise MemoryRuntimeError("Cannot establish the memory hub process identity") from exc


def read_receipt(home: Path) -> dict | None:
    path = hub_directory(home) / "owner.json"
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 16384:
        raise MemoryRuntimeError("Invalid memory hub receipt")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != HUB_SCHEMA:
        raise MemoryRuntimeError("Invalid memory hub receipt schema")
    nonce = value.get("nonce", "")
    if not isinstance(nonce, str) or len(nonce) != 64 or any(c not in "0123456789abcdef" for c in nonce):
        raise MemoryRuntimeError("Invalid memory hub instance binding")
    if value.get("home") != str(home) or value.get("palace") != str(home / "memory/palace") \
            or value.get("command") != hub_command(home, nonce) or value.get("uid") != os.getuid() \
            or value.get("python_real") != str(Path(sys.executable).resolve(strict=True)):
        raise MemoryRuntimeError("Memory hub receipt belongs to another runtime")
    return value


def write_receipt(home: Path, value: dict) -> None:
    directory = hub_directory(home)
    fd, temporary = tempfile.mkstemp(prefix="owner-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "owner.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def owned_process(receipt: dict, config: dict, *, current: bool = True) -> dict | None:
    identity = process_identity(receipt.get("pid"))
    if identity is None:
        return None
    if any(identity[key] != receipt.get(key) for key in identity):
        raise MemoryRuntimeError("Memory hub PID is not the recorded owned process; no signal sent")
    if current and receipt.get("fingerprint") != hub_fingerprint(config):
        raise MemoryRuntimeError("Running memory hub binding differs; stop this owned hub before restarting")
    return identity


def registry_path(home: Path) -> Path:
    # MemPalace 3.11 server_registry.server_state_dir uses this canonical key.
    palace = os.path.normcase(str((home / "memory/palace").resolve()))
    key = hashlib.sha256(palace.encode()).hexdigest()[:24]
    return Path.home() / ".mempalace/server" / key / "serverinfo.json"


def native_registry(home: Path) -> dict | None:
    path = registry_path(home)
    try:
        if path.is_symlink() or path.stat().st_size > 16384:
            raise MemoryRuntimeError("Invalid native memory hub registry")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        # Upstream publishes this file in place. Reject an incomplete record;
        # the bounded startup loop can retry after publication finishes.
        raise MemoryRuntimeError("Native memory hub registry is incomplete") from exc
    if not isinstance(value, dict):
        raise MemoryRuntimeError("Invalid native memory hub registry")
    return value


def require_hub(home: Path, config: dict) -> dict:
    require_linux()
    receipt = read_receipt(home)
    if receipt is None or owned_process(receipt, config) is None:
        raise MemoryRuntimeError("Memory hub is stopped; run hub-start before using memory")
    info = native_registry(home)
    if not info or info.get("pid") != receipt["pid"] or info.get("host") != "127.0.0.1" \
            or info.get("scheme") != "http" or info.get("read_only") is not False \
            or info.get("palace_path") != str((home / "memory/palace").resolve()) \
            or not isinstance(info.get("port"), int) or isinstance(info["port"], bool) \
            or not 0 < info["port"] < 65536:
        raise MemoryRuntimeError("Native memory hub registry does not match the owned writable process")
    endpoint = f"http://127.0.0.1:{info['port']}"
    # Ignore HTTP_PROXY and redirects: this check must reach the exact loopback
    # listener, and health is not permission to execute through another owner.
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(endpoint + "/healthz", timeout=2.0) as response:
            if response.status != 200:
                raise MemoryRuntimeError("Owned memory hub health check failed")
        if owned_process(receipt, config) is None or native_registry(home) != info:
            raise MemoryRuntimeError("Memory hub ownership changed during readiness check")
    except OSError as exc:
        raise MemoryRuntimeError("Owned memory hub is not healthy") from exc
    return {"status": "running", "pid": receipt["pid"], "endpoint": endpoint,
            "palace": str(home / "memory/palace"), "owned": True}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MemoryRuntimeError("Memory hub health check must not redirect")


def terminate_owned(receipt: dict, config: dict) -> None:
    """Signal an exact recorded lifetime using a pidfd, never a recycled PID."""
    require_linux()
    try:
        fd = os.pidfd_open(receipt["pid"], 0)
    except ProcessLookupError:
        return
    try:
        if owned_process(receipt, config, current=False) is None:
            return
        try:
            signal.pidfd_send_signal(fd, signal.SIGTERM, None, 0)
        except ProcessLookupError:
            return
        if not select.select([fd], [], [], HUB_STOP_SECONDS)[0]:
            raise MemoryRuntimeError("Owned memory hub did not stop gracefully; no forced kill sent")
    finally:
        os.close(fd)


def hub_start(home: Path, config: dict) -> dict:
    if config.get("memory_runtime") != build_binding(home):
        raise MemoryRuntimeError("MemPalace environment or model-cache binding drift")
    if not (home / "memory/palace").is_dir():
        raise MemoryRuntimeError("Initialize this home's empty palace before starting its hub")
    with hub_lock(home):
        existing = read_receipt(home)
        if existing is not None and owned_process(existing, config) is not None:
            return require_hub(home, config)
        native = native_registry(home)
        if native is not None and process_identity(native.get("pid")) is not None:
            raise MemoryRuntimeError("Another live native writer is registered for this palace; no process changed")
        nonce = secrets.token_hex(32)
        command = hub_command(home, nonce)
        log = os.open(hub_directory(home) / "hub.log", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       cwd=home, start_new_session=True)
        finally:
            os.close(log)
        # The child waits for this receipt before importing MemPalace. Its argv
        # already contains a fresh instance nonce, so no receipt can adopt a peer.
        receipt = process_identity(process.pid)
        if receipt is None:
            raise MemoryRuntimeError("Memory hub child exited before its ownership receipt was created")
        receipt.update({"schema": HUB_SCHEMA, "home": str(home), "palace": str(home / "memory/palace"),
                        "nonce": nonce, "fingerprint": hub_fingerprint(config)})
        if receipt["command"] != command or receipt["uid"] != os.getuid():
            raise MemoryRuntimeError("Memory hub child identity differs; no signal sent")
        deadline = time.monotonic() + HUB_START_SECONDS
        last_error = "Memory hub did not become ready"
        try:
            write_receipt(home, receipt)
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise MemoryRuntimeError("Memory hub child exited; inspect state/mempalace-hub/hub.log")
                try:
                    return require_hub(home, config)
                except MemoryRuntimeError as exc:
                    last_error = str(exc)
                time.sleep(0.1)
            raise MemoryRuntimeError("Memory hub startup timed out: " + last_error)
        except BaseException:
            terminate_owned(receipt, config)
            process.wait(timeout=1)
            raise


def hub_stop(home: Path, config: dict) -> dict:
    with hub_lock(home):
        receipt = read_receipt(home)
        if receipt is not None:
            terminate_owned(receipt, config)
            (hub_directory(home) / "owner.json").unlink()
    return {"status": "stopped", "palace": str(home / "memory/palace"), "owned": False}


def hub_status(home: Path, config: dict) -> dict:
    require_linux()
    receipt = read_receipt(home)
    if receipt is None or owned_process(receipt, config) is None:
        return {"status": "stopped", "palace": str(home / "memory/palace"), "owned": False}
    return require_hub(home, config)


def run_hub(home: Path, config: dict, nonce: str) -> int:
    require_linux()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        receipt = read_receipt(home)
        if receipt is not None and receipt.get("nonce") == nonce and receipt.get("pid") == os.getpid():
            if owned_process(receipt, config) is not None:
                break
        time.sleep(0.05)
    else:
        raise MemoryRuntimeError("Hub child has no matching owned launch receipt")
    prepare_runtime(home, config.get("memory_runtime"))
    # Native HTTP is the sole writer and owns its normal lease. Clients use
    # native forwarding, including CLI mine, rather than another local writer.
    os.environ["MEMPALACE_MCP_IDLE_HOURS"] = "0"
    sys.argv = ["mempalace-mcp", "--palace", str(home / "memory/palace"),
                "--transport", "http", "--host", "127.0.0.1", "--port", "0"]
    result = importlib.import_module("mempalace.mcp_server").main()
    return result if isinstance(result, int) else 0


def dispatch(home: Path, config: dict, records: dict, mode: str, arguments: list[str]) -> int:
    helper = None
    if mode in HELPERS:
        for relative in HELPERS[mode]:
            checked = checked_source(home, records, relative)
            if helper is None:
                helper = checked
    elif mode not in {"cli", "mcp", "hub-start", "hub-stop", "hub-status", "hub-run"}:
        raise MemoryRuntimeError("Unsupported memory entry point")
    if mode in {"hub-start", "hub-stop", "hub-status"}:
        if arguments:
            raise MemoryRuntimeError("Hub lifecycle modes do not accept extra arguments")
        result = {"hub-start": hub_start, "hub-stop": hub_stop, "hub-status": hub_status}[mode](home, config)
        print(json.dumps(result, sort_keys=True))
        return 0
    if mode == "hub-run":
        if len(arguments) != 1:
            raise MemoryRuntimeError("Hub child requires its exact launch instance binding")
        return run_hub(home, config, arguments[0])
    if mode == "mcp" and arguments:
        raise MemoryRuntimeError("The home MCP entry uses fixed local stdio arguments")
    if mode == "cli":
        if arguments[:1] in (["serve"], ["daemon"]) or any(value in {"--daemon", "--background"} for value in arguments):
            raise MemoryRuntimeError("Use the owned native hub; separate daemon/background writers are refused")
        for index, value in enumerate(arguments):
            if value == "--palace":
                if index + 1 == len(arguments) or arguments[index + 1] != str(home / "memory/palace"):
                    raise MemoryRuntimeError("The memory CLI uses only this home's palace")
            elif value.startswith("--palace=") and value != "--palace=" + str(home / "memory/palace"):
                raise MemoryRuntimeError("The memory CLI uses only this home's palace")
    initialization = mode == "cli" and arguments[:1] == ["init"]
    with contextlib.ExitStack() as lifetime:
        if initialization:
            # Keep startup excluded until initialization finishes, including
            # native config writes. It must not race an admitted hub-start.
            lifetime.enter_context(hub_lock(home))
            receipt = read_receipt(home)
            native = native_registry(home)
            if receipt is not None and owned_process(receipt, config, current=False) is not None \
                    or native is not None and process_identity(native.get("pid")) is not None:
                raise MemoryRuntimeError("Stop the palace hub before initialization")
        elif mode in {"cli", "mcp", "capture", "validated"}:
            require_hub(home, config)
        prepare_runtime(home, config.get("memory_runtime"))
        if helper is not None:
            sys.path.insert(0, str(helper.parent))
            sys.argv = [str(helper), *arguments]
            runpy.run_path(str(helper), run_name="__main__")
            return 0
        if mode == "mcp":
            sys.argv = ["mempalace-mcp", "--palace", str(home / "memory/palace")]
            # Native stdio forwards to the verified same-palace hub. The hub itself
            # was launched through this wrapper, so its CPU/cache binding is intact.
            result = importlib.import_module("mempalace.mcp_server").main()
        else:
            sys.argv = ["mempalace", *arguments]
            result = importlib.import_module("mempalace.cli").main()
        return result if isinstance(result, int) else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--bind", action="store_true", help="Print package/cache identity without importing or running memory")
    parser.add_argument("mode", nargs="?", choices=("cli", "mcp", "capture", "validated", "verify",
                                                   "hub-start", "hub-status", "hub-stop", "hub-run"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        home, config, records = checked_home(args.home)
        if args.bind:
            if args.mode or args.arguments:
                raise MemoryRuntimeError("--bind does not run an entry point")
            print(json.dumps(build_binding(home), sort_keys=True))
            return 0
        if not args.mode:
            raise MemoryRuntimeError("Select a memory entry point or --bind")
        arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        return dispatch(home, config, records, args.mode, arguments)
    except (MemoryRuntimeError, OSError, KeyError, json.JSONDecodeError, metadata.PackageNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
