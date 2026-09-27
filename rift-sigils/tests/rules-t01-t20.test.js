// GDD §21, mandatory scenarios T01-T20.
import { test } from 'node:test';
import {
  R, assert, act, addMod, deckWith, finishDuel, give, handOf, has, lastEvent, pass, place, play, powerOf, preset,
  resolveChain, setGate, setMana, setupMatch, tryAct, unit,
} from './helpers.js';

const restRound = s => act(act(s, 'A', { type: 'rest' }), 'B', { type: 'rest' });

test('T01 легальная сборка: допуск; третий аспект или третья копия — отказ', () => {
  for (const key of Object.keys(R.PRESET_DECKS)) assert.deepEqual(R.validateDeck(preset(key)), []);
  const third = preset('attack');
  third.colossi[1] = 'RS-C005'; // Жар + Камень + Свет
  assert.ok(R.validateDeck(third).some(e => e.includes('двух базовых аспектов')));
  const copies = preset('attack');
  copies.abilities[1] = 'RS-A001'; copies.abilities[2] = 'RS-A001'; // Угольный рывок x3
  assert.ok(R.validateDeck(copies).some(e => e.includes('копий')));
  assert.throws(() => R.createMatch({ players: [{ deck: third }, { deck: preset('answers') }] }), e => e.code === 'illegal-deck');
});

test('T02 обмен руки: замены до возвращения отложенных; скрытые карты не раскрываются', () => {
  let { state: s } = R.createMatch({ seed: 3, assignSeats: false, players: [{ deck: preset('attack') }, { deck: preset('answers') }] });
  while (s.phase === 'setupGates') for (const p of ['A', 'B']) { const a = R.legalActions(s, p)[0]; if (a) s = act(s, p, a); }
  const back = s.players.A.hand.slice(0, 2);
  // Put second copies of the returned abilities on top: a new instance of the same id may come.
  for (const [i, cid] of back.entries()) {
    const twin = s.players.A.deck.find(c => c !== cid && s.cards[c].def === s.cards[cid].def);
    if (twin) { s.players.A.deck = s.players.A.deck.filter(c => c !== twin); s.players.A.deck.splice(i, 0, twin); }
  }
  s = act(s, 'A', { type: 'mulligan', cards: back });
  s = act(s, 'B', { type: 'mulligan', cards: [] });
  const hand = s.players.A.hand;
  assert.equal(hand.length, 4);
  for (const cid of back) {
    assert.ok(!hand.includes(cid), 'возвращённый экземпляр не может сразу вернуться');
    assert.ok(s.players.A.deck.includes(cid));
  }
  assert.deepEqual(hand.slice(2).map(c => s.cards[c].def).sort(), back.map(c => s.cards[c].def).sort());
  const bView = JSON.stringify(R.viewFor(s, 'B'));
  for (const cid of [...back, ...hand]) assert.ok(!bView.includes(`"${cid}"`), `B видит ${cid}`);
});

test('T03 мана раунда: в раунде 4 обе стороны получают ровно 5', () => {
  let s = setupMatch();
  s = restRound(restRound(s));
  s = act(s, 'A', { type: 'rest' });
  setMana(s, 1, 0);
  s = act(s, 'B', { type: 'rest' });
  assert.equal(s.round, 4);
  assert.equal(s.players.A.mana, 5);
  assert.equal(s.players.B.mana, 5);
});

test('T04 защита и свой ход: потратив 3 из 4 в чужой ход, B играет свой ход с 1', () => {
  let s = restRound(restRound(setupMatch()));
  assert.equal(s.players.B.mana, 4);
  place(s, unit(s, 'B', 'RS-C003'), 'C2');
  const heavy = give(s, 'B', 'RS-A010'), mute = give(s, 'B', 'RS-A032');
  s = act(s, 'A', { type: 'launch', unit: unit(s, 'A', 'RS-C001'), platform: 'C2' });
  s = pass(s, 'A');
  s = resolveChain(play(s, 'B', heavy));
  s = pass(s, 'A');
  s = resolveChain(play(s, 'B', mute));
  s = finishDuel(s);
  assert.equal(s.active, 'B');
  assert.equal(s.round, 3);
  assert.equal(s.players.B.mana, 1);
});

