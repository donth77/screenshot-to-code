// Makes the preview's stand-in fonts lay out like the phone's system fonts.
//
// iOS: Inter stands in for SF Pro, which tracks size-dependently (looser below ~13 pt, tighter
// above); the fitted tracking closes the width gap. Lines are SF Pro's ascender + descender tall.
// Android: Roboto is the real font, but React Native rounds the font size up to a whole pixel,
// spaces lines by the rounded hhea ascent and descent, and (includeFontPadding) pads the first
// and last line out to the font's bounding box.
//
// calibration/fit.json holds the constants and the fitted tracking; calibration/README.md has the
// measurements behind every rule here. Corrections apply to the Text the model's code imports.
import * as React from 'react';
import { StyleSheet, Text as WebText } from 'react-native-web';
import FIT from '../calibration/fit.json';

const DEFAULT_FONT_SIZE = 14; // React Native's default on both platforms
const up = (px) => Math.ceil(px - 1e-9);

// What the enclosing Text set, so nested Text inherits like it does natively.
const TextParent = React.createContext(null);

function weightNumber(weight) {
  if (weight === 'bold') return 700;
  const value = parseInt(weight, 10);
  return Number.isFinite(value) ? value : 400;
}

function interpolate(xs, ys, x) {
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  let i = 1;
  while (x > xs[i]) i += 1;
  const t = (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
  return ys[i - 1] + t * (ys[i] - ys[i - 1]);
}

export function trackingEm(fontSize, fontWeight) {
  const { sizes, byWeight } = FIT.ios.tracking;
  const weights = Object.keys(byWeight).map(Number).sort((a, b) => a - b);
  const atWeight = weights.map((weight) => interpolate(sizes, byWeight[weight], fontSize));
  return interpolate(weights, atWeight, weightNumber(fontWeight));
}

// Android renders at ceil(size * density) pixels (TextAttributeProps.setFontSize).
export function renderedFontSize(platform, fontSize, scale) {
  return platform === 'android' ? up(fontSize * scale) / scale : fontSize;
}

// Baseline-to-baseline distance when the code sets no lineHeight.
export function naturalLineHeight(platform, fontSize, scale) {
  const { ascent, descent } = FIT[platform];
  if (platform === 'ios') return (ascent + descent) * fontSize; // iOS rounds the whole block, not each line
  const px = fontSize * scale;
  return (Math.round(ascent * px) + Math.round(descent * px)) / scale;
}

// includeFontPadding: extra space above the first line and below the last.
export function fontPadding(fontSize, scale) {
  const { ascent, descent, top, bottom } = FIT.android;
  const px = fontSize * scale;
  return { top: (up(top * px) - Math.round(ascent * px)) / scale, bottom: (up(bottom * px) - Math.round(descent * px)) / scale };
}

export function fontFaceDescriptors(platform) {
  const { ascent, descent } = FIT[platform];
  const percent = (value) => `${(value * 100).toFixed(2)}%`;
  return `ascent-override:${percent(ascent)};descent-override:${percent(descent)};line-gap-override:0%;`;
}

function paddingEdge(flat, edge, vertical) {
  const value = flat[edge] ?? flat[vertical] ?? flat.padding ?? 0;
  return typeof value === 'number' ? value : null;
}

// Resolves this Text's style against its parent's (nested Text inherits, as it does natively)
// and returns the overrides, which win over the code's style.
function resolve(flat, parent, profile) {
  const platform = profile.platform === 'android' ? 'android' : 'ios';
  const scale = Number(profile.scale) || 3;
  const ownSize = typeof flat.fontSize === 'number';
  const fontSize = renderedFontSize(platform, ownSize ? flat.fontSize : parent ? parent.fontSize : DEFAULT_FONT_SIZE, scale);
  const state = {
    fontSize,
    fontWeight: flat.fontWeight ?? (parent ? parent.fontWeight : undefined),
    letterSpacing: typeof flat.letterSpacing === 'number' ? flat.letterSpacing : parent ? parent.letterSpacing : undefined,
    lineHeightSet: typeof flat.lineHeight === 'number' || Boolean(parent && parent.lineHeightSet),
  };
  if (profile.textMetrics === false) return { state, extra: null };

  const extra = {};
  if (platform === 'android' && (!parent || ownSize)) extra.fontSize = fontSize;

  // iOS letterSpacing adds to SF Pro's tracking; letterSpacing: 0 also turns pair kerning off.
  if (platform === 'ios' && (!parent || ownSize || flat.fontWeight != null || flat.letterSpacing != null)) {
    extra.letterSpacing = trackingEm(fontSize, state.fontWeight) * fontSize + (state.letterSpacing || 0);
    extra.fontKerning = state.letterSpacing === 0 ? 'none' : 'auto';
  }

  if (typeof flat.lineHeight === 'number') {
    if (platform === 'android') extra.lineHeight = up(flat.lineHeight * scale) / scale; // rounded per line
  } else if (!state.lineHeightSet && (!parent || ownSize)) {
    extra.lineHeight = naturalLineHeight(platform, fontSize, scale);
    // No padding with an explicit lineHeight (CustomLineHeightSpan), so only here.
    if (platform === 'android' && !parent && flat.includeFontPadding !== false) {
      const pad = fontPadding(fontSize, scale);
      const top = paddingEdge(flat, 'paddingTop', 'paddingVertical');
      const bottom = paddingEdge(flat, 'paddingBottom', 'paddingVertical');
      if (top !== null) extra.paddingTop = top + pad.top;
      if (bottom !== null) extra.paddingBottom = bottom + pad.bottom;
    }
  }
  return { state, extra };
}

export const Text = React.forwardRef(function Text(props, ref) {
  const parent = React.useContext(TextParent);
  const { state, extra } = resolve(StyleSheet.flatten(props.style) || {}, parent, window.__RN_PREVIEW_PROFILE__ || {});
  return React.createElement(
    TextParent.Provider,
    { value: state },
    React.createElement(WebText, { ...props, ref, style: extra ? [props.style, extra] : props.style })
  );
});
Text.displayName = 'Text';
