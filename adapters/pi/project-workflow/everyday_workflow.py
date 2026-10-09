"""Build one compact file-work task for the existing portable supervisor."""
import hashlib
import json
import os
import ctypes
import importlib.util
from pathlib import Path
import sys
import signal
import threading
import uuid

OWNED = '''import hashlib, json, os, subprocess, sys
from pathlib import Path
config = json.loads(Path(sys.argv[1]).read_text())
def run_owned(cwd=None):
    guard = Path(config['guard'])
    assert hashlib.sha256(guard.read_bytes()).hexdigest() == config['guard_sha256'], 'Guard drift'
    process = subprocess.Popen([sys.executable, str(guard), '--guard', *config['argv']],
        cwd=cwd, stdin=subprocess.PIPE, env={**os.environ, 'PI_TASK_TIMEOUT': str(config['timeout'])})
    owner = process.stdin
    process.stdin = None
    try:
        return process.wait()
    finally:
        owner.close()
'''
WORKER = OWNED + '''raise SystemExit(run_owned())
'''
VERIFIER = OWNED + '''import tempfile
if '--negative-control' in sys.argv:
    with tempfile.TemporaryDirectory(prefix='pi-predicate-negative-') as root:
        code = run_owned(cwd=root)
    # Only the predicate's documented rejection status qualifies. Interpreter,
    # invocation, timeout, cancellation, and unexpected failures are not proof.
    if code != 1:
        print('Negative control did not report predicate rejection: exit ' + str(code), file=sys.stderr)
    raise SystemExit(0 if code == 1 else 1)
raise SystemExit(run_owned())
'''


def validate(request):
    if not isinstance(request, dict):
        raise ValueError('Request must be an object')
    if not isinstance(request.get('objective'), str) or not request['objective'].strip():
        raise ValueError('A short objective is required')
    root = Path(request['cwd']).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Target must be a working directory')
    for key in ('action', 'verify', 'outputs'):
        value = request.get(key)
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
            raise ValueError(key + ' must be a nonempty string array')
    if len(set(request['outputs'])) != len(request['outputs']):
        raise ValueError('Outputs must be unique')
    for name in request['outputs']:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or any(part in ('.enforcement', '.pi-workflow') for part in relative.parts):
            raise ValueError('Outputs must be relative project artifacts')
        if not (root / relative).resolve().is_relative_to(root):
            raise ValueError('Output escaped target')
    return root


def prepare(request, runtime=None):
    root = validate(request)
    task_id = 'step-' + uuid.uuid4().hex
    relative = Path('.pi-workflow') / task_id
    directory = root / relative
    if not directory.resolve().is_relative_to(root):
        raise ValueError('Workflow store escaped target')
    directory.mkdir(parents=True, exist_ok=False)
    guard = Path(runtime) / 'pi-task-worker.py' if runtime is not None else None
    def command(argv, timeout):
        return {'argv': argv, 'guard': str(guard),
                'guard_sha256': hashlib.sha256(guard.read_bytes()).hexdigest() if guard else None,
                'timeout': timeout}
    files = {
        'worker.py': WORKER,
        'verifier.py': VERIFIER,
        'action.json': json.dumps(command(request['action'], request.get('_action_timeout', 585))),
        'check.json': json.dumps(command(request['verify'], request.get('_check_timeout', 45))),
        'plan.json': json.dumps({'objective': request['objective'], 'target': str(root),
                                'outputs': request['outputs'], 'retry': 'no automatic replay',
                                'authority': 'supplied predicate only'}, indent=2),
    }
    for name, text in files.items():
        (directory / name).write_text(text + '\n', encoding='ascii')
    worker = str(relative / 'worker.py')
    verifier = str(relative / 'verifier.py')
    action = str(relative / 'action.json')
    check = str(relative / 'check.json')
    spec = {
        'schema_version': 1, 'task_id': task_id, 'objective': request['objective'],
        'worker': {'argv': ['{python}', worker, action], 'files': [worker, action, str(relative / 'plan.json')], 'timeout_seconds': request.get('_worker_timeout', 600)},
        'outputs': request['outputs'], 'receipt_output': str(relative / 'receipt.json'),
        'retry': {'max_attempts': 1, 'retry_on': ['process_failure'], 'inner_tool_max_attempts': 0},
        'research': {'required': False},
        'verifier': {'argv': ['{python}', verifier, check], 'files': [verifier, check],
                     'timeout_seconds': 60,
                     'negative_control': {'argv': ['{python}', verifier, check, '--negative-control'],
                                          'files': [verifier, check], 'timeout_seconds': 60}},
    }
    specification = directory / 'task.json'
    specification.write_text(json.dumps(spec, indent=2) + '\n', encoding='ascii')
    return root, specification


