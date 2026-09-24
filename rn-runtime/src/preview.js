// Renders a single-file React Native screen (App.jsx) inside the preview page.
//
// Contract with the page (see preview-template.html):
//   <script id="rn-preview-config" type="application/json"> {source, profile, mode} </script>
//   window.Babel                     @babel/standalone 7.x, loaded before this runtime
//   window.__RN_PREVIEW_ERRORS__     created by the template's inline error hook
// Exposes on window, per render:
//   __RN_PREVIEW_READY__ = true      once the render settled (first commit, fonts, images)
//   __RN_PREVIEW_STATUS__            "ok" | "degraded" | "error" | "streaming"
//   __RN_PREVIEW_META__              facts about the render (render id, timings, status bar)
//
// Updates without a reload: the parent window posts
//   {type: 'rn-preview:update', source, profile?, mode?}
// and, after each render settles, receives
//   {type: 'rn-preview:status', renderId, status, errors, meta}.
// In "streaming" mode the source is a file still being written: syntax and module errors keep the
// last good render on screen instead of replacing it with the error panel.
import * as React from 'react';
import { AppRegistry, ScrollView, Text, View } from 'react-native-web';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { FONT_FACES } from 'virtual:fonts';
import { lintNativeCompat } from './lint.js';
import { fontFaceDescriptors } from './text-metrics.js';

const FILENAME = 'App.jsx';
// new Function() prepends "function anonymous(require,module,exports,React\n) {\n".
const FUNCTION_HEADER_LINES = 2;
const IMAGE_SETTLE_TIMEOUT_MS = 5000;
const MAX_ERRORS = 50;
const PLATFORM_FONT = { ios: 'RNP Inter', android: 'RNP Roboto' };

let modules = null;
let currentRoot = null;
let renderId = 0;
let lastGoodApp = null;
let appliedFontKey = null;

function errorList() {
  return (window.__RN_PREVIEW_ERRORS__ = window.__RN_PREVIEW_ERRORS__ || []);
}

export function reportError(entry) {
  const errors = errorList();
  const key = `${entry.kind}|${entry.message}|${entry.line || ''}`;
  if (errors.length >= MAX_ERRORS || errors.some((e) => e.key === key)) return;
  if (entry.kind === 'runtime') {
    // React also logs every boundary-caught error via console.error; keep one.
    for (let i = errors.length - 1; i >= 0; i--) {
      if (errors[i].kind === 'console_error' && errors[i].message.includes(entry.message)) errors.splice(i, 1);
    }
  }
  errors.push(Object.assign({ key }, entry));
  // Prefixed so the Playwright collector can pick these out of other logs.
  window.__RN_PREVIEW_CONSOLE_ERROR__(`[rn-preview] ${entry.kind}: ${entry.message}`);
}

// ---------- device profile: fonts ----------

function applyProfile(profile) {
  window.__RN_PREVIEW_PROFILE__ = profile;
  const platform = profile.platform === 'android' ? 'android' : 'ios';
  const family = PLATFORM_FONT[platform];
  // Calibrated metrics can be switched off (calibration measures the raw fonts).
  const descriptors = profile.textMetrics === false ? '' : fontFaceDescriptors(platform);
  const fontKey = `${family}|${descriptors}`;
  if (fontKey === appliedFontKey) return;
  appliedFontKey = fontKey;
  const faces = FONT_FACES.filter((face) => face.family === family)
    .map(
      (face) =>
        `@font-face{font-family:"${face.family}";font-style:normal;font-weight:${face.weight};` +
        `font-display:block;${descriptors}src:url(${face.src}) format("woff2");}`
    )
    .join('\n');
  let style = document.getElementById('rn-preview-fonts');
  if (!style) {
    style = document.createElement('style');
    style.id = 'rn-preview-fonts';
    document.head.appendChild(style);
  }
  style.textContent = `${faces}\n:root{--rn-preview-system-font:"${family}";}`;
  // Start loading every weight now, so fonts.ready covers them.
  for (const face of FONT_FACES) {
    if (face.family === family) document.fonts.load(`${face.weight} 16px "${family}"`);
  }
}

// ---------- image settle tracking ----------

