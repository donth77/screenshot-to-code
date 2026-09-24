// Replaces react-native-safe-area-context's web NativeSafeAreaProvider.
//
// The stock web provider measures CSS env(safe-area-inset-*) after mount and
// overwrites whatever initialMetrics the app passed (always 0 in desktop and
// headless Chromium). The preview instead reports the device profile's insets
// and the viewport frame, so SafeAreaView behaves deterministically.
import * as React from 'react';
import { View } from 'react-native';

function profileMetrics() {
  const profile = window.__RN_PREVIEW_PROFILE__ || {};
  const insets = Object.assign({ top: 0, right: 0, bottom: 0, left: 0 }, profile.insets);
  const frame = { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight };
  return { insets, frame };
}

export function NativeSafeAreaProvider({ children, style, onInsetsChange }) {
  React.useEffect(() => {
    const report = () => onInsetsChange({ nativeEvent: profileMetrics() });
    report();
    window.addEventListener('resize', report);
    return () => window.removeEventListener('resize', report);
  }, [onInsetsChange]);
  return React.createElement(View, { style }, children);
}
