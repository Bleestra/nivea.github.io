// Test fixtures: a match past setup, plus direct position edits for the artificial positions the GDD scenarios use.
import assert from 'node:assert/strict';
import * as R from '../src/core/index.js';

export { R, assert };

export const preset = key => structuredClone(R.PRESET_DECKS[key]);

// A legal deck: the listed abilities twice each, padded with neutral abilities up to 24.
export function deckWith(colossi, abilities, gates = ['RS-G002', 'RS-G008', 'RS-G003']) {
  const ids = [...new Set(abilities)];
  for (const a of Object.values(R.ABILITIES)) {
    if (ids.length >= 12) break;
    if (a.aspect === 'neutral' && !ids.includes(a.id)) ids.push(a.id);
  }
  return { name: 'test', colossi, gates, abilities: ids.slice(0, 12).flatMap(id => [id, id]) };
}

// A = first deck, B = second; gates placed in listed order, both keep their opening hands -> A's first turn.
export function setupMatch({ a = 'attack', b = 'answers', seed = 7 } = {}) {
  const deck = d => (typeof d === 'string' ? preset(d) : d);
  let { state } = R.createMatch({ seed, assignSeats: false, players: [{ name: 'A', deck: deck(a) }, { name: 'B', deck: deck(b) }] });
  while (state.phase === 'setupGates' || state.phase === 'mulligan') {
    for (const p of ['A', 'B']) {
      const acts = R.legalActions(state, p);
      if (!acts.length) continue;
      state = act(state, p, state.phase === 'mulligan' ? { type: 'mulligan', cards: [] } : acts[0]);
    }
  }
  return state;
}

export function act(state, p, a) {
  const r = R.apply(state, { ...a, player: p });
  assert.ok(r.ok, `${p} ${JSON.stringify(a)} отклонено: ${r.error}`);
  return r.state;
}

export const tryAct = (state, p, a) => R.apply(state, { ...a, player: p });
export const has = (state, p, pred) => R.legalActions(state, p).some(pred);
export const unit = (s, p, def) => s.players[p].units.find(u => s.units[u].def === def);

// Make sure a fresh instance of `def` is in the hand: one already there that this test has not taken yet,
// else one moved from the deck or the discard. Returns its instance id.
const taken = new WeakMap();
export function give(s, p, def) {
  const pl = s.players[p];
  if (!taken.has(s)) taken.set(s, new Set());
  const mine = taken.get(s);
  const inHand = pl.hand.find(c => s.cards[c].def === def && !mine.has(c));
  if (inHand) {
    mine.add(inHand);
    return inHand;
  }
  for (const zone of ['deck', 'discard']) {
    const cid = pl[zone].find(c => s.cards[c].def === def);
    if (cid) {
      pl[zone] = pl[zone].filter(c => c !== cid);
      pl.hand.push(cid);
      mine.add(cid);
      return cid;
    }
  }
  throw new Error(`${p}: больше нет ${def}`);
}

export function handOf(s, p, def) {
  return s.players[p].hand.find(c => s.cards[c].def === def);
}

export function place(s, uid, q, hold = 0) {
  const u = s.units[uid];
  assert.equal(s.board[q].unit, null, `${q} занята`);
  if (u.platform) s.board[u.platform].unit = null;
  u.zone = 'field'; u.platform = q; u.hold = hold; u.epoch++;
  s.board[q].unit = uid;
}

export function setGate(s, q, def) {
  s.gates[s.board[q].gate].def = def;
}

export function setMana(s, a, b = a) {
  s.players.A.mana = a;
  s.players.B.mana = b;
}

// A plain test modifier, as if an unremovable ability had resolved.
export function addMod(s, uid, amount) {
  const d = s.duel;
  d.mods.push({ id: `m${d.nextMod++}`, target: uid, amount, def: 'RS-A037', card: null, owner: s.units[uid].owner, removable: false, linkBound: false });
}

export const play = (s, p, cid, targets = {}) => act(s, p, { type: 'play', card: cid, targets });
export const pass = (s, p) => act(s, p, { type: 'pass' });

// Both pass in priority order until the chain is empty (the duel stays open).
export function resolveChain(s) {
  while (s.duel && s.duel.chain.length) s = pass(s, s.duel.priority);
  return s;
}

// Two passes over an empty chain: the clash.
export function finishDuel(s) {
  s = resolveChain(s);
  while (s.duel) s = pass(s, s.duel.priority);
  return s;
}

export const lastEvent = (s, t) => [...s.log].reverse().find(e => e.t === t);
export const powerOf = (s, uid) => R.breakdown(s, uid).total;
