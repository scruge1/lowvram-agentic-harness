"""Prepare one hardware report through the existing project path; check it read-only.

No model request, service discovery, tuning or model selection is performed.
Passing the fixed factual checks still requires separate semantic review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


SCHEMA = "first-project/v1"
INPUTS = ("hardware-facts.json", "FIRST-PROJECT.md")
MANIFEST = "first-project.json"
OUTPUT = "hardware-report.md"
MAX_BYTES = 64 * 1024


class FirstProjectError(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def measured(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def word_count(text):
    """Count Unicode word tokens; keep joined filenames, numbers and words whole."""
    return len(re.findall(r"\b\w+(?:[.,'’-]\w+)*\b", text))


def _rows(facts):
    return [
        {"label": "RAM total", "value": facts["ram_total_gb"], "unit": "GB (decimal)"},
        {"label": "GPU VRAM", "value": facts["gpu_vram_mib"], "unit": "MiB"},
        {"label": "Storage total", "value": facts["storage_total_gb"], "unit": "GB (decimal)"},
        {"label": "Configured context", "value": facts["configured_model"]["context_tokens"], "unit": "tokens"},
        {"label": "Configured output", "value": facts["configured_model"]["output_tokens"], "unit": "tokens"},
    ]


def _facts(home, config):
    from harness import hardware_probe, onboarding

    observed = onboarding.inventory(home / "projects")
    hardware = observed["hardware"]
    models_path = home / "agent/models.json"
    metadata = json.loads(models_path.read_text(encoding="utf-8"))
    selected = config.get("model")
    matches = [item for item in metadata.get("providers", {}).get("local", {}).get("models", [])
               if isinstance(item, dict) and item.get("id") == selected]
    model = matches[0] if len(matches) == 1 else {}
    storage_bytes = measured(observed["storage"].get("total_bytes"))
    gpu = hardware["gpu"]
    return {
        "schema": "first-project-facts/v1", "observed_at": observed["observed_at"],
        "system": observed["system"],
        "ram_total_gb": measured(hardware["ram"].get("total_gb")),
        "gpu_name": gpu.get("name") if gpu.get("available") else None,
        "gpu_vram_mib": measured(gpu.get("vram_total_mb")) if gpu.get("available") else None,
        "storage_total_gb": round(storage_bytes / 1e9, 1) if storage_bytes is not None else None,
        "storage_measured_path": observed["storage"]["measured_existing_path"],
        "configured_model": {"provider": "local", "id": selected if isinstance(selected, str) else None,
                             "context_tokens": measured(model.get("contextWindow")),
                             "output_tokens": measured(model.get("maxTokens")),
                             "state": "configured_metadata_only"},
        "sources": {"inventory": {"module": "harness/onboarding.py", "sha256": digest(Path(onboarding.__file__).read_bytes())},
                    "hardware_probe": {"module": "harness/hardware_probe.py", "sha256": digest(Path(hardware_probe.__file__).read_bytes())},
                    "model_metadata": {"file": "agent/models.json", "sha256": digest(models_path.read_bytes())}},
        "limits": observed["limits"] + [
            "Unavailable observations remain null; write unknown, do not infer a value.",
            "hardware_probe reports the first observed GPU; it does not select an inference device.",
            "Configured model caps are not observed serving limits, local-inference proof or hardware-fit qualification.",
            "This preparation makes no model request and does not execute an offload tuner.",
            "Subsequent model/tool execution requires its actual trace; this input cannot prove what a later run did."],
    }


def prepare(home, name):
    """Create only an explicitly new normal Git/board project; preserve failures."""
    from harness import home as agent_home
    from harness import home_entry

    home = Path(home).expanduser().resolve(strict=True)
    with home_entry.consumer(home):
        home, config = agent_home.load(home)
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise FirstProjectError("Use a new project name with letters, digits, hyphens or underscores.")
        projects = home / "projects"
        if projects.is_symlink() or projects.resolve(strict=True) != projects or not projects.is_dir():
            raise FirstProjectError("Use the selected home's existing projects directory without redirection.")
        root = home / "projects" / name
        if root.exists() or root.is_symlink():
            raise FirstProjectError("Project already exists; preserve it and choose a new name.")
        facts = _facts(home, config)
        # The existing project function owns Git creation and native board/context
        # admission. This helper neither invents identity nor initializes a second board.
        admission = agent_home.project(home, name)
        if root.is_symlink() or root.resolve(strict=True) != root:
            raise FirstProjectError("New project path is redirected.")
        instructions = (
            "# First hardware report\n\n"
            "Create hardware-report.md, a useful 250-400 word Markdown report from hardware-facts.json. "
            "Cite that input. Use a three-column Markdown table: Measurement | Value | Unit. "
            "Copy the labels and units listed below exactly; write unknown for null values.\n\n"
            + "\n".join("- " + row["label"] + " | " + row["unit"] for row in _rows(facts)) + "\n\n"
            "Explain measured inventory versus configured model caps. Preserve unknowns. "
            "Do not infer a customer's RAM, model fit, GPU selection, running service or tool capability. "
            "Give practical next steps. Inventory only observes; actual tuning would launch a server and make "
            "inference requests. It is not authorized by this task. Your saved report is a file-changing action. "
            "Do not call the complete run read-only. Do not assert a word count; the fixed checker counts it.\n\n"
            "Read the complete installed supervised-tasks/SKILL.md through native read. Use project_admit first; "
            "then agent_capabilities, system_tool_query, relevant local memory and project_knowledge_query. "
            "Read project_context for this directory and complete remaining_reads. Select an authorized ready card. "
            "After compaction refresh project_context before workflow_step. Do not repeat project_admit and erase "
            "the observations just collected. Aim near300 words. Pass the COMPLETE report text in the action argv; never assume a body file exists. "
            "Declare only hardware-report.md as output. Use the pinned check argv returned by prepare; "
            "it checks files relative to cwd and returns 1 from an empty directory. "
            "Do not edit these inputs or first-project.json. A passed checker still needs semantic review. "
            "No model/server/GPU changes, tuning, downloads, cloud fallback or commits.\n\n"
            "Word count uses Unicode word tokens; joined filenames, decimal/grouped numbers and hyphenated "
            "words count as one. Markdown separator characters do not count as words.\n"
        )
        contents = {"hardware-facts.json": json.dumps(facts, indent=2) + "\n", "FIRST-PROJECT.md": instructions}
        for relative, text in contents.items():
            with (root / relative).open("xb") as stream:
                stream.write(text.encode("utf-8"))
        manifest = {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                    "inputs": {relative: digest(text.encode("utf-8")) for relative, text in contents.items()},
                    "output": OUTPUT, "words": {"minimum": 250, "maximum": 400}, "rows": _rows(facts)}
        raw = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        with (root / MANIFEST).open("xb") as stream:
            stream.write(raw)
        return {"schema": SCHEMA, "status": "prepared", "project_root": str(root),
                "admission": admission, "manifest_sha256": digest(raw),
                "check_argv": [sys.executable, "-B", str(Path(__file__).resolve()), "check", "--expected-sha256", digest(raw)],
                "model_requests": 0, "semantic_review": "required_after_real_report"}


def _read(root, relative):
    path = root / relative
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True).parent != root:
        raise FirstProjectError("Missing or redirected project file: " + relative)
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise FirstProjectError("Project file exceeds 64 KiB: " + relative)
    return raw


def check(root, expected_sha256):
    """Read only fixed relative inputs/output; never claim semantic acceptance."""
    result = {"schema": "first-project-check/v1", "passed": False, "checks": [],
              "semantic_review": "required", "tuner_execution": "not_observed_by_this_checker",
              "authority": "fixed_predicates_only", "changes": [], "model_requests": 0}

    def record(name, passed, **detail):
        result["checks"].append(dict(name=name, passed=bool(passed), **detail))

    try:
        root = Path(root).resolve(strict=True)
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
            raise FirstProjectError("Use the original prepare manifest SHA-256 in the verifier argv.")
        raw = _read(root, MANIFEST)
        if digest(raw) != expected_sha256:
            raise FirstProjectError("First-project manifest byte drift.")
        manifest = json.loads(raw)
        if (not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA
                or set(manifest.get("inputs", {})) != set(INPUTS)
                or manifest.get("output") != OUTPUT or manifest.get("words") != {"minimum": 250, "maximum": 400}):
            raise FirstProjectError("Unsupported first-project check contract.")
        for relative, expected in manifest["inputs"].items():
            record("unchanged-input:" + relative, digest(_read(root, relative)) == expected)
        facts = json.loads(_read(root, "hardware-facts.json"))
        if manifest.get("rows") != _rows(facts):
            raise FirstProjectError("Fact rows differ from the original check contract.")
        text = _read(root, OUTPUT).decode("utf-8")
        count = word_count(text)
        result["word_count"] = count
        record("word-count", 250 <= count <= 400, minimum=250, maximum=400, actual=count)
        record("source-citation", "hardware-facts.json" in text)
        rows = {}
        for line in text.splitlines():
            parts = [part.strip() for part in line.strip().strip("|").split("|")]
            if len(parts) == 3:
                rows.setdefault(parts[0], []).append(parts[1:])
        for expected in manifest["rows"]:
            values = rows.get(expected["label"], [])
            matches = False
            if len(values) == 1 and values[0][1] == expected["unit"]:
                value = values[0][0]
                if expected["value"] is None:
                    matches = value.lower() == "unknown"
                elif re.fullmatch(r"(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)(?:\.\d+)?", value):
                    try:
                        matches = Decimal(value.replace(",", "")) == Decimal(str(expected["value"]))
                    except InvalidOperation:
                        pass
            record("fact:" + expected["label"], matches, expected=expected, observed=values)
        result["report_sha256"] = digest(text.encode("utf-8"))
        result["passed"] = all(item["passed"] for item in result["checks"])
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
        result["error"] = str(error)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare", help="Create one new normal hardware-report project; no model call.")
    create.add_argument("--home", required=True, type=Path)
    create.add_argument("--name", required=True)
    verify = commands.add_parser("check", help="Read fixed files in cwd; return 1 if missing or invalid.")
    verify.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        report = prepare(args.home, args.name) if args.command == "prepare" else check(Path.cwd(), args.expected_sha256)
    except (OSError, ValueError) as error:
        report = {"schema": SCHEMA, "status": "failed", "error": str(error), "model_requests": 0}
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "prepared" or report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
