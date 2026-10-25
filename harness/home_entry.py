"""Scaffold a stable, pinned entry before importing exchanged runtime code.

install() writes only absent HOME/home-lifecycle.py and HOME/agent-home.py.
The caller must persist the returned guard_sha256 as lifecycle_guard_sha256
in home.json before publishing commands. It does not rewrite user settings,
context, memory, package environments or home.json.

On Linux the generated entry holds a shared lifetime lease through main().
inherited_pass_fds() validates its environment handle for explicit subprocess
passing. The handle does not authorize skipping the stable entry or acquiring
no lease. Windows keeps the existing inspection dispatch without a Linux lease.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import sys
import types


FD_ENV = "AGENT_HOME_LIFECYCLE_FD"
MAX_CONFIG_BYTES = 65536


class EntryError(ValueError):
    pass


def require(value, message):
    if not value:
        raise EntryError(message)


def selected_home(value):
    path = Path(value).expanduser()
    require(path.is_absolute() and ".." not in path.parts and path.resolve(strict=True) == path,
            "Select the actual absolute agent home")
    require(path.is_dir(), "Selected home is not a directory")
    config_file = path / "home.json"
    require(config_file.is_file() and not config_file.is_symlink()
            and config_file.stat().st_size <= MAX_CONFIG_BYTES, "Invalid home identity file")
    config = json.loads(config_file.read_text(encoding="utf-8"))
    require(isinstance(config, dict) and config.get("schema") == "agent-home/v1"
            and config.get("home") == str(path), "Agent home identity differs")
    return path, config


def launcher_bytes(pin):
    require(isinstance(pin, str) and len(pin) == 64 and all(c in "0123456789abcdef" for c in pin),
            "Use an exact lowercase guard SHA256")
    # Execute the bytes that were hashed, rather than reading the module again
    # through an import loader after the hash check. All imports before the
    # lifecycle lease are from Python's standard library.
    source = '''"""Stable managed-home entry; runtime is imported only after its lifecycle boundary."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import types

PIN = __PIN__
FD_ENV = "AGENT_HOME_LIFECYCLE_FD"

def require(value, message):
    if not value:
        raise ValueError(message)

def dispatch(root, descriptor=None):
    previous = os.environ.pop(FD_ENV, None)
    if descriptor is not None:
        os.environ[FD_ENV] = str(descriptor)
    try:
        sys.path.insert(0, str(root / 'runtime'))
        from harness.home import main
        return main(['--home', str(root), *sys.argv[1:]], bound_home=root)
    finally:
        os.environ.pop(FD_ENV, None)
        if previous is not None:
            os.environ[FD_ENV] = previous

def run():
    entry = Path(__file__).absolute()
    root = entry.parent
    require(root.resolve(strict=True) == root and not entry.is_symlink(), 'Agent-home entry path is an alias')
    # A global override must fail before importing runtime. Values after '--'
    # belong to the existing runtime command parser, which retains its own
    # selected-home/model/project checks.
    values = sys.argv[1:]
    index = 0
    while index < len(values) and values[index] != '--':
        option, separator, inline = values[index].partition('=')
        if option == '--home':
            require(separator or index + 1 < len(values), '--home requires a value')
            value = inline if separator else values[index + 1]
            require(Path(value).expanduser().resolve(strict=True) == root, 'This entry is bound to a different agent home')
            if not separator:
                index += 1
        index += 1
    guard_file = root / 'home-lifecycle.py'
    info = guard_file.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Stable lifecycle guard is not a regular unique file')
    raw = guard_file.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == PIN, 'Stable lifecycle guard byte drift; runtime was not imported')
    config_file = root / 'home.json'
    require(config_file.is_file() and not config_file.is_symlink() and config_file.stat().st_size <= 65536,
            'Invalid home identity file')
    config = json.loads(config_file.read_text(encoding='utf-8'))
    require(isinstance(config, dict) and config.get('schema') == 'agent-home/v1'
            and config.get('home') == str(root) and config.get('lifecycle_guard_sha256') == PIN,
            'Stable entry home/guard binding differs')
    if sys.platform != 'linux':
        return dispatch(root)  # Existing core inspection only; no Linux lease claim.
    module = types.ModuleType('agent_home_lifecycle_guard')
    module.__file__ = str(guard_file)
    module.__package__ = ''
    sys.modules[module.__name__] = module
    exec(compile(raw, str(guard_file), 'exec'), module.__dict__)
    with module.lease(root, expected_sha256=PIN) as held:
        return dispatch(root, held.fd)

try:
    raise SystemExit(run())
except (OSError, ValueError) as error:
    print(json.dumps({'schema':'agent-home-entry/v1','status':'refused','error':str(error)}), file=sys.stderr)
    raise SystemExit(1)
