// RulesCore: apply(state, command) -> { ok, state, events }. Pure with respect to the input state (it works on a clone),
// deterministic (all randomness comes from state.rng), and it validates every command against legalActions(),
// so the list of legal actions and the validator can never disagree.
import { ABILITIES, CONTENT_HASH, RULES_VERSION, validateDeck } from './content.js';
import { randInt, seedRng, shuffleInPlace } from './rng.js';
import { adjacent, FIRST_GATE_CELL, GATE_ORDER, OUTER, PLATFORMS } from './board.js';
import { LOGIC } from './abilities.js';
import { breakdown, duelGate, fighterOf } from './power.js';
import * as S from './state.js';

export const START_HAND = 4, TURN_LIMIT = 36, SIGILS_TO_WIN = 3, RESOLUTION_LIMIT = 128, IDLE_TURN_LIMIT = 3;
const { emit, other } = S;

export class MatchError extends Error {
  constructor(code, details = []) {
    super([code, ...[].concat(details)].join(': '));
    this.code = code;
    this.details = [].concat(details);
  }
}

// ---------------------------------------------------------------- match setup (§07 "Подготовка матча")

export function createMatch({ seed = 1, matchId = 'local', players, assignSeats = true }) {
  if (!Array.isArray(players) || players.length !== 2) throw new MatchError('bad-players');
  for (const pl of players) {
    if (pl.contentHash && pl.contentHash !== CONTENT_HASH) {
      throw new MatchError('content-mismatch', `клиент ${pl.contentHash}, сервер ${CONTENT_HASH}`);
    }
  }
  const errors = players.flatMap((pl, i) => validateDeck(pl.deck).map(e => `игрок ${i + 1}: ${e}`));
  if (errors.length) throw new MatchError('illegal-deck', errors);

  const rng = seedRng(seed);
  const flip = assignSeats && randInt(rng, 2) === 1;
  const entrant = { A: flip ? 1 : 0, B: flip ? 0 : 1 };
  const s = {
    rulesVersion: RULES_VERSION, contentHash: CONTENT_HASH, matchId, revision: 0, rng,
    players: {}, cards: {}, units: {}, gates: {}, board: {},
    phase: 'setupGates', setup: { step: 0 }, mulligan: { A: null, B: null },
    round: 0, active: null, turnNo: 0, turn: null, duel: null, choice: null, result: null,
    log: [], nonces: [],
  };
  for (const p of S.SEATS) {
    const src = players[entrant[p]], deck = src.deck;
    // Instance ids are shuffled so an id never tells which ability it is.
    const numbers = shuffleInPlace(rng, deck.abilities.map((_, i) => i + 1));
    const cards = deck.abilities.map((def, i) => {
      const cid = `${p}${String(numbers[i]).padStart(2, '0')}`;
      s.cards[cid] = { def, owner: p };
      return cid;
    });
    const units = deck.colossi.map((def, i) => {
      const uid = `${p}u${i + 1}`;
      s.units[uid] = { def, owner: p, zone: 'reserve', platform: null, hold: 0, readyOn: 0, anchorUntil: null, epoch: 0 };
      return uid;
    });
    const gates = deck.gates.map((def, i) => {
      const gid = `${p}g${i + 1}`;
      s.gates[gid] = { def, owner: p, revealed: false, captured: false, seenBy: [] };
      return gid;
    });
    s.players[p] = {
      name: src.name ?? `Игрок ${entrant[p] + 1}`, entrant: entrant[p],
      deck: cards, hand: [], discard: [], mana: 0, turnIndex: 0, sigils: 0,
      units, gatesToPlace: gates, idleTurns: 0, knownTop: [],
    };
  }
  for (const q of PLATFORMS) s.board[q] = { gate: null, unit: null, removed: false };
  const ctx = { s, events: [], budget: RESOLUTION_LIMIT };
  emit(ctx, {
    t: 'matchStart', names: { A: s.players.A.name, B: s.players.B.name },
    colossi: { A: s.players.A.units.map(u => s.units[u].def), B: s.players.B.units.map(u => s.units[u].def) },
  });
  return { state: s, events: ctx.events };
}

