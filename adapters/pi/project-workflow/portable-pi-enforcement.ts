/** Target candidate: admission before tools; existing portable hooks own retry/completion. */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import * as fs from "node:fs";
import * as path from "node:path";
import { createHash } from "node:crypto";

const execute = promisify(execFile);
const hash = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const inspection = new Set(["read", "find", "grep", "ls"]);
const communication = new Set(["codex_reply", "codex_send", "codex_sessions"]);
type Source = { role: string; path: string; sha256: string };
type Binding = { task_id: string; policy_sha256: string; sources: Source[]; allowed_tools: string[];
  read_roots: string[]; worker_outputs: string[]; require_native_discovery?: boolean };

function canonical(value: any): any {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}

function canonicalPath(candidate: string): string {
  let parent = candidate;
  const absent: string[] = [];
  while (!fs.existsSync(parent)) {
    absent.unshift(path.basename(parent));
    const next = path.dirname(parent);
    if (next === parent) throw new Error("No path ancestor.");
    parent = next;
  }
  return path.join(fs.realpathSync(parent), ...absent);
}

function under(candidate: string, root: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === "" || (relative !== ".." && !relative.startsWith(".." + path.sep) && !path.isAbsolute(relative));
}

export function loadBinding(environment: NodeJS.ProcessEnv): Binding {
  const file = environment.ENFORCEMENT_ADMISSION_FILE;
  const expected = environment.ENFORCEMENT_ADMISSION_SHA256;
  const policy = environment.ENFORCEMENT_POLICY_FILE;
  if (!file || !policy || !environment.ENFORCEMENT_HOOK_EVENT_DIR || !expected?.match(/^[a-f0-9]{64}$/)) {
    throw new Error("No supervised admission binding.");
  }
  const bytes = fs.readFileSync(file);
  if (hash(bytes) !== expected) throw new Error("Admission binding changed.");
  const value = JSON.parse(bytes.toString("utf8"));
  if (typeof value.task_id !== "string" || !Array.isArray(value.sources) || !Array.isArray(value.allowed_tools) ||
      !Array.isArray(value.read_roots) || !Array.isArray(value.worker_outputs)) {
    throw new Error("Admission binding has invalid types.");
  }
  if (value.allowed_tools.some((name: unknown) => typeof name !== "string")) throw new Error("Invalid tool set.");
  if (value.require_native_discovery !== undefined && typeof value.require_native_discovery !== "boolean") {
    throw new Error("Invalid discovery prerequisite.");
  }
  if (value.read_roots.some((root: unknown) => typeof root !== "string" || !path.isAbsolute(root)) ||
      value.worker_outputs.some((output: unknown) => typeof output !== "string" || !path.isAbsolute(output))) throw new Error("Invalid scope.");
  const policyBytes = fs.readFileSync(policy);
  if (hash(policyBytes) !== value.policy_sha256 || JSON.parse(policyBytes.toString("utf8")).task_id !== value.task_id) {
    throw new Error("Policy identity changed.");
  }
  for (const role of ["skill", "checkpoint", "plan"]) {
    if (!value.sources.some((source: Source) => source.role === role)) throw new Error("Required source role missing.");
  }
  const paths = new Set<string>();
  for (const source of value.sources) {
    if (typeof source.path !== "string" || !path.isAbsolute(source.path) ||
        typeof source.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(source.sha256)) throw new Error("Invalid source.");
    const canonical = fs.realpathSync(source.path);
    if (paths.has(canonical) || hash(fs.readFileSync(canonical)) !== source.sha256) throw new Error("Source identity changed.");
    paths.add(canonical);
  }
  const plan = JSON.parse(fs.readFileSync(value.sources.find((s: Source) => s.role === "plan").path, "utf8"));
  for (const key of ["question", "expected_evidence", "verification", "stop_condition"]) {
    if (typeof plan[key] !== "string" || plan[key].trim().length < 8 || plan[key].length > 1000) throw new Error("Incomplete plan.");
  }
  return value;
}

function commandStrings(event: any): string[] {
  const input = event.input ?? {};
  if (["bash", "powershell"].includes(event.toolName)) return [input.command ?? ""];
  if (event.toolName === "run_step") return [input.action ?? "", input.verify ?? ""];
  if (event.toolName === "run_ledger") return Array.isArray(input.steps)
    ? input.steps.flatMap((step: any) => [step.action ?? "", step.verify ?? ""]) : [];
  return [];
}

