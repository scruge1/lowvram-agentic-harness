import { createHash } from 'node:crypto';

// One canonical representation for projection, read-loop and helper bindings.
export const ordered = (value: any): any => Array.isArray(value) ? value.map(ordered)
  : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])])) : value;
export const packetDigest = (value: unknown) => createHash('sha256').update(JSON.stringify(ordered(value))).digest('hex');