test('T05 лимит руки: девятая карта раскрывается и сбрасывается', () => {
  let s = setupMatch();
  while (s.players.A.hand.length < 8) s.players.A.hand.push(s.players.A.deck.shift());
  const discard = s.players.A.discard.length;
  s = restRound(s);
  assert.equal(s.players.A.hand.length, 8);
  assert.equal(s.players.A.discard.length, discard + 1);
  const burn = lastEvent(s, 'burn');
  assert.equal(burn.player, 'A');
  assert.ok(R.viewFor(s, 'B').log.some(e => e.t === 'burn' && e.def === burn.def), 'сожжённая карта видна сопернику');
});

test('T06 Тактический резерв: 8 с разыгранной, взять 2, сбросить 1 — остаётся 8, досрочного сжигания нет', () => {
  let s = setupMatch({ a: 'answers', b: 'attack' });
  const card = handOf(s, 'A', 'RS-A039') ?? give(s, 'A', 'RS-A039');
  while (s.players.A.hand.length < 8) s.players.A.hand.push(s.players.A.deck.shift());
  s = act(s, 'A', { type: 'prep', card, targets: {} });
  assert.equal(s.phase, 'choice');
  assert.equal(s.players.A.hand.length, 9);
  assert.ok(!s.log.some(e => e.t === 'burn'));
  s = act(s, 'A', { type: 'discard', card: s.players.A.hand[0] });
  assert.equal(s.players.A.hand.length, 8);
  assert.equal(s.phase, 'turn');
  assert.ok(has(s, 'A', a => a.type === 'launch'), 'основное действие остаётся');
});

test('T07 пустая колода: добор ничего не делает, без урона и ошибки', () => {
  let s = setupMatch();
  s.players.A.discard.push(...s.players.A.deck);
  s.players.A.deck = [];
  const hand = s.players.A.hand.length;
  s = restRound(s);
  assert.equal(s.players.A.hand.length, hand);
  assert.ok(s.log.some(e => e.t === 'drawEmpty' && e.player === 'A'));
  assert.equal(s.result, null);
});

test('T08 своё существо на цели: запуск на свою платформу — отказ, Double Stand нет', () => {
  let s = setupMatch();
  s = act(s, 'A', { type: 'launch', unit: 'Au1', platform: 'A1' });
  s = act(s, 'B', { type: 'rest' });
  const r = tryAct(s, 'A', { type: 'launch', unit: 'Au2', platform: 'A1' });
  assert.equal(r.ok, false);
  assert.equal(r.error, 'illegal');
});

test('T09 соседство после удаления: A1 и C1 не соседи, перемещение стоит 1', () => {
  let s = setupMatch();
  s.board.B1.removed = true;
  place(s, 'Au1', 'A1');
  assert.equal(R.adjacent('A1', 'C1'), false);
  s = act(s, 'A', { type: 'move', unit: 'Au1', platform: 'C1' });
  assert.equal(s.players.A.mana, 1);
  assert.equal(lastEvent(s, 'move').cost, 1);
  assert.equal(s.units.Au1.platform, 'C1');
});

