"""Read-only evidence consistency screen. NOT an admission/acceptance authority.

Caller must bind trusted host observations outside model-writable artifacts.
Matching two model-authored records is not proof of an observed action.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

SHA = re.compile(r'[0-9a-f]{64}\Z')
STATES = {'unknown', 'untested', 'observed_success', 'observed_failure'}
MAX_BYTES = 16 * 1024 * 1024


class EvidenceError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise EvidenceError(reason)


def parse_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def artifact(root: Path, ref: dict) -> bytes:
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'artifact_reference_shape')
    name, digest = ref['path'], ref['sha256']
    require(isinstance(name, str) and 0 < len(name) <= 2048 and '\\' not in name and ':' not in name, 'artifact_path')
    parts = PurePosixPath(name)
    require(not parts.is_absolute() and '..' not in parts.parts, 'artifact_path_escape')
    require(isinstance(digest, str) and SHA.fullmatch(digest), 'artifact_hash_missing')
    root = root.resolve(strict=True)
    candidate = root.joinpath(*parts.parts)
    # Reject even inward links: evidence location must be explicit.
    cursor = root
    for part in parts.parts:
        cursor = cursor / part
        require(not cursor.is_symlink(), 'artifact_symlink')
    resolved = candidate.resolve(strict=True)
    require(resolved.is_relative_to(root) and resolved.is_file(), 'artifact_path_escape')
    with resolved.open('rb') as handle:
        import os
        before = os.fstat(handle.fileno())
        require(before.st_size <= MAX_BYTES, 'artifact_too_large')
        data = handle.read(MAX_BYTES + 1)
        after = os.fstat(handle.fileno())
    require((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns), 'artifact_changed_during_read')
    require(len(data) <= MAX_BYTES and hashlib.sha256(data).hexdigest() == digest, 'artifact_hash_mismatch')
    return data


def unique_records(records, field):
    require(isinstance(records, list) and len(records) <= 10000, 'record_list')
    found = {}
    for item in records:
        require(isinstance(item, dict), 'record_shape')
        key = item.get(field)
        require(isinstance(key, str) and 0 < len(key) <= 256 and key not in found, 'duplicate_or_missing_identity')
        found[key] = item
    return found


def validate(root, report, observations, expected_task_sha256, expected_session_id):
    """Validate shapes/bindings against caller-supplied host observations.

    Does not authenticate observer custody, validate semantics of raw output,
    prove complete discovery, authorize actions, or score a benchmark.
    """
    require(isinstance(expected_task_sha256, str) and SHA.fullmatch(expected_task_sha256), 'expected_task_hash')
    require(isinstance(expected_session_id, str) and expected_session_id, 'expected_session_id')
    require(isinstance(report, dict) and report.get('schema') == 'pi-workflow-evidence/v1', 'report_schema')
    require(isinstance(observations, dict) and observations.get('schema') == 'pi-host-observations/v1', 'observation_schema')
    require(set(report) == {'schema', 'task_sha256', 'session_id', 'native_snapshot', 'shell_inventory', 'installed_extensions', 'probes', 'research'}, 'unsupported_report_fields')
    for document in (report, observations):
        require(document.get('task_sha256') == expected_task_sha256, 'task_binding')
        require(document.get('session_id') == expected_session_id, 'session_binding')
    snapshot_ref = report.get('native_snapshot')
    require(snapshot_ref == observations.get('native_snapshot'), 'snapshot_observation_binding')
    snapshot = parse_json(artifact(root, snapshot_ref))
    require(isinstance(snapshot, dict) and snapshot.get('schema') == 'pi-native-capabilities/v1' and snapshot.get('session_id') == expected_session_id, 'snapshot_identity')
    native = unique_records(snapshot.get('configured_tools'), 'name')
    for entry in native.values():
        require(entry.get('interface') == 'pi-native-callable' and type(entry.get('active')) is bool, 'native_identity_shape')
        require('status' not in entry, 'registry_not_health')
    shell = unique_records(report.get('shell_inventory'), 'name')
    for entry in shell.values():
        require(entry.get('interface') == 'shell-cli' and entry.get('state') in {'unknown', 'untested'}, 'shell_not_native_or_health')
    installed = unique_records(report.get('installed_extensions'), 'path')
    for entry in installed.values():
        require(entry.get('state') == 'installed_only' and isinstance(entry.get('sha256'), str) and SHA.fullmatch(entry['sha256']), 'installed_not_loaded')
    seen = unique_records(observations.get('events'), 'id')
    probes = unique_records(report.get('probes'), 'id')
    consumed = set()
    for probe in probes.values():
        state = probe.get('state')
        require(state in STATES, 'unsupported_working_or_verified_claim')
        interface, target = probe.get('interface'), probe.get('target')
        require(interface in {'pi-native-callable', 'shell-cli'}, 'probe_interface')
        require(target in (native if interface == 'pi-native-callable' else shell), 'probe_target_undiscovered')
        if state in {'unknown', 'untested'}:
            require(probe.get('observation_id') is None and probe.get('output') is None, 'untested_with_success_evidence')
            continue
        if interface == 'pi-native-callable':
            require(native[target]['active'] is True, 'native_probe_inactive_at_snapshot')
        event = seen.get(probe.get('observation_id'))
        require(isinstance(event, dict) and event.get('kind') == 'probe', 'missing_probe_observation')
        require(probe['observation_id'] not in consumed, 'probe_observation_reused')
        consumed.add(probe['observation_id'])
        require(event.get('interface') == interface and event.get('target') == target, 'probe_observation_identity')
        input_hash = probe.get('input_sha256')
        require(isinstance(input_hash, str) and SHA.fullmatch(input_hash) and input_hash == event.get('input_sha256'), 'probe_input_binding')
        rc = event.get('exit_code')
        require(type(rc) is int and -255 <= rc <= 255 and probe.get('exit_code') == rc and type(probe.get('exit_code')) is int, 'missing_or_invalid_exit_code')
        require((rc == 0) == (state == 'observed_success'), 'exit_code_state_mismatch')
        require(probe.get('output') == event.get('output'), 'probe_output_binding')
        artifact(root, probe['output'])
    research = unique_records(report.get('research'), 'id')
    for record in research.values():
        event = seen.get(record.get('observation_id'))
        require(isinstance(event, dict) and event.get('kind') == 'source_fetch', 'missing_source_observation')
        url = record.get('url')
        require(isinstance(url, str) and url.startswith('https://') and url == event.get('url'), 'source_url_binding')
        require(type(event.get('exit_code')) is int and event['exit_code'] == 0, 'source_fetch_failed')
        require(record.get('raw') == event.get('output'), 'source_output_binding')
        require(len(artifact(root, record['raw'])) > 0, 'empty_original_source')
    return {'result': 'consistent', 'probes': len(probes), 'sources': len(research), 'authority': 'evidence_consistency_only; trusted observer custody and semantic/task acceptance external'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--observations', required=True, type=Path)
    parser.add_argument('--task-sha256', required=True)
    parser.add_argument('--session-id', required=True)
    args = parser.parse_args()
    try:
        for path in (args.report, args.observations):
            require(path.stat().st_size <= MAX_BYTES, 'input_too_large')
        result = validate(args.root, parse_json(args.report.read_bytes()), parse_json(args.observations.read_bytes()), args.task_sha256, args.session_id)
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'result': 'rejected', 'reason': str(exc) if isinstance(exc, EvidenceError) else type(exc).__name__, 'authority': 'none'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
