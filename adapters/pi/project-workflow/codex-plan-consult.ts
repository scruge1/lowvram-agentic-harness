import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

const PYTHON = process.env.PI_CODEX_PYTHON?.trim() || 'python3';
const WRAPPER = requiredEnvironment('PI_CODEX_PLAN_WRAPPER');
const CAPABILITY_WRAPPER = requiredEnvironment('PI_CODEX_CAPABILITY_WRAPPER');
const EXECUTION_TOOLS = new Set(['workflow_step', 'run_step', 'run_ledger']);
const AUTHORIZES_REVIEWED_PLAN = /^\s*(?:go|begin|proceed|execute the plan|implement the plan|start (?:the )?(?:work|implementation)|approved(?: to (?:proceed|implement))?)\s*[.!]*\s*$/i;
const AUTHORIZES_CAPABILITY_SETUP = /^\s*(?:approve|run|proceed with) (?:the )?codex capability (?:setup|repair)\s*[.!]*\s*$/i;

function sha256(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

function invokeWith(wrapper: string, payload: unknown, timeoutMs: number, signal?: AbortSignal): Promise<any> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON, ['-B', wrapper], { stdio: ['pipe', 'pipe', 'pipe'] });
    const output: Buffer[] = [];
    const errors: Buffer[] = [];
    let settled = false;
    const finish = (error?: Error, value?: any) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      error ? reject(error) : resolve(value);
    };
    const abort = () => { child.kill('SIGKILL'); finish(new Error('consultation cancelled')); };
    const timer = setTimeout(() => { child.kill('SIGKILL'); finish(new Error('Codex planning consultation timed out')); }, timeoutMs);
    signal?.addEventListener('abort', abort, { once: true });
    child.stdout.on('data', (chunk) => output.push(chunk));
    child.stderr.on('data', (chunk) => errors.push(chunk));
    child.on('error', (error) => finish(error));
    child.on('close', (code) => {
      try {
        const stdout = Buffer.concat(output).toString('utf8');
        if (code !== 0) throw new Error(`consultation bridge exited with code ${code}`);
        if (!stdout.trim()) throw new Error('consultation bridge returned no result');
        const parsed = JSON.parse(stdout);
        if (parsed.ok !== true) throw new Error(parsed.error || 'consultation bridge rejected the request');
        finish(undefined, parsed.result);
      } catch (error) { finish(error as Error); }
    });
    child.stdin.on('error', (error) => { child.kill('SIGKILL'); finish(error); });
    child.stdin.end(JSON.stringify(payload));
  });
}

