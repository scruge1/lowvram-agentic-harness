#!/usr/bin/env python3
"""hardware_probe.py -- what GPU/VRAM/RAM does THIS machine actually have.

Every flag recommendation in SETUP.md (--n-cpu-moe 34, etc.) was measured on ONE
specific 8GB card. Your friend's 2080 is also 8GB but the rest of his box (system RAM,
what else is running) is unknown -- so instead of shipping one hardcoded number, this
probes the real machine and autotune_offload.py (same directory's parent, scripts/)
uses it to find a setting that actually fits, on whatever hardware it's run on.

No third-party deps: shells out to `nvidia-smi` (GPU) and reads OS-native memory
info (RAM) so this works with a bare Python install, matching the rest of the harness.
"""
from __future__ import annotations

import platform
import re
import shutil
import subprocess


def _run(cmd: list[str], timeout: float = 10.0) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:  # noqa: BLE001 -- missing binary, timeout, permissions: all mean "unknown"
        return None


def gpu_info() -> dict:
    """{'available': bool, 'name': str|None, 'vram_total_mb': int|None, 'vram_free_mb': int|None,
    'other_procs': [{'pid', 'name', 'used_mb'}]} -- other_procs is what a --kill-others
    flag in autotune_offload.py would consider evicting; this module only REPORTS."""
    if not shutil.which("nvidia-smi"):
        return {"available": False, "name": None, "vram_total_mb": None,
                "vram_free_mb": None, "other_procs": [], "reason": "nvidia-smi not on PATH"}

    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits"])
    if not out or not out.strip():
        return {"available": False, "name": None, "vram_total_mb": None,
                "vram_free_mb": None, "other_procs": [], "reason": "nvidia-smi returned nothing"}
    name, total, free = [p.strip() for p in out.strip().splitlines()[0].split(",")]

    procs = []
    procs_out = _run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                       "--format=csv,noheader,nounits"])
    if procs_out:
        for line in procs_out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 3 and parts[0].isdigit():
                procs.append({"pid": int(parts[0]), "name": parts[1], "used_mb": _to_int(parts[2])})

    return {"available": True, "name": name, "vram_total_mb": _to_int(total),
            "vram_free_mb": _to_int(free), "other_procs": procs}


def ram_info() -> dict:
    """{'total_gb': float|None, 'available_gb': float|None}. Tries psutil first (if
    installed), falls back to OS-native commands so a bare install still works."""
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        return {"total_gb": round(vm.total / 1e9, 1), "available_gb": round(vm.available / 1e9, 1)}
    except ImportError:
        pass

    system = platform.system()
    if system == "Linux":
        return _ram_linux()
    if system == "Windows":
        return _ram_windows()
    if system == "Darwin":
        return _ram_macos()
    return {"total_gb": None, "available_gb": None}


def _ram_linux() -> dict:
    try:
        with open("/proc/meminfo") as f:
            text = f.read()
    except OSError:
        return {"total_gb": None, "available_gb": None}
    total = re.search(r"MemTotal:\s+(\d+) kB", text)
    avail = re.search(r"MemAvailable:\s+(\d+) kB", text)
    return {
        "total_gb": round(int(total.group(1)) / 1e6, 1) if total else None,
        "available_gb": round(int(avail.group(1)) / 1e6, 1) if avail else None,
    }


def _ram_windows() -> dict:
    out = _run(["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory", "/format:list"])
    if not out:
        return {"total_gb": None, "available_gb": None}
    total = re.search(r"TotalVisibleMemorySize=(\d+)", out)
    free = re.search(r"FreePhysicalMemory=(\d+)", out)
    # wmic reports KB
    return {
        "total_gb": round(int(total.group(1)) / 1e6, 1) if total else None,
        "available_gb": round(int(free.group(1)) / 1e6, 1) if free else None,
    }


def _ram_macos() -> dict:
    out = _run(["sysctl", "-n", "hw.memsize"])
    total_gb = round(int(out.strip()) / 1e9, 1) if out and out.strip().isdigit() else None
    return {"total_gb": total_gb, "available_gb": None}  # macOS has no simple "available" equivalent here


def _to_int(s: str):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def summary() -> dict:
    """The one call autotune_offload.py and the FAQ-agent path actually use."""
    return {"gpu": gpu_info(), "ram": ram_info()}


def _selftest() -> int:
    fails = 0

    def chk(name, cond):
        nonlocal fails
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            fails += 1

    chk("_to_int parses plain int", _to_int("6.0") == 6)
    chk("_to_int returns None on garbage", _to_int("n/a") is None)

    # gpu_info() must degrade honestly when nvidia-smi is absent -- never fake a GPU.
    import unittest.mock as mock
    with mock.patch("shutil.which", return_value=None):
        g = gpu_info()
        chk("gpu_info reports unavailable (no fake VRAM number) when nvidia-smi missing",
            g["available"] is False and g["vram_total_mb"] is None and "reason" in g)

    with mock.patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
         mock.patch(__name__ + "._run") as m:
        def fake_run(cmd, timeout=10.0):
            if "--query-gpu=name,memory.total,memory.free" in " ".join(cmd):
                return "NVIDIA GeForce RTX 2080, 8192, 6100\n"
            if "--query-compute-apps" in " ".join(cmd):
                return "1234, some-other-server, 900\n"
            return None
        m.side_effect = fake_run
        g = gpu_info()
        chk("gpu_info parses a mocked nvidia-smi line", g["available"] and g["vram_total_mb"] == 8192)
        chk("gpu_info surfaces other GPU processes for review (never auto-kills)",
            len(g["other_procs"]) == 1 and g["other_procs"][0]["pid"] == 1234)

    r = ram_info()
    chk("ram_info returns a dict with total_gb key on this real machine",
        "total_gb" in r)

    with mock.patch.dict("sys.modules", {"psutil": None}),          mock.patch("platform.system", return_value="NoSuchOS"):
        r2 = ram_info()
        chk("ram_info degrades to None/None on an unknown OS with no psutil (no fabricated number)",
            r2 == {"total_gb": None, "available_gb": None})

    print("SELFTEST OK" if fails == 0 else f"SELFTEST FAILED ({fails})")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    import json
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(json.dumps(summary(), indent=2))
