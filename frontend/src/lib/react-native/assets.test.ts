import { findUrlLiterals, inlineImageUrls } from "./assets";

const SOURCE = `import { Image, Linking, Text } from 'react-native';
const AVATAR_URL = 'http://127.0.0.1:7001/local-assets/asset_abc.png';
const HERO = "/local-assets/hero.jpg";
const HELP = 'https://example.com/help';
const dynamic = \`\${base}/local-assets/x.png\`;
export default function App() {
  return (
    <>
      <Image source={{ uri: AVATAR_URL }} />
      <Image source={{ uri: 'http://127.0.0.1:7001/local-assets/asset_abc.png' }} />
      <Image source={{ uri: \`https://replicate.delivery/out.webp\` }} />
      <Text onPress={() => Linking.openURL(HELP)}>Help</Text>
    </>
  );
}
`;

const IMAGES: Record<string, string> = {
  "http://127.0.0.1:7001/local-assets/asset_abc.png": "data:image/png;base64,QUJD",
  "http://backend/local-assets/hero.jpg": "data:image/jpeg;base64,SEVSTw==",
  "https://replicate.delivery/out.webp": "data:image/webp;base64,V0VCUA==",
};

describe("findUrlLiterals", () => {
  test("finds each quoted URL once, skipping interpolated templates", () => {
    expect(findUrlLiterals(SOURCE)).toEqual([
      "http://127.0.0.1:7001/local-assets/asset_abc.png",
      "/local-assets/hero.jpg",
      "https://example.com/help",
      "https://replicate.delivery/out.webp",
    ]);
  });
});

describe("inlineImageUrls", () => {
  test("embeds images, keeps links, and resolves backend paths", async () => {
    const fetched: string[] = [];
    const result = await inlineImageUrls(
      SOURCE,
      async (url) => {
        fetched.push(url);
        return IMAGES[url] ?? null;
      },
      (url) => (url.startsWith("/") ? `http://backend${url}` : url)
    );
    expect(result.embedded).toEqual([
      "http://127.0.0.1:7001/local-assets/asset_abc.png",
      "/local-assets/hero.jpg",
      "https://replicate.delivery/out.webp",
    ]);
    expect(result.failed).toEqual(["https://example.com/help"]);
    expect(fetched).toContain("http://backend/local-assets/hero.jpg");
    expect(result.source).toContain("const AVATAR_URL = 'data:image/png;base64,QUJD';");
    expect(result.source).toContain("uri: 'data:image/png;base64,QUJD'");
    expect(result.source).toContain('const HERO = "data:image/jpeg;base64,SEVSTw==";');
    expect(result.source).toContain("uri: `data:image/webp;base64,V0VCUA==`");
    expect(result.source).toContain("const HELP = 'https://example.com/help';");
    expect(result.source).toContain("`${base}/local-assets/x.png`");
    expect(result.source).not.toContain("127.0.0.1:7001");
  });

  test("treats a fetch that throws as not embeddable", async () => {
    const result = await inlineImageUrls("const a = 'https://x.test/a.png';", async () => {
      throw new Error("offline");
    });
    expect(result).toEqual({
      source: "const a = 'https://x.test/a.png';",
      embedded: [],
      failed: ["https://x.test/a.png"],
    });
  });
});
