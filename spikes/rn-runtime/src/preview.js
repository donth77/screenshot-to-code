// Boots a single-file React Native screen (App.jsx) inside the preview page.
//
// Contract with the page (see preview-template.html):
//   <script id="rn-preview-config" type="application/json"> {source, profile} </script>
//   window.Babel                     @babel/standalone 7.x, loaded before this runtime
//   window.__RN_PREVIEW_ERRORS__     created by the template's inline error hook
// Exposes on window:
//   __RN_PREVIEW_READY__ = true      once the first render settled (fonts, images)
//   __RN_PREVIEW_STATUS__            "ok" | "error"
//   __RN_PREVIEW_META__              facts about the render (status bar style, timings)
import * as React from 'react';
import { AppRegistry, ScrollView, Text, View } from 'react-native-web';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { FONT_FACES } from 'virtual:fonts';

const FILENAME = 'App.jsx';
// new Function() prepends "function anonymous(require,module,exports,React\n) {\n".
const FUNCTION_HEADER_LINES = 2;
const IMAGE_SETTLE_TIMEOUT_MS = 5000;
const PLATFORM_FONT = { ios: 'RNP Inter', android: 'RNP Roboto' };

export function reportError(entry) {
  const errors = (window.__RN_PREVIEW_ERRORS__ = window.__RN_PREVIEW_ERRORS__ || []);
  const key = `${entry.kind}|${entry.message}|${entry.line || ''}`;
  if (errors.some((e) => e.key === key)) return;
  if (entry.kind === 'runtime') {
    // React also logs every boundary-caught error via console.error; keep one.
    for (let i = errors.length - 1; i >= 0; i--) {
      if (errors[i].kind === 'console_error' && errors[i].message.includes(entry.message)) errors.splice(i, 1);
    }
  }
  errors.push(Object.assign({ key }, entry));
  if (errors.length <= 50) {
    // Prefixed so the Playwright collector can pick these out of other logs.
    window.__RN_PREVIEW_CONSOLE_ERROR__(`[rn-preview] ${entry.kind}: ${entry.message}`);
  }
}

// ---------- device profile: fonts, background ----------

function applyProfile(profile) {
  const platform = profile.platform === 'android' ? 'android' : 'ios';
  const family = PLATFORM_FONT[platform];
  const faces = FONT_FACES.filter((face) => face.family === family)
    .map(
      (face) =>
        `@font-face{font-family:"${face.family}";font-style:normal;font-weight:${face.weight};` +
        `font-display:block;src:url(${face.src}) format("woff2");}`
    )
    .join('\n');
  const style = document.createElement('style');
  style.id = 'rn-preview-fonts';
  style.textContent = `${faces}\n:root{--rn-preview-system-font:"${family}";}`;
  document.head.appendChild(style);
  // Kick off font loading for every weight now, so fonts.ready covers them.
  for (const face of FONT_FACES) {
    if (face.family === family) document.fonts.load(`${face.weight} 16px "${family}"`);
  }
}

// ---------- image settle tracking ----------

const imageState = { pending: 0, failed: [] };

function trackImages() {
  const NativeImage = window.Image;
  function TrackedImage(width, height) {
    const image = new NativeImage(width, height);
    imageState.pending += 1;
    let done = false;
    const finish = () => {
      if (!done) {
        done = true;
        imageState.pending -= 1;
      }
    };
    image.addEventListener('load', finish);
    image.addEventListener('error', () => {
      imageState.failed.push(image.src);
      reportError({ kind: 'image_load', message: `Image failed to load: ${image.src.slice(0, 200)}` });
      finish();
    });
    return image;
  }
  TrackedImage.prototype = NativeImage.prototype;
  window.Image = TrackedImage;
}

function waitForImages() {
  const start = performance.now();
  return new Promise((resolve) => {
    const tick = () => {
      const domPending = Array.from(document.images).some((img) => !img.complete);
      if ((imageState.pending === 0 && !domPending) || performance.now() - start > IMAGE_SETTLE_TIMEOUT_MS) {
        resolve();
      } else {
        setTimeout(tick, 50);
      }
    };
    tick();
  });
}

let readyScheduled = false;
async function markReady(status) {
  if (readyScheduled) return;
  readyScheduled = true;
  const meta = (window.__RN_PREVIEW_META__ = window.__RN_PREVIEW_META__ || {});
  meta.firstCommitMs = Math.round(performance.now());
  try {
    await document.fonts.ready;
  } catch (e) {
    /* fonts API unavailable */
  }
  await waitForImages();
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  meta.readyMs = Math.round(performance.now());
  const errors = window.__RN_PREVIEW_ERRORS__;
  // "degraded": rendered, but something non-fatal needs fixing (unknown icon,
  // failed image, console error).
  window.__RN_PREVIEW_STATUS__ =
    status || (errors.some((e) => e.fatal) ? 'error' : errors.length ? 'degraded' : 'ok');
  window.__RN_PREVIEW_READY__ = true;
}

// ---------- error panel (rendered with RN primitives so it shows in screenshots) ----------

function ErrorPanel({ errors }) {
  return React.createElement(
    ScrollView,
    { testID: 'rn-preview-error', style: { flex: 1, backgroundColor: '#FEF2F2' }, contentContainerStyle: { padding: 16 } },
    React.createElement(Text, { style: { color: '#B91C1C', fontSize: 16, fontWeight: '700', marginBottom: 8 } }, 'Preview error'),
    ...errors.map((error, index) =>
      React.createElement(
        View,
        { key: index, style: { marginBottom: 12 } },
        React.createElement(
          Text,
          { style: { color: '#7F1D1D', fontSize: 13, fontWeight: '600' } },
          `${error.kind}${error.line ? ` at ${FILENAME}:${error.line}${error.column ? `:${error.column}` : ''}` : ''}`
        ),
        React.createElement(Text, { style: { color: '#7F1D1D', fontSize: 12, fontFamily: 'monospace' } }, error.frame || error.message)
      )
    )
  );
}