function placeGate(ctx, p, gid, q) {
  const s = ctx.s, pl = s.players[p];
  pl.gatesToPlace = pl.gatesToPlace.filter(g => g !== gid);
  s.board[q].gate = gid;
  emit(ctx, { t: 'gatePlaced', player: p, platform: q, secret: { to: p, gate: gid, gateDef: s.gates[gid].def } });
  if (++s.setup.step < GATE_ORDER.length) return;
  for (const x of S.SEATS) shuffleInPlace(s.rng, s.players[x].deck);
  for (const x of S.SEATS) for (let i = 0; i < START_HAND; i++) S.draw(ctx, x, { limit: false });
  s.phase = 'mulligan';
  emit(ctx, { t: 'mulliganStart' });
}

// One exchange of any number of cards: replacements are dealt first, then the set-aside cards go back and the deck
// is shuffled, so a returned instance can never come straight back (§04).
function mulligan(ctx, p, cards) {
  const s = ctx.s;
  s.mulligan[p] = cards;
  emit(ctx, { t: 'mulliganChosen', player: p });
  if (!s.mulligan.A || !s.mulligan.B) return;
  for (const x of S.SEATS) {
    const pl = s.players[x], aside = s.mulligan[x];
    pl.hand = pl.hand.filter(c => !aside.includes(c));
    for (let i = 0; i < aside.length; i++) S.draw(ctx, x, { limit: false });
    pl.deck.push(...aside);
    shuffleInPlace(s.rng, pl.deck);
    pl.knownTop = [];
    emit(ctx, {
      t: 'mulligan', player: x, count: aside.length,
      secret: { to: x, returned: aside, returnedDefs: aside.map(c => s.cards[c].def) },
    });
  }
  s.mulligan = { A: null, B: null };
  startRound(ctx, 1);
}

// ---------------------------------------------------------------- rounds and turns (§07)

function startRound(ctx, r) {
  const s = ctx.s;
  s.round = r;
  for (const p of S.SEATS) s.players[p].mana = Math.min(6, r + 1); // not carried over
  emit(ctx, { t: 'roundStart', round: r, mana: s.players.A.mana });
  if (r >= 2) for (const p of S.SEATS) S.draw(ctx, p);
  startTurn(ctx, 'A');
}

function startTurn(ctx, p) {
  const s = ctx.s, pl = s.players[p];
  s.active = p;
  s.phase = 'turn';
  s.turnNo++;
  pl.turnIndex++;
  emit(ctx, { t: 'turnStart', player: p, turnNo: s.turnNo, turnIndex: pl.turnIndex });
  for (const u of pl.units) {
    const unit = s.units[u];
    if (unit.zone === 'exhausted' && unit.readyOn <= pl.turnIndex) {
      unit.zone = 'reserve';
      emit(ctx, { t: 'ready', unit: u });
    }
  }
  // Remember where the opponent's colossi stand: those still in place at the end of this turn mature by one.
  const snapshot = {};
  for (const u of S.fieldUnits(s, other(p))) snapshot[u] = s.units[u].epoch;
  s.turn = { prepPlayed: false, hadInput: false, snapshot };
}

function endTurn(ctx) {
  const s = ctx.s, p = s.active, pl = s.players[p];
  for (const [u, epoch] of Object.entries(s.turn.snapshot)) {
    const unit = s.units[u];
    if (unit.zone === 'field' && unit.epoch === epoch) {
      unit.hold++;
      emit(ctx, { t: 'hold', unit: u, hold: unit.hold });
    }
  }
  for (const [u, unit] of Object.entries(s.units)) {
    if (unit.anchorUntil !== null && unit.anchorUntil <= s.turnNo) {
      unit.anchorUntil = null;
      emit(ctx, { t: 'anchorEnd', unit: u });
    }
  }
  pl.idleTurns = s.turn.hadInput ? 0 : pl.idleTurns + 1;
  s.turn = null;
  emit(ctx, { t: 'turnEnd', player: p, turnNo: s.turnNo });
  if (pl.idleTurns >= IDLE_TURN_LIMIT) return endMatch(ctx, other(p), 'idle');
  if (s.turnNo >= TURN_LIMIT) return finishByLimit(ctx);
  if (p === 'A') startTurn(ctx, 'B');
  else startRound(ctx, s.round + 1);
}

// §13: after 36 turns — more sigils wins, then more mature holds, then a draw.
function finishByLimit(ctx) {
  const s = ctx.s;
  const mature = p => S.fieldUnits(s, p).filter(u => s.units[u].hold >= 2).length;
  const [a, b] = S.SEATS.map(p => s.players[p].sigils);
  if (a !== b) return endMatch(ctx, a > b ? 'A' : 'B', 'turn-limit-sigils');
  const [ma, mb] = S.SEATS.map(mature);
  if (ma !== mb) return endMatch(ctx, ma > mb ? 'A' : 'B', 'turn-limit-holds');
  return endMatch(ctx, null, 'turn-limit-draw');
}

