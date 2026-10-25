"""Read-only retained-work decision. Pi owns admission, state, tools and dispatch."""
import asyncio
import hashlib
from importlib import metadata
import json
import sys

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

SCHEMA = "pi-retained-work-decision/v2"
RESULT_SCHEMA = SCHEMA
MAX_BYTES = 262144
TERMINAL = {"done", "archived"}
STATUSES = {"triage", "todo", "ready", "running", "scheduled", "blocked", "review", "done", "archived"}
TOP_KEYS = {"schema", "version", "project_root", "mode", "reason", "pending_inputs",
            "coverage", "anchors", "tasks", "prerequisite_status", "excluded", "selected_task", "waiting_tasks", "session_wait"}
TASK_KEYS = {"id", "project_root", "status", "source", "parent", "prerequisites", "priority",
             "integration_known", "integration_invalidated", "integration_complete"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def text(value, limit=256):
    return isinstance(value, str) and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value)


def keys(value, expected, where):
    require(type(value) is dict and set(value) == expected, "Invalid " + where + " keys")


def items(value, limit, where):
    require(type(value) is list and len(value) <= limit, "Invalid " + where)


def unique_strings(value, limit, where):
    items(value, limit, where)
    require(all(text(x) for x in value) and len(set(value)) == len(value), "Invalid " + where)


def validate(packet):
    keys(packet, TOP_KEYS, "packet")
    require(packet["schema"] == SCHEMA and type(packet["version"]) is int and packet["version"] == 2,
            "Unsupported schema or version")
    root = packet["project_root"]
    require(text(root, 4096) and root.startswith("/") and ".." not in root.split("/"), "Invalid project root")
    require(packet["mode"] in {"running", "paused", "blocked", "waiting", "complete"}, "Invalid mode")
    require(type(packet["reason"]) is str and len(packet["reason"]) <= 3072
            and all(ord(c) >= 32 or c in "\n\r\t" for c in packet["reason"]), "Invalid reason")
    unique_strings(packet["pending_inputs"], 128, "pending inputs")
    unique_strings(packet["waiting_tasks"], 128, "waiting tasks")
    require(type(packet["session_wait"]) is bool, "Invalid session wait flag")
    keys(packet["coverage"], {"complete", "truncated", "missing"}, "coverage")
    require(type(packet["coverage"]["complete"]) is bool and type(packet["coverage"]["truncated"]) is bool,
            "Invalid coverage flags")
    unique_strings(packet["coverage"]["missing"], 512, "missing coverage")
    for field, maximum in [("anchors", 128), ("excluded", 512)]:
        items(packet[field], maximum, field)
        for ref in packet[field]:
            keys(ref, {"task", "source"}, field + " reference")
            require(text(ref["task"]) and text(ref["source"]), "Invalid " + field + " reference")
        require(len({(r["task"], r["source"]) for r in packet[field]}) == len(packet[field]),
                "Duplicate " + field + " references")
    items(packet["tasks"], 512, "tasks")
    ids = []
    for task in packet["tasks"]:
        keys(task, TASK_KEYS, "task")
        require(text(task["id"]) and text(task["source"]) and text(task["project_root"], 4096), "Invalid task reference")
        require(task["parent"] is None or text(task["parent"]), "Invalid containment parent")
        require(task["status"] in STATUSES, "Invalid task status")
        unique_strings(task["prerequisites"], 128, "prerequisites")
        require(type(task["priority"]) is int and -1000000 <= task["priority"] <= 1000000, "Invalid priority")
        for flag in ["integration_known", "integration_invalidated", "integration_complete"]:
            require(type(task[flag]) is bool, "Invalid integration flag")
        require(not (task["integration_invalidated"] and task["integration_complete"]), "Contradictory integration facts")
        ids.append(task["id"])
    require(len(set(ids)) == len(ids), "Duplicate task ID")
    statuses = packet["prerequisite_status"]
    require(type(statuses) is dict and len(statuses) <= 2048, "Invalid prerequisite status map")
    require(all(text(k) and v in STATUSES for k, v in statuses.items()), "Invalid prerequisite status")
    for task in packet["tasks"]:
        require(task["id"] not in statuses or statuses[task["id"]] == task["status"], "Conflicting task status")
    require(packet["selected_task"] is None or text(packet["selected_task"]), "Invalid selected task")
    return packet


