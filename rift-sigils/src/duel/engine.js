// Hybrid duel engine (rules v0.3). Pure and deterministic like the v0.1 core: apply(state, command) -> { ok, state, events }.
// Real time lives outside: the session sends { player: 'system', type: 'endRound' } when the round timer runs out.
//
// Flow: coin flip -> bout { a gate laid face down in turn, fighters chosen in secret, rounds } -> next bout -> ...
// until a life gauge hits 0 or a player has no colossi left.
// A round: both play cards and the gate owner may order the gate open; the opponent only sees that something was done.
// Tactic cards (draws, mana) are not combat cards: they take effect as they are played and no counter can touch them.
// At the end of the round everything is revealed: counters look for what they cancel, the gate opens, the combat cards
// take effect in the order they were played, then the forces meet: the weaker fighter loses the difference, the stronger
// one takes part of the blow back. G below zero knocks the colossus out and hits the life gauge.
// Mana and the round timer grow while both fighters survive and start over with each bout.
// Back from a bout a colossus is tired: it keeps what G it has left (at least half) until it sits out a bout.
import { ASPECTS, BEATS, CARDS, COLOSSI, DUEL_CONTENT_HASH, DUEL_RULES_VERSION, GATES, playableBy, ROUND_RULES, RULES, validateDuelDeck } from './content.js';
import { randInt, seedRng, shuffleInPlace } from '../core/rng.js';

export const SEATS = ['A', 'B'];
export const other = p => (p === 'A' ? 'B' : 'A');

export class DuelError extends Error {
  constructor(code, details = []) {
    super([code, ...[].concat(details)].join(': '));
    this.code = code;
    this.details = [].concat(details);
  }
}

function emit(ctx, ev) {
  const e = { seq: ctx.s.log.length, ...ev };
  ctx.events.push(e);
  ctx.s.log.push(e);
}

const passiveOf = (s, uid) => (uid ? COLOSSI[s.units[uid].def].passive : {});
const baseG = (s, uid) => COLOSSI[s.units[uid].def].g;
export const activationsFor = (s, p) => passiveOf(s, s.players[p].fighter).activations ?? RULES.activationsPerRound;

// ---------------------------------------------------------------- setup

export function createDuel({ seed = 1, matchId = 'duel', players, assignSeats = true }) {
  if (!Array.isArray(players) || players.length !== 2) throw new DuelError('bad-players');
  for (const pl of players) if (pl.contentHash && pl.contentHash !== DUEL_CONTENT_HASH) throw new DuelError('content-mismatch');
  const errors = players.flatMap((pl, i) => validateDuelDeck(pl.deck).map(e => `игрок ${i + 1}: ${e}`));
  if (errors.length) throw new DuelError('illegal-deck', errors);
  const rng = seedRng(seed);
  const flip = assignSeats && randInt(rng, 2) === 1;
  const entrant = { A: flip ? 1 : 0, B: flip ? 0 : 1 };
  const s = {
    rulesVersion: DUEL_RULES_VERSION, contentHash: DUEL_CONTENT_HASH, matchId, revision: 0, rng,
    phase: 'gate', round: 0, boutNo: 0, gateTurn: 'A', bout: null, timerMs: 0,
    players: {}, units: {}, cards: {}, gates: {}, result: null, log: [], nonces: [],
  };
  for (const p of SEATS) {
    const src = players[entrant[p]], deck = src.deck;
    const numbers = shuffleInPlace(rng, deck.cards.map((_, i) => i + 1));
    const cards = deck.cards.map((def, i) => {
      const cid = `${p}${String(numbers[i]).padStart(2, '0')}`;
      s.cards[cid] = { def, owner: p };
      return cid;
    });
    const units = deck.colossi.map((def, i) => {
      const uid = `${p}u${i + 1}`;
      s.units[uid] = { def, owner: p, zone: 'reserve', g: COLOSSI[def].g, startG: COLOSSI[def].g, shield: 0 };
      return uid;
    });
    const gates = deck.gates.map((def, i) => {
      const gid = `${p}g${i + 1}`;
      s.gates[gid] = { def, owner: p, used: false };
      return gid;
    });
    s.players[p] = {
      name: src.name ?? `Игрок ${entrant[p] + 1}`, entrant: entrant[p], life: RULES.life,
      mana: 0, manaMax: 0, deck: shuffleInPlace(rng, cards), hand: [], discard: [], exiled: [], units, gates,
      fighter: null, choice: null, activations: 0, ready: false, nextMana: 0,
    };
  }
  const ctx = { s, events: [] };
  s.gateTurn = randInt(rng, 2) === 0 ? 'A' : 'B';
  emit(ctx, { t: 'coin', first: s.gateTurn, names: { A: s.players.A.name, B: s.players.B.name } });
  startBout(ctx);
  return { state: s, events: ctx.events };
}

// ---------------------------------------------------------------- gates