function endMatch(ctx, winner, reason) {
  const s = ctx.s;
  s.result = { winner, reason };
  s.phase = 'ended';
  emit(ctx, { t: 'matchEnd', winner, reason, sigils: { A: s.players.A.sigils, B: s.players.B.sigils } });
}

function gainSigil(ctx, p, q, via) {
  const s = ctx.s, gid = s.board[q].gate, g = s.gates[gid];
  s.players[p].sigils++;
  s.board[q].removed = true;
  s.board[q].unit = null;
  g.captured = true;
  g.revealed = true; // a closed gate taken by holding is revealed for the journal only
  emit(ctx, { t: 'sigil', player: p, platform: q, gateDef: g.def, via, sigils: s.players[p].sigils });
  return s.players[p].sigils >= SIGILS_TO_WIN;
}

// ---------------------------------------------------------------- main actions (§08)

function launch(ctx, p, uid, q) {
  const s = ctx.s, defender = s.board[q].unit;
  emit(ctx, { t: 'launch', player: p, unit: uid, platform: q });
  if (defender) {
    const u = s.units[uid];
    u.zone = 'field'; u.platform = q; u.hold = 0; u.epoch++;
    return startDuel(ctx, uid, defender, q, false);
  }
  S.placeOnField(ctx, uid, q);
  endTurn(ctx);
}

function move(ctx, p, uid, q) {
  const s = ctx.s, u = s.units[uid], from = u.platform, cost = adjacent(from, q) ? 0 : 1;
  s.players[p].mana -= cost;
  s.board[from].unit = null;
  emit(ctx, { t: 'move', player: p, unit: uid, from, to: q, cost });
  const defender = s.board[q].unit;
  u.platform = q; u.hold = 0; u.epoch++;
  if (defender) return startDuel(ctx, uid, defender, q, true);
  s.board[q].unit = uid;
  endTurn(ctx);
}

function capture(ctx, p, uid) {
  const s = ctx.s, q = s.units[uid].platform;
  const won = gainSigil(ctx, p, q, 'hold');
  S.toRecovery(ctx, uid, 1, 'capture');
  if (won) return endMatch(ctx, p, 'sigils');
  endTurn(ctx);
}

function playPrep(ctx, p, cid, targets) {
  const s = ctx.s, pl = s.players[p], def = ABILITIES[s.cards[cid].def];
  pl.mana -= def.cost;
  pl.hand = pl.hand.filter(c => c !== cid);
  s.turn.prepPlayed = true;
  emit(ctx, { t: 'prep', player: p, card: cid, def: def.id, targets, cost: def.cost });
  S.tick(ctx);
  const ok = LOGIC[def.id].resolve(ctx, { oid: null, card: cid, def: def.id, owner: p, targets, cost: def.cost });
  pl.discard.push(cid);
  if (!ok) emit(ctx, { t: 'fizzle', card: cid, def: def.id, owner: p });
  if (s.choice) s.phase = 'choice';
}

function resolveChoice(ctx, p, a) {
  const s = ctx.s, pl = s.players[p];
  if (a.type === 'discard') {
    S.discardFromHand(ctx, p, a.card, s.choice.def);
    while (pl.hand.length > S.HAND_MAX) S.discardFromHand(ctx, p, pl.hand[pl.hand.length - 1], 'limit');
  } else {
    pl.deck.splice(0, a.order.length, ...a.order);
    pl.knownTop = a.order.slice();
    emit(ctx, { t: 'arranged', player: p, count: a.order.length, secret: { to: p, order: a.order } });
  }
  s.choice = null;
  s.phase = 'turn';
}

// ---------------------------------------------------------------- duel (§09-§10)

function eligibleSupport(s, p) {
  const d = s.duel;
  return S.fieldUnits(s, p).filter(u => u !== d.attacker && u !== d.defender && adjacent(s.units[u].platform, d.platform));
}

