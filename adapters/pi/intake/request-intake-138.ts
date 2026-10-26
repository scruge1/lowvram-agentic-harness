import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { createHash, randomUUID } from 'node:crypto';
import { buildRetainedPacket, cancelledSelection, nativeCompletionOrder, workKey } from './retained-packet-138.ts';
import { decideRetainedWork, packetDigest } from './decision-bridge-138.ts';
import { checkedReceipt, inspectReceipt, watchReceipt, blockedTaskIds, type TaskWait, type Receipt } from './dependency-receipts-138.ts';
import { registerReadLoopGuard } from './read-loop-079.ts';

// Registered by pi-kanban, not a second extension/board/dispatcher.
const CAPTURE = 'pi-request-capture/v1';
const INTENT = 'pi-request-route-intent/v1';
const ROUTED = 'pi-request-routed/v1';
const STATE = 'pi-request-work-state/v1';
const DISCUSSION = 'pi-request-discussion/v1';
const TERMINAL = new Set(['done', 'archived']);
const EXECUTION = new Set(['workflow_step', 'run_step', 'run_ledger', 'write', 'edit', 'task_agent']);
const digest = (value: unknown) => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const boardTitle = (summary: string) => Array.from(summary.trim()).slice(0, 200).join('').trim();

// The bounded set is only a recent lookup cache. Older credits remain in the
// existing native intake snapshots; eviction must never make old content new.
export function rememberResearchCredit(recent: Set<string>, key: string) {
  recent.delete(key); recent.add(key);
  if (recent.size > 256) recent.delete(recent.values().next().value!);
}
export function researchCreditSeen(branch: any[], recent: Set<string>, key: string) {
  if (recent.has(key)) return true;
  if (!branch.some(entry => entry.type === 'custom' && entry.customType === STATE && entry.data?.research_credit?.key === key)) return false;
  rememberResearchCredit(recent, key); return true;
}
// Native journal recovery only. No child run store or completion authority.
export function unresolvedChildCalls(branch: any[], root?: string) {
  const starts = new Map<string, { data: any; ordinal: number }>();
  const captures = new Map<string, any>(), intents = new Map<string, any>();
  const resumes = new Map<string, number>();
  const identity = (data: any) => digest([data.project?.root, data.project?.projectId, data.project?.boardId,
    data.card, data.parent_card, data.source, data.source_sha256, data.parent_session]);
  for (const [ordinal, entry] of branch.entries()) {
    if (entry.type !== 'custom') continue;
    const data = entry.data;
    if (entry.customType === CAPTURE) captures.set(data.id, data);
    if (entry.customType === INTENT) intents.set(data.id, data.intent);
    if (entry.customType === ROUTED && data.control === 'resume') {
      const capture = captures.get(data.id), intent = intents.get(data.id);
      if (capture && !['historical-unverified', 'extension'].includes(capture.source)
          && intent?.control === 'resume' && typeof intent.project?.root === 'string'
          && capture.project?.root === intent.project.root)
        resumes.set(intent.project.root, ordinal);
    }
    if (entry.customType === 'pi-managed-child-start/v1') {
      if (typeof data?.id !== 'string' || !data.id || typeof data.project?.root !== 'string')
        throw new Error('Invalid managed-child start journal; inspect before execution');
      starts.set(data.id, { data, ordinal });
    }
    if (entry.customType === 'pi-managed-child-result/v1') {
      const start = starts.get(data?.id);
      if (start && identity(start.data) === identity(data)) starts.delete(data.id);
    }
  }
  return [...starts].filter(([, start]) => (!root || start.data.project.root === root)
    && start.ordinal > (resumes.get(start.data.project.root) ?? -1)).map(([id]) => id);
}

type Project = { root: string; projectId: string; boardId: string };
type Part = { kind: 'task' | 'amend' | 'held' | 'question' | 'control'; summary: string;
  task_id?: string; execute?: boolean; priority?: number; expandable?: boolean };
type Capture = { id: string; session: string; text: string; source: string; at: number;
  project: Project | null; sha256: string; images: number };
type Work = { root: string; task: string; source: string };
type State = { mode: 'running' | 'paused' | 'blocked' | 'waiting' | 'complete'; reason: string;
  wait?: { kind: 'user' | 'peer' | 'resource' | 'external'; trigger: string }; next_action?: string;
  conversation?: { source_id: string; phase: 'review' | 'discussion' | 'execution' };
  task_waits?: TaskWait[]; queue: Work[]; requests: number; started: number; progress: number; seen: number; stalls: number;
  research_credit?: { key: string; fingerprint: string; session: string; root: string; task: string; source: string;
    artifact_id: string; content_scope: string; coverage: string } };
type Bindings = { project: () => Project | null; task: () => string | null; child?: () => string | undefined;
  select: (id: string) => void; failed: () => boolean;
  call: (request: Record<string, unknown>, signal?: AbortSignal) => Promise<any> };