def result(packet, decision, reason, selection=None):
    return {"schema": RESULT_SCHEMA, "ok": True, "decision": decision,
            "packet_sha256": digest(packet), "reason": reason, "selected": selection}


class Boundary(Executor):
    def __init__(self):
        super().__init__(id="native-intake-boundary")

    @handler
    async def receive(self, packet: dict, ctx: WorkflowContext[dict, dict]):
        if packet["pending_inputs"]:
            await ctx.yield_output(result(packet, "route_pending", "Route retained pending input before selecting work"))
        elif packet["mode"] in {"paused", "blocked"} or packet["session_wait"]:
            await ctx.yield_output(result(packet, "hold", packet["reason"]))
        else:
            await ctx.send_message(packet)


class Provenance(Executor):
    def __init__(self):
        super().__init__(id="retained-source-provenance")

    @handler
    async def check(self, packet: dict, ctx: WorkflowContext[dict, dict]):
        tasks = {t["id"]: t for t in packet["tasks"]}
        anchors = {(a["task"], a["source"]) for a in packet["anchors"]}
        excluded = {(e["task"], e["source"]) for e in packet["excluded"]}
        valid, cancelled, invalid = set(), set(), set()
        for key, task in tasks.items():
            current, seen, chain = task, set(), []
            admitted = False
            for _ in range(64):
                if current["id"] in seen or current["project_root"] != packet["project_root"] or current["source"] != task["source"]:
                    break
                seen.add(current["id"])
                chain.append((current["id"], current["source"]))
                if chain[-1] in excluded:
                    cancelled.add(key)
                    break
                if chain[-1] in anchors:
                    admitted = True
                    break
                current = tasks.get(current["parent"])
                if current is None:
                    break
            if admitted:
                valid.add(key)
            elif key not in cancelled:
                invalid.add(key)
        valid_refs = {(tasks[key]["id"], tasks[key]["source"]) for key in valid}
        missing_anchors = list(anchors - excluded - valid_refs)
        await ctx.send_message({"kind": "provenance", "valid": sorted(valid),
            "cancelled": sorted(cancelled), "invalid": sorted(invalid), "missing_anchors": len(missing_anchors)})


class Readiness(Executor):
    def __init__(self):
        super().__init__(id="retained-board-readiness")

    @handler
    async def check(self, packet: dict, ctx: WorkflowContext[dict, dict]):
        statuses = dict(packet["prerequisite_status"])
        statuses.update({t["id"]: t["status"] for t in packet["tasks"]})
        await ctx.send_message({"kind": "readiness", "packet": packet, "statuses": statuses})