function startDuel(ctx, attacker, defender, q, viaMove) {
  const s = ctx.s, gid = s.board[q].gate, att = s.units[attacker].owner;
  s.phase = 'duel';
  s.duel = {
    platform: q, gate: gid, attacker, defender, viaMove, step: 'support',
    support: { A: null, B: null }, supportChoice: { A: 'none', B: 'none' },
    priority: att, passes: 0, chain: [], nextOid: 1, mods: [], nextMod: 1,
    shroud: {}, silenced: {}, sageUsed: false, aspect: {}, aspectBonusOff: false,
    discountUsed: { A: false, B: false }, history: { A: [], B: [] },
  };
  emit(ctx, { t: 'duelStart', platform: q, attacker, defender, viaMove });
  // B1: open the gate (cannot be countered), one-shot effect, then its permanent rule applies.
  const g = s.gates[gid];
  if (!g.revealed) {
    g.revealed = true;
    emit(ctx, { t: 'gateRevealed', platform: q, gate: gid, gateDef: g.def, owner: g.owner });
    S.tick(ctx);
    if (g.def === 'RS-G003') for (const p of [att, other(att)]) S.draw(ctx, p);
    if (g.def === 'RS-G009') {
      for (const u of [attacker, defender]) {
        s.duel.shroud[u] = true;
        emit(ctx, { t: 'shroud', unit: u, from: 'gate' });
      }
    }
  }
  // B2: both choose an adjacent ally in secret, revealed together.
  for (const p of S.SEATS) s.duel.supportChoice[p] = eligibleSupport(s, p).length ? 'pending' : 'none';
  if (!S.SEATS.some(p => s.duel.supportChoice[p] === 'pending')) finishSupport(ctx);
}

function chooseSupport(ctx, p, unit) {
  const d = ctx.s.duel;
  d.supportChoice[p] = unit ?? 'none';
  emit(ctx, { t: 'supportSubmitted', player: p });
  if (!S.SEATS.some(x => d.supportChoice[x] === 'pending')) finishSupport(ctx);
}

function finishSupport(ctx) {
  const s = ctx.s, d = s.duel;
  for (const p of S.SEATS) {
    const c = d.supportChoice[p];
    if (c !== 'none') {
      d.support[p] = { unit: c, suppressed: false };
      s.units[c].hold = 0;
    }
  }
  emit(ctx, { t: 'supportRevealed', A: d.support.A?.unit ?? null, B: d.support.B?.unit ?? null });
  d.step = 'cards';
  d.priority = s.units[d.attacker].owner;
  d.passes = 0;
  emit(ctx, { t: 'powers', attacker: breakdown(s, d.attacker), defender: breakdown(s, d.defender) });
}

export function costOf(s, p, def) {
  let c = def.cost;
  if (s.duel) {
    const g = s.gates[s.duel.gate].def;
    if (g === 'RS-G010' && def.tags.includes('counter')) c += 1;
    if (g === 'RS-G004' && !s.duel.discountUsed[p]) c -= 1;
  }
  return Math.max(1, c);
}

function playCard(ctx, p, cid, targets) {
  const s = ctx.s, d = s.duel, pl = s.players[p], def = ABILITIES[s.cards[cid].def];
  const cost = costOf(s, p, def);
  pl.mana -= cost;
  d.discountUsed[p] = true; // the first-ability discount is spent on payment, even if the card is then countered
  pl.hand = pl.hand.filter(c => c !== cid);
  const oid = `o${d.nextOid++}`;
  d.chain.push({ oid, card: cid, def: def.id, owner: p, targets, cost });
  emit(ctx, { t: 'play', player: p, oid, card: cid, def: def.id, targets, cost });
  d.passes = 0;
  d.priority = other(p);
}

function pass(ctx, p) {
  const s = ctx.s, d = s.duel;
  d.passes++;
  emit(ctx, { t: 'pass', player: p, chain: d.chain.length });
  if (d.passes < 2) {
    d.priority = other(p);
    return;
  }
  d.passes = 0;
  if (!d.chain.length) return clash(ctx);
  // Two passes over a non-empty chain resolve only its top object; the attacker gets priority again.
  const o = d.chain.pop();
  S.tick(ctx);
  emit(ctx, { t: 'resolve', oid: o.oid, def: o.def, owner: o.owner });
  const ok = LOGIC[o.def].resolve(ctx, o);
  s.players[o.owner].discard.push(o.card);
  if (ok) d.history[o.owner].push(o.def);
  else emit(ctx, { t: 'fizzle', oid: o.oid, def: o.def, owner: o.owner });
  d.priority = s.units[d.attacker].owner;
}