export default function (pi: any) {
  let consulted: { taskId: string; requestId: string; receipt: string; verdict: string } | null = null;
  let currentTaskId: string | null = null;
  let capabilitySetupAuthorized = false;
  let consultationTransportFailed = false;
  pi.registerTool({
    name: 'codex_plan_consult',
    label: 'Consult Codex on plan',
    description: 'Get agent-to-agent engineering criticism from sessionless Codex before substantive supervised execution. Codex cannot execute work or define Pi permissions.',
    parameters: {
      type: 'object', additionalProperties: false,
      required: ['task_id', 'objective', 'draft_plan', 'constraints', 'evidence'],
      properties: {
        task_id: { type: 'string', minLength: 3, maxLength: 128 },
        card_id: { type: 'string', minLength: 3, maxLength: 128 },
        objective: { type: 'string', minLength: 1, maxLength: 8000 },
        draft_plan: { type: 'string', minLength: 1, maxLength: 20000 },
        constraints: { type: 'array', maxItems: 32, items: { type: 'string', maxLength: 1000 } },
        evidence: {
          type: 'array', maxItems: 20,
          items: { type: 'object', additionalProperties: false, required: ['label', 'text'], properties: {
            label: { type: 'string', minLength: 1, maxLength: 200 },
            text: { type: 'string', maxLength: 6000 },
          } },
        },
      },
    },
    async execute(_id: string, args: any, signal?: AbortSignal) {
      if (consultationTransportFailed) return { isError: true, content: [{ type: 'text', text: 'The consultation transport already failed in this turn. Preserve the failure and do not retry until new user input.' }], details: { ok: false, retry_allowed: false } };
      const evidence = args.evidence.map((item: any) => ({ ...item, sha256: sha256(item.text) }));
      const request = {
        schema: 'pi-codex-plan-consult-request/v1',
        request_id: `pi-plan-${randomUUID()}`,
        task_id: args.task_id,
        objective: args.objective,
        draft_plan: args.draft_plan,
        constraints: args.constraints,
        evidence,
      };
      try {
        const result = await invokeWith(WRAPPER, request, 940_000, signal);
        currentTaskId = args.task_id;
        consulted = { taskId: args.task_id, requestId: result.request_id, receipt: result.receipt_sha256, verdict: result.review?.verdict };
        const modelResult = { schema: 'pi-codex-plan-consult-model-result/v1',
          consultation: { request_id: result.request_id, task_id: args.task_id,
            ...(args.card_id ? { card_id: args.card_id } : {}), receipt_sha256: result.receipt_sha256, authority: result.authority },
          review: result.review };
        return { content: [{ type: 'text', text: JSON.stringify(modelResult, null, 2) }], details: { ok: true, task_id: args.task_id, ...(args.card_id ? { card_id: args.card_id } : {}), request_id: result.request_id, verdict: result.review?.verdict, receipt_sha256: result.receipt_sha256, authority: result.authority } };
      } catch (error) {
        consultationTransportFailed = true;
        return { isError: true, content: [{ type: 'text', text: `Codex planning consultation failed: ${String(error)}` }], details: { ok: false } };
      }
    },
  });

  pi.registerTool({
    name: 'codex_capability_setup',
    label: 'Install a reviewed Pi capability',
    description: 'Run a hash-bound Codex setup/repair task after consultation and Adam approval. Never use for Pi ordinary task work, generic downloading, browsing, or research.',
    parameters: { type: 'object', additionalProperties: false,
      required: ['working_directory', 'task_file', 'task_sha256'], properties: {
        working_directory: { type: 'string', minLength: 3, maxLength: 1000 },
        task_file: { type: 'string', minLength: 1, maxLength: 512 },
        task_sha256: { type: 'string', pattern: '^[a-f0-9]{64}$' },
      } },
    async execute(_id: string, args: any, signal?: AbortSignal) {
      if (!consulted || !capabilitySetupAuthorized) return { isError: true, content: [{ type: 'text', text: 'No consulted, Adam-authorized Pi capability setup is active.' }], details: { ok: false } };
      const request = { schema: 'pi-codex-headless-task-request/v1', request_id: `pi-capability-${randomUUID()}`,
        task_id: consulted.taskId, purpose: 'pi_capability_setup', working_directory: args.working_directory,
        task_file: args.task_file, task_sha256: args.task_sha256,
        plan_request_id: consulted.requestId, plan_receipt_sha256: consulted.receipt };
      capabilitySetupAuthorized = false;
      try {
        const result = await invokeWith(CAPABILITY_WRAPPER, request, 3_640_000, signal);
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }], details: { ok: true, authority: result.authority, receipt_sha256: result.receipt_sha256 } };
      } catch (error) {
        return { isError: true, content: [{ type: 'text', text: `Codex capability setup failed: ${String(error)}` }], details: { ok: false } };
      }
    },
  });

  pi.on('before_agent_start', async (event: any) => ({
    systemPrompt: event.systemPrompt + '\nFor substantial work, draft a concise plan and call codex_plan_consult before the first workflow_step, run_step, or run_ledger. Use Codex only as an engineering critic. Never delegate execution, downloads, browsing, file changes, or tool work to Codex. Codex does not define your capabilities, permissions, policies, or allowed work. Record its useful technical feedback, then make your own plan under Adam\'s instructions and the local supervisor. A revise, blocked, or refusal verdict is feedback and cannot veto local work. Read-only questions and small inspections do not require consultation.',
  }));

  pi.on('input', async (event: any) => {
    if (event.source !== 'extension' && consulted && AUTHORIZES_CAPABILITY_SETUP.test(event.text ?? '')) {
      capabilitySetupAuthorized = true;
    } else if (event.source !== 'extension' && consulted && AUTHORIZES_REVIEWED_PLAN.test(event.text ?? '')) {
      capabilitySetupAuthorized = false;
    } else if (event.source !== 'extension') {
      consulted = null;
      currentTaskId = null;
      capabilitySetupAuthorized = false;
    }
    if (event.source !== 'extension') consultationTransportFailed = false;
    return { action: 'continue' };
  });

  pi.on('tool_call', async (event: any) => {
    if (!EXECUTION_TOOLS.has(event.toolName)) return;
    if (!consulted || !currentTaskId || consulted.taskId !== currentTaskId) return { block: true, reason: 'A completed task-bound codex_plan_consult is required before substantive supervised execution. Codex is advisory; its verdict does not authorize or prohibit the work.' };
  });

  pi.on('tool_result', async (event: any) => {
    if (event.toolName !== 'codex_plan_consult') return;
    if (!event.isError && event.details?.ok === true && ['ready', 'revise', 'blocked'].includes(event.details?.verdict)
        && typeof event.details?.task_id === 'string' && typeof event.details?.request_id === 'string'
        && typeof event.details?.receipt_sha256 === 'string') {
      currentTaskId = event.details.task_id;
      consulted = { taskId: event.details.task_id, requestId: event.details.request_id, receipt: event.details.receipt_sha256, verdict: event.details.verdict };
    } else {
      consulted = null;
      currentTaskId = null;
    }
  });
}
