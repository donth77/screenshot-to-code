import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

// RNW-8: the same shadow written two ways. Only boxShadow renders the same on web, iOS and Android.
export default function App() {
  return (
    <View style={styles.screen}>
      <View testID="card-boxshadow" style={[styles.card, styles.boxShadow]}>
        <Text>boxShadow</Text>
      </View>
      <View testID="card-legacy-shadow" style={[styles.card, styles.legacyShadow]}>
        <Text>shadow* + elevation</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, flexDirection: 'row', gap: 12, padding: 16, backgroundColor: '#F6F7FB' },
  card: { flex: 1, height: 120, borderRadius: 16, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  boxShadow: { boxShadow: '0px 4px 12px rgba(17, 24, 39, 0.12)' },
  legacyShadow: {
    shadowColor: '#111827',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.12,
    shadowRadius: 12,
    elevation: 4,
  },
});
