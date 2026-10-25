/** Bind the two internal native APIs to the exact qualified Pi package. */
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync } from 'node:fs';
import { isAbsolute, join, relative } from 'node:path';
import { createRequire } from 'node:module';

const selected = process.env.PI_PROJECT_CONTEXT_PI_PACKAGE;
if (!selected || !isAbsolute(selected)) throw new Error('PI_PROJECT_CONTEXT_PI_PACKAGE must name the exact installed Pi package');
const root = realpathSync(selected);
const metadata = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
if (metadata.name !== '@earendil-works/pi-coding-agent' || metadata.version !== '1.4.0')
  throw new Error('Project context requires the qualified Pi1.4.0 package');
const pins = {
  'dist/core/tools/path-utils.js': '76acb2622a7f4f54c871a553501340829580f0f9caad627e7dafb8aee8b449af',
  'dist/utils/tools-manager.js': '4a8c8fc56b88dc306d10f476f6dfed2469dbd8d812251f40cc20f3e97b6928ec',
};
for (const [name, expected] of Object.entries(pins)) {
  const file = realpathSync(join(root, name));
  if (isAbsolute(relative(root, file)) || relative(root, file).split(/[\\/]/).includes('..')
      || createHash('sha256').update(readFileSync(file)).digest('hex') !== expected)
    throw new Error('Project context native API source drift: ' + name);
}
const nativeRequire = createRequire(join(root, 'package.json'));
const paths = nativeRequire(join(root, 'dist/core/tools/path-utils.js'));
const tools = nativeRequire(join(root, 'dist/utils/tools-manager.js'));
if (typeof paths.resolveReadPath !== 'function' || typeof tools.ensureTool !== 'function')
  throw new Error('Project context native API unavailable');

export const resolveReadPath: (file: string, cwd: string) => string = paths.resolveReadPath;
export const ensureTool: (name: 'rg') => Promise<string | null> = tools.ensureTool;
