// Hybrid rules v0.3: G (power, attack and health), the 500 life gauge, rounds, cards hidden until the end of the round
// and taking effect there, fusion, counters as conditions, closed gates (bonuses, fields, traps) opened at the owner's
// will, the clash with recoil, the aspect cycle, colossus abilities, gates in turn, both fighters back to the reserve
// after a knockout, tired fighters.
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

// Two Паладины рассвета: one aspect and no abilities in the attack, so the numbers of the clash are plain.
const PLAIN = { a: 'RS-C009', b: 'RS-C009' };

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

test('атака: 450 против 380 — слабый теряет разницу (380 → 310), сильный — отдачу 60% (450 → 408), жизнь не тронута', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  setFighters(s, { ga: 450, gb: 380 });
  s = act(s, 'system', sys);
  assert.equal(fighter(s, 'B').g, 310);
  assert.equal(fighter(s, 'A').g, 408);
  assert.equal(s.players.A.life, 500);
  assert.equal(s.players.B.life, 500);
  assert.equal(s.phase, 'round', 'оба живы — следующий раунд');
  assert.equal(s.players.B.mana, D.RULES.mana(2) + 1, 'проигравший атаку получает +1 ману');
  assert.equal(s.players.A.mana, D.RULES.mana(2));
});

test('равные силы изнашивают обоих на 40; разница меньше 40 всё равно стоит слабому 40', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 400 });
  s = act(s, 'system', sys);
  assert.equal(fighter(s, 'A').g, 360);
  assert.equal(fighter(s, 'B').g, 360);
  assert.equal(s.players.A.mana, s.players.B.mana, 'при равенстве маны за проигрыш нет ни у кого');
  setFighters(s, { ga: 400, gb: 390 });
  s = act(s, 'system', sys);
  assert.equal(fighter(s, 'B').g, 350, 'разница 10, потеря 40');
  assert.equal(fighter(s, 'A').g, 394, 'отдача — 60% настоящей разницы');
});

test('бой идёт раундами, пока G слабого не уйдёт в минус; минус и ещё 60 бьют по шкале жизни, колосс вылетает', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  setFighters(s, { ga: 500, gb: 300 });
  const loser = s.players.B.fighter;
  s = act(s, 'system', sys); // B 300 → 100, A 500 − 120 = 380
  assert.equal(s.units[loser].g, 100);
  assert.equal(s.phase, 'round');
  s = act(s, 'system', sys); // B 100 − 280 = −180
  assert.equal(s.players.B.life, 500 - 180 - 60);
  assert.equal(s.units[loser].zone, 'reserve');
  assert.equal(s.units[loser].g, 200, 'выбитый возвращается в резерв с половиной силы');
  assert.equal(s.phase, 'gate', 'новый бой: следующие ворота');
});

test('эффект карты срабатывает не при розыгрыше, а в конце раунда, до атаки', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 400 });
  s.players.A.mana = 10;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N08')] }); // враг теряет 280 G
  assert.equal(fighter(s, 'B').g, 400, 'сразу после розыгрыша ничего не изменилось');
  assert.equal(D.viewDuel(s, 'A').preview.B.g, 120, 'сыгравший видит прогноз на конец раунда');
  assert.equal(D.viewDuel(s, 'B').preview.B.g, 400, 'соперник карту не видит, и прогноз её не выдаёт');
  s = act(s, 'system', sys);
  // конец раунда: −280 от карты (400 → 120), затем атака 400 против 120: слабый теряет ещё 280 → −160, вылет
  assert.equal(s.players.B.life, 500 - 160 - 60);
  assert.equal(s.phase, 'gate');
});

