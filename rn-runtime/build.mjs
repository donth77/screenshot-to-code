// Builds the React Native preview runtime into dist/:
//
//   rn-runtime.<hash>.js           one minified IIFE: React, ReactDOM, react-native-web and the
//                                  allowlisted React Native libraries, plus the preview boot code
//   babel-standalone-<v>.<hash>.js a pinned copy of @babel/standalone (classic JSX runtime)
//   preview-template.html          the one template the backend and frontend both fill
//   manifest.json                  file names, versions and sizes (read by backend and frontend)
//   expo-sdk.json, device-profiles.json   data the backend and frontend share
//
// The build fails when an invariant breaks: the font or safe-area patches stop matching, a
// core package is bundled twice, versions drift from expo-sdk.json, or the size budget is blown.
//
//   node build.mjs
//   RN_RUNTIME_MODE=production node build.mjs      (experiments only; the stack ships development)
//   RN_RUNTIME_NO_FONTS=1 / RN_RUNTIME_NO_LUCIDE=1 / RN_RUNTIME_NO_SAFE_AREA_SHIM=1
//   RN_RUNTIME_OUT=<dir>                           (default: dist)
import * as esbuild from 'esbuild';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const ROOT = path.dirname(new URL(import.meta.url).pathname);
const MODE = process.env.RN_RUNTIME_MODE === 'production' ? 'production' : 'development';
const OUT = path.resolve(ROOT, process.env.RN_RUNTIME_OUT || 'dist');
const EXPERIMENT = Boolean(
  process.env.RN_RUNTIME_MODE || process.env.RN_RUNTIME_NO_FONTS || process.env.RN_RUNTIME_NO_LUCIDE || process.env.RN_RUNTIME_NO_SAFE_AREA_SHIM
);

// Size budget for the shipped runtime (KB = 1024 bytes). Babel is a fixed third-party file.
const BUDGET = { rawKB: 1900, gzipKB: 700 };

const FONT_WEIGHTS = [300, 400, 500, 600, 700, 800];
const FONTS = [
  { family: 'RNP Inter', pkg: '@fontsource/inter', file: (w) => `inter-latin-${w}-normal.woff2` },
  { family: 'RNP Roboto', pkg: '@fontsource/roboto', file: (w) => `roboto-latin-${w}-normal.woff2` },
];

const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8'));
const version = (name) => readJson(path.join(ROOT, 'node_modules', name, 'package.json')).version;

