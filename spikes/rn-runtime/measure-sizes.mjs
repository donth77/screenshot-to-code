// Builds the runtime in several configurations and prints a size table.
// Usage: node measure-sizes.mjs <scratch-dir>
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const scratch = path.resolve(process.argv[2] || 'dist-sizes');
const variants = {
  'dev (shipped)': { RN_RUNTIME_MODE: 'development' },
  'dev, no lucide': { RN_RUNTIME_MODE: 'development', RN_RUNTIME_NO_LUCIDE: '1' },
  'dev, no fonts': { RN_RUNTIME_MODE: 'development', RN_RUNTIME_NO_FONTS: '1' },
  production: { RN_RUNTIME_MODE: 'production' },
  'production, no lucide': { RN_RUNTIME_MODE: 'production', RN_RUNTIME_NO_LUCIDE: '1' },
  'production, no lucide, no fonts': {
    RN_RUNTIME_MODE: 'production',
    RN_RUNTIME_NO_LUCIDE: '1',
    RN_RUNTIME_NO_FONTS: '1',
  },
};

const kb = (n) => `${Math.round(n / 1024)} KB`;
const rows = [];
for (const [name, env] of Object.entries(variants)) {
  const out = path.join(scratch, name.replace(/[^a-z0-9]+/gi, '-'));
  execFileSync('node', ['build.mjs'], {
    cwd: path.dirname(new URL(import.meta.url).pathname),
    env: { ...process.env, ...env, RN_RUNTIME_OUT: out },
    stdio: 'ignore',
  });
  const manifest = JSON.parse(fs.readFileSync(path.join(out, 'manifest.json'), 'utf8'));
  const s = manifest.sizes.runtime;
  rows.push(`| ${name} | ${kb(s.raw)} | ${kb(s.gzip)} | ${kb(s.brotli)} |`);
  if (name === 'dev (shipped)') {
    const b = manifest.sizes.babel;
    rows.unshift(`| @babel/standalone 7.25.6 (separate file) | ${kb(b.raw)} | ${kb(b.gzip)} | ${kb(b.brotli)} |`);
    console.log('bytes by package (dev):', JSON.stringify(manifest.bytesByPackage));
  }
}
console.log('| build | raw | gzip -9 | brotli |\n|---|---|---|---|\n' + rows.join('\n'));
