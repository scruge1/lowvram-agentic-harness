import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

const PYTHON = requiredEnvironment('PI_PROJECT_KANBAN_PYTHON');
const ADAPTER = requiredEnvironment('PI_PROJECT_KANBAN_ADAPTER');
const ADAPTER_SHA256 = requiredEnvironment('PI_PROJECT_KANBAN_ADAPTER_SHA256');
const MAX_OUTPUT = 1024 * 1024;
const EXECUTION_TOOLS = new Set(['workflow_step', 'run_step', 'run_ledger']);

type Reply = { schema: string; ok: boolean; action?: string; result?: unknown; limits?: string[]; error?: string };

function callAdapter(request: Record<string, unknown>, signal?: AbortSignal): Promise<Reply> {
  return new Promise((resolve, reject) => {
    let adapterDigest: string;
    try { adapterDigest = createHash('sha256').update(readFileSync(ADAPTER)).digest('hex'); }
    catch { reject(new Error('kanban adapter is unavailable')); return; }
    if (adapterDigest !== ADAPTER_SHA256) { reject(new Error('kanban adapter byte drift')); return; }
    const child = spawn(PYTHON, ['-B', ADAPTER], { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = Buffer.alloc(0);
    let stderr = Buffer.alloc(0);
    let settled = false;
    const finish = (error?: Error, value?: Reply) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      if (error) reject(error); else resolve(value!);
    };
    const abort = () => { child.kill('SIGKILL'); finish(new Error('cancelled')); };
    const timer = setTimeout(() => { child.kill('SIGKILL'); finish(new Error('kanban adapter timeout')); }, 10000);
    signal?.addEventListener('abort', abort, { once: true });
    child.stdout.on('data', (chunk: Buffer) => {
      stdout = Buffer.concat([stdout, chunk]);
      if (stdout.length > MAX_OUTPUT) { child.kill('SIGKILL'); finish(new Error('kanban adapter output too large')); }
    });
    child.stderr.on('data', (chunk: Buffer) => {
      stderr = Buffer.concat([stderr, chunk]);
      if (stderr.length > 8192) { child.kill('SIGKILL'); finish(new Error('kanban adapter stderr too large')); }
    });
    child.on('error', (error) => finish(error));
    child.on('close', (code) => {
      if (settled) return;
      let value: Reply;
      try { value = JSON.parse(stdout.toString('utf8')); } catch { return finish(new Error(`invalid kanban adapter response (exit ${code})`)); }
      if (code !== 0 || value?.schema !== 'pi-kanban-result/v1' || value.ok !== true) return finish(new Error(value?.error || `kanban adapter failed (exit ${code})`));
      finish(undefined, value);
    });
    child.stdin.on('error', (error) => { child.kill('SIGKILL'); finish(error); });
    child.stdin.end(JSON.stringify(request));
  });
}

function response(value: Reply) {
  return { content: [{ type: 'text' as const, text: JSON.stringify(value) }], details: value };
}

function failure(error: unknown) {
  const message = error instanceof Error ? error.message : 'unknown kanban error';
  return { content: [{ type: 'text' as const, text: `Kanban operation failed: ${message}` }], details: { ok: false, error: message }, isError: true };
}

export default function (pi: ExtensionAPI) {
  const pendingConsultations = new Map<string, { taskId: string; cardId?: string; objective: string; draftPlan: string }>();
  let activeProject: { root: string; projectId: string; boardId: string } | null = null;
  let activeTask: { taskId: string; cardId: string } | null = null;
  let boardAdmissionFailed = false;
  let capabilitiesObserved = false;
  let knowledgeQueried = false;

  const projectRequest = (request: Record<string, unknown>) => {
    if (!activeProject) throw new Error('Admit a project with project_admit before using its board');
    return { ...request, project_root: activeProject.root };
  };

  pi.registerTool({
    name: 'project_admit', label: 'Admit project',
    description: 'Resolve or explicitly initialize one project identity and select its isolated host-local board for this Pi session. Initialization never overwrites an existing identity.',
    parameters: Type.Object({
      project_root: Type.String({ minLength: 1, maxLength: 4096 }),
      initialize: Type.Optional(Type.Boolean()),
      native_authority: Type.Optional(Type.String({ maxLength: 4096 })),
      target: Type.Optional(Type.String({ minLength: 1, maxLength: 1000 })),
      why: Type.Optional(Type.String({ minLength: 1, maxLength: 2000 })),
      system_setup: Type.Optional(Type.Boolean()),
    }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      try {
        const value = await callAdapter({ action: 'project_admit', ...params }, signal);
        const result = value.result as any;
        const projectId = result?.identity?.project_id;
        const boardId = result?.identity?.board_id;
        const root = result?.project_root;
        if (typeof root !== 'string' || typeof projectId !== 'string' || typeof boardId !== 'string') throw new Error('project admission returned an incomplete identity');
        activeProject = { root, projectId, boardId };
        activeTask = null;
        boardAdmissionFailed = false;
        capabilitiesObserved = false;
        knowledgeQueried = false;
        return response(value);
      } catch (error) {
        activeProject = null;
        activeTask = null;
        boardAdmissionFailed = true;
        capabilitiesObserved = false;
        knowledgeQueried = false;
        return failure(error);
      }
    },
  });

  pi.registerTool({
    name: 'project_knowledge_query', label: 'Query project knowledge',
    description: 'Search the admitted project knowledge index. Results cite source path, source hash, and line range and have retrieval-only authority.',
    parameters: Type.Object({
      terms: Type.String({ minLength: 1, maxLength: 1000 }),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
    }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'knowledge_query', ...params }), signal)); } catch (error) { return failure(error); } },
  });

  pi.registerTool({
    name: 'project_knowledge_rebuild', label: 'Rebuild project knowledge',
    description: 'Rebuild the admitted project retrieval index and hash-bound manifest from its readable source policy. This grants retrieval-only authority.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_id, _params, signal) { try { return response(await callAdapter(projectRequest({ action: 'knowledge_build' }), signal)); } catch (error) { return failure(error); } },
  });

  pi.registerTool({
    name: 'project_closeout_prepare', label: 'Prepare verified project closeout',
    description: 'Validate one accepted supervised receipt and its current output bytes, write one immutable project lesson record, rebuild project knowledge, and return a canonical guidance-only memory payload. This does not write durable memory or promote a skill.',
    parameters: Type.Object({
      task_id: Type.String({ minLength: 1, maxLength: 128 }),
      card_id: Type.String({ minLength: 1, maxLength: 128 }),
      receipt_path: Type.String({ minLength: 1, maxLength: 4096 }),
      receipt_sha256: Type.String({ minLength: 64, maxLength: 64 }),
      summary: Type.String({ minLength: 1, maxLength: 4000 }),
      lessons: Type.Array(Type.String({ minLength: 1, maxLength: 2000 }), { minItems: 1, maxItems: 20 }),
    }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'project_closeout_prepare', ...params }), signal)); } catch (error) { return failure(error); } },
  });

  pi.registerTool({
    name: 'project_skill_candidate_compile', label: 'Compile project skill candidate',
    description: 'Compile one immutable project-local skill candidate from a verified closeout. The result is guidance only. It is not installed, shared, or promoted.',
    parameters: Type.Object({
      name: Type.String({ minLength: 2, maxLength: 64, pattern: '^[a-z0-9][a-z0-9-]+$' }),
      description: Type.String({ minLength: 1, maxLength: 500 }),
      closeout_path: Type.String({ minLength: 1, maxLength: 4096 }),
      closeout_sha256: Type.String({ minLength: 64, maxLength: 64, pattern: '^[a-f0-9]{64}$' }),
      triggers: Type.Array(Type.String({ minLength: 1, maxLength: 300 }), { minItems: 1, maxItems: 12 }),
      steps: Type.Array(Type.String({ minLength: 1, maxLength: 1000 }), { minItems: 1, maxItems: 30 }),
      verification: Type.Array(Type.String({ minLength: 1, maxLength: 1000 }), { minItems: 1, maxItems: 20 }),
      stop_conditions: Type.Array(Type.String({ minLength: 1, maxLength: 1000 }), { minItems: 1, maxItems: 20 }),
    }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'project_skill_candidate_compile', ...params }), signal)); } catch (error) { return failure(error); } },
  });

  pi.registerTool({
    name: 'kanban_status', label: 'Kanban status',
    description: 'Read the live host-local Pi Kanban backend identity, runtime, journal mode, task counts, and authority limits.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_id, _params, signal) { try { return response(await callAdapter(projectRequest({ action: 'status' }), signal)); } catch (error) { return failure(error); } },
  });
  pi.registerTool({
    name: 'kanban_list', label: 'List Kanban work',
    description: 'List host-local Pi Kanban cards. This reads work state only and grants no evidence or SSOT authority.',
    parameters: Type.Object({ status: Type.Optional(Type.String()), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })) }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'list', ...params }), signal)); } catch (error) { return failure(error); } },
  });
  pi.registerTool({
    name: 'kanban_show', label: 'Show Kanban work',
    description: 'Show one Pi Kanban card with dependencies and comments.',
    parameters: Type.Object({ task_id: Type.String() }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'show', ...params }), signal)); } catch (error) { return failure(error); } },
  });
  pi.registerTool({
    name: 'kanban_create', label: 'Create Kanban work',
    description: 'Create or idempotently recover one bounded host-local work card. A card never grants execution, evidence, proof, promotion, or submission authority.',
    parameters: Type.Object({
      title: Type.String({ minLength: 1, maxLength: 200 }),
      body: Type.Optional(Type.String({ maxLength: 8000 })),
      priority: Type.Optional(Type.Integer({ minimum: -100, maximum: 100 })),
      parents: Type.Optional(Type.Array(Type.String(), { maxItems: 20 })),
      idempotency_key: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      initial_status: Type.Optional(Type.Union([Type.Literal('triage'), Type.Literal('ready')])),
    }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'create', ...params }), signal)); } catch (error) { return failure(error); } },
  });
  pi.registerTool({
    name: 'kanban_move', label: 'Move Kanban work',
    description: 'Apply one valid Hermes state transition to a Pi Kanban card. Completion is workflow state only and has no SSOT authority.',
    parameters: Type.Object({
      task_id: Type.String(),
      transition: Type.Union(['schedule', 'block', 'unblock', 'request_review', 'request_changes', 'reopen_review', 'complete', 'archive'].map(Type.Literal)),
      reason: Type.Optional(Type.String({ maxLength: 2000 })),
      summary: Type.Optional(Type.String({ maxLength: 4000 })),
    }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'move', ...params }), signal)); } catch (error) { return failure(error); } },
  });
  pi.registerTool({
    name: 'kanban_comment', label: 'Comment on Kanban work',
    description: 'Append one audit comment to a Pi Kanban card.',
    parameters: Type.Object({ task_id: Type.String(), comment: Type.String({ minLength: 1, maxLength: 8000 }) }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'comment', ...params }), signal)); } catch (error) { return failure(error); } },
  });

  pi.on('input', async (event: any) => {
    if (event.source !== 'extension') {
      activeTask = null;
      activeProject = null;
      boardAdmissionFailed = false;
      capabilitiesObserved = false;
      knowledgeQueried = false;
      pendingConsultations.clear();
    }
    return { action: 'continue' };
  });

  pi.on('tool_call', async (event: any) => {
    if (event.toolName === 'codex_plan_consult') {
      if (!activeProject) return { block: true, reason: 'Admit the project with project_admit before planning consultation.' };
      if (!capabilitiesObserved) return { block: true, reason: 'Call agent_capabilities before planning so the plan uses the tools actually loaded in this Pi session.' };
      if (!knowledgeQueried) return { block: true, reason: 'Query relevant project knowledge before planning so prior verified work is not rediscovered.' };
      const taskId = typeof event.input?.task_id === 'string' ? event.input.task_id : '';
      const cardId = typeof event.input?.card_id === 'string' ? event.input.card_id : undefined;
      const objective = typeof event.input?.objective === 'string' ? event.input.objective : '';
      const draftPlan = typeof event.input?.draft_plan === 'string' ? event.input.draft_plan : '';
      if (taskId && objective && draftPlan) pendingConsultations.set(event.toolCallId, { taskId, cardId, objective, draftPlan });
      return;
    }
    if (!EXECUTION_TOOLS.has(event.toolName)) return;
    if (boardAdmissionFailed) return { block: true, reason: 'Kanban admission failed for this task. Preserve the failure and repair board admission before supervised execution.' };
    if (!activeTask) return { block: true, reason: 'A session-bound Kanban card created from codex_plan_consult is required before supervised execution.' };
  });

  pi.on('tool_result', async (event: any, ctx: any) => {
    if (event.toolName === 'agent_capabilities' && !event.isError && event.details?.ok === true) {
      if (!activeProject) return;
      try {
        await callAdapter(projectRequest({
          action: 'capability_snapshot',
          snapshot: event.details.snapshot,
          session_id: ctx.sessionManager.getSessionId(),
        }));
        capabilitiesObserved = true;
      } catch {
        capabilitiesObserved = false;
        return { isError: true, content: [{ type: 'text', text: 'Capability discovery completed, but the project-bound snapshot could not be saved. Stop before planning.' }], details: { ok: false, capability_snapshot: 'failed' } };
      }
      return;
    }
    if (event.toolName === 'project_knowledge_query' && !event.isError && event.details?.ok === true) {
      knowledgeQueried = true;
      return;
    }
    if (event.toolName === 'codex_plan_consult') {
      const pending = pendingConsultations.get(event.toolCallId);
      pendingConsultations.delete(event.toolCallId);
      if (!pending || event.isError || event.details?.ok !== true || event.details?.task_id !== pending.taskId) {
        activeTask = null;
        return;
      }
      try {
        const requestId = String(event.details.request_id || '');
        const card = await callAdapter(projectRequest({
          action: 'consultation_admit',
          task_id: pending.taskId,
          ...(pending.cardId ? { card_id: pending.cardId } : {}),
          request_id: requestId,
          objective: pending.objective.slice(0, 200),
          draft_plan: pending.draftPlan.slice(0, 6000),
          session_id: ctx.sessionManager.getSessionId(),
        }));
        const cardId = (card.result as any)?.task?.id;
        if (typeof cardId !== 'string' || !cardId) throw new Error('Kanban admission returned no task ID');
        activeTask = { taskId: pending.taskId, cardId };
        boardAdmissionFailed = false;
      } catch {
        activeTask = null;
        boardAdmissionFailed = true;
        return { isError: true, content: [{ type: 'text', text: 'Planning consultation completed, but mandatory Kanban admission failed. Stop before supervised execution.' }], details: { ok: false, kanban_admission: 'failed' } };
      }
      return;
    }
    if (!EXECUTION_TOOLS.has(event.toolName) || !activeTask) return;
    const outcome = event.isError || event.details?.ok === false ? 'failed' : 'completed';
    try {
      await callAdapter(projectRequest({ action: 'comment', task_id: activeTask.cardId, comment: `${event.toolName} ${outcome}; native tool call ${event.toolCallId}.` }));
      if (outcome === 'completed') await callAdapter(projectRequest({ action: 'knowledge_build' }));
    } catch {
      boardAdmissionFailed = true;
      return { isError: true, content: [{ type: 'text', text: 'Supervised tool returned, but mandatory project audit or knowledge refresh failed. Preserve the original result and stop.' }], details: { ok: false, project_closeout: 'failed' } };
    }
  });
}