class Select(Executor):
    def __init__(self):
        super().__init__(id="retained-work-selection")

    @handler
    async def choose(self, branches: list[dict], ctx: WorkflowContext[dict, dict]):
        require(sorted(b["kind"] for b in branches) == ["provenance", "readiness"], "Incomplete framework fan-in")
        provenance = next(b for b in branches if b["kind"] == "provenance")
        readiness = next(b for b in branches if b["kind"] == "readiness")
        packet, statuses = readiness["packet"], readiness["statuses"]
        valid = set(provenance["valid"])
        tasks = {t["id"]: t for t in packet["tasks"] if t["id"] in valid}
        children = {key: [] for key in tasks}
        for task in tasks.values():
            if task["parent"] in children:
                children[task["parent"]].append(task["id"])
        waiting = set(packet["waiting_tasks"]) & set(tasks)
        # A held scope includes decomposition descendants and transitive dependants.
        for _ in range(len(tasks) + 1):
            expanded = waiting | {t["id"] for t in tasks.values()
                if t["parent"] in waiting or any(p in waiting for p in t["prerequisites"])}
            if expanded == waiting:
                break
            waiting = expanded
        summaries = {}

        def descendants_unfinished(key, stack=()):
            require(key not in stack and len(stack) < 64, "Cyclic or excessive containment depth")
            if key not in summaries:
                summaries[key] = any(child in waiting or tasks[child]["status"] not in TERMINAL
                    or tasks[child]["integration_invalidated"]
                    or descendants_unfinished(child, stack + (key,)) for child in children[key])
            return summaries[key]

        candidates = []
        integration_unknown = False
        outstanding = bool(waiting)
        for key, task in tasks.items():
            descendant_work = descendants_unfinished(key)
            outstanding |= task["status"] not in TERMINAL or task["integration_invalidated"]
            if not task["integration_known"] or not task["integration_complete"]:
                integration_unknown = True
            ready = task["status"] in {"ready", "running"} and key not in waiting
            prerequisites_done = all(statuses.get(p) in TERMINAL and p not in waiting for p in task["prerequisites"])
            if ready and prerequisites_done and not descendant_work:
                candidates.append({"task": key, "source": task["source"],
                                   "action": "integrate" if children[key] else "execute"})
        if candidates:
            candidates.sort(key=lambda c: (-tasks[c["task"]]["priority"], c["task"] != packet["selected_task"], c["task"]))
            await ctx.yield_output(result(packet, "continue", "Continue selected runnable retained work", candidates[0]))
            return
        coverage = packet["coverage"]
        uncertain = (not coverage["complete"] or coverage["truncated"] or bool(coverage["missing"])
                     or provenance["missing_anchors"] or provenance["invalid"] or integration_unknown
                     or any(p not in statuses for t in tasks.values() for p in t["prerequisites"]))
        if not outstanding and not uncertain:
            await ctx.yield_output(result(packet, "queue_complete", "Retained graph terminal only; root outcome is not accepted; compare intended requirements and route necessary follow-up through existing intake"))
        else:
            causes = []
            if not coverage["complete"] or coverage["truncated"] or coverage["missing"]:
                causes.append("coverage incomplete/truncated/missing=" + str(len(coverage["missing"])))
            if provenance["missing_anchors"] or provenance["invalid"]:
                causes.append("source anchors missing=" + str(provenance["missing_anchors"])
                              + ", invalid lineage=" + str(len(provenance["invalid"])))
            waiting_status = [t["id"] + "=" + t["status"] for t in tasks.values() if t["status"] not in TERMINAL]
            if waiting:
                causes.append("dependency waits " + ", ".join(sorted(waiting)[:6]))
            if waiting_status:
                causes.append("tasks " + ", ".join(waiting_status[:6]))
            integration = [t["id"] for t in tasks.values() if not t["integration_known"]
                           or not t["integration_complete"] or t["integration_invalidated"]]
            if integration:
                causes.append("integration unresolved " + ", ".join(integration[:6]))
            dependencies = [t["id"] + "->" + p + "=" + statuses.get(p, "unknown")
                            for t in tasks.values() for p in t["prerequisites"]
                            if statuses.get(p) not in TERMINAL]
            if dependencies:
                causes.append("prerequisites " + ", ".join(dependencies[:6]))
            reason = ("Retained work held: " + "; ".join(causes or ["no runnable retained task"]))[:1024]
            await ctx.yield_output(result(packet, "hold", reason))


async def decide(packet, include_trace=False):
    validate(packet)
    require(metadata.version("agent-framework-core") == "1.21.0", "Agent Framework version drift")
    boundary, provenance, readiness, selection = Boundary(), Provenance(), Readiness(), Select()
    builder = WorkflowBuilder(name="pi-retained-decision-062", start_executor=boundary, max_iterations=4)
    builder.add_edge(boundary, provenance, condition=lambda p: p["mode"] in {"running", "waiting", "complete"} and not p["pending_inputs"])
    builder.add_edge(boundary, readiness, condition=lambda p: p["mode"] in {"running", "waiting", "complete"} and not p["pending_inputs"])
    builder.add_fan_in_edges([provenance, readiness], selection)
    outputs, trace = [], []
    async for event in builder.build().run(packet, stream=True):
        if include_trace:
            trace.append({"type": event.type, "executor_id": getattr(event, "executor_id", None)})
        if event.type == "output":
            outputs.append(event.data)
    require(len(outputs) == 1, "Framework did not return one decision")
    return (outputs[0], trace) if include_trace else outputs[0]


def no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "Duplicate JSON key")
        value[key] = item
    return value


def main():
    packet_hash = None
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES, "Input exceeds 256 KiB")
        packet = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON number")))
        packet_hash = digest(packet)
        output = asyncio.run(decide(packet))
        code = 0
    except (ValueError, TypeError, KeyError, RuntimeError, UnicodeError, RecursionError) as error:
        output = {"schema": RESULT_SCHEMA, "ok": False, "decision": "hold",
                  "packet_sha256": packet_hash, "reason": str(error)[:1024], "selected": None}
        code = 2
    encoded = canonical(output)
    require(len(encoded.encode("utf-8")) < 16384, "Decision output exceeds limit")
    sys.stdout.write(encoded + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
