// Hybrid rules v0.2: G (power, attack and health), the 500 life gauge, rounds, cards hidden until the end of the round
// and taking effect there, fusion, blind counters, closed gates (bonuses, fields, traps) opened at the owner's will,
// gates in turn, both fighters back to the reserve after a knockout.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as D from '../src/duel/index.js';
import { seedRng } from '../src/core/rng.js';

const deck = key => structuredClone(D.DUEL_DECKS[key]);
const sys = { player: 'system', type: 'endRound' };

function act(s, p, a) {
  const r = D.apply(s, { ...a, player: p });
  assert.ok(r.ok, `${p} ${JSON.stringify(a)}: ${r.error}`);
  return r.state;
}

// A duel past gate placement and fighter choice: A fields `a`, B fields `b` (colossus defs from their decks).
function duel({ a = 'RS-C001', b = 'RS-C009', da = 'attack', db = 'attack', gate = null, seed = 5 } = {}) {
  let { state: s } = D.createDuel({ seed, assignSeats: false, players: [{ name: 'A', deck: deck(da) }, { name: 'B', deck: deck(db) }] });
  const placer = s.bout.placer;
  s = act(s, placer, D.legalActions(s, placer)[0]);
  if (gate) s.gates[s.bout.gate].def = gate;
  for (const [p, def] of [['A', a], ['B', b]]) s = act(s, p, { type: 'choose', unit: s.players[p].units.find(u => s.units[u].def === def) });
  return s;
}

// Put the fighters to exact numbers (as if earlier rounds had happened) without touching anything else.
function setFighters(s, { ga, gb }) {
  const a = s.units[s.players.A.fighter], b = s.units[s.players.B.fighter];
  if (ga !== undefined) a.g = ga;
  if (gb !== undefined) b.g = gb;
  a.shield = 0; b.shield = 0;
}

function give(s, p, def) {
  const pl = s.players[p];
  const inHand = pl.hand.find(c => s.cards[c].def === def && !(s.given ??= new Set()).has(c));
  if (inHand) { s.given.add(inHand); return inHand; }
  const cid = pl.deck.find(c => s.cards[c].def === def) ?? pl.discard.find(c => s.cards[c].def === def);
  assert.ok(cid, `${p}: нет ${def}`);
  pl.deck = pl.deck.filter(c => c !== cid);
  pl.discard = pl.discard.filter(c => c !== cid);
  pl.hand.push(cid);
  (s.given ??= new Set()).add(cid);
  return cid;
}

const fighter = (s, p) => s.units[s.players[p].fighter];

test('у колоссов нет ХП: сила G — это и атака, и здоровье', () => {
  const s = duel();
  for (const u of Object.values(s.units)) assert.equal(u.hp, undefined);
  for (const c of Object.values(D.COLOSSI)) assert.equal(c.hp, undefined);
});

test('атака: 450 против 380 — слабый теряет разницу (380 → 310), сильный цел, жизнь не тронута', () => {
  let s = duel({ gate: 'RS-G008' });
  setFighters(s, { ga: 450, gb: 380 });
  s = act(s, 'system', sys);
  assert.equal(fighter(s, 'A').g, 450);
  assert.equal(fighter(s, 'B').g, 310);
  assert.equal(s.players.A.life, 500);
  assert.equal(s.players.B.life, 500);
  assert.equal(s.phase, 'round', 'оба живы — следующий раунд');
});

test('бой идёт раундами, пока G слабого не уйдёт в минус; минус бьёт по шкале жизни, колосс вылетает', () => {
  let s = duel({ gate: 'RS-G008' });
  setFighters(s, { ga: 450, gb: 380 });
  const loser = s.players.B.fighter;
  s = act(s, 'system', sys); // 380 → 310
  s = act(s, 'system', sys); // 310 → 170
  assert.equal(s.units[loser].g, 170);
  s = act(s, 'system', sys); // 170 − 280 = −110
  assert.equal(s.players.B.life, 390);
  assert.equal(s.units[loser].zone, 'reserve');
  assert.equal(s.units[loser].g, D.COLOSSI[s.units[loser].def].g, 'в резерве сила восстановлена');
  assert.equal(s.phase, 'gate', 'новый бой: следующие ворота');
});