test('раунд за раундом растут мана и таймер; сила от карт держится до конца боя', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  const [m1, t1] = [s.players.A.mana, s.timerMs];
  const g0 = fighter(s, 'A').g;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N02')] }); // +150 G в конце раунда
  setFighters(s, { gb: g0 + 100 });
  s = act(s, 'system', sys);
  assert.equal(s.players.A.mana, m1 + 1);
  assert.equal(s.timerMs, t1 + 5000);
  // g0 + 150 против g0 + 100: B теряет 50, A — отдачу 30
  assert.equal(fighter(s, 'A').g, g0 + 150 - 30, 'бонус карты остался');
  assert.equal(fighter(s, 'B').g, g0 + 50);
  assert.equal(D.RULES.mana(8), 10, 'мана растёт до 10');
  assert.equal(D.RULES.timerMs(20), 45000, 'таймер — до 45 секунд');
});

test('карта маны даёт ману на следующий раунд', () => {
  let s = duel({ a: 'RS-C004', b: 'RS-C009', da: 'answers', gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 400 });
  const m = s.players.A.mana;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-U04')] }); // Архив раковины: 2 карты и +1 мана
  assert.equal(s.players.A.mana, m - 2, 'прибавка маны не в этом раунде');
  s = act(s, 'system', sys); // 400 против 400: маны за проигрыш атаки нет
  assert.equal(s.players.A.mana, D.RULES.mana(s.bout.rounds) + 1);
});

test('щит поглощает урон раньше G; урон карты ниже нуля выбивает колосса в конце раунда, атаки нет', () => {
  let s = duel({ gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 100 });
  fighter(s, 'B').shield = 60;
  s.players.A.mana = 10;
  const loser = s.players.B.fighter;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N08')] }); // враг теряет 280 G
  s = act(s, 'system', sys);
  assert.equal(s.players.B.life, 500 - 120 - 60); // 280 − 60 щита − 100 G = 120 в минус
  assert.equal(s.units[loser].zone, 'reserve');
  assert.ok(!s.log.some(e => e.t === 'attack'), 'колосс выбит картой — атаки в этом раунде нет');
});

test('восстановление G не поднимает силу выше полной в этом бою', () => {
  let s = duel({ a: 'RS-C005', b: 'RS-C009', da: 'control', gate: 'RS-G008' });
  const uid = s.players.A.fighter, start = s.units[uid].startG;
  setFighters(s, { ga: start - 50, gb: start });
  s.players.A.mana = 10;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N04')] }); // восстановить 180 G
  s = act(s, 'system', sys);
  const heal = s.log.find(e => e.t === 'heal' && e.unit === uid);
  assert.equal(heal.amount, 50);
  assert.equal(heal.g, start);
});

test('после вылета оба колосса возвращаются в резерв и оба игрока выбирают бойца заново', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  setFighters(s, { ga: 420, gb: 100 });
  const [winner, loser] = [s.players.A.fighter, s.players.B.fighter];
  const firstGateOwner = s.bout.placer;
  s = act(s, 'system', sys); // B: 100 − 320 = −220; A: отдача 192
  assert.equal(s.units[winner].zone, 'reserve');
  assert.equal(s.units[winner].g, 420 - 192, 'победитель устал: остаток G, но не меньше половины');
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

test('усталость: кто дрался, остаётся с остатком G (не меньше половины), пока не пропустит бой; Птица маяка не устаёт', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  const tired = s.players.A.fighter;
  setFighters(s, { ga: 300, gb: 100 });
  s.players.B.life = 5000;
  s = act(s, 'system', sys); // B выбит; A: 300 − 120 отдачи = 180, но не меньше половины от 400
  assert.equal(s.units[tired].g, 200);
  s = act(s, s.bout.placer, D.legalActions(s, s.bout.placer)[0]);
  const next = s.players.A.units.find(u => u !== tired);
  s = act(s, 'A', { type: 'choose', unit: next });
  s = act(s, 'B', D.legalActions(s, 'B')[0]);
  assert.equal(s.units[tired].g, 200, 'в резерве усталость держится весь бой');
  setFighters(s, { ga: 400, gb: 0 });
  s = act(s, 'system', sys);
  assert.equal(s.units[tired].g, D.COLOSSI[s.units[tired].def].g, 'пропустил бой — снова полная сила');

  let t = duel({ a: 'RS-C010', da: 'sky', b: 'RS-C009', gate: 'RS-G008' });
  const bird = t.players.A.fighter;
  setFighters(t, { ga: 300, gb: 100 });
  t.players.B.life = 5000;
  t = act(t, 'system', sys); // Птица: 300 − 120 отдачи = 180
  assert.equal(t.units[bird].g, D.COLOSSI['RS-C010'].g, 'Птица маяка возвращается из боя без усталости');
});

