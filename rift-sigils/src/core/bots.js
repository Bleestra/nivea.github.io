// AIAdapter (§21). Bots see what a player sees: they choose among legalActions() of their own seat and read the
// board through viewFor(). The random bot is the test generator; the simple bot is a first sparring partner.
import { ABILITIES, ASPECTS, COLOSSI, DECK_RULES, GATES } from './content.js';
import { adjacent } from './board.js';
import { apply, legalActions } from './engine.js';
import { enemyOf, fighterOf, power } from './power.js';
import { randInt, seedRng, shuffleInPlace } from './rng.js';
import { other } from './state.js';
import { viewFor } from './visibility.js';

export const newBotRng = seed => seedRng(`bot:${seed}`);
const pick = (rng, xs) => xs[randInt(rng, xs.length)];

export function randomBot(s, p, rng) {
  const acts = legalActions(s, p);
  return acts.length ? pick(rng, acts) : null;
}

// A random legal deck: two aspects, three colossi, three gates, 24 abilities with at most two copies.
export function randomDeck(rng) {
  const aspects = shuffleInPlace(rng, ASPECTS.slice()).slice(0, 2);
  const colossi = shuffleInPlace(rng, Object.values(COLOSSI).filter(c => aspects.includes(c.aspect)).map(c => c.id)).slice(0, 3);
  const gates = shuffleInPlace(rng, Object.keys(GATES)).slice(0, 3);
  const pool = Object.values(ABILITIES).filter(a => a.aspect === 'neutral' || aspects.includes(a.aspect)).map(a => a.id);
  const abilities = shuffleInPlace(rng, pool.flatMap(id => [id, id])).slice(0, DECK_RULES.abilities);
  return { name: 'Случайная колода', colossi, gates, abilities };
}

// ---------------------------------------------------------------- simple bot

// Resolve the chain as if nobody answers any more; returns the state right before the clash.
function settle(s) {
  let st = s;
  for (let i = 0; i < 64 && st.duel && st.duel.step === 'cards' && st.duel.chain.length; i++) {
    st = apply(st, { player: st.duel.priority, type: 'pass' }).state;
  }
  return st;
}

function margin(st, p) {
  if (!st.duel) return 0;
  const me = fighterOf(st, p), foe = enemyOf(st, me);
  const diff = power(st, me) - power(st, foe);
  if (diff) return diff;
  const mirror = st.gates[st.duel.gate].def === 'RS-G012';
  const tieMine = (st.duel.attacker === me) === mirror;
  return tieMine ? 0.5 : -0.5;
}

function duelChoice(s, p, acts) {
  const now = margin(settle(s), p);
  const hot = s.players[other(p)].sigils >= 2 || s.players[p].sigils >= 2;
  let best = null;
  for (const a of acts) {
    if (a.type !== 'play') continue;
    const r = apply(s, { ...a, player: p });
    if (!r.ok) continue;
    const m = margin(settle(r.state), p);
    const cost = s.players[p].mana - r.state.players[p].mana;
    // Prefer the cheapest card that turns the duel; if we are already winning, only answer what the chain threatens.
    const score = (m > 0 ? 100 : 0) + m - cost * 1.5;
    if (m > now && (m > 0 || hot) && (!best || score > best.score)) best = { a, score, m };
  }
  if (now > 0 && (!best || best.m <= now)) return acts.find(a => a.type === 'pass');
  return best ? best.a : acts.find(a => a.type === 'pass');
}

function gateBonusFor(view, q, unitDef) {
  const g = view.board[q].gate;
  if (!g?.def) return 0;
  return GATES[g.def].bonus[ASPECTS.indexOf(unitDef.aspect)];
}

// Static estimate of an attack: base + obvious passives + known gate bonuses; no cards, no support.
function attackEstimate(view, p, uid, q, viaMove) {
  const me = COLOSSI[view.units[uid].def], foeUid = view.board[q].unit, foe = COLOSSI[view.units[foeUid].def];
  let a = me.base + gateBonusFor(view, q, me);
  if (me.id === 'RS-C001') a += 2;
  if (me.id === 'RS-C005') a -= 3;
  if (me.id === 'RS-C008' && viaMove) a += 2;
  let d = foe.base + gateBonusFor(view, q, foe);
  if (foe.id === 'RS-C009') d += 1;
  return a - d;
}

function turnChoice(s, p, acts, rng) {
  const view = viewFor(s, p), opp = other(p);
  const capture = acts.find(a => a.type === 'capture');
  if (capture) return capture;

  const threats = new Set(view.players[opp].units.filter(u => view.units[u].zone === 'field' && view.units[u].hold >= 1)
    .map(u => view.units[u].platform));
  const attacks = acts.filter(a => (a.type === 'launch' || a.type === 'move') && view.board[a.platform].unit &&
    view.units[view.board[a.platform].unit].owner === opp)
    .map(a => ({ a, est: attackEstimate(view, p, a.unit, a.platform, a.type === 'move') + (threats.has(a.platform) ? 3 : 0) }));
  attacks.sort((x, y) => y.est - x.est);
  if (attacks.length && attacks[0].est >= 1) return attacks[0].a;

  if (!view.turn.prepPlayed) {
    const preps = acts.filter(a => a.type === 'prep');
    const byDef = id => preps.filter(a => view.players[p].hand.find(h => h.card === a.card)?.def === id);
    const shove = byDef('RS-A040').find(a => threats.has(view.units[a.targets.unit].platform));
    if (shove) return shove;
    const anchor = byDef('RS-A017').find(a => view.units[a.targets.unit].hold >= 1);
    if (anchor) return anchor;
    if (view.players[p].hand.length <= 3) {
      const cycle = [...byDef('RS-A039'), ...byDef('RS-A044'), ...byDef('RS-A048')];
      if (cycle.length) return pick(rng, cycle);
    }
  }

  const launches = acts.filter(a => a.type === 'launch' && !view.board[a.platform].unit).map(a => {
    const def = COLOSSI[view.units[a.unit].def];
    const allies = view.players[p].units.filter(u => view.units[u].zone === 'field' && adjacent(view.units[u].platform, a.platform)).length;
    return { a, score: gateBonusFor(view, a.platform, def) + allies + randInt(rng, 100) / 1000 };
  });
  launches.sort((x, y) => y.score - x.score);
  if (launches.length) return launches[0].a;
  if (attacks.length && attacks[0].est >= 0) return attacks[0].a;
  return acts.find(a => a.type === 'rest');
}

export function simpleBot(s, p, rng) {
  const acts = legalActions(s, p);
  if (!acts.length) return null;
  switch (s.phase) {
    case 'mulligan': {
      // Return expensive cards from the opening hand.
      const hand = s.players[p].hand;
      const heavy = hand.filter(c => ABILITIES[s.cards[c].def].cost >= 3).sort();
      return acts.find(a => JSON.stringify(a.cards) === JSON.stringify(heavy)) ?? acts[0];
    }
    case 'choice':
      if (s.choice.kind === 'discard') {
        return acts.reduce((best, a) => (ABILITIES[s.cards[a.card].def].cost > ABILITIES[s.cards[best.card].def].cost ? a : best));
      }
      return acts[0];
    case 'turn':
      return turnChoice(s, p, acts, rng);
    case 'duel':
      if (s.duel.step === 'support') {
        const options = acts.filter(a => a.unit && s.units[a.unit].hold < 2);
        return options[0] ?? acts.find(a => a.unit === null);
      }
      return duelChoice(s, p, acts);
    default:
      return pick(rng, acts);
  }
}

export const BOTS = { random: randomBot, simple: simpleBot };
