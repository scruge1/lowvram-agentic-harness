import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';

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

export default function (pi: ExtensionAPI) {
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
