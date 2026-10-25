import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ordered, packetDigest } from './packet-digest.ts';

export { packetDigest } from './packet-digest.ts';
const HELPER = join(dirname(fileURLToPath(import.meta.url)), 'decision-138.py');
const sha = (data: any) => createHash('sha256').update(data).digest('hex');
const HASH = /^[a-f0-9]{64}$/;
const bindingKeys = ['schema', 'framework_version', 'python', 'python_sha256', 'helper', 'helper_sha256', 'files'].sort();

function runtimeBinding() {
  const filename = process.env.PI_FRAMEWORK_BINDING;
  const expected = process.env.PI_FRAMEWORK_BINDING_SHA256;
  if (!filename || !isAbsolute(filename) || !expected || !HASH.test(expected))
    throw new Error('Set the exact PI_FRAMEWORK_BINDING and PI_FRAMEWORK_BINDING_SHA256 before retained-work decisions');
  const raw = readFileSync(filename);
  if (raw.length > 1024 * 1024 || sha(raw) !== expected) throw new Error('Framework binding byte drift');
  const runtime = JSON.parse(raw.toString('utf8'));
  if (!runtime || JSON.stringify(Object.keys(runtime).sort()) !== JSON.stringify(bindingKeys)
      || runtime.schema !== 'pi-framework-binding/v1' || runtime.framework_version !== '1.21.0'
      || typeof runtime.python !== 'string' || !isAbsolute(runtime.python)
      || !HASH.test(runtime.python_sha256) || runtime.helper !== HELPER || !HASH.test(runtime.helper_sha256)
      || !Array.isArray(runtime.files) || runtime.files.length < 1 || runtime.files.length > 512)
    throw new Error('Invalid Framework target binding');
  if (sha(readFileSync(HELPER)) !== runtime.helper_sha256) throw new Error('Retained decision helper byte drift');
  if (sha(readFileSync(runtime.python)) !== runtime.python_sha256) throw new Error('Retained decision Python executable byte drift');
  const seen = new Set<string>();
  for (const file of runtime.files) {
    if (!file || JSON.stringify(Object.keys(file).sort()) !== JSON.stringify(['path', 'sha256'])
        || typeof file.path !== 'string' || !isAbsolute(file.path) || !HASH.test(file.sha256) || seen.has(file.path))
      throw new Error('Invalid Framework source binding');
    seen.add(file.path);
    if (sha(readFileSync(file.path)) !== file.sha256) throw new Error('Retained decision runtime source drift: ' + file.path);
  }
  return runtime;
}

export async function decideRetainedWork(packet: any): Promise<any> {
  const bytes = Buffer.from(JSON.stringify(ordered(packet)));
  if (bytes.length > 256 * 1024) throw new Error('Retained decision packet exceeds its bound');
  const runtime = runtimeBinding();
  const env: NodeJS.ProcessEnv = { PATH: dirname(runtime.python), LANG: 'C.UTF-8',
    PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1' };
  if (process.platform === 'win32' && process.env.SystemRoot) env.SystemRoot = process.env.SystemRoot;
  const decision = await new Promise<any>((resolve, reject) => {
    const child = spawn(runtime.python, ['-B', HELPER], { stdio: ['pipe', 'pipe', 'pipe'], env });
    let stdout = Buffer.alloc(0), stderr = Buffer.alloc(0), settled = false;
    const finish = (error?: Error, value?: any) => {
      if (settled) return;
      settled = true; clearTimeout(timer);
      if (error) reject(error); else resolve(value);
    };
    const stop = (reason: string) => { child.kill('SIGKILL'); finish(new Error(reason)); };
    const timer = setTimeout(() => stop('Retained decision helper deadline reached'), 10000);
    child.on('error', error => finish(error));
    child.stdout.on('data', chunk => {
      stdout = Buffer.concat([stdout, chunk]);
      if (stdout.length > 16 * 1024) stop('Retained decision output exceeds its bound');
    });
    child.stderr.on('data', chunk => {
      stderr = Buffer.concat([stderr, chunk]);
      if (stderr.length > 4096) stop('Retained decision stderr exceeds its bound');
    });
    child.on('close', code => {
      if (settled) return;
      try {
        const value = JSON.parse(stdout.toString('utf8'));
        if (code !== 0 || value.ok !== true) {
          const reason = value.schema === packet.schema && typeof value.reason === 'string' ? value.reason.slice(0, 3072)
            : typeof value.error === 'string' ? value.error.slice(0, 3072) : 'Retained decision failed with exit ' + code;
          throw new Error(reason);
        }
        finish(undefined, value);
      } catch (error) { finish(error instanceof Error ? error : new Error('Invalid retained decision result')); }
    });
    child.stdin.on('error', error => { child.kill('SIGKILL'); finish(error); });
    child.stdin.end(bytes);
  });
  if (decision.schema !== packet.schema || decision.packet_sha256 !== packetDigest(packet)
      || !['route_pending', 'continue', 'hold', 'queue_complete'].includes(decision.decision)
      || typeof decision.reason !== 'string') throw new Error('Retained decision response binding is invalid');
  if (decision.decision === 'continue') {
    const selected = decision.selected;
    const task = packet.tasks.find((item: any) => item.id === selected?.task && item.source === selected?.source);
    if (!task || !['ready', 'running'].includes(task.status)
        || !['execute', 'integrate'].includes(selected.action)) throw new Error('Retained decision selected an invalid leaf');
  }
  return decision;
}
