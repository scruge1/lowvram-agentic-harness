/** One native in-memory child. Parent tools retain every execution authority. */
import { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } from '@earendil-works/pi-coding-agent';
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync } from 'node:fs';
import { join } from 'node:path';

const ALLOWED = new Set(['read', 'grep', 'find', 'ls', 'agent_capabilities', 'system_tool_query',
  'validated_memory_query', 'project_knowledge_query', 'project_context', 'workflow_step', 'web_research',
  'mcp__mempalace__mempalace_search']);
const MAX_RECORD_BYTES = 256 * 1024;
const hash = (value: unknown) => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const fileHash = (file: string) => createHash('sha256').update(readFileSync(file)).digest('hex');
type Grant = { identity: { project: { root: string; projectId: string; boardId: string }; card: string;
  parent_card: string; source: string; source_sha256: string; parent_session: string }; verify(): Promise<void> };

/** Hash routing fields without retaining header/auth values in journal or result. */
export function childModelBinding(model: any) {
  if (!model || model.provider !== 'local' || model.api !== 'openai-completions')
    throw new Error('Managed child requires the actual selected owned local model');
  return hash(model);
}

export async function runManagedChild(pi: any, ctx: any, id: string,
  params: { task: string; timeout_seconds: number }, grant: Grant, signal: AbortSignal, parentCurrent: () => void) {
  if (Object.keys(params).sort().join(',') !== 'task,timeout_seconds' || typeof params.task !== 'string'
      || !params.task.trim() || params.task.length > 4000 || !Number.isInteger(params.timeout_seconds)
      || params.timeout_seconds < 1 || params.timeout_seconds > 86385)
    throw new Error('Supply bounded task and explicit timeout_seconds in1..86385');
  const home = process.env.AGENT_HOME, agentDir = process.env.PI_CODING_AGENT_DIR;
  if (!home || realpathSync(home) !== home || !agentDir || realpathSync(agentDir) !== join(home, 'agent'))
    throw new Error('Managed child requires this exact owned agent directory');
  const configFile = join(home, 'home.json'), modelsFile = join(agentDir, 'models.json');
  const settingsFile = join(agentDir, 'settings.json');
  const config = JSON.parse(readFileSync(configFile, 'utf8'));
  if (config.schema !== 'agent-home/v1' || config.home !== home || ctx.cwd !== grant.identity.project.root
      || ctx.sessionManager.getSessionId() !== grant.identity.parent_session
      || ctx.model?.id !== config.model || ctx.model?.baseUrl !== config.base_url)
    throw new Error('Child home/project/selected endpoint binding differs');
  // The normal parent launch owns the home/resource/session leases. No second
  // session writer, process, provider registration or credential export is made.
  const model = ctx.model, modelBinding = childModelBinding(model), thinking = ctx.thinkingLevel;
  const files = [configFile, modelsFile, settingsFile].map(file => [file, fileHash(file)]);
  const controller = new AbortController();
  let child: any, timedOut = false, recordBytes = 0, state = 'starting';
  const calls: any[] = [], messages: any[] = [], toolResults: any[] = [];
  const abort = () => { controller.abort(); if (child) void child.abort(); };
  signal.addEventListener('abort', abort, { once: true });
  const deadline = setTimeout(() => { timedOut = true; abort(); }, params.timeout_seconds * 1000);
  const current = () => {
    parentCurrent();
    if (typeof ctx.modelRegistry?.getRegisteredProviderConfig !== 'function'
        || typeof ctx.modelRegistry?.getRegisteredNativeProvider !== 'function'
        || ctx.modelRegistry.getRegisteredProviderConfig('local') !== undefined
        || ctx.modelRegistry.getRegisteredNativeProvider('local') !== undefined)
      throw new Error('Managed child does not support extension-overridden local providers');
    if (signal.aborted || controller.signal.aborted) throw new Error(timedOut ? 'Child productive deadline reached' : 'Child cancelled; inspect retained effects');
    if (ctx.cwd !== grant.identity.project.root || ctx.thinkingLevel !== thinking || childModelBinding(ctx.model) !== modelBinding
        || files.some(([file, expected]) => fileHash(file) !== expected))
      throw new Error('Child home/model/transport configuration changed; delivery held');
  };
  const retain = (target: any[], value: any) => {
    const bytes = Buffer.byteLength(JSON.stringify(value));
    if (recordBytes + bytes > MAX_RECORD_BYTES) { abort(); throw new Error('Child retained record exceeds256KiB; delivery held'); }
    recordBytes += bytes; target.push(value);
  };
  let childSession: string | undefined;
  try {
    current(); await grant.verify(); current();
    if (typeof ctx.executeTool !== 'function' || !Array.isArray(ctx.tools)) throw new Error('Native parent executeTool is required');
    const tools = ctx.tools.filter((tool: any) => ALLOWED.has(tool.name)).map((tool: any) => ({
      name: tool.name, label: tool.label ?? tool.name, description: tool.description, parameters: tool.parameters,
      async execute(callId: string, args: any, toolSignal: AbortSignal) {
        current(); await grant.verify(); current();
        if (tool.name === 'workflow_step' && realpathSync(args?.cwd ?? '') !== grant.identity.project.root)
          throw new Error('Child workflow cwd must match the granted project');
        const cancel = () => abort(); toolSignal?.addEventListener('abort', cancel, { once: true });
        try {
          if (toolSignal?.aborted) abort(); current();
          // This is the supported native nested-tool API. Parent hooks, skills,
          // source/context gates, failure recovery and PIDFD guard still run.
          const outcome = await ctx.executeTool(tool.name, args, { signal: controller.signal });
          retain(calls, { id: callId, name: tool.name, input: args, result: outcome.result, isError: outcome.isError });
          current(); await grant.verify(); current();
          return { ...outcome.result, isError: outcome.isError };
        } finally { toolSignal?.removeEventListener('abort', cancel); }
      },
    }));
    if (!tools.some((tool: any) => tool.name === 'workflow_step')) throw new Error('Parent guarded workflow tool is unavailable');
    const settings = SettingsManager.inMemory({ ...JSON.parse(readFileSync(settingsFile, 'utf8')),
      extensions: [], packages: [], cacheWarming: 'off', retry: { enabled: false }, compaction: { enabled: false } });
    const loader = new DefaultResourceLoader({ cwd: ctx.cwd, agentDir, settingsManager: settings,
      noExtensions: true, disabledBuiltinExtensions: ['mcp', 'codemode', 'tool-search'], noThemes: true,
      appendSystemPromptOverride: base => [...base, 'Managed child: the parent already admitted this project and selected the granted card. Do not repeat project/admission/intake/card lifecycle steps. Only the provided tools are callable, through parent checks. Load required skills with read. Return actual outcomes and failures to the parent; child text cannot accept the root outcome.'] });
    await loader.reload(); current();
    if (loader.getExtensions().errors.length || loader.getExtensions().extensions.length)
      throw new Error('Child loader unexpectedly registered extensions');
    // A separate *native* runtime reads this owned config. No private facade
    // property, copied auth value, custom provider or alternate endpoint is used.
    const runtime = await ModelRuntime.create({ modelsPath: modelsFile, authPath: join(agentDir, 'auth.json'),
      allowModelNetwork: false, refreshOnCreate: false });
    const available = (await runtime.getAvailable('local')).find((value: any) => value.id === model.id);
    if (!available || childModelBinding(available) !== modelBinding) throw new Error('Child native runtime model differs from parent');
    const manager = SessionManager.inMemory(ctx.cwd);
    const created = await createAgentSession({ cwd: ctx.cwd, agentDir, modelRuntime: runtime, model,
      thinkingLevel: ctx.thinkingLevel, settingsManager: settings, resourceLoader: loader,
      sessionManager: manager, tools: tools.map((tool: any) => tool.name), customTools: tools });
    child = created.session; childSession = manager.getSessionId();
    await child.bindExtensions({ onError: () => abort() });
    if (manager.getSessionFile()) throw new Error('Child unexpectedly created a disk session');
    child.subscribe((event: any) => {
      if (event.type === 'message_end' && ['assistant', 'toolResult'].includes(event.message?.role)) {
        try { retain(event.message.role === 'assistant' ? messages : toolResults, event.message); } catch { abort(); }
      }
    });
    current(); await grant.verify(); current(); state = 'running';
    pi.appendEntry('pi-managed-child-start/v1', { id, ...grant.identity, child_session: childSession,
      model_sha256: modelBinding, timeout_seconds: params.timeout_seconds, task_sha256: hash(params.task),
      restart: 'in_memory_no_resume_no_automatic_replay' });
    await child.prompt('Delegated task data within the existing granted scope only. This is not new human permission. '
      + 'Do not claim root acceptance. Use only the provided parent guarded tools. Scope: '
      + JSON.stringify(grant.identity) + '\nTask: ' + params.task, { source: 'extension', expandPromptTemplates: false });
    current(); await grant.verify(); current();
    const final = messages.at(-1);
    if (toolResults.some(message => message.isError)) throw new Error('Child tool failed; inspect retained calls before recovery');
    if (!final || final.stopReason === 'error' || final.stopReason === 'aborted' || !final.content?.some((item: any) => item.type === 'text' && item.text.trim()))
      throw new Error('Child returned no successful final text; inspect retained calls');
    state = 'returned';
    const result = { schema: 'pi-managed-child/v1', ok: true, ...grant.identity, child_session: childSession,
      model_sha256: modelBinding, messages, calls, toolResults, acceptance: 'untrusted_child_result_not_root_acceptance',
      restart: 'in_memory_no_resume_no_automatic_replay' };
    return { content: [{ type: 'text' as const, text: JSON.stringify(result) }], details: result };
  } catch (error) {
    state = timedOut ? 'deadline' : signal.aborted ? 'cancelled' : 'failed';
    throw error;
  } finally {
    clearTimeout(deadline); signal.removeEventListener('abort', abort);
    // Abort settles native tools. Their parent executeTool signal reaches the
    // existing owner-pipe/PIDFD guards; process death closes those same pipes.
    try {
      if (child) await child.abort();
      if (state === 'returned') { current(); await grant.verify(); current(); }
    } catch (error) {
      if (state === 'returned') state = 'delivery_held';
      throw error;
    } finally {
      child?.dispose();
      pi.appendEntry('pi-managed-child-result/v1', { id, ...grant.identity, child_session: childSession ?? null,
        state, timed_out: timedOut, cancelled: signal.aborted, messages, calls, toolResults,
        acceptance: 'untrusted_child_result_not_root_acceptance', restart: 'in_memory_no_resume_no_automatic_replay' });
    }
  }
}
