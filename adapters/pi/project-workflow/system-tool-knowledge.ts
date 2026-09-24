import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const PYTHON = process.env.PI_SYSTEM_TOOL_PYTHON || 'python3';
const HELPER = process.env.PI_SYSTEM_TOOL_HELPER || '';
const DATABASE = process.env.PI_SYSTEM_TOOL_DATABASE || '';
const HELPER_SHA256 = process.env.PI_SYSTEM_TOOL_HELPER_SHA256 || '';

function run(args: string[], signal?: AbortSignal): Promise<any> {
  return new Promise((resolve, reject) => {
    if (!HELPER || !DATABASE || !HELPER_SHA256) return reject(new Error('PI_SYSTEM_TOOL_HELPER, PI_SYSTEM_TOOL_DATABASE, and PI_SYSTEM_TOOL_HELPER_SHA256 are required'));
    const observed = createHash('sha256').update(readFileSync(HELPER)).digest('hex');
    if (observed !== HELPER_SHA256) return reject(new Error('system tool helper byte drift'));
    const child = spawn(PYTHON, ['-B', HELPER, '--database', DATABASE, ...args], { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = Buffer.alloc(0); let stderr = Buffer.alloc(0); let settled = false;
    const finish = (error?: Error, value?: any) => { if (settled) return; settled = true; clearTimeout(timer); signal?.removeEventListener('abort', abort); error ? reject(error) : resolve(value); };
    const abort = () => { child.kill('SIGKILL'); finish(new Error('cancelled')); };
    const timer = setTimeout(() => { child.kill('SIGKILL'); finish(new Error('system tool query timeout')); }, 10000);
    signal?.addEventListener('abort', abort, { once: true });
    child.stdout.on('data', (chunk: Buffer) => { stdout = Buffer.concat([stdout, chunk]); if (stdout.length > 1024 * 1024) { child.kill('SIGKILL'); finish(new Error('system tool query output too large')); } });
    child.stderr.on('data', (chunk: Buffer) => { stderr = Buffer.concat([stderr, chunk]); });
    child.on('error', (error) => finish(error));
    child.on('close', (code) => { try { const value = JSON.parse(stdout.toString('utf8')); if (code !== 0 || value?.ok !== true) return finish(new Error(value?.error || stderr.toString('utf8') || `exit ${code}`)); finish(undefined, value); } catch { finish(new Error('invalid system tool query response')); } });
  });
}

function result(value: any) { return { content: [{ type: 'text' as const, text: JSON.stringify(value) }], details: value }; }
function failure(error: unknown) { const text = error instanceof Error ? error.message : String(error); return { content: [{ type: 'text' as const, text }], details: { ok: false, error: text }, isError: true }; }

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: 'system_tool_query', label: 'Query system tools',
    description: 'Search the hash-bound rig-wide catalog of Claude, Codex, Pi, MCP, script, rule, and skill capabilities. Results cite source files and hashes and grant retrieval-only authority.',
    parameters: Type.Object({ terms: Type.String({ minLength: 1, maxLength: 1000 }), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })) }, { additionalProperties: false }),
    async execute(_id, params, signal) { try { return result(await run(['query', params.terms, '--limit', String(params.limit ?? 8)], signal)); } catch (error) { return failure(error); } },
  });
  pi.registerTool({
    name: 'system_tool_status', label: 'System tool catalog status',
    description: 'Report the exact source hashes and record count of the rig-wide tool catalog.',
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_id, _params, signal) { try { return result(await run(['status'], signal)); } catch (error) { return failure(error); } },
  });
}