const gateOf = s => (s.bout?.gate ? GATES[s.gates[s.bout.gate].def] : null);
export const gateOwner = s => (s.bout?.gate ? s.gates[s.bout.gate].owner : null);
// A field rule works while the gate is open; a round rule only in the round the gate was opened.
const fieldRule = (s, name) => !!s.bout?.gateOpen && gateOf(s)?.rule === name;
const roundRule = (s, name) => (s.bout?.roundRule?.rule === name ? s.bout.roundRule : null);
// Каменный круг: healing and stealing do not work for the gate owner's opponent.
const circleBlocks = (s, p) => fieldRule(s, 'circle') && gateOwner(s) !== p;

// The aspect bonus the bout's gate gives this colossus (only the owner's fighter gets it, when the gate opens).
export function gateBonus(s, uid) {
  const g = gateOf(s);
  if (!g) return 0;
  return g.bonus[ASPECTS.indexOf(COLOSSI[s.units[uid].def].aspect)];
}

// The owner's gate turns face up: the owner's fighter gets its aspect bonus, then the gate does what it does.
function openGateNow(ctx, owner) {
  const s = ctx.s, g = gateOf(s), foeP = other(owner);
  s.bout.gateOpen = true;
  emit(ctx, { t: 'gateRevealed', gate: s.bout.gate, gateDef: g.id, owner, kind: g.kind });
  const self = s.players[owner].fighter, foe = s.players[foeP].fighter;
  const bonus = gateBonus(s, self);
  if (bonus) {
    gain(ctx, self, bonus, 'gateBonus');
    s.units[self].startG += bonus;
  }
  if (ROUND_RULES.includes(g.rule)) s.bout.roundRule = { rule: g.rule, owner };
  for (const [op, a] of g.open) {
    switch (op) {
      case 'damage': damage(ctx, foe, a, { why: g.id }); break;
      case 'pierce': damage(ctx, foe, a, { pierce: true, why: g.id }); break;
      case 'shield': addShield(ctx, self, a); break;
      case 'draw': for (let i = 0; i < a; i++) draw(ctx, owner); break;
      case 'mana':
        s.players[owner].nextMana += a;
        emit(ctx, { t: 'mana', player: owner, amount: a, next: true, why: g.id });
        break;
      case 'restore': if (s.units[self].g < s.units[self].startG) gain(ctx, self, s.units[self].startG - s.units[self].g, g.id); break;
      case 'drainMana':
        s.players[foeP].nextMana -= a;
        emit(ctx, { t: 'mana', player: foeP, amount: -a, next: true, why: g.id });
        break;
      case 'swap': {
        const x = s.units[self], y = s.units[foe];
        [x.g, y.g] = [y.g, x.g];
        emit(ctx, { t: 'swap', units: [self, foe], g: { [self]: x.g, [foe]: y.g } });
        break;
      }
      case 'punishStronger':
        if (s.units[foe].g > s.units[self].g) damage(ctx, foe, a, { why: g.id });
        else emit(ctx, { t: 'trapMissed', gate: g.id, player: owner });
        break;
      default: throw new Error(`unknown gate op ${op}`);
    }
  }
}

// ---------------------------------------------------------------- bouts

function startBout(ctx) {
  const s = ctx.s;
  s.boutNo++;
  let placer = s.gateTurn;
  const free = p => s.players[p].gates.filter(g => !s.gates[g].used);
  if (!free(placer).length) placer = other(placer);
  s.bout = {
    n: s.boutNo, gate: null, gateOpen: false, placer: free(placer).length ? placer : null, rounds: 0, queue: [],
    roundRule: null, fought: { A: null, B: null },
  };
  s.gateTurn = other(s.gateTurn);
  emit(ctx, { t: 'boutStart', n: s.boutNo, placer: s.bout.placer });
  if (s.bout.placer) s.phase = 'gate';
  else choosePhase(ctx);
}

// The gate is laid face down: only its owner knows what it is.
function placeGate(ctx, p, gid) {
  const s = ctx.s;
  s.gates[gid].used = true;
  s.bout.gate = gid;
  emit(ctx, { t: 'gatePlaced', player: p, gate: gid, secret: { to: p, gateDef: s.gates[gid].def } });
  choosePhase(ctx);
}

function choosePhase(ctx) {
  const s = ctx.s;
  for (const p of SEATS) {
    const pl = s.players[p];
    pl.choice = null;
    if (pl.fighter) continue;
    if (!pl.units.some(u => s.units[u].zone === 'reserve')) return endMatch(ctx, other(p), 'no-colossi');
  }
  s.phase = 'choose';
  if (SEATS.every(p => s.players[p].fighter)) openBout(ctx);
}

