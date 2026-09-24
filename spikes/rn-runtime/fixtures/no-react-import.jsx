import { Text, View } from 'react-native';

export default function App() {
  return (
    <View testID="no-react-import" style={{ padding: 24 }}>
      <Text>JSX without importing React</Text>
    </View>
  );
}