const imageState = { pending: 0 };

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
      reportError({ kind: 'image_load', message: `Image failed to load: ${String(image.src).slice(0, 200)}` });
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
      const domPending = Array.from(document.images).filter((img) => !img.complete).length;
      const pending = imageState.pending + domPending;
      if (pending === 0) return resolve();
      if (performance.now() - start > IMAGE_SETTLE_TIMEOUT_MS) {
        reportError({
          kind: 'image_settle_timeout',
          message: `${pending} image(s) still loading after ${IMAGE_SETTLE_TIMEOUT_MS / 1000} s; the screenshot may show them missing.`,
        });
        return resolve();
      }
      setTimeout(tick, 50);
    };
    tick();
  });
}

// ---------- settle + status ----------

function statusFor(errors, streaming) {
  if (errors.some((e) => e.fatal)) return 'error';
  if (streaming) return 'streaming';
  return errors.length ? 'degraded' : 'ok';
}

async function settle(id, { streaming = false } = {}) {
  const meta = window.__RN_PREVIEW_META__;
  if (id === renderId) meta.firstCommitMs = Math.round(performance.now() - meta.startedAt);
  try {
    await document.fonts.ready;
  } catch (e) {
    /* fonts API unavailable */
  }
  await waitForImages();
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  if (id !== renderId) return; // superseded by a newer render
  const errors = errorList();
  const status = statusFor(errors, streaming);
  meta.readyMs = Math.round(performance.now() - meta.startedAt);
  // A render the error boundary didn't have to catch is the fallback for later streaming updates.
  if (meta.app && !meta.caught && status !== 'error') lastGoodApp = meta.app;
  window.__RN_PREVIEW_STATUS__ = status;
  window.__RN_PREVIEW_READY__ = true;
  if (window.parent && window.parent !== window) {
    const publicErrors = errors.map(({ key, ...rest }) => rest);
    const { app, ...publicMeta } = meta;
    window.parent.postMessage({ type: 'rn-preview:status', renderId: id, status, errors: publicErrors, meta: publicMeta }, '*');
  }
}

// ---------- error panel (RN primitives, so it shows in screenshots) ----------

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
        React.createElement(Text, { style: { color: '#7F1D1D', fontSize: 12, marginTop: 2 } }, error.message),
        error.frame
          ? React.createElement(Text, { style: { color: '#7F1D1D', fontSize: 12, fontFamily: 'monospace', marginTop: 6 } }, error.frame)
          : null
      )
    )
  );
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
    window.__RN_PREVIEW_META__.caught = true;
    if (this.props.streaming) {
      // A half-written file failing at runtime is expected; drop React's log of it.
      const message = String((error && error.message) || error);
      const errors = errorList();
      for (let i = errors.length - 1; i >= 0; i--) {
        if (errors[i].kind === 'console_error' && errors[i].message.includes(message)) errors.splice(i, 1);
      }
      return;
    }
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
      if (this.props.streaming) {
        // Show the last good render (or nothing yet) until the file is complete.
        return this.props.fallbackApp
          ? React.createElement(ErrorBoundary, null, React.createElement(this.props.fallbackApp))
          : null;
      }
      return React.createElement(ErrorPanel, { errors: errorList().filter((e) => e.fatal) });
    }
    return this.props.children;
  }
}

function SettleSignal({ id, streaming }) {
  React.useEffect(() => {
    settle(id, { streaming });
  }, [id, streaming]);
  return null;
}

// ---------- source locations ----------

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