test('эффект карты срабатывает не при розыгрыше, а в конце раунда, до атаки', () => {
  let s = duel({ gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 400 });
  s.players.A.mana = 10;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N08')] }); // враг теряет 250 G
  assert.equal(fighter(s, 'B').g, 400, 'сразу после розыгрыша ничего не изменилось');
  assert.equal(D.viewDuel(s, 'A').preview.B.g, 150, 'сыгравший видит прогноз на конец раунда');
  assert.equal(D.viewDuel(s, 'B').preview.B.g, 400, 'соперник карту не видит, и прогноз её не выдаёт');
  s = act(s, 'system', sys);
  // конец раунда: −250 от карты (400 → 150), затем атака 400 против 150: слабый теряет ещё 250 → −100, вылет
  assert.equal(s.players.B.life, 400);
  assert.equal(s.phase, 'gate');
});

test('раунд за раундом растут мана и таймер; сила от карт держится до конца боя', () => {
  let s = duel({ gate: 'RS-G008' });
  const [m1, t1] = [s.players.A.mana, s.timerMs];
  const g0 = fighter(s, 'A').g;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N02')] }); // +150 G в конце раунда
  setFighters(s, { gb: g0 + 100 });
  s = act(s, 'system', sys);
  assert.equal(s.players.A.mana, m1 + 1);
  assert.equal(s.timerMs, t1 + 5000);
  assert.equal(fighter(s, 'A').g, g0 + 150, 'бонус карты остался, сильный не теряет G');
  assert.equal(fighter(s, 'B').g, g0 + 50);
});

test('карта маны даёт ману на следующий раунд', () => {
  let s = duel({ a: 'RS-C003', b: 'RS-C009', da: 'answers', gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 400 });
  const m = s.players.A.mana;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N07')] });
  assert.equal(s.players.A.mana, m, 'прилив маны не в этом раунде');
  s = act(s, 'system', sys);
  assert.equal(s.players.A.mana, D.RULES.mana(s.round) + 2);
});

test('щит поглощает урон раньше G; урон карты ниже нуля выбивает колосса в конце раунда, атаки нет', () => {
  let s = duel({ gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 100 });
  fighter(s, 'B').shield = 60;
  s.players.A.mana = 10;
  const loser = s.players.B.fighter;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N08')] }); // враг теряет 250 G
  s = act(s, 'system', sys);
  assert.equal(s.players.B.life, 410); // 250 − 60 щита − 100 G = 90 в минус
  assert.equal(s.units[loser].zone, 'reserve');
  assert.ok(!s.log.some(e => e.t === 'attack'), 'колосс выбит картой — атаки в этом раунде нет');
});

test('восстановление G не поднимает силу выше стартовой в этом бою', () => {
  let s = duel({ a: 'RS-C005', b: 'RS-C009', da: 'control', gate: 'RS-G008' });
  const start = fighter(s, 'A').startG;
  setFighters(s, { ga: start - 50, gb: start });
  s.players.A.mana = 10;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N04')] });
  s = act(s, 'system', sys);
  assert.equal(fighter(s, 'A').g, start);
});

test('после вылета оба колосса возвращаются в резерв и оба игрока выбирают бойца заново', () => {
  let s = duel({ gate: 'RS-G008' });
  setFighters(s, { ga: 420, gb: 100 });
  const [winner, loser] = [s.players.A.fighter, s.players.B.fighter];
  const firstGateOwner = s.bout.placer;
  s = act(s, 'system', sys);
  assert.equal(s.units[winner].zone, 'reserve');
  assert.equal(s.units[winner].g, D.COLOSSI[s.units[winner].def].g, 'сила победителя восстановлена');
  assert.equal(s.units[loser].zone, 'reserve');
  assert.equal(s.players.A.fighter, null);
  assert.notEqual(s.bout.placer, firstGateOwner, 'ворота выкладывают по очереди');
  s = act(s, s.bout.placer, D.legalActions(s, s.bout.placer)[0]);
  const choices = D.legalActions(s, 'A').map(a => a.unit);
  assert.equal(choices.length, 3, 'победитель тоже в выборе');
  const other = choices.find(u => u !== winner);
  s = act(s, 'A', { type: 'choose', unit: other });
  s = act(s, 'B', D.legalActions(s, 'B')[0]);
  assert.equal(s.players.A.fighter, other, 'можно выставить другого');
});

