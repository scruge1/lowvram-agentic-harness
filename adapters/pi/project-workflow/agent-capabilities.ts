import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

function names(values: unknown): string[] {
  if (!Array.isArray(values) || values.length > 10000 || values.some((v) => typeof v !== 'string' || !v || v.length > 256)) throw new Error('invalid_registry');
  if (new Set(values).size !== values.length) throw new Error('duplicate_registry_identity');
  return [...values].sort();
}

export function collectCapabilities(pi: Pick<ExtensionAPI, 'getAllTools' | 'getActiveTools'>, sessionId: string) {
  if (typeof sessionId !== 'string' || !sessionId || sessionId.length > 256) throw new Error('missing_session_identity');
  // Read at invocation, not factory time. Do not change active tools.
  const activeBefore = names(pi.getActiveTools());
  const all = pi.getAllTools();
  if (!Array.isArray(all) || all.length > 10000) throw new Error('invalid_registry');
  const configured = names(all.map((tool) => tool?.name));
  const activeAfter = names(pi.getActiveTools());
  if (JSON.stringify(activeBefore) !== JSON.stringify(activeAfter)) throw new Error('registry_changed_during_read');
  const configuredSet = new Set(configured);
  const activeSet = new Set(activeAfter);
  if (activeAfter.some((name) => !configuredSet.has(name))) throw new Error('active_tool_not_configured');
  const tools = all.map((tool) => {
    const info: Record<string, string> = {};
    for (const field of ['path', 'source', 'scope', 'origin'] as const) {
      const value = tool.sourceInfo?.[field];
      if (value !== undefined) {
        if (typeof value !== 'string' || value.length > 2048) throw new Error('invalid_source_metadata');
        info[field] = value;
      }
    }
    return { name: tool.name, active: activeSet.has(tool.name), interface: 'pi-native-callable', source_info: info };
  }).sort((a, b) => a.name.localeCompare(b.name));
  const snapshot = {
    schema: 'pi-native-capabilities/v1', session_id: sessionId, observed_at: new Date().toISOString(),
    configured_tools: tools,
    shell_inventory: { state: 'not_inspected', entries: [] },
    installed_extensions: { state: 'not_inspected', entries: [] },
    limits: ['Registry observation only; active does not mean tested or healthy.', 'Reported source metadata is not an installed-file hash or action authorization.', 'No shell/transport/browser/memory probes or tools activated.'],
  };
  if (JSON.stringify(snapshot).length > 1024 * 1024) throw new Error('snapshot_too_large');
  return snapshot;
}

export function resourceWaits(branch: any[]) {
  const selected = branch.findLast(entry => entry.type === 'custom' && entry.customType === 'pi-kanban-selection/v1')?.data?.project?.root;
  const state = branch.findLast(entry => entry.type === 'custom' && entry.customType === 'pi-request-work-state/v1')?.data;
  const rows = Array.isArray(state?.task_waits) && typeof selected === 'string'
    ? state.task_waits.filter((wait: any) => wait.root === selected && wait.kind === 'resource' && wait.status === 'waiting'
      && typeof wait.id === 'string' && wait.id.length <= 256 && typeof wait.task === 'string' && wait.task.length <= 256) : [];
  return { source: 'current_native_branch', count: rows.length, truncated: rows.length > 8,
    rows: rows.slice(0, 8).map((wait: any) => ({ wait_id: wait.id, task_id: wait.task, kind: 'resource', status: 'waiting' })),
    inspect: { tool: 'kanban_intake_status', arguments: {} },
    limits: 'Retained wait metadata only; inspect its original reason/trigger. This read does not verify a receipt, resolve a wait, grant permission or earn progress.' };
}

