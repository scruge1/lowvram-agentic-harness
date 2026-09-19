import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { execFile } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';

// Admission adapter only. The existing portable supervisor owns acceptance.
export default function (pi: ExtensionAPI) {
  let nativeDiscoveryReady = false;
  const loadedSkills = new Map<string, string>();
  let pendingFailure: string | undefined;
  const skillRoot = path.join(homedir(), '.pi/agent/skills');
  const skillPath = (name: string) => {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(name)) throw new Error('Invalid skill name');
    const root = fs.realpathSync(skillRoot);
    const file = fs.realpathSync(path.join(root, name, 'SKILL.md'));
    if (!file.startsWith(root + path.sep)) throw new Error('Skill path escapes installed skill directory');
    return file;
  };
  const missingSkills = (input: any) => {
    const names = ['supervised-tasks', ...(input.required_skills ?? [])];
    return [...new Set(names)].filter((name: string) => {
      try {
        const file = skillPath(name);
        return loadedSkills.get(file) !== createHash('sha256').update(fs.readFileSync(file)).digest('hex');
      } catch { return true; }
    });
  };
  const enableInspectionTools = () => {
    const available = new Set(pi.getAllTools().map((tool) => tool.name));
    const active = new Set(pi.getActiveTools());
    for (const name of ['ls', 'find', 'grep']) {
      if (available.has(name)) active.add(name);
    }
    pi.setActiveTools([...active]);
  };
  const base = path.dirname(fileURLToPath(import.meta.url));
  const configuration = JSON.parse(fs.readFileSync(path.join(base, 'everyday-runtime.json'), 'utf8'));
  const helper = path.join(base, 'everyday_workflow.py');
  const hash = createHash('sha256').update(fs.readFileSync(helper)).digest('hex');
  if (hash !== configuration.helper_sha256) throw new Error('Everyday workflow source drift');

  pi.registerTool({
    name: 'workflow_step', label: 'Supervised workflow step',
    description: 'Execute one planned file-work action through the portable supervisor. First discover native capabilities and read the matching skill for specialized tools. Supply a short goal, existing working directory, argv action, read-only argv verifier and relative output files. Verifier must use relative output paths: it is also run in an empty directory as a negative control. Use the installed tool environment from the skill, not a guessed Python. Host records plan, negative control and verified receipt. No automatic action replay. Passed predicate is not universal task correctness or permission for physical/privileged actions.',
    parameters: Type.Object({ objective: Type.String(), cwd: Type.String(),
      action: Type.Array(Type.String()), verify: Type.Array(Type.String()),
      outputs: Type.Array(Type.String()),
      required_skills: Type.Optional(Type.Array(Type.String({ description: 'Installed skill names required for specialized work; read each SKILL.md fully first.' }))) }),
    async execute(_id: string, params: any, signal?: AbortSignal) {
      if (signal?.aborted) return { content: [{ type: 'text', text: 'Cancelled before execution.' }], details: { ok: false } };
      const result = await new Promise<{ rc: number; out: string; error: string }>((resolve) => {
        const child = execFile(configuration.python, ['-B', helper, configuration.runtime,
          configuration.runtime_manifest_sha256, configuration.engine_sha256, '--interactive-owner'],
          { env: { PATH: process.env.PATH || '', LANG: process.env.LANG || 'C.UTF-8' },
            maxBuffer: 1024 * 1024 }, (error, stdout, stderr) => {
              clearTimeout(deadline);
              signal?.removeEventListener('abort', cancel);
              resolve({ rc: error ? Number((error as any).code) || 1 : 0,
                        out: stdout, error: stderr });
          });
        // Closing the ownership pipe asks the host to stop its owned processes.
        const cancel = () => child.stdin?.end();
        const deadline = setTimeout(cancel, 780000);
        signal?.addEventListener('abort', cancel, { once: true });
        child.stdin?.on('error', () => cancel());
        child.stdin?.write(JSON.stringify(params) + '\n');
        if (signal?.aborted) cancel();
      });
      let record: any;
      try { record = JSON.parse(result.out); }
      catch { record = { status: 'failed', authority: 'none', reason: result.error || 'Missing host result' }; }
      const ok = result.rc === 0 && record.status === 'supplied_predicate_passed' && !signal?.aborted;
      return { content: [{ type: 'text', text: JSON.stringify(record) }], details: { ok, host: record }, isError: !ok };
    },
  });

  pi.on('before_agent_start', async (event) => {
    nativeDiscoveryReady = false;
    enableInspectionTools();
    return {
    systemPrompt: event.systemPrompt + '\nEveryday work: answer questions and inspect with native read-only tools directly. For file-changing project work, use workflow_step: short goal, target directory, argv action, read-only argv check, declared outputs. The host manages records and hashes. Do not ask Adam to sign or manage task files. Work one useful operation at a time. Failed or uncertain actions are not replayed automatically; inspect evidence before proposing a correction. Existing physical-action, credential and privilege approvals still apply. Tasks needing browser/MCP tools or long-context workers retain their dedicated reviewed harness route; do not fake them with a shell substitute.'
    };
  });
  pi.on('session_start', async () => {
    nativeDiscoveryReady = false;
    loadedSkills.clear();
    enableInspectionTools();
  });
  pi.on('tool_result', async (event: any, ctx: any) => {
    if (event.toolName === 'workflow_step' && event.details?.ok === false) {
      const host = event.details?.host;
      if (host?.task_root && /^[a-f0-9]{32}$/.test(host.run_id ?? '')) {
        pendingFailure = path.join(host.task_root, '.enforcement/runs', host.run_id, 'final.json');
      }
    }
    if (event.toolName === 'read' && !event.isError && !event.details?.truncation
        && event.input?.offset === undefined && event.input?.limit === undefined) {
      try {
        const file = fs.realpathSync(path.resolve(ctx.cwd ?? process.cwd(), event.input.path));
        const bytes = fs.readFileSync(file);
        const complete = Array.isArray(event.content) && event.content.length === 1
          && event.content[0].type === 'text' && event.content[0].text === bytes.toString('utf8');
        if (pendingFailure && complete && file === fs.realpathSync(pendingFailure)) pendingFailure = undefined;
        const root = fs.realpathSync(skillRoot);
        if (file.startsWith(root + path.sep) && path.basename(file) === 'SKILL.md') {
          const bytes = fs.readFileSync(file);
          if (Array.isArray(event.content) && event.content.length === 1
              && event.content[0].type === 'text' && event.content[0].text === bytes.toString('utf8')) {
            loadedSkills.set(file, createHash('sha256').update(bytes).digest('hex'));
          } else {
            loadedSkills.delete(file);
          }
        }
      } catch { /* An unavailable read cannot admit a skill. */ }
    }
    if (event.toolName === 'agent_capabilities') {
      nativeDiscoveryReady = !event.isError && event.details?.ok === true;
      const snapshot = event.details?.snapshot;
      if (nativeDiscoveryReady && snapshot?.schema === 'pi-native-capabilities/v1'
          && Array.isArray(snapshot.configured_tools)) {
        const view = { schema: 'pi-capability-summary/v1', session_id: snapshot.session_id,
          observed_at: snapshot.observed_at,
          active_tools: snapshot.configured_tools.filter((tool: any) => tool.active).map((tool: any) => tool.name),
          inactive_tools: snapshot.configured_tools.filter((tool: any) => !tool.active).map((tool: any) => tool.name),
          limits: 'Registry activity only, not health. Full host snapshot retained in result details.' };
        return { content: [{ type: 'text', text: JSON.stringify(view) }],
          details: { ...event.details,
            original_content_sha256: createHash('sha256').update(JSON.stringify(event.content)).digest('hex'),
            model_view: 'compact_registry' } };
      }
    }
  });
  pi.on('tool_call', async (event) => {
    if (pendingFailure && ['workflow_step', 'run_step', 'run_ledger'].includes(event.toolName)) {
      return { block: true, reason: 'Inspect the complete saved failure record before another workflow action: ' + pendingFailure + '. Preserve the failed attempt; a changed command is not automatic recovery.' };
    }
    if (event.toolName === 'workflow_step' && !nativeDiscoveryReady) {
      return { block: true, reason: 'Call native agent_capabilities first. A successful native registry result is required; shell commands and remembered tools do not establish readiness.' };
    }
    if (event.toolName === 'workflow_step') {
      const missing = missingSkills(event.input);
      if (missing.length) return { block: true, reason: 'Read the complete installed SKILL.md for: ' + missing.join(', ') + '. Missing, partial or changed skill bytes do not satisfy workflow admission.' };
    }
    if (event.toolName === 'bash') {
      return { block: true, reason: 'Use native read/ls/find/grep for inspection. For execution use workflow_step with declared file outputs, or the existing run_step/run_ledger action+verify route. A prior successful check does not admit an unrelated raw shell action.' };
    }
    if (['write', 'edit'].includes(event.toolName)) {
      return { block: true, reason: 'Use workflow_step for planned file work with its verifier and declared outputs. Use native read-only tools for inspection. Do not bypass the existing supervisor.' };
    }
  });
}