function choose(ctx, p, uid) {
  const s = ctx.s;
  s.players[p].choice = uid;
  emit(ctx, { t: 'chosen', player: p });
  if (!SEATS.every(x => s.players[x].fighter || s.players[x].choice)) return;
  for (const x of SEATS) {
    const pl = s.players[x];
    if (pl.fighter) continue;
    pl.fighter = pl.choice;
    pl.choice = null;
    s.units[pl.fighter].zone = 'field';
  }
  emit(ctx, { t: 'fighters', A: s.players.A.fighter, B: s.players.B.fighter });
  openBout(ctx);
}

// The fighters stand on the closed gate with the G they have (a tired colossus has less); hands are reshuffled.
function openBout(ctx) {
  const s = ctx.s;
  for (const p of SEATS) {
    const uid = s.players[p].fighter, u = s.units[uid];
    s.bout.fought[p] = uid;
    u.startG = baseG(s, uid);
    u.down = false;
    u.shield = 0;
    emit(ctx, { t: 'fighterReady', unit: uid, g: u.g, startG: u.startG });
    const shield = passiveOf(s, uid).startShield;
    if (shield) addShield(ctx, uid, shield, 'ability');
  }
  for (const p of SEATS) {
    const pl = s.players[p];
    pl.deck.push(...pl.hand, ...pl.discard);
    pl.hand = [];
    pl.discard = [];
    shuffleInPlace(s.rng, pl.deck);
    emit(ctx, { t: 'reshuffle', player: p, deck: pl.deck.length });
    const n = RULES.startHand + (passiveOf(s, pl.fighter).extraDraw ?? 0);
    for (let i = 0; i < n; i++) draw(ctx, p);
  }
  startRound(ctx, true);
}

// ---------------------------------------------------------------- rounds

function startRound(ctx, first = false) {
  const s = ctx.s;
  s.round++;
  s.bout.rounds++;
  s.bout.queue = [];
  s.bout.roundRule = null;
  if (s.round > RULES.roundLimit) return finishByLife(ctx, 'round-limit');
  s.timerMs = RULES.timerMs(s.bout.rounds);
  s.phase = 'round';
  for (const p of SEATS) {
    const pl = s.players[p];
    pl.mana = pl.manaMax = Math.max(0, RULES.mana(s.bout.rounds) + pl.nextMana);
    pl.nextMana = 0;
    pl.activations = 0;
    pl.ready = false;
  }
  emit(ctx, { t: 'roundStart', round: s.round, boutRound: s.bout.rounds, timerMs: s.timerMs, mana: { A: s.players.A.mana, B: s.players.B.mana } });
  if (!first) for (const p of SEATS) draw(ctx, p);
  if (fieldRule(s, 'forge')) {
    for (const p of SEATS) gain(ctx, s.players[p].fighter, 40, 'gate');
    gain(ctx, s.players[gateOwner(s)].fighter, 40, 'gate');
  }
  for (const p of SEATS) {
    const uid = s.players[p].fighter, pass = passiveOf(s, uid);
    if (pass.roundGain && !first) gain(ctx, uid, pass.roundGain, 'ability');
    if (pass.roundHeal && !first) heal(ctx, uid, pass.roundHeal, 'ability');
  }
}

// Draw the first card of the deck the current fighter can use; cards for other colossi stay where they are.
function draw(ctx, p) {
  const s = ctx.s, pl = s.players[p];
  const fighter = pl.fighter && s.units[pl.fighter].def;
  if (!fighter) return;
  if (pl.hand.length >= RULES.handMax) return emit(ctx, { t: 'handFull', player: p });
  const i = pl.deck.findIndex(c => playableBy(s.cards[c].def, fighter));
  if (i < 0) return emit(ctx, { t: 'drawNone', player: p });
  const [cid] = pl.deck.splice(i, 1);
  pl.hand.push(cid);
  emit(ctx, { t: 'draw', player: p, secret: { to: p, card: cid, def: s.cards[cid].def } });
}

// What an activation costs now: the sum of its cards (Дуэлянт облаков gets his first activation of a round cheaper).
export function activationCost(s, p, cardIds) {
  const sum = cardIds.reduce((x, cid) => x + CARDS[s.cards[cid].def].cost, 0);
  const pl = s.players[p], discount = pl.activations === 0 ? passiveOf(s, pl.fighter).discount ?? 0 : 0;
  return Math.max(0, sum - discount);
}

function gain(ctx, uid, n, why) {
  const u = ctx.s.units[uid];
  u.g += n;
  emit(ctx, { t: 'gain', unit: uid, amount: n, g: u.g, why });
}

function addShield(ctx, uid, n, why) {
  const u = ctx.s.units[uid];
  const amount = Math.round(n * (passiveOf(ctx.s, uid).shieldScale ?? 1));
  u.shield += amount;
  emit(ctx, { t: 'shield', unit: uid, amount, shield: u.shield, why });
}

