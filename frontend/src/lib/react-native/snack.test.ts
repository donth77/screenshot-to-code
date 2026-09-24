import * as fs from "fs";
import * as path from "path";
import { ExpoSdk, snackSdkVersion, snackUrl, usesLocalAssets } from "./snack";

const sdk: ExpoSdk = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../../rn-runtime/expo-sdk.json"), "utf8")
);
const APP = "import { Text } from 'react-native';\nexport default function App() { return <Text>Hi & bye</Text>; }\n";

describe("snackUrl", () => {
  const url = new URL(snackUrl(APP, sdk));

  test("opens Snack on the SDK expo-sdk.json names for it", () => {
    expect(url.origin).toBe("https://snack.expo.dev");
    expect(url.searchParams.get("sdkVersion")).toBe(snackSdkVersion(sdk));
    expect(url.searchParams.get("sdkVersion")).toBe("55.0.0");
    expect(url.searchParams.get("platform")).toBe("web");
  });

  test("sends the screen and a SafeAreaProvider host as files", () => {
    const files = JSON.parse(url.searchParams.get("files") ?? "{}");
    expect(Object.keys(files)).toEqual(["App.js", "Screen.js"]);
    expect(files["Screen.js"]).toEqual({ type: "CODE", contents: APP });
    expect(files["App.js"].contents).toContain("<SafeAreaProvider>");
    expect(files["App.js"].contents).toContain("import Screen from './Screen';");
  });

  test("pins lucide and lets Snack choose Expo packages' versions", () => {
    expect(url.searchParams.get("dependencies")).toBe(
      `expo-status-bar,react-native-safe-area-context,react-native-svg,lucide-react-native@${sdk.dependencies["lucide-react-native"]}`
    );
  });

  test("refuses an SDK file without a Snack version", () => {
    expect(() => snackUrl(APP, { sdk: "57.0.0", dependencies: {} })).toThrow();
  });
});

test("usesLocalAssets", () => {
  expect(usesLocalAssets("uri: 'http://127.0.0.1:7001/local-assets/a.png'")).toBe(true);
  expect(usesLocalAssets("uri: 'https://example.com/a.png'")).toBe(false);
});