test('вылет с минусом больше 500 удаляет колосса из игры', () => {
  let s = duel({ gate: 'RS-G008' });
  setFighters(s, { ga: 900, gb: 300 });
  s.players.B.life = 5000; // чтобы матч не кончился по шкале
  const loser = s.players.B.fighter;
  s = act(s, 'system', sys); // 300 − 600 = −300: ещё не удаление
  assert.equal(s.units[loser].zone, 'reserve');
  let t = duel({ gate: 'RS-G008' });
  setFighters(t, { ga: 1000, gb: 0 });
  t.players.B.life = 5000;
  const loser2 = t.players.B.fighter;
  t = act(t, 'system', sys); // 0 − 1000 = −1000
  assert.equal(t.units[loser2].zone, 'removed');
  t = act(t, t.bout.placer, D.legalActions(t, t.bout.placer)[0]);
  assert.ok(!D.legalActions(t, 'B').some(a => a.unit === loser2));
});

test('монетка решает, кто выкладывает первые ворота, дальше по очереди', () => {
  const firsts = new Set();
  for (let seed = 1; seed <= 20; seed++) {
    const { state } = D.createDuel({ seed, assignSeats: false, players: [{ deck: deck('attack') }, { deck: deck('control') }] });
    firsts.add(state.bout.placer);
    assert.equal(state.log[0].t, 'coin');
    assert.equal(state.log[0].first, state.bout.placer);
  }
  assert.deepEqual([...firsts].sort(), ['A', 'B']);
});

test('в руку приходят только карты текущего бойца: у Виверна нет карт Паладина и Света', () => {
  const s = duel({ a: 'RS-C001', b: 'RS-C009' });
  for (const h of s.players.A.hand) {
    const c = D.CARDS[s.cards[h].def];
    assert.ok(D.playableBy(c.id, 'RS-C001'), `${c.name} не для Виверна`);
    assert.ok(c.aspect !== 'light' && c.unique !== 'RS-C009');
  }
  for (const h of s.players.B.hand) assert.ok(D.playableBy(s.cards[h].def, 'RS-C009'));
});

test('новый бой перемешивает руки обратно в колоду; одноразовые карты уходят из игры', () => {
  let s = duel({ gate: 'RS-G008' });
  s.players.A.mana = 10;
  const once = give(s, 'A', 'D-N06');
  s = act(s, 'A', { type: 'activate', cards: [once] });
  assert.ok(s.players.A.exiled.includes(once));
  setFighters(s, { ga: 400, gb: 0 });
  s.players.B.life = 5000;
  s = act(s, 'system', sys);
  s = act(s, s.bout.placer, D.legalActions(s, s.bout.placer)[0]);
  s = act(s, 'A', D.legalActions(s, 'A')[0]);
  s = act(s, 'B', D.legalActions(s, 'B')[0]);
  const pl = s.players.A;
  assert.equal(pl.discard.length, 0);
  assert.ok(!pl.deck.includes(once) && !pl.hand.includes(once));
  assert.equal(pl.deck.length + pl.hand.length + pl.exiled.length, 24);
});

