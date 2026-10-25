import { realpathSync, openSync, closeSync, fstatSync, readSync, watch, constants } from 'node:fs';
import { dirname, basename, isAbsolute, relative } from 'node:path';
import { createHash } from 'node:crypto';

export type Receipt = { path: string; equals: Record<string, string | number | boolean> };
export type TaskWait = { id: string; root: string; task: string; source: string; key: string;
  kind: 'user' | 'peer' | 'resource' | 'external'; reason: string; trigger: string;
  status: 'waiting' | 'resolved'; receipt?: Receipt; evidence?: string;
  notice?: 'claimed' | 'sent' | 'suppressed'; hint_seen?: boolean };
const MAX = 256 * 1024;
function requireLinuxReceiptSupport() {
  if (process.platform !== 'linux' || typeof process.getuid !== 'function'
      || typeof constants.O_NOFOLLOW !== 'number' || typeof constants.O_NONBLOCK !== 'number')
    throw new Error('Dependency receipts require Linux account ownership and opened-file containment checks');
}
const terminal = new Set(['complete', 'completed', 'done', 'passed', 'success', 'succeeded',
  'reviewed-source-committed-and-private-remote-verified', 'supplied_predicate_passed']);
const inside = (root: string, target: string) => {
  const r = relative(root, target);
  return r !== '' && r !== '..' && !r.startsWith('../') && !isAbsolute(r);
};
export function checkedReceipt(root: string, spec: Receipt): Receipt {
  requireLinuxReceiptSupport();
  if (!spec || typeof spec.path !== 'string' || !isAbsolute(spec.path) || !spec.path.endsWith('.json')
      || spec.path.length > 4096 || !spec.equals || typeof spec.equals !== 'object' || Array.isArray(spec.equals))
    throw new Error('Receipt needs an absolute in-project JSON path and exact expected fields');
  if (JSON.stringify(spec.equals).length > 8192) throw new Error('Receipt expectations exceed their bound');
  const keys = Object.keys(spec.equals);
  if (!keys.length || keys.length > 16 || keys.some(k => k.length > 128 || !/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(k)
      || k.split('.').some(x => ['__proto__', 'constructor', 'prototype'].includes(x))))
    throw new Error('Invalid expected receipt fields');
  if (Object.values(spec.equals).some(v => !['string', 'number', 'boolean'].includes(typeof v)
      || typeof v === 'string' && (!v.length || v.length > 1024)
      || typeof v === 'number' && !Number.isFinite(v)))
    throw new Error('Receipt expectations must be bounded primitive values');
  if (!keys.some(k => /(^|\.)(id|job_id|run_id|operation|operation_id|task_id|commit)$/.test(k)
      && typeof spec.equals[k] === 'string' && String(spec.equals[k]).length > 0))
    throw new Error('Pin the specific job/run/operation identity, not just a success status');
  if (!keys.some(k => /(^|\.)(status|state)$/.test(k) && terminal.has(String(spec.equals[k]))))
    throw new Error('Pin the expected terminal completion state');
  const base = realpathSync(root), parent = realpathSync(dirname(spec.path));
  if (parent !== base && !inside(base, parent)) throw new Error('Receipt parent escapes the admitted project');
  return { path: parent + '/' + basename(spec.path), equals: { ...spec.equals } };
}
export function inspectReceipt(root: string, spec: Receipt): { verified: boolean; reason: string; sha256?: string } {
  let fd: number | undefined;
  try {
    spec = checkedReceipt(root, spec);
    fd = openSync(spec.path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    const a = fstatSync(fd);
    if (!a.isFile() || a.size > MAX || a.uid !== process.getuid?.())
      return { verified: false, reason: 'Receipt is not a small account-owned regular file' };
    const actual = realpathSync('/proc/self/fd/' + fd);
    if (!inside(realpathSync(root), actual)) return { verified: false, reason: 'Opened receipt escapes project' };
    const bytes = Buffer.alloc(MAX + 1); let n = 0, count = 0;
    while (n <= MAX && (count = readSync(fd, bytes, n, MAX + 1 - n, null)) > 0) n += count;
    const z = fstatSync(fd);
    if (n > MAX || a.size !== z.size || a.ino !== z.ino || a.mtimeMs !== z.mtimeMs || n !== z.size)
      return { verified: false, reason: 'Receipt changed during read' };
    const raw = bytes.subarray(0, n), value = JSON.parse(raw.toString('utf8'));
    for (const [key, expected] of Object.entries(spec.equals)) {
      let actual = value;
      for (const part of key.split('.')) {
        if (!actual || typeof actual !== 'object' || !Object.hasOwn(actual, part))
          return { verified: false, reason: 'Expected receipt field missing' };
        actual = actual[part];
      }
      if (actual !== expected) return { verified: false, reason: 'Receipt identity/state does not match this wait' };
    }
    return { verified: true, reason: 'Registered receipt identity and terminal state verified',
      sha256: createHash('sha256').update(raw).digest('hex') };
  } catch (error: any) {
    return { verified: false, reason: error?.code === 'ENOENT' ? 'Receipt not present yet' : 'Receipt unavailable or not valid JSON' };
  } finally { if (fd !== undefined) closeSync(fd); }
}
export function watchReceipt(spec: Receipt, changed: () => void, error: () => void) {
  requireLinuxReceiptSupport();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const watcher = watch(dirname(spec.path), { persistent: false }, (_kind, filename) => {
    if (filename && String(filename) !== basename(spec.path)) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(changed, 25);
  });
  watcher.on('error', error);
  return () => { if (timer) clearTimeout(timer); watcher.close(); };
}
export function blockedTaskIds(packet: any): Set<string> {
  const held = new Set<string>(packet.waiting_tasks ?? []);
  for (let i = 0; i <= packet.tasks.length; i++) {
    let changed = false;
    for (const task of packet.tasks)
      if (!held.has(task.id) && (held.has(task.parent) || task.prerequisites.some((p: string) => held.has(p)))) {
        held.add(task.id); changed = true;
      }
    if (!changed) break;
  }
  return held;
}
