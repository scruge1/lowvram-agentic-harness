import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync, statSync } from 'node:fs';
import { dirname, isAbsolute, join } from 'node:path';

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}
const PYTHON = required('PI_VALIDATED_MEMORY_PYTHON');
const HELPER = required('PI_VALIDATED_MEMORY_HELPER');
const REGISTRY = required('PI_VALIDATED_MEMORY_REGISTRY');
const POLICY = required('PI_VALIDATED_MEMORY_POLICY');
const HELPER_SHA256 = required('PI_VALIDATED_MEMORY_HELPER_SHA256');
const POLICY_SHA256 = required('PI_VALIDATED_MEMORY_POLICY_SHA256');
const REGISTRY_SHA256 = required('PI_VALIDATED_MEMORY_REGISTRY_SHA256');
const PALACE = required('MEMPALACE_PALACE_PATH');
const CONFIG = required('MEMPALACE_CONFIG_DIR');
for (const file of [PYTHON, HELPER, REGISTRY, POLICY, PALACE, CONFIG]) {
  if (!isAbsolute(file)) throw new Error('Validated memory paths must be absolute');
}

function digest(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

function run(query: string, limit: number, signal?: AbortSignal): Promise<any> {
  return new Promise((resolve, reject) => {
    if (typeof query !== 'string' || !query.trim() || query.length > 1000
        || !Number.isInteger(limit) || limit < 1 || limit > 20) return reject(new Error('Invalid validated memory query'));
    if (signal?.aborted) return reject(new Error('Validated memory query cancelled'));
    if (!statSync(PALACE).isDirectory() || !statSync(CONFIG).isDirectory())
      return reject(new Error('Validated memory palace and configuration directories are required'));
    if (realpathSync(POLICY) !== realpathSync(join(dirname(HELPER), 'memory_retrieval_policy.py')))
      return reject(new Error('Validated memory policy must be the helper\'s actual sibling import'));
    for (const [file, expected] of [[HELPER, HELPER_SHA256], [POLICY, POLICY_SHA256], [REGISTRY, REGISTRY_SHA256]]) {
      if (!/^[a-f0-9]{64}$/.test(expected) || digest(file) !== expected)
        return reject(new Error('Validated memory component byte drift'));
    }
    const wrapper = process.env.PI_MEMORY_RUNTIME_WRAPPER;
    const home = process.env.AGENT_HOME;
    if (wrapper && (!home || !isAbsolute(wrapper) || digest(wrapper) !== process.env.PI_MEMORY_RUNTIME_WRAPPER_SHA256))
      return reject(new Error('Memory runtime wrapper binding differs'));
    const prefix = wrapper ? ['-B', wrapper, '--home', home!, 'validated', '--'] : ['-B', HELPER];
    const child = spawn(PYTHON, [...prefix, '--query', query, '--live', '--claim-registry', REGISTRY, '--limit', String(limit)], {
      cwd: dirname(HELPER), stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, MEMPALACE_PALACE_PATH: PALACE, MEMPALACE_CONFIG_DIR: CONFIG,
        PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1' },
    });
    let stdout = Buffer.alloc(0), stderr = Buffer.alloc(0), settled = false;
    const finish = (error?: Error, value?: any) => {
      if (settled) return;
      settled = true; clearTimeout(timer); signal?.removeEventListener('abort', abort);
      error ? reject(error) : resolve(value);
    };
    const abort = () => { child.kill('SIGKILL'); finish(new Error('Validated memory query cancelled')); };
    const timer = setTimeout(() => { child.kill('SIGKILL'); finish(new Error('Validated memory query timed out')); }, 30000);
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    child.stdout.on('data', (chunk: Buffer) => {
      if (settled) return;
      if (stdout.length + chunk.length > 1024 * 1024) {
        child.kill('SIGKILL'); finish(new Error('Validated memory result exceeds its bound')); return;
      }
      stdout = Buffer.concat([stdout, chunk]);
    });
    child.stderr.on('data', (chunk: Buffer) => {
      if (settled) return;
      if (stderr.length + chunk.length > 8192) {
        child.kill('SIGKILL'); finish(new Error('Validated memory diagnostic exceeds its bound')); return;
      }
      stderr = Buffer.concat([stderr, chunk]);
    });
    child.on('error', error => finish(error));
    child.on('close', code => {
      if (settled) return;
      try {
        const value = JSON.parse(stdout.toString('utf8'));
        if (code !== 0 || value?.schema !== 'validated-memory-query/v1' || !Array.isArray(value.results))
          return finish(new Error('Validated memory helper did not return a valid result'));
        finish(undefined, value);
      } catch { finish(new Error('Invalid validated memory response')); }
    });
  });
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: 'validated_memory_query', label: 'Query validated memory',
    description: 'Retrieve only reviewed memory claims bound to exact current source bytes. Sensitive queries abstain before palace access. Unknown, obsolete, drifted or unsafe summaries are refused. Retrieval gives no execution authority.',
    parameters: Type.Object({ query: Type.String({ minLength: 1, maxLength: 1000 }),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })) }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      try {
        const value = await run(params.query, params.limit ?? 5, signal);
        return { content: [{ type: 'text', text: JSON.stringify(value) }], details: value };
      } catch {
        return { content: [{ type: 'text', text: 'Validated memory query unavailable. Inspect the configured source, registry and palace bindings.' }],
          details: { ok: false }, isError: true };
      }
    },
  });
}