test('слияние: несколько карт одной активацией, мана — сумма; не больше 2 активаций и 3 карт в слиянии', () => {
  let s = duel({ gate: 'RS-G008' });
  s.players.A.mana = 10;
  const cards = ['D-N01', 'D-N02', 'D-F01', 'D-F04'].map(d => give(s, 'A', d));
  assert.ok(!D.legalActions(s, 'A').some(a => a.type === 'activate' && a.cards.length > 3));
  const g0 = fighter(s, 'A').g;
  s = act(s, 'A', { type: 'activate', cards: [cards[1], cards[2], cards[3]] });
  assert.equal(s.players.A.mana, 10 - 2 - 1 - 2);
  assert.equal(D.eventFor(s.log.filter(e => e.t === 'activate').at(-1), 'A').fusion, true);
  s = act(s, 'A', { type: 'activate', cards: [cards[0]] });
  assert.ok(!D.legalActions(s, 'A').some(a => a.type === 'activate'), 'третьей активации в раунде нет');
  setFighters(s, { gb: g0 + 400 - 80 });
  s = act(s, 'system', sys);
  assert.equal(fighter(s, 'A').g, g0 + 400, 'слияние +150 +100 +150 сработало в конце раунда');
});

test('отмена целится в уже сыгранную активацию соперника; отмена отмены возвращает её', () => {
  let s = duel({ gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 400 });
  s.players.A.mana = 10;
  s.players.B.mana = 10;
  const counterA = give(s, 'A', 'D-N05');
  assert.ok(!D.legalActions(s, 'A').some(a => a.cards?.includes(counterA)), 'отменять пока нечего');
  s = act(s, 'B', { type: 'activate', cards: [give(s, 'B', 'D-N02')] }); // B: +150
  const target = s.bout.queue[0].id;
  s = act(s, 'A', { type: 'activate', cards: [counterA], target });
  let t = s;
  s = act(s, 'system', sys);
  assert.equal(fighter(s, 'B').g, 400, 'усиление B отменено');
  assert.ok(s.log.some(e => e.t === 'countered' && e.id === target));
  t = act(t, 'B', { type: 'activate', cards: [give(t, 'B', 'D-N05')], target: t.bout.queue[1].id });
  t = act(t, 'system', sys);
  assert.equal(fighter(t, 'A').g, 250, 'отмена отменена: +150 у B сработало, A проиграл разницу');
  assert.equal(fighter(t, 'B').g, 550);
});

test('оба «Готов» заканчивают раунд досрочно; таймер — системная команда', () => {
  let s = duel({ gate: 'RS-G008' });
  const r0 = s.round;
  s = act(s, 'A', { type: 'ready' });
  assert.equal(s.round, r0);
  assert.deepEqual(D.legalActions(s, 'A'), []);
  s = act(s, 'B', { type: 'ready' });
  assert.ok(s.round > r0 || s.phase !== 'round');
  assert.equal(D.apply(s, { player: 'A', type: 'endRound' }).ok, false, 'игрок не может закончить раунд за таймер');
});

test('шкала жизни на нуле — поражение', () => {
  let s = duel({ gate: 'RS-G008' });
  setFighters(s, { ga: 300, gb: 0 });
  s.players.B.life = 100;
  s = act(s, 'system', sys);
  assert.deepEqual(s.result, { winner: 'A', reason: 'life' });
});

test('скрытое: рука соперника, его выбор бойца и порядок колод не видны', () => {
  let { state: s } = D.createDuel({ seed: 3, assignSeats: false, players: [{ deck: deck('attack') }, { deck: deck('answers') }] });
  s = act(s, s.bout.placer, D.legalActions(s, s.bout.placer)[0]);
  s = act(s, 'B', D.legalActions(s, 'B')[0]);
  const v = D.viewDuel(s, 'A');
  const json = JSON.stringify(v);
  assert.equal(v.players.B.hand, undefined);
  assert.equal(v.players.B.chose, true);
  assert.equal(v.players.B.choice, undefined, 'какого колосса выбрал соперник, не видно');
  assert.equal(v.units[s.players.B.choice].zone, 'reserve', 'выбранный колосс не выходит на поле до раскрытия');
  for (const c of s.players.B.deck) assert.ok(!json.includes(`"${c}"`));
  assert.equal(v.rng, undefined);
});