// Healing never goes above full strength (base G plus the gate bonus).
function heal(ctx, uid, n, why) {
  const s = ctx.s, u = s.units[uid];
  if (circleBlocks(s, u.owner)) return emit(ctx, { t: 'healBlocked', unit: uid });
  const before = u.g;
  u.g = Math.max(u.g, Math.min(u.startG, u.g + n));
  if (u.g !== before || why !== 'ability') emit(ctx, { t: 'heal', unit: uid, amount: u.g - before, g: u.g, why });
}

// Damage first eats the shield (unless it pierces), then G. G is the colossus' health: below zero it falls,
// and what went below zero hits its player's life gauge.
function damage(ctx, uid, n, { pierce = false, why } = {}) {
  const s = ctx.s, u = s.units[uid];
  let left = n;
  if (!pierce && u.shield > 0 && left > 0) {
    const a = Math.min(u.shield, left);
    u.shield -= a;
    left -= a;
    emit(ctx, { t: 'shieldAbsorb', unit: uid, amount: a, shield: u.shield });
  }
  if (left <= 0) return 0;
  const before = u.g;
  u.g -= left;
  let over = 0;
  if (u.g < 0 && !u.down) {
    over = -u.g;
    u.g = 0;
    u.down = true;
    u.lastOver = over;
    // the difference in power at the knockout blow decides whether the colossus leaves the game
    const foe = s.players[other(u.owner)].fighter;
    u.koDiff = Math.max(0, (foe ? s.units[foe].g : 0) - Math.max(0, before));
    s.players[u.owner].life -= over + RULES.koLife;
  } else if (u.g < 0) u.g = 0;
  emit(ctx, { t: 'damage', unit: uid, amount: left, g: u.g, over, ko: over ? RULES.koLife : 0, life: s.players[u.owner].life, why });
  return over;
}

const HOSTILE = ['damage', 'pierce', 'damageIfStrong', 'steal'];

// A card's operations. In the round the Чаша отражений trap opens, the opponent's attacks turn onto their own fighter.
// `now`: a tactic card played mid-round, whose mana stays its player's secret until the reveal.
function applyOps(ctx, p, def, fusion, now = false) {
  const s = ctx.s, self = s.players[p].fighter, foe = s.players[other(p)].fighter;
  const reflect = roundRule(s, 'reflect');
  const reflected = !!reflect && reflect.owner !== p;
  const victim = reflected ? self : foe, taker = reflected ? foe : self;
  if (reflected && def && CARDS[def].ops.some(o => HOSTILE.includes(o[0]))) emit(ctx, { t: 'reflected', player: p, def });
  for (const [op, a, b, c] of def ? CARDS[def].ops : []) {
    if (!s.units[self] || s.units[self].zone !== 'field' || !s.units[foe] || s.units[foe].zone !== 'field') return;
    switch (op) {
      case 'gain': gain(ctx, self, a, def); break;
      case 'damage': damage(ctx, victim, a, { why: def }); break;
      case 'pierce': damage(ctx, victim, a, { pierce: true, why: def }); break;
      case 'damageIfStrong': damage(ctx, victim, s.units[victim].g >= c ? a : b, { why: def }); break;
      case 'steal': {
        if (circleBlocks(s, s.units[taker].owner)) { emit(ctx, { t: 'stealBlocked', unit: taker }); break; }
        if (passiveOf(s, victim).stealImmune) { emit(ctx, { t: 'stealBlocked', unit: victim, why: 'ability' }); break; }
        const want = Math.round(a * (passiveOf(s, taker).stealScale ?? 1));
        const took = Math.min(want, Math.max(0, s.units[victim].g));
        s.units[victim].g -= took;
        emit(ctx, { t: 'damage', unit: victim, amount: took, g: s.units[victim].g, over: 0, life: s.players[s.units[victim].owner].life, why: def });
        gain(ctx, taker, took, def);
        break;
      }
      case 'shield': addShield(ctx, self, a, def); break;
      case 'breakShield': {
        const had = s.units[foe].shield;
        s.units[foe].shield = 0;
        emit(ctx, { t: 'shieldBroken', unit: foe, amount: had });
        break;
      }
      case 'heal': heal(ctx, self, a, def); break;
      case 'restore': {
        if (circleBlocks(s, p)) { emit(ctx, { t: 'healBlocked', unit: self }); break; }
        const u = s.units[self];
        if (u.g < u.startG) gain(ctx, self, u.startG - u.g, def);
        break;
      }
      case 'counter': break; // settled before resolution, see settleCounters()
      case 'draw': for (let i = 0; i < a; i++) draw(ctx, p); break;
      case 'mana':
        s.players[p].nextMana += a;
        emit(ctx, now ? { t: 'mana', player: p, secret: { to: p, amount: a, next: true } } : { t: 'mana', player: p, amount: a, next: true });
        break;
      default: throw new Error(`unknown op ${op}`);
    }
  }
  if (fusion) {
    const extra = passiveOf(s, self).fusionGain;
    if (extra) gain(ctx, self, extra, 'ability');
    if (fieldRule(s, 'gallery') && gateOwner(s) === p) gain(ctx, self, 120, 'gate');
  }
}

