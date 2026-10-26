/** Public research evidence is data, never project or execution authority. */
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

const MAX_OUTPUT = 12 * 1024;
const LOCAL_ACTIONS = new Set(['plan', 'retrieval_plan', 'consensus']);
const sha = (value: Buffer) => createHash('sha256').update(value).digest('hex');
const stable = (value: any): any => Array.isArray(value) ? value.map(stable)
  : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
const hashObject = (value: any) => sha(Buffer.from(JSON.stringify(stable(value))));

function selected(ctx: any) {
  const entry = [...ctx.sessionManager.getBranch()].reverse().find(
    (item: any) => item.type === 'custom' && item.customType === 'pi-kanban-selection/v1');
  const value = entry?.data;
  if (!value?.project || value.boardAdmissionFailed === true)
    throw new Error('Admit the current project before research.');
  for (const field of ['root', 'projectId', 'boardId'])
    if (typeof value.project[field] !== 'string' || !value.project[field])
      throw new Error('Native project selection is incomplete.');
  return JSON.parse(JSON.stringify({ project: value.project, task: value.task ?? null,
    boardAdmissionFailed: false }));
}

function binding() {
  const home = process.env.AGENT_HOME;
  const python = process.env.PI_WEB_RESEARCH_PYTHON;
  const helper = process.env.PI_WEB_RESEARCH_HELPER;
  const expected = process.env.PI_WEB_RESEARCH_HELPER_SHA256;
  if (!home || !python || !helper || !/^[a-f0-9]{64}$/.test(expected ?? '')
      || ![home, python, helper].every(value => path.isAbsolute(value)))
    throw new Error('The home-owned research runtime is not configured.');
  const exact = path.join(home, 'runtime', 'harness', 'research_runtime.py');
  if (path.resolve(helper) !== exact || fs.lstatSync(helper).isSymbolicLink()
      || fs.realpathSync(helper) !== exact || sha(fs.readFileSync(helper)) !== expected)
    throw new Error('Research helper source binding changed.');
  const direct = [python, '-I', '-B', helper, '--home', home];
  const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json'), 'utf8'));
  const raw = process.env.PI_WEB_RESEARCH_COMMAND;
  const commandHash = process.env.PI_WEB_RESEARCH_COMMAND_SHA256;
  if (Object.hasOwn(config, 'lifecycle_guard_sha256') && (!raw || !commandHash))
    throw new Error('This home requires the bound research lifecycle command.');
  let command = direct;
  if (raw || commandHash) {
    if (!raw || Buffer.byteLength(raw) > 65536 || !/^[a-f0-9]{64}$/.test(commandHash ?? '')
        || sha(Buffer.from(raw)) !== commandHash) throw new Error('Research lifecycle command binding changed.');
    command = JSON.parse(raw);
    if (!Array.isArray(command) || !command.length
        || !command.every(item => typeof item === 'string' && !item.includes('\0'))
        || command[0] !== python || JSON.stringify(command.slice(-direct.length)) !== JSON.stringify(direct))
      throw new Error('Research lifecycle command target differs.');
  }
  return { home, python, helper, command };
}