// Babel reports "/App.jsx: Unterminated JSX contents. (8:11)\n\n  6 | ...": keep the
// sentence as the message, the code frame separately, and 1-based line/column.
function transformError(error) {
  const text = String((error && error.message) || error);
  const [first, ...rest] = text.split('\n');
  return {
    kind: 'transform',
    fatal: true,
    message: first.replace(/^\/?App\.jsx:\s*/, '').replace(/\s*\(\d+:\d+\)\s*$/, ''),
    line: error && error.loc ? error.loc.line : undefined,
    column: error && error.loc ? error.loc.column + 1 : undefined,
    frame: rest.join('\n').replace(/^\n+/, '') || undefined,
  };
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

function evaluate(code) {
  const require = (specifier) => {
    if (Object.prototype.hasOwnProperty.call(modules, specifier)) return modules[specifier];
    const error = new Error(`Cannot import "${specifier}". Allowed modules: ${Object.keys(modules).join(', ')}.`);
    error.rnPreviewKind = 'import';
    throw error;
  };
  const module = { exports: {} };
  // eslint-disable-next-line no-new-func
  const factory = new Function('require', 'module', 'exports', 'React', `${code}\n//# sourceURL=${FILENAME}`);
  factory(require, module, module.exports, modules.react);
  const exported = module.exports;
  const App = exported && (exported.default || (typeof exported === 'function' ? exported : null));
  if (typeof App !== 'function' && !(App && typeof App === 'object' && App.$$typeof)) {
    const error = new Error(`${FILENAME} must \`export default\` a React component.`);
    error.rnPreviewKind = 'no_default_export';
    throw error;
  }
  return App;
}

// ---------- mounting ----------

function mount(element) {
  if (currentRoot) currentRoot.unmount();
  AppRegistry.registerComponent('App', () => () => element);
  currentRoot = AppRegistry.runApplication('App', { rootTag: document.getElementById('root') });
}

function mountErrorPanel(id) {
  mount(
    React.createElement(
      React.Fragment,
      null,
      React.createElement(ErrorPanel, { errors: errorList().filter((e) => e.fatal) }),
      React.createElement(SettleSignal, { id, streaming: false })
    )
  );
}

function lint(source) {
  try {
    return lintNativeCompat(window.Babel, source, FILENAME);
  } catch (error) {
    return []; // the transform already accepted this source; never block on the lint itself
  }
}

let badge = null;
function setStreamingBadge(visible) {
  if (!visible) {
    if (badge) badge.hidden = true;
    return;
  }
  if (!badge) {
    badge = document.createElement('div');
    badge.id = 'rn-preview-streaming';
    badge.textContent = 'Writing App.jsx…';
    badge.style.cssText =
      'position:fixed;left:50%;bottom:12px;transform:translateX(-50%);z-index:2147483647;' +
      'font:500 12px/1 system-ui,sans-serif;color:#fff;background:rgba(24,24,27,.82);' +
      'padding:6px 10px;border-radius:999px;pointer-events:none;';
    document.body.appendChild(badge);
  }
  badge.hidden = false;
}

function render(config) {
  const id = ++renderId;
  const streaming = config.mode === 'streaming';
  const profile = config.profile || {};
  window.__RN_PREVIEW_READY__ = false;
  window.__RN_PREVIEW_STATUS__ = undefined;
  errorList().length = 0;
  const meta = (window.__RN_PREVIEW_META__ = {
    renderId: id,
    mode: streaming ? 'streaming' : 'final',
    runtime: window.__RN_RUNTIME__,
    startedAt: performance.now(),
  });
  applyProfile(profile);
  setStreamingBadge(streaming);

  let App;
  const t0 = performance.now();
  try {
    const code = transform(config.source);
    meta.transformMs = Math.round(performance.now() - t0);
    if (!streaming) {
      // Only finished files: a half-written one would raise false alarms.
      const findings = lint(config.source);
      meta.lintMs = Math.round(performance.now() - t0) - meta.transformMs;
      findings.forEach(reportError);
      if (findings.some((finding) => finding.fatal)) return mountErrorPanel(id);
    }
    App = evaluate(code);
  } catch (error) {
    if (streaming) {
      // The file is still being written: keep the last render (or a blank screen).
      errorList().length = 0;
      if (currentRoot) settle(id, { streaming: true });
      else mount(React.createElement(SettleSignal, { id, streaming: true }));
      return;
    }
    if (error && error.loc) {
      reportError(transformError(error));
    } else {
      const location = locateInSource(error);
      reportError({
        kind: (error && error.rnPreviewKind) || 'module',
        fatal: true,
        message: String((error && error.message) || error),
        line: location && location.line,
      });
    }
    mountErrorPanel(id);
    return;
  }
  meta.app = App;

  const insets = Object.assign({ top: 0, right: 0, bottom: 0, left: 0 }, profile.insets);
  const initialMetrics = {
    insets,
    frame: { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight },
  };
  mount(
    React.createElement(
      SafeAreaProvider,
      { initialMetrics },
      React.createElement(
        ErrorBoundary,
        { streaming, fallbackApp: streaming && lastGoodApp !== App ? lastGoodApp : null },
        React.createElement(App)
      ),
      React.createElement(SettleSignal, { id, streaming })
    )
  );
}

export function boot(registry) {
  modules = registry;
  trackImages();
  window.addEventListener('message', (event) => {
    const data = event.data;
    if (event.source !== window.parent || !data || data.type !== 'rn-preview:update') return;
    if (typeof data.source !== 'string') return;
    render({ source: data.source, profile: data.profile || window.__RN_PREVIEW_PROFILE__ || {}, mode: data.mode });
  });
  const config = JSON.parse(document.getElementById('rn-preview-config').textContent);
  render(config);
}
