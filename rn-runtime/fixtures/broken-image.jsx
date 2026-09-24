import React from 'react';
import { Image, Text, View } from 'react-native';

export default function App() {
  return (
    <View testID="image-screen" style={{ padding: 24, gap: 12 }}>
      <Image testID="missing-image" source={{ uri: 'https://rn-runtime.invalid/missing.png' }} style={{ width: 64, height: 64 }} />
      <Text>An image that fails to load</Text>
    </View>
  );
}
