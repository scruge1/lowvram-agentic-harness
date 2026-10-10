"""Compare pinned runtime and CI lock files without installing packages."""

import argparse
from pathlib import Path
import re

MAX_LOCK_BYTES = 2 * 1024 * 1024


def read_lock(path):
    path = Path(path)
    with path.open("rb") as source:
        content = source.read(MAX_LOCK_BYTES + 1)
    if len(content) > MAX_LOCK_BYTES:
        raise ValueError(f"Lock exceeds {MAX_LOCK_BYTES} bytes: {path}")
    packages = {}
    current = None
    for line in content.decode("utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pin = re.fullmatch(r"([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9.!+_-]*)\s*\\?", stripped)
        digest = re.fullmatch(r"--hash=sha256:([0-9a-f]{64})\s*\\?", stripped)
        if pin:
            name = re.sub(r"[-_.]+", "-", pin[1]).lower()
            if name in packages:
                raise ValueError(f"Duplicate package in {path}: {name}")
            current = {"version": pin[2], "hashes": set()}
            packages[name] = current
        elif digest and current is not None:
            current["hashes"].add(digest[1])
        else:
            raise ValueError(f"Unsupported lock syntax in {path}")
    if not packages or any(not p["hashes"] for p in packages.values()):
        raise ValueError(f"Empty or unhashed lock: {path}")
    return packages


def check_runtime_lock(runtime_path, ci_path):
    runtime, ci = read_lock(runtime_path), read_lock(ci_path)
    for name, package in runtime.items():
        candidate = ci.get(name)
        if candidate is None or candidate["version"] != package["version"]:
            raise ValueError(f"Runtime/CI version mismatch: {name}")
        if not package["hashes"].issubset(candidate["hashes"]):
            raise ValueError(f"Runtime/CI distribution hash mismatch: {name}")
    return len(runtime)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--ci", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        count = check_runtime_lock(args.runtime, args.ci)
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(1, f"Runtime/CI lock check failed: {error}\n")
    print(f"Runtime/CI lock check passed: {count} shared packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
