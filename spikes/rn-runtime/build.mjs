// Builds the preview runtime: one minified IIFE with React, ReactDOM,
// react-native-web and the allowlisted RN libraries, plus a pinned copy of
// @babel/standalone and the preview template, all content-hashed.
//
//   node build.mjs                      development React (full error messages)
//   RN_RUNTIME_MODE=production node build.mjs
//   RN_RUNTIME_NO_FONTS=1 / RN_RUNTIME_NO_LUCIDE=1 / RN_RUNTIME_NO_SAFE_AREA_SHIM=1  (size + behavior experiments)
import * as esbuild from 'esbuild';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const ROOT = path.dirname(new URL(import.meta.url).pathname);
const MODE = process.env.RN_RUNTIME_MODE === 'production' ? 'production' : 'development';
const OUT = path.resolve(ROOT, process.env.RN_RUNTIME_OUT || 'dist');
const FONT_WEIGHTS = [300, 400, 500, 600, 700, 800];
const FONTS = [
  { family: 'RNP Inter', pkg: '@fontsource/inter', file: (w) => `inter-latin-${w}-normal.woff2` },
  { family: 'RNP Roboto', pkg: '@fontsource/roboto', file: (w) => `roboto-latin-${w}-normal.woff2` },
];

const version = (name) =>
  JSON.parse(fs.readFileSync(path.join(ROOT, 'node_modules', name, 'package.json'), 'utf8')).version;

const hits = { systemFont: 0, safeAreaShim: 0 };

// react-native-web resolves fontFamily "System" (the default for Text and
// TextInput) to a hard-coded stack that renders differently on every OS.
// Route it through a CSS variable the preview sets per device profile.
const RNW_STACK = `-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif`;
const systemFontPlugin = {
  name: 'rnw-system-font',
  setup(build) {
    build.onLoad({ filter: /react-native-web[\\/]dist[\\/]exports[\\/]StyleSheet[\\/]compiler[\\/]createReactDOMStyle\.js$/ }, async (args) => {
      const source = await fs.promises.readFile(args.path, 'utf8');
      const needle = `var SYSTEM_FONT_STACK = '${RNW_STACK}';`;
      const count = source.split(needle).length - 1;
      if (count !== 1) throw new Error(`rnw-system-font: expected 1 SYSTEM_FONT_STACK, found ${count}`);
      hits.systemFont += 1;
      return {
        contents: source.replace(needle, `var SYSTEM_FONT_STACK = 'var(--rn-preview-system-font,${RNW_STACK})';`),
        loader: 'js',
      };
    });
  },
};

// Report the device profile's insets instead of CSS env() (always 0 here).
const safeAreaShimPlugin = {
  name: 'safe-area-shim',
  setup(build) {
    if (process.env.RN_RUNTIME_NO_SAFE_AREA_SHIM) return;
    build.onResolve({ filter: /^\.\/NativeSafeAreaProvider$/ }, (args) => {
      if (!args.importer.includes(`${path.sep}react-native-safe-area-context${path.sep}`)) return undefined;
      hits.safeAreaShim += 1;
      return { path: path.join(ROOT, 'src/shims/NativeSafeAreaProvider.web.js') };
    });
  },
};

const fontsPlugin = {
  name: 'virtual-fonts',
  setup(build) {
    build.onResolve({ filter: /^virtual:fonts$/ }, () => ({ path: 'fonts', namespace: 'virtual' }));
    build.onLoad({ filter: /^fonts$/, namespace: 'virtual' }, () => {
      const faces = process.env.RN_RUNTIME_NO_FONTS
        ? []
        : FONTS.flatMap((font) =>
            FONT_WEIGHTS.map((weight) => {
              const file = path.join(ROOT, 'node_modules', font.pkg, 'files', font.file(weight));
              const data = fs.readFileSync(file).toString('base64');
              return { family: font.family, weight, src: `data:font/woff2;base64,${data}` };
            })
          );
      return { contents: `export const FONT_FACES = ${JSON.stringify(faces)};`, loader: 'js' };
    });
  },
};

const noLucidePlugin = {
  name: 'no-lucide',
  setup(build) {
    if (!process.env.RN_RUNTIME_NO_LUCIDE) return;
    build.onResolve({ filter: /^lucide-react-native$/ }, () => ({ path: 'lucide', namespace: 'virtual' }));
    build.onLoad({ filter: /^lucide$/, namespace: 'virtual' }, () => ({ contents: 'export {}', loader: 'js' }));
  },
};