export function createAdmissionGate(readBinding: () => Binding) {
  const loaded = new Set<string>();
  const readCoverage = new Map<string, Set<number>>();
  const failures = new Map<string, number>();
  const blockedCalls = new Set<string>();
  let transportFailed = false;
  let denied = 0;
  let discovered = false;
  const fingerprint = (event: any) => hash(JSON.stringify(canonical([event.toolName, event.input ?? {}])));
  return {
    failedTransport() { transportFailed = true; },
    call(event: any, cwd = process.cwd()) {
      const block = (reason: string, terminal = false) => {
        blockedCalls.add(event.toolCallId);
        return { block: true, reason, terminate: terminal || ++denied >= 3 };
      };
      if (communication.has(event.toolName)) return;
      let binding: Binding;
      try { binding = readBinding(); } catch { return block("Portable workflow: supervised binding or required source is missing/stale.", true); }
      if (transportFailed) return block("Portable workflow: host hook failed; no further executable work.", true);
      if (inspection.has(event.toolName)) {
        try {
          const candidate = canonicalPath(path.resolve(cwd, event.input?.path ?? "."));
          if (binding.sources.some(source => fs.realpathSync(source.path) === candidate) ||
              binding.read_roots.some(root => under(candidate, fs.realpathSync(root)))) return;
        } catch { /* Missing paths are denied without echoing raw input. */ }
        return block("Portable workflow: inspection path is outside this task's declared scope.", true);
      }
      if (!binding.allowed_tools.includes(event.toolName)) return block("Portable workflow: tool is outside this task's declared set.", true);
      if (!binding.sources.every(source => loaded.has(fs.realpathSync(source.path)))) {
        return block("Portable workflow: read the pinned skill, checkpoint and plan completely before executing tools.");
      }
      if (binding.require_native_discovery && !discovered && event.toolName !== "agent_capabilities") {
        return block("Portable workflow: call native agent_capabilities after all source read results; discovery must succeed before planning writes or probes.");
      }
      if (["write", "edit"].includes(event.toolName)) {
        try {
          const target = canonicalPath(path.resolve(cwd, event.input?.path ?? ""));
          if (!binding.worker_outputs.some(output => canonicalPath(output) === target)) {
            return block("Portable workflow: native writes are limited to declared worker outputs.", true);
          }
        } catch { return block("Portable workflow: invalid output path.", true); }
      }
      if ((failures.get(fingerprint(event)) ?? 0) >= 2) return block("Portable workflow: identical input failed twice; inspect state and change the approach.", true);
      for (const command of commandStrings(event)) {
        if (typeof command !== "string" || /--break-system-packages\b/.test(command) ||
            /\b(?:pip3?|uv\s+pip)\b[^\n]*\binstall\b[^\n]*\|\s*(?:tail|head)\b/.test(command)) {
          return block("Portable workflow: unsafe install pattern; preserve exit status and use the existing isolated environment.", true);
        }
      }
      denied = 0;
    },
    result(event: any, cwd: string) {
      if (blockedCalls.delete(event.toolCallId)) return { blocked: true };
      const key = fingerprint(event);
      const failed = event.isError === true || event.details?.ok === false;
      if (event.toolName === "agent_capabilities") {
        discovered = !failed && event.details?.ok === true &&
          event.details?.snapshot?.schema === "pi-native-capabilities/v1" &&
          typeof event.details?.snapshot?.session_id === "string" &&
          Array.isArray(event.details?.snapshot?.configured_tools);
      }
      if (failed) failures.set(key, (failures.get(key) ?? 0) + 1);
      else failures.delete(key);
      if (event.toolName !== "read" || failed || event.details?.truncation?.truncated) return;
      try {
        const binding = readBinding();
        const sourcePath = fs.realpathSync(path.resolve(cwd, event.input.path));
        const source = binding.sources.find(source => fs.realpathSync(source.path) === sourcePath);
        if (!source) return;
        const bytes = fs.readFileSync(sourcePath);
        if (hash(bytes) !== source.sha256) throw new Error("Source changed during read.");
        const lines = bytes.toString("utf8").split("\n");
        const offset = event.input.offset ?? 1;
        const limit = event.input.limit ?? lines.length;
        if (!Number.isSafeInteger(offset) || offset < 1 || offset > lines.length ||
            !Number.isSafeInteger(limit) || limit < 1) return;
        const start = offset - 1;
        const end = Math.min(start + limit, lines.length);
        let expected = lines.slice(start, end).join("\n");
        if (end < lines.length) expected += `\n\n[${lines.length - end} more lines in file. Use offset=${end + 1} to continue.]`;
        // Count only bytes actually delivered by the native read result, not a
        // model's declaration or a requested range that was truncated.
        if (!Array.isArray(event.content) || event.content.length !== 1 ||
            event.content[0].type !== "text" || event.content[0].text !== expected) return;
        const coverage = readCoverage.get(sourcePath) ?? new Set<number>();
        for (let index = start; index < end; index++) coverage.add(index);
        readCoverage.set(sourcePath, coverage);
        if (coverage.size === lines.length) loaded.add(sourcePath);
      } catch { transportFailed = true; }
    },
    status() { return { loaded_source_count: loaded.size, hook_failed: transportFailed, pending_failed_input_count: failures.size }; },
  };
}