function clash(ctx) {
  const s = ctx.s, d = s.duel;
  const a = breakdown(s, d.attacker), b = breakdown(s, d.defender);
  const mirror = duelGate(s).id === 'RS-G012';
  const winner = a.total !== b.total ? (a.total > b.total ? d.attacker : d.defender) : (mirror ? d.attacker : d.defender);
  const loser = winner === d.attacker ? d.defender : d.attacker;
  const wp = s.units[winner].owner;
  emit(ctx, { t: 'clash', platform: d.platform, attacker: { unit: d.attacker, ...a }, defender: { unit: d.defender, ...b }, winner });
  // B6: sigil, recovery (passives and Немота still apply at this moment), then everyone leaves the platform.
  const won = gainSigil(ctx, wp, d.platform, 'duel');
  const bird = s.units[loser].def === 'RS-C010' && !d.silenced[loser];
  S.toRecovery(ctx, winner, 1, 'won');
  S.toRecovery(ctx, loser, bird ? 1 : 2, bird ? 'lost-bird' : 'lost');
  for (const p of S.SEATS) if (d.support[p]) S.toRecovery(ctx, d.support[p].unit, 1, 'support');
  s.duel = null;
  s.phase = 'turn';
  emit(ctx, { t: 'duelEnd', winner });
  if (won) return endMatch(ctx, wp, 'sigils');
  endTurn(ctx);
}

// ---------------------------------------------------------------- legal actions (the only validator)

function subsets(xs) {
  const out = [];
  for (let m = 0; m < 1 << xs.length; m++) out.push(xs.filter((_, i) => m & (1 << i)).sort());
  return out;
}

function permutations(xs) {
  if (xs.length <= 1) return [xs.slice()];
  return xs.flatMap((x, i) => permutations([...xs.slice(0, i), ...xs.slice(i + 1)]).map(rest => [x, ...rest]));
}

function turnActions(s, p) {
  const pl = s.players[p], out = [];
  if (!s.turn.prepPlayed) {
    for (const cid of pl.hand) {
      const def = ABILITIES[s.cards[cid].def];
      if (def.window !== 'prep' || def.cost > pl.mana) continue;
      for (const targets of LOGIC[def.id].targets(s, p, cid)) out.push({ type: 'prep', card: cid, targets });
    }
  }
  const live = S.livePlatforms(s);
  const hostileOrEmpty = q => !s.board[q].unit || s.units[s.board[q].unit].owner !== p;
  for (const uid of pl.units) {
    const u = s.units[uid];
    if (u.zone === 'reserve') for (const q of live) if (hostileOrEmpty(q)) out.push({ type: 'launch', unit: uid, platform: q });
    if (u.zone !== 'field') continue;
    for (const q of live) {
      if (q !== u.platform && hostileOrEmpty(q) && (adjacent(u.platform, q) ? 0 : 1) <= pl.mana) {
        out.push({ type: 'move', unit: uid, platform: q });
      }
    }
    out.push({ type: 'recall', unit: uid });
    if (u.hold >= 2) out.push({ type: 'capture', unit: uid });
  }
  out.push({ type: 'rest' });
  return out;
}

function duelActions(s, p) {
  const d = s.duel;
  if (d.step === 'support') {
    if (d.supportChoice[p] !== 'pending') return [];
    return [{ type: 'support', unit: null }, ...eligibleSupport(s, p).map(unit => ({ type: 'support', unit }))];
  }
  if (d.priority !== p) return [];
  const pl = s.players[p], out = [{ type: 'pass' }];
  for (const cid of pl.hand) {
    const def = ABILITIES[s.cards[cid].def];
    if (def.window === 'prep') continue; // Подготовка is forbidden in a duel
    if (def.window === 'battle' && d.chain.length) continue; // Бой needs an empty chain
    if (costOf(s, p, def) > pl.mana) continue;
    for (const targets of LOGIC[def.id].targets(s, p, cid)) out.push({ type: 'play', card: cid, targets });
  }
  return out;
}

export function legalActions(s, p) {
  if (s.result) return [];
  switch (s.phase) {
    case 'setupGates': {
      const step = s.setup.step;
      if (GATE_ORDER[step] !== p) return [];
      const cells = step < 2 ? [FIRST_GATE_CELL[p]] : OUTER.filter(q => !s.board[q].gate);
      return s.players[p].gatesToPlace.flatMap(gate => cells.map(platform => ({ type: 'placeGate', gate, platform })));
    }
    case 'mulligan':
      return s.mulligan[p] ? [] : subsets(s.players[p].hand).map(cards => ({ type: 'mulligan', cards }));
    case 'turn':
      return s.active === p ? turnActions(s, p) : [];
    case 'duel':
      return duelActions(s, p);
    case 'choice':
      if (s.choice.player !== p) return [];
      if (s.choice.kind === 'discard') return s.players[p].hand.map(card => ({ type: 'discard', card }));
      return permutations(s.choice.cards).map(order => ({ type: 'arrange', order }));
    default:
      return [];
  }
}

