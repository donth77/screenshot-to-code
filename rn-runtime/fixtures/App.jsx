import React, { useEffect, useRef, useState } from 'react';
import { FlatList, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Circle, Path, Rect } from 'react-native-svg';
import { Bell, ChevronRight, Heart, Search, Settings } from 'lucide-react-native';
import { StatusBar } from 'expo-status-bar';

const tokens = {
  colors: {
    background: '#F6F7FB',
    card: '#FFFFFF',
    text: '#111827',
    muted: '#6B7280',
    primary: '#6366F1',
    border: '#E5E7EB',
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 },
  radii: { md: 12, lg: 16, full: 999 },
  fontSize: { caption: 12, body: 15, title: 22 },
};

const AVATAR_URL = '__ASSET_BASE__/local-assets/avatar.png';

const CHIPS = ['All', 'Account', 'Privacy', 'Devices', 'Billing'];

const ROWS = [
  { id: 'profile', title: 'Profile', subtitle: 'Name, photo, bio' },
  { id: 'notifications', title: 'Notifications', subtitle: 'Push, email, SMS' },
  { id: 'privacy', title: 'Privacy', subtitle: 'Blocked accounts' },
  { id: 'security', title: 'Security', subtitle: 'Password, 2FA' },
  { id: 'appearance', title: 'Appearance', subtitle: 'Light' },
  { id: 'language', title: 'Language', subtitle: 'English (US)' },
  { id: 'storage', title: 'Storage', subtitle: '12.4 GB used' },
  { id: 'help', title: 'Help center', subtitle: 'FAQ, contact us' },
  { id: 'about', title: 'About', subtitle: 'Version 4.2.0' },
];

// Hooks inside an SVG-rendering component (RNW-4).
function ProgressRing({ progress }) {
  const mounted = useRef(false);
  const [value, setValue] = useState(0);
  useEffect(() => {
    mounted.current = true;
    setValue(progress);
  }, [progress]);
  const angle = value * 2 * Math.PI;
  const x = 32 + 26 * Math.sin(angle);
  const y = 32 - 26 * Math.cos(angle);
  return (
    <Svg testID="progress-ring" width={64} height={64} viewBox="0 0 64 64">
      <Rect x="0" y="0" width="64" height="64" rx="16" fill="#EEF2FF" />
      <Circle cx="32" cy="32" r="26" stroke={tokens.colors.border} strokeWidth="6" fill="none" />
      <Path d={`M32 6 A26 26 0 ${value > 0.5 ? 1 : 0} 1 ${x} ${y}`} stroke={tokens.colors.primary} strokeWidth="6" strokeLinecap="round" fill="none" />
    </Svg>
  );
}

// Hooks inside list rows that render lucide icons (RNW-4).
function SettingsRow({ item }) {
  const [liked, setLiked] = useState(item.id === 'notifications');
  return (
    <Pressable testID={`settings-row-${item.id}`} onPress={() => setLiked(!liked)} style={styles.row}>
      <View style={styles.rowIcon}>
        <Settings size={18} color={tokens.colors.primary} />
      </View>
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{item.title}</Text>
        <Text style={styles.rowSubtitle}>{item.subtitle}</Text>
      </View>
      <Heart size={18} color={liked ? '#EF4444' : tokens.colors.muted} fill={liked ? '#EF4444' : 'none'} />
      <ChevronRight size={18} color={tokens.colors.muted} />
    </Pressable>
  );
}

function Header({ query, onQueryChange }) {
  return (
    <View>
      <View style={styles.header}>
        <Image testID="avatar" source={{ uri: AVATAR_URL }} style={styles.avatar} resizeMode="cover" />
        <View style={styles.headerText}>
          <Text testID="greeting" style={styles.title}>Good morning, Ada</Text>
          <Text style={styles.subtitle}>
            You have <Text style={styles.bold}>3 new</Text> updates
          </Text>
        </View>
        <Pressable testID="bell-button" style={styles.iconButton}>
          <Bell size={22} color={tokens.colors.text} />
        </Pressable>
      </View>

      <View style={styles.search}>
        <Search size={18} color={tokens.colors.muted} />
        <TextInput
          testID="search-input"
          placeholder="Search settings"
          placeholderTextColor={tokens.colors.muted}
          value={query}
          onChangeText={onQueryChange}
          style={styles.searchInput}
        />
      </View>

      <ScrollView testID="chips" horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        {CHIPS.map((chip, index) => (
          <View key={chip} testID={`chip-${chip.toLowerCase()}`} style={[styles.chip, index === 0 && styles.chipActive]}>
            <Text style={[styles.chipText, index === 0 && styles.chipTextActive]}>{chip}</Text>
          </View>
        ))}
      </ScrollView>

      <View style={styles.cards}>
        <View testID="card-boxshadow" style={[styles.card, styles.cardBoxShadow]}>
          <ProgressRing progress={0.68} />
          <Text style={styles.cardLabel}>boxShadow</Text>
        </View>
        <View testID="card-bordered" style={[styles.card, styles.cardBordered]}>
          <ProgressRing progress={0.32} />
          <Text style={styles.cardLabel}>border</Text>
        </View>
      </View>
      <Text style={styles.sectionTitle}>Settings</Text>
    </View>
  );
}

