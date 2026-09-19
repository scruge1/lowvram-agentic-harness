#!/usr/bin/env python3
"""Create a non-overwriting ICM-shaped workspace under a blessed SSOT."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--why", required=True)
    parser.add_argument("--parent-authority", required=True)
    parser.add_argument("--lanes", type=int, default=0)
    parser.add_argument(
        "--system-setup",
        action="store_true",
        help="require a research wiki before system implementation stages",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_root(root: Path) -> None:
    resolved = root.resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError("workspace root cannot be a filesystem root")
    if resolved == Path.home().resolve():
        raise ValueError("workspace root cannot be the user home directory")
    if root.exists() and not root.is_dir():
        raise ValueError("workspace root exists and is not a directory")


def build_files(args: argparse.Namespace, root: Path) -> dict[Path, str]:
    stamp = utc_now()
    target_json = {
        "target": args.target,
        "why_this_target": args.why,
        "authority": args.parent_authority,
        "workspace_role": "ICM context container governed by blessed SSOT controls",
        "authority_state": "scaffolded",
        "system_research_wiki": {
            "required": args.system_setup,
            "path": "wiki/SYSTEM-RESEARCH-WIKI.md" if args.system_setup else None,
            "status": "unbuilt" if args.system_setup else "not_required",
        },
        "source_evidence": [],
        "alternatives_considered": [],
        "not_allowed_to_skip_because": [
            "low confidence",
            "large evidence volume",
            "a specialist disagrees",
            "another route looks easier",
        ],
    }
    lanes = "\n".join(
        f"- Lane {number}: define scope, owner, artifact, receipt, and verifier."
        for number in range(1, args.lanes + 1)
    ) or "- No parallel lanes declared. Add bounded stages before work."
    files = {
        root / "AGENTS.md": (
            "# Workspace Instructions\n\nRead `PROJECT-SSOT.md` first. Reuse the "
            "parent authority. Do not create a second PRD or ledger. Specialists own "
            "only their declared artifacts and receipts. The main thread owns status "
            "and synthesis.\n"
        ),
        root / "PROJECT-SSOT.md": (
            "# Workspace SSOT Router\n\n"
            f"Opened: {stamp}\n\n## Authority\n\n{args.parent_authority}\n\n"
            "This is an ICM context container governed by blessed SSOT controls.\n\n"
            "## Read Order\n\n1. `TARGET-PROVENANCE.json`\n"
            "2. `ACTIVE-CHECKPOINT.md`\n3. `COVERAGE-MATRIX.md`\n"
            "4. `wiki/SYSTEM-RESEARCH-WIKI.md` when target provenance requires it\n"
            "5. Only the artifact needed for the current stage\n\n"
            "## Candidate Run Order\n\nDeclare stage, owner, output, receipt, and gate before execution. "
            "This order has no blessed authority until the full contract is compiled, configured, enforced, and tested.\n"
        ),
        root / "ACTIVE-CHECKPOINT.md": (
            "# Active Checkpoint\n\n"
            f"Updated: {stamp}\n\nCurrent target: {args.target}\n\n"
            "Current state: workspace opened; stages not yet verified.\n\n"
            + (
                "Next allowed action: declare and run the research-wiki stage before implementation.\n"
                if args.system_setup
                else "Next allowed action: declare the ordered stages and unique producers.\n"
            )
        ),
        root / "TARGET-PROVENANCE.json": json.dumps(target_json, indent=2) + "\n",
        root / "CONTRACT-SOURCE-MANIFEST.json": json.dumps(
            {
                "schema": "blessed-ssot-contract-sources/v1",
                "authority_state": "scaffolded",
                "compilation_status": "uncompiled",
                "upstream_repository": None,
                "upstream_head": None,
                "sources": [],
                "requirement_inventory": "REQUIREMENT-INVENTORY.jsonl",
                "semantic_drift_report": None,
            },
            indent=2,
        ) + "\n",
        root / "REQUIREMENT-INVENTORY.jsonl": "",
        root / "RUN-REGISTER.jsonl": json.dumps(
            {
                "ts": stamp,
                "run_id": "workspace-open",
                "stage": "S0",
                "owner": "main",
                "target": args.target,
                "status": "running",
                "receipt": "OPERATION-RECEIPTS/000-workspace-open.json",
            },
            separators=(",", ":"),
        ) + "\n",
        root / "DIARY.md": f"# Workspace Diary\n\n## {stamp}\n\n- Workspace opened.\n",
        root / "COVERAGE-MATRIX.md": f"# Coverage Matrix\n\n{lanes}\n",
        root / "wiki" / "HOWTO.md": (
            "# Workspace How-To\n\nStart at `../PROJECT-SSOT.md`. Load only the "
            "current stage context. Write large output under `../artifacts/`. "
            "Write one receipt per producing operation. When target provenance "
            "requires system research, complete `SYSTEM-RESEARCH-WIKI.md` before "
            "implementation-affecting work.\n"
        ),
    }
    if args.system_setup:
        files[root / "wiki" / "SYSTEM-RESEARCH-WIKI.md"] = (
            "# System Research Wiki\n\n"
            f"Subject: {args.target}\n\n"
            f"Opened: {stamp}\n\n"
            "Status: unbuilt\n\n"
            "## Scope and Questions\n\nPending retained research.\n\n"
            "## Research Run and Raw Evidence\n\nPending.\n\n"
            "## Sources and Supported Claims\n\nPending.\n\n"
            "## Exact Local Facts\n\nPending.\n\n"
            "## Claim Comparison\n\nPending.\n\n"
            "## Selected Defaults and Limits\n\nPending.\n\n"
            "## Rejected Alternatives\n\nPending.\n\n"
            "## Unknowns and Contradictions\n\nPending.\n\n"
            "## Finite Test Matrix and Restoration\n\nPending.\n\n"
            "## Verification and Next Allowed Action\n\nPending.\n"
        )
    return files


def main() -> int:
    args = parse_args()
    if args.lanes < 0:
        raise ValueError("lanes must be zero or greater")
    root = Path(args.root).expanduser().resolve()
    validate_root(root)
    files = build_files(args, root)
    collisions = [str(path) for path in files if path.exists()]
    if collisions and not args.resume:
        raise FileExistsError("workspace files already exist; use --resume: " + ", ".join(collisions))
    result = {
        "root": str(root),
        "dry_run": args.dry_run,
        "resume": args.resume,
        "create": [str(path) for path in files if not path.exists()],
        "preserve": collisions,
    }
    if not args.dry_run:
        for directory in (root, root / "OPERATION-RECEIPTS", root / "artifacts", root / "wiki"):
            directory.mkdir(parents=True, exist_ok=True)
        for path, content in files.items():
            if not path.exists():
                path.write_text(content, encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
