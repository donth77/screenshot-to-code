import * as fs from "fs";
import * as path from "path";
import {
  DeviceOverrides,
  DeviceTable,
  ReactNativeDevice,
  contentHeight,
  cropBottomPx,
  cropTopPx,
  insetFromOffset,
  previewProfile,
  resolveDevice,
  roundHalfEven,
  withChosenName,
} from "./devices";

// Shared with backend/tests/test_rn_device_detection.py, whose Python
// implementation produced every expected value.
interface Vectors {
  cases: {
    name: string;
    pixelWidth: number | null;
    pixelHeight: number | null;
    overrides: DeviceOverrides | null;
    expected: Record<string, unknown>;
  }[];
}

const RN_RUNTIME = path.resolve(__dirname, "../../../../rn-runtime");
const table: DeviceTable = JSON.parse(
  fs.readFileSync(path.join(RN_RUNTIME, "device-profiles.json"), "utf8")
);
const vectors: Vectors = JSON.parse(
  fs.readFileSync(path.join(RN_RUNTIME, "test-vectors/device-detection.json"), "utf8")
);

function describeDevice(device: ReactNativeDevice): Record<string, unknown> {
  return {
    ...device,
    cropTopPx: cropTopPx(device),
    cropBottomPx: cropBottomPx(device),
    contentHeight: contentHeight(device),
    previewProfile: previewProfile(device),
  };
}

describe("resolveDevice", () => {
  test.each(vectors.cases)("$name", ({ pixelWidth, pixelHeight, overrides, expected }) => {
    const size =
      pixelWidth === null || pixelHeight === null
        ? null
        : { width: pixelWidth, height: pixelHeight };
    expect(describeDevice(resolveDevice(table, size, overrides ?? {}))).toEqual(expected);
  });
});

describe("withChosenName", () => {
  const size = { width: 1170, height: 2532 };

  test("keeps the detected name until the width is overridden", () => {
    const device = resolveDevice(table, size, { insetTop: 40 });
    expect(withChosenName(table, device, { insetTop: 40 }).name).toBe(device.name);
  });

  test("names the phone the user picked from the table", () => {
    const overrides = { platform: "ios" as const, logicalWidth: 393, insetTop: 59, insetBottom: 34 };
    const device = withChosenName(table, resolveDevice(table, size, overrides), overrides);
    expect(device.name).toBe("iPhone 14 Pro, 15, 15 Pro, 16");
  });

  test("names no phone for a width no phone has", () => {
    const overrides = { logicalWidth: 391 };
    expect(withChosenName(table, resolveDevice(table, size, overrides), overrides).name).toBeNull();
  });
});

describe("insetFromOffset", () => {
  const iphone = resolveDevice(table, { width: 1170, height: 2532 });

  test("converts screenshot pixels to points, to one decimal", () => {
    expect(insetFromOffset(iphone, "top", 141)).toBe(47);
    expect(insetFromOffset(iphone, "bottom", 100)).toBe(33.3);
  });

  test("never goes negative, past the backend's limit or over the other strip", () => {
    expect(insetFromOffset(iphone, "top", -20)).toBe(0);
    expect(insetFromOffset(iphone, "top", 5000)).toBe(200);
    // A 208 pt tall image with no bottom strip: the top strip stops 100 pt short.
    const short = resolveDevice(table, { width: 780, height: 416 });
    expect(short.pixelHeight / short.scale).toBe(208);
    expect(insetFromOffset(short, "top", 1000)).toBe(108);
  });
});

describe("roundHalfEven", () => {
  test.each([
    [0.5, 0],
    [1.5, 2],
    [2.5, 2],
    [3.5, 4],
    [2.4999, 2],
    [2.5001, 3],
    [-0.5, 0],
    [7, 7],
  ])("rounds %p to %p like Python", (value, expected) => {
    expect(roundHalfEven(value)).toBe(expected);
  });
});
