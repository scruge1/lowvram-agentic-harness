import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { randomUUID } from 'node:crypto';
import { packetDigest } from './packet-digest.ts';

const EXECUTION = new Set(['workflow_step', 'run_step', 'run_ledger', 'bash', 'write', 'edit']);
export function registerReadLoopGuard(pi: ExtensionAPI, bindings: {
  identity: () => unknown;
  stall: (reason: string) => void;
}) {
  type Probe = { signature: string; binding: string; repeats: number; marker?: string; delivered: boolean };
  let probe: Probe | undefined;
  let pending: { signature: string; binding: string; toolCallId: string; content: string; input: any; repeats: number } | undefined;
  const admitted = new Map<string, { signature: string; binding: string; marker: string }>();
  const executing = new Set<string>();
  const reset = () => { probe = undefined; pending = undefined; admitted.clear(); };
  for (const event of ['agent_start', 'agent_end', 'session_start', 'session_tree', 'session_shutdown'] as const)
    pi.on(event, async () => { reset(); executing.clear(); });
  pi.on('input', async () => { reset(); });
  pi.on('tool_execution_start', async (event: any) => {
    if (EXECUTION.has(event.toolName)) executing.add(event.toolCallId);
  });
  pi.on('tool_execution_end', async (event: any) => { executing.delete(event.toolCallId); });
  pi.on('tool_call', async (event: any) => {
    if (event.toolName === 'read' && !event.parentToolCallId && probe?.delivered && probe.marker
        && probe.binding === packetDigest(bindings.identity()))
      admitted.set(event.toolCallId, { signature: probe.signature, binding: probe.binding, marker: probe.marker });
  });
  pi.on('before_provider_request', async (event: any) => {
    const payload = JSON.stringify(event.payload);
    if (probe?.marker && typeof payload === 'string' && payload.includes(probe.marker)) probe.delivered = true;
  });
  pi.on('tool_result', async (event: any) => {
    if (event.toolName !== 'read' || event.parentToolCallId) { reset(); return; }
    const admission = admitted.get(event.toolCallId);
    admitted.delete(event.toolCallId);
    const binding = packetDigest(bindings.identity());
    const content = packetDigest([event.content, Boolean(event.isError)]);
    const signature = packetDigest(['read', event.input, content, binding]);
    if (!probe || probe.signature !== signature) {
      probe = { signature, binding, repeats: 1, delivered: false }; pending = undefined; return;
    }
    probe.repeats++;
    if (probe.repeats === 2) probe.marker = 'READ-OBSERVATION-RECOVERY:' + randomUUID();
    if (admission?.signature === signature && admission.binding === binding
        && admission.marker === probe.marker && probe.delivered) pending = { signature, binding, toolCallId: event.toolCallId,
      content, input: structuredClone(event.input), repeats: probe.repeats };
  });
  pi.on('turn_end', async (event: any, ctx: any) => {
    if (!pending) return;
    if (ctx.signal?.aborted || ctx.hasPendingMessages?.()
        || pending.binding !== packetDigest(bindings.identity())) { reset(); return; }
    if (executing.size) return;
    const index = event.toolResults?.findIndex((message: any) => message.toolCallId === pending!.toolCallId);
    const entryId = index >= 0 ? event.toolResultEntryIds?.[index] : undefined;
    const entry = entryId && ctx.sessionManager.getBranch().find((item: any) => item.id === entryId);
    const message = entry?.message;
    // Both tool_result and message_end are pre-commit hooks. turn_end is after all
    // parallel batch results are persisted, and this exact result must be present.
    if (message?.role !== 'toolResult' || message.toolName !== 'read'
        || message.toolCallId !== pending.toolCallId
        || packetDigest([message.content, Boolean(message.isError)]) !== pending.content) return;
    const reason = 'No progress: repeated identical read input and unchanged result after a delivered recovery instruction. '
      + 'Inspect the producer/job, a new log region, or an existing bounded wait before resuming. Read input: '
      + JSON.stringify(pending.input).slice(0, 1000);
    bindings.stall(reason);
    pi.appendEntry('pi-read-stall/v1', { reason, tool_call_id: pending.toolCallId,
      source_entry_id: entryId, observation_sha256: pending.content, repeats: pending.repeats,
      action: 'abort_current_read_cycle_only' });
    reset();
    ctx.ui?.notify?.(reason, 'warning');
    ctx.abort();
  });
  return {
    warning() {
      if (!probe?.marker) return '';
      return '\n' + probe.marker + ': The same read arguments returned the same observation twice. '
        + 'Before repeating, use one different inspection of the producer/job or a new log region, '
        + 'or use an existing bounded wait for legitimate polling. Repeating unchanged evidence after this instruction '
        + 'will stop this model operation. This is not permission to restart workers, replay effects, or declare completion.';
    },
  };
}
