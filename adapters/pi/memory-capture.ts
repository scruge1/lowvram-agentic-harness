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
  const capture = (ctx: any) => {
    const file = ctx.sessionManager.getSessionFile();
    if (!file) return serial; // Native in-memory SDK sessions have no original file.
    serial = serial.then(async () => {
      if (createHash('sha256').update(readFileSync(helper)).digest('hex') !== expected)
        throw new Error('Memory capture source drift');
      const wrapper = process.env.PI_MEMORY_RUNTIME_WRAPPER;
      if (!wrapper || createHash('sha256').update(readFileSync(wrapper)).digest('hex') !== process.env.PI_MEMORY_RUNTIME_WRAPPER_SHA256)
        throw new Error('Memory runtime wrapper binding differs');
      const guard = join(home, 'runtime', 'pi-task-worker.py');
      const argv = ['-B', guard, '--guard', python, '-B', wrapper, '--home', home, 'capture', '--',
        '--sessions-root', join(home, 'agent', 'sessions'),
        '--state-root', join(home, 'memory', 'pi-capture'),
        '--palace', join(home, 'memory', 'palace'),
        '--mempalace-cli', process.env.PI_MEMORY_CAPTURE_CLI!, '--session-file', file];
      last = await new Promise<any>((resolve, reject) => {
        const child = spawn(python, argv, { stdio: ['pipe', 'pipe', 'pipe'],
          env: { ...process.env, CUDA_VISIBLE_DEVICES: '', PI_TASK_TIMEOUT: '150' } });
        let out = Buffer.alloc(0), error = Buffer.alloc(0), done = false;
        const finish = (failure?: Error, value?: any) => {
          if (done) return;
          done = true; clearTimeout(timer); child.stdin.end();
          failure ? reject(failure) : resolve(value);
        };
        const timer = setTimeout(() => { child.stdin.end(); finish(new Error('Memory capture deadline; inspect retained state before recovery')); }, 165000);
        child.on('error', failure => finish(failure));
        child.stdout.on('data', chunk => { out = Buffer.concat([out, chunk]); if (out.length > 65536) finish(new Error('Capture result exceeded its bound')); });
        child.stderr.on('data', chunk => { error = Buffer.concat([error, chunk]); if (error.length > 65536) finish(new Error('Capture error exceeded its bound')); });
        child.on('close', code => {
          if (code !== 0) return finish(new Error(error.toString('utf8').slice(-4000) || `Capture exited ${code}`));
          try { finish(undefined, JSON.parse(out.toString('utf8'))); }
          catch { finish(new Error('Capture returned no complete JSON result')); }
        });
        child.stdin.on('error', () => finish(new Error('Capture ownership pipe failed')));
        // Retain the ownership pipe. EOF asks the existing guard to cancel.
      });
      ctx.ui?.setStatus?.('pi-memory-capture', undefined);
    }).catch(error => {
      last = { status: 'failed', error: String(error), authority: 'none' };
      pi.appendEntry('pi-memory-capture/v1', last);
      ctx.ui?.setStatus?.('pi-memory-capture', 'Transcript capture held; use pi_memory_capture_status');
    });
    return serial;
  };
  pi.registerTool({ name: 'pi_memory_capture_status', label: 'Current transcript capture status',
    description: 'Read the latest current-session export/mining result. Exact stored bytes do not prove recalled claims or project completion.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute() { return { content: [{ type: 'text', text: JSON.stringify(last) }], details: { ok: last.status !== 'failed', result: last } }; },
  });
  pi.on('agent_settled', async (_event: any, ctx: any) => { await capture(ctx); });
  pi.on('session_shutdown', async (_event: any, ctx: any) => { await capture(ctx); });
}