const isCounterCard = def => CARDS[def].ops.some(o => o[0] === 'counter');
const isTactic = def => CARDS[def].kind === 'tactic';

// Playing cards queues them, face down for the opponent: combat cards take effect at the end of the round, tactic cards
// at once (in a fusion, the tactic part at once and the rest at the end of the round).
function activate(ctx, p, cardIds) {
  const s = ctx.s, pl = s.players[p];
  const cost = activationCost(s, p, cardIds);
  pl.mana -= cost;
  pl.activations++;
  pl.hand = pl.hand.filter(c => !cardIds.includes(c));
  for (const cid of cardIds) (CARDS[s.cards[cid].def].once ? pl.exiled : pl.discard).push(cid);
  const defs = cardIds.map(c => s.cards[c].def);
  const id = `r${s.round}a${s.bout.queue.length + 1}`;
  const entry = { id, player: p, kind: 'cards', cards: cardIds, defs, cost, fusion: cardIds.length > 1, cancelled: false };
  s.bout.queue.push(entry);
  emit(ctx, { t: 'activate', id, player: p, secret: { to: p, kind: 'cards', cards: cardIds, defs, cost, fusion: entry.fusion } });
  for (const def of defs.filter(isTactic)) applyOps(ctx, p, def, false, true);
}

// Ordering the gate open is free and uses no activation, but to the opponent it looks like any other action.
function orderGate(ctx, p) {
  const s = ctx.s;
  const id = `r${s.round}a${s.bout.queue.length + 1}`;
  s.bout.queue.push({ id, player: p, kind: 'gate', cancelled: false });
  emit(ctx, { t: 'activate', id, player: p, secret: { to: p, kind: 'gate' } });
}

// What an opponent's action is, for a counter's condition. Tactic cards are not combat cards: nothing cancels them,
// so an action of tactic cards alone is no target at all.
function matchesCounter(a, what) {
  if (a.kind === 'gate') return what === 'any' || what === 'gate';
  const kinds = a.defs.map(d => CARDS[d].kind);
  switch (what) {
    case 'any': return a.defs.some(d => !isTactic(d));
    case 'attack': return kinds.includes('attack');
    case 'defense': return kinds.includes('defense');
    case 'counter': return a.defs.some(isCounterCard);
    default: return false;
  }
}

// Counters are conditions, so when they were played does not matter. Counters of counters go first, then the rest;
// within a layer in the order played. Each cancels the first matching action of the opponent that still stands.
function settleCounters(ctx) {
  const q = ctx.s.bout.queue;
  for (const layer of [w => w === 'counter', w => w !== 'counter']) {
    for (const a of q) {
      if (a.kind !== 'cards' || a.cancelled) continue;
      for (const def of a.defs) {
        for (const [op, what, drawOnMiss] of CARDS[def].ops) {
          if (op !== 'counter' || !layer(what) || a.cancelled) continue;
          const victim = q.find(x => x.player !== a.player && !x.cancelled && matchesCounter(x, what));
          if (victim) {
            victim.cancelled = true;
            // a fusion's tactic part has already happened: only its combat cards are cancelled
            emit(ctx, { t: 'countered', id: victim.id, by: a.id, byDef: def, what, player: victim.player, kind: victim.kind, defs: (victim.defs ?? []).filter(d => !isTactic(d)) });
          } else {
            emit(ctx, { t: 'counterMiss', id: a.id, def, what, player: a.player });
            for (let i = 0; i < (drawOnMiss ?? 0); i++) draw(ctx, a.player);
          }
        }
      }
    }
  }
}

// End of the round, part one: everything is revealed, counters are settled, the gate opens, then the combat cards take
// effect in the order they were played (tactic cards already did when played). A knockout stops the rest: those cards
// are spent without effect.
function resolveQueue(ctx) {
  const s = ctx.s;
  if (s.bout.queue.length) {
    emit(ctx, { t: 'reveal', actions: s.bout.queue.map(a => ({ id: a.id, player: a.player, kind: a.kind, defs: a.defs ?? [], fusion: !!a.fusion })) });
  }
  settleCounters(ctx);
  const gate = s.bout.queue.find(a => a.kind === 'gate' && !a.cancelled);
  if (gate) openGateNow(ctx, gate.player);
  for (const a of s.bout.queue) {
    if (a.kind !== 'cards' || a.cancelled) continue;
    const combat = a.defs.filter(d => !isTactic(d));
    if (!combat.length && !a.fusion) continue;
    if (SEATS.some(p => s.units[s.players[p].fighter]?.down)) {
      emit(ctx, { t: 'fizzle', id: a.id, player: a.player, defs: combat });
      continue;
    }
    emit(ctx, { t: 'resolve', id: a.id, player: a.player, defs: a.defs, fusion: a.fusion });
    for (const def of combat) applyOps(ctx, a.player, def, false);
    if (a.fusion) applyOps(ctx, a.player, null, true);
  }
}

