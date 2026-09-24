// "Open in Snack" (DESIGN.md §13.4): a URL that prefills an Expo Snack with
// the generated screen. Snack trails the export's Expo SDK (it runs up to
// SDK 55 while the export targets 57), so the SDK comes from expo-sdk.json's
// `snack` entry and the menu says which SDK opens.
//
// Assumed from Snack's documented URL parameters (files, dependencies,
// sdkVersion, platform), not verified here: this sandbox can't reach
// snack.expo.dev. Known limits: /local-assets images don't load in Snack,
// and very long files may exceed URL limits.

export interface ExpoSdk {
  sdk: string;
  dependencies: Record<string, string>;
  snack?: { sdkVersion: string };
}

// Longer URLs are refused: the Expo project zip is the export for those.
export const MAX_SNACK_URL_LENGTH = 60_000;

const SNACK_APP = `import { SafeAreaProvider } from 'react-native-safe-area-context';
import Screen from './Screen';

// The host provides SafeAreaProvider, as the exported Expo project's index.js does.
export default function App() {
  return (
    <SafeAreaProvider>
      <Screen />
    </SafeAreaProvider>
  );
}
`;

// Snack picks versions compatible with its SDK for unversioned names;
// lucide-react-native isn't an Expo package, so it keeps the export's pin.
const SNACK_DEPENDENCIES = [
  "expo-status-bar",
  "react-native-safe-area-context",
  "react-native-svg",
  "lucide-react-native",
];

export function snackSdkVersion(sdk: ExpoSdk): string | null {
  return sdk.snack?.sdkVersion ?? null;
}

export function snackUrl(appJsx: string, sdk: ExpoSdk, name = "Screenshot to Code"): string {
  const sdkVersion = snackSdkVersion(sdk);
  if (!sdkVersion) throw new Error("expo-sdk.json has no snack.sdkVersion");
  const files = {
    "App.js": { type: "CODE", contents: SNACK_APP },
    "Screen.js": { type: "CODE", contents: appJsx },
  };
  const dependencies = SNACK_DEPENDENCIES.map((pkg) =>
    pkg === "lucide-react-native" ? `${pkg}@${sdk.dependencies[pkg]}` : pkg
  ).join(",");
  const params = new URLSearchParams({
    name,
    sdkVersion,
    platform: "web",
    dependencies,
    files: JSON.stringify(files),
  });
  return `https://snack.expo.dev/?${params.toString()}`;
}

export function usesLocalAssets(appJsx: string): boolean {
  return appJsx.includes("/local-assets/");
}
