import * as fs from "fs";
import * as path from "path";
import {
  DeviceOverrides,
  DeviceTable,
  ReactNativeDevice,
  contentHeight,
  cropBottomPx,
  cropTopPx,
  previewProfile,
  resolveDevice,
  roundHalfEven,
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
