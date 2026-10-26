/** Capture only the current owned Pi session at settled/shutdown notifications. */
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

export default function (pi: ExtensionAPI) {
  const home = process.env.AGENT_HOME;
  const python = process.env.PI_MEMORY_CAPTURE_PYTHON;
  const helper = process.env.PI_MEMORY_CAPTURE_HELPER;
  const expected = process.env.PI_MEMORY_CAPTURE_HELPER_SHA256;
  if (!home || !python || !helper || !expected) throw new Error('Explicit Pi memory capture bindings are required');
  let serial: Promise<unknown> = Promise.resolve();
  let last: any = { status: 'not_observed', authority: 'none' };
  const invoke = (mode: 'capture' | 'capture-status', args: string[], seconds: number, signal?: AbortSignal) => {
    if (process.env.AGENT_HOME !== home) throw new Error('Memory capture home binding changed');
    if (createHash('sha256').update(readFileSync(helper)).digest('hex') !== expected)
      throw new Error('Memory capture source drift');
    const wrapper = process.env.PI_MEMORY_RUNTIME_WRAPPER;
    if (!wrapper || createHash('sha256').update(readFileSync(wrapper)).digest('hex') !== process.env.PI_MEMORY_RUNTIME_WRAPPER_SHA256)
      throw new Error('Memory runtime wrapper binding differs');
    if (signal?.aborted) throw new Error('Memory status cancelled');
    const guard = join(home, 'runtime', 'pi-task-worker.py');
    const argv = ['-B', guard, '--guard', python, '-B', wrapper, '--home', home, mode, '--', ...args];
    return new Promise<any>((resolve, reject) => {
      const child = spawn(python, argv, { stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...process.env, CUDA_VISIBLE_DEVICES: '', PI_TASK_TIMEOUT: String(seconds) } });
      let out = Buffer.alloc(0), error = Buffer.alloc(0), done = false;
      const abort = () => finish(new Error('Memory status cancelled; child ownership pipe closed'));
      const finish = (failure?: Error, value?: any) => {
        if (done) return;
        done = true; clearTimeout(timer); signal?.removeEventListener('abort', abort); child.stdin.end();
        failure ? reject(failure) : resolve(value);
      };
      const timer = setTimeout(() => finish(new Error('Memory helper deadline; inspect retained state before recovery')), (seconds + 15) * 1000);
      child.on('error', failure => finish(failure));
      child.stdout.on('data', chunk => { out = Buffer.concat([out, chunk]); if (out.length > 65536) finish(new Error('Capture result exceeded its bound')); });
      child.stderr.on('data', chunk => { error = Buffer.concat([error, chunk]); if (error.length > 65536) finish(new Error('Capture error exceeded its bound')); });
      child.on('close', code => {
        if (code !== 0) return finish(new Error(error.toString('utf8').slice(-4000) || `Capture exited ${code}`));
        try { finish(undefined, JSON.parse(out.toString('utf8'))); }
        catch { finish(new Error('Capture returned no complete JSON result')); }
      });
      child.stdin.on('error', () => finish(new Error('Capture ownership pipe failed')));
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted) abort();
      // Retain the ownership pipe. EOF asks the existing guard to cancel.
    });
  };
  const capture = (ctx: any) => {
    const file = ctx.sessionManager.getSessionFile();
    if (!file) return serial; // Native in-memory SDK sessions have no original file.
    serial = serial.then(async () => {
      last = await invoke('capture', [
        '--sessions-root', join(home, 'agent', 'sessions'),
        '--state-root', join(home, 'memory', 'pi-capture'),
        '--palace', join(home, 'memory', 'palace'),
        '--mempalace-cli', process.env.PI_MEMORY_CAPTURE_CLI!, '--session-file', file], 150);
      ctx.ui?.setStatus?.('pi-memory-capture', undefined);
    }).catch(error => {
      last = { status: 'failed', error: String(error), authority: 'none' };
      pi.appendEntry('pi-memory-capture/v1', last);
      ctx.ui?.setStatus?.('pi-memory-capture', 'Transcript capture held; use pi_memory_capture_status');
    });
    return serial;
  };
  pi.registerTool({ name: 'pi_memory_capture_status', label: 'Current transcript capture status',
    description: 'Read bounded persisted owned-history receipts after reopen. Metadata matches do not verify current raw bytes; unknown sessions are not scanned. No palace, model or capture is started.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_id, _params, signal) {
      try {
        const wrapper = process.env.PI_MEMORY_RUNTIME_WRAPPER, wrapperPin = process.env.PI_MEMORY_RUNTIME_WRAPPER_SHA256;
        const result = await invoke('capture-status', [], 30, signal);
        if (signal?.aborted || process.env.AGENT_HOME !== home
            || createHash('sha256').update(readFileSync(helper)).digest('hex') !== expected
            || !wrapper || !wrapperPin || process.env.PI_MEMORY_RUNTIME_WRAPPER !== wrapper
            || process.env.PI_MEMORY_RUNTIME_WRAPPER_SHA256 !== wrapperPin
            || createHash('sha256').update(readFileSync(wrapper)).digest('hex') !== wrapperPin)
          throw new Error('Memory status delivery held after cancellation or binding drift');
        const text = JSON.stringify(result);
        if (Buffer.byteLength(text, 'utf8') > 12 * 1024) throw new Error('Memory status exceeded its delivery bound');
        return { content: [{ type: 'text', text }], details: { ok: true, result, last_notification_status: last.status ?? 'settled_result' } };
      } catch {
        return { content: [{ type: 'text', text: 'Owned transcript status held; inspect capture metadata and source bindings. No capture, retry or palace request was made.' }],
          details: { ok: false, status: 'held', authority: 'none' }, isError: true };
      }
    },
  });
  pi.on('agent_settled', async (_event: any, ctx: any) => { await capture(ctx); });
  pi.on('session_shutdown', async (_event: any, ctx: any) => { await capture(ctx); });
}