function renderFatal() {
  const errors = window.__RN_PREVIEW_ERRORS__.filter((e) => e.fatal);
  AppRegistry.registerComponent('PreviewError', () => () => React.createElement(ErrorPanel, { errors }));
  AppRegistry.runApplication('PreviewError', { rootTag: document.getElementById('root') });
  markReady('error');
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    const location = locateInSource(error);
    reportError({
      kind: 'runtime',
      fatal: true,
      message: String((error && error.message) || error),
      // Columns refer to the transformed code, so only the line is reliable.
      line: location && location.line,
      componentStack: sourceComponentStack(info && info.componentStack),
    });
  }
  render() {
    if (this.state.error) {
      return React.createElement(ErrorPanel, { errors: window.__RN_PREVIEW_ERRORS__.filter((e) => e.fatal) });
    }
    return this.props.children;
  }
}

function ReadySignal() {
  React.useEffect(() => {
    markReady();
  }, []);
  return null;
}

// Maps "App.jsx:LINE:COL" in a stack trace back to the source (retainLines keeps
// transformed lines aligned with the source; the Function header adds 2).
export function locateInSource(error) {
  const stack = String((error && error.stack) || '');
  const match = stack.match(new RegExp(`${FILENAME.replace('.', '\\.')}:(\\d+):(\\d+)`));
  if (!match) return null;
  return { line: Number(match[1]) - FUNCTION_HEADER_LINES, column: Number(match[2]) };
}

// "at Price (App.jsx:6:18)\n at div (<anonymous>)\n at View (http://.../rn-runtime.js)
// \n at App (<anonymous>)" -> "Price (App.jsx:4) < App". Keeps the user's
// components (App.jsx frames with source lines, capitalized anonymous frames by
// name); drops DOM tags and runtime-internal frames.
function sourceComponentStack(componentStack) {
  const frames = [];
  const file = FILENAME.replace('.', '\\.');
  const pattern = new RegExp(`at (\\S+) \\((?:${file}:(\\d+):\\d+|<anonymous>)\\)`, 'g');
  for (const match of String(componentStack || '').matchAll(pattern)) {
    if (match[2]) frames.push(`${match[1]} (${FILENAME}:${Number(match[2]) - FUNCTION_HEADER_LINES})`);
    else if (/^[A-Z]/.test(match[1])) frames.push(match[1]);
  }
  return frames.slice(0, 8).join(' < ');
}

// ---------- transform + execute ----------

export function transform(source) {
  return window.Babel.transform(source, {
    filename: FILENAME,
    sourceType: 'module',
    retainLines: true,
    presets: [['react', { runtime: 'classic' }]],
    plugins: ['transform-modules-commonjs'],
  }).code;
}

export function boot(modules) {
  const configElement = document.getElementById('rn-preview-config');
  const config = JSON.parse(configElement.textContent);
  const profile = config.profile || {};
  window.__RN_PREVIEW_PROFILE__ = profile;
  applyProfile(profile);
  trackImages();

  const meta = (window.__RN_PREVIEW_META__ = window.__RN_PREVIEW_META__ || {});
  meta.runtime = window.__RN_RUNTIME__;

  let code;
  const t0 = performance.now();
  try {
    code = transform(config.source);
  } catch (error) {
    reportError({
      kind: 'transform',
      fatal: true,
      message: String(error.message).split('\n')[0],
      line: error.loc && error.loc.line,
      column: error.loc && error.loc.column + 1,
      frame: String(error.message),
    });
    return renderFatal();
  }
  meta.transformMs = Math.round(performance.now() - t0);

  const require = (specifier) => {
    if (Object.prototype.hasOwnProperty.call(modules, specifier)) return modules[specifier];
    const error = new Error(
      `Cannot import "${specifier}". Allowed modules: ${Object.keys(modules).join(', ')}.`
    );
    error.rnPreviewKind = 'import';
    throw error;
  };

  const module = { exports: {} };
  try {
    // eslint-disable-next-line no-new-func
    const factory = new Function('require', 'module', 'exports', 'React', `${code}\n//# sourceURL=${FILENAME}`);
    factory(require, module, module.exports, modules.react);
  } catch (error) {
    const location = locateInSource(error);
    reportError({
      kind: error.rnPreviewKind || 'module',
      fatal: true,
      message: String(error.message),
      line: location && location.line,
    });
    return renderFatal();
  }

  const exported = module.exports;
  const App = exported && (exported.default || (typeof exported === 'function' ? exported : null));
  if (typeof App !== 'function' && !(App && typeof App === 'object' && App.$$typeof)) {
    reportError({ kind: 'no_default_export', fatal: true, message: `${FILENAME} must \`export default\` a React component.` });
    return renderFatal();
  }

  const insets = Object.assign({ top: 0, right: 0, bottom: 0, left: 0 }, profile.insets);
  const initialMetrics = {
    insets,
    frame: { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight },
  };
  function PreviewRoot() {
    return React.createElement(
      SafeAreaProvider,
      { initialMetrics },
      React.createElement(ErrorBoundary, null, React.createElement(App)),
      React.createElement(ReadySignal)
    );
  }
  AppRegistry.registerComponent('App', () => PreviewRoot);
  AppRegistry.runApplication('App', { rootTag: document.getElementById('root') });
}
