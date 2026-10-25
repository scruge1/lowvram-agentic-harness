"""Run native Pi under the existing supervisor; retain host-observed events.

Linux process ownership only. This is cleanup, not a hostile-code sandbox.
Reviewed parent source SHA-256:
bf93bfe6f082e775e86ea21da056c12783c9a11d9e35934a4759bb7a8422d0b2
"""
import hashlib
import ctypes
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from pi_native_events import tool_results


def require_process_ownership():
    if (sys.platform != 'linux' or not Path('/proc/self/task').is_dir()
            or not hasattr(os, 'pidfd_open')
            or not hasattr(signal, 'pidfd_send_signal')):
        raise ValueError('Pi process ownership requires Linux /proc and pidfd support; no fallback is enabled.')
    libc = ctypes.CDLL(None, use_errno=True)
    if not hasattr(libc, 'prctl'):
        raise ValueError('Pi process ownership requires Linux prctl support; no fallback is enabled.')
    return libc


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned_children(pid):
    children = set()
    for task in Path('/proc/%s/task' % pid).glob('*/children'):
        try:
            children.update(int(value) for value in task.read_text().split())
        except FileNotFoundError:
            pass
    return children


def stop_owned_tree(pid):
    # Freeze each parent before discovery so ordinary children cannot fork away.
    # Retaining every pidfd uses one descriptor per level and can exhaust the
    # caller's limit before reaching a deep tree's leaves. Keep identities in
    # memory, close each pidfd before descent, and reopen the exact identity for
    # the signal. No recursive Python calls or depth-sized descriptor set.
    frozen = {}

    def open_exact(current, expected=None):
        descriptor = None
        try:
            descriptor = os.pidfd_open(current)
            # /proc/stat fields after the final ')' start with state (field3).
            # starttime is field22. pidfd inode adds its kernel identity where
            # available; the starttime check also covers older anon-inode hosts.
            fields = Path('/proc/%s/stat' % current).read_text().rsplit(')', 1)[1].split()
            info = os.fstat(descriptor)
            identity = (fields[19], info.st_dev, info.st_ino)
            # The original process must still exist after the /proc read. If
            # its PID was reused, this old pidfd reports that it has exited.
            signal.pidfd_send_signal(descriptor, 0)
            if expected is not None and identity != expected:
                os.close(descriptor)
                return None
            return descriptor, identity
        except (ProcessLookupError, FileNotFoundError):
            if descriptor is not None:
                os.close(descriptor)
            return None
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            raise

    def freeze(current):
        opened = open_exact(current)
        if opened is None:
            return None
        descriptor, identity = opened
        try:
            signal.pidfd_send_signal(descriptor, signal.SIGSTOP)
            frozen[current] = identity
            deadline = time.monotonic() + 2
            while True:
                state = Path('/proc/%s/status' % current).read_text()
                if any(line.startswith('State:') and line.split()[1] in ('T', 't', 'Z')
                       for line in state.splitlines()):
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Owned process did not stop for cleanup.')
                time.sleep(0.005)
            return identity, owned_children(current)
        except (ProcessLookupError, FileNotFoundError):
            frozen.pop(current, None)
            return None
        finally:
            os.close(descriptor)

    def kill_frozen(current, identity):
        opened = open_exact(current, identity)
        if opened is not None:
            descriptor, _ = opened
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                os.close(descriptor)
        frozen.pop(current, None)

    try:
        pending = [('freeze', pid, None)]
        while pending:
            action, current, identity = pending.pop()
            if action == 'kill':
                kill_frozen(current, identity)
                continue
            observed = freeze(current)
            if observed is not None:
                identity, children = observed
                pending.append(('kill', current, identity))
                pending.extend(('freeze', child, None) for child in children)
    finally:
        # An inspection or signal failure remains a cleanup failure. Still try
        # every known frozen identity, so one error does not strand all parents.
        failures = []
        for current, identity in reversed(list(frozen.items())):
            try:
                kill_frozen(current, identity)
            except OSError as error:
                failures.append(error)
        if failures:
            raise OSError('Owned process cleanup remains uncertain: ' + str(failures[0])) from failures[0]


def guarded_pi(command):
    # Adopt ordinary orphaned ledger children; this is cleanup, not a sandbox.
    libc = require_process_ownership()
    if not command or any(not isinstance(value, str) or not value for value in command):
        raise ValueError('A nonempty command argument array is required.')
    timeout = float(os.environ.get('PI_TASK_TIMEOUT', 'nan'))
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('PI_TASK_TIMEOUT must be a finite positive number of seconds.')
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot enable child subreaper.')
    stopped = threading.Event()
    lock = threading.RLock()
    holder = {}

    def cleanup():
        for value in owned_children(os.getpid()):
            stop_owned_tree(value)

    def cancelled():
        stopped.set()
        with lock:
            cleanup()

    def watch_owner():
        # Only the owning worker retains this pipe's write end.
        os.read(0, 1)
        cancelled()

    threading.Thread(target=watch_owner, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: cancelled())
    signal.signal(signal.SIGINT, lambda *_: cancelled())
    with lock:
        if stopped.is_set():
            return 125
        holder['child'] = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          start_new_session=True)
    child = holder['child']
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        cancelled()
        try:
            stdout, stderr = child.communicate(timeout=5)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.output or b'', error.stderr or b''
            child.stdout.close()
            child.stderr.close()
            child.wait(timeout=5)
        returncode = 124
    else:
        returncode = 125 if stopped.is_set() else child.returncode
    finally:
        with lock:
            cleanup()
    # Reap adopted children before releasing the output handles.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with lock:
            cleanup()
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if pid == 0:
            time.sleep(0.01)
    if owned_children(os.getpid()):
        raise RuntimeError('Owned descendants did not finish cleanup.')
    sys.stdout.buffer.write(stdout)
    sys.stderr.buffer.write(stderr)
    return returncode


