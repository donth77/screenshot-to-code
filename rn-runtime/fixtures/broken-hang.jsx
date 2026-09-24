import React from 'react';
import { Text } from 'react-native';

export default function App() {
  // An infinite loop while rendering: the preview can never settle.
  while (true) {}
  return <Text>unreachable</Text>;
}