function invoke(runtime: ReturnType<typeof binding>, request: object, timeout: number,
                signal?: AbortSignal, internal = false): Promise<any> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new Error('Research cancelled before execution.')); return; }
    const child = spawn(runtime.command[0], runtime.command.slice(1), {
      cwd: runtime.home, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    });
    let output = Buffer.alloc(0), errors = Buffer.alloc(0), stopped = '', stoppedStatus = 'runtime_error', finished = false;
    let killTimer: ReturnType<typeof setTimeout> | undefined;
    const stop = (reason: string, status = 'runtime_error') => {
      if (stopped) return;
      stopped = reason;
      stoppedStatus = status;
      // Let the native browser guard settle its owned descendants before close.
      child.kill('SIGTERM');
      killTimer = setTimeout(() => child.kill('SIGKILL'), 8000);
    };
    const abort = () => stop('Research cancelled; delivery held; inspect retained bound artifacts.', 'cancelled');
    const timer = setTimeout(() => stop('Research helper productive deadline reached; delivery held; inspect retained bound artifacts.', 'deadline'), timeout);
    signal?.addEventListener('abort', abort, { once: true });
    const finish = (error?: Error, value?: any) => {
      if (finished) return;
      finished = true; clearTimeout(timer); clearTimeout(killTimer);
      signal?.removeEventListener('abort', abort);
      error ? reject(error) : resolve(value);
    };
    child.on('error', error => finish(error));
    child.stdout.on('data', chunk => {
      if (output.length + chunk.length > (internal ? 512 * 1024 : MAX_OUTPUT) + 2) stop('Research output exceeded its byte limit.');
      else output = Buffer.concat([output, chunk]);
    });
    child.stderr.on('data', chunk => {
      if (errors.length + chunk.length > 8192) stop('Research diagnostic exceeded its byte limit.');
      else errors = Buffer.concat([errors, chunk]);
    });
    child.stdin.on('error', () => stop('Research input channel failed.'));
    child.on('close', code => {
      if (stopped) { finish(Object.assign(new Error(stopped), { researchStatus: stoppedStatus })); return; }
      try {
        if (code !== 0 && !output.length) {
          const refusal = JSON.parse(errors.toString('utf8'));
          if (['agent-home-entry/v1', 'agent-home-lifecycle/v1'].includes(refusal?.schema)
              && typeof refusal.error === 'string') throw new Error('Research lifecycle refused: ' + refusal.error);
        }
        const value = JSON.parse(output.toString('utf8'));
        if (![...(internal ? ['research-mine-plan/v1'] : []), 'research-result/v1'].includes(value?.schema) || typeof value.ok !== 'boolean'
            || value.authority !== 'untrusted_source_evidence'
            || Buffer.byteLength(JSON.stringify(value)) > (internal ? 512 * 1024 : MAX_OUTPUT))
          throw new Error('Invalid bounded research response.');
        if (code !== 0 && value.ok) throw new Error('Research helper exited unsuccessfully.');
        finish(undefined, value);
      } catch (error) { finish(new Error('Research helper failed: ' + String(error).slice(0, 700))); }
    });
    child.stdin.end(JSON.stringify(request));
  });
}

/** Host-only readback for intake accounting; never a model tool action. */
export async function validateResearchProgress(delivery: any, ctx: any) {
  return invoke(binding(), { action: '_progress_validate', delivery, selection: selected(ctx),
    session_id: ctx.sessionManager.getSessionId() }, 30000, ctx.signal, true);
}

function miningModel(ctx: any, runtime: ReturnType<typeof binding>) {
  const model = ctx.model;
  const file = path.join(runtime.home, 'agent', 'models.json');
  if (fs.lstatSync(file).isSymbolicLink() || fs.realpathSync(file) !== file)
    throw new Error('Configured model source is redirected.');
  const config = JSON.parse(fs.readFileSync(path.join(runtime.home, 'home.json'), 'utf8'));
  if (!model || model.provider !== 'local' || model.api !== 'openai-completions'
      || model.id !== config.model || model.baseUrl !== config.base_url
      || !Number.isInteger(model.contextWindow) || !Number.isInteger(model.maxTokens) || model.maxTokens < 1)
    throw new Error('Mining requires this home’s actual selected local model; virtual or foreign routes are unsupported.');
  return { provider: model.provider, id: model.id, api: model.api, base_url: model.baseUrl,
    context_window: model.contextWindow, max_tokens: model.maxTokens, reasoning: model.reasoning === true,
    compat_sha256: hashObject(model.compat ?? {}), models_sha256: sha(fs.readFileSync(file)),
    headers_sha256: hashObject(model.headers ?? {}),
    output_tokens: Math.min(1000, model.maxTokens) };
}

