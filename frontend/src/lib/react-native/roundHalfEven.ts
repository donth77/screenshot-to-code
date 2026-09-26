// Python's round(): halves go to the even neighbour. The React Native ports of
// backend code use it wherever the backend rounds, so both land on the same pixel.
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}