test('вылет при разнице сил больше 500 удаляет колосса из игры', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  setFighters(s, { ga: 800, gb: 300 });
  s.players.B.life = 5000; // чтобы матч не кончился по шкале
  const loser = s.players.B.fighter;
  s = act(s, 'system', sys); // разница ровно 500: вылет, но ещё не удаление
  assert.equal(s.units[loser].zone, 'reserve');
  let t = duel({ ...PLAIN, gate: 'RS-G008' });
  setFighters(t, { ga: 900, gb: 300 });
  t.players.B.life = 5000;
  const loser2 = t.players.B.fighter;
  t = act(t, 'system', sys); // разница 600
  assert.equal(t.units[loser2].zone, 'removed');
  assert.ok(t.log.some(e => e.t === 'knockout' && e.unit === loser2 && e.removed && e.diff === 600));
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
  s = act(s, 'system', sys);
  const attack = s.log.find(e => e.t === 'attack');
  assert.equal(attack.A.g, g0 + 400, 'слияние +150 +90 +160 сработало в конце раунда, до атаки');
});

test('отмена — условие, а не цель: в конце раунда отменяет первое действие соперника, даже сыгранное позже неё', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 400 });
  s.players.A.mana = 10;
  s.players.B.mana = 10;
  const counterA = give(s, 'A', 'D-N05');
  assert.ok(D.legalActions(s, 'A').some(a => a.cards?.length === 1 && a.cards[0] === counterA), 'отмену можно сыграть заранее');
  s = act(s, 'A', { type: 'activate', cards: [counterA] });
  s = act(s, 'B', { type: 'activate', cards: [give(s, 'B', 'D-N02')] }); // B: +150
  const victim = s.bout.queue[1].id;
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'countered' && e.id === victim && e.byDef === 'D-N05'));
  assert.ok(!s.log.some(e => e.t === 'gain' && e.why === 'D-N02'), 'усиление B отменено');
  assert.equal(fighter(s, 'B').g, 360, 'силы равны: оба теряют по 40');
});

test('отмены отмен разбираются раньше остальных: Встречный знак спасает карту от Отмены', () => {
  let s = duel({ a: 'RS-C009', b: 'RS-C004', db: 'answers', gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 400 });
  s.players.A.mana = 10;
  s.players.B.mana = 10;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N05')] });
  s = act(s, 'B', { type: 'activate', cards: [give(s, 'B', 'D-N02')] }); // B: +150
  s = act(s, 'B', { type: 'activate', cards: [give(s, 'B', 'D-N12')] });
  const [counterA, , counterB] = s.bout.queue.map(a => a.id);
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'countered' && e.id === counterA && e.by === counterB));
  assert.ok(s.log.some(e => e.t === 'gain' && e.why === 'D-N02'), 'усиление B сработало');
  // 400 против 550: A теряет 150, B — отдачу 90
  assert.equal(fighter(s, 'A').g, 250);
  assert.equal(fighter(s, 'B').g, 460);
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

// ---------------------------------------------------------------- the aspect cycle and colossus abilities

test('аспект: против аспекта, который вы бьёте, в атаке +100; сама G не меняется', () => {
  let s = duel({ a: 'RS-C009', b: 'RS-C011', db: 'answers', gate: 'RS-G008' }); // Свет рассеивает Тень
  setFighters(s, { ga: 400, gb: 400 });
  const atk = D.attackValue(s, 'A');
  assert.equal(atk.g, 400);
  assert.equal(atk.value, 500);
  s = act(s, 'system', sys); // 500 против 400: B теряет 100, A — отдачу 60
  assert.equal(fighter(s, 'B').g, 300);
  assert.equal(fighter(s, 'A').g, 340);
});

