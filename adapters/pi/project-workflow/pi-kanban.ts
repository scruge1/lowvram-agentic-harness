import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { registerRequestIntake } from '../intake/request-intake-138.ts';
import { registerProjectContext } from '../context/project-context.ts';
import { projectKanbanReply } from './kanban-reply-projector.mjs';

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
const RARE_PROJECT_TOOLS = [
  'kanban_hierarchy', 'kanban_decompose', 'project_knowledge_rebuild',
  'project_closeout_prepare', 'project_skill_candidate_compile', 'project_memory_candidate_prepare',
  'kanban_list', 'kanban_show', 'kanban_create', 'kanban_comment',
] as const;

type Reply = { schema: string; ok: boolean; action?: string; result?: unknown; limits?: string[]; error?: string };
const offsetSchema = () => Type.Integer({ minimum: 0, maximum: Number.MAX_SAFE_INTEGER });
const viewSchema = Type.Object({
  before_id: Type.Optional(offsetSchema()),
  comment_id: Type.Optional(offsetSchema()),
  offset: Type.Optional(offsetSchema()),
  body_offset: Type.Optional(offsetSchema()),
  items_offset: Type.Optional(offsetSchema()),
  items_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
  hierarchy_offset: Type.Optional(offsetSchema()),
  relation_offset: Type.Optional(offsetSchema()),
  max_bytes: Type.Optional(Type.Integer({ minimum: 1024, maximum: 12288 })),
  task_field: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
  expected_reply_sha256: Type.Optional(Type.String({ pattern: '^[a-f0-9]{64}$' })),
}, { additionalProperties: false });

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

function createManagedProject(name: string, signal?: AbortSignal): Promise<Reply> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new Error('Project creation cancelled before launch')); return; }
    let python: string, helper: string;
    try {
      const home = requiredEnvironment('AGENT_HOME');
      python = requiredEnvironment('AGENT_HOME_PYTHON');
      const config = JSON.parse(readFileSync(join(home, 'home.json'), 'utf8'));
      const raw = readFileSync(join(home, 'runtime', 'runtime-manifest.json'));
      if (config?.schema !== 'agent-home/v1' || config.home !== home
          || createHash('sha256').update(raw).digest('hex') !== config.runtime_manifest_sha256)
        throw new Error('Managed home/runtime binding differs');
      helper = join(home, 'runtime', 'adapters', 'pi', 'project-workflow', 'project_create.py');
      const expected = JSON.parse(raw.toString('utf8')).files.find((item: any) => item.path === 'adapters/pi/project-workflow/project_create.py')?.sha256;
      if (!expected || createHash('sha256').update(readFileSync(helper)).digest('hex') !== expected)
        throw new Error('Managed project helper source drift');
    } catch (error) { reject(error); return; }
    const child = spawn(python, ['-s', '-B', helper, '--name=' + name], {
      stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, PI_TASK_TIMEOUT: '90', CUDA_VISIBLE_DEVICES: '' },
    });
    let out = Buffer.alloc(0), error = Buffer.alloc(0), done = false;
    const finish = (failure?: Error, value?: Reply) => {
      if (done) return;
      done = true; clearTimeout(timer); signal?.removeEventListener('abort', abort);
      child.stdin.end(); // EOF asks the existing guard to settle its descendants.
      failure ? reject(failure) : resolve(value!);
    };
    const abort = () => finish(new Error('Project creation cancelled; inspect any partial project before adoption'));
    const timer = setTimeout(() => finish(new Error('Project creation deadline; preserve and inspect any partial project')), 105000);
    signal?.addEventListener('abort', abort, { once: true });
    child.on('error', failure => finish(failure));
    child.stdout.on('data', chunk => { out = Buffer.concat([out, chunk]); if (out.length > MAX_OUTPUT) finish(new Error('Project creation result exceeds its bound')); });
    child.stderr.on('data', chunk => { error = Buffer.concat([error, chunk]); if (error.length > 8192) finish(new Error('Project creation diagnostics exceed their bound')); });
    child.on('close', code => {
      let value: Reply;
      try { value = JSON.parse(out.toString('utf8')); }
      catch { finish(new Error('Project creation returned no complete result; inspect any partial project')); return; }
      if (code !== 0 || value.schema !== 'pi-kanban-result/v1' || value.ok !== true)
        finish(new Error(value.error || 'Project creation failed; inspect any partial project'));
      else finish(undefined, value);
    });
    child.stdin.on('error', () => finish(new Error('Project creation ownership pipe failed')));
    // Retain the owner pipe through the existing lifecycle/worker guard.
  });
}