function fail(message) {
  console.error(`rn-runtime build failed: ${message}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Version parity with the Expo SDK the export targets (RNW-5)
// ---------------------------------------------------------------------------

const expoSdk = readJson(path.join(ROOT, 'expo-sdk.json'));
const PARITY = ['react', 'react-dom', 'react-native-web', 'react-native-svg', 'react-native-safe-area-context', 'lucide-react-native'];
for (const name of PARITY) {
  const want = expoSdk.dependencies[name];
  const have = version(name);
  if (want !== have) fail(`${name} is ${have} but expo-sdk.json pins ${want}`);
}
if (version('@react-native/assets-registry') !== expoSdk.dependencies['react-native']) {
  fail(`@react-native/assets-registry must match react-native ${expoSdk.dependencies['react-native']}`);
}

// ---------------------------------------------------------------------------
// Plugins
// ---------------------------------------------------------------------------

const hits = { systemFont: 0, safeAreaShim: 0 };

// react-native-web resolves fontFamily "System" (the default for Text and TextInput) to a
// hard-coded stack that renders differently on every OS. Route it through a CSS variable the
// preview sets per device profile.
const RNW_STACK = `-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif`;
const systemFontPlugin = {
  name: 'rnw-system-font',
  setup(build) {
    build.onLoad(
      { filter: /react-native-web[\\/]dist[\\/]exports[\\/]StyleSheet[\\/]compiler[\\/]createReactDOMStyle\.js$/ },
      async (args) => {
        const source = await fs.promises.readFile(args.path, 'utf8');
        const needle = `var SYSTEM_FONT_STACK = '${RNW_STACK}';`;
        const count = source.split(needle).length - 1;
        if (count !== 1) throw new Error(`rnw-system-font: expected 1 SYSTEM_FONT_STACK, found ${count}`);
        hits.systemFont += 1;
        return {
          contents: source.replace(needle, `var SYSTEM_FONT_STACK = 'var(--rn-preview-system-font,${RNW_STACK})';`),
          loader: 'js',
        };
      }
    );
  },
};

// The stock web NativeSafeAreaProvider overwrites initialMetrics with CSS env() insets (always 0
// in Chromium). Report the device profile's insets instead.
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

// ---------------------------------------------------------------------------
// Build
// ---------------------------------------------------------------------------

const buildInfo = {
  mode: MODE,
  expoSdkVersion: expoSdk.sdk,
  versions: Object.fromEntries(
    [...PARITY, '@react-native/assets-registry', '@babel/standalone'].map((name) => [name, version(name)])
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

if (hits.systemFont !== 1) fail(`rnw-system-font plugin matched ${hits.systemFont} files (expected 1)`);
if (!process.env.RN_RUNTIME_NO_SAFE_AREA_SHIM && hits.safeAreaShim < 1) fail('safe-area-shim plugin never matched');

// Exactly one copy of each core package. With pnpm, copies live under different
// node_modules/.pnpm/<id>/ prefixes, so compare the resolved package roots.
const inputs = Object.keys(result.metafile.inputs);
function packageRoots(pkg) {
  const marker = `node_modules/${pkg}/`;
  const roots = new Set();
  for (const input of inputs) {
    const at = input.lastIndexOf(marker);
    if (at >= 0) roots.add(input.slice(0, at + marker.length));
  }
  return roots;
}
for (const pkg of ['react', 'react-dom', 'react-native-web', 'scheduler']) {
  const roots = packageRoots(pkg);
  if (roots.size !== 1) fail(`expected one copy of ${pkg}, found ${roots.size}: ${[...roots].join(', ')}`);
}
if (packageRoots('react-native').size > 0) fail('bundled files from the react-native alias package; alias it to react-native-web');

const runtime = Buffer.from(result.outputFiles[0].contents);
if (runtime.includes('</script')) fail('output contains a raw </script sequence');

const sizes = (buf) => ({
  raw: buf.length,
  gzip: zlib.gzipSync(buf, { level: 9 }).length,
  brotli: zlib.brotliCompressSync(buf).length,
});
const runtimeSizes = sizes(runtime);
if (!EXPERIMENT) {
  if (runtimeSizes.raw > BUDGET.rawKB * 1024) fail(`runtime is ${Math.round(runtimeSizes.raw / 1024)} KB raw, over the ${BUDGET.rawKB} KB budget`);
  if (runtimeSizes.gzip > BUDGET.gzipKB * 1024) fail(`runtime is ${Math.round(runtimeSizes.gzip / 1024)} KB gzip, over the ${BUDGET.gzipKB} KB budget`);
}

// ---------------------------------------------------------------------------
// Write dist/
// ---------------------------------------------------------------------------

const hash = (buf) => crypto.createHash('sha256').update(buf).digest('hex').slice(0, 12);
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const runtimeName = `rn-runtime.${hash(runtime)}.js`;
fs.writeFileSync(path.join(OUT, runtimeName), runtime);

const babel = fs.readFileSync(path.join(ROOT, 'node_modules/@babel/standalone/babel.min.js'));
const babelName = `babel-standalone-${version('@babel/standalone')}.${hash(babel)}.js`;
fs.writeFileSync(path.join(OUT, babelName), babel);

for (const file of ['preview-template.html']) fs.copyFileSync(path.join(ROOT, 'src', file), path.join(OUT, file));
for (const file of ['expo-sdk.json', 'device-profiles.json']) fs.copyFileSync(path.join(ROOT, file), path.join(OUT, file));

const byPackage = {};
for (const [file, info] of Object.entries(result.metafile.outputs['rn-runtime.js'].inputs)) {
  const match = file.match(/.*node_modules\/((?:@[^/]+\/)?[^/]+)/);
  const key = match ? match[1] : file.startsWith('virtual:') ? file : 'src';
  byPackage[key] = (byPackage[key] || 0) + info.bytesInOutput;
}

const manifest = {
  runtime: runtimeName,
  babel: babelName,
  template: 'preview-template.html',
  expoSdk: 'expo-sdk.json',
  deviceProfiles: 'device-profiles.json',
  ...buildInfo,
  sizes: { runtime: runtimeSizes, babel: sizes(babel) },
  budget: BUDGET,
  bytesByPackage: Object.fromEntries(Object.entries(byPackage).sort((a, b) => b[1] - a[1])),
};
fs.writeFileSync(path.join(OUT, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);

const kb = (n) => `${Math.round(n / 1024)} KB`;
console.log(
  `rn-runtime ${MODE}: ${path.relative(ROOT, OUT)}/${runtimeName} ${kb(runtimeSizes.raw)} raw, ${kb(runtimeSizes.gzip)} gzip ` +
    `(budget ${BUDGET.rawKB} / ${BUDGET.gzipKB} KB); Expo SDK ${expoSdk.sdk}`
);
