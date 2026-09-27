// Duel bots. Both only use their own legal actions and what their seat may know: the opponent's hidden actions and
// closed gate are left out of every simulation. The simple bot looks one round ahead by simulating the attack.
import { BEATS, CARDS, COLOSSI, GATES, ASPECTS, RULES } from './content.js';
import { apply, gateOwner, legalActions, other, SEATS } from './engine.js';
import { randInt } from '../core/rng.js';

const pick = (rng, xs) => xs[randInt(rng, xs.length)];

export function randomDuelBot(s, p, rng) {
  const acts = legalActions(s, p);
  if (!acts.length) return null;
  if (s.phase === 'round') {
    const open = acts.find(a => a.type === 'openGate');
    if (open && randInt(rng, 3) === 0) return open;
    const plays = acts.filter(a => a.type === 'activate');
    if (plays.length && randInt(rng, 3) > 0) return pick(rng, plays);
    return acts.find(a => a.type === 'ready');
  }
  return pick(rng, acts);
}

// How good a position is for p: life first, then what is standing on the gate, then how rested the reserve is.
function score(s, p) {
  if (s.result) return s.result.winner === p ? 1e6 : s.result.winner ? -1e6 : 0;
  const me = s.players[p], foe = s.players[other(p)];
  const unit = uid => (uid ? s.units[uid] : null);
  const worth = u => (u ? u.g * 0.6 + u.shield * 0.4 : -250);
  const bench = q => s.players[q].units.reduce((sum, u) => sum + (s.units[u].zone === 'reserve' ? s.units[u].g * 0.08 : 0), 0);
  const removed = q => s.players[q].units.filter(u => s.units[u].zone === 'removed').length;
  return (me.life - foe.life) * 2 + worth(unit(me.fighter)) - worth(unit(foe.fighter)) + bench(p) - bench(other(p))
    + (removed(other(p)) - removed(p)) * 400 + (me.nextMana - foe.nextMana) * 15;
}

// The round as p sees it: the opponent's face-down actions are not there.
function blind(s, p) {
  const b = structuredClone(s);
  if (b.bout) b.bout.queue = b.bout.queue.filter(a => a.player === p);
  return b;
}

const afterRound = st => (st.phase === 'round' ? apply(st, { player: 'system', type: 'endRound' }).state : st);
const aspectIndex = (s, uid) => ASPECTS.indexOf(COLOSSI[s.units[uid].def].aspect);
const KIND_WORTH = { bonus: 40, field: 30, trap: 60 };

// What a counter is likely worth, from what p can see of the opponent's round.
function counterWorth(s, p, what) {
  const foeP = other(p), foe = s.players[foeP];
  const hidden = s.bout.queue.filter(a => a.player === foeP);
  const sees = COLOSSI[s.units[s.players[p].fighter].def].passive.seesKinds;
  const kindsOf = a => (a.kind === 'gate' ? ['gate'] : a.defs.map(d => CARDS[d].kind));
  const likely = hidden.length + (foe.ready ? 0 : 0.8); // actions the opponent took or probably will take
  const foeGate = gateOwner(s) === foeP && !s.bout.gateOpen;
  switch (what) {
    case 'any': return likely > 0.5 ? 130 : 20;
    case 'attack':
      if (sees) return hidden.some(a => kindsOf(a).includes('attack')) ? 140 : 25;
      return likely * 55;
    case 'defense':
      if (sees) return hidden.some(a => kindsOf(a).includes('defense')) ? 100 : 20;
      return likely * 35;
    case 'gate': return foeGate ? 70 : 25;
    case 'counter': return 30;
    default: return 0;
  }
}

// Things the one-round simulation does not see: cards drawn and mana for the next round.
function futureWorth(defs) {
  let v = 0;
  for (const d of defs) {
    for (const [op, a] of CARDS[d].ops) {
      if (op === 'draw') v += 28 * a;
      if (op === 'mana') v += 22 * a;
    }
  }
  return v;
}

export function simpleDuelBot(s, p, rng) {
  const acts = legalActions(s, p);
  if (!acts.length) return null;
  const pl = s.players[p], foeP = other(p);
  if (s.phase === 'gate') {
    const hopeful = pl.units.filter(u => s.units[u].zone === 'reserve');
    const value = a => {
      const g = GATES[s.gates[a.gate].def];
      return Math.max(...hopeful.map(u => g.bonus[aspectIndex(s, u)])) + KIND_WORTH[g.kind] + randInt(rng, 30);
    };
    return acts.reduce((best, a) => (value(a) > value(best) ? a : best));
  }
  if (s.phase === 'choose') {
    // Only the owner knows the closed gate, so only the owner can pick a fighter for it. The opponent's pick is
    // hidden: weigh the aspect edge against every colossus it may send.
    const gate = gateOwner(s) === p ? GATES[s.gates[s.bout.gate].def] : null;
    const foeUnits = s.players[foeP].fighter ? [s.players[foeP].fighter] : s.players[foeP].units.filter(u => s.units[u].zone === 'reserve');
    const value = a => {
      const u = s.units[a.unit], k = COLOSSI[u.def];
      let edge = 0;
      for (const f of foeUnits) {
        const fa = COLOSSI[s.units[f].def].aspect;
        if (BEATS[k.aspect] === fa) edge += RULES.aspectEdge;
        if (BEATS[fa] === k.aspect) edge -= RULES.aspectEdge;
      }
      return u.g + (gate ? gate.bonus[aspectIndex(s, a.unit)] : 0) + edge / Math.max(1, foeUnits.length) + (k.passive.attack ?? 0) * 0.5 + randInt(rng, 40);
    };
    return acts.reduce((best, a) => (value(a) > value(best) ? a : best));
  }
  // round: compare doing nothing with opening the gate and with every affordable activation
  const view = blind(s, p);
  const base = score(afterRound(view), p);
  const hidden = s.bout.queue.filter(a => a.player === foeP);
  let best = null, bestVal = base + 15;
  for (const a of acts) {
    let v;
    if (a.type === 'openGate') {
      const r = apply(view, { ...a, player: p });
      const g = GATES[s.gates[s.bout.gate].def];
      // A reflecting trap only pays if the opponent is doing something this round.
      v = score(afterRound(r.state), p) + (g.rule === 'reflect' ? (hidden.length ? 90 : -40) : 0) + 5;
    } else if (a.type === 'activate') {
      const defs = a.cards.map(c => s.cards[c].def);
      const cost = defs.reduce((sum, d) => sum + CARDS[d].cost, 0);
      const once = defs.filter(d => CARDS[d].once).length;
      const r = apply(view, { ...a, player: p });
      if (!r.ok) continue;
      v = score(afterRound(r.state), p) - cost * 4 - once * 15 + futureWorth(defs);
      for (const d of defs) for (const [op, what] of CARDS[d].ops) if (op === 'counter') v += counterWorth(s, p, what);
    } else continue;
    if (v > bestVal) { bestVal = v; best = a; }
  }
  return best ?? acts.find(a => a.type === 'ready');
}

export const DUEL_BOTS = { random: randomDuelBot, simple: simpleDuelBot };
export { SEATS };
