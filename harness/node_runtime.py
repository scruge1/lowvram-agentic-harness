"""Persist the exact owned Node runtime produced by the native bootstrap."""
from __future__ import annotations

import json
from pathlib import Path
import platform
import sys

from harness import bootstrap


class NodeRuntimeError(ValueError):
    pass


def require(value, message):
    if not value:
        raise NodeRuntimeError(message)


def receipt(home, node):
    home, node = Path(home).absolute(), Path(node).absolute()
    require(home.resolve() == home and node.resolve(strict=True) == node and node.is_file() and not node.is_symlink(),
            'Select the canonical owned Node binary and agent home.')
    prefix = node.parent.parent
    root = prefix.parent
    require(node == prefix / 'bin/node' and root == Path(str(home) + '-runtimes'),
            'Managed Node must belong to this home\'s permanent bootstrap prefix.')
    marker = root / 'bootstrap-owner'
    require(marker.is_file() and not marker.is_symlink()
            and marker.read_text().strip() == 'agent-home-bootstrap/v1:' + str(home), 'Bootstrap runtime owner differs.')
    source = root / 'runtime-receipt.json'
    require(source.is_file() and not source.is_symlink() and source.stat().st_size <= 8 * 1024 * 1024,
            'A bounded native bootstrap runtime receipt is required.')
    value = json.loads(source.read_text(encoding='utf-8'))
    require(isinstance(value, dict), 'Bootstrap runtime receipt must be an object.')
    entry = value.get('node', {})
    require(isinstance(entry, dict), 'Managed Node receipt must be an object.')
    require(value.get('schema') == 'agent-home-bootstrap/v1' and value.get('home') == str(home)
            and value.get('runtime_root') == str(root) and value.get('status') == 'runtimes_installed',
            'Bootstrap runtime receipt identity differs.')
    require(entry.get('path') == str(node) and entry.get('runtime_root') == str(prefix)
            and entry.get('version') == bootstrap.NODE_VERSION and entry.get('sha256') == bootstrap.sha256(node),
            'Managed Node identity differs from its accepted runtime receipt.')
    require(entry.get('files') == bootstrap.inventory(prefix), 'Managed Node/npm file inventory changed.')
    python = value.get('python', {})
    require(isinstance(python, dict), 'Managed Python receipt must be an object.')
    require(isinstance(python.get('path'), str) and python['path'], 'Managed base Python path is invalid.')
    base = Path(python['path'])
    require(base.is_absolute() and base.resolve(strict=True).is_relative_to(root / 'python')
            and base.is_file() and bootstrap.sha256(base) == python.get('sha256'), 'Managed base Python drift.')
    npm = prefix / 'lib/node_modules/npm/bin/npm-cli.js'
    require(npm.is_file() and not npm.is_symlink(), 'Managed npm CLI is unavailable.')
    return source, value, npm


def bind(home, node):
    source, value, npm = receipt(home, node)
    require(Path(sys.executable).absolute() == Path(value['python']['path']) and platform.python_version() == '3.12.13',
            'Run this bootstrap installation through its exact managed Python.')
    return {'path': value['node']['path'], 'sha256': value['node']['sha256'],
            'version': value['node']['version'], 'runtime_root': value['node']['runtime_root'],
            'npm_cli': str(npm), 'npm_cli_sha256': bootstrap.sha256(npm),
            'bootstrap_receipt': str(source), 'bootstrap_receipt_sha256': bootstrap.sha256(source)}


def check(home, record):
    try:
        require(isinstance(record, dict), 'Managed Node binding must be an object.')
        source, value, npm = receipt(home, record['path'])
        expected = {'path': value['node']['path'], 'sha256': value['node']['sha256'],
                    'version': value['node']['version'], 'runtime_root': value['node']['runtime_root'],
                    'npm_cli': str(npm), 'npm_cli_sha256': bootstrap.sha256(npm),
                    'bootstrap_receipt': str(source), 'bootstrap_receipt_sha256': bootstrap.sha256(source)}
        require(record == expected, 'Managed Node binding or bootstrap receipt changed; no ambient fallback is allowed.')
    except (OSError, ValueError, KeyError, TypeError) as error:
        return str(error)
    return None
