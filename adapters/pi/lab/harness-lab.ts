/** Optional deterministic component diagnostic; no model experiment route. */
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

const sha = (value: Buffer) => createHash('sha256').update(value).digest('hex');
const MAX = 12 * 1024;

function binding() {
  const home = process.env.AGENT_HOME;
  const python = process.env.PI_HARNESS_LAB_PYTHON;
  const helper = process.env.PI_HARNESS_LAB_HELPER;
  const pin = process.env.PI_HARNESS_LAB_HELPER_SHA256;
  const raw = process.env.PI_HARNESS_LAB_COMMAND;
  const commandPin = process.env.PI_HARNESS_LAB_COMMAND_SHA256;
  if (process.platform !== 'linux' || !home || !python || !helper || !pin || !raw || !commandPin
      || ![home, python, helper].every(value => path.isAbsolute(value)))
    throw new Error('The full-profile Linux lab lifecycle binding is required.');
  if (python !== path.join(home, 'envs/harness2/bin/python')
      || helper !== path.join(home, 'runtime/adapters/pi/lab/harness_lab.py')
      || fs.lstatSync(helper).isSymbolicLink() || fs.realpathSync(helper) !== helper
      || !/^[a-f0-9]{64}$/.test(pin) || sha(fs.readFileSync(helper)) !== pin
      || Buffer.byteLength(raw) > 65536 || !/^[a-f0-9]{64}$/.test(commandPin)
      || sha(Buffer.from(raw, 'utf8')) !== commandPin)
    throw new Error('The lab helper or lifecycle command binding changed.');
  const config = JSON.parse(fs.readFileSync(path.join(home, 'home.json'), 'utf8'));
  const manifestRaw = fs.readFileSync(path.join(home, 'runtime/runtime-manifest.json'));
  if (config.profile !== 'full' || config.home !== home || !config.lifecycle_guard_sha256
      || sha(manifestRaw) !== config.runtime_manifest_sha256)
    throw new Error('The lab requires its managed full-profile home and lifecycle guard.');
  const files = JSON.parse(manifestRaw.toString('utf8')).files;
  for (const name of ['pi-task-worker.py', 'pi_native_events.py', 'native_pidfd.py']) {
    const file = path.join(home, 'runtime', name);
    if (fs.lstatSync(file).isSymbolicLink() || fs.realpathSync(file) !== file
        || sha(fs.readFileSync(file)) !== files.find((item: any) => item.path === name)?.sha256)
      throw new Error('Lab process ownership source changed.');
  }
  const target = [python, '-s', '-B', path.join(home, 'runtime/pi-task-worker.py'), '--guard',
    python, '-I', '-B', helper, '--home', home];
  const command = JSON.parse(raw);
  if (!Array.isArray(command) || !command.every(item => typeof item === 'string' && !item.includes('\0'))
      || command[0] !== python || JSON.stringify(command.slice(-target.length)) !== JSON.stringify(target))
    throw new Error('The lab lifecycle command target differs.');
  const env: NodeJS.ProcessEnv = {};
  for (const key of ['HOME', 'USER', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'WINDIR'])
    if (process.env[key] !== undefined) env[key] = process.env[key];
  Object.assign(env, { AGENT_HOME: home, PATH: path.dirname(python) + ':/usr/bin:/bin',
    PYTHONDONTWRITEBYTECODE: '1', PI_TASK_TIMEOUT: '120', CUDA_VISIBLE_DEVICES: '',
    TMPDIR: path.join(home, 'cache/lab/tmp'), XDG_CACHE_HOME: path.join(home, 'cache/lab') });
  return { home, command, env };
}

