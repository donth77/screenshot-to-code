import * as fs from "fs";
import * as path from "path";
import { DeviceTable, resolveDevice } from "./devices";
import { detectSystemBars, luminance } from "./systemBars";

// Shared with backend/tests/test_rn_system_bars.py, whose Python
// implementation produced every expected value.
interface Vectors {
  luminance: [number, number, number, number][];
  cases: {
    name: string;
    width: number;
    height: number;
    scale: number;
    fill: number;
    rects: [number, number, number, number, number][];
    expected: { topPx: number; bottomPx: number };
  }[];
}

const RN_RUNTIME = path.resolve(__dirname, "../../../../rn-runtime");
const table: DeviceTable = JSON.parse(
  fs.readFileSync(path.join(RN_RUNTIME, "device-profiles.json"), "utf8")
);
const vectors: Vectors = JSON.parse(
  fs.readFileSync(path.join(RN_RUNTIME, "test-vectors/system-bars.json"), "utf8")
);

// A screen of luminance: the fill, then each rectangle drawn in order.
function draw({ width, height, fill, rects }: Vectors["cases"][number]): Uint8Array {
  const lum = new Uint8Array(width * height).fill(fill);
  for (const [x, y, w, h, level] of rects) {
    for (let row = Math.max(0, y); row < Math.min(height, y + h); row++) {
      lum.fill(level, row * width + Math.max(0, x), row * width + Math.min(width, x + w));
    }
  }
  return lum;
}

describe("detectSystemBars", () => {
  test.each(vectors.cases)("$name", (scene) => {
    expect(detectSystemBars(draw(scene), scene.width, scene.height, scene.scale)).toEqual(scene.expected);
  });
});

test("luminance matches Pillow's RGB to L", () => {
  const rgba = new Uint8ClampedArray(vectors.luminance.flatMap(([r, g, b]) => [r, g, b, 255]));
  expect(Array.from(luminance(rgba, vectors.luminance.length, 1))).toEqual(
    vectors.luminance.map(([, , , level]) => level)
  );
});

describe("resolveDevice with a screenshot's pixels", () => {
  const scene = vectors.cases.find((c) => c.name === "status bar and three buttons")!;
  const screenshot = { width: scene.width, height: scene.height, luminance: draw(scene) };

  test("crops an unknown Android phone at its bars", () => {
    const device = resolveDevice(table, screenshot);
    expect(device.match).toBe("guessed");
    expect(Math.round(device.insetTop * device.scale)).toBe(scene.expected.topPx);
    expect(Math.round(device.insetBottom * device.scale)).toBe(scene.expected.bottomPx);
  });

  test("keeps the user's insets", () => {
    const device = resolveDevice(table, screenshot, { insetTop: 0 });
    expect(device.insetTop).toBe(0);
    expect(Math.round(device.insetBottom * device.scale)).toBe(scene.expected.bottomPx);
  });

  test("reads no bars without pixels, or for an iPhone", () => {
    expect(resolveDevice(table, { width: scene.width, height: scene.height }).insetTop).toBe(0);
    const iphone = resolveDevice(table, screenshot, { platform: "ios" });
    expect([iphone.insetTop, iphone.insetBottom]).toEqual([0, 0]);
  });
});