export default function (pi: ExtensionAPI) {
  const gate = createAdmissionGate(() => loadBinding(process.env));
  let followups = 0;
  const helper = process.env.ENFORCEMENT_ADAPTER_HELPER;
  const python = process.env.ENFORCEMENT_ADAPTER_PYTHON;
  function failedHook() {
    gate.failedTransport();
    const directory = process.env.ENFORCEMENT_HOOK_EVENT_DIR;
    try {
      if (directory) fs.writeFileSync(path.join(directory, "adapter-failure.json"), JSON.stringify({ failed: true }));
    } catch { /* The in-memory failure latch remains closed if evidence storage fails. */ }
  }
  async function send(payload: object) {
    if (!helper || !python || !path.isAbsolute(helper) || !path.isAbsolute(python)) throw new Error("Hook helper not configured.");
    const done = new Promise<string>((resolve, reject) => {
      const child = execFile(python, [helper, "hook"],
        { timeout: 5000, killSignal: "SIGKILL", maxBuffer: 8192 },
        (error, output) => error ? reject(new Error("Hook helper failed.")) : resolve(output));
      child.stdin?.on("error", () => {
        child.kill("SIGKILL");
        reject(new Error("Hook helper input failed."));
      });
      child.stdin?.end(JSON.stringify(payload));
    });
    return JSON.parse(await done || "{}");
  }
  // Admission errors block before execution. Hook outcomes still use the existing
  // portable supervisor rather than another model-driven retry authority.
  pi.on("tool_call", async (event, ctx) => {
    const decision = gate.call(event, ctx.cwd);
    if (decision?.block) {
      try {
        await send({ event_type: "admission_denied", tool_call_id: event.toolCallId,
          status: "blocked", tool_name: event.toolName,
          input_sha256: hash(JSON.stringify(canonical(event.input))) });
      } catch {
        failedHook();
        return { ...decision, terminate: true };
      }
    }
    return decision;
  });
  pi.on("tool_result", async (event, ctx) => {
    const admission = gate.result(event, ctx.cwd);
    if (admission?.blocked) return;
    try {
      await send({ event_type: "tool_result", tool_call_id: event.toolCallId,
        status: event.isError || event.details?.ok === false ? "failed" : "success",
        tool_name: event.toolName, tool_input: { sha256: hash(JSON.stringify(canonical(event.input))) },
        error_summary: event.isError ? "Pi tool failed; inspect original task evidence." : "" });
    } catch {
      failedHook();
      return { isError: true, content: [{ type: "text", text: "Portable host hook failed. Stop and retain task evidence; no result acceptance." }] };
    }
  });
  pi.on("agent_settled", async () => {
    try {
      const directive = await send({ event_type: "completion_check" });
      const binding = loadBinding(process.env);
      const policy = JSON.parse(fs.readFileSync(process.env.ENFORCEMENT_POLICY_FILE!, "utf8"));
      if (directive.allow === false && followups < policy.retry.inner_tool_max_attempts) {
        followups += 1;
        pi.sendMessage({ customType: "trusted-task-enforcement", content: directive.reason, display: true },
          { triggerTurn: true, deliverAs: "followUp" });
      }
      await execute(python!, [helper!, "proof", JSON.stringify({ ...gate.status(), task_id: binding.task_id, followups,
        completion_allowed: directive.allow !== false })],
        { timeout: 5000, maxBuffer: 8192 });
    } catch { failedHook(); }
  });
}
