import React, { useRef } from 'react';
import { ScrollView, Text, View } from 'react-native';

// Font calibration: every sample reports its laid-out size, then one line
// "RNCAL {id: [width, height]}" is logged. The same file runs in the web preview
// and natively (Metro prints device logs), so the stand-in fonts can be fitted to
// the real system fonts. See README.md.
const SIZES = [11, 13, 15, 17, 20, 22, 28, 34];
const WEIGHTS = ['400', '600', '700'];
const STRINGS = ['Good morning, Ada', 'Hamburgefonstiv 0123'];
// fit.py fits to these.
const GRID = SIZES.flatMap((size) =>
  WEIGHTS.flatMap((weight) => STRINGS.map((text, index) => ({ id: `${size}-${weight}-${index}`, style: { fontSize: size, fontWeight: weight }, text })))
);
// Held out: they check the fit on sizes, weights and styles it never saw.
const CHECKS = [
  ...[12, 14, 16, 18, 24, 32].flatMap((size) =>
    STRINGS.map((text, index) => ({ id: `${size}-400-${index}`, style: { fontSize: size, fontWeight: '400' }, text }))
  ),
  ...[15, 17, 20].flatMap((size) =>
    ['500', '800'].map((weight) => ({ id: `${size}-${weight}-0`, style: { fontSize: size, fontWeight: weight }, text: STRINGS[0] }))
  ),
  ...[13, 17, 34].flatMap((size) =>
    [-0.5, 0, 1].flatMap((letterSpacing) =>
      STRINGS.map((text, index) => ({ id: `${size}-400-${index}-ls${letterSpacing}`, style: { fontSize: size, letterSpacing }, text }))
    )
  ),
  ...[[15, 20], [17, 22.5], [28, 34]].map(([size, lineHeight]) => ({
    id: `${size}-400-0-lh${lineHeight}`,
    style: { fontSize: size, lineHeight },
    text: STRINGS[0],
  })),
  { id: 'default-0', style: {}, text: STRINGS[0] },
  // Paragraphs (hard breaks, so every platform has the same line count).
  ...[13, 17, 22].flatMap((size) =>
    [2, 3].map((lines) => ({
      id: `${size}-400-0-lines${lines}`,
      style: { fontSize: size },
      text: Array(lines).fill(STRINGS[0]).join('\n'),
    }))
  ),
  { id: '17-400-0-lines3-lh22', style: { fontSize: 17, lineHeight: 22 }, text: Array(3).fill(STRINGS[0]).join('\n') },
  // Android-only style; iOS ignores it.
  ...[1, 3].map((lines) => ({
    id: `17-400-0-lines${lines}-nopad`,
    style: { fontSize: 17, includeFontPadding: false },
    text: Array(lines).fill(STRINGS[0]).join('\n'),
  })),
];
const SAMPLES = [...GRID, ...CHECKS];

export default function App() {
  const results = useRef({});
  const reported = useRef(false);
  // Latest values, for harnesses that read them after fonts load (the web preview).
  globalThis.__RNCAL__ = results.current;
  const onLayout = (id) => (event) => {
    const { width, height } = event.nativeEvent.layout;
    results.current[id] = [Math.round(width * 100) / 100, Math.round(height * 100) / 100];
    if (!reported.current && Object.keys(results.current).length === SAMPLES.length) {
      reported.current = true;
      console.log(`RNCAL ${JSON.stringify(results.current)}`);
    }
  };
  return (
    <ScrollView testID="text-grid">
      {/* Wider than any phone, so no sample wraps. */}
      <View style={{ width: 1200, padding: 16 }}>
        {SAMPLES.map((sample) => (
          <View key={sample.id} style={{ flexDirection: 'row', marginBottom: 4 }}>
            <Text testID={`cal-${sample.id}`} onLayout={onLayout(sample.id)} style={sample.style}>
              {sample.text}
            </Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}