test('способности в атаке: Виверн +120, Титан −20, Охотник +80 только против сильнейшего', () => {
  const s = duel({ a: 'RS-C001', b: 'RS-C011', db: 'answers' }); // Жар и Тень: преимущества аспекта нет
  setFighters(s, { ga: 400, gb: 400 });
  assert.equal(D.attackValue(s, 'A').value, 520);
  assert.equal(D.attackValue(s, 'B').value, 400, 'силы равны — бонуса из тени нет');
  fighter(s, 'A').g = 450;
  assert.equal(D.attackValue(s, 'B').value, 480);
  const t = duel({ a: 'RS-C005', b: 'RS-C005', da: 'control', db: 'control' });
  assert.equal(D.attackValue(t, 'A').value, 480 - 20);
});

test('Речной левиафан, проигрывая атаку, теряет вдвое меньше', () => {
  let s = duel({ a: 'RS-C003', b: 'RS-C009', da: 'answers', gate: 'RS-G008' });
  setFighters(s, { ga: 400, gb: 600 });
  s = act(s, 'system', sys);
  assert.equal(fighter(s, 'A').g, 300, 'разница 200, потеря 100');
  assert.equal(fighter(s, 'B').g, 480, 'отдача считается от полной разницы');
});

test('способности начала раунда: Рыцарь со второго раунда +20 G, Птица маяка восстанавливает 100 G', () => {
  let s = duel({ a: 'RS-C002', b: 'RS-C010', db: 'sky', gate: 'RS-G008' });
  setFighters(s, { ga: 300, gb: 300 });
  s = act(s, 'system', sys); // равные силы: оба 260
  assert.equal(fighter(s, 'A').g, 280);
  assert.equal(fighter(s, 'B').g, 360);
});

test('щиты и кражи: Паладин начинает бой со щитом 120, щиты Копейщика прочнее на пятую часть и его силу не украсть, Хранитель крадёт на треть больше', () => {
  assert.equal(fighter(duel(), 'B').shield, 120);

  let s = duel({ a: 'RS-C012', da: 'sky', b: 'RS-C006', db: 'control', gate: 'RS-G008' });
  const spear = s.players.B.fighter;
  s.players.A.mana = 10;
  s.players.B.mana = 10;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N10')] }); // перенести 150 G
  s = act(s, 'B', { type: 'activate', cards: [give(s, 'B', 'D-S01')] }); // щит 200
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'stealBlocked' && e.unit === spear && e.why === 'ability'));
  assert.ok(s.log.some(e => e.t === 'shield' && e.unit === spear && e.amount === 240));

  let t = duel({ a: 'RS-C012', da: 'sky', b: 'RS-C009', gate: 'RS-G008' });
  setFighters(t, { ga: 400, gb: 400 });
  t.players.A.mana = 10;
  t = act(t, 'A', { type: 'activate', cards: [give(t, 'A', 'D-N10')] });
  t = act(t, 'system', sys);
  assert.equal(t.log.find(e => e.t === 'gain' && e.why === 'D-N10').amount, 195);
});

test('Мудрец глубин видит вид скрытых карт соперника и в начале боя берёт на карту больше', () => {
  let s = duel({ a: 'RS-C004', b: 'RS-C009', da: 'answers' });
  assert.equal(s.players.A.hand.length, D.RULES.startHand + 1);
  assert.equal(s.players.B.hand.length, D.RULES.startHand);
  s.players.B.mana = 10;
  s = act(s, 'B', { type: 'activate', cards: [give(s, 'B', 'D-N08')] });
  const seen = D.viewDuel(s, 'A').bout.queue[0];
  assert.deepEqual(seen.kinds, ['attack']);
  assert.equal(seen.defs, undefined, 'сами карты скрыты');
  assert.equal(D.viewDuel(s, 'B').bout.queue.length, 1);
});

