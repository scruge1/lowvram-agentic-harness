// Read-only projection of the native Pi journal and the admitted project board.
// Prerequisites constrain selection; they never grant containment or execution scope.
import { packetDigest } from './packet-digest.ts';
type Work = { root: string; task: string; source: string };
type Project = { root: string; projectId: string; boardId: string };
const TERMINAL = new Set(['done', 'archived']);
export const workKey = (work: Work) => JSON.stringify([work.root, work.task, work.source]);

export function nativeCompletionOrder(branch: any[]) {
  const calls = new Map<string, any>();
  const order = new Map<string, { ordinal: number; row_sha256: string }>();
  for (const [ordinal, entry] of branch.entries()) {
    if (entry.type !== 'message') continue;
    const message = entry.message;
    if (message?.role === 'assistant' && Array.isArray(message.content))
      for (const call of message.content) if (call.type === 'toolCall' && call.name === 'kanban_move') calls.set(call.id, call.arguments);
    if (message?.role !== 'toolResult' || message.toolName !== 'kanban_move' || message.isError
        || message.details?.ok !== true) continue;
    const input = calls.get(message.toolCallId), task = message.details.result?.task;
    if (!input || input.task_id !== task?.id) continue;
    order.delete(task.id); // A later native state change invalidates an earlier completion witness.
    if (input.transition === 'complete' && TERMINAL.has(task.status))
      order.set(task.id, { ordinal, row_sha256: packetDigest(task) });
  }
  return order;
}

export async function cancelledSelection(view: {
  project: Project; selected: string; queue: Work[]; authorized: Set<string>;
  order: Map<string, number>; excluded: (Work & { cancel_order: number })[];
  call: (request: Record<string, unknown>, signal?: AbortSignal) => Promise<any>;
}) {
  const cancelled = view.excluded.filter(x => x.root === view.project.root);
  if (!cancelled.length) return null;
  if (cancelled.length > 128) throw new Error('Cancelled-scope lookup exceeds its bound');
  const latest = new Map<string, number>();
  for (const [key, ordinal] of view.order) if (view.authorized.has(key)) {
    const [root, task] = JSON.parse(key);
    if (root === view.project.root) latest.set(task, Math.max(latest.get(task) ?? -1, ordinal));
  }
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), 10000);
  const trees = new Map<string, Set<string>>();
  const contains = async (root: string) => {
    if (root === view.selected) return true;
    if (!trees.has(root)) {
      if (controller.signal.aborted) throw new Error('Cancelled-scope lookup deadline reached');
      const result = await view.call({ action: 'hierarchy', project_root: view.project.root,
        task_id: root, depth: 12 }, controller.signal);
      if (result?.ok !== true || !result.result?.root || result.result.truncated)
        throw new Error('Cannot establish complete cancelled decomposition scope');
      const ids = new Set<string>();
      const visit = (node: any) => { ids.add(node.id); for (const child of node.children ?? []) visit(child); };
      visit(result.result.root); trees.set(root, ids);
    }
    return trees.get(root)!.has(view.selected);
  };
  try {
    for (const cancelledRoot of cancelled) {
      const fresh = view.queue.filter(work => work.root === view.project.root
        && view.authorized.has(workKey(work)) && (latest.get(work.task) ?? -1) > cancelledRoot.cancel_order);
      if (fresh.some(work => work.task === view.selected)) continue;
      if (!(await contains(cancelledRoot.task))) continue;
      let readmitted = false;
      for (const work of fresh) if (await contains(work.task)) { readmitted = true; break; }
      if (!readmitted) return cancelledRoot.task;
    }
    return null;
  } finally { clearTimeout(deadline); }
}

