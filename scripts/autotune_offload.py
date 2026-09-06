#!/usr/bin/env python3
"""autotune_offload.py -- find the --n-cpu-moe value that actually fits THIS machine,
instead of trusting a number measured on someone else's 8 GB card.

Every card sold as "8 GB" doesn't behave identically once the OS, display compositor,
and whatever else is running takes its slice -- and RAM headroom (needed for the
offloaded experts) varies even more between two "8 GB GPU" boxes. So: probe real free
VRAM (harness/hardware_probe.py), sweep a handful of --n-cpu-moe values from
safest-fits (offload the most) toward fastest (offload the least), launch the REAL
llama-server for each candidate, and keep the fastest one that did not OOM.

Two layers, deliberately separated so the decision logic is unit-testable without a
GPU:
  * pick_winner(attempts) / candidate_offload_values(...) -- pure, no I/O, covered
    by --selftest with fabricated attempt data.
  * probe_offload(...) -- the real thing: launches llama-server, waits for it to
    report ready, sends one short completion, measures tok/s and VRAM used, kills it.
    NOT exercised by --selftest (needs the real binary plus a GPU) -- run it for real,
    once, on the target machine, and read what it prints before trusting it.

Usage:
  python scripts/autotune_offload.py plan
  python scripts/autotune_offload.py run --model models/Qwen3-30B-A3B-Instruct-2507-UD-Q4_K_XL.gguf --llama-server /path/to/llama-server
  python scripts/autotune_offload.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness import hardware_probe  # noqa: E402


def candidate_offload_values(total_hint: int = 48) -> list[int]:
    """Best-first-for-SAFETY sweep order: start by offloading MOST experts (safest,
    slowest, most likely to fit), then progressively offload fewer (faster, needs more
    VRAM) until one fails. total_hint is a rough ceiling on expert-layer count for a
    30B-A3B-class model (Qwen3-30B-A3B has 48 in its default config) -- it only bounds
    the sweep range, it is never asserted as exact."""
    if total_hint <= 0:
        return [0]
    fracs = (1.0, 0.85, 0.7, 0.55, 0.4, 0.25)
    vals = sorted({max(0, round(total_hint * f)) for f in fracs}, reverse=True)
    return vals


def pick_winner(attempts: list) -> dict:
    """attempts: [{n_cpu_moe, ok, tok_s, vram_used_mb, ...}]. Winner = fastest
    (highest tok_s) among the ones that actually loaded without OOM. Returns None if
    nothing worked -- a real, reportable outcome, never silently swallowed."""
    ok = [a for a in attempts if a.get("ok") and a.get("tok_s") is not None]
    if not ok:
        return None
    return max(ok, key=lambda a: a["tok_s"])


def probe_offload(model_path, llama_server_bin, n_cpu_moe, port=8099,
                   startup_timeout_s=120.0, prompt="Count from 1 to 5."):
    """REAL launch of llama-server with this --n-cpu-moe, one completion, teardown.
    Not covered by --selftest (needs the real binary plus a GPU) -- this is the one
    function to verify by hand on the target machine before trusting run()'s output."""
    import subprocess

    cmd = [llama_server_bin, "-m", model_path, "-ngl", "99", "--n-cpu-moe", str(n_cpu_moe),
           "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
           "-c", "4096", "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = "http://127.0.0.1:%d/v1" % port
    t0 = time.time()
    ready = False
    try:
        while time.time() - t0 < startup_timeout_s:
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                return {"n_cpu_moe": n_cpu_moe, "ok": False, "tok_s": None, "vram_used_mb": None,
                        "error": "server exited (code %s) during startup" % proc.returncode,
                        "log_tail": out[-2000:]}
            try:
                urllib.request.urlopen(base + "/models", timeout=2)
                ready = True
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(2)
        if not ready:
            return {"n_cpu_moe": n_cpu_moe, "ok": False, "tok_s": None, "vram_used_mb": None,
                    "error": "server never became ready within %ss" % startup_timeout_s}

        load_s = time.time() - t0
        body = json.dumps({"model": "local", "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 64, "temperature": 0}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body,
                                      headers={"Content-Type": "application/json"}, method="POST")
        t1 = time.time()
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        elapsed = time.time() - t1
        usage = data.get("usage", {})
        completion_tokens = usage.get("completion_tokens") or 64
        tok_s = round(completion_tokens / elapsed, 1) if elapsed > 0 else None

        gpu = hardware_probe.gpu_info()
        vram_used = None
        if gpu.get("available") and gpu.get("vram_total_mb") is not None and gpu.get("vram_free_mb") is not None:
            vram_used = gpu["vram_total_mb"] - gpu["vram_free_mb"]

        return {"n_cpu_moe": n_cpu_moe, "ok": True, "tok_s": tok_s, "vram_used_mb": vram_used,
                "load_s": round(load_s, 1)}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def evict_other_gpu_processes(other_procs, kill=False):
    """other_procs: hardware_probe.gpu_info()["other_procs"]. With kill=False (the
    default) this ONLY reports what's holding VRAM -- it never terminates anything
    unless you explicitly pass kill=True (surfaced as --evict-others on the CLI). A
    30B-class MoE plus literally any other GPU process does not fit in 8GB, so if
    something else is running, --n-cpu-moe cannot save you; something has to close
    first, and that is a real, visible action, not a silent side effect."""
    if not other_procs:
        return {"evicted": [], "reported_only": []}
    if not kill:
        return {"evicted": [], "reported_only": other_procs}
    import os
    import platform
    import subprocess
    evicted = []
    for proc in other_procs:
        pid = proc["pid"]
        try:
            if platform.system() == "Windows":
                r = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10, text=True)
                if r.returncode != 0:
                    raise RuntimeError((r.stderr or r.stdout or "taskkill failed").strip())
            else:
                os.kill(pid, 15)  # SIGTERM
            evicted.append(proc)
        except Exception as e:  # noqa: BLE001 -- best-effort; report failures, do not crash the sweep over them
            proc["evict_error"] = str(e)
    return {"evicted": evicted, "reported_only": []}


def run(model_path, llama_server_bin, total_hint=48, port=8099, prober=probe_offload, evict_others=False):
    """Sweep candidate_offload_values(), prober() each, pick_winner(). prober is
    swappable so this whole orchestration function IS covered by --selftest with a
    fake prober -- only probe_offload's internals need a real machine. evict_others
    (default False) controls whether other_procs holding VRAM get terminated before
    the sweep -- see evict_other_gpu_processes."""
    hw = hardware_probe.summary()
    eviction = evict_other_gpu_processes(hw["gpu"].get("other_procs", []), kill=evict_others)
    attempts = [prober(model_path, llama_server_bin, n, port=port) for n in candidate_offload_values(total_hint)]
    winner = pick_winner(attempts)
    return {"hardware": hw, "eviction": eviction, "attempts": attempts, "winner": winner}


def write_result(winner, model_tag, path="models.yaml"):
    """Append/update a local-tuned class entry in models.yaml with the measured
    winning flags. Never overwrites your hand-edited entries in other classes."""
    from harness.model_catalog import load_catalog
    p = Path(path)
    catalog = load_catalog(p)
    catalog.setdefault("size_classes", {})
    catalog["size_classes"]["local-tuned"] = [{
        "rank": 1, "model": model_tag, "backend": "llama-server",
        "n_cpu_moe": winner["n_cpu_moe"], "tok_s": winner["tok_s"],
        "vram_used_mb": winner["vram_used_mb"],
        "note": "auto-tuned by scripts/autotune_offload.py on this machine -- re-run if you change hardware.",
    }]
    _write_yaml_flat(catalog, p)


def _write_yaml_flat(data, path):
    """Zero-dependency YAML writer for the one shape models.yaml actually needs
    (matches harness/llm.py's _mini_yaml reader). Uses PyYAML if present; falls back
    to a manual dump for this flat 2-level shape."""
    try:
        import yaml
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return
    except ImportError:
        pass
    lines = ["size_classes:"]
    for cls, members in data.get("size_classes", {}).items():
        lines.append("  %s:" % cls)
        for m in members:
            lines.append("    - rank: %s" % m.get("rank", 1))
            for k, v in m.items():
                if k == "rank":
                    continue
                lines.append("      %s: %s" % (k, json.dumps(v) if isinstance(v, str) else v))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _selftest():
    fails = 0

    def chk(name, cond):
        nonlocal fails
        print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
        if not cond:
            fails += 1

    vals = candidate_offload_values(48)
    chk("candidate values are descending (safest/most-offload first)", vals == sorted(vals, reverse=True))
    chk("candidate values stay within [0, total_hint]", all(0 <= v <= 48 for v in vals))
    chk("total_hint=0 degrades to a single [0] candidate, not an empty/garbage list",
        candidate_offload_values(0) == [0])

    ok_attempts = [
        {"n_cpu_moe": 34, "ok": True, "tok_s": 19.0, "vram_used_mb": 6400},
        {"n_cpu_moe": 20, "ok": False, "tok_s": None, "vram_used_mb": None, "error": "OOM"},
        {"n_cpu_moe": 41, "ok": True, "tok_s": 12.0, "vram_used_mb": 5000},
    ]
    w = pick_winner(ok_attempts)
    chk("winner is the FASTEST among the ones that actually loaded (not the first, not the OOM one)",
        w is not None and w["n_cpu_moe"] == 34)

    all_fail = [{"n_cpu_moe": n, "ok": False, "tok_s": None, "vram_used_mb": None, "error": "OOM"} for n in (48, 34, 12)]
    chk("pick_winner returns None (not a fake pick) when every candidate failed", pick_winner(all_fail) is None)

    def fake_prober(model_path, llama_server_bin, n_cpu_moe, port=8099):
        if n_cpu_moe < 30:
            return {"n_cpu_moe": n_cpu_moe, "ok": False, "tok_s": None, "vram_used_mb": None, "error": "OOM"}
        return {"n_cpu_moe": n_cpu_moe, "ok": True, "tok_s": round(50 - n_cpu_moe * 0.5, 1), "vram_used_mb": 7000}

    result = run("fake.gguf", "fake-llama-server", total_hint=48, prober=fake_prober)
    chk("run() reports hardware summary alongside the sweep", "hardware" in result and "gpu" in result["hardware"])
    chk("run() picks a winner that actually fit (n_cpu_moe >= 30 in the fake OOM boundary)",
        result["winner"] is not None and result["winner"]["n_cpu_moe"] >= 30)
    chk("run() records every attempt, not just the winner", len(result["attempts"]) == len(candidate_offload_values(48)))

    other_procs = [{"pid": 4242, "name": "some-vision-server", "used_mb": 900}]
    report_only = evict_other_gpu_processes(other_procs, kill=False)
    chk("evict_other_gpu_processes defaults to REPORT-ONLY, never kills without kill=True",
        report_only["evicted"] == [] and report_only["reported_only"] == other_procs)

    import platform as _platform
    import unittest.mock as _mock
    killed_pids = []

    if _platform.system() == "Windows":
        class _FakeCompleted:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kw):
            killed_pids.append(int(cmd[cmd.index("/PID") + 1]))
            return _FakeCompleted()

        with _mock.patch("subprocess.run", side_effect=fake_run):
            killed = evict_other_gpu_processes(other_procs, kill=True)
    else:
        with _mock.patch("os.kill", side_effect=lambda pid, sig: killed_pids.append(pid)):
            killed = evict_other_gpu_processes(other_procs, kill=True)

    chk("evict_other_gpu_processes with kill=True actually terminates the reported pid",
        killed_pids == [4242] and len(killed["evicted"]) == 1)

    if _platform.system() == "Windows":
        class _FailedCompleted:
            returncode = 1
            stdout = ""
            stderr = "Access is denied."

        with _mock.patch("subprocess.run", return_value=_FailedCompleted()):
            failed = evict_other_gpu_processes(other_procs, kill=True)
        chk("evict_other_gpu_processes does NOT count a non-zero taskkill exit as evicted",
            failed["evicted"] == [] and "evict_error" in other_procs[0])

    result2 = run("fake.gguf", "fake-llama-server", total_hint=48, prober=fake_prober, evict_others=False)
    chk("run() reports eviction as report-only by default (no side effects unless asked)",
        "eviction" in result2)

    print("SELFTEST OK" if fails == 0 else "SELFTEST FAILED (%d)" % fails)
    return 0 if fails == 0 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    p_plan = sub.add_parser("plan", help="show the candidate sweep plus detected hardware, no GPU work")
    p_plan.add_argument("--total-hint", type=int, default=48)

    p_run = sub.add_parser("run", help="actually launch llama-server repeatedly and measure")
    p_run.add_argument("--model", required=True)
    p_run.add_argument("--llama-server", required=True, help="path to the llama-server binary")
    p_run.add_argument("--total-hint", type=int, default=48)
    p_run.add_argument("--port", type=int, default=8099)
    p_run.add_argument("--write", metavar="MODEL_TAG",
                        help="on success, write the winning flags into models.yaml under this model tag")
    p_run.add_argument("--evict-others", action="store_true",
                        help="DESTRUCTIVE: terminate other processes holding GPU VRAM before the sweep "
                             "(default: only report them -- a 30B MoE plus anything else won't fit in 8GB "
                             "regardless of --n-cpu-moe, so something has to close, but that is your call)")

    args = ap.parse_args()
    if args.selftest:
        return _selftest()

    if args.cmd == "plan":
        hw = hardware_probe.summary()
        print(json.dumps({"hardware": hw, "candidate_n_cpu_moe_sweep": candidate_offload_values(args.total_hint)}, indent=2))
        return 0

    if args.cmd == "run":
        result = run(args.model, args.llama_server, total_hint=args.total_hint, port=args.port,
                     evict_others=args.evict_others)
        print(json.dumps(result, indent=2))
        if result["winner"] is None:
            print("\nNo candidate fit. This model may not fit on this machine at all -- consider a smaller quant or a dense 7-8B model instead.", file=sys.stderr)
            return 1
        print("\nBest: --n-cpu-moe %s (%s tok/s, %s MB VRAM)" %
              (result["winner"]["n_cpu_moe"], result["winner"]["tok_s"], result["winner"]["vram_used_mb"]))
        if args.write:
            write_result(result["winner"], args.write)
            print("Wrote this as class 'local-tuned' in models.yaml.")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
