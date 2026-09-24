import React from 'react';
import { PlatformColor, Text, View } from 'react-native';

export default function App() {
  return (
    <View>
      <Text style={{ color: PlatformColor('label') }}>Native-only API</Text>
    </View>
  );
}