async function resourceStatus(pi: ExtensionAPI, ctx: any, signal?: AbortSignal) {
  if (signal?.aborted) throw new Error('cancelled');
  const home = process.env.AGENT_HOME, python = process.env.AGENT_HOME_PYTHON;
  if (!home || !python || !path.isAbsolute(home) || !path.isAbsolute(python) || fs.realpathSync(home) !== home) throw new Error('home');
  const configFile = path.join(home, 'home.json');
  if (fs.statSync(configFile).size > 65536) throw new Error('home');
  const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
  if (config.schema !== 'agent-home/v1' || config.home !== home) throw new Error('identity');
  const runtime = path.join(home, 'runtime'), manifestFile = path.join(runtime, 'runtime-manifest.json');
  if (fs.statSync(manifestFile).size > 4 * 1024 * 1024) throw new Error('manifest');
  const raw = fs.readFileSync(manifestFile), digest = (data: Buffer) => createHash('sha256').update(data).digest('hex');
  if (digest(raw) !== config.runtime_manifest_sha256) throw new Error('manifest');
  const manifest = JSON.parse(raw.toString('utf8'));
  const closure = ['harness/__init__.py', 'harness/resource_status.py', 'harness/home_entry.py', 'harness/model_service.py',
    'harness/model_service_handoff.py', 'harness/model_profiles.py', 'harness/hardware_probe.py', 'harness/bootstrap.py',
    'harness/model-service-pins.json', 'adapters/pi/project-workflow/agent-capabilities.ts'];
  for (const relative of closure) {
    const file = path.join(runtime, relative), rows = manifest.files?.filter((item: any) => item.path === relative);
    if (!Array.isArray(rows) || rows.length !== 1 || fs.realpathSync(file) !== file || digest(fs.readFileSync(file)) !== rows[0].sha256)
      throw new Error('source');
  }
  if (fs.realpathSync(new URL(import.meta.url)) !== path.join(runtime, 'adapters/pi/project-workflow/agent-capabilities.ts')) throw new Error('loaded_source');
  const result = await pi.exec(python, ['-I', '-B', path.join(runtime, 'harness/resource_status.py'), '--home', home],
    { cwd: home, timeout: 15000, signal });
  if (signal?.aborted || result.killed || result.code !== 0 || Buffer.byteLength(result.stdout) > 12288) throw new Error('read');
  const report = JSON.parse(result.stdout);
  if (report.schema !== 'agent-home-resource-status/v1' || report.home !== home || report.authority !== 'none' || report.generative_requests !== 0)
    throw new Error('report');
  report.waits_observed = resourceWaits(ctx.sessionManager.getBranch());
  if (Buffer.byteLength(JSON.stringify(report)) > 12288) throw new Error('bounds');
  ctx.ui?.setStatus?.('resource-status', `Model: ${report.service?.status ?? 'unknown'}; queue/busy unknown; ${report.waits_observed.count} retained resource waits`);
  return report;
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: 'resource_status', label: 'Current home resources',
    description: 'Read this managed home\'s owned service identity and bounded local health status, measured host RAM/CPU and retained resource-wait IDs. Queue/busy/fit are unknown; attached endpoints grant no process ownership. No start, stop, reservation, receipt resolution, productive progress or inference.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_id, _params, signal, _update, ctx) {
      try { const report = await resourceStatus(pi, ctx, signal); return { content: [{ type: 'text' as const, text: JSON.stringify(report) }], details: { ok: true, report } }; }
      catch { return { content: [{ type: 'text' as const, text: 'Resource status unavailable or cancelled. Inspect this home\'s lifecycle/identity and retained service evidence; no action was taken.' }], details: { ok: false }, isError: true }; }
    },
  });
  pi.registerCommand('resource-status', {
    description: 'Read this home\'s resource status once; no model request or resource action.',
    handler: async (args, ctx) => {
      try {
        if (args.trim()) throw new Error('no_arguments');
        fs.writeSync(1, JSON.stringify(await resourceStatus(pi, ctx)) + '\n');
      }
      catch { fs.writeSync(1, JSON.stringify({ schema: 'agent-home-resource-status/v1', status: 'unavailable', authority: 'none', generative_requests: 0 }) + '\n'); }
    },
  });
  pi.registerCommand('agent-health', {
    description: 'Read this managed home\'s loaded native bindings and tool readiness without a model request.',
    handler: async (_args, ctx) => {
      try {
        const home = process.env.AGENT_HOME;
        if (!home || !path.isAbsolute(home) || fs.realpathSync(home) !== home) throw new Error('home');
        const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json'), 'utf8'));
        if (config.schema !== 'agent-home/v1' || config.home !== home) throw new Error('identity');
        const manifest = fs.readFileSync(path.join(home, 'runtime/runtime-manifest.json'));
        const manifestHash = createHash('sha256').update(manifest).digest('hex');
        if (manifestHash !== config.runtime_manifest_sha256) throw new Error('manifest');
        const mcp = JSON.parse(fs.readFileSync(path.join(home, 'agent/mcp.json'), 'utf8'));
        const mcpConfigured = mcp.mcpServers?.mempalace?.enabled === true;
        const memoryTool = 'mcp__mempalace__mempalace_search';
        const deadline = Date.now() + 15000;
        while (mcpConfigured && !pi.getAllTools().some(tool => tool.name === memoryTool) && Date.now() < deadline)
          await new Promise(resolve => setTimeout(resolve, 25));
        const snapshot = collectCapabilities(pi, ctx.sessionManager.getSessionId());
        const configured = snapshot.configured_tools.map(tool => tool.name);
        const active = snapshot.configured_tools.filter(tool => tool.active).map(tool => tool.name);
        const required = config.profile === 'core' ? ['agent_capabilities', 'system_tool_query']
          : ['workflow_step', 'project_context', 'kanban_intake_route', 'validated_memory_query'];
        if (config.selected_packages?.research) required.push('web_research');
        const missing = required.filter(name => !active.includes(name));
        const mcpObserved = configured.includes(memoryTool);
        if (mcpConfigured && !mcpObserved) missing.push(memoryTool);
        const report = { schema: 'pi-agent-health/v1', home, cwd: ctx.cwd,
          runtime_manifest_sha256: manifestHash, active_tools: active, configured_tools: configured,
          readiness: { ok: missing.length === 0, missing_tools: missing,
            mcp_configured: mcpConfigured, mcp_observed: mcpObserved },
          model: { provider: ctx.model?.provider ?? null, id: ctx.model?.id ?? null,
            context_window: ctx.model?.contextWindow ?? null, max_output: ctx.model?.maxTokens ?? null },
          session_id: snapshot.session_id,
          prompt_sha256: createHash('sha256').update(ctx.getSystemPrompt()).digest('hex'),
          authority: 'none', generative_requests: 0 };
        // Pi's noninteractive output guard redirects console and stdout.write.
        // A public native descriptor write preserves this machine JSON channel.
        fs.writeSync(1, JSON.stringify(report) + '\n');
      } catch {
        fs.writeSync(1, JSON.stringify({ schema: 'pi-agent-health/v1', readiness: { ok: false },
          error: 'managed_native_health_unavailable', authority: 'none', generative_requests: 0 }) + '\n');
      }
    },
  });
  pi.registerTool({
    name: 'agent_capabilities', label: 'Agent callable tools',
    description: 'Read the current Pi configured tool registry and active names. Separate callable identity from shell inventory and installed files. This does not probe tool health or authorize actions.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_id, _params, signal, _update, ctx) {
      if (signal?.aborted) return { content: [{ type: 'text', text: 'Capability read cancelled.' }], details: { ok: false, error: 'cancelled' }, isError: true };
      try {
        const snapshot = collectCapabilities(pi, ctx.sessionManager.getSessionId());
        return { content: [{ type: 'text', text: JSON.stringify(snapshot) }], details: { ok: true, snapshot } };
      } catch {
        // Do not expose exceptions from a stale runtime or custom metadata.
        return { content: [{ type: 'text', text: 'Capability read failed: no valid snapshot. Retry after checking runtime state.' }], details: { ok: false, error: 'invalid_or_unavailable_registry' }, isError: true };
      }
    },
  });
}
