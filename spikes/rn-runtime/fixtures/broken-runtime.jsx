import React from 'react';
import { Text, View } from 'react-native';

function Price({ amount }) {
  return <Text testID="price">{amount.toFixed(2)}</Text>;
}

export default function App() {
  return (
    <View>
      <Price />
    </View>
  );
}