test('T10 одно действие: после запуска второй запуск и подготовка запрещены', () => {
  let s = setupMatch();
  const shove = give(s, 'A', 'RS-A040');
  s = act(s, 'A', { type: 'launch', unit: 'Au1', platform: 'A1' });
  assert.ok(s.players.A.mana > 0);
  assert.deepEqual(R.legalActions(s, 'A'), []);
  assert.equal(tryAct(s, 'A', { type: 'launch', unit: 'Au2', platform: 'C1' }).ok, false);
  assert.equal(tryAct(s, 'A', { type: 'prep', card: shove, targets: {} }).ok, false);
  // And at most one Подготовка before the action.
  s = act(s, 'B', { type: 'rest' });
  const scan = give(s, 'A', 'RS-A040');
  place(s, 'Bu1', 'C2');
  s = act(s, 'A', { type: 'prep', card: scan, targets: { unit: 'Bu1', platform: 'C1' } });
  assert.ok(!has(s, 'A', a => a.type === 'prep'));
});

test('T11 удержание: после одного окончания хода B счётчик 1, захват ещё незаконен', () => {
  let s = setupMatch();
  s = act(s, 'A', { type: 'launch', unit: 'Au1', platform: 'A1' });
  s = act(s, 'B', { type: 'rest' });
  assert.equal(s.units.Au1.hold, 1);
  assert.ok(!has(s, 'A', a => a.type === 'capture'));
});

test('T12 зрелое удержание: счётчик 2, захват требует собственного основного действия', () => {
  let s = setupMatch();
  s = act(s, 'A', { type: 'launch', unit: 'Au1', platform: 'A1' });
  s = act(act(s, 'B', { type: 'rest' }), 'A', { type: 'rest' });
  s = act(s, 'B', { type: 'rest' });
  assert.equal(s.units.Au1.hold, 2);
  assert.equal(s.players.A.sigils, 0, 'печать не приходит сама');
  assert.ok(has(s, 'A', a => a.type === 'capture' && a.unit === 'Au1'));
  s = act(s, 'A', { type: 'capture', unit: 'Au1' });
  assert.equal(s.players.A.sigils, 1);
  assert.equal(s.board.A1.removed, true);
  assert.equal(s.units.Au1.zone, 'exhausted');
  assert.equal(s.units.Au1.readyOn, s.players.A.turnIndex + 1);
});

test('T13 Сдвиг опоры: враг перемещён, удержание 0, основное действие сохранено', () => {
  let s = setupMatch();
  place(s, 'Bu1', 'B1', 2);
  const card = give(s, 'A', 'RS-A040');
  s = act(s, 'A', { type: 'prep', card, targets: { unit: 'Bu1', platform: 'A1' } });
  assert.equal(s.units.Bu1.platform, 'A1');
  assert.equal(s.units.Bu1.hold, 0);
  assert.equal(s.active, 'A');
  assert.ok(has(s, 'A', a => a.type === 'launch'));
});

test('T14 Якорь: карта и 2 маны расходуются, цель не перемещается, удержание 2', () => {
  let s = setupMatch();
  place(s, 'Bu1', 'B1', 2);
  s.units.Bu1.anchorUntil = s.turnNo + 1;
  const card = give(s, 'A', 'RS-A040');
  s = act(s, 'A', { type: 'prep', card, targets: { unit: 'Bu1', platform: 'A1' } });
  assert.equal(s.units.Bu1.platform, 'B1');
  assert.equal(s.units.Bu1.hold, 2);
  assert.equal(s.players.A.mana, 0);
  assert.ok(s.players.A.discard.includes(card));
  assert.ok(lastEvent(s, 'anchorHeld'));
});

test('T15 своя смена позиции: Якорь не мешает Обратному течению, удержание 0', () => {
  let s = setupMatch({ a: deckWith(['RS-C003', 'RS-C004', 'RS-C006'], ['RS-A009']), b: 'attack' });
  const spear = unit(s, 'A', 'RS-C006');
  place(s, spear, 'B2', 2);
  assert.ok(s.units[spear].def === 'RS-C006');
  const card = give(s, 'A', 'RS-A009');
  s = act(s, 'A', { type: 'prep', card, targets: { unit: spear, platform: 'C1' } });
  assert.equal(s.units[spear].platform, 'C1');
  assert.equal(s.units[spear].hold, 0);
});

