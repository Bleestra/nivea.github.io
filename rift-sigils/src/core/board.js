// Logical field 2x3 (GDD §05). Canonical ids never change with the camera.
//   [A1] - [B1] - [C1]      row 1: side of player B
//     |      |      |
//   [A2] - [B2] - [C2]      row 2: side of player A
// Which row belongs to whom is not stated in GDD v0.1; this is our decision (see README, "Gaps").

export const PLATFORMS = ['A1', 'B1', 'C1', 'A2', 'B2', 'C2'];
export const OUTER = ['A1', 'C1', 'A2', 'C2'];
// "The first cards are placed on the opponent's side": A's first gate goes to B1, B's to B2.
export const FIRST_GATE_CELL = { A: 'B1', B: 'B2' };
export const GATE_ORDER = ['A', 'B', 'B', 'A', 'A', 'B'];

const col = p => 'ABC'.indexOf(p[0]);
const row = p => p[1];

// Only cells sharing a side are neighbours; a removed cell does not connect its neighbours.
export function adjacent(p, q) {
  if (p === q) return false;
  if (row(p) === row(q)) return Math.abs(col(p) - col(q)) === 1;
  return col(p) === col(q);
}

export function neighbours(p) {
  return PLATFORMS.filter(q => adjacent(p, q));
}