export default function App() {
  const [query, setQuery] = useState('');
  const rows = ROWS.filter((row) => row.title.toLowerCase().includes(query.toLowerCase()));
  return (
    <SafeAreaView testID="screen" style={styles.safe}>
      <StatusBar style="dark" />
      <FlatList
        testID="settings-list"
        data={rows}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <SettingsRow item={item} />}
        ListHeaderComponent={<Header query={query} onQueryChange={setQuery} />}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        contentContainerStyle={styles.listContent}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: tokens.colors.background },
  listContent: { paddingHorizontal: tokens.spacing.lg, paddingBottom: tokens.spacing.xl },
  header: { flexDirection: 'row', alignItems: 'center', paddingTop: tokens.spacing.lg, gap: tokens.spacing.md },
  avatar: { width: 48, height: 48, borderRadius: tokens.radii.full },
  headerText: { flex: 1 },
  title: { fontSize: tokens.fontSize.title, fontWeight: '700', color: tokens.colors.text },
  subtitle: { fontSize: tokens.fontSize.body, color: tokens.colors.muted, marginTop: 2 },
  bold: { fontWeight: '700', color: tokens.colors.text },
  iconButton: { width: 40, height: 40, borderRadius: tokens.radii.full, backgroundColor: tokens.colors.card, alignItems: 'center', justifyContent: 'center' },
  search: {
    marginTop: tokens.spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: tokens.spacing.sm,
    backgroundColor: tokens.colors.card,
    borderRadius: tokens.radii.md,
    borderWidth: 1,
    borderColor: tokens.colors.border,
    paddingHorizontal: tokens.spacing.md,
    height: 44,
  },
  searchInput: { flex: 1, fontSize: tokens.fontSize.body, color: tokens.colors.text },
  chips: { gap: tokens.spacing.sm, paddingVertical: tokens.spacing.lg },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: tokens.radii.full, backgroundColor: tokens.colors.card, borderWidth: 1, borderColor: tokens.colors.border },
  chipActive: { backgroundColor: tokens.colors.primary, borderColor: tokens.colors.primary },
  chipText: { fontSize: 13, fontWeight: '600', color: tokens.colors.text },
  chipTextActive: { color: '#FFFFFF' },
  cards: { flexDirection: 'row', gap: tokens.spacing.md },
  card: { flex: 1, backgroundColor: tokens.colors.card, borderRadius: tokens.radii.lg, padding: tokens.spacing.lg, alignItems: 'center', gap: tokens.spacing.sm },
  cardBoxShadow: { boxShadow: '0px 4px 12px rgba(17, 24, 39, 0.12)' },
  cardBordered: { borderWidth: 1, borderColor: tokens.colors.border },
  cardLabel: { fontSize: tokens.fontSize.caption, color: tokens.colors.muted, fontWeight: '500' },
  sectionTitle: { marginTop: tokens.spacing.xl, marginBottom: tokens.spacing.sm, fontSize: 13, fontWeight: '600', color: tokens.colors.muted, textTransform: 'uppercase', letterSpacing: 0.6 },
  row: { flexDirection: 'row', alignItems: 'center', gap: tokens.spacing.md, backgroundColor: tokens.colors.card, paddingHorizontal: tokens.spacing.md, paddingVertical: tokens.spacing.md, borderRadius: tokens.radii.md },
  rowIcon: { width: 32, height: 32, borderRadius: 8, backgroundColor: '#EEF2FF', alignItems: 'center', justifyContent: 'center' },
  rowText: { flex: 1 },
  rowTitle: { fontSize: tokens.fontSize.body, fontWeight: '600', color: tokens.colors.text },
  rowSubtitle: { fontSize: 13, color: tokens.colors.muted, marginTop: 2 },
  separator: { height: tokens.spacing.sm },
});