test('Дуэлянт облаков: 3 активации за раунд, первая на 1 ману дешевле', () => {
  let s = duel({ a: 'RS-C008', b: 'RS-C009', da: 'sky' });
  const [n01, n02, n03] = ['D-N01', 'D-N02', 'D-N03'].map(d => give(s, 'A', d)); // 1, 2 и 2 маны
  s.players.A.mana = 10;
  assert.equal(D.activationCost(s, 'A', [n02]), 1);
  s = act(s, 'A', { type: 'activate', cards: [n02] });
  assert.equal(s.players.A.mana, 9);
  s = act(s, 'A', { type: 'activate', cards: [n03] });
  assert.equal(s.players.A.mana, 7, 'скидка только на первую активацию');
  s = act(s, 'A', { type: 'activate', cards: [n01] });
  assert.ok(!D.legalActions(s, 'A').some(a => a.type === 'activate'), 'четвёртой активации нет');
});

test('Буревой грифон: каждое его слияние даёт ещё +60 G', () => {
  let s = duel({ a: 'RS-C007', b: 'RS-C009', da: 'control', gate: 'RS-G008' });
  const griffin = s.players.A.fighter;
  s.players.A.mana = 10;
  s = act(s, 'A', { type: 'activate', cards: [give(s, 'A', 'D-N01'), give(s, 'A', 'D-W01')] });
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'gain' && e.unit === griffin && e.why === 'ability' && e.amount === 60));
});

// ---------------------------------------------------------------- gates

// The bout's gate: who laid it and who plays against it.
const sides = s => {
  const owner = D.gateOwner(s), foe = D.other(owner);
  return { owner, foe, uo: s.players[owner].fighter, uf: s.players[foe].fighter };
};
// Fighters at exact G as they will be right after the gate opens: only the owner's fighter gets the aspect bonus.
function afterBonus(s, go, gf) {
  const { uo, uf } = sides(s);
  s.units[uo].g = go - D.gateBonus(s, uo);
  s.units[uf].g = gf;
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

test('открыть ворота — скрытое действие без траты активации; они открываются в конце раунда, бонус аспекта — бойцу владельца', () => {
  let s = duel({ gate: 'RS-G005' }); // бонус: щит 200 бойцу владельца
  const { owner, foe, uo, uf } = sides(s);
  const bonus = D.gateBonus(s, uo);
  assert.ok(bonus > 0);
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
  assert.equal(s.units[uo].startG, D.COLOSSI[s.units[uo].def].g + bonus, 'бонус держится до конца боя');
  assert.equal(s.units[uf].startG, D.COLOSSI[s.units[uf].def].g, 'бойцу соперника бонуса нет');
  assert.ok(s.log.some(e => e.t === 'shield' && e.unit === uo && e.amount === 200));
  assert.equal(D.viewDuel(s, foe).bout.gateDef, 'RS-G005', 'открытые ворота видят оба');
  assert.ok(!D.legalActions(s, owner).some(a => a.type === 'openGate'));
});

test('ловушка «Горящий мост»: при открытии боец соперника теряет 200 G, щиты не защищают', () => {
  let s = duel({ gate: 'RS-G002' });
  const { owner, uf } = sides(s);
  afterBonus(s, 400, 400);
  s.units[uf].shield = 100;
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  const hit = s.log.find(e => e.t === 'damage' && e.why === 'RS-G002');
  assert.equal(hit.unit, uf);
  assert.equal(hit.amount, 200);
  assert.equal(hit.g, 200);
  assert.ok(!s.log.some(e => e.t === 'shieldAbsorb' && e.seq < hit.seq), 'щит не тронут');
});

test('ловушка «Белый амфитеатр»: в раунде открытия сильный теряет разницу, слабый — отдачу; дальше как обычно', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G010' });
  const { owner, uo, uf } = sides(s);
  afterBonus(s, 300, 500);
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'attack' && e.inverted));
  assert.equal(s.units[uf].g, 300, 'сильный потерял разницу');
  assert.equal(s.units[uo].g, 180, 'слабому — отдача 120');
  s.units[uo].g = 200;
  s = act(s, 'system', sys);
  assert.equal(s.units[uo].g, 100, 'следующий раунд — снова теряет слабый');
  assert.equal(s.units[uf].g, 240);
});