// A knockout ends the bout at once, whether it came from a card, a gate or the attack.
function afterDamage(ctx) {
  const s = ctx.s;
  if (s.phase === 'ended') return true;
  const down = SEATS.filter(p => s.players[p].fighter && s.units[s.players[p].fighter].down);
  for (const p of down) {
    const uid = s.players[p].fighter, u = s.units[uid];
    const removed = (u.koDiff ?? 0) > RULES.removeOver;
    u.zone = removed ? 'removed' : 'reserve';
    u.down = false;
    u.shield = 0;
    s.players[p].fighter = null;
    emit(ctx, { t: 'knockout', unit: uid, player: p, removed, over: u.lastOver ?? 0, diff: u.koDiff ?? 0 });
  }
  const dead = SEATS.filter(p => s.players[p].life <= 0);
  if (dead.length === 2) {
    const [a, b] = SEATS.map(p => s.players[p].life);
    endMatch(ctx, a === b ? null : a > b ? 'A' : 'B', 'life');
    return true;
  }
  if (dead.length === 1) { endMatch(ctx, other(dead[0]), 'life'); return true; }
  if (!down.length) return false;
  // The winner goes back to the reserve too: both players choose again for the next bout.
  for (const p of SEATS) {
    const uid = s.players[p].fighter;
    if (!uid) continue;
    const u = s.units[uid];
    u.zone = 'reserve';
    u.shield = 0;
    s.players[p].fighter = null;
    emit(ctx, { t: 'recall', unit: uid, player: p, g: u.g });
  }
  // Rest: who fought is tired and keeps what is left of its G (at least half, a knocked-out one exactly half);
  // who sat the whole bout out is back to full strength.
  for (const p of SEATS) {
    for (const uid of s.players[p].units) {
      const u = s.units[uid];
      if (u.zone === 'removed') continue;
      const full = baseG(s, uid);
      if (uid === s.bout.fought[p] && !passiveOf(s, uid).noFatigue) {
        u.g = Math.min(full, Math.max(u.g, Math.round((full * RULES.restFloor) / 10) * 10));
        emit(ctx, { t: 'tired', unit: uid, player: p, g: u.g, full });
      } else u.g = full;
      u.startG = full;
    }
  }
  // A gate nobody opened goes back to its owner, still unknown to the opponent.
  const g = s.bout.gate;
  if (g && !s.bout.gateOpen) s.gates[g].used = false;
  emit(ctx, { t: 'boutEnd', n: s.bout.n, gate: g, gateOpened: s.bout.gateOpen, owner: gateOwner(s), gateReturned: !!g && !s.bout.gateOpen });
  startBout(ctx);
  return true;
}

// What each fighter brings to the attack: its G, the aspect edge and abilities. Only the attack sees these bonuses.
export function attackValue(s, p) {
  const uid = s.players[p].fighter, u = s.units[uid], k = COLOSSI[u.def], pass = k.passive;
  const foe = s.units[s.players[other(p)].fighter];
  const g = Math.max(0, u.g), parts = [];
  if (BEATS[k.aspect] === COLOSSI[foe.def].aspect) parts.push({ why: 'aspect', n: RULES.aspectEdge });
  if (pass.attack) parts.push({ why: 'ability', n: pass.attack });
  if (pass.attackIfWeaker && foe.g > u.g) parts.push({ why: 'ability', n: pass.attackIfWeaker });
  return { unit: uid, g, value: Math.max(0, g + parts.reduce((x, y) => x + y.n, 0)), parts };
}

// The clash: the weaker loses the difference, the stronger takes back part of it (recoil).
// Under the Белый амфитеатр trap the roles swap: the stronger takes the loss, the weaker the recoil.
export function clash(s) {
  const A = attackValue(s, 'A'), B = attackValue(s, 'B');
  const inverted = !!roundRule(s, 'weakerWins');
  const out = { A, B, inverted, loser: null, loss: 0, recoil: 0, tie: 0 };
  // equal forces wear both down, so that a bout always comes to an end
  if (A.value === B.value) { out.tie = RULES.minLoss; return out; }
  const weaker = A.value < B.value ? 'A' : 'B';
  out.loser = inverted ? other(weaker) : weaker;
  const d = Math.abs(A.value - B.value);
  out.loss = Math.round(Math.max(d, RULES.minLoss) * (passiveOf(s, s.players[out.loser].fighter).lossScale ?? 1));
  out.recoil = Math.round(d * RULES.recoil);
  return out;
}

