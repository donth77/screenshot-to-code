// The status and navigation bars of an Android screenshot from a phone that
// isn't in the device table: the TypeScript port of detect_system_bars in
// backend/react_native/profiles.py. Both run the vectors in
// rn-runtime/test-vectors/system-bars.json, so the crop the UI shows is the
// crop the backend makes.
//
// The status bar is a band at the top holding one thin row of small glyphs,
// the clock on the left and icons on the right; the navigation bar is a band
// at the bottom holding a gesture pill or three buttons. Glyphs sit in the
// middle of their band, so a band is twice as tall as its glyphs' centre is
// far from the edge. Only clear cases count: a pill drawn over content, or
// anything else, leaves that edge uncropped.
import { roundHalfEven as round } from "./roundHalfEven";

export interface SystemBars {
  topPx: number;
  bottomPx: number;
}

const GLYPH_CONTRAST = 64; // as the backend's status-bar style check
const SEARCH_DP = 64; // how far in from each edge to look
const MIN_INK = 2; // glyph pixels a row needs
const MIN_CONTENT_DP = 100;

// Pillow's RGB to L, so both ports see the same levels.
export function luminance(rgba: Uint8ClampedArray, width: number, height: number): Uint8Array {
  const out = new Uint8Array(width * height);
  for (let i = 0, j = 0; i < out.length; i++, j += 4) {
    out[i] = (19595 * rgba[j] + 38470 * rgba[j + 1] + 7471 * rgba[j + 2] + 32768) >> 16;
  }
  return out;
}

// Rows [start, end) of a screenshot's luminance, as a band to search.
interface Band {
  lum: Uint8Array;
  width: number;
  start: number; // the band's first row in the screenshot
  count: number;
}

// The most common luminance in band rows [from, to): the lowest, on a tie.
function background(band: Band, from: number, to: number): number {
  const counts = new Uint32Array(256);
  for (let i = (band.start + from) * band.width; i < (band.start + to) * band.width; i++) {
    counts[band.lum[i]]++;
  }
  let best = 0;
  for (let level = 1; level < 256; level++) if (counts[level] > counts[best]) best = level;
  return best;
}

function isInk(band: Band, row: number, x: number, level: number): boolean {
  return Math.abs(band.lum[(band.start + row) * band.width + x] - level) > GLYPH_CONTRAST;
}

function inkCount(band: Band, row: number, level: number, from = 0, to = band.width): number {
  let count = 0;
  for (let x = from; x < to; x++) if (isInk(band, row, x, level)) count++;
  return count;
}

// The first run of inked rows in `order`, bridging gaps of up to maxGap rows.
function glyphBand(inked: boolean[], order: number[], maxGap: number): [number, number] | null {
  let first: number | null = null;
  let last = 0;
  let gap = 0;
  for (const row of order) {
    if (inked[row]) {
      if (first === null) first = row;
      last = row;
      gap = 0;
    } else if (first !== null) {
      gap++;
      if (gap > maxGap) break;
    }
  }
  return first === null ? null : [first, last];
}

function range(from: number, to: number, step = 1): number[] {
  const out: number[] = [];
  for (let i = from; step > 0 ? i < to : i > to; i += step) out.push(i);
  return out;
}

function statusBarPx(band: Band, dp: number): number {
  const { count, width } = band;
  const level = background(band, 0, Math.max(1, round(2 * dp)));
  const inked = range(0, count).map((row) => inkCount(band, row, level) >= MIN_INK);
  const found = glyphBand(inked, range(0, count), round(1.5 * dp));
  if (!found) return 0;
  const [first, last] = found;
  const height = first + last + 1;
  const rows = range(first, last + 1);
  const left = rows.some((row) => inkCount(band, row, level, 0, round(0.4 * width)) >= MIN_INK);
  const right = rows.some((row) => inkCount(band, row, level, round(0.6 * width)) >= MIN_INK);
  const clearBelow = !range(last + 1, height - round(dp)).some((row) => inked[row]);
  return round(2 * dp) <= first &&
    first <= round(20 * dp) &&
    round(6 * dp) <= last - first + 1 &&
    last - first + 1 <= round(20 * dp) &&
    round(20 * dp) <= height &&
    height <= Math.min(count, round(56 * dp)) &&
    clearBelow &&
    left &&
    right
    ? height
    : 0;
}

function navigationBarPx(band: Band, dp: number): number {
  const { count, width } = band;
  const level = background(band, count - Math.max(1, round(2 * dp)), count);
  const inked = range(0, count).map((row) => inkCount(band, row, level) >= MIN_INK);
  // Found scanning up, so the bottom row comes first.
  const found = glyphBand(inked, range(count - 1, -1, -1), round(1.5 * dp));
  if (!found) return 0;
  const [last, first] = found;
  const columns: number[] = [];
  for (let x = 0; x < width; x++) {
    if (range(first, last + 1).some((row) => isInk(band, row, x, level))) columns.push(x);
  }
  const low = columns[0];
  const high = columns[columns.length - 1];
  const tall = last - first + 1;
  const inkedBetween = (start: number, end: number) =>
    columns.some((x) => x >= start * width && x < end * width);
  const pill =
    round(2 * dp) <= tall &&
    tall <= round(8 * dp) &&
    Math.abs((low + high) / 2 - width / 2) <= 0.05 * width &&
    0.15 * width <= high - low &&
    high - low <= 0.5 * width;
  const buttons =
    round(8 * dp) <= tall &&
    tall <= round(24 * dp) &&
    inkedBetween(0.15, 0.35) &&
    inkedBetween(0.4, 0.6) &&
    inkedBetween(0.65, 0.85) &&
    low >= 0.1 * width &&
    high < 0.9 * width;
  const height = 2 * count - first - last - 1;
  const clearAbove = !range(count - height + round(dp), first).some((row) => inked[row]);
  return (pill || buttons) &&
    count - 1 - last >= round(3 * dp) &&
    round(16 * dp) <= height &&
    height <= Math.min(count, round(56 * dp)) &&
    clearAbove
    ? height
    : 0;
}

// An Android screenshot's status and navigation bars, in pixels; 0 where
// there's no clear bar. `scale` is pixels per dp.
export function detectSystemBars(
  lum: Uint8Array,
  width: number,
  height: number,
  scale: number
): SystemBars {
  const count = Math.min(Math.floor(height / 2), round(SEARCH_DP * scale));
  if (count < 1) return { topPx: 0, bottomPx: 0 };
  const topPx = statusBarPx({ lum, width, start: 0, count }, scale);
  const bottomPx = navigationBarPx({ lum, width, start: height - count, count }, scale);
  if (height - topPx - bottomPx < round(MIN_CONTENT_DP * scale)) return { topPx: 0, bottomPx: 0 };
  return { topPx, bottomPx };
}