'''
    return source.replace("__PIN__", repr(pin)).encode("utf-8")


def install(home, *, guard_source=None):
    """Write fresh stable entry files; return the binding for caller persistence."""
    home, config = selected_home(home)
    source = Path(guard_source) if guard_source is not None else Path(__file__).with_name("home_lifecycle.py")
    require(source.is_file() and not source.is_symlink(), "Select the reviewed lifecycle guard source")
    raw = source.read_bytes()
    pin = hashlib.sha256(raw).hexdigest()
    require(config.get("lifecycle_guard_sha256", pin) == pin, "Existing home guard declaration differs")
    guard, launcher = home / "home-lifecycle.py", home / "agent-home.py"
    require(not any(p.exists() or p.is_symlink() for p in (guard, launcher)),
            "Stable entry destination is occupied; preserve and inspect existing bytes")
    content = launcher_bytes(pin)
    for path, data in ((guard, raw), (launcher, content)):
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o700)
    require(hashlib.sha256(source.read_bytes()).hexdigest() == pin, "Guard source changed during scaffold")
    return {"guard": str(guard), "guard_sha256": pin, "launcher": str(launcher),
            "launcher_sha256": hashlib.sha256(content).hexdigest(),
            "home_json_update": "Caller must persist lifecycle_guard_sha256 before publishing commands",
            "linux_lease": "shared before runtime import; held until main returns",
            "other_platforms": "Existing inspection dispatch only; no Linux lease enforcement"}


def inherited_pass_fds(home, *, environ=None, required=True):
    """Validate the stable entry's handle for Popen(pass_fds=...), not admission."""
    if sys.platform != "linux":
        return ()
    home, _config = selected_home(home)
    env = os.environ if environ is None else environ
    value = env.get(FD_ENV)
    if value is None and not required:
        return ()
    require(isinstance(value, str) and value.isascii() and value.isdigit(),
            "Stable entry lifecycle descriptor is missing or invalid")
    descriptor = int(value)
    require(descriptor >= 3, "Do not pass a standard stream as a lifecycle descriptor")
    state, lock = home / "state", home / "state/home-lifecycle.lock"
    require(state.is_dir() and not state.is_symlink() and lock.is_file() and not lock.is_symlink(),
            "Lifecycle lock path differs")
    info, current = os.fstat(descriptor), lock.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
            and (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino),
            "Lifecycle descriptor does not name this home's lock")
    return (descriptor,)


def _load_guard(home, pin):
    """Load only the exact verified stable bytes; never an ambient fd/module."""
    require(isinstance(pin, str) and len(pin) == 64 and all(c in "0123456789abcdef" for c in pin),
            "Home lifecycle guard declaration is invalid")
    file = home / "home-lifecycle.py"
    info = file.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Stable lifecycle guard is not a regular unique file")
    raw = file.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == pin, "Stable lifecycle guard byte drift")
    module = types.ModuleType("agent_home_lifecycle_consumer")
    module.__file__, module.__package__ = str(file), ""
    exec(compile(raw, str(file), "exec"), module.__dict__)
    return module


@contextmanager
def consumer(home):
    """Independently hold a shared operation lease; yield actual child pass_fds.

    An existing entry lease may nest this one. No ambient descriptor is trusted
    for admission. Legacy homes with no pin key and non-Linux inspection yield
    () without a lease claim. A declared but invalid pin fails on Linux.
    """
    home, config = selected_home(home)
    if sys.platform != "linux" or "lifecycle_guard_sha256" not in config:
        yield ()
        return
    pin = config["lifecycle_guard_sha256"]
    guard = _load_guard(home, pin)
    with guard.lease(home, expected_sha256=pin) as held:
        yield held.pass_fds


def guarded_command(home, argv, *, python=None):
    """Verify stable guard before executing its CLI, then exec the final argv.

    The returned command creates no service. Root callers own child settlement
    and hub identity publication. After exec the PID and /proc argv belong to
    the final command. Legacy/no-pin and Windows inspection return argv without
    claiming a lease. Generate after the caller persisted the fresh guard pin.
    """
    require(isinstance(argv, (list, tuple)) and argv
            and all(isinstance(arg, (str, os.PathLike)) for arg in argv), "Supply an explicit command argument array")
    target = [os.fspath(arg) for arg in argv]
    require(all(isinstance(arg, str) and "\x00" not in arg for arg in target), "Invalid command argument")
    home, config = selected_home(home)
    if sys.platform != "linux" or "lifecycle_guard_sha256" not in config:
        return target
    pin = config["lifecycle_guard_sha256"]
    require(isinstance(pin, str) and len(pin) == 64 and all(c in "0123456789abcdef" for c in pin),
            "Home lifecycle guard declaration is invalid")
    interpreter = Path(python or sys.executable)
    require(interpreter.is_absolute() and interpreter.is_file(), "Select the actual bootstrap Python executable")
    verifier = '''import hashlib,json,stat,sys
from pathlib import Path
home=Path(__HOME__)
pin=__PIN__
file=home/'home-lifecycle.py'
try:
    info=file.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
        raise ValueError('Stable lifecycle guard is not a regular unique file')
    raw=file.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=pin:
        raise ValueError('Stable lifecycle guard byte drift; target was not executed')
    sys.argv=[str(file),'--home',str(home),'--expected-sha256',pin,'--mode','shared','--',*sys.argv[1:]]
    namespace={'__name__':'__main__','__file__':str(file),'__package__':''}
    exec(compile(raw,str(file),'exec'),namespace)
except (OSError,ValueError) as error:
    print(json.dumps({'schema':'agent-home-entry/v1','status':'refused','error':str(error)}),file=sys.stderr)
    raise SystemExit(1)
'''
    verifier = verifier.replace("__HOME__", repr(str(home))).replace("__PIN__", repr(pin))
    return [str(interpreter), "-c", verifier, *target]