test('ловушка «Пустой престол»: силы бойцов меняются местами', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G011' });
  const { owner, uo, uf } = sides(s);
  afterBonus(s, 300, 450);
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'swap'));
  // после обмена 450 против 300: слабый теряет 150, сильный — отдачу 90
  assert.equal(s.units[uf].g, 150);
  assert.equal(s.units[uo].g, 360);
});

test('ловушка «Чаша отражений»: в раунде открытия урон карт соперника бьёт по его собственному бойцу', () => {
  let s = duel({ gate: 'RS-G004' });
  const { owner, foe, uo, uf } = sides(s);
  afterBonus(s, 400, 400);
  s.players[foe].mana = 10;
  s = act(s, foe, { type: 'activate', cards: [give(s, foe, 'D-N08')] }); // враг теряет 280 G
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'reflected' && e.player === foe));
  const hit = s.log.find(e => e.t === 'damage' && e.why === 'D-N08');
  assert.equal(hit.unit, uf, 'карта ударила по своему');
  assert.ok(!s.log.some(e => e.t === 'damage' && e.unit === uo && e.why === 'D-N08'));
});

test('ловушка «Паруса высоты»: у соперника на 3 маны меньше в следующем раунде', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G008' });
  const { owner, foe } = sides(s);
  afterBonus(s, 400, 400); // равные силы: маны за проигрыш атаки нет
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  assert.equal(s.players[foe].mana, D.RULES.mana(s.bout.rounds) - 3);
  assert.equal(s.players[owner].mana, D.RULES.mana(s.bout.rounds));
});

test('ловушка «Зеркальный разлом» бьёт только если боец соперника сильнее', () => {
  for (const [go, gf, hits] of [[300, 400, true], [400, 300, false]]) {
    let s = duel({ gate: 'RS-G012' });
    const { owner } = sides(s);
    afterBonus(s, go, gf);
    s = act(s, owner, { type: 'openGate' });
    s = act(s, 'system', sys);
    assert.equal(s.log.some(e => e.t === 'damage' && e.why === 'RS-G012'), hits);
  }
});

test('поле «Кузница над бездной»: пока ворота открыты, в начале раунда оба бойца +40 G, боец владельца — ещё +40', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G001' });
  const { owner, uo, uf } = sides(s);
  afterBonus(s, 400, 400);
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys); // равные силы: оба 360, затем новый раунд под Кузницей
  assert.equal(s.units[uo].g, 360 + 80);
  assert.equal(s.units[uf].g, 360 + 40);
});

test('поле «Каменный круг»: пока ворота открыты, восстановление и кража силы не действуют у соперника владельца', () => {
  let s = duel({ a: 'RS-C005', b: 'RS-C005', da: 'control', db: 'control', gate: 'RS-G006' });
  const { owner, foe, uo, uf } = sides(s);
  afterBonus(s, 500, 500);
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  s.units[uo].g = s.units[uo].startG - 200;
  s.units[uf].g = s.units[uf].startG - 200;
  s.players[owner].mana = 10;
  s.players[foe].mana = 10;
  s = act(s, foe, { type: 'activate', cards: [give(s, foe, 'D-N04'), give(s, foe, 'D-N10')] });
  s = act(s, owner, { type: 'activate', cards: [give(s, owner, 'D-N04')] });
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'healBlocked' && e.unit === uf));
  assert.ok(s.log.some(e => e.t === 'stealBlocked' && e.unit === uf));
  assert.ok(s.log.some(e => e.t === 'heal' && e.unit === uo && e.amount === 180), 'у владельца восстановление работает');
});

test('поле «Разорванная галерея»: каждое слияние владельца даёт его бойцу ещё +120 G, слияния соперника — нет', () => {
  let s = duel({ ...PLAIN, gate: 'RS-G007' });
  const { owner, foe, uo } = sides(s);
  for (const p of [owner, foe]) {
    s.players[p].mana = 10;
    s = act(s, p, { type: 'activate', cards: [give(s, p, 'D-N02'), give(s, p, 'D-L01')] });
  }
  s = act(s, owner, { type: 'openGate' });
  s = act(s, 'system', sys);
  const extra = s.log.filter(e => e.t === 'gain' && e.why === 'gate');
  assert.deepEqual(extra.map(e => [e.unit, e.amount]), [[uo, 120]]);
});