test('карты соперника скрыты до конца раунда: видно только, что он что-то сыграл; в конце раунда всё вскрывается', () => {
  let s = duel({ gate: 'RS-G008' });
  s.players.A.mana = 10;
  const cid = give(s, 'A', 'D-N08');
  s = act(s, 'A', { type: 'activate', cards: [cid] });
  const id = s.bout.queue[0].id;
  const v = D.viewDuel(s, 'B');
  assert.deepEqual(v.bout.queue, [{ id, player: 'A', hidden: true }]);
  assert.equal(v.players.A.mana, null, 'сколько маны осталось у соперника — тоже тайна');
  assert.equal(v.players.A.activations, null);
  const ev = v.log.at(-1);
  assert.equal(ev.t, 'activate');
  assert.equal(ev.defs, undefined);
  assert.equal(ev.cost, undefined);
  assert.ok(!JSON.stringify(v).includes(`"${cid}"`), 'карта соперника никуда не утекла');
  assert.deepEqual(D.viewDuel(s, 'A').bout.queue[0].defs, ['D-N08'], 'свои действия видны');
  s = act(s, 'system', sys);
  const rev = D.viewDuel(s, 'B').log.find(e => e.t === 'reveal');
  assert.deepEqual(rev.actions.map(a => [a.player, a.defs]), [['A', ['D-N08']]]);
});

// The bout's gate: who laid it and who plays against it.
const sides = s => {
  const owner = D.gateOwner(s), foe = D.other(owner);
  return { owner, foe, uo: s.players[owner].fighter, uf: s.players[foe].fighter };
};
// Fighters at exact G as they will be right after the gate's aspect bonus.
function afterBonus(s, go, gf) {
  const { uo, uf } = sides(s);
  s.units[uo].g = go - D.gateBonus(s, uo);
  s.units[uf].g = gf - D.gateBonus(s, uf);
  s.units[uo].shield = s.units[uf].shield = 0;
}

test('ворота лежат закрытыми: бонуса нет, соперник не знает, что это за карта, открыть может только владелец', () => {
  const s = duel({ gate: 'RS-G002' });
  const { owner, foe } = sides(s);
  assert.equal(s.bout.gateOpen, false);
  for (const p of D.SEATS) assert.equal(fighter(s, p).g, D.COLOSSI[fighter(s, p).def].g, 'без бонуса аспекта');
  assert.equal(D.viewDuel(s, owner).bout.gateDef, 'RS-G002', 'владелец свои ворота знает');
  const v = D.viewDuel(s, foe);
  assert.equal(v.bout.gateDef, null);
  assert.ok(!JSON.stringify(v.log).includes('gateDef'), 'и в журнале ворот не видно');
  assert.ok(D.legalActions(s, owner).some(a => a.type === 'openGate'));
  assert.ok(!D.legalActions(s, foe).some(a => a.type === 'openGate'));
});

test('открыть ворота — скрытое действие без траты активации; они открываются в конце раунда, бонус аспекта обоим', () => {
  let s = duel({ gate: 'RS-G005' }); // бонус: щит 200 бойцу владельца
  const { owner, foe, uo, uf } = sides(s);
  const bonus = { [uo]: D.gateBonus(s, uo), [uf]: D.gateBonus(s, uf) };
  s = act(s, owner, { type: 'openGate' });
  assert.equal(s.players[owner].activations, 0, 'активация не потрачена');
  assert.equal(s.bout.gateOpen, false, 'пока идёт раунд, ворота закрыты');
  assert.ok(!D.legalActions(s, owner).some(a => a.type === 'openGate'), 'дважды не открыть');
  const v = D.viewDuel(s, foe);
  assert.deepEqual(v.bout.queue, [{ id: s.bout.queue[0].id, player: owner, hidden: true }], 'сопернику видно только «что-то сделал»');
  assert.equal(v.log.at(-1).kind, undefined);
  s = act(s, 'system', sys);
  assert.equal(s.bout.gateOpen, true);
  assert.ok(s.log.some(e => e.t === 'gateRevealed' && e.gateDef === 'RS-G005' && e.owner === owner));
  for (const u of [uo, uf]) assert.equal(s.units[u].startG, D.COLOSSI[s.units[u].def].g + bonus[u], 'бонус держится до конца боя');
  assert.ok(s.log.some(e => e.t === 'shield' && e.unit === uo && e.amount === 200));
  assert.equal(D.viewDuel(s, foe).bout.gateDef, 'RS-G005', 'открытые ворота видят оба');
  assert.ok(!D.legalActions(s, owner).some(a => a.type === 'openGate'));
});