// What a timeout means (§13): priority -> pass, main decision -> rest, secret choices -> decline/keep.
export function defaultAction(s, p) {
  const acts = legalActions(s, p);
  if (!acts.length) return null;
  const find = type => acts.find(a => a.type === type);
  switch (s.phase) {
    case 'mulligan': return acts.find(a => a.cards.length === 0);
    case 'turn': return find('rest');
    case 'duel': return s.duel.step === 'support' ? acts.find(a => a.unit === null) : find('pass');
    case 'choice': return s.choice.kind === 'arrange' ? { type: 'arrange', order: s.choice.cards.slice() } : acts[acts.length - 1];
    default: return acts[0];
  }
}

function sortKeys(x) {
  if (Array.isArray(x)) return x.map(sortKeys);
  if (x && typeof x === 'object') return Object.fromEntries(Object.keys(x).sort().map(k => [k, sortKeys(x[k])]));
  return x;
}

export function actionKey(a) {
  const { player, nonce, revision, matchId, ...rest } = a;
  const c = structuredClone(rest);
  if (c.type === 'mulligan' && Array.isArray(c.cards)) c.cards.sort();
  if (Array.isArray(c.targets?.units)) c.targets.units.sort();
  return JSON.stringify(sortKeys(c));
}

// ---------------------------------------------------------------- command entry point

function perform(ctx, a) {
  const p = a.player;
  switch (a.type) {
    case 'placeGate': return placeGate(ctx, p, a.gate, a.platform);
    case 'mulligan': return mulligan(ctx, p, a.cards);
    case 'prep': return playPrep(ctx, p, a.card, a.targets);
    case 'launch': return launch(ctx, p, a.unit, a.platform);
    case 'move': return move(ctx, p, a.unit, a.platform);
    case 'recall':
      S.toReserve(ctx, a.unit, 'recall');
      return endTurn(ctx);
    case 'capture': return capture(ctx, p, a.unit);
    case 'rest':
      emit(ctx, { t: 'rest', player: p });
      return endTurn(ctx);
    case 'support': return chooseSupport(ctx, p, a.unit);
    case 'play': return playCard(ctx, p, a.card, a.targets);
    case 'pass': return pass(ctx, p);
    case 'discard':
    case 'arrange': return resolveChoice(ctx, p, a);
    default: throw new Error(`unknown action ${a.type}`);
  }
}

const reject = (state, error) => ({ ok: false, state, events: [], error });

export function apply(state, cmd) {
  if (!cmd || !S.SEATS.includes(cmd.player)) return reject(state, 'bad-player');
  if (state.result) return reject(state, 'match-over');
  // A retried command is recognised as a duplicate before anything else about it is checked.
  if (cmd.nonce !== undefined && state.nonces.includes(cmd.nonce)) return reject(state, 'duplicate-nonce');
  if (cmd.revision !== undefined && cmd.revision !== state.revision) return reject(state, 'stale-revision');

  let action;
  if (cmd.type === 'concede') action = cmd;
  else if (cmd.type === 'timeout') {
    action = defaultAction(state, cmd.player);
    if (!action) return reject(state, 'nothing-pending');
  } else {
    const key = actionKey(cmd);
    action = legalActions(state, cmd.player).find(a => actionKey(a) === key);
    if (!action) return reject(state, 'illegal');
  }

  const s = structuredClone(state);
  const ctx = { s, events: [], budget: RESOLUTION_LIMIT };
  if (cmd.nonce !== undefined) s.nonces.push(cmd.nonce);
  if (cmd.type !== 'timeout' && s.turn && s.active === cmd.player) s.turn.hadInput = true;
  try {
    if (cmd.type === 'concede') endMatch(ctx, other(cmd.player), 'concede');
    else perform(ctx, { ...structuredClone(action), player: cmd.player });
  } catch (e) {
    if (!(e instanceof S.BudgetError)) throw e;
    // A content error: the match is voided with a report, never an accidental win (§13).
    s.result = { winner: null, reason: 'resolution-limit', void: true };
    s.phase = 'ended';
    emit(ctx, { t: 'matchVoid', reason: 'resolution-limit' });
  }
  s.revision++;
  return { ok: true, state: s, events: ctx.events };
}

export { fighterOf };