test('Отмена бьёт первое действие соперника: если это открытие ворот, ворота остаются закрытыми', () => {
  let s = duel({ gate: 'RS-G002' });
  const { owner, foe } = sides(s);
  s.players[foe].mana = 10;
  s = act(s, owner, { type: 'openGate' });
  s = act(s, foe, { type: 'activate', cards: [give(s, foe, 'D-N05')] });
  s = act(s, 'system', sys);
  assert.equal(s.bout.gateOpen, false);
  assert.ok(s.log.some(e => e.t === 'countered' && e.kind === 'gate'));
  assert.ok(!s.log.some(e => e.why === 'RS-G002'));
  assert.ok(D.legalActions(s, owner).some(a => a.type === 'openGate'), 'можно попробовать ещё раз');
});

test('Замок ворот пропускает карты и отменяет только открытие ворот; промах — карта в руку', () => {
  let s = duel({ a: 'RS-C005', b: 'RS-C005', da: 'control', db: 'control', gate: 'RS-G002' });
  const { owner, foe } = sides(s);
  s.players[owner].mana = 10;
  s.players[foe].mana = 10;
  s = act(s, owner, { type: 'activate', cards: [give(s, owner, 'D-N01')] });
  s = act(s, owner, { type: 'openGate' });
  s = act(s, foe, { type: 'activate', cards: [give(s, foe, 'D-N11')] });
  const [card, gate] = s.bout.queue.map(a => a.id);
  s = act(s, 'system', sys);
  assert.ok(s.log.some(e => e.t === 'countered' && e.id === gate && e.kind === 'gate'));
  assert.ok(!s.log.some(e => e.t === 'countered' && e.id === card), 'карта владельца сработала');
  assert.equal(s.bout.gateOpen, false);
  // следующий раунд ворота никто не открывает: Замок промахивается, и его хозяин берёт карту
  s.players[foe].mana = 10;
  s = act(s, foe, { type: 'activate', cards: [give(s, foe, 'D-N11')] });
  s = act(s, 'system', sys);
  const miss = s.log.findIndex(e => e.t === 'counterMiss' && e.player === foe && e.def === 'D-N11');
  assert.ok(miss >= 0);
  assert.deepEqual([s.log[miss + 1].t, s.log[miss + 1].player], ['draw', foe]);
});

test('неоткрытые ворота с концом боя возвращаются владельцу и остаются тайной', () => {
  let s = duel({ gate: 'RS-G002' });
  const { owner, foe } = sides(s);
  const gid = s.bout.gate;
  setFighters(s, { ga: 400, gb: 0 });
  s.players.B.life = 5000;
  s = act(s, 'system', sys);
  const end = s.log.find(e => e.t === 'boutEnd');
  assert.equal(end.gateOpened, false);
  assert.equal(end.gateReturned, true);
  assert.equal(s.gates[gid].used, false, 'их можно выложить снова');
  const v = D.viewDuel(s, foe);
  assert.ok(!JSON.stringify(v.log).includes('gateDef'), 'сопернику ворота так и не показаны');
  assert.equal(v.players[owner].gates.find(g => g.gate === gid).def, null);
});

// ---------------------------------------------------------------- whole matches

function playOut(seed, bots) {
  const rng = seedRng(`duel:${seed}`);
  const decks = Object.keys(D.DUEL_DECKS);
  let { record, state } = D.newDuelRecord({ seed, players: [{ deck: deck(decks[seed % decks.length]) }, { deck: deck(decks[(seed + 1) % decks.length]) }] });
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

test('все готовые колоды законны', () => {
  for (const [key, d] of Object.entries(D.DUEL_DECKS)) assert.deepEqual(D.validateDuelDeck(d), [], key);
});

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