async function mine(runtime: ReturnType<typeof binding>, params: any, ctx: any, signal: AbortSignal | undefined,
                    unchanged: () => void) {
  const selection = selected(ctx), session = ctx.sessionManager.getSessionId();
  const model = ctx.model, modelBinding = miningModel(ctx, runtime);
  const snapshot = hashObject(modelBinding);
  const current = () => {
    unchanged();
    if (hashObject(miningModel(ctx, runtime)) !== snapshot)
      throw new Error('Selected model or transport changed during mining; delivery held; inspect retained bound artifacts.');
  };
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, params.timeout * 1000);
  try {
    if (signal?.aborted) throw new Error('Research mining cancelled before execution.');
    current();
    const plan = await invoke(runtime, { action: 'mine_prepare', selection, session_id: session, model_binding: modelBinding,
      query: params.query, artifact_ids: params.artifact_ids, extraction_schema: params.extraction_schema,
      ...(params.recall_bias !== undefined || !params.research_plan_id ? { recall_bias: params.recall_bias ?? 'MEDIUM' } : {}),
      ...(params.research_plan_id ? { research_plan_id: params.research_plan_id } : {}),
      ...(params.retrieval_plan_id ? { retrieval_plan_id: params.retrieval_plan_id } : {}),
      mine_timeout_seconds: params.timeout,
      ...(params.resume_artifact_id ? { resume_artifact_id: params.resume_artifact_id } : {}) },
    Math.min(params.timeout * 1000, 30000), controller.signal, true);
    current();
    if (!plan.ok) return plan;
    if (plan.cached_result) return plan.cached_result;
    const responses: object[] = [];
    let unavailable = false;
    for (let source = 0; source < plan.sources.length && !controller.signal.aborted && !unavailable; source++) {
      for (let shard = 0; shard < plan.shards.length && !controller.signal.aborted && !unavailable; shard++) {
        current();
        let status = 'model_error', text = '';
        try {
          // Pi1.4 public facade resolves this provider's request-time auth. No URL,
          // API key, tools or provider override comes from the mining request.
          const stream = ctx.modelRegistry.streamSimple(model, { systemPrompt: plan.system_prompts[shard], messages: [{
            role: 'user', content: plan.sources[source].user_prompt,
            timestamp: Date.now(),
          }] }, { reasoning: 'off', temperature: 0.1, maxTokens: modelBinding.output_tokens, signal: controller.signal });
          const result: any = await new Promise((resolve, reject) => {
            const stop = () => reject(new Error('Mining request cancelled.'));
            controller.signal.addEventListener('abort', stop, { once: true });
            if (controller.signal.aborted) stop();
            stream.result().then(resolve, reject).finally(() => controller.signal.removeEventListener('abort', stop));
          });
          current();
          if (result.provider !== modelBinding.provider || result.model !== modelBinding.id || result.api !== modelBinding.api)
            status = 'model_changed';
          else if (result.stopReason === 'length') status = 'length';
          else if (result.stopReason === 'stop' && Array.isArray(result.content)
              && result.content.every((part: any) => ['text', 'thinking'].includes(part.type))) {
            text = result.content.filter((part: any) => part.type === 'text').map((part: any) => part.text).join('');
            status = Buffer.byteLength(text) <= 32768 ? 'ok' : 'malformed';
            if (status !== 'ok') text = '';
          }
        } catch {
          status = controller.signal.aborted ? timedOut ? 'deadline' : 'cancelled' : 'model_error';
        }
        responses.push({ source, shard, status, text });
        // First native transport/route failure is model-health evidence, not
        // permission to repeat a dead backend across the remaining corpus.
        unavailable = status === 'model_error' || status === 'model_changed';
      }
    }
    current();
    // Cancellation can publish a failure ledger only, using a separate bounded
    // settlement call. It cannot schedule inference or mark any source seen.
    const value = await invoke(runtime, { action: 'mine_finish', selection, session_id: session, model_binding: modelBinding,
      plan_artifact_id: plan.plan_artifact_id, responses, cancelled: signal?.aborted === true,
      timed_out: timedOut }, 30000, controller.signal.aborted ? undefined : controller.signal);
    current();
    if (controller.signal.aborted && value.ok)
      throw new Error('Mining stopped after final publication; delivery held; inspect retained bound artifacts.');
    return value;
  } catch (error) {
    if (controller.signal.aborted)
      throw Object.assign(new Error('Research mining ' + (timedOut ? 'deadline reached' : 'cancelled')
        + '; delivery held; inspect retained bound artifacts. No automatic resume or replay.'),
      { miningStatus: timedOut ? 'deadline' : 'cancelled' });
    throw error;
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort);
  }
}