function response(value: Reply, view: Record<string, unknown> = {}) {
  // Only the model view is projected. Full controller evidence stays intact.
  return { content: [{ type: 'text' as const, text: JSON.stringify(projectKanbanReply(value, view)) }], details: value };
}

function failure(error: unknown) {
  const message = error instanceof Error ? error.message : 'unknown kanban error';
  return { content: [{ type: 'text' as const, text: `Kanban operation failed: ${message}` }], details: { ok: false, error: message }, isError: true };
}

function successfulCanonicalMemorySearch(event: any): boolean {
  // Pi preserves the full MCP result here, before model-facing output limits.
  // MemPalace can report semantic errors as JSON without setting MCP isError.
  const raw = event.structuredContent;
  if (event.isError || raw?.isError) return false;
  const blocks = raw?.content ?? event.content;
  if (!Array.isArray(blocks) || blocks.length !== 1
      || blocks[0]?.type !== 'text' || typeof blocks[0].text !== 'string') return false;
  try {
    const value = JSON.parse(blocks[0].text);
    return value !== null && typeof value === 'object' && !Array.isArray(value)
      && Array.isArray(value.results)
      && !Object.prototype.hasOwnProperty.call(value, 'error');
  } catch {
    return false;
  }
}

export default function (pi: ExtensionAPI) {
  const nativeExposure = typeof pi.getAllTools === 'function'
    && typeof pi.getActiveTools === 'function' && typeof pi.setActiveTools === 'function';
  const enableRareToolDiscovery = () => {
    if (!nativeExposure) return; // Older API surfaces retain direct definitions.
    const active = pi.getActiveTools();
    try {
      const search = pi.getAllTools().find(tool => tool.name === 'tool_search');
      if (typeof search?.reachesTools === 'function' && search.exposure !== 'hidden') {
        if (!active.includes('tool_search')) pi.setActiveTools([...active, 'tool_search']);
        if (pi.getActiveTools().includes('tool_search')) return;
      }
    } catch { /* Preserve the previous direct surface if discovery cannot be used. */ }
    pi.setActiveTools([...new Set([...active, ...RARE_PROJECT_TOOLS])]);
  };
  const pendingConsultations = new Map<string, { taskId: string; cardId?: string; objective: string; draftPlan: string }>();
  let activeProject: { root: string; projectId: string; boardId: string } | null = null;
  let activeTask: { taskId: string; cardId: string } | null = null;
  let boardAdmissionFailed = false;
  let capabilitiesObserved = false;
  let systemToolsQueried = false;
  let memoryQueried = false;
  let knowledgeQueried = false;
  const preparing = new Set<string>();
  const prepared = new Map<string, {
    project: NonNullable<typeof activeProject>; session: string; text: string;
    stamp: string; sources: [string, string][]; observations: string[]; signal?: AbortSignal;
  }>();
  const sourceDigest = (file: string | URL) => createHash('sha256').update(readFileSync(file)).digest('hex');
  const preparationStamp = () => JSON.stringify([
    ...['PI_PROJECT_KANBAN_ADAPTER', 'PI_SYSTEM_TOOL_HELPER', 'PI_SYSTEM_TOOL_DATABASE',
      'PI_VALIDATED_MEMORY_HELPER', 'PI_VALIDATED_MEMORY_POLICY', 'PI_VALIDATED_MEMORY_REGISTRY',
      'PI_MEMORY_RUNTIME_WRAPPER'].map(key => {
      const file = process.env[key]; return [key, file ?? null, file ? sourceDigest(file) : null];
    }),
    ...['./pi-kanban.ts', './agent-capabilities.ts', './system-tool-knowledge.ts',
      '../memory/validated-memory-query.ts', '../context/project-context.ts'].map(file =>
      [file, sourceDigest(new URL(file, import.meta.url))]),
  ]);

  // Navigation is persisted in the native branch. It is never execution permission.
  const saveSelection = () => pi.appendEntry('pi-kanban-selection/v1', {
    project: activeProject, task: activeTask, boardAdmissionFailed,
  });
  const resetDiscovery = () => {
    capabilitiesObserved = false;
    systemToolsQueried = false;
    memoryQueried = false;
    knowledgeQueried = false;
    pendingConsultations.clear();
    prepared.clear();
  };
  const restoreSelection = async (_event: any, ctx: any) => {
    // Adding discovery never removes a tool explicitly active on a resumed branch.
    enableRareToolDiscovery();
    activeProject = null;
    activeTask = null;
    boardAdmissionFailed = false;
    resetDiscovery();
    const saved = [...ctx.sessionManager.getBranch()].reverse().find(
      (entry: any) => entry.type === 'custom' && entry.customType === 'pi-kanban-selection/v1')?.data;
    if (!saved?.project) return;
    try {
      const value = await callAdapter({ action: 'project_admit', project_root: saved.project.root });
      const result = value.result as any;
      if (result?.project_root !== saved.project.root
          || result?.identity?.project_id !== saved.project.projectId
          || result?.identity?.board_id !== saved.project.boardId) throw new Error('Saved project identity changed');
      activeProject = { root: result.project_root, projectId: result.identity.project_id,
        boardId: result.identity.board_id };
      boardAdmissionFailed = saved.boardAdmissionFailed === true;
      if (saved.task) {
        const card = await callAdapter({ action: 'show', project_root: activeProject.root,
          task_id: saved.task.cardId });
        if ((card.result as any)?.task?.id !== saved.task.cardId) throw new Error('Saved task identity changed');
        activeTask = { taskId: saved.task.cardId, cardId: saved.task.cardId };
      }
    } catch {
      activeTask = null;
      boardAdmissionFailed = true;
      ctx.ui?.notify?.('Saved Kanban selection could not be validated. Admit the project and select its card again.', 'warning');
    }
  };
  pi.on('session_start', restoreSelection);
  pi.on('session_tree', restoreSelection);

  const contextDelivery = registerProjectContext(pi, { project: () => activeProject });
  registerRequestIntake(pi, {
    project: () => activeProject,
    task: () => activeTask?.cardId ?? null,
    select: (id: string) => {
      activeTask = { taskId: id, cardId: id };
      saveSelection();
    },
    failed: () => boardAdmissionFailed,
    call: callAdapter,
  });

  const projectRequest = (request: Record<string, unknown>) => {
    if (!activeProject) throw new Error('Admit a project with project_admit before using its board');
    return { ...request, project_root: activeProject.root };
  };

  const selectAdmission = (value: Reply) => {
    const result = value.result as any;
    const projectId = result?.identity?.project_id;
    const boardId = result?.identity?.board_id;
    const root = result?.project_root;
    if (typeof root !== 'string' || typeof projectId !== 'string' || typeof boardId !== 'string') throw new Error('project admission returned an incomplete identity');
    const sameProject = activeProject?.root === root && activeProject?.projectId === projectId
      && activeProject?.boardId === boardId;
    activeProject = { root, projectId, boardId };
    if (!sameProject) activeTask = null;
    boardAdmissionFailed = false;
    resetDiscovery();
    saveSelection();
  };
  const clearAdmission = () => {
    if (!activeProject && !activeTask && boardAdmissionFailed) return;
    activeProject = null;
    activeTask = null;
    boardAdmissionFailed = true;
    resetDiscovery();
    saveSelection();
  };
  const failedAdmission = (error: unknown) => { clearAdmission(); return failure(error); };

  pi.registerTool({
    name: 'project_prepare', label: 'Read project preparation context',
    description: 'For an already admitted project, deliver actual callable capabilities, relevant system tools, validated memory, project knowledge and missing instructions in one bounded packet. Supply explicit relevance query. No admission, task selection, permission, skill or execution authority. Follow incomplete sections and remaining_reads; readiness counts only after unchanged result delivery to model context.',
    parameters: Type.Object({ query: Type.String({ minLength: 1, maxLength: 1000 }),
      path: Type.Optional(Type.String({ minLength: 1, maxLength: 4096 })) }, { additionalProperties: false }),
    async execute(id, params, signal, _update, ctx) {
      const project = activeProject;
      if (!project || !params.query.trim()) return failure(new Error('Select an existing project and supply a relevant query first'));
      if (typeof ctx.executeTool !== 'function') return failure(new Error('Native nested tool calls are unavailable'));
      preparing.add(id);
      try {
        const stamp = preparationStamp(), session = ctx.sessionManager.getSessionId();
        const sections: any[] = [], observations: string[] = [], sources: [string, string][] = [];
        let contextChild: { id: string; text: string } | undefined;
        const children = [
          ['project_context', params.path ? { path: params.path } : {}],
          ['agent_capabilities', {}], ['system_tool_query', { terms: params.query, limit: 5 }],
          ['validated_memory_query', { query: params.query, limit: 5 }],
          ['project_knowledge_query', { terms: params.query, limit: 5 }],
        ] as const;
        let used = 4096;
        for (const [name, args] of children) {
          if (signal?.aborted) throw new Error('Preparation cancelled');
          if (!ctx.tools.some(tool => tool.name === name)) {
            // The public search tool may expose a fixed deferred read tool. It does not
            // count as executing that read tool, and cannot widen this fixed child set.
            await ctx.executeTool('tool_search', { query: name, limit: 1 }, { signal });
          }
          const outcome = await ctx.executeTool(name, args, { signal });
          if (signal?.aborted || activeProject !== project || ctx.sessionManager.getSessionId() !== session)
            throw new Error('Preparation identity changed or was cancelled');
          const raw = outcome.result;
          const text = raw?.content?.length === 1 && raw.content[0].type === 'text' ? raw.content[0].text : undefined;
          const size = typeof text === 'string' ? Buffer.byteLength(JSON.stringify(text)) : Infinity;
          if (size > 32768 || used + size > 61440) {
            sections.push({ tool: name, call_id: outcome.toolCall.id, status: 'omitted', reason: 'result_exceeds_packet_bound' });
            continue;
          }
          used += size;
          let value: any;
          try { value = JSON.parse(text); } catch { /* Preserve error text, without success evidence. */ }
          let ok = !outcome.isError && raw?.details?.ok !== false;
          if (name === 'agent_capabilities') ok &&= raw?.details?.ok === true
            && value?.schema === 'pi-native-capabilities/v1' && value.session_id === session;
          else if (name === 'validated_memory_query') ok &&= value?.schema === 'validated-memory-query/v1'
            && Array.isArray(value.results) && value.reason !== 'sensitive_query';
          else if (name === 'project_context') ok &&= value?.ok === true && value.root === project.root;
          else ok &&= value?.ok === true && (name !== 'system_tool_query' || Array.isArray(value.results));
          sections.push({ tool: name, call_id: outcome.toolCall.id,
            status: !ok ? 'unavailable' : name === 'project_context' && value.remaining_reads?.length ? 'partial' : 'returned',
            content: text, content_sha256: createHash('sha256').update(text).digest('hex') });
          if (!ok) continue;
          if (name === 'project_context') contextChild = { id: outcome.toolCall.id, text };
          else observations.push(name);
          const records = name === 'project_knowledge_query' ? value.result?.results : value.results;
          for (const record of records ?? []) {
            const file = name === 'project_knowledge_query' ? join(project.root, record.path ?? '')
              : record.source_path ?? record.source_file;
            const hash = name === 'project_knowledge_query' ? record.sha256 : record.source_sha256;
            // Palace URIs are verified by the existing validated query, not host file paths.
            if (typeof file === 'string' && (file.startsWith('/') || /^[A-Za-z]:[\\/]/.test(file))
                && /^[a-f0-9]{64}$/.test(hash)) sources.push([file, hash]);
          }
        }
        if (signal?.aborted || activeProject !== project || preparationStamp() !== stamp)
          throw new Error('Preparation source or identity changed');
        const packet = { schema: 'pi-project-preparation/v1', ok: true, project_root: project.root,
          project_id: project.projectId, session_id: session, query: params.query, sections,
          complete: sections.every(section => section.status === 'returned'),
          limits: 'Read-only context delivery, not permission or completion. Omitted/unavailable sections do not count. Memory source freshness is checked by the validated query; helper/registry bindings are rechecked at delivery. Follow project_context remaining_reads and existing skill/intake/board/effect gates.' };
        const text = JSON.stringify(packet);
        if (Buffer.byteLength(text) > 65536) throw new Error('Preparation packet exceeds64KiB');
        if (contextChild) contextDelivery.enclose(contextChild.id, id, contextChild.text, text, () =>
          !signal?.aborted && activeProject === project && ctx.sessionManager.getSessionId() === session
          && preparationStamp() === stamp && sources.every(([file, hash]) => sourceDigest(file) === hash));
        prepared.set(id, { project, session, stamp, sources, observations, text, signal });
        while (prepared.size > 16) prepared.delete(prepared.keys().next().value!);
        return { content: [{ type: 'text' as const, text }], details: { ok: true, schema: packet.schema, complete: packet.complete } };
      } catch {
        prepared.delete(id);
        return failure(new Error('Project preparation unavailable, cancelled or changed. Inspect incomplete sections with the existing read tools.'));
      } finally { preparing.delete(id); }
    },
  });

  pi.on('context', async (event: any, ctx: any) => {
    for (const message of event.messages) {
      const proof = prepared.get(message.toolCallId);
      if (message.role !== 'toolResult' || !proof) continue;
      prepared.delete(message.toolCallId);
      const text = message.content?.length === 1 && message.content[0].type === 'text' ? message.content[0].text : undefined;
      if (message.isError || proof.signal?.aborted || text !== proof.text || activeProject !== proof.project
          || ctx.sessionManager.getSessionId() !== proof.session) continue;
      try {
        if (preparationStamp() !== proof.stamp || proof.sources.some(([file, hash]) => sourceDigest(file) !== hash)) continue;
        // Keep the existing project-bound snapshot operation. Only delivered capability
        // bytes can reach it; failure does not unlock planning or execution.
        const packet = JSON.parse(text);
        if (proof.observations.includes('agent_capabilities')) {
          const section = packet.sections.find((value: any) => value.tool === 'agent_capabilities');
          await callAdapter(projectRequest({ action: 'capability_snapshot', snapshot: JSON.parse(section.content), session_id: proof.session }));
          if (activeProject !== proof.project) continue;
          capabilitiesObserved = true;
        }
        if (proof.observations.includes('system_tool_query')) systemToolsQueried = true;
        if (proof.observations.includes('validated_memory_query')) memoryQueried = true;
        if (proof.observations.includes('project_knowledge_query')) knowledgeQueried = true;
      } catch { /* Drift or unavailable snapshot storage cannot establish readiness. */ }
    }
  });

  pi.registerTool({
    name: 'project_create', label: 'Create managed project',
    description: 'Create a NEW short-named project under this managed home/projects with Git, AGENTS.md, .gitignore and its isolated ICM/board, then select it. Selects no task and grants no execution permission. Existing/external projects use project_admit without initialize.',
    parameters: Type.Object({ name: Type.String({ minLength: 1, maxLength: 80, pattern: '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$' }) }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      try {
        clearAdmission();
        if (Object.keys(params).length !== 1 || !Object.prototype.hasOwnProperty.call(params, 'name')
            || typeof params.name !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(params.name))
          throw new Error('project_create accepts only one short project name');
        const created = await createManagedProject(params.name, signal);
        const root = join(requiredEnvironment('AGENT_HOME'), 'projects', params.name);
        const result = created.result as any;
        if (result?.project_root !== root) throw new Error('Created managed project root differs');
        if (signal?.aborted) throw new Error('Project creation cancelled before readmission');
        const admitted = await callAdapter({ action: 'project_admit', project_root: root }, signal);
        if (signal?.aborted) throw new Error('Project creation cancelled during readmission');
        const actual = admitted.result as any;
        if (actual?.identity?.project_id !== result?.identity?.project_id || actual?.identity?.board_id !== result?.identity?.board_id)
          throw new Error('Created project identity changed during admission');
        if (signal?.aborted) throw new Error('Project creation cancelled before selection');
        selectAdmission(admitted);
        return response({ ...admitted, action: 'project_create', limits: created.limits });
      } catch (error) {
        const cause = error instanceof Error ? error.message : String(error);
        return failedAdmission(new Error(cause + '. Preserve any partial project; inspect Git, instructions and ICM/board before project_admit without initialize. Do not recreate or reinitialize it.'));
      }
    },
  });

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
        selectAdmission(value);
        return response(value);
      } catch (error) { return failedAdmission(error); }
    },
  });

  pi.registerTool({
    name: 'project_recover', label: 'Inspect or recover project provenance',
    description: 'Inspect an existing legacy project identity. Bind only a missing native authority with its exact prior identity hash. Preserve IDs, boards, pauses and evidence.',
    parameters: Type.Object({ project_root: Type.String(),
      expected_identity_sha256: Type.Optional(Type.String()),
      native_authority: Type.Optional(Type.String()) }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      try { return response(await callAdapter({ action: 'project_recover', ...params }, signal)); }
      catch (error) { return failure(error); }
    },
  });

  pi.registerTool({
    name: 'kanban_hierarchy', label: 'Read retained task hierarchy',
    exposure: nativeExposure ? 'deferred' : 'direct',
    description: 'Read decomposition containment and distinct native prerequisites. A ready card is not completed work or execution authority.',
    parameters: Type.Object({ task_id: Type.String(),
      depth: Type.Optional(Type.Integer({ minimum: 1, maximum: 12 })),
      view: Type.Optional(viewSchema) }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      const { view, ...request } = params;
      try { return response(await callAdapter(projectRequest({ action: 'hierarchy', ...request }), signal), view); }
      catch (error) { return failure(error); }
    },
  });

  pi.registerTool({
    name: 'kanban_decompose', label: 'Decompose an unstarted task',
    exposure: nativeExposure ? 'deferred' : 'direct',
    description: 'Use native Hermes fan-out on an unstarted triage root. Sibling indices express prerequisites; expandable children remain triage. Keep the original owner outcome.',
    parameters: Type.Object({ task_id: Type.String(), children: Type.Array(Type.Object({
      title: Type.String({ minLength: 1, maxLength: 200 }),
      body: Type.Optional(Type.String({ maxLength: 8000 })),
      parents: Type.Optional(Type.Array(Type.Integer({ minimum: 0, maximum: 11 }))),
      expandable: Type.Optional(Type.Boolean()),
    }, { additionalProperties: false }), { minItems: 1, maxItems: 12 }) }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      try { return response(await callAdapter(projectRequest({ action: 'decompose', ...params }), signal)); }
      catch (error) { return failure(error); }
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
    exposure: nativeExposure ? 'deferred' : 'direct',
    description: 'Rebuild the admitted project retrieval index and hash-bound manifest from its readable source policy. This grants retrieval-only authority.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_id, _params, signal) { try { return response(await callAdapter(projectRequest({ action: 'knowledge_build' }), signal)); } catch (error) { return failure(error); } },
  });

  pi.registerTool({
    name: 'project_closeout_prepare', label: 'Prepare verified project closeout',
    exposure: nativeExposure ? 'deferred' : 'direct',
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
    exposure: nativeExposure ? 'deferred' : 'direct',
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
    name: 'project_memory_candidate_prepare', label: 'Prepare project memory candidate',
    exposure: nativeExposure ? 'deferred' : 'direct',
    description: 'Bind one verified project closeout to one exact MemPalace drawer readback and write an immutable project-local memory claim candidate. It rejects sensitive summaries and grants no shared-memory promotion authority.',
    parameters: Type.Object({
      closeout_path: Type.String({ minLength: 1, maxLength: 4096 }),
      drawer_snapshot_path: Type.String({ minLength: 1, maxLength: 4096 }),
    }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'project_memory_candidate_prepare', ...params }), signal)); } catch (error) { return failure(error); } },
  });

  pi.registerTool({
    name: 'kanban_status', label: 'Kanban status',
    description: 'Read the live host-local Pi Kanban backend identity, runtime, journal mode, task counts, and authority limits.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_id, _params, signal) { try { return response(await callAdapter(projectRequest({ action: 'status' }), signal)); } catch (error) { return failure(error); } },
  });
  pi.registerTool({
    name: 'kanban_list', label: 'List Kanban work',
    exposure: nativeExposure ? 'deferred' : 'direct',
    description: 'List bounded card summaries. Use view.items_offset and returned paging metadata to recover the fetched list. Backend limit remains at most100. This is work state, not execution or proof authority.',
    parameters: Type.Object({ status: Type.Optional(Type.String()), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
      view: Type.Optional(viewSchema) }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      const { view, ...request } = params;
      try { return response(await callAdapter(projectRequest({ action: 'list', ...request }), signal),
        { ...view, selected_task_id: activeTask?.cardId }); } catch (error) { return failure(error); }
    },
  });
  pi.registerTool({
    name: 'kanban_show', label: 'Show Kanban work',
    exposure: nativeExposure ? 'deferred' : 'direct',
    description: 'Read a bounded card view with latest comments. Page body via view.body_offset; comments via before_id or comment_id plus offset; any top-level task_field via offset; relations via relation_offset. Reuse expected_reply_sha256 to reject changed-source cursors. Full host evidence remains separate.',
    parameters: Type.Object({ task_id: Type.String(), view: Type.Optional(viewSchema) }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      const { view, ...request } = params;
      try { return response(await callAdapter(projectRequest({ action: 'show', ...request }), signal), view); }
      catch (error) { return failure(error); }
    },
  });
  pi.registerTool({
    name: 'kanban_select', label: 'Select existing Kanban work',
    description: 'Select an existing card on the admitted project board. Selection persists on the native session branch. It does not grant execution permission or require planning advice.',
    parameters: Type.Object({ task_id: Type.String({ minLength: 1, maxLength: 128 }) }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      try {
        const project = activeProject;
        const value = await callAdapter(projectRequest({ action: 'show', task_id: params.task_id }), signal);
        if (activeProject !== project || (value.result as any)?.task?.id !== params.task_id) throw new Error('Project or task identity changed during selection');
        activeTask = { taskId: params.task_id, cardId: params.task_id };
        saveSelection();
        return response(value);
      } catch (error) { return failure(error); }
    },
  });
  pi.registerTool({
    name: 'kanban_create', label: 'Create Kanban work',
    exposure: nativeExposure ? 'deferred' : 'direct',
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
      transition: Type.Union(['specify', 'schedule', 'block', 'unblock', 'request_review', 'request_changes', 'reopen_review', 'complete', 'archive'].map(Type.Literal)),
      reason: Type.Optional(Type.String({ maxLength: 2000 })),
      summary: Type.Optional(Type.String({ maxLength: 4000 })),
    }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'move', ...params }), signal)); } catch (error) { return failure(error); } },
  });
  pi.registerTool({
    name: 'kanban_comment', label: 'Comment on Kanban work',
    exposure: nativeExposure ? 'deferred' : 'direct',
    description: 'Append one audit comment to a Pi Kanban card.',
    parameters: Type.Object({ task_id: Type.String(), comment: Type.String({ minLength: 1, maxLength: 8000 }) }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return response(await callAdapter(projectRequest({ action: 'comment', ...params }), signal)); } catch (error) { return failure(error); } },
  });

  pi.on('input', async () => {
    // New input does not silently switch projects or discard the selected work.
    pendingConsultations.clear();
    return { action: 'continue' };
  });

  pi.on('tool_call', async (event: any) => {
    if (event.toolName === 'project_create') { clearAdmission(); return; }
    if (event.toolName === 'codex_plan_consult') {
      if (!activeProject) return { block: true, reason: 'Admit the project with project_admit before planning consultation.' };
      if (!capabilitiesObserved) return { block: true, reason: 'Call agent_capabilities before planning so the plan uses the tools actually loaded in this Pi session.' };
      if (!systemToolsQueried) return { block: true, reason: 'Query system_tool_query for relevant capabilities before planning so existing tools and workflows are considered.' };
      if (!memoryQueried) return { block: true, reason: 'Search local Pi MemPalace for relevant validated lessons and recent session history before planning.' };
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
    if (!activeProject || !activeTask) return { block: true, reason: 'Admit the project and select its existing Kanban card before supervised execution. Planning advice is optional.' };
    if (!capabilitiesObserved || !systemToolsQueried || !memoryQueried || !knowledgeQueried) {
      const missing: string[] = [];
      if (!capabilitiesObserved) missing.push('agent_capabilities');
      if (!systemToolsQueried) missing.push('system_tool_query with relevant terms');
      if (!memoryQueried) missing.push('mcp__mempalace__mempalace_search or validated_memory_query with a relevant query');
      if (!knowledgeQueried) missing.push('project_knowledge_query with relevant terms');
      return { block: true, reason: 'Discovery is incomplete. Missing successful calls: ' + missing.join('; ')
        + '. project_prepare with an explicit relevant query can deliver the fixed read-only discovery set together; incomplete sections remain held'
        + '. Use tool_search to discover a missing tool and its actual argument schema, then call it. '
        + 'A search for a tool does not execute that tool. Completed observations remain recorded until project selection or session reload resets them.' };
    }
    const project = activeProject, task = activeTask;
    try {
      const shown = (await callAdapter(projectRequest({ action: 'show', task_id: task.cardId }))).result as any;
      if (shown?.task?.id !== task.cardId || !['ready', 'running'].includes(shown.task.status)) {
        return { block: true, reason: 'Selected card is not runnable. Select an authorized ready task.' };
      }
      if (!Array.isArray(shown.parents)) throw new Error('Missing prerequisite state');
      for (const id of shown.parents) {
        const prerequisite = (await callAdapter(projectRequest({ action: 'show', task_id: id }))).result as any;
        if (prerequisite?.task?.id !== id || !['done', 'archived'].includes(prerequisite.task.status)) {
          return { block: true, reason: 'Selected card has an unfinished prerequisite: ' + id };
        }
      }
      if (activeProject !== project || activeTask !== task) throw new Error('Selection changed during admission');
    } catch { return { block: true, reason: 'Cannot validate the selected card and its prerequisites. Inspect the project board before execution.' }; }
  });

  pi.on('tool_result', async (event: any, ctx: any) => {
    if (preparing.has(event.parentToolCallId)) return;
    if (event.toolName === 'project_create' && event.isError) { clearAdmission(); return; }
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
    if (event.toolName === 'system_tool_query' && !event.isError && event.details?.ok === true && Array.isArray(event.details?.results)) {
      systemToolsQueried = true;
      return;
    }
    if ((event.toolName === 'mcp__mempalace__mempalace_search'
          && successfulCanonicalMemorySearch(event)
        || event.toolName === 'validated_memory_query'
          && event.details?.schema === 'validated-memory-query/v1'
          && Array.isArray(event.details.results)
          && event.details.reason !== 'sensitive_query') && !event.isError) {
      memoryQueried = true;
      return;
    }
    if (event.toolName === 'kanban_create' && !event.isError && event.details?.ok === true) {
      const cardId = event.details?.result?.task?.id;
      if (activeProject && !activeTask && typeof cardId === 'string' && cardId) {
        activeTask = { taskId: cardId, cardId };
        saveSelection();
      }
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
        saveSelection();
      } catch {
        activeTask = null;
        boardAdmissionFailed = true;
        saveSelection();
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