def main():
    require_process_ownership()
    root = Path.cwd().resolve()
    config = json.loads((root / 'worker-config.json').read_text())
    binding = root / 'admission.json'
    if digest(binding) != config['admission_sha256']:
        raise ValueError('Admission binding drift.')
    if Path(os.environ['ENFORCEMENT_TASK_ROOT']).resolve() != root:
        raise ValueError('Missing supervisor root binding.')
    if Path(os.environ['ENFORCEMENT_POLICY_FILE']).resolve() != root / 'task.json':
        raise ValueError('Wrong supervisor policy.')
    environment = {key: value for key, value in os.environ.items()
                   if key in ('PATH', 'LANG') or key.startswith('ENFORCEMENT_')}
    environment.update({
        'HOME': str(root / 'home'), 'PI_CODING_AGENT_DIR': str(root / 'config'),
        'PI_OFFLINE': '1', 'PYTHONPATH': str(root),
        'ENFORCEMENT_ADMISSION_FILE': str(binding),
        'ENFORCEMENT_ADMISSION_SHA256': config['admission_sha256'],
        'ENFORCEMENT_ADAPTER_HELPER': str(root / 'adapter-helper.py'),
        'ENFORCEMENT_ADAPTER_PYTHON': sys.executable,
    })
    # Pi's shebang uses env node; select the Node beside the admitted Pi binary.
    environment['PATH'] = str(Path(config['pi_binary']).parent) + os.pathsep + environment.get('PATH', '')
    command = [config['pi_binary'], '--offline', '--no-session', '--no-context-files',
               '--no-skills', '--no-extensions', '--provider', config['provider'],
               '--model', config['model'], '--mode', 'json']
    if 'active_tools' in config:
        tools = config['active_tools']
        admitted = set(json.loads(binding.read_text())['allowed_tools']) | {'read', 'find', 'grep', 'ls'}
        if (not isinstance(tools, list) or not tools or any(not isinstance(name, str) or name not in admitted for name in tools)
                or len(set(tools)) != len(tools)):
            raise ValueError('Active tool set exceeds the admitted task interfaces.')
        command.extend(['--tools', ','.join(tools)])
    for file in ('portable-pi-enforcement.ts', 'agent-capabilities.ts', 'ledger-tools.ts'):
        command.extend(['-e', str(root / file)])
    command.extend(['-p', (root / 'prompt.txt').read_text()])
    environment['PI_TASK_TIMEOUT'] = str(config['timeout_seconds'])
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--guard', *command],
                             cwd=root, env=environment,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
    ownership = child.stdin
    child.stdin = None

    def stop(_number=None, _frame=None):
        ownership.close()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    timed_out = False
    try:
        # Keep the ownership pipe open while the guard runs.
        stdout, stderr = child.communicate(timeout=config['timeout_seconds'] + 15)
    except subprocess.TimeoutExpired:
        timed_out = True
        ownership.close()
        stop()
        try:
            stdout, stderr = child.communicate(timeout=5)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.output or b'', error.stderr or b''
            child.stdout.close()
            child.stderr.close()
            child.wait(timeout=5)
    finally:
        ownership.close()
        stop()
    timed_out = timed_out or child.returncode == 124
    artifacts = root / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    (artifacts / 'native-events.jsonl').write_bytes(stdout)
    (artifacts / 'native-stderr.txt').write_bytes(stderr)
    observations = []
    events = [json.loads(line) for line in stdout.splitlines()]
    for event in tool_results(events):
        if event['tool_name'] == 'agent_capabilities':
            result = event['result']
            if result.get('details', {}).get('ok') is True and not event['is_error']:
                observations.append({'tool_call_id': event['tool_call_id'],
                                     'snapshot': result['details']['snapshot']})
    (artifacts / 'native-observation.json').write_text(json.dumps({
        'schema': 'pi-supervised-observation/v1', 'task_id': config['task_id'],
        'events_sha256': hashlib.sha256(stdout).hexdigest(),
        'provider_config_sha256': digest(root / 'config' / 'models.json'),
        'worker_returncode': child.returncode, 'timed_out': timed_out,
        'observations': observations,
    }, indent=2) + '\n')
    return 124 if timed_out else child.returncode


if __name__ == '__main__':
    try:
        code = guarded_pi(sys.argv[2:]) if sys.argv[1:2] == ['--guard'] else main()
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        code = 2
    raise SystemExit(code)