test('ловушка «удар»: при открытии боец соперника теряет 150 G', () => {
  let s = duel({ gate: 'RS-G002' });
  const { owner, uf } = sides(s);
  afterBonus(s, 400, 400);
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  const hit = s.log.find(e => e.t === 'damage' && e.why === 'RS-G002');
  assert.equal(hit.unit, uf);
  assert.equal(hit.g, 250);
});

test('ловушка «слабый побеждает»: в раунде открытия разницу теряет сильный, дальше как обычно', () => {
  let s = duel({ gate: 'RS-G010' });
  const { owner, uo, uf } = sides(s);
  afterBonus(s, 300, 500);
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'attack' && e.inverted));
  assert.equal(s.units[uo].g, 300);
  assert.equal(s.units[uf].g, 300, 'сильный потерял разницу');
  s.units[uo].g = 200;
  s = act(s, 'system', sys);
  assert.equal(s.units[uo].g, 100, 'следующий раунд — снова теряет слабый');
});

test('ловушка «обмен»: силы бойцов меняются местами', () => {
  let s = duel({ gate: 'RS-G011' });
  const { owner, uo, uf } = sides(s);
  afterBonus(s, 300, 450);
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'swap'));
  assert.equal(s.units[uo].g, 450);
  assert.equal(s.units[uf].g, 150, 'после обмена 450 против 300: слабый теряет 150');
});

test('ловушка «отражение»: в раунде открытия урон карт соперника бьёт по его собственному бойцу', () => {
  let s = duel({ gate: 'RS-G004' });
  const { owner, foe, uo, uf } = sides(s);
  afterBonus(s, 400, 400);
  s.players[foe].mana = 10;
  s = act(s, foe, { type: 'activate', cards: [give(s, foe, 'D-N08')] }); // враг теряет 250 G
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'reflected' && e.player === foe));
  const hit = s.log.find(e => e.t === 'damage' && e.why === 'D-N08');
  assert.equal(hit.unit, uf, 'карта ударила по своему');
  assert.ok(!s.log.some(e => e.t === 'damage' && e.unit === uo && e.why === 'D-N08'));
});

test('ловушка «иссушение»: у соперника на 2 маны меньше в следующем раунде', () => {
  let s = duel({ gate: 'RS-G008' });
  const { owner, foe } = sides(s);
  afterBonus(s, 400, 400);
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  assert.equal(s.players[foe].mana, D.RULES.mana(s.round) - 2);
  assert.equal(s.players[owner].mana, D.RULES.mana(s.round));
});

test('ловушка «кара сильного» бьёт только если боец соперника сильнее', () => {
  for (const [go, gf, hits] of [[300, 400, true], [400, 300, false]]) {
    let s = duel({ gate: 'RS-G012' });
    const { owner } = sides(s);
    afterBonus(s, go, gf);
    s = act(s, owner, { type: 'openGate' });
    s = act(s, 'system', sys);
    assert.equal(s.log.some(e => e.t === 'damage' && e.why === 'RS-G012'), hits);
  }
});

test('поле «круг»: пока ворота открыты, восстановление силы не действует', () => {
  let s = duel({ a: 'RS-C005', b: 'RS-C009', da: 'control', gate: 'RS-G006' });
  const { owner } = sides(s);
  afterBonus(s, 500, 500);
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  const a = fighter(s, 'A');
  a.g = a.startG - 100;
  fighter(s, 'B').g = a.g;
  s.players.A.mana = 10;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N04')] });
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'healBlocked'));
  assert.equal(fighter(s, 'A').g, a.startG - 100);
});

