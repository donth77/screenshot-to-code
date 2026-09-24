import React from 'react';
import { Platform, StyleSheet, Text, View } from 'react-native';

export default function App() {
  const top = Platform.OS === 'ios' ? 20 : 0;
  return (
    <View testID="web-styles" style={[styles.screen, { paddingTop: top }]}>
      <View style={styles.grid}>
        <Text style={{ fontSize: '14px', cursor: 'pointer' }}>Grid cell</Text>
      </View>
      <View style={styles.card}><Text>Card</Text></View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, padding: '8px 16px' },
  grid: { display: 'grid', gridTemplateColumns: '1fr 1fr', position: 'sticky' },
  card: { border: '1px solid #E5E7EB', shadowColor: '#000', elevation: 2 },
});
