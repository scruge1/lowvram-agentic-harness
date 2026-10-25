"""Exact owned research environment and browser inventory for agent-home setup.

These are the versions exercised together on Python3.12/Linux. The native
Playwright installer selects its own matching browser revision. No OS packages,
global browser profile or private search-provider configuration are installed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


REQUIREMENTS = (
    "anyio==4.15.1", "beautifulsoup4==4.15.0", "certifi==2026.10.23",
    "click==8.5.0", "ddgs==9.16.1", "greenlet==3.5.6", "h11==0.16.0",
    "httpcore==1.0.9", "httpx==0.28.1", "idna==3.20", "lxml==6.1.3",
    "playwright==1.64.1", "primp==2.0.1", "pyee==14.0.0",
    "soupsieve==3.0.4", "typing_extensions==4.16.0",
)
BROWSER_REVISION = "1248"
FFMPEG_REVISION = "1013"

# Executed only by the selected environment's own interpreter. Inspect native
# distribution records without importing third-party packages or invoking them.
INVENTORY_CODE = '''import importlib.metadata as m,json,sys
from pathlib import Path
result=[]
for requirement in json.loads(sys.argv[1]):
 name,version=requirement.split('==')
 dist=m.distribution(name)
 if dist.version!=version: raise SystemExit('Research distribution version mismatch: '+name)
 result.append({'name':name,'version':version,'files':[str(Path(dist.locate_file(f)).absolute()) for f in dist.files or [] if str(f).endswith(('.pyc','.pyo')) is False]})
print(json.dumps(result))
'''


def install_owned(home, *, execute, environment):
    """Run the existing install caller in its already created owned venv."""
    home = Path(home).resolve(strict=True)
    python = home / 'envs/research/bin/python'
    if not python.is_file() or not Path(environment.get('PLAYWRIGHT_BROWSERS_PATH', '')).is_absolute() \
            or Path(environment['PLAYWRIGHT_BROWSERS_PATH']) != home / 'cache/playwright':
        raise ValueError('Select the existing owned research interpreter and browser cache before installation.')
    output = execute([python, '-m', 'pip', 'install', '--no-deps', *REQUIREMENTS], cwd=home, env=environment)
    output += execute([python, '-m', 'playwright', 'install', 'chromium'], cwd=home, env=environment)
    return output


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def inventory(home, distributions):
    """Bind installed runtime files and the native browser cache, not .pyc."""
    home = Path(home).resolve(strict=True)
    environment = home / 'envs/research'
    cache = home / 'cache/playwright'
    if environment.is_symlink() or cache.is_symlink():
        raise ValueError('Research environment/browser cache must be owned directories.')
    expected = dict(item.split('==') for item in REQUIREMENTS)
    observed = {item['name']: item['version'] for item in distributions}
    if observed != expected or len(distributions) != len(expected):
        raise ValueError('Research distribution inventory differs from the selected exact plan.')
    paths = set()
    for distribution in distributions:
        if not distribution['files']:
            raise ValueError('Research distribution has no recorded files: ' + distribution['name'])
        for item in distribution['files']:
            path = Path(item)
            if not path.is_absolute() or not path.resolve(strict=True).is_relative_to(environment):
                raise ValueError('Research distribution file escaped its owned environment.')
            if path.is_symlink() or not path.is_file():
                raise ValueError('Research distribution file is not a regular owned file.')
            paths.add(path.resolve(strict=True))
    roots = [cache / ('chromium-' + BROWSER_REVISION),
             cache / ('chromium_headless_shell-' + BROWSER_REVISION),
             cache / ('ffmpeg-' + FFMPEG_REVISION)]
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            raise ValueError('Matching native browser revision is missing: ' + root.name)
        found = False
        for path in root.rglob('*'):
            if path.is_symlink() or not path.resolve().is_relative_to(cache):
                raise ValueError('Native browser file escaped its owned cache.')
            if path.is_file():
                paths.add(path)
                found = True
        if not found:
            raise ValueError('Native browser revision is empty: ' + root.name)
    files = [{'path': str(path.relative_to(home)), 'sha256': digest(path)} for path in sorted(paths)]
    return {'schema': 'agent-home-research-installation/v1',
            'requirements': list(REQUIREMENTS), 'browser_revision': BROWSER_REVISION,
            'ffmpeg_revision': FFMPEG_REVISION, 'files': files,
            'running': 'not_started', 'network_search_acceptance': 'not_run',
            'browser_acceptance': 'not_run'}


def verify(home, manifest):
    home = Path(home).resolve(strict=True)
    if manifest.get('schema') != 'agent-home-research-installation/v1' or manifest.get('requirements') != list(REQUIREMENTS):
        return 'Research installation plan differs from this runtime.'
    files = manifest.get('files')
    if not isinstance(files, list) or not files:
        return 'Research installation inventory is empty.'
    for item in files:
        relative = Path(item['path'])
        path = home / relative
        if relative.is_absolute() or '..' in relative.parts or not path.resolve().is_relative_to(home) \
                or path.is_symlink() or not path.is_file() or digest(path) != item['sha256']:
            return 'Research runtime/browser file missing or changed: ' + str(relative)
    return None