export function registerRequestIntake(pi: ExtensionAPI, bindings: Bindings) {
  let captures = new Map<string, Capture>();
  let intents = new Map<string, { project: Project | null; parts: Part[]; control?: string; cancel_task_ids: string[] }>();
  let routed = new Set<string>();
  let deferred = new Set<string>();
  let authorized = new Set<string>();
  let excluded: (Work & { cancel_order: number })[] = [];
  let captureOrdinal = 0;
  let captureOrder = new Map<string, number>();
  let authorizationOrder = new Map<string, number>();
  let revision = 0;
  let alive = true;
  let liveUI: any;
  const initial = (): State => ({ mode: 'running', reason: 'Await request routing', queue: [], task_waits: [],
    requests: 0, started: Date.now(), progress: 0, seen: 0, stalls: 0 });
  let state = initial();
  let serial: Promise<unknown> = Promise.resolve();
  let researchEpoch = 0;
  const recentResearch = new Set<string>();
  const researchCalls = new Map<string, { scope: string; candidate?: boolean; content?: string }>();
  const refreshStatus = () => liveUI?.setStatus?.('request-intake', `Work: ${state.mode}; ${pending().length} unrouted; ${state.queue.length} retained`);
  const save = () => { revision++; pi.appendEntry(STATE, structuredClone(state)); refreshStatus(); };
  const pending = () => [...captures.values()].filter(x => !routed.has(x.id) && !deferred.has(x.id));
  const deferUncommitted = (reason: string) => {
    // Only the current conversational source can settle or be superseded.
    // Legacy/historical pending inputs and frozen uncertain effects stay pending.
    const id = state.conversation?.source_id;
    const capture = id ? captures.get(id) : undefined;
    if (!capture || routed.has(capture.id) || deferred.has(capture.id)
        || intents.has(capture.id) || capture.source === 'historical-unverified') return false;
    pi.appendEntry(DISCUSSION, { id: capture.id, source_sha256: capture.sha256,
      disposition: 'deferred', reason });
    deferred.add(capture.id);
    return true;
  };
  const status = () => ({ ...state, dependency_protocol: 'task-waits/v1', conversation_protocol: 'plan-first/v2',
    deferred_total: deferred.size, deferred_truncated: deferred.size > 12,
    deferred: [...captures.values()].filter(x => deferred.has(x.id)).slice(-12).map(x => ({ id: x.id, sha256: x.sha256,
      excerpt: x.text.slice(0, 160), truncated: x.text.length > 160 })),
    queue: state.queue.slice(0, 30), retained_total: state.queue.length,
    queue_truncated: state.queue.length > 30, pending_total: pending().length, pending_truncated: pending().length > 12,
    pending: pending().slice(0, 12).map(({ text, ...rest }) => ({ ...rest,
    excerpt: text.slice(0, 2500), truncated: text.length > 2500 })) });
  const result = (data: unknown) => ({ content: [{ type: 'text' as const, text: JSON.stringify(data) }], details: { ok: true, result: data } });
  const failed = (error: unknown) => ({ content: [{ type: 'text' as const, text: String(error) }],
    details: { ok: false }, isError: true });
  const readLoop = registerReadLoopGuard(pi, {
    identity: () => ({ project: bindings.project(), task: bindings.task() }),
    stall: reason => {
      if (state.mode !== 'paused' && state.mode !== 'blocked' && state.mode !== 'waiting') {
        state.mode = 'blocked'; state.reason = reason; state.stalls = Math.max(state.stalls, 2); save();
      } else refreshStatus();
    },
  });
  const projectCall = async (project: Project, args: Record<string, unknown>, signal?: AbortSignal) => {
    const reply = await bindings.call({ ...args, project_root: project.root }, signal);
    if (reply?.ok !== true) throw new Error('Board operation did not succeed');
    return reply.result;
  };
  const rememberRouting = (data: any) => {
    const capture = captures.get(data.id), intent = intents.get(data.id);
    for (const item of data.work ?? []) {
      const index = (data.bound ?? []).findIndex((part: any) => part.task_id === item.task);
      const part = intent?.parts[index];
      if (capture && capture.source !== 'historical-unverified' && intent?.project?.root === item.root
          && item.source === capture.id && part?.execute === true
          && ['task', 'amend'].includes(part.kind)) {
        authorized.add(workKey(item)); authorizationOrder.set(workKey(item), captureOrder.get(data.id) ?? -1);
      }
    }
    for (const id of data.cancel_task_ids ?? []) for (const item of state.queue)
      if (item.task === id && !excluded.some(x => workKey(x) === workKey(item)))
        excluded.push({ ...structuredClone(item), cancel_order: captureOrder.get(data.id) ?? Number.MAX_SAFE_INTEGER });
  };
  const stamp = () => digest([revision, alive, state, pending().map(x => x.id),
    bindings.project(), bindings.task(), bindings.failed(), [...authorized], excluded]);
  const researchScope = (ctx: any) => digest([researchEpoch, alive, ctx.sessionManager.getSessionId(),
    bindings.project(), bindings.task(), bindings.failed(), captureOrdinal, pending().map(x => x.id),
    state.mode, state.queue, state.task_waits, [...authorized], excluded]);
  const projectPacket = (ctx: any) => buildRetainedPacket({ state: structuredClone(state),
    project: structuredClone(bindings.project()), selected: bindings.task(), admissionFailed: bindings.failed(),
    pending: pending().map(x => x.id), authorized: new Set(authorized), excluded: structuredClone(excluded),
    authorizationOrder: new Map(authorizationOrder),
    completionOrder: nativeCompletionOrder(ctx.sessionManager.getBranch()),
    call: bindings.call });
  const recordDecision = (decision: any, packet: any) => pi.appendEntry('pi-work-decision/v1', {
    ...decision, authority: 'retained_queue_only_not_root_acceptance',
    projection: { tasks: packet.tasks.length, anchors: packet.anchors.length,
      complete: packet.coverage.complete, truncated: packet.coverage.truncated,
      missing: packet.coverage.missing.length },
  });
  const decide = async (ctx: any) => {
    const before = stamp();
    const packet = await projectPacket(ctx);
    if (!alive || stamp() !== before) throw new Error('STALE_RETAINED_DECISION: native input or work changed during projection');
    const decision = await decideRetainedWork(packet);
    if (!alive || stamp() !== before) throw new Error('STALE_RETAINED_DECISION: native input or work changed during helper execution');
    const readback = await projectPacket(ctx);
    if (!alive || stamp() !== before || packetDigest(readback) !== packetDigest(packet))
      throw new Error('STALE_RETAINED_DECISION: retained board or native state changed before use');
    return { decision, packet };
  };
  let liveCtx: any;
  let watchEpoch = 0;
  const watchers = new Map<string, () => void>();
  const cleanWatchers = () => { watchEpoch++; for (const close of watchers.values()) close(); watchers.clear(); };
  const journalDependency = (wait: TaskWait, extra: any) => pi.appendEntry('pi-task-dependency/v1', {
    wait_id: wait.id, root: wait.root, task: wait.task, source: wait.source, key: wait.key, ...extra });
  const maybeWake = async (wait: TaskWait, ctx: any, allowWake: boolean) => {
    // A receipt verifies its registered condition; it is never owner approval.
    if (!allowWake || wait.notice || !alive || !ctx || bindings.project()?.root !== wait.root
        || pending().length || bindings.failed() || state.mode === 'paused' || state.mode === 'blocked' || state.wait) return;
    const { decision, packet } = await decide(ctx);
    if (decision.decision !== 'continue' || wait.status !== 'resolved') return;
    let admitted = packet.tasks.find((t: any) => t.id === wait.task && t.source === wait.source);
    if (!admitted) return; // cancelled/reauthorised tickets cannot wake a different source
    for (let depth = 0; admitted && depth < 64; depth++) {
      if (packet.excluded.some((x: any) => x.task === admitted.id && x.source === admitted.source)) return;
      admitted = packet.tasks.find((t: any) => t.id === admitted.parent && t.source === wait.source);
    }
    recordDecision(decision, packet);
    if (state.mode === 'waiting') state.mode = 'running';
    state.stalls = 0;
    wait.notice = 'claimed'; save(); // persist before delivery; never replay uncertain sends
    try {
      pi.sendMessage({ customType: 'pi-dependency-ready/v1', display: true,
        content: 'The registered dependency for retained task ' + wait.task + ' is verified: ' + wait.evidence
          + '. Read the current board and continue authorised ready work ' + decision.selected.task
          + '. Preserve pause/cancellation/input gates; this receipt does not accept the root outcome.',
        details: { wait_id: wait.id, task: wait.task } }, { triggerTurn: true, deliverAs: 'followUp' });
      wait.notice = 'sent'; save();
      journalDependency(wait, { status: 'resolved', delivery: 'sent' });
    } catch (error) {
      wait.notice = 'suppressed'; save();
      journalDependency(wait, { status: 'resolved', delivery: 'uncertain_no_replay', reason: String(error).slice(0, 300) });
    }
  };
  const checkDependency = async (id: string, epoch: number, allowWake: boolean) => {
    if (!alive || epoch !== watchEpoch) return;
    const wait = state.task_waits?.find(w => w.id === id && w.status === 'waiting');
    if (!wait?.receipt) return;
    const observed = inspectReceipt(wait.root, wait.receipt);
    if (!observed.verified || !alive || epoch !== watchEpoch) return;
    wait.status = 'resolved'; wait.evidence = observed.reason + '; sha256=' + observed.sha256;
    journalDependency(wait, { status: 'resolved', receipt_sha256: observed.sha256 }); save();
    watchers.get(id)?.(); watchers.delete(id);
    await maybeWake(wait, liveCtx, allowWake);
  };
  const syncWatchers = (allowWake: boolean) => {
    const active = (state.task_waits ?? []).filter(w => w.status === 'waiting' && w.receipt);
    for (const [id, close] of watchers) if (!active.some(w => w.id === id)) { close(); watchers.delete(id); }
    const epoch = watchEpoch;
    for (const wait of active) {
      if (watchers.has(wait.id)) continue;
      try {
        const schedule = (wake: boolean) => {
          serial = serial.then(() => checkDependency(wait.id, epoch, wake)).catch(error => {
            journalDependency(wait, { status: 'verification_error', reason: String(error).slice(0, 300) });
          });
        };
        watchers.set(wait.id, watchReceipt(wait.receipt!, () => schedule(true), () => {
          watchers.get(wait.id)?.(); watchers.delete(wait.id);
          journalDependency(wait, { status: 'watch_unavailable_no_polling' });
        }));
        schedule(allowWake); // closes the register/watch race; reload never starts inference
      } catch (error) { journalDependency(wait, { status: 'watch_unavailable', reason: String(error).slice(0, 300) }); }
    }
  };
  const restore = (_event: any, ctx: any) => {
    researchEpoch++; researchCalls.clear(); recentResearch.clear();
    cleanWatchers(); liveCtx = ctx;
    liveUI = ctx.ui;
    revision++; alive = true; authorized = new Set(); excluded = []; captureOrdinal = 0; captureOrder = new Map(); authorizationOrder = new Map();
    captures = new Map(); intents = new Map(); routed = new Set(); deferred = new Set(); state = initial();
    const priorReasons = new Map<string, string>();
    const retiredReason = 'Automatic continuation budget reached; retained work is not complete';
    let repairedCurrentReason = false;
    for (const entry of ctx.sessionManager.getBranch()) {
      if (entry.type !== 'custom') continue;
      if (entry.customType === CAPTURE) { captures.set(entry.data.id, entry.data); captureOrder.set(entry.data.id, ++captureOrdinal); }
      if (entry.customType === INTENT) { intents.set(entry.data.id, entry.data.intent); deferred.delete(entry.data.id); }
      if (entry.customType === DISCUSSION) {
        const capture = captures.get(entry.data.id);
        if (capture && capture.sha256 === entry.data.source_sha256 && entry.data.disposition === 'deferred'
            && !intents.has(capture.id)) deferred.add(capture.id);
      }
      if (entry.customType === ROUTED) {
        rememberRouting(entry.data);
        routed.add(entry.data.id);
        for (const item of entry.data.work ?? []) if (!state.queue.some(x => x.root === item.root && x.task === item.task)) state.queue.push(item);
        state.queue = state.queue.filter(x => !(entry.data.cancel_task_ids ?? []).includes(x.task));
        if (entry.data.control === 'pause') { state.mode = 'paused'; state.reason = 'Recovered user pause'; }
        if (entry.data.control === 'resume') { state.mode = 'running'; state.reason = 'Recovered user resume'; delete state.wait; delete state.next_action; }
        if (entry.data.work?.length && state.mode === 'complete') state.mode = 'running';
      }
      if (entry.customType === STATE) {
        if (/^[a-f0-9]{64}$/.test(entry.data?.research_credit?.key ?? '')) rememberResearchCredit(recentResearch, entry.data.research_credit.key);
        const saved = structuredClone(entry.data);
        const { reason, ...nonReason } = saved;
        const key = packetDigest(nonReason);
        repairedCurrentReason = reason === retiredReason;
        if (repairedCurrentReason) saved.reason = priorReasons.get(key)
          ?? 'Retired continuation-limit diagnostic; original stop reason is unknown. Existing work mode is unchanged.';
        else if (typeof reason === 'string') priorReasons.set(key, reason);
        state = saved;
        state.task_waits ??= [];
      }
    }
    const unfinished = unresolvedChildCalls(ctx.sessionManager.getBranch(), bindings.project()?.root);
    if (unfinished.length && !['paused', 'waiting'].includes(state.mode)) {
      state.mode = 'blocked'; state.reason = 'Unsettled in-memory child: ' + unfinished.slice(0, 8).join(', ')
        + '. Inspect retained start/tool/output evidence; fresh owner resume is required, never automatic replay.';
      save();
    }
    // Repair only the retired diagnostic. Preserve every non-reason field and write back once.
    if (repairedCurrentReason) save();
    // Restart/reload never starts inference by itself.
    refreshStatus(); syncWatchers(false);
  };
  pi.on('session_start', restore);
  pi.on('session_tree', restore);
  pi.on('session_shutdown', async () => { alive = false; revision++; researchCalls.clear(); cleanWatchers(); liveCtx = undefined; });
  pi.on('input', async (event: any, ctx: any) => {
    // Extension/peer messages are not fresh human approval. Raw Pi transcript is retained.
    if (event.source === 'extension') return { action: 'continue' as const };
    researchEpoch++; researchCalls.clear();
    deferUncommitted('superseded_uncommitted_conversation');
    const capture: Capture = { id: randomUUID(), session: ctx.sessionManager.getSessionId(),
      text: event.text, source: event.source, at: Date.now(), project: structuredClone(bindings.project()),
      sha256: digest(event.text), images: event.images?.length ?? 0 };
    pi.appendEntry(CAPTURE, capture);
    captures.set(capture.id, capture);
    captureOrder.set(capture.id, ++captureOrdinal);
    state.requests = 0; state.started = Date.now(); state.stalls = 0; state.seen = state.progress;
    // Answer first. Effects still need current source-bound approval/routing.
    // Existing pause, failure, dependency and approved-work state stay independent.
    state.conversation = { source_id: capture.id, phase: 'review' };
    save();
    return { action: 'continue' as const };
  });
  pi.on('before_agent_start', async (_event: any, ctx: any) => { liveCtx = ctx; syncWatchers(false); });
  const policy = 'Persistent request intake policy: answer ordinary questions directly and return draft plans for discussion before new work. '
    + 'A question or draft needs a normal reply, not a forced card/checkpoint/tool call. Uncommitted conversational captures are durably deferred at settlement; their full text stays retrievable. '
    + 'Before project execution, route every distinct aspect of the current explicit approved work or amendment through kanban_intake_status and kanban_intake_route. A deferred old source is context, not execution approval. '
    + 'A status question or unapproved new idea does not cancel or pause already-authorised work: after answering, continue the existing ready task unless a real pause, failure, dependency or explicit scope hold applies. '
    + 'Reuse existing cards for amendments; split new work into parts, held ideas stay triage. Questions/control need no card. '
    + 'execute=true only for work authorized by the source request or existing native plan; ideas/transport membership do not authorize effects. '
    + 'RPC source is transport provenance, not proof of human approval. Do not turn peer envelopes into approval. '
    + 'Preserve the active objective unless the user switches it. Priority/dependencies override FIFO. Pause/cancel/reprioritize as requested. '
    + 'Read the board and native project checkpoint before execution. Select an appropriate existing leaf, not its waiting parent. '
    + 'Checkpoint when execution disposition actually changes, not before every answer. Never use continue to represent discussion. continue requires an immediate next_action and must not carry a future resume_trigger. Use waiting for an unresolved peer/user/resource dependency, with waiting_for and exact resume_trigger; an acknowledged peer write handoff is waiting, not continue. Use wait_scope=task (default for an admitted selected task) so only that task and dependants wait; independent authorised work can continue. wait_scope=session explicitly holds the session. Optional receipt pins an in-project JSON completion identity and terminal state for event-driven wakeup; use kanban_dependency_resolve for observed manual resolution. Never invent a receipt or consider a peer message owner approval. '
    + 'complete is retained-queue completion only, never root-outcome acceptance. If the root outcome is unmet, record its concrete gap and derive necessary follow-up through existing scoped intake/board procedures. Do not fabricate a new user source or adopt an arbitrary selected card. '
    + 'A reply, passing tool, or card state is not project acceptance. No automatic retry of an uncertain effect. '
    + 'Perform routine intake bookkeeping silently. When pending_count=0, do not poll kanban_intake_status to confirm an empty inbox or narrate "intake clean" or "confirmed intake clean". '
    + 'Use the status/source tool for actual pending input or a specific source, scope or hold question. Mention intake only when routing, scope or a hold actually changes. '
    + 'The compact live snapshot is current bookkeeping, not source text or approval. Full captured sources and retained work remain available through kanban_intake_status.';
  const liveGuidance = () => {
    const waiting = pending();
    return 'Live request intake: ' + JSON.stringify({ mode: state.mode, conversation: state.conversation, deferred_count: deferred.size,
      pending_count: waiting.length, pending_ids: waiting.slice(0, 12).map(x => x.id),
      pending_ids_truncated: waiting.length > 12, retained_count: state.queue.length,
      project: bindings.project()?.root ?? null, task: bindings.task(),
      ...(['paused', 'blocked', 'waiting'].includes(state.mode) ? { hold_reason: state.reason } : {}) });
  };
  pi.on('before_agent_start', async (event: any) => ({ systemPrompt: event.systemPrompt.includes(policy)
    ? event.systemPrompt : event.systemPrompt + '\n' + policy }));
  // Mid-turn steering still reaches EVERY provider request. Policy stays in the system prompt.
  pi.on('context', async (event: any) => ({ messages: [...event.messages, { role: 'custom',
    customType: 'pi-request-context/v1', content: liveGuidance() + readLoop.warning(), display: false, timestamp: Date.now() }] }));
  pi.registerTool({ name: 'kanban_intake_status', label: 'Read pending requests',
    description: 'Read durable pending/deferred source messages and retained authorized work. Optional source_id returns the full captured source, disposition and any frozen routing intent for exact retry recovery. Deferred conversation is context, not approval.',
    parameters: Type.Object({ source_id: Type.Optional(Type.String()) }, { additionalProperties: false }),
    async execute(_id, params) { const source = params.source_id ? captures.get(params.source_id) : undefined;
      return params.source_id && !source ? failed('Unknown source') : result({ ...status(), ...(source ? { source, disposition: routed.has(source.id) ? 'routed' : deferred.has(source.id) ? 'deferred' : 'pending', ...(intents.has(source.id) ? { frozen_intent: structuredClone(intents.get(source.id)) } : {}) } : {}) }); },
  });
  pi.registerTool({ name: 'kanban_intake_reconcile', label: 'Recover earlier session requests',
    description: 'On owner-authorized backlog review, capture earlier USER message entries on this branch from an explicit first_entry_id, up to 30 at a time. Preserves originals and uses stable entry IDs. Historical origin is unverified: imports are triage/held only, not execution authority. Inspect each source and reconcile existing cards; report remaining entries.',
    parameters: Type.Object({ first_entry_id: Type.String({ minLength: 1 }), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 30 })) }, { additionalProperties: false }),
    async execute(_id, params, _signal, _update, ctx) {
      const branch = ctx.sessionManager.getBranch();
      const start = branch.findIndex(x => x.id === params.first_entry_id);
      if (start < 0) return failed('First entry is not on the current session branch');
      // Modern inputs are already captured. Do not import them a second time under history IDs.
      const firstCapture = branch.findIndex((x: any) => x.type === 'custom' && x.customType === CAPTURE && x.data.source !== 'historical-unverified');
      const messages = branch.slice(start, firstCapture < 0 ? branch.length : firstCapture).filter((x: any) => x.type === 'message' && x.message.role === 'user');
      const imported = [];
      for (const entry of messages) {
        const id = 'history-' + digest([ctx.sessionManager.getSessionId(), entry.id]);
        if (captures.has(id)) continue;
        if (imported.length >= (params.limit ?? 30)) break;
        const message = (entry as any).message;
        const text = typeof message.content === 'string' ? message.content : message.content.filter((x: any) => x.type === 'text').map((x: any) => x.text).join('\n');
        const capture: Capture = { id, session: ctx.sessionManager.getSessionId(), text, source: 'historical-unverified',
          at: Date.parse(entry.timestamp), project: structuredClone(bindings.project()), sha256: digest(text),
          images: Array.isArray(message.content) ? message.content.filter((x: any) => x.type === 'image').length : 0 };
        pi.appendEntry(CAPTURE, capture); captures.set(id, capture); captureOrder.set(id, ++captureOrdinal); imported.push({ id, entry_id: entry.id });
      }
      const remaining = messages.filter(x => !captures.has('history-' + digest([ctx.sessionManager.getSessionId(), x.id]))).length;
      return result({ imported, remaining, authority: 'Historical recovery only; no execution approval' });
    },
  });
  const route = async (params: any, signal?: AbortSignal) => {
    const capture = captures.get(params.source_id);
    if (!capture) throw new Error('Unknown captured source');
    if (deferred.has(capture.id) && (params.parts.some((p: Part) => ['task', 'amend', 'held'].includes(p.kind))
        || (params.cancel_task_ids?.length ?? 0) > 0 || ![undefined, 'preserve'].includes(params.control)))
      throw new Error('Deferred conversation is context, not approval. Bind work or controls to the current explicit owner source.');
    const current = bindings.project();
    const cancellations: string[] = [...new Set<string>(params.cancel_task_ids ?? [])];
    const needsBoard = cancellations.length > 0 || params.parts.some((p: Part) => ['task', 'amend', 'held'].includes(p.kind));
    if (needsBoard && (!current || bindings.failed())) throw new Error('Admit and validate the destination project first');
    if (needsBoard && capture.project && capture.project.root !== current!.root)
      throw new Error('Source belongs to another project. Return to its project before routing; record a cross-project handoff there.');
    const intent = { project: current ?? capture.project, parts: params.parts, control: params.control ?? 'preserve', cancel_task_ids: cancellations };
    const previous = intents.get(capture.id);
    if (previous && digest(previous) !== digest(intent)) throw new Error('Routing intent already persisted. Resume identical parts after uncertain effects; amend cards separately.');
    if (routed.has(capture.id)) return result({ replay: true, source_id: capture.id });
    const recovered = new Map<number, string>();
    for (const item of params.recover_existing ?? []) {
      const index = item.part_index, part = params.parts[index];
      if (!Number.isInteger(index) || index < 0 || !part || !['task', 'held'].includes(part.kind)
          || recovered.has(index) || [...recovered.values()].includes(item.task_id))
        throw new Error('Recovery requires unique existing cards for task/held part indices');
      if (!current || bindings.failed()) throw new Error('Admit the recovery destination project first');
      const shown = await projectCall(current, { action: 'show', task_id: item.task_id }, signal);
      const body = shown.task.body ?? '';
      if (!body.includes(capture.id) || !body.includes(capture.sha256))
        throw new Error('Existing recovery card must cite this captured source ID and SHA256');
      if (part.kind === 'held' && shown.task.status !== 'triage')
        throw new Error('Held recovery card must remain triage');
      recovered.set(index, item.task_id);
    }
    for (const id of cancellations) {
      if (!state.queue.some(x => x.root === current?.root && x.task === id)) throw new Error('Cancellation can only affect this session\'s retained work');
      await projectCall(current!, { action: 'show', task_id: id }, signal);
    }
    // Validate the whole plan before freezing it or writing any card.
    for (const part of params.parts as Part[]) {
      if (['task', 'held'].includes(part.kind) && !boardTitle(part.summary)) throw new Error('Task summary must contain readable text');
      if (capture.source === 'historical-unverified' && part.execute) throw new Error('Historical import cannot grant execution authority. Route as held/amend-only; bind any authorized execution to a fresh owner request.');
      if (part.execute && !['task', 'amend'].includes(part.kind)) throw new Error('Only tasks/amendments can be executable');
      if (['task', 'held', 'question', 'control'].includes(part.kind) && part.task_id) throw new Error('Use amend for an existing card');
      if (part.kind === 'amend') {
        if (!part.task_id) throw new Error('Amendment requires an existing task_id');
        await projectCall(current!, { action: 'show', task_id: part.task_id }, signal);
      }
    }
    // Validation above can await read-only board calls. A superseded conversation
    // must not freeze a new routing intent or write a card after that boundary.
    if (deferred.has(capture.id)) throw new Error('Conversation was deferred during validation; bind work to the current owner source.');
    // Freeze plan BEFORE board effects. Stable per-source/part keys recover a lost reply without duplicate cards.
    if (!previous) { pi.appendEntry(INTENT, { id: capture.id, intent }); intents.set(capture.id, intent as any); }
    const work: Work[] = [];
    const bound: any[] = [];
    for (const [index, part] of (params.parts as Part[]).entries()) {
      if (part.execute && !['task', 'amend'].includes(part.kind)) throw new Error('Only tasks/amendments can be executable');
      let card = part.task_id;
      const marker = `Pi request ${capture.session}/${capture.id}/${index}`;
      if (part.kind === 'task' || part.kind === 'held') {
        if (card) throw new Error('Use amend for an existing card');
        if (recovered.has(index)) {
          card = recovered.get(index);
          const shown = await projectCall(current!, { action: 'show', task_id: card }, signal);
          const comment = `${marker}\nSource SHA256: ${capture.sha256}\nRecovered existing card for frozen ${part.kind} part; summary SHA256: ${digest(part.summary)}`;
          if (!shown.comments.some((x: any) => x.body === comment))
            await projectCall(current!, { action: 'comment', task_id: card, comment }, signal);
        } else {
        const created = await projectCall(current!, { action: 'create', title: boardTitle(part.summary),
          body: `${marker}\nSource SHA256: ${capture.sha256}\nDisposition: ${part.kind}\n${part.summary}`.trimEnd(),
          priority: part.priority ?? 0, initial_status: part.execute && !part.expandable ? 'ready' : 'triage',
          idempotency_key: `intake:${digest([capture.session, capture.id, index])}`, session_id: capture.session }, signal);
        card = created.task.id;
        }
      } else if (part.kind === 'amend') {
        if (!card) throw new Error('Amendment requires an existing task_id');
        const shown = await projectCall(current!, { action: 'show', task_id: card }, signal);
        const comment = `${marker}\nSource SHA256: ${capture.sha256}\nAmendment: ${part.summary}`.trimEnd();
        // Native loader serializes route operations below; exact marker readback recovers an uncertain comment write.
        if (!shown.comments.some((x: any) => x.body === comment))
          await projectCall(current!, { action: 'comment', task_id: card, comment }, signal);
      } else if (card) throw new Error('Question/control must not bind a fake task');
      if (card && part.execute) work.push({ root: current!.root, task: card, source: capture.id });
      bound.push({ kind: part.kind, summary: part.summary, task_id: card ?? null });
    }
    for (const id of cancellations) {
      const shown = await projectCall(current!, { action: 'show', task_id: id }, signal);
      const comment = `Pi request ${capture.session}/${capture.id}: owner cancelled retained work. Source SHA256: ${capture.sha256}`;
      if (!shown.comments.some((x: any) => x.body === comment)) await projectCall(current!, { action: 'comment', task_id: id, comment }, signal);
      if (['ready', 'running'].includes(shown.task.status)) await projectCall(current!, { action: 'move', task_id: id, transition: 'block', reason: comment }, signal);
      // Preserve card, dependencies, workspace and evidence; never archive/delete on cancellation.
    }
    const routing = { id: capture.id, bound, work, control: intent.control, cancel_task_ids: cancellations };
    pi.appendEntry(ROUTED, routing); rememberRouting(routing); routed.add(capture.id);
    for (const item of work) if (!state.queue.some(x => x.root === item.root && x.task === item.task)) state.queue.push(item);
    state.queue = state.queue.filter(x => !cancellations.includes(x.task));
    if (intent.control === 'pause') { state.mode = 'paused'; state.reason = 'User pause/control: ' + params.parts.map((x: Part) => x.summary).join('; '); }
    if (intent.control === 'resume') { state.mode = 'running'; state.reason = 'Explicit user resume'; delete state.wait; delete state.next_action; }
    if (work.length && !['paused', 'blocked', 'waiting'].includes(state.mode)) state.mode = 'running';
    if (state.conversation?.source_id === capture.id) {
      state.conversation.phase = work.length > 0 || intent.control === 'resume' ? 'execution' : 'discussion';
      if (intent.control === 'pause') state.conversation.phase = 'discussion';
    }
    // Question/control-only bookkeeping is not task progress.
    if (needsBoard) state.progress++;
    save();
    if (!bindings.task() && work[0]) bindings.select(work[0].task);
    return result({ source_id: capture.id, bound, state: status() });
  };
  pi.registerTool({ name: 'kanban_intake_route', label: 'Route captured requests',
    description: 'Account for EVERY distinct aspect of ONE captured input. Tasks/new ideas create idempotent cards, amendments comment on existing cards; questions/control remain in the source log. Preserve active task. Retry identical parts after uncertainty. recover_existing binds explicitly identified source-bound cards created manually during a failed route; it does not rewrite the frozen intent or authorize new work. execute is permission scope classification, never new approval. Pause/resume must follow explicit user instructions.',
    parameters: Type.Object({ source_id: Type.String(), control: Type.Optional(Type.Union(['preserve', 'pause', 'resume'].map(Type.Literal))),
      recover_existing: Type.Optional(Type.Array(Type.Object({ part_index: Type.Integer({ minimum: 0, maximum: 29 }), task_id: Type.String({ minLength: 1 }) }, { additionalProperties: false }), { maxItems: 30, description: 'Recover cards already created manually for this frozen source, without duplicate creation. Each card must cite this source ID and SHA256; held parts must remain triage. Original parts and authority remain unchanged.' })),
      cancel_task_ids: Type.Optional(Type.Array(Type.String(), { maxItems: 30, description: 'Only explicit owner cancellation. Stop retaining these session-owned cards; record cancellation and block runnable cards without deleting workspaces.' })),
      parts: Type.Array(Type.Object({ kind: Type.Union(['task', 'amend', 'held', 'question', 'control'].map(Type.Literal)),
        summary: Type.String({ minLength: 1, maxLength: 4000 }), task_id: Type.Optional(Type.String()),
        execute: Type.Optional(Type.Boolean()), priority: Type.Optional(Type.Integer({ minimum: -100, maximum: 100 })),
        expandable: Type.Optional(Type.Boolean({ description: 'For an authorized compound task, retain its execution scope but create it in triage so kanban_decompose can build the persistent recursive hierarchy. Select ready leaves before execution.' })) },
      { additionalProperties: false }), { minItems: 1, maxItems: 30 }) }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      const operation = serial.then(() => route(params, signal)); serial = operation.catch(() => undefined);
      try { return await operation; } catch (error) { return failed(error); }
    },
  });
  pi.registerTool({ name: 'kanban_work_checkpoint', label: 'Checkpoint retained work',
    description: 'Persist why work continues or stops. complete requires a full, source-bound terminal retained graph with known post-child integration; it means QUEUE completion only and never accepts the root outcome. Missing/truncated/cross-project scope refuses completion. blocked/paused/needs_user requires reason and resume trigger. waiting records a task hold by default for an admitted selected task; wait_scope=session holds all work. It requires waiting_for plus resume_trigger; receipt registers an exact event-driven completion condition. continue requires next_action ready now, forbids resume_trigger, and leaving waiting requires observed resolved_dependency. continue cannot clear a user pause; route explicit resume first.',
    parameters: Type.Object({ disposition: Type.Union(['continue', 'complete', 'blocked', 'paused', 'needs_user', 'waiting'].map(Type.Literal)),
      reason: Type.String({ minLength: 1, maxLength: 2000 }), resume_trigger: Type.Optional(Type.String({ minLength: 1, maxLength: 1000 })),
      next_action: Type.Optional(Type.String({ minLength: 1, maxLength: 1000, description: 'Concrete authorized step ready now; required for continue.' })),
      waiting_for: Type.Optional(Type.Union(['user', 'peer', 'resource', 'external'].map(Type.Literal))),
      resolved_dependency: Type.Optional(Type.String({ minLength: 1, maxLength: 1000, description: 'Observed resolution evidence required to leave a legacy session wait.' })),
      wait_scope: Type.Optional(Type.Union(['task', 'session'].map(Type.Literal))),
      dependency_key: Type.Optional(Type.String({minLength:1,maxLength:128})),
      receipt: Type.Optional(Type.Object({path:Type.String({minLength:1,maxLength:4096}),
        equals:Type.Record(Type.String(),Type.Union([Type.String({maxLength:1024}),Type.Number(),Type.Boolean()]))},{additionalProperties:false})) }, { additionalProperties: false }),
    async execute(_id, params, _signal, _update, ctx) {
      try {
        if (pending().length) throw new Error('Route pending input before a work checkpoint');
        if (state.mode === 'paused' && params.disposition !== 'paused') throw new Error('Explicit user resume required before changing a user pause');
        if (['blocked', 'paused', 'needs_user', 'waiting'].includes(params.disposition) && !params.resume_trigger) throw new Error('Specify the exact resume trigger');
        if (params.disposition === 'waiting' && !params.waiting_for) throw new Error('Specify waiting_for: user, peer, resource or external');
        if (params.disposition === 'continue' && params.resume_trigger) throw new Error('continue is ready work, not a future dependency. Use waiting with waiting_for and resume_trigger, or omit resume_trigger and supply next_action for work ready now.');
        if (params.disposition === 'continue' && !params.next_action) throw new Error('continue requires a concrete next_action ready now. For an unresolved dependency use waiting.');
        if (state.mode === 'waiting' && state.wait && ['continue', 'complete'].includes(params.disposition) && !params.resolved_dependency) throw new Error('Record observed resolved_dependency evidence before leaving waiting; another final reply or timer does not resolve it.');
        if (params.disposition === 'waiting' && params.wait_scope !== 'session' && bindings.project() && bindings.task()) {
          const before = stamp(), packet = await projectPacket(ctx);
          if (!alive || stamp() !== before) throw new Error('Wait registration became stale');
          const task = packet.tasks.find((t: any) => t.id === bindings.task());
          if (!task || !packet.coverage.complete || packet.coverage.truncated || packet.coverage.missing.length)
            throw new Error('Task wait needs complete retained source-bound scope');
          if (packet.excluded.some((x: any) => x.task === task.id && x.source === task.source)) throw new Error('Cannot wait on cancelled scope');
          const root = bindings.project()!.root;
          const receipt = params.receipt ? checkedReceipt(root, params.receipt) : undefined;
          const key = params.dependency_key ?? params.waiting_for!;
          const active = (state.task_waits ??= []).filter(w => w.status === 'waiting');
          const existing = active.find(w => w.root === root && w.task === task.id && w.source === task.source && w.key === key);
          if (existing) {
            if (existing.trigger !== params.resume_trigger || JSON.stringify(existing.receipt) !== JSON.stringify(receipt))
              throw new Error('Resolve the existing dependency ticket before changing its identity/condition');
            return result({ ...status(), wait_id: existing.id });
          }
          if (active.length >= 32) throw new Error('Too many active task dependency tickets');
          state.task_waits = [...active, ...(state.task_waits ?? []).filter(w => w.status === 'resolved').slice(-32)];
          const wait: TaskWait = { id: randomUUID(), root, task: task.id, source: task.source,
            key, kind: params.waiting_for!, reason: params.reason, trigger: params.resume_trigger!, status: 'waiting', ...(receipt ? {receipt} : {}) };
          state.task_waits.push(wait);
          state.reason = 'Task ' + task.id + ' waits: ' + params.reason + '; resume: ' + params.resume_trigger;
          journalDependency(wait, { status: 'waiting', trigger: wait.trigger }); save(); syncWatchers(true);
          return result({ ...status(), wait_id: wait.id });
        }
        if (params.disposition === 'waiting' && params.wait_scope === 'task') throw new Error('Select an admitted retained task before task-scoped waiting');
        if (params.receipt && (params.disposition !== 'waiting' || !bindings.task() || params.wait_scope === 'session')) throw new Error('Automatic receipt waits must be task-scoped');
        if (params.disposition === 'complete') {
          const { decision, packet } = await decide(ctx);
          if (decision.decision !== 'queue_complete') {
            if (state.mode === 'complete') { state.mode = 'running'; state.reason = decision.reason; save(); }
            throw new Error('Retained graph is not complete: ' + decision.reason);
          }
          recordDecision(decision, packet);
        }
        state.mode = params.disposition === 'continue' ? 'running' : params.disposition === 'needs_user' ? 'blocked' : params.disposition;
        state.wait = params.disposition === 'waiting' ? { kind: params.waiting_for!, trigger: params.resume_trigger! } : undefined;
        state.next_action = params.disposition === 'continue' ? params.next_action : undefined;
        state.reason = params.reason + (params.resume_trigger ? '; resume: ' + params.resume_trigger : ''); save();
        return result(status());
      } catch (error) { return failed(error); }
    },
  });
  pi.registerTool({ name: 'kanban_dependency_resolve', label: 'Resolve a registered task dependency',
    description: 'Record observed evidence for the exact task wait. Registered receipts must actually match. Resolving a dependency never grants permission, clears a user pause or accepts the root outcome.',
    parameters: Type.Object({wait_id:Type.String({minLength:1,maxLength:128}),evidence:Type.String({minLength:1,maxLength:1000})},{additionalProperties:false}),
    async execute(_id, params, _signal, _update, ctx) {
      try {
        const wait = state.task_waits?.find(w => w.id === params.wait_id);
        if (!wait || wait.root !== bindings.project()?.root) throw new Error('Unknown wait in the current project');
        if (wait.status === 'resolved') return result({wait_id:wait.id,status:wait.status});
        if (wait.receipt) {
          const observed = inspectReceipt(wait.root, wait.receipt);
          if (!observed.verified) throw new Error(observed.reason);
          wait.evidence = params.evidence + '; receipt_sha256=' + observed.sha256;
        } else wait.evidence = params.evidence;
        wait.status = 'resolved'; journalDependency(wait,{status:'resolved',evidence:wait.evidence});save();syncWatchers(false);
        return result({wait_id:wait.id,status:wait.status,mode:state.mode});
      } catch(error) { return failed(error); }
    }
  });
  pi.on('tool_call', async (event: any, ctx: any) => {
    if (event.toolName === 'web_research' && ['search', 'fetch', 'render'].includes(event.input?.action)) {
      if (researchCalls.size < 32 && alive && !ctx.signal?.aborted)
        researchCalls.set(event.toolCallId, { scope: researchScope(ctx) });
      return; // Pure inspection never acquires execution authority from accounting.
    }
    if (!EXECUTION.has(event.toolName) && event.toolName !== 'bash') return;
    const unresolved = unresolvedChildCalls(ctx.sessionManager.getBranch(), bindings.project()?.root);
    const activeChild = bindings.child?.();
    if (unresolved.some(id => id !== activeChild || event.parentToolCallId !== activeChild))
      return { block: true, reason: 'An active or unsettled managed child owns this scope. Inspect retained evidence; only its own native nested tools may run. After parent loss, route a fresh explicit owner resume before another attempt.' };
    if (pending().length) return { block: true, reason: 'New user input is not routed. Read kanban_intake_status and route every aspect before project execution.' };
    if (state.mode === 'paused' || state.mode === 'blocked' || (state.mode === 'waiting' && state.wait)) return { block: true, reason: `Work ${state.mode}: ${state.reason}. Route an explicit resume or record resolved dependency first.` };
    const before = stamp();
    if ((state.task_waits ?? []).some(w => w.status === 'waiting') && bindings.task()) {
      try {
        const packet = await projectPacket(ctx);
        if (blockedTaskIds(packet).has(bindings.task()!)) return {block:true,reason:'Selected task is held by a registered task dependency. Select independent authorised work or verify the exact dependency.'};
      } catch(error) { return {block:true,reason:'Cannot validate task dependency scope: '+String(error)}; }
    }
    if (bindings.project() && bindings.task()) {
      try {
        const cancelled = await cancelledSelection({ project: bindings.project()!, selected: bindings.task()!,
          queue: state.queue, authorized, order: authorizationOrder, excluded, call: bindings.call });
        if (cancelled) return { block: true, reason: 'Selected task belongs to cancelled retained scope ' + cancelled + '. Preserve its graph; bind fresh owner-authorised work before execution.' };
      } catch (error) { return { block: true, reason: 'Cannot validate cancelled scope: ' + String(error) }; }
    }
    if (EXECUTION.has(event.toolName) && !bindings.task()) return { block: true, reason: 'Select the project task before substantive execution. Read-only discovery remains available.' };
    if (EXECUTION.has(event.toolName) && bindings.task()) {
      const project = bindings.project();
      if (!project || bindings.failed()) return { block: true, reason: 'Validate project admission before execution' };
      try {
        const packet = await projectPacket(ctx);
        if (!alive || stamp() !== before)
          return { block: true, reason: 'Native input, selection or work changed during retained-source admission; inspect current intake before retrying.' };
        if (!packet.coverage.complete || packet.coverage.truncated || packet.coverage.missing.length)
          return { block: true, reason: 'Execution requires a complete retained source-bound task projection' };
        // A ready board card is not execution scope. Match the same-source
        // containment chain used by the decision helper, including explicit
        // descendant reauthorisation and cancelled-source exclusions.
        const selected = packet.tasks.find((task: any) => task.id === bindings.task());
        const seen = new Set<string>();
        let current = selected, admitted = false;
        for (let depth = 0; current && depth < 64; depth++) {
          if (seen.has(current.id) || current.project_root !== project.root
              || current.source !== selected.source
              || packet.excluded.some((item: any) => item.task === current.id && item.source === current.source)) break;
          seen.add(current.id);
          if (packet.anchors.some((item: any) => item.task === current.id && item.source === current.source)) {
            admitted = true; break;
          }
          current = packet.tasks.find((task: any) => task.id === current.parent);
        }
        if (!admitted)
          return { block: true, reason: 'Selected task is outside retained source-authorized scope. Route the actual request or select its admitted task; board readiness and selection grant no permission.' };
        const shown = await projectCall(project, { action: 'show', task_id: bindings.task() });
        if (!['ready', 'running'].includes(shown.task.status)) return { block: true, reason: 'Selected card is not runnable. Select an authorized ready leaf, not triage/blocked/review/terminal work.' };
        for (const id of shown.parents) {
          const parent = await projectCall(project, { action: 'show', task_id: id });
          if (!TERMINAL.has(parent.task.status)) return { block: true, reason: 'Selected card has an unfinished prerequisite: ' + id };
        }
      } catch (error) { return { block: true, reason: 'Cannot validate selected task: ' + String(error) }; }
    }
    if (!alive || stamp() !== before) return { block: true, reason: 'Native input, selection or work changed during execution admission; inspect current intake before retrying.' };
  });
  pi.on('tool_result', async (event: any) => {
    if (event.toolName === 'web_research') {
      const call = researchCalls.get(event.toolCallId);
      if (!call) return;
      if (event.isError || event.details?.ok !== true || event.details?.cached !== false) researchCalls.delete(event.toolCallId);
      else { call.candidate = true; call.content = digest([event.content, Boolean(event.isError)]); }
      return;
    }
    if (!EXECUTION.has(event.toolName) && event.toolName !== 'bash') return;
    if (event.isError || event.details?.ok === false) {
      state.mode = 'blocked'; state.reason = `Inspect failed/uncertain ${event.toolName} before retry; do not replay effects`; save();
    } else if (event.toolName !== 'task_agent') { state.progress++; save(); }
  });
  pi.on('turn_end', async (event: any, ctx: any) => {
    for (const result of event.toolResults ?? []) {
      const call = researchCalls.get(result.toolCallId);
      researchCalls.delete(result.toolCallId);
      if (!call?.candidate || ctx.signal?.aborted || !alive || call.scope !== researchScope(ctx)
          || pending().length || ['paused', 'blocked', 'waiting', 'complete'].includes(state.mode)) continue;
      const index = event.toolResults.findIndex((value: any) => value.toolCallId === result.toolCallId);
      const entry = ctx.sessionManager.getBranch().find((value: any) => value.id === event.toolResultEntryIds?.[index]);
      if (entry?.message?.role !== 'toolResult' || entry.message.toolName !== 'web_research'
          || entry.message.toolCallId !== result.toolCallId
          || digest([entry.message.content, Boolean(entry.message.isError)]) !== call.content) continue;
      try {
        const blocks = entry.message.content;
        if (!Array.isArray(blocks) || blocks.length !== 1 || blocks[0].type !== 'text'
            || typeof blocks[0].text !== 'string' || Buffer.byteLength(blocks[0].text) > 12 * 1024) continue;
        // Hidden details cannot prove delivery. Validate the actual committed
        // model-facing projection, including its source window, instead.
        const delivery = JSON.parse(blocks[0].text);
        const packet = await projectPacket(ctx);
        if (ctx.signal?.aborted || call.scope !== researchScope(ctx) || !packet.coverage.complete
            || packet.coverage.truncated || packet.coverage.missing.length) continue;
        const project = bindings.project(), task = bindings.task();
        const selected = packet.tasks.find((value: any) => value.id === task);
        if (!project || !selected || !['ready', 'running'].includes(selected.status)) continue;
        const seen = new Set<string>(); let current = selected, admitted = false;
        for (let depth = 0; current && depth < 64; depth++) {
          if (seen.has(current.id) || current.project_root !== project.root || current.source !== selected.source
              || packet.excluded.some((value: any) => value.task === current.id && value.source === current.source)) break;
          seen.add(current.id);
          if (packet.anchors.some((value: any) => value.task === current.id && value.source === current.source)) { admitted = true; break; }
          current = packet.tasks.find((value: any) => value.id === current.parent);
        }
        if (!admitted || blockedTaskIds(packet).has(task!)) continue;
        // Research is optional in standalone/minimal coordinator installs.
        // Resolve through the native extension loader only for real delivered
        // research, rather than adding a mandatory startup dependency.
        const { validateResearchProgress } = await import('../research/research-tools.ts');
        const verified = await validateResearchProgress(delivery, ctx);
        if (ctx.signal?.aborted || call.scope !== researchScope(ctx) || verified.ok !== true || verified.credit !== true
            || !/^[a-f0-9]{64}$/.test(verified.fingerprint ?? '')) continue;
        const session = ctx.sessionManager.getSessionId();
        const key = digest([session, project.root, project.projectId, project.boardId, verified.fingerprint]);
        if (researchCreditSeen(ctx.sessionManager.getBranch(), recentResearch, key)) continue;
        state.research_credit = { key, fingerprint: verified.fingerprint, session, root: project.root,
          task: task!, source: selected.source, artifact_id: verified.artifact_id,
          content_scope: verified.content_scope, coverage: verified.coverage };
        state.progress++; save(); rememberResearchCredit(recentResearch, key);
      } catch { /* Missing/stale/unproved evidence earns no credit or permission. */ }
    }
    // A bounded parallel batch cannot keep abandoned candidates forever.
    researchCalls.clear();
  });
  pi.on('agent_before_settle', async (event: any, ctx: any) => {
    // canContinue is a preview BEFORE our drafts. A final assistant message normally
    // makes it false; the custom_message below supplies the required next context.
    // Pi revalidates canContinue after committing drafts and still owns abort handling.
    if (event.outcome !== 'completed' || event.continue || event.context.pendingMessages?.length) return;
    const stop = (reason: string) => {
      // Intake diagnostics must not replace an explicit pause or an unresolved failure.
      if (state.mode !== 'paused' && state.mode !== 'blocked' && state.mode !== 'waiting') state.reason = reason;
      save(); ctx.ui?.notify?.(`Work stopped: ${state.reason}`, 'warning');
    };
    if (unresolvedChildCalls(ctx.sessionManager.getBranch(), bindings.project()?.root).length) {
      if (!['paused', 'waiting'].includes(state.mode)) {
        state.mode = 'blocked'; state.reason = 'Unsettled in-memory child; inspect retained evidence and route fresh owner resume. No automatic replay.';
      }
      save(); return;
    }
    if (state.conversation && state.conversation.phase !== 'execution') {
      const changed = deferUncommitted('settled_without_committed_execution');
      if (state.conversation.phase === 'review') { state.conversation.phase = 'discussion'; save(); }
      else if (changed) save();
      // Answer-only turns create no work. Existing approved tasks still use the
      // normal source-bound decision below; discussion itself is not progress.
      if (pending().length || !state.queue.length) return;
    }
    // Explicit holds keep their original reason. A wall-clock/count cap is not progress evidence.
    if (!pending().length && (state.mode === 'paused' || state.mode === 'blocked' || state.mode === 'waiting')) { save(); return; }
    if (state.progress === state.seen) state.stalls++; else state.stalls = 0;
    state.seen = state.progress;
    if (state.stalls >= 2) { stop('No progress across two settlement checks; inspect retained queue'); return; }
    let instruction: string | undefined;
    try {
      const { decision, packet } = await decide(ctx);
      recordDecision(decision, packet);
      if (decision.decision === 'route_pending') instruction = 'Route the pending user input before finishing. Do not execute it first. ' + liveGuidance();
      else if (decision.decision === 'continue') {
        if (state.mode === 'complete') state.mode = 'running';
        instruction = 'A reply is not the end of the authorized work. Continue the source-bound retained task '
        + decision.selected.task + ' (source ' + decision.selected.source + '; ' + decision.selected.action + '). '
        + 'Read its current board/requirements, preserve actual prerequisites and verify the user outcome. Queue state is not root acceptance. Do not replay uncertain effects.';
      }
      else if (decision.decision === 'hold') {
        if (state.mode === 'complete') state.mode = 'running';
        stop(decision.reason); return;
      }
      else { save(); return; } // A terminal retained graph does not accept the root outcome.
    } catch (error) {
      const reason = String(error);
      if (reason.includes('STALE_RETAINED_DECISION')) {
        ctx.ui?.notify?.('Retained work changed; discarded the old continuation decision.', 'warning'); return;
      }
      stop('Retained decision unavailable; inspect before continuing: ' + reason); return;
    }
    if (!instruction) { save(); return; }
    state.requests++; save();
    return { entries: [{ type: 'custom_message' as const, customType: 'pi-work-continuation/v1',
      content: instruction, display: true }], continue: true };
  });
  pi.registerCommand('work-pause', { description: 'Pause automatic work without removing queued tasks',
    handler: async (_args, ctx) => { state.mode = 'paused'; state.reason = 'User /work-pause; resume: /work-resume'; save(); ctx.ui.notify(state.reason, 'info'); } });
  pi.registerCommand('work-resume', { description: 'Allow retained work on the next user turn; does not start inference',
    handler: async (_args, ctx) => { state.mode = 'running'; state.reason = 'User /work-resume'; delete state.wait; delete state.next_action; state.requests = 0; state.started = Date.now(); state.stalls = 0; save(); ctx.ui.notify(state.reason, 'info'); } });
  pi.registerCommand('work-status', { description: 'Show retained work and pending intake without inference',
    handler: async (args, ctx) => {
      if (args.trim() !== 'evaluate') { ctx.ui.notify(JSON.stringify(status()), 'info'); return; }
      try {
        const { decision, packet } = await decide(ctx);
        recordDecision({ ...decision, diagnostic: true }, packet);
        ctx.ui.notify(JSON.stringify({ engine: 'agent-framework-core/1.21.0', diagnostic: true,
          ...decision, tasks: packet.tasks.length, anchors: packet.anchors.length }), 'info');
      } catch (error) { ctx.ui.notify('Retained evaluation unavailable: ' + String(error), 'warning'); }
    } });
  // Host-only capability. Delegated task prose is never inserted as fresh owner input.
  // Reuse the retained packet and current source scope; expose no grant tool/schema.
  return {
    async childGrant(ctx: any) {
      const scope = researchScope(ctx), session = ctx.sessionManager.getSessionId();
      const project = bindings.project(), task = bindings.task();
      if (unresolvedChildCalls(ctx.sessionManager.getBranch(), project?.root).length)
        throw new Error('Unsettled child evidence requires inspection and fresh owner resume');
      if (!alive || !project || !task || bindings.failed() || pending().length || state.mode !== 'running')
        throw new Error('Child requires unchanged admitted running source-bound work');
      const packet = await projectPacket(ctx);
      if (scope !== researchScope(ctx) || !packet.coverage.complete || packet.coverage.truncated || packet.coverage.missing.length)
        throw new Error('Child requires a complete unchanged retained projection');
      const selected = packet.tasks.find((item: any) => item.id === task);
      if (!selected?.parent || !['ready', 'running'].includes(selected.status) || blockedTaskIds(packet).has(task))
        throw new Error('Select an existing runnable authorized hierarchy child before delegation');
      const seen = new Set<string>(); let current = selected, admitted = false;
      for (let depth = 0; current && depth < 64; depth++) {
        if (seen.has(current.id) || current.project_root !== project.root || current.source !== selected.source
            || packet.excluded.some((item: any) => item.task === current.id && item.source === current.source)) break;
        seen.add(current.id);
        if (packet.anchors.some((item: any) => item.task === current.id && item.source === current.source)) { admitted = true; break; }
        current = packet.tasks.find((item: any) => item.id === current.parent);
      }
      const source = captures.get(selected.source);
      if (!admitted || !source || selected.prerequisites.some((id: string) => !TERMINAL.has(packet.prerequisite_status[id])))
        throw new Error('Child scope or prerequisites are not authorized');
      const bound = packetDigest(packet);
      return {
        identity: { project: structuredClone(project), card: task, parent_card: selected.parent,
          source: source.id, source_sha256: source.sha256, parent_session: session },
        async verify() {
          if (!alive || scope !== researchScope(ctx) || ctx.sessionManager.getSessionId() !== session)
            throw new Error('Child source, input, selection or work changed; delivery held');
          const actual = await projectPacket(ctx);
          if (scope !== researchScope(ctx) || packetDigest(actual) !== bound)
            throw new Error('Child board/source changed; delivery held; inspect retained child effects');
        },
      };
    },
  };

}