def checked_runtime(runtime, runtime_sha, engine_sha):
    for value, name in ((runtime_sha, 'runtime manifest hash'), (engine_sha, 'engine hash')):
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError(name + ' must be a lowercase SHA-256')
    runtime = Path(runtime).resolve(strict=True)
    manifest = runtime / 'runtime-manifest.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != runtime_sha:
        raise ValueError('Runtime manifest drift')
    for item in json.loads(manifest.read_text())['files']:
        file = (runtime / item['path']).resolve(strict=True)
        if not file.is_relative_to(runtime) or hashlib.sha256(file.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Runtime source drift')
    engine = runtime / 'harness' / 'enforcement.py'
    if hashlib.sha256(engine.read_bytes()).hexdigest() != engine_sha:
        raise ValueError('Portable engine changed; no implicit version approval')
    return runtime


def execute(request, runtime, runtime_sha, engine_sha):
    runtime = checked_runtime(runtime, runtime_sha, engine_sha)
    root, spec = prepare(request, runtime)
    sys.path.insert(0, str(runtime))
    from harness.enforcement import run_task, verify_receipt
    receipt = run_task(root, spec)
    if receipt['status'] != 'accepted':
        return {'status': 'failed', 'run_id': receipt['run_id'], 'reason': receipt.get('reason'),
                'authority': 'none', 'task_root': str(root), 'task_spec': str(spec)}
    checked = verify_receipt(root, spec, spec.parent / 'receipt.json')
    return {'status': 'supplied_predicate_passed', 'run_id': checked['run_id'],
            'authority': 'tested', 'task_root': str(root), 'task_spec': str(spec),
            'receipt': str(spec.parent / 'receipt.json'),
            'limits': 'Not semantic goal acceptance, physical authorization, or a shell sandbox'}


if __name__ == '__main__':
    try:
        if len(sys.argv) < 4:
            raise ValueError('runtime path and reviewed runtime hashes are required')
        runtime_sha, engine_sha = sys.argv[2:4]
        runtime = checked_runtime(sys.argv[1], runtime_sha, engine_sha)
        if '--interactive-owner' in sys.argv[4:]:
            # Reuse reviewed ownership cleanup; no second attempt/acceptance core.
            sys.path.insert(0, str(runtime))
            spec = importlib.util.spec_from_file_location('owned_cleanup', runtime / 'pi-task-worker.py')
            cleanup = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cleanup)
            if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
                raise OSError('Cannot enable child ownership cleanup')
            request = json.loads(sys.stdin.buffer.readline())

            def cancel(*_):
                for pid in cleanup.owned_children(os.getpid()):
                    cleanup.stop_owned_tree(pid)
                print(json.dumps({'status': 'cancelled', 'authority': 'none',
                                  'reason': 'Owner cancelled; partial evidence retained, no replay'}))
                raise SystemExit(130)

            signal.signal(signal.SIGTERM, cancel)
            signal.signal(signal.SIGINT, cancel)

            def watch_owner():
                os.read(0, 1)
                os.kill(os.getpid(), signal.SIGTERM)

            threading.Thread(target=watch_owner, daemon=True).start()
        else:
            request = json.load(sys.stdin)
        try:
            result = execute(request, runtime, runtime_sha, engine_sha)
        finally:
            if '--interactive-owner' in sys.argv[4:]:
                for pid in cleanup.owned_children(os.getpid()):
                    cleanup.stop_owned_tree(pid)
        print(json.dumps(result))
        raise SystemExit(0 if result['status'] == 'supplied_predicate_passed' else 1)
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({'status': 'rejected', 'reason': str(error), 'authority': 'none'}))
        raise SystemExit(2)
