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

/** Bounded, privacy-preserving read of the currently visible Pi context metadata.
 * Raw system prompts, tool descriptions, schema bodies, and model identities
 * are never returned by this projection. SDK usage values are observations,
 * not a provider-serialized request or an effective context guarantee.
 */
export function collectContextProfile(
  pi: Pick<ExtensionAPI, 'getAllTools' | 'getActiveTools'>, ctx: any, snapshot: any,
) {
  const hash = (text: string) => createHash('sha256').update(text).digest('hex');
  const finite = (value: unknown, positive = false): number | null =>
    typeof value === 'number' && Number.isFinite(value) && (positive ? value > 0 : value >= 0) ? value : null;
  const profile = {
    schema: 'pi-context-profile/v1',
    observed_at_ms: Date.now(),
    snapshot_sha256: hash(JSON.stringify(snapshot)),
    system_prompt_utf8_bytes: null as number | null,
    system_prompt_sha256: null as string | null,
    configured_tool_count: snapshot.configured_tools.length,
    active_tool_count: snapshot.configured_tools.filter((tool: any) => tool.active).length,
    active_parameter_schema_utf8_bytes: null as number | null,
    active_parameter_schema_sha256: null as string | null,
    active_declaration_metadata_utf8_bytes: null as number | null,
    active_declaration_metadata_sha256: null as string | null,
    native_reported_context_tokens: null as number | null,
    native_reported_context_window: null as number | null,
    model_identity_sha256: null as string | null,
    effective_provider_payload_captured: false,
    authority: 'none',
  };
  try {
    const prompt = ctx?.getSystemPrompt?.();
    if (typeof prompt === 'string') {
      profile.system_prompt_utf8_bytes = Buffer.byteLength(prompt, 'utf8');
      profile.system_prompt_sha256 = hash(prompt);
    }
  } catch { /* Unknown is not zero. */ }
  try {
    const usage = ctx?.getContextUsage?.();
    profile.native_reported_context_tokens = finite(usage?.tokens);
    profile.native_reported_context_window = finite(usage?.contextWindow, true);
  } catch { /* Context usage may be unavailable. */ }
  try {
    const { provider, id } = ctx?.model ?? {};
    if (typeof provider === 'string' && typeof id === 'string'
        && provider.length <= 256 && id.length <= 512) {
      profile.model_identity_sha256 = hash(JSON.stringify({ provider, id }));
    }
  } catch { /* Never serialize an entire provider/model object. */ }
  try {
    const all = pi.getAllTools();
    const active = names(pi.getActiveTools());
    const expectedActive = snapshot.configured_tools.filter((tool: any) => tool.active).map((tool: any) => tool.name).sort();
    const expectedAll = snapshot.configured_tools.map((tool: any) => tool.name).sort();
    if (!Array.isArray(all) || all.length > 10000
        || JSON.stringify(names(all.map(tool => tool?.name))) !== JSON.stringify(expectedAll)
        || JSON.stringify(active) !== JSON.stringify(expectedActive)) return profile;
    const selected = all.filter(tool => active.includes(tool.name)).sort((a, b) => a.name.localeCompare(b.name));
    const schemas: string[] = [];
    const declarations: string[] = [];
    let schemaBytes = 0, declarationBytes = 0;
    for (const tool of selected) {
      if (!tool.parameters || typeof tool.parameters !== 'object' || Array.isArray(tool.parameters)
          || typeof tool.description !== 'string') return profile;
      const schema = JSON.stringify(tool.parameters);
      const declaration = JSON.stringify({ name: tool.name, description: tool.description, parameters: tool.parameters });
      schemaBytes += Buffer.byteLength(schema);
      declarationBytes += Buffer.byteLength(declaration);
      if (schemaBytes > 8 * 1024 * 1024 || declarationBytes > 8 * 1024 * 1024) return profile;
      schemas.push(schema);
      declarations.push(declaration);
    }
    const schemaText = '[' + schemas.join(',') + ']';
    const declarationText = '[' + declarations.join(',') + ']';
    profile.active_parameter_schema_utf8_bytes = Buffer.byteLength(schemaText);
    profile.active_parameter_schema_sha256 = hash(schemaText);
    profile.active_declaration_metadata_utf8_bytes = Buffer.byteLength(declarationText);
    profile.active_declaration_metadata_sha256 = hash(declarationText);
  } catch { /* Missing or cyclic metadata cannot break capability discovery. */ }
  return profile;
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
        let contextProfile: ReturnType<typeof collectContextProfile> | undefined;
        // Disabled by default: hashing large tool declarations on every
        // capability refresh would itself increase CPU/context overhead.
        if (process.env.PI_CONTEXT_PROFILE_ENABLE === '1') {
          try {
            contextProfile = collectContextProfile(pi, ctx, snapshot);
            // Separate opt-in to retain the hash-only local telemetry.
            if (process.env.PI_CONTEXT_PROFILE_PERSIST === '1') {
              try { pi.appendEntry('pi-context-profile/v1', contextProfile); }
              catch { /* Optional telemetry cannot gate capability discovery. */ }
            }
          } catch { /* Preserve original capabilities on telemetry error. */ }
        }
        return { content: [{ type: 'text', text: JSON.stringify(snapshot) }],
          details: { ok: true, snapshot, ...(contextProfile ? { context_profile: contextProfile } : {}) } };
      } catch {
        // Do not expose exceptions from a stale runtime or custom metadata.
        return { content: [{ type: 'text', text: 'Capability read failed: no valid snapshot. Retry after checking runtime state.' }], details: { ok: false, error: 'invalid_or_unavailable_registry' }, isError: true };
      }
    },
  });
}