function endRound(ctx) {
  const s = ctx.s;
  emit(ctx, { t: 'roundEnd', round: s.round, queued: s.bout.queue.length });
  resolveQueue(ctx);
  if (afterDamage(ctx)) return;
  const c = clash(s);
  emit(ctx, { t: 'attack', A: c.A, B: c.B, inverted: c.inverted, loser: c.loser, loss: c.loss, recoil: c.recoil, tie: c.tie });
  if (c.tie) for (const p of SEATS) damage(ctx, s.players[p].fighter, c.tie, { why: 'attack' });
  if (c.loser) {
    const winner = other(c.loser);
    damage(ctx, s.players[c.loser].fighter, c.loss, { why: 'attack' });
    if (c.recoil) damage(ctx, s.players[winner].fighter, c.recoil, { why: 'recoil' });
    if (RULES.rally) {
      s.players[c.loser].nextMana += RULES.rally;
      emit(ctx, { t: 'mana', player: c.loser, amount: RULES.rally, next: true, why: 'rally' });
    }
  }
  if (!afterDamage(ctx)) startRound(ctx);
}

// What the fighters will look like after the queued effects, before the attack. With a viewer, only that player's
// own actions are counted: the opponent's are hidden, and the forecast must not leak them.
export function previewRound(state, viewer = null) {
  if (state.phase !== 'round') return null;
  const s = structuredClone(state);
  if (viewer) s.bout.queue = s.bout.queue.filter(a => a.player === viewer);
  const ctx = { s, events: [] };
  resolveQueue(ctx);
  const f = p => {
    const u = s.units[s.players[p].fighter];
    return { g: u.g, shield: u.shield, down: !!u.down };
  };
  const out = { A: f('A'), B: f('B'), inverted: !!roundRule(s, 'weakerWins') };
  if (!out.A.down && !out.B.down) {
    const c = clash(s);
    out.attack = { A: c.A.value, B: c.B.value, loser: c.loser, loss: c.loss, recoil: c.recoil, tie: c.tie };
  }
  return out;
}

function finishByLife(ctx, reason) {
  const s = ctx.s, [a, b] = SEATS.map(p => s.players[p].life);
  endMatch(ctx, a === b ? null : a > b ? 'A' : 'B', reason);
}

function endMatch(ctx, winner, reason) {
  const s = ctx.s;
  s.result = { winner, reason };
  s.phase = 'ended';
  emit(ctx, { t: 'matchEnd', winner, reason, life: { A: s.players.A.life, B: s.players.B.life } });
}

// ---------------------------------------------------------------- legal actions and commands

function subsets(xs, max) {
  const out = [];
  const rec = (start, pick) => {
    if (pick.length) out.push(pick.slice());
    if (pick.length === max) return;
    for (let i = start; i < xs.length; i++) { pick.push(xs[i]); rec(i + 1, pick); pick.pop(); }
  };
  rec(0, []);
  return out;
}

export function legalActions(s, p) {
  if (s.result || !SEATS.includes(p)) return [];
  const pl = s.players[p];
  switch (s.phase) {
    case 'gate':
      if (s.bout.placer !== p) return [];
      return pl.gates.filter(g => !s.gates[g].used).map(gate => ({ type: 'placeGate', gate }));
    case 'choose':
      if (pl.fighter || pl.choice) return [];
      return pl.units.filter(u => s.units[u].zone === 'reserve').map(unit => ({ type: 'choose', unit }));
    case 'round': {
      if (pl.ready) return [];
      const out = [];
      if (pl.activations < activationsFor(s, p)) {
        const fighter = s.units[pl.fighter].def;
        const usable = pl.hand.filter(c => playableBy(s.cards[c].def, fighter)).sort();
        for (const cards of subsets(usable, RULES.fusionMax)) {
          if (activationCost(s, p, cards) <= pl.mana) out.push({ type: 'activate', cards });
        }
      }
      if (gateOwner(s) === p && !s.bout.gateOpen && !s.bout.queue.some(a => a.kind === 'gate')) out.push({ type: 'openGate' });
      out.push({ type: 'ready' });
      return out;
    }
    default:
      return [];
  }
}

const key = a => {
  const { player, nonce, revision, ...rest } = a;
  const c = { ...rest };
  if (Array.isArray(c.cards)) c.cards = c.cards.slice().sort();
  return JSON.stringify(Object.keys(c).sort().map(k => [k, c[k]]));
};
export const actionKey = key;

const reject = (state, error) => ({ ok: false, state, events: [], error });

