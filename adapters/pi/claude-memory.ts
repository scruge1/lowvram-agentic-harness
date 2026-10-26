/** Home-owned Claude-mem hooks. A package listing is not capture acceptance. */
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { spawn } from 'node:child_process';

export default function (pi: ExtensionAPI) {
  const home = process.env.AGENT_HOME;
  const python = process.env.AGENT_HOME_PYTHON;
  if (!home || !python) throw new Error('AGENT_HOME and AGENT_HOME_PYTHON are required for memory hooks');
  let errorText = '';
  let serial: Promise<unknown> = Promise.resolve();
  let run: { sessionId: string; cwd: string; leafId: string | null } | undefined;
  const inputs = new Map<string, unknown>();
  const invoke = (action: string, payload?: object, event?: string) => new Promise<any>((resolve, reject) => {
    const wire = payload ? JSON.stringify(payload) : '';
    if (Buffer.byteLength(wire) > 2 * 1024 * 1024) throw new Error('Memory capture input exceeds its bound; original session remains on disk');
    const argv = ['-B', '-m', 'harness.claude_memory', '--home', home, action, ...(event ? [event] : [])];
    const child = spawn(python, argv, { stdio: ['pipe', 'pipe', 'pipe'] });
    let output = Buffer.alloc(0), errors = Buffer.alloc(0), done = false;
    const finish = (error?: Error, value?: any) => {
      if (done) return;
      done = true; clearTimeout(timer);
      error ? reject(error) : resolve(value);
    };
    const stop = (message: string) => { child.kill('SIGKILL'); finish(new Error(message)); };
    const timer = setTimeout(() => stop('Memory hook deadline reached; inspect owned logs before recovery'), 60000);
    child.on('error', error => finish(error));
    child.stdout.on('data', chunk => { output = Buffer.concat([output, chunk]); if (output.length > 65536) stop('Memory hook response exceeds its bound'); });
    child.stderr.on('data', chunk => { errors = Buffer.concat([errors, chunk]); if (errors.length > 65536) stop('Memory hook error exceeds its bound'); });
    child.on('close', code => {
      if (done) return;
      try {
        if (code !== 0) throw new Error(errors.toString('utf8').slice(-4000) || 'Memory hook failed');
        finish(undefined, JSON.parse(output.toString('utf8')));
      } catch (error) { finish(error as Error); }
    });
    child.stdin.on('error', () => stop('Memory input channel failed'));
    child.stdin.end(wire);
  });
  const capture = (ctx: any, event: string, payload: object) => {
    const sessionId = ctx.sessionManager.getSessionId(), cwd = ctx.cwd;
    const queuedPayload = JSON.parse(JSON.stringify({ sessionId, cwd, ...payload }));
    serial = serial.then(async () => {
      try {
        await invoke('hook', queuedPayload, event);
        errorText = ''; ctx.ui?.setStatus?.('claude-memory', undefined);
      } catch (error) {
        errorText = String(error);
        ctx.ui?.setStatus?.('claude-memory', 'Memory capture held; use claude_memory_status');
        // Retain the failure in native history without inventing task authority.
        pi.appendEntry('claude-memory-capture/v1', { status: 'failed', event, error: errorText, authority: 'none' });
      }
    });
    return serial;
  };
  pi.registerTool({ name: 'claude_memory_status', label: 'Claude-mem capture status',
    description: 'Check this agent home\'s exact local Claude-mem worker ownership and provider. Health is not capture freshness or memory quality.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute() {
      try {
        const value = { ...await invoke('status'), last_capture_error: errorText || null };
        return { content: [{ type: 'text', text: JSON.stringify(value) }], details: { ok: true, result: value } };
      } catch (error) { return { content: [{ type: 'text', text: String(error) }], details: { ok: false }, isError: true }; }
    },
  });
  pi.registerTool({ name: 'claude_memory_search', label: 'Search local observer memory',
    description: 'Search this home\'s owned Claude-mem SQLite FTS keyword index. Returns original observation IDs and rows as historical retrieval guidance; this is not semantic search or current task authority.',
    parameters: Type.Object({ query: Type.String({ minLength: 1, maxLength: 1000 }) }, { additionalProperties: false }),
    async execute(_id, params) {
      try {
        const value = await invoke('search', undefined, params.query);
        return { content: [{ type: 'text', text: JSON.stringify(value) }], details: { ok: true, result: value } };
      } catch (error) { return { content: [{ type: 'text', text: String(error) }], details: { ok: false }, isError: true }; }
    },
  });
  pi.on('input', async (event: any, ctx: any) => {
    if (event.source !== 'extension') await capture(ctx, 'session-init', { prompt: event.text });
    return { action: 'continue' as const };
  });
  pi.on('tool_execution_start', async (event: any) => { inputs.set(event.toolCallId, event.args); });
  pi.on('tool_execution_end', async (event: any, ctx: any) => {
    const input = inputs.get(event.toolCallId) ?? {};
    inputs.delete(event.toolCallId);
    if (!event.toolName.startsWith('claude_memory_'))
      await capture(ctx, 'observation', { toolName: event.toolName, toolInput: input,
        toolResponse: event.result, toolUseId: event.toolCallId });
  });
  pi.on('agent_start', async (_event: any, ctx: any) => {
    run = { sessionId: ctx.sessionManager.getSessionId(), cwd: ctx.cwd, leafId: ctx.sessionManager.getLeafId() };
  });
  pi.on('agent_settled', async (event: any, ctx: any) => {
    const started = run;
    run = undefined;
    if (event.aborted) return;
    const branch = ctx.sessionManager.getBranch();
    const marker = started?.leafId == null ? -1 : branch.findIndex((entry: any) => entry.id === started.leafId);
    const bound = started && started.sessionId === ctx.sessionManager.getSessionId() && started.cwd === ctx.cwd
      && (started.leafId === null || marker >= 0);
    // Read the final persisted message after all message_end hooks. Never scan
    // an older run, forward thinking/tool calls, or fall back to unrelated text.
    const latest = bound ? branch.slice(marker + 1).reverse().find((entry: any) =>
      entry.type === 'message' && entry.message?.role === 'assistant')?.message : undefined;
    const text = Array.isArray(latest?.content) ? latest.content
      .filter((part: any) => part.type === 'text' && typeof part.text === 'string')
      .map((part: any) => part.text).join('\n') : '';
    if (!bound || !text.trim() || latest.stopReason === 'aborted' || latest.stopReason === 'error') {
      errorText = 'Summary held: no completed plain assistant text in the current bound run';
      ctx.ui?.setStatus?.('claude-memory', errorText);
      pi.appendEntry('claude-memory-capture/v1', { status: 'held', event: 'summarize', error: errorText, authority: 'none' });
      return;
    }
    await capture(ctx, 'summarize', { last_assistant_message: text });
  });
  pi.on('session_shutdown', async () => { await serial; inputs.clear(); run = undefined; });
}
