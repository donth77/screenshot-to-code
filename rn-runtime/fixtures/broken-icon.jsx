import React from 'react';
import { Text, View } from 'react-native';
import { HeartOutline, House } from 'lucide-react-native';

export default function App() {
  return (
    <View testID="icons" style={{ flexDirection: 'row', gap: 12, padding: 24 }}>
      <House size={24} color="#111827" />
      <HeartOutline size={24} color="#E11D48" />
      <Text>Icons</Text>
    </View>
  );
}