export function apply(state, cmd) {
  if (!cmd) return reject(state, 'bad-command');
  if (state.result) return reject(state, 'match-over');
  if (cmd.nonce !== undefined && state.nonces.includes(cmd.nonce)) return reject(state, 'duplicate-nonce');
  if (cmd.revision !== undefined && cmd.revision !== state.revision) return reject(state, 'stale-revision');
  const system = cmd.player === 'system';
  if (system) {
    if (cmd.type !== 'endRound' || state.phase !== 'round') return reject(state, 'illegal');
  } else if (cmd.type !== 'concede') {
    if (!SEATS.includes(cmd.player)) return reject(state, 'bad-player');
    if (!legalActions(state, cmd.player).some(a => key(a) === key(cmd))) return reject(state, 'illegal');
  }
  const s = structuredClone(state);
  const ctx = { s, events: [] };
  if (cmd.nonce !== undefined) s.nonces.push(cmd.nonce);
  const p = cmd.player;
  switch (cmd.type) {
    case 'concede': endMatch(ctx, other(p), 'concede'); break;
    case 'endRound': endRound(ctx); break;
    case 'placeGate': placeGate(ctx, p, cmd.gate); break;
    case 'choose': choose(ctx, p, cmd.unit); break;
    case 'activate': activate(ctx, p, cmd.cards.slice()); break;
    case 'openGate': orderGate(ctx, p); break;
    case 'ready':
      s.players[p].ready = true;
      emit(ctx, { t: 'ready', player: p });
      if (SEATS.every(x => s.players[x].ready)) endRound(ctx);
      break;
    default: return reject(state, 'illegal');
  }
  s.revision++;
  return { ok: true, state: s, events: ctx.events };
}

// ---------------------------------------------------------------- visibility

export function eventFor(e, viewer) {
  if (!e.secret) return e;
  const { secret, ...pub } = e;
  if (secret.to !== viewer) return pub;
  const { to, ...data } = secret;
  return { ...pub, ...data };
}

// A client sees its own hand, its own queued actions and its own closed gate. Of the opponent's round it sees only
// how many actions were taken (with Мудрец глубин on the gate, also of what kind): the cards, their cost and the
// opening of the gate are revealed at the end of the round.
export function viewDuel(s, viewer) {
  const inRound = s.phase === 'round';
  const players = {};
  for (const p of SEATS) {
    const pl = s.players[p];
    const mine = p === viewer;
    players[p] = {
      name: pl.name, life: pl.life, mana: mine || !inRound ? pl.mana : null, manaMax: pl.manaMax,
      handCount: pl.hand.length, deckCount: pl.deck.length, discardCount: pl.discard.length,
      exiled: pl.exiled.map(c => s.cards[c].def), units: pl.units.slice(),
      gates: pl.gates.map(g => ({ gate: g, used: s.gates[g].used, def: mine ? s.gates[g].def : null })),
      fighter: pl.fighter, activations: mine || !inRound ? pl.activations : null,
      activationsMax: pl.fighter ? activationsFor(s, p) : RULES.activationsPerRound, ready: pl.ready,
      nextMana: mine ? pl.nextMana : null, chose: !!pl.choice,
    };
    if (mine) players[p].hand = pl.hand.map(c => ({ card: c, def: s.cards[c].def }));
  }
  let bout = null;
  if (s.bout) {
    const owner = gateOwner(s);
    const known = s.bout.gate && (s.bout.gateOpen || owner === viewer);
    const sees = viewer && passiveOf(s, s.players[viewer]?.fighter).seesKinds;
    bout = {
      n: s.bout.n, gate: s.bout.gate, gateOpen: s.bout.gateOpen, owner, placer: s.bout.placer, rounds: s.bout.rounds,
      gateDef: known ? s.gates[s.bout.gate].def : null,
      roundRule: s.bout.roundRule,
      queue: s.bout.queue.map(a => {
        if (a.player === viewer) return structuredClone(a);
        const hidden = { id: a.id, player: a.player, hidden: true };
        if (sees) hidden.kinds = a.kind === 'gate' ? ['gate'] : [...new Set(a.defs.map(d => CARDS[d].kind))];
        return hidden;
      }),
    };
  }
  return {
    rulesVersion: s.rulesVersion, contentHash: s.contentHash, viewer, revision: s.revision, phase: s.phase,
    round: s.round, boutNo: s.boutNo, timerMs: s.timerMs, gateTurn: s.gateTurn, bout,
    preview: previewRound(s, viewer),
    players, units: structuredClone(s.units), result: s.result,
    log: s.log.map(e => eventFor(e, viewer)),
  };
}

// ---------------------------------------------------------------- replay

export function newDuelRecord(setup) {
  const { state } = createDuel(setup);
  return { record: { rulesVersion: DUEL_RULES_VERSION, contentHash: DUEL_CONTENT_HASH, setup, commands: [] }, state };
}

export function applyDuelRecorded(record, state, cmd) {
  const r = apply(state, cmd);
  if (r.ok) record.commands.push(cmd);
  return r;
}

export function replayDuel(record) {
  if (record.contentHash !== DUEL_CONTENT_HASH) throw new DuelError('content-mismatch');
  let { state } = createDuel(record.setup);
  for (const cmd of record.commands) {
    const r = apply(state, cmd);
    if (!r.ok) throw new DuelError('replay-diverged', r.error);
    state = r.state;
  }
  return state;
}