test('отмена вслепую может попасть в открытие ворот — тогда ворота остаются закрытыми', () => {
  let s = duel({ gate: 'RS-G002' });
  const { owner, foe } = sides(s);
  s.players[foe].mana = 10;
  s = act(s, owner, { type: 'openGate' });
  const target = s.bout.queue[0].id;
  assert.ok(D.legalActions(s, foe).some(a => a.target === target), 'цель — любое скрытое действие');
  s = act(s, foe, { type: 'activate', cards: [give(s, foe, 'D-N05')], target });
  s = act(s, 'system', sys);
  assert.equal(s.bout.gateOpen, false);
  assert.ok(s.log.some(e => e.t === 'countered' && e.kind === 'gate'));
  assert.ok(!s.log.some(e => e.why === 'RS-G002'));
  assert.ok(D.legalActions(s, owner).some(a => a.type === 'openGate'), 'можно попробовать ещё раз');
});

test('неоткрытые ворота сгорают с концом боя и только тогда показываются', () => {
  let s = duel({ gate: 'RS-G002' });
  const gid = s.bout.gate;
  setFighters(s, { ga: 400, gb: 0 });
  s.players.B.life = 5000;
  s = act(s, 'system', sys);
  const end = s.log.find(e => e.t === 'boutEnd');
  assert.equal(end.gateOpened, false);
  assert.equal(end.gateDef, 'RS-G002');
  assert.equal(s.gates[gid].used, true);
});

function playOut(seed, bots) {
  const rng = seedRng(`duel:${seed}`);
  const decks = ['attack', 'control', 'answers'];
  let { record, state } = D.newDuelRecord({ seed, players: [{ deck: deck(decks[seed % 3]) }, { deck: deck(decks[(seed + 1) % 3]) }] });
  let steps = 0;
  while (!state.result) {
    assert.ok(++steps < 4000, `партия ${seed} не закончилась`);
    const p = D.SEATS.find(x => D.legalActions(state, x).length);
    let cmd;
    if (state.phase === 'round' && (!p || steps % 7 === 0)) cmd = sys;
    else cmd = { ...bots[p](state, p, rng), player: p };
    const r = D.applyDuelRecorded(record, state, cmd);
    assert.ok(r.ok, `${seed}: ${JSON.stringify(cmd)} ${r.error}`);
    state = r.state;
    for (const q of D.SEATS) {
      const pl = state.players[q];
      assert.equal(pl.deck.length + pl.hand.length + pl.discard.length + pl.exiled.length, 24);
      assert.ok(pl.mana >= 0);
      assert.ok(pl.hand.length <= 8);
      if (state.phase === 'round') assert.equal(state.units[pl.fighter].zone, 'field');
    }
  }
  return { record, state };
}

test('случайные боты: 300 партий заканчиваются, инварианты держатся', () => {
  const reasons = {};
  for (let seed = 1; seed <= 300; seed++) {
    const { state } = playOut(seed, { A: D.randomDuelBot, B: D.randomDuelBot });
    reasons[state.result.reason] = (reasons[state.result.reason] ?? 0) + 1;
  }
  assert.ok(reasons.life > 0);
});

test('запись партии воспроизводится в то же состояние', () => {
  const { record, state } = playOut(42, { A: D.simpleDuelBot, B: D.randomDuelBot });
  const again = D.replayDuel(JSON.parse(JSON.stringify(record)));
  assert.deepEqual(again.result, state.result);
  assert.equal(JSON.stringify(again), JSON.stringify(state));
});

test('простой бот обыгрывает случайного', () => {
  let wins = 0, losses = 0;
  for (let seed = 1; seed <= 40; seed++) {
    const simpleA = seed % 2 === 0;
    const { state } = playOut(seed, simpleA ? { A: D.simpleDuelBot, B: D.randomDuelBot } : { A: D.randomDuelBot, B: D.simpleDuelBot });
    const w = state.result.winner;
    if (w === (simpleA ? 'A' : 'B')) wins++;
    else if (w) losses++;
  }
  assert.ok(wins > losses * 2, `простой ${wins} : случайный ${losses}`);
});