export default function (pi: ExtensionAPI) {
  let epoch = 0;
  for (const event of ['session_start', 'session_tree', 'session_shutdown'] as const) pi.on(event, async () => { epoch++; });
  pi.registerTool({
    name: 'web_research', label: 'Public web research',
    description: 'Use plan to retain the main agent question/schema/angle queries, search those angles, then retrieval_plan to declare requested URLs before fetch/render. Bind acquisition, mine and consensus to those immutable IDs for requested-set coverage; incomplete or failed requests remain held. Unbound search/fetch/render/read/mine/consensus calls remain available. Planning performs no inference and grants no permissions. Mine uses the selected local model; bound mine derives intent from its plan. Consensus is deterministic lexical/domain/numeric policy, not truth or editorial independence. Admit the project first. Read full cached data by artifact_id/offsets. Only successful unchanged mining may resume.',
    parameters: Type.Object({
      action: Type.Union(['plan', 'retrieval_plan', 'search', 'fetch', 'render', 'read', 'mine', 'consensus'].map(value => Type.Literal(value))),
      query: Type.Optional(Type.String({ minLength: 1, maxLength: 1000 })),
      url: Type.Optional(Type.String({ minLength: 1, maxLength: 4096 })),
      max_results: Type.Optional(Type.Integer({ minimum: 1, maximum: 10 })),
      timeout: Type.Optional(Type.Number({ minimum: 2, maximum: 86400,
        description: 'Declared operation seconds: mine 2–86400(default300), fetch2–120(default60), others2–60(default30;render40). Local plan/retrieval_plan/consensus enforce productive deadlines separately from cleanup; other existing calls reserve settlement. Not a session limit.' })),
      artifact_ids: Type.Optional(Type.Array(Type.String({ pattern: '^sha256:[a-f0-9]{64}$' }), { minItems: 0, maxItems: 32,
        description: 'Mine:1–4 cached fetch/render IDs. Consensus:1–32 cached mining-result IDs, within existing artifact byte quotas.' })),
      extraction_schema: Type.Optional(Type.Array(Type.String({ pattern: '^[A-Za-z][A-Za-z0-9_ -]{0,63}$' }), { minItems: 1, maxItems: 32 })),
      recall_bias: Type.Optional(Type.Union([Type.Literal('MEDIUM'), Type.Literal('HIGH')])),
      research_plan_id: Type.Optional(Type.String({ pattern: '^sha256:[a-f0-9]{64}$' })),
      retrieval_plan_id: Type.Optional(Type.String({ pattern: '^sha256:[a-f0-9]{64}$' })),
      angle_id: Type.Optional(Type.String({ pattern: '^[A-Za-z][A-Za-z0-9_-]{0,39}$' })),
      request_id: Type.Optional(Type.String({ pattern: '^[A-Za-z][A-Za-z0-9_-]{0,39}$' })),
      angles: Type.Optional(Type.Array(Type.Object({ id: Type.String({ pattern: '^[A-Za-z][A-Za-z0-9_-]{0,39}$' }),
        query: Type.String({ minLength: 1, maxLength: 1000 }) }, { additionalProperties: false }), { minItems: 1, maxItems: 12 })),
      source_priorities: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 64 }), { maxItems: 8 })),
      requests: Type.Optional(Type.Array(Type.Object({ id: Type.String({ pattern: '^[A-Za-z][A-Za-z0-9_-]{0,39}$' }),
        url: Type.String({ minLength: 1, maxLength: 4096 }), angle_id: Type.String({ pattern: '^[A-Za-z][A-Za-z0-9_-]{0,39}$' }),
        search_artifact_id: Type.Optional(Type.String({ pattern: '^sha256:[a-f0-9]{64}$' })),
        hit_index: Type.Optional(Type.Integer({ minimum: 0, maximum: 9 })) }, { additionalProperties: false }), { minItems: 1, maxItems: 128,
        description: 'Explicit URL acquisition manifest, at most64KiB serialized; exact cached search hit or agent-declared direct URL.' })),
      acquisition_artifact_ids: Type.Optional(Type.Array(Type.String({ pattern: '^sha256:[a-f0-9]{64}$' }), { maxItems: 268,
        description: 'Consensus: supplied bound search/fetch/render outcome audit. Missing fulfillment stays held; does not prove every ever-issued attempt was supplied.' })),
      fulfillments: Type.Optional(Type.Array(Type.Object({ request_id: Type.String({ pattern: '^[A-Za-z][A-Za-z0-9_-]{0,39}$' }),
        acquisition_artifact_id: Type.String({ pattern: '^sha256:[a-f0-9]{64}$' }), mining_artifact_id: Type.String({ pattern: '^sha256:[a-f0-9]{64}$' })
      }, { additionalProperties: false }), { maxItems: 128, description: 'Optional override for ambiguous fulfillment. A uniquely eligible complete acquisition+healthy mining pair is selected automatically and recorded. All supplied attempts remain audited.' })),
      search_fulfillments: Type.Optional(Type.Array(Type.Object({ angle_id: Type.String({ pattern: '^[A-Za-z][A-Za-z0-9_-]{0,39}$' }),
        artifact_id: Type.String({ pattern: '^sha256:[a-f0-9]{64}$' }) }, { additionalProperties: false }), { maxItems: 12 })),
      resume_artifact_id: Type.Optional(Type.String({ pattern: '^sha256:[a-f0-9]{64}$' })),
      allow_archive: Type.Optional(Type.Boolean({ description: 'Fetch only: permit a public archive candidate after eligible source failures. Archived and abstract results remain partial. Default false.' })),
      artifact_id: Type.Optional(Type.String({ pattern: '^sha256:[a-f0-9]{64}$' })),
      view: Type.Optional(Type.Union(['text', 'metadata', 'tables', 'links', 'headings', 'downloads'].map(value => Type.Literal(value)))),
      offset: Type.Optional(Type.Integer({ minimum: 0 })),
      limit: Type.Optional(Type.Integer({ minimum: 80, maximum: 8192 })),
      wait_selector: Type.Optional(Type.String({ minLength: 1, maxLength: 500 })),
      click_selectors: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 500 }), { maxItems: 4 })),
      download_selector: Type.Optional(Type.String({ minLength: 1, maxLength: 500 })),
    }, { additionalProperties: false }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      try {
        const timeout = params.timeout ?? (params.action === 'mine' ? 300 : params.action === 'render' ? 40 : params.action === 'fetch' ? 60 : 30);
        const maximumTimeout = params.action === 'mine' ? 86400 : params.action === 'fetch' ? 120 : 60;
        if (!Number.isFinite(timeout) || timeout < 2 || timeout > maximumTimeout)
          throw new Error(`Research ${params.action} timeout must be 2 through ${maximumTimeout} seconds.`);
        const selection = selected(ctx);
        const session = ctx.sessionManager.getSessionId();
        const fingerprint = JSON.stringify(selection);
        const branch = ctx.sessionManager.getLeafId(), before = epoch;
        const unchanged = () => {
          if (epoch !== before || ctx.sessionManager.getSessionId() !== session || ctx.sessionManager.getLeafId() !== branch
              || JSON.stringify(selected(ctx)) !== fingerprint)
            throw new Error('Session input or project admission changed during research; delivery held; inspect retained bound artifacts.');
        };
        const value = params.action === 'mine'
          ? await mine(binding(), { ...params, timeout }, ctx, signal, unchanged)
          : await invoke(binding(), { ...params, selection, session_id: session },
            timeout * 1000 + (LOCAL_ACTIONS.has(params.action) ? 0 : 30000), signal);
        if (params.action === 'mine' || LOCAL_ACTIONS.has(params.action) || params.research_plan_id || params.retrieval_plan_id) unchanged();
        if (ctx.sessionManager.getSessionId() !== session || JSON.stringify(selected(ctx)) !== fingerprint)
          throw new Error('Project selection changed during research; no result was delivered.');
        if ((LOCAL_ACTIONS.has(params.action) || params.research_plan_id || params.retrieval_plan_id) && signal?.aborted)
          throw Object.assign(new Error('Research cancelled after helper settlement; delivery held; inspect retained bound artifacts.'),
            { researchStatus: 'cancelled' });
        return { content: [{ type: 'text', text: JSON.stringify(value) }], details: value, isError: !value.ok };
      } catch (error) {
        const value = { schema: 'research-result/v1', ok: false,
          status: params.action === 'mine' ? (error as any)?.miningStatus ?? (signal?.aborted ? 'cancelled' : 'runtime_error')
            : LOCAL_ACTIONS.has(params.action) || params.research_plan_id || params.retrieval_plan_id
              ? (error as any)?.researchStatus ?? (signal?.aborted ? 'cancelled' : 'runtime_error') : 'runtime_error',
          reason: String(error).slice(0, 1000), authority: 'untrusted_source_evidence' };
        return { content: [{ type: 'text', text: JSON.stringify(value) }], details: value, isError: true };
      }
    },
  });
}