function duelAt(s, gateDef, q = 'B1') {
  place(s, 'Bu1', q);
  if (gateDef) setGate(s, q, gateDef);
  return act(s, 'A', { type: 'launch', unit: 'Au1', platform: q });
}

function evenTo(s, target) {
  addMod(s, s.duel.attacker, target - powerOf(s, s.duel.attacker));
  addMod(s, s.duel.defender, target - powerOf(s, s.duel.defender));
  assert.equal(powerOf(s, s.duel.attacker), target);
  assert.equal(powerOf(s, s.duel.defender), target);
}

test('T16 ничья на обычных воротах 18:18 — выигрывает защитник', () => {
  let s = duelAt(setupMatch(), 'RS-G002');
  evenTo(s, 18);
  s = finishDuel(s);
  assert.equal(lastEvent(s, 'clash').winner, 'Bu1');
  assert.equal(s.players.B.sigils, 1);
});

test('T17 особая ничья: Зеркальный разлом 18:18 — выигрывает нападающий', () => {
  let s = duelAt(setupMatch(), 'RS-G012');
  evenTo(s, 18);
  s = finishDuel(s);
  assert.equal(lastEvent(s, 'clash').winner, 'Au1');
  assert.equal(s.players.A.sigils, 1);
});

test('T18 минимум силы: сумма −2 показывается как 0; бой идёт до двух пасов при пустой цепочке', () => {
  let s = duelAt(setupMatch(), 'RS-G002');
  addMod(s, 'Au1', -(powerOf(s, 'Au1') + 2));
  const b = R.breakdown(s, 'Au1');
  assert.equal(b.raw, -2);
  assert.equal(b.total, 0);
  s = pass(s, 'A');
  assert.ok(s.duel, 'одного паса недостаточно');
  s = pass(s, 'B');
  assert.equal(s.duel, null);
});

test('T19 поддержка: ортогональный союзник допустим, диагональный нет, выбирается не более одного', () => {
  let s = setupMatch();
  place(s, 'Bu1', 'B1');
  place(s, 'Au2', 'A1'); // orthogonal to B1
  place(s, 'Au3', 'A2'); // diagonal to B1
  s = act(s, 'A', { type: 'launch', unit: 'Au1', platform: 'B1' });
  const options = R.legalActions(s, 'A').map(a => a.unit);
  assert.deepEqual(options.sort(), ['Au2', null].sort());
  assert.equal(tryAct(s, 'A', { type: 'support', unit: 'Au3' }).ok, false);
  s = act(s, 'A', { type: 'support', unit: 'Au2' });
  assert.deepEqual(R.legalActions(s, 'A').filter(a => a.type === 'support'), []);
});

test('T20 разрыв поддержки: у Грифона исчезают все 4, союзник всё равно восстанавливается и освобождает клетку', () => {
  let s = setupMatch({ a: 'control', b: 'control' });
  const griffin = unit(s, 'A', 'RS-C007'), ally = unit(s, 'A', 'RS-C005');
  place(s, 'Bu2', 'B1');
  setGate(s, 'B1', 'RS-G008');
  place(s, ally, 'A1');
  s = act(s, 'A', { type: 'launch', unit: griffin, platform: 'B1' });
  s = act(s, 'A', { type: 'support', unit: ally });
  const before = powerOf(s, griffin);
  const cut = give(s, 'B', 'RS-A021');
  s = pass(s, 'A');
  s = resolveChain(play(s, 'B', cut));
  assert.equal(powerOf(s, griffin), before - 4);
  assert.ok(R.breakdown(s, griffin).parts.some(x => x.label === 'Поддержка подавлена'));
  const k = s.players.A.turnIndex;
  s = finishDuel(s);
  assert.equal(s.units[ally].zone, 'exhausted');
  assert.equal(s.units[ally].readyOn, k + 1);
  assert.equal(s.board.A1.unit, null);
});
