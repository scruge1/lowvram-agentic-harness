import { readFileSync, realpathSync, statSync, existsSync, openSync, readSync, closeSync } from 'node:fs';
import { basename, dirname, join, relative, resolve, sep } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { Type } from 'typebox';
import { loadProjectContextFiles } from '@earendil-works/pi-coding-agent';
import { homedir } from 'node:os';
import { resolveReadPath, ensureTool } from './project-context-runtime.ts';

// Reviewed parent SHA-256: e3d78ae27011f582299199aae6c931304bb697c76dae02f11b52d9ebe773dbe5.

type Project = { root: string; projectId: string; boardId: string };
type Document = { path: string; role: string; text: string; sha256: string; source_bytes: number; excerpt: boolean;
  range?: { start: number; end: number; total: number }; window_sha256?: string };
type View = { root: string; directory: string; documents: Document[] };
const EXECUTION = new Set(['workflow_step', 'run_step', 'run_ledger', 'write', 'edit', 'task_agent']);
const digest = (value: string) => createHash('sha256').update(value).digest('hex');
const within = (root: string, file: string) => file === root || file.startsWith(root + sep);
const MAX_RETURN_BYTES = 32768;
const POLICY = 'Project context: use project_context for the relevant directory before project work. It reads current applicable instructions and a bounded checkpoint head; it does not grant execution authority. Native-injected or previously delivered unchanged sources count. Do not load unrelated topic trees or the full historical archive.';
const ROUTE_FILES = new Set(['AGENTS.override.md', 'AGENTS.md', 'AGENTS.MD', 'CLAUDE.md', 'CLAUDE.MD',
  'PROJECT-SSOT.md', 'ACTIVE-CHECKPOINT.md', 'TARGET-PROVENANCE.json']);

// Resolve existing ancestors first so missing output directories cannot conceal a symlink escape.
function canonical(file: string): string {
  if (existsSync(file)) return realpathSync(file);
  const parent = dirname(file);
  if (parent === file) throw new Error('Path has no existing ancestor');
  return join(canonical(parent), file.slice(parent.length + (parent.endsWith(sep) ? 0 : 1)));
}

function directory(file: string): string {
  let current = file;
  while (!existsSync(current)) current = dirname(current);
  return statSync(current).isDirectory() ? current : dirname(current);
}

function snapshot(project: Project, target: string): View {
  const root = realpathSync(project.root);
  const identity = JSON.parse(readFileSync(join(root, '.icm/project.json'), 'utf8'));
  if (identity.project_id !== project.projectId || identity.board_id !== project.boardId
      || realpathSync(identity.canonical_root) !== root) throw new Error('Admitted project identity changed');
  const scope = canonical(target);
  if (!within(root, scope)) throw new Error('Target is outside the admitted project; select its owning project');
  const cwd = directory(scope);
  const workspace = canonical(resolve(root, identity.workspace_path));
  if (!within(root, workspace)) throw new Error('Workspace route escapes the admitted project');
  const documents: Document[] = [];
  const add = (path: string, role: string, head = false) => {
    const file = realpathSync(path);
    if (!within(root, file)) throw new Error('Instruction route escapes the admitted project');
    if (documents.some(d => d.path === file)) return;
    const size = statSync(file).size;
    let bytes: Buffer;
    if (head) {
      const fd = openSync(file, 'r');
      try {
        const buffer = Buffer.alloc(4099); //4KiB plus a possible UTF-8 BOM.
        bytes = buffer.subarray(0, readSync(fd, buffer, 0, buffer.length, 0));
      } finally { closeSync(fd); }
    } else bytes = readFileSync(file);
    const full = (head ? new TextDecoder('utf-8', { ignoreBOM: true }).decode(bytes, { stream: true }) : bytes.toString('utf8')).replace(/^\uFEFF/, '');
    let text = full;
    if (head) {
      const lines = full.split('\n').slice(0, 64).join('\n');
      text = new TextDecoder('utf-8', { ignoreBOM: true }).decode(Buffer.from(lines).subarray(0, 4096), { stream: true });
    }
    documents.push({ path: file, role, text, sha256: digest(text), source_bytes: size,
      excerpt: bytes.length < size || text !== full });
  };
  // Use Pi's own ancestor/override/CLAUDE selection. Do not scan descendant or sibling topics.
  for (const item of loadProjectContextFiles({ cwd, agentDir: process.env.PI_CODING_AGENT_DIR || join(homedir(), '.pi/agent') })) {
    const file = realpathSync(item.path);
    if (within(root, resolve(item.path))) add(file, 'directory-instructions');
  }
  add(join(workspace, 'AGENTS.md'), 'workspace-instructions');
  add(join(workspace, 'PROJECT-SSOT.md'), 'workspace-router');
  add(join(workspace, 'ACTIVE-CHECKPOINT.md'), 'current-checkpoint-head', true);
  return { root, directory: cwd, documents };
}