async function invoke(action: string, signal?: AbortSignal): Promise<any> {
  if (action === 'experiment') throw new Error('Model experiments are held; use status or the deterministic demo.');
  if (!['status', 'demo'].includes(action)) throw new Error('Unsupported lab action.');
  if (signal?.aborted) throw new Error('Lab diagnostic cancelled before dispatch.');
  const runtime = binding();
  return new Promise((resolve, reject) => {
    const child = spawn(runtime.command[0], [...runtime.command.slice(1), '--action', action], {
      cwd: runtime.home, env: runtime.env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
    });
    let output = Buffer.alloc(0), errors = Buffer.alloc(0), stopped = '', done = false;
    let settlement: ReturnType<typeof setTimeout> | undefined;
    const stop = (reason: string) => {
      if (stopped) return;
      stopped = reason;
      // EOF is the canonical guard's owner-loss signal. Await its close before
      // returning so cancellation does not claim synchronous child settlement.
      child.stdin.end();
      settlement = setTimeout(() => child.kill('SIGTERM'), 35000);
    };
    const abort = () => stop('Lab diagnostic cancelled; retained runs may be partial.');
    const timer = setTimeout(() => stop('Lab diagnostic deadline; inspect retained run logs.'), 135000);
    signal?.addEventListener('abort', abort, { once: true });
    const finish = (error?: Error, value?: any) => {
      if (done) return;
      done = true; clearTimeout(timer); clearTimeout(settlement);
      signal?.removeEventListener('abort', abort); child.stdin.end();
      error ? reject(error) : resolve(value);
    };
    child.on('error', error => finish(error));
    child.stdin.on('error', () => stop('Lab ownership pipe failed.'));
    child.stdout.on('data', chunk => {
      if (output.length + chunk.length > MAX) stop('Lab response exceeds its bound.');
      else output = Buffer.concat([output, chunk]);
    });
    child.stderr.on('data', chunk => {
      if (errors.length + chunk.length > 8192) stop('Lab diagnostics exceed their bound.');
      else errors = Buffer.concat([errors, chunk]);
    });
    child.on('close', code => {
      if (stopped || signal?.aborted) { finish(new Error(stopped || 'Lab diagnostic cancelled.')); return; }
      try {
        const value = JSON.parse(output.toString('utf8'));
        if (value?.schema !== 'harness-lab/v1' || typeof value.ok !== 'boolean'
            || value.action !== action || (code !== 0 && value.ok)) throw new Error('Invalid lab response.');
        finish(undefined, value);
      } catch { finish(new Error('Lab helper returned no complete bound result; inspect retained logs.')); }
    });
    // Keep stdin open. Parent loss closes the pipe and settles owned descendants.
    if (signal?.aborted) abort();
  });
}

export default function register(pi: ExtensionAPI) {
  pi.registerCommand('harness-lab', {
    description: 'Inspect optional lab package identity without model inference.',
    handler: async (_args, ctx) => {
      try { const value = await invoke('status'); ctx.ui.notify(JSON.stringify(value), value.ok ? 'info' : 'warning'); }
      catch (error) { ctx.ui.notify(String(error), 'warning'); }
    },
  });
  pi.registerTool({
    name: 'harness_lab', label: 'Optional component lab',
    description: 'Full-profile optional diagnostics. status verifies recorded Harness2/DeepSeek identities. demo runs the pinned upstream scripted signed-ledger adaptation, retains local logs and independently checks selected answers. No model inference or project permission is granted. experiment is held. This is a component check, not agent quality or full-system acceptance.',
    parameters: Type.Object({ action: Type.Union([Type.Literal('status'), Type.Literal('demo'), Type.Literal('experiment')]) },
      { additionalProperties: false }),
    async execute(_id, args, signal) {
      try {
        const value = await invoke(args.action, signal);
        return { content: [{ type: 'text' as const, text: JSON.stringify(value) }], details: value, isError: !value.ok };
      } catch (error) {
        const value = { schema: 'harness-lab/v1', ok: false, action: args.action, error: String(error).slice(0, 700) };
        return { content: [{ type: 'text' as const, text: JSON.stringify(value) }], details: value, isError: true };
      }
    },
  });
}