const buildInfo = {
  mode: MODE,
  builtAt: new Date().toISOString(),
  versions: Object.fromEntries(
    [
      'react',
      'react-dom',
      'react-native-web',
      'react-native-svg',
      'react-native-safe-area-context',
      'lucide-react-native',
      '@babel/standalone',
    ].map((name) => [name, version(name)])
  ),
};

const result = await esbuild.build({
  entryPoints: [path.join(ROOT, 'src/runtime-entry.js')],
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: ['chrome115', 'safari16', 'firefox115'],
  minify: true,
  legalComments: 'none',
  write: false,
  metafile: true,
  outfile: 'rn-runtime.js',
  alias: { 'react-native': 'react-native-web' },
  resolveExtensions: ['.web.tsx', '.web.ts', '.web.mjs', '.web.js', '.tsx', '.ts', '.mjs', '.js', '.jsx', '.json'],
  mainFields: ['browser', 'module', 'main'],
  define: {
    'process.env.NODE_ENV': JSON.stringify(MODE),
    __DEV__: String(MODE === 'development'),
    global: 'globalThis',
    __RN_RUNTIME_BUILD__: JSON.stringify(buildInfo),
  },
  plugins: [systemFontPlugin, safeAreaShimPlugin, fontsPlugin, noLucidePlugin],
  logLevel: 'warning',
});

if (hits.systemFont !== 1) throw new Error(`rnw-system-font plugin matched ${hits.systemFont} files (expected 1)`);
if (!process.env.RN_RUNTIME_NO_SAFE_AREA_SHIM && hits.safeAreaShim < 1) {
  throw new Error('safe-area-shim plugin never matched');
}

// Exactly one copy of each core package may be bundled.
const inputs = Object.keys(result.metafile.inputs);
const copies = (pkg) =>
  new Set(
    inputs
      .map((p) => p.match(new RegExp(`node_modules/(${pkg.replace('/', '\\/')})/`)))
      .filter(Boolean)
      .map((m) => m[0])
  );
for (const pkg of ['react', 'react-dom', 'react-native-web', 'react-native', 'scheduler']) {
  const found = copies(pkg);
  if (pkg === 'react-native' && found.size > 0) throw new Error(`bundled the react-native alias package: ${[...found]}`);
  if (found.size > 1) throw new Error(`multiple copies of ${pkg}: ${[...found]}`);
}

const hash = (buf) => crypto.createHash('sha256').update(buf).digest('hex').slice(0, 12);
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const runtime = Buffer.from(result.outputFiles[0].contents);
const runtimeName = `rn-runtime.${hash(runtime)}.js`;
fs.writeFileSync(path.join(OUT, runtimeName), runtime);

const babel = fs.readFileSync(path.join(ROOT, 'node_modules/@babel/standalone/babel.min.js'));
const babelName = `babel-standalone-${version('@babel/standalone')}.${hash(babel)}.js`;
fs.writeFileSync(path.join(OUT, babelName), babel);

const template = fs.readFileSync(path.join(ROOT, 'src/preview-template.html'));
fs.writeFileSync(path.join(OUT, 'preview-template.html'), template);

// Bytes contributed to the output, grouped by package.
const byPackage = {};
for (const [file, info] of Object.entries(result.metafile.outputs['rn-runtime.js'].inputs)) {
  const match = file.match(/node_modules\/((?:@[^/]+\/)?[^/]+)/);
  const key = match ? match[1] : file.startsWith('virtual:') ? file : 'src';
  byPackage[key] = (byPackage[key] || 0) + info.bytesInOutput;
}

const sizes = (buf) => ({
  raw: buf.length,
  gzip: zlib.gzipSync(buf, { level: 9 }).length,
  brotli: zlib.brotliCompressSync(buf).length,
});

const manifest = {
  runtime: runtimeName,
  babel: babelName,
  template: 'preview-template.html',
  ...buildInfo,
  sizes: { runtime: sizes(runtime), babel: sizes(babel) },
  bytesByPackage: Object.fromEntries(Object.entries(byPackage).sort((a, b) => b[1] - a[1])),
};
fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log(JSON.stringify({ out: path.relative(ROOT, OUT), runtime: runtimeName, babel: babelName, sizes: manifest.sizes, top: Object.entries(manifest.bytesByPackage).slice(0, 8) }, null, 1));
