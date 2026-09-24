// Browser-global runtime for the React Native preview (Phase 0 spike).
//
// Bundles exactly one React + ReactDOM with react-native-web and the allowlisted
// React Native libraries, then exposes:
//   window.React            classic JSX compiles to React.createElement
//   window.ReactDOM
//   window.__RN_MODULES__   import specifier -> module, allowlist only
//   window.__RN_RUNTIME__   build facts (versions) for parity checks
//   window.__RN_PREVIEW__   { boot, transform } used by preview-template.html
// Default imports give the CommonJS module.exports objects themselves (the same
// objects every bundled library resolves), not esbuild namespace wrappers.
import React from 'react';
import ReactDOM from 'react-dom';
import * as RNW from 'react-native-web';
import * as SafeArea from 'react-native-safe-area-context';
import * as Svg from 'react-native-svg';
import * as Lucide from 'lucide-react-native';
import * as StatusBar from './shims/expo-status-bar.js';
import { boot, reportError, transform } from './preview.js';

// Babel's CommonJS interop only reads `.default` from objects flagged
// __esModule; esbuild namespace objects are not, so `import Svg from
// 'react-native-svg'` would otherwise yield the whole namespace.
function esModule(namespace, extra) {
  return Object.freeze(Object.assign({}, namespace, extra, { __esModule: true }));
}

const ICON_NAMES = Object.keys(Lucide).filter(
  (name) => /^[A-Z]/.test(name) && !name.startsWith('Lucide') && !name.endsWith('Icon') && name !== 'Icon'
);

function suggestIcons(name) {
  const base = name.replace(/^Lucide/, '').replace(/Icon$/, '').toLowerCase();
  const parts = name.replace(/Icon$/, '').split(/(?=[A-Z])/).filter((part) => part.length > 2);
  return ICON_NAMES.map((candidate) => {
    const lower = candidate.toLowerCase();
    let score = 0;
    if (lower === base) score = 100;
    else if (lower.includes(base) || base.includes(lower)) score = 50 - Math.abs(lower.length - base.length);
    else score = parts.filter((part) => candidate.includes(part)).length * 10;
    return [score, candidate];
  })
    .filter(([score]) => score > 0)
    .sort((a, b) => b[0] - a[0])
    .slice(0, 5)
    .map(([, candidate]) => candidate);
}

const placeholders = new Map();
function placeholderIcon(name) {
  if (!placeholders.has(name)) {
    const Placeholder = React.forwardRef(function UnknownIcon(props, ref) {
      const size = props.size || 24;
      return React.createElement(
        RNW.View,
        {
          ref,
          testID: props.testID || `unknown-icon-${name}`,
          style: [
            {
              width: size,
              height: size,
              borderWidth: 1,
              borderStyle: 'dashed',
              borderColor: '#E11D48',
              borderRadius: 4,
              alignItems: 'center',
              justifyContent: 'center',
            },
            props.style,
          ],
        },
        React.createElement(RNW.Text, { style: { color: '#E11D48', fontSize: Math.max(8, size * 0.5) } }, '?')
      );
    });
    Placeholder.displayName = `UnknownIcon(${name})`;
    placeholders.set(name, Placeholder);
  }
  return placeholders.get(name);
}

const lucideModule = new Proxy(esModule(Lucide), {
  get(target, prop, receiver) {
    if (typeof prop === 'string' && !(prop in target) && /^[A-Z]/.test(prop)) {
      reportError({
        kind: 'unknown_icon',
        message: `lucide-react-native has no icon "${prop}". Closest: ${suggestIcons(prop).join(', ') || 'none'}.`,
        name: prop,
      });
      return placeholderIcon(prop);
    }
    return Reflect.get(target, prop, receiver);
  },
});

// On native, `import RN from 'react-native'` yields the module object, so keep
// that for default. Unknown capitalized names are flagged instead of silently
// rendering `undefined` ("Element type is invalid").
const reactNativeModule = new Proxy(esModule(RNW, { default: RNW }), {
  get(target, prop, receiver) {
    if (typeof prop === 'string' && !(prop in target) && /^[A-Z]/.test(prop)) {
      reportError({
        kind: 'unknown_export',
        message: `react-native (web preview) has no export "${prop}".`,
        name: prop,
      });
    }
    return Reflect.get(target, prop, receiver);
  },
});

const modules = Object.freeze({
  react: React,
  'react-native': reactNativeModule,
  'react-native-safe-area-context': esModule(SafeArea),
  'react-native-svg': esModule(Svg),
  'lucide-react-native': lucideModule,
  'expo-status-bar': esModule(StatusBar),
});

window.React = React;
window.ReactDOM = ReactDOM;
window.__RN_MODULES__ = modules;
window.__RN_RUNTIME__ = Object.freeze(__RN_RUNTIME_BUILD__);
window.__RN_PREVIEW__ = Object.freeze({ boot: () => boot(modules), transform });