export function registerProjectContext(pi: any, bindings: { project(): Project | null }) {
  // Ephemeral delivery evidence. Existing Pi project/card entries remain the only saved identity.
  const delivered = new Map<string, string>();
  const coverage = new Map<string, { sha256: string; next: number }>();
  const pending = new Map<string, { root: string; text: string; documents: Document[]; valid?: () => boolean }>();
  let suggested: { root: string; path: string } | undefined;
  const reset = () => { delivered.clear(); coverage.clear(); pending.clear(); suggested = undefined; };
  pi.on('session_start', reset);
  pi.on('session_tree', reset);
  pi.on('session_compact', reset);
  const key = (root: string, file: string) => root + '\0' + file;
  const missing = (view: View, ctx: any) => {
    const prompt = ctx.getSystemPrompt?.() ?? '';
    return view.documents.filter(doc => {
      // Count native-injected instructions only when both their locator and exact current bytes exist.
      if (doc.role === 'directory-instructions' && prompt.includes(doc.path) && prompt.includes(doc.text)) return false;
      return delivered.get(key(view.root, doc.path)) !== doc.sha256;
    });
  };
  const fail = (error: unknown) => ({ isError: true, content: [{ type: 'text',
    text: 'Project context unavailable: ' + String(error) }], details: { ok: false } });

  pi.registerTool({
    name: 'project_context', label: 'Read applicable project context',
    description: 'Read missing current project instructions before work in a directory. Uses admitted identity, native ancestor rules, workspace router and at most64lines/4KiB of checkpoint. Instruction documents are delivered in bounded source-hashed windows; call again for remaining_reads after the result reaches model context. Other topics stay unloaded. Instructions above128KiB require a maintained thin router; inspection stays available. No permission or completion authority.',
    parameters: Type.Object({ path: Type.Optional(Type.String({ minLength: 1, maxLength: 4096 })) }, { additionalProperties: false }),
    async execute(id: string, params: any, _signal: any, _update: any, ctx: any) {
      try {
        const project = bindings.project();
        if (!project) throw new Error('Use project_admit to select an existing project first');
        const requested = params.path ?? (suggested?.root === project.root ? suggested.path : project.root);
        const target = resolveReadPath(requested, project.root);
        const view = snapshot(project, target);
        const required = missing(view, ctx);
        let used = 1024 + Buffer.byteLength(view.root + view.directory);
        const selected: Document[] = [];
        const remaining: string[] = [];
        for (const doc of required) {
          const bytes = Buffer.from(doc.text);
          if (doc.role !== 'current-checkpoint-head' && bytes.length > 131072) {
            throw new Error('Instruction exceeds128KiB: ' + doc.path + '. Inspect it in native read windows and compile a maintained thin router before project execution; do not repeatedly retry this route.');
          }
          let part = doc;
          if (bytes.length > 8192 || Buffer.byteLength(JSON.stringify(doc)) > 16384) {
            const prior = coverage.get(key(view.root, doc.path));
            const start = prior?.sha256 === doc.sha256 ? prior.next : 0;
            let width = Math.min(8192, bytes.length - start);
            do {
              const text = new TextDecoder('utf-8', { ignoreBOM: true }).decode(bytes.subarray(start, start + width), { stream: start + width < bytes.length });
              part = { ...doc, text, range: { start, end: start + Buffer.byteLength(text), total: bytes.length },
                window_sha256: digest(text) };
              width = Math.floor(width / 2);
            } while (Buffer.byteLength(JSON.stringify(part)) > 16384 && width > 0);
          }
          const size = Buffer.byteLength(JSON.stringify(part)) + 1;
          if (used + size > MAX_RETURN_BYTES) remaining.push(doc.path);
          else {
            selected.push(part); used += size;
            if (part.range && part.range.end < part.range.total) remaining.push(doc.path);
          }
        }
        const value = { ok: true, root: view.root, scope: view.directory,
          applicability: 'Directory instructions apply only in their directory subtree. Workspace routes apply to this admitted project. Earlier topic context does not apply to unrelated siblings.',
          documents: selected, remaining_reads: remaining,
          limits: 'Source delivery at the context hook, not final-provider attestation. Range sha256 identifies the complete normalized instruction; window_sha256 identifies returned bytes. Checkpoint is a bounded head. Existing task, pause, skill and action checks still apply.' };
        let text = JSON.stringify(value);
        while (Buffer.byteLength(text) > MAX_RETURN_BYTES && selected.length) {
          remaining.unshift(selected.pop()!.path);
          text = JSON.stringify(value);
        }
        if (Buffer.byteLength(text) > MAX_RETURN_BYTES) throw new Error('Context route list exceeds32KiB; inspect the nearest instruction files directly');
        pending.set(id, { root: view.root, text, documents: selected });
        while (pending.size > 64) pending.delete(pending.keys().next().value!);
        suggested = { root: project.root, path: view.directory };
        return { content: [{ type: 'text', text }], details: value };
      } catch (error) { return fail(error); }
    },
  });

  pi.on('tool_result', (event: any, ctx: any) => {
    if (event.toolName !== 'read' || event.isError || !bindings.project()) return;
    const text = event.content?.length === 1 && event.content[0].type === 'text' ? event.content[0].text : undefined;
    if (typeof text !== 'string' || typeof event.input?.path !== 'string') return;
    try {
      const project = bindings.project()!;
      const file = realpathSync(resolveReadPath(event.input.path, ctx.cwd));
      if (!within(realpathSync(project.root), file)) return;
      const view = snapshot(project, file);
      const docs = view.documents.filter(doc => doc.path === file &&
        (doc.excerpt ? text.startsWith(doc.text) : text.replace(/^\uFEFF/, '') === doc.text));
      if (docs.length) {
        pending.set(event.toolCallId, { root: view.root, text, documents: docs });
        while (pending.size > 64) pending.delete(pending.keys().next().value!);
      }
    } catch { /* Failed, unrelated or partial reads cannot establish delivery. */ }
  });

  pi.on('context', (event: any) => {
    const project = bindings.project();
    if (!project) return;
    let root: string;
    try { root = realpathSync(project.root); } catch { return; }
    // A result must reach a later model-input context. Merely executing a read in the
    // same tool-call batch must not unlock a sibling action in that batch.
    for (const message of event.messages) {
      if (message.role !== 'toolResult') continue;
      const proof = pending.get(message.toolCallId);
      if (!proof || proof.root !== root) continue;
      pending.delete(message.toolCallId);
      try { if (proof.valid && !proof.valid()) continue; } catch { continue; }
      const text = message.content?.length === 1 && message.content[0].type === 'text' ? message.content[0].text : undefined;
      if (!message.isError && text === proof.text) {
        for (const doc of proof.documents) {
            // A source can change between tool execution and delivery.
            let current: Document | undefined;
            try { current = snapshot(project, doc.path).documents.find(value => value.path === doc.path); }
            catch { continue; }
            if (current?.sha256 !== doc.sha256) continue;
          const id = key(root, doc.path);
          if (doc.range) {
            const previous = coverage.get(id);
            const next = previous?.sha256 === doc.sha256 ? previous.next : 0;
            if (doc.range.start !== next) continue;
            coverage.set(id, { sha256: doc.sha256, next: doc.range.end });
            while (coverage.size > 64) coverage.delete(coverage.keys().next().value!);
            if (doc.range.end !== doc.range.total) continue;
          }
          delivered.set(id, doc.sha256); coverage.delete(id);
          while (delivered.size > 256) delivered.delete(delivered.keys().next().value!);
        }
      }
    }
  });

  pi.on('before_agent_start', (event: any) => {
    const project = bindings.project();
    if (!project || event.systemPrompt.includes(POLICY)) return;
    return { systemPrompt: event.systemPrompt + '\n' + POLICY };
  });

  pi.on('tool_call', async (event: any, ctx: any) => {
    const project = bindings.project();
    if (!project) return; // Existing intake/selection gates own admission before a project is selected.
    const execution = EXECUTION.has(event.toolName);
    const reading = ['read', 'grep'].includes(event.toolName);
    if (!execution && !reading) return;
    try {
      const root = realpathSync(project.root);
      const targets: string[] = [];
      if (reading || ['write', 'edit'].includes(event.toolName)) {
        const inputPath = event.input?.path ?? (event.toolName === 'grep' ? ctx.cwd : undefined);
        if (typeof inputPath !== 'string') return;
        const file = canonical(resolveReadPath(inputPath, ctx.cwd));
        if (!within(root, file) && reading) return; // Global inspection remains available.
        // Route inspection must work even when identity or another route is broken.
        if (event.toolName === 'read' && (ROUTE_FILES.has(basename(file))
            || file === join(root, '.icm/project.json'))) return;
        targets.push(file);
        if (event.toolName === 'grep' && statSync(file).isDirectory()) {
          const rg = await ensureTool('rg');
          if (!rg) throw new Error('Native ripgrep unavailable; narrow inspection to a file');
          const args = ['--no-config', '--files', '--hidden', '-0'];
          if (event.input?.glob) args.push('--glob', event.input.glob);
          args.push('--', file);
          let names = '';
          try { names = execFileSync(rg, args, { encoding: 'utf8', timeout: 2000, maxBuffer: 1024 * 1024 }); }
          catch (error: any) {
            if (error.status !== 1 || String(error.stdout ?? '').length) throw new Error('Search scope is too broad or unavailable; use find for filenames, then grep a file or narrower directory');
          }
          // File names only, using the same ignore/glob rules as native grep. No sibling
          // instructions are injected or preloaded into model context by this check.
          const dirs = [...new Set(names.split('\0').filter(Boolean).map(name => dirname(canonical(name))))];
          if (dirs.length > 256) throw new Error('Search spans more than256directories; use find for filenames and narrow to the relevant topic');
          targets.push(...dirs);
        }
      } else {
        const cwd = canonical(resolve(event.toolName === 'task_agent' ? ctx.cwd : event.input?.cwd ?? process.cwd()));
        targets.push(cwd);
        if (Array.isArray(event.input?.outputs)) {
          for (const file of event.input.outputs) targets.push(canonical(resolve(cwd, file)));
        }
      }
      for (const target of targets) {
        const view = snapshot(project, target);
        // The instruction files themselves remain readable to resolve the gate.
        if (event.toolName === 'read' && view.documents.some(doc => doc.path === target)) continue;
        const absent = missing(view, ctx);
        if (!absent.length) continue;
        suggested = { root: project.root, path: view.directory };
        return { block: true, reason: 'Read current applicable project context with project_context({path:'
          + JSON.stringify(view.directory) + '}) before this work. Missing or changed sources: '
          + absent.map(doc => relative(root, doc.path)).join(', ')
          + '. A path-only hit, partial read, or read in this same tool-call batch does not count. Inspection of the instruction files remains available.' };
      }
    } catch (error) {
      return { block: true, reason: 'Project context check failed: ' + String(error).slice(0, 600)
        + '. Inspect identity/routes with native read-only tools; do not reset the board or invent context.' };
    }
  });
  return {
    // Native nested results have no separate transcript message. Bind only exact
    // returned child bytes to their actual enclosing result, without marking delivery.
    enclose(childId: string, parentId: string, childText: string, parentText: string, valid: () => boolean) {
      const proof = pending.get(childId);
      pending.delete(childId);
      if (!proof || proof.text !== childText || !bindings.project()
          || proof.root !== bindings.project()!.root) return false;
      pending.set(parentId, { ...proof, text: parentText, valid });
      return true;
    },
  };
}