export async function buildRetainedPacket(view: {
  state: any; project: Project | null; selected: string | null; admissionFailed: boolean;
  pending: string[]; authorized: Set<string>; excluded: (Work & { cancel_order: number })[];
  authorizationOrder: Map<string, number>;
  completionOrder: Map<string, { ordinal: number; row_sha256: string }>;
  call: (request: Record<string, unknown>, signal?: AbortSignal) => Promise<any>;
}) {
  const root = view.project?.root ?? process.cwd();
  const reason = [...view.state.reason].length > 3072
    ? [...view.state.reason].slice(0, 3000).join('') + ' [reason abbreviated; full native reason retained]' : view.state.reason;
  const packet: any = { schema: 'pi-retained-work-decision/v2', version: 2,
    project_root: root, mode: view.state.mode, reason,
    pending_inputs: [...view.pending].sort(), coverage: { complete: true, truncated: false, missing: [] },
    anchors: [], tasks: [], prerequisite_status: {},
    excluded: view.excluded.filter(x => x.root === root).map(({ task, source }) => ({ task, source })),
    selected_task: view.selected,
    waiting_tasks: [...new Set((view.state.task_waits ?? []).filter((w: any) => w.root === root && w.status === 'waiting').map((w: any) => w.task))].sort(),
    session_wait: view.state.mode === 'waiting' && !!view.state.wait };
  const missing = new Set<string>();
  const shown = new Map<string, any>();
  const tasks = new Map<string, any>();
  const latestBinding = new Map<string, { task: string; source: string; ordinal: number }>();
  const sourceOrder = new Map<string, number>();
  for (const [key, ordinal] of view.authorizationOrder) if (view.authorized.has(key)) {
    const [workRoot, task, source] = JSON.parse(key);
    sourceOrder.set(source, ordinal);
    if (workRoot === root && ordinal > (latestBinding.get(task)?.ordinal ?? -1)) latestBinding.set(task, { task, source, ordinal });
  }
  const explicitSources = new Map<string, string>();
  for (const work of view.state.queue as Work[]) if (work.root === root && view.authorized.has(workKey(work)))
    explicitSources.set(work.task, latestBinding.get(work.task)?.source ?? work.source);
  const project = view.project;
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), 30000);
  let reads = 0;
  const read = async (args: Record<string, unknown>) => {
    if (controller.signal.aborted || ++reads > 450) throw new Error('Retained board projection limit reached');
    const result = await view.call({ ...args, project_root: root }, controller.signal);
    if (result?.ok !== true) throw new Error('Retained board read failed');
    return result.result;
  };
  const show = async (id: string) => {
    if (shown.has(id)) return shown.get(id);
    const result = await read({ action: 'show', task_id: id });
    if (result?.task?.id !== id || !Array.isArray(result.parents)) throw new Error('Malformed retained card readback');
    shown.set(id, result);
    return result;
  };
  try {
    if (view.admissionFailed && !view.pending.length) throw new Error('Current project admission is not qualified');
    if (view.admissionFailed) missing.add('project-admission');
    if (view.state.queue.length > 128) { packet.coverage.truncated = true; missing.add('anchor-limit'); }
    for (const item of view.state.queue.slice(0, 128) as Work[]) {
      if (!project || item.root !== root) { missing.add('other-project:' + item.root + ':' + item.task); continue; }
      if (!view.authorized.has(workKey(item))) { missing.add('native-source:' + item.task); continue; }
      packet.anchors.push({ task: item.task, source: explicitSources.get(item.task) ?? item.source });
      const hierarchy = await read({ action: 'hierarchy', task_id: item.task, depth: 12 });
      if (!hierarchy?.root || hierarchy.root.id !== item.task) throw new Error('Malformed retained hierarchy');
      if (hierarchy.truncated) { packet.coverage.truncated = true; missing.add('hierarchy:' + item.task); }
      const visit = async (node: any, parent: string | null, ancestors: Set<string>, inheritedSource: string) => {
        if (tasks.size >= 200) { packet.coverage.truncated = true; missing.add('node-limit'); return; }
        if (ancestors.has(node.id)) throw new Error('Cyclic retained hierarchy');
        if (tasks.has(node.id)) {
          const prior = tasks.get(node.id);
          // An explicitly retained descendant can also appear under its retained root.
          if (parent && prior.parent && prior.parent !== parent) throw new Error('Conflicting decomposition parent');
          if (parent && !prior.parent) prior.parent = parent;
          return;
        }
        if (!Array.isArray(node.child_ids) || !Array.isArray(node.children)
            || !Array.isArray(node.prerequisites)) throw new Error('Malformed decomposition node');
        if (node.child_ids.length !== node.children.length) { packet.coverage.truncated = true; missing.add('children:' + node.id); }
        const actual = await show(node.id);
        if (actual.task.status !== node.status
            || JSON.stringify([...actual.parents].sort()) !== JSON.stringify([...node.prerequisites].sort()))
          throw new Error('Board changed during hierarchy projection');
        const value = { id: node.id, project_root: root, status: actual.task.status,
          source: explicitSources.get(node.id) ?? inheritedSource, parent, prerequisites: [...actual.parents].sort(),
          priority: Number.isInteger(actual.task.priority) ? actual.task.priority : 0,
          integration_known: false, integration_invalidated: false, integration_complete: false };
        tasks.set(node.id, value);
        for (const child of node.children) await visit(child, node.id, new Set([...ancestors, node.id]), value.source);
      };
      await visit(hierarchy.root, null, new Set(), explicitSources.get(item.task) ?? item.source);
    }
    for (const cancelled of view.excluded.filter(x => x.root === root && tasks.size > 0)) {
      const tree = await read({ action: 'hierarchy', task_id: cancelled.task, depth: 12 });
      if (!tree?.root) throw new Error('Cannot inspect cancelled retained hierarchy');
      const ids = new Set<string>();
      const collect = (node: any) => { ids.add(node.id); for (const child of node.children ?? []) collect(child); };
      collect(tree.root);
      if (tree.truncated) { packet.coverage.truncated = true; missing.add('cancelled-hierarchy:' + cancelled.task); }
      for (const task of tasks.values()) if ((ids.has(task.id) || tree.truncated)
          && (sourceOrder.get(task.source) ?? -1) <= cancelled.cancel_order
          && !packet.excluded.some((x: any) => x.task === task.id && x.source === task.source))
        packet.excluded.push({ task: task.id, source: task.source });
    }
    for (const task of tasks.values()) {
      packet.prerequisite_status[task.id] = task.status;
      for (const id of task.prerequisites) {
        if (packet.prerequisite_status[id]) continue;
        try { packet.prerequisite_status[id] = (await show(id)).task.status; }
        catch { missing.add('prerequisite:' + id); }
      }
    }
    const descendants = (id: string, seen = new Set<string>()): any[] => {
      if (seen.has(id)) throw new Error('Cyclic projected containment');
      const children = [...tasks.values()].filter(x => x.parent === id);
      return children.flatMap(x => [x, ...descendants(x.id, new Set([...seen, id]))]);
    };
    for (const task of tasks.values()) {
      const children = descendants(task.id);
      if (!TERMINAL.has(task.status)) continue;
      task.integration_complete = true;
      if (!children.length) { task.integration_known = true; continue; }
      if (children.some(x => !TERMINAL.has(x.status))) {
        task.integration_known = true; task.integration_invalidated = true; task.integration_complete = false; continue;
      }
      const completed = shown.get(task.id)?.task.completed_at;
      const childTimes = children.map(x => shown.get(x.id)?.task.completed_at);
      // Equal or absent coarse timestamps cannot prove post-child integration.
      task.integration_known = typeof completed === 'number' && childTimes.every(t => typeof t === 'number' && completed > t);
      if (!task.integration_known) {
        const witnessed = [task, ...children].map(value => {
          const entry = view.completionOrder.get(value.id);
          return entry && entry.row_sha256 === packetDigest(shown.get(value.id).task) ? entry.ordinal : null;
        });
        if (witnessed.every(value => value !== null)) {
          task.integration_known = true;
          task.integration_invalidated = witnessed.slice(1).some(value => value! >= witnessed[0]!);
          task.integration_complete = !task.integration_invalidated;
        }
      }
    }
    packet.tasks = [...tasks.values()].sort((a, b) => a.id.localeCompare(b.id));
    // Wait tickets are bound to the original source, not a later reauthorisation.
    packet.waiting_tasks = [...new Set((view.state.task_waits ?? []).filter((w: any) =>
      w.root === root && w.status === 'waiting' && tasks.get(w.task)?.source === w.source).map((w: any) => w.task))].sort();
    packet.anchors.sort((a: any, b: any) => a.task.localeCompare(b.task) || a.source.localeCompare(b.source));
    packet.coverage.missing = [...missing].sort();
    packet.coverage.complete = !packet.coverage.truncated && missing.size === 0;
    return packet;
  } finally { clearTimeout(deadline); }
}
