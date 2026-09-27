// GDD §21, mandatory scenarios T21-T40.
import { test } from 'node:test';
import {
  R, assert, act, addMod, deckWith, finishDuel, give, has, lastEvent, pass, place, play, powerOf, preset,
  resolveChain, setGate, setMana, setupMatch, tryAct, unit,
} from './helpers.js';

// A's first colossus attacks B's `defender` standing on `q`.
function duel(s, { gate = 'RS-G008', q = 'B1', attacker = 'Au1', defender = 'Bu1', mana } = {}) {
  place(s, defender, q);
  setGate(s, q, gate);
  if (mana !== undefined) setMana(s, mana);
  return act(s, 'A', { type: 'launch', unit: attacker, platform: q });
}

const chainTargets = (s, p, cid) => R.legalActions(s, p).filter(a => a.card === cid).map(a => a.targets);

test('T21 Каменный круг: вклад выбранного союзника 0, расчёт показывает причину', () => {
  let s = setupMatch();
  place(s, 'Au2', 'A1');
  s = duel(s, { gate: 'RS-G006' });
  s = act(s, 'A', { type: 'support', unit: 'Au2' });
  const part = R.breakdown(s, 'Au1').parts.find(x => x.kind === 'support');
  assert.equal(part.value, 0);
  assert.match(part.label, /Каменный круг/);
  assert.equal(s.units.Au2.hold, 0, 'участие поддержки уже израсходовано');
});

test('T22 порядок LIFO: пара пасов разрешает только отмену; усиление уходит в сброс без эффекта', () => {
  let s = duel(setupMatch(), { mana: 6 });
  const boost = give(s, 'A', 'RS-A001'), cut = give(s, 'B', 'RS-A041');
  s = play(s, 'A', boost);
  s = play(s, 'B', cut, { object: 'o1' });
  s = pass(pass(s, 'A'), 'B');
  assert.ok(s.duel, 'поединок продолжается');
  assert.equal(s.duel.chain.length, 0);
  assert.ok(s.players.A.discard.includes(boost));
  assert.deepEqual(s.duel.mods, []);
});

test('T23 отмена отмены: отмена B удалена, исходное усиление остаётся и разрешается', () => {
  let s = duel(setupMatch(), { mana: 6 });
  const boost = give(s, 'A', 'RS-A001'), cutB = give(s, 'B', 'RS-A041'), cutA = give(s, 'A', 'RS-A041');
  s = play(s, 'A', boost);
  s = play(s, 'B', cutB, { object: 'o1' });
  s = play(s, 'A', cutA, { object: 'o2' });
  s = pass(pass(s, 'B'), 'A');
  assert.deepEqual(s.duel.chain.map(c => c.oid), ['o1']);
  assert.ok(s.players.B.discard.includes(cutB));
  s = resolveChain(s);
  assert.equal(s.duel.mods.find(m => m.target === 'Au1').amount, 3);
  assert.equal(s.players.A.mana, 6 - 1 - 3, 'все три карты оплачены');
  assert.equal(s.players.B.mana, 6 - 3);
});

test('T24 карта Бой поверх цепочки запрещена, законная Реакция допустима', () => {
  let s = duel(setupMatch(), { mana: 6 });
  const boost = give(s, 'A', 'RS-A001');
  const heavy = give(s, 'B', 'RS-A010'), cut = give(s, 'B', 'RS-A041');
  s = play(s, 'A', boost);
  assert.equal(s.duel.priority, 'B');
  assert.ok(!has(s, 'B', a => a.card === heavy));
  assert.ok(has(s, 'B', a => a.card === cut));
});

test('T25 снятие уже выполненного: отмена его не выбирает, Смыть чары выбирает модификатор', () => {
  let s = duel(setupMatch(), { mana: 6 });
  const boost = give(s, 'A', 'RS-A001');
  const cut = give(s, 'B', 'RS-A041'), wash = give(s, 'B', 'RS-A007');
  s = resolveChain(play(s, 'A', boost));
  s = pass(s, 'A');
  assert.deepEqual(chainTargets(s, 'B', cut), []);
  const mod = s.duel.mods.find(m => m.target === 'Au1').id;
  assert.deepEqual(chainTargets(s, 'B', wash), [{ mod }]);
  s = resolveChain(play(s, 'B', wash, { mod }));
  assert.equal(s.duel.mods.length, 0);
});

test('T26 цена и скидка: скидка первой карты тратится при оплате, даже если карту отменили; удорожание отмены +1', () => {
  let s = duel(setupMatch(), { gate: 'RS-G004', mana: 6 });
  const cut = R.ABILITIES['RS-A041'];
  const boost = give(s, 'A', 'RS-A001'), cutB = give(s, 'B', 'RS-A041'), cutA = give(s, 'A', 'RS-A041');
  s = play(s, 'A', boost);
  assert.equal(s.players.A.mana, 5, 'минимум 1 даже со скидкой');
  assert.equal(R.costOf(s, 'B', cut), 2);
  s = play(s, 'B', cutB, { object: 'o1' });
  assert.equal(s.players.B.mana, 4);
  s = play(s, 'A', cutA, { object: 'o2' });
  assert.equal(s.players.A.mana, 2, 'вторая способность без скидки');
  s = pass(pass(s, 'B'), 'A');
  assert.ok(s.players.B.discard.includes(cutB), 'карта B отменена');
  assert.equal(R.costOf(s, 'B', cut), 3, 'скидка B уже потрачена');

  let t = duel(setupMatch(), { gate: 'RS-G010', mana: 6 });
  assert.equal(R.costOf(t, 'A', cut), 4);
  assert.equal(R.costOf(t, 'A', R.ABILITIES['RS-A036']), 4);
  assert.equal(R.costOf(t, 'A', R.ABILITIES['RS-A007']), 2, 'снятие модификатора — не отмена');
});

test('T27 печатная стоимость: карта с базой 3 за 2 после скидки не цель для Отнятого эха', () => {
  const shadow = deckWith(['RS-C011', 'RS-C012', 'RS-C001'], ['RS-A036']);
  let s = duel(setupMatch({ a: 'control', b: shadow }), { gate: 'RS-G004', mana: 6 });
  const strike = give(s, 'A', 'RS-A046'), echo = give(s, 'B', 'RS-A036');
  s = play(s, 'A', strike);
  assert.equal(s.players.A.mana, 4, 'заплачено 2');
  assert.deepEqual(chainTargets(s, 'B', echo), []);

  let t = duel(setupMatch({ a: 'control', b: shadow }), { gate: 'RS-G004', mana: 6 });
  const stance = give(t, 'A', 'RS-A013'), echo2 = give(t, 'B', 'RS-A036');
  t = play(t, 'A', stance);
  assert.deepEqual(chainTargets(t, 'B', echo2), [{ object: 'o1' }]);
});

test('T28 Покров и перенос: ослабление предотвращено, Покров снят, свой боец получает +3', () => {
  let s = duel(setupMatch({ a: 'answers', b: 'attack' }), { mana: 6 });
  const shield = give(s, 'B', 'RS-A025'), debt = give(s, 'A', 'RS-A031');
  s = pass(s, 'A');
  s = resolveChain(play(s, 'B', shield));
  assert.equal(s.duel.shroud.Bu1, true);
  const [a0, b0] = [powerOf(s, 'Au1'), powerOf(s, 'Bu1')];
  s = resolveChain(play(s, 'A', debt));
  assert.equal(s.duel.shroud.Bu1, undefined);
  assert.equal(powerOf(s, 'Bu1'), b0);
  assert.equal(powerOf(s, 'Au1'), a0 + 3);
});

test('T29 Покров и Мудрец: расходуется только Покров, пассив Мудреца остаётся', () => {
  let s = setupMatch({ a: 'attack', b: 'answers' });
  const sage = unit(s, 'B', 'RS-C004');
  s = duel(s, { defender: sage, mana: 6 });
  const pool = give(s, 'B', 'RS-A008');
  const blade1 = give(s, 'A', 'RS-A003'), blade2 = give(s, 'A', 'RS-A003');
  s = pass(s, 'A');
  s = resolveChain(play(s, 'B', pool));
  s = resolveChain(play(s, 'A', blade1));
  assert.equal(s.duel.shroud[sage], undefined);
  assert.equal(s.duel.sageUsed, false);
  assert.ok(!s.duel.mods.some(m => m.target === sage && m.amount < 0));
  s = resolveChain(play(s, 'A', blade2));
  assert.equal(s.duel.sageUsed, true);
  assert.ok(!s.duel.mods.some(m => m.target === sage && m.amount < 0));
});

test('T30 Немота титана: штраф −3 исчезает, титан становится сильнее', () => {
  let s = setupMatch({ a: 'control', b: 'answers' });
  const titan = unit(s, 'A', 'RS-C005');
  s = duel(s, { attacker: titan, mana: 6 });
  assert.ok(R.breakdown(s, titan).parts.some(x => x.kind === 'passive' && x.value === -3));
  const before = powerOf(s, titan);
  const mute = give(s, 'B', 'RS-A032');
  s = pass(s, 'A');
  s = resolveChain(play(s, 'B', mute));
  assert.equal(powerOf(s, titan), before + 3);
});

test('T31 Немота Птицы: поражение под Немотой — обычное k+2; без Немоты — k+1', () => {
  const light = deckWith(['RS-C010', 'RS-C009', 'RS-C001'], ['RS-A025']);
  for (const muted of [true, false]) {
    let s = setupMatch({ a: 'answers', b: light });
    const bird = unit(s, 'B', 'RS-C010');
    s = duel(s, { defender: bird, mana: 6 });
    addMod(s, 'Au1', 20);
    if (muted) s = resolveChain(play(s, 'A', give(s, 'A', 'RS-A032')));
    const k = s.players.B.turnIndex;
    s = finishDuel(s);
    assert.equal(s.units[bird].readyOn, k + (muted ? 2 : 1));
  }
});

test('T32 восстановление до первого своего хода: k=0, готовность на собственном ходе 2', () => {
  let s = duel(setupMatch());
  addMod(s, 'Au1', 20);
  s = finishDuel(s);
  assert.equal(s.units.Bu1.readyOn, 2);
  assert.equal(s.units.Bu1.zone, 'exhausted', 'в первом своём ходе B колосс ещё восстанавливается');
  s = act(act(s, 'B', { type: 'rest' }), 'A', { type: 'rest' });
  assert.equal(s.players.B.turnIndex, 2);
  assert.equal(s.units.Bu1.zone, 'reserve');
});

test('T33 Новый рассвет: срок k+1 становится k, колосс сразу в резерве, без автозапуска', () => {
  const light = deckWith(['RS-C009', 'RS-C010', 'RS-C001'], ['RS-A030']);
  let s = setupMatch({ a: light, b: 'answers' });
  const k = s.players.A.turnIndex;
  Object.assign(s.units.Au1, { zone: 'exhausted', readyOn: k + 1 });
  setMana(s, 6);
  const dawn = give(s, 'A', 'RS-A030');
  s = act(s, 'A', { type: 'prep', card: dawn, targets: { unit: 'Au1' } });
  assert.equal(s.units.Au1.zone, 'reserve');
  assert.equal(s.units.Au1.platform, null);
  assert.equal(s.active, 'A');
  assert.ok(has(s, 'A', a => a.type === 'launch' && a.unit === 'Au1'));
});

test('T34 смена аспекта: Жар→Прилив, затем Истинный облик — пересчёт каждый раз, база и рука не меняются', () => {
  const firetide = deckWith(['RS-C001', 'RS-C003', 'RS-C004'], ['RS-A011']);
  const light = deckWith(['RS-C009', 'RS-C010', 'RS-C002'], ['RS-A028']);
  let s = duel(setupMatch({ a: firetide, b: light }), { gate: 'RS-G002', mana: 6 });
  const gatePart = () => R.breakdown(s, 'Au1').parts.find(x => x.kind === 'gate').value;
  assert.equal(gatePart(), 2);
  const river = give(s, 'A', 'RS-A011'), trueForm = give(s, 'B', 'RS-A028');
  const handBefore = s.players.A.hand.filter(c => c !== river);
  s = resolveChain(play(s, 'A', river, { aspect: 'tide' }));
  assert.equal(R.currentAspect(s, 'Au1'), 'tide');
  assert.equal(gatePart(), 0);
  s = pass(s, 'A');
  s = resolveChain(play(s, 'B', trueForm, { unit: 'Au1' }));
  assert.equal(R.currentAspect(s, 'Au1'), 'fire');
  assert.equal(gatePart(), 2);
  assert.equal(R.breakdown(s, 'Au1').parts.find(x => x.kind === 'base').value, 12);
  assert.deepEqual(s.players.A.hand, handBefore);
});

test('T35 третья печать удержанием: немедленная победа, следующего действия нет', () => {
  let s = setupMatch();
  s.players.A.sigils = 2;
  place(s, 'Au1', 'A1', 2);
  s = act(s, 'A', { type: 'capture', unit: 'Au1' });
  assert.deepEqual(s.result, { winner: 'A', reason: 'sigils' });
  assert.deepEqual(R.legalActions(s, 'A'), []);
  assert.deepEqual(R.legalActions(s, 'B'), []);
  assert.equal(tryAct(s, 'B', { type: 'rest' }).error, 'match-over');
});

test('T36 предел партии: после 36 ходов — печати, затем зрелые удержания, затем ничья', () => {
  const run = (s, before) => {
    while (!s.result) {
      if (before && s.turnNo === R.TURN_LIMIT) before(s);
      s = act(s, s.active, { type: 'rest' });
    }
    return s;
  };
  let draw = run(setupMatch());
  assert.equal(draw.turnNo, 36);
  assert.deepEqual(draw.result, { winner: null, reason: 'turn-limit-draw' });

  let holds = act(setupMatch(), 'A', { type: 'launch', unit: 'Au1', platform: 'A1' });
  holds = run(holds);
  assert.deepEqual(holds.result, { winner: 'A', reason: 'turn-limit-holds' });

  let sig = run(setupMatch(), s => { s.players.B.sigils = 1; });
  assert.deepEqual(sig.result, { winner: 'B', reason: 'turn-limit-sigils' });
});

test('T37 повтор сетевой команды: тот же nonce не списывает ману и не выполняет эффект повторно', () => {
  let s = duel(setupMatch(), { mana: 6 });
  const card = give(s, 'A', 'RS-A001');
  const cmd = { player: 'A', type: 'play', card, targets: {}, nonce: 'n-1', revision: s.revision };
  const first = R.apply(s, cmd);
  assert.ok(first.ok);
  const again = R.apply(first.state, cmd);
  assert.equal(again.ok, false);
  assert.equal(again.error, 'duplicate-nonce');
  const sameNonceNewRevision = R.apply(first.state, { ...cmd, revision: first.state.revision });
  assert.equal(sameNonceNewRevision.error, 'duplicate-nonce');
  assert.equal(first.state.players.A.mana, 5);
  assert.equal(first.state.duel.chain.length, 1);
  assert.equal(R.apply(s, { ...cmd, nonce: 'n-2', revision: s.revision - 1 }).error, 'stale-revision');
});

test('T38 секреты противника: клиент не получает чужую руку, порядок колоды и неизвестные ворота', () => {
  let s = setupMatch();
  s = act(s, 'A', { type: 'launch', unit: 'Au1', platform: 'A1' });
  const v = R.viewFor(s, 'A');
  const json = JSON.stringify(v);
  for (const cid of [...s.players.B.hand, ...s.players.B.deck, ...s.players.A.deck]) {
    assert.ok(!json.includes(`"${cid}"`), `в представлении A есть ${cid}`);
  }
  assert.equal(v.players.B.hand, undefined);
  assert.equal(v.players.B.handCount, s.players.B.hand.length);
  assert.equal(v.rng, undefined);
  assert.equal(v.cards, undefined);
  for (const q of R.PLATFORMS) {
    const g = s.gates[s.board[q].gate];
    if (g.owner === 'B') {
      assert.equal(v.board[q].gate.def, undefined, `ворота B на ${q} видны`);
      assert.ok(!json.includes(`"${g.def}"`) || Object.values(s.gates).some(x => x.def === g.def && x.owner === 'A'));
    }
  }
  assert.ok(v.log.every(e => !e.secret));
});

test('T39 контент-версия: при разных хэшах правил матч не стартует', () => {
  assert.throws(
    () => R.createMatch({ players: [{ deck: preset('attack'), contentHash: R.CONTENT_HASH }, { deck: preset('answers'), contentHash: 'deadbeef' }] }),
    e => e.code === 'content-mismatch',
  );
  const { record } = R.newRecord({ seed: 1, players: [{ deck: preset('attack') }, { deck: preset('answers') }] });
  assert.throws(() => R.replay({ ...record, contentHash: 'deadbeef' }), e => e.code === 'content-mismatch');
});

test('T40 учебный поединок §14: виверн 19, паладин 20; мана 1 и 0; печать защитнику', () => {
  let s = setupMatch({ a: 'attack', b: 'attack' });
  const wyvern = unit(s, 'A', 'RS-C001'), paladin = unit(s, 'B', 'RS-C009'), knight = unit(s, 'B', 'RS-C002');
  place(s, knight, 'A1');
  s = duel(s, { attacker: wyvern, defender: paladin, gate: 'RS-G002', mana: 4 });
  s = act(s, 'B', { type: 'support', unit: knight });
  assert.equal(powerOf(s, wyvern), 16);
  assert.equal(powerOf(s, paladin), 17);

  const breath = give(s, 'A', 'RS-A002'), cutA = give(s, 'A', 'RS-A041');
  const cutB = give(s, 'B', 'RS-A041'), guard = give(s, 'B', 'RS-A045');
  const rush = give(s, 'A', 'RS-A001');
  s = play(s, 'A', breath);
  s = play(s, 'B', cutB, { object: 'o1' });
  assert.ok(!has(s, 'A', a => a.card === cutA), 'у нападающего осталось 2 маны, своей отмены не оплатить');
  s = pass(pass(s, 'A'), 'B');
  assert.ok(s.players.A.discard.includes(breath));
  assert.equal(powerOf(s, wyvern), 16);
  assert.equal(powerOf(s, paladin), 17);

  s = play(s, 'A', rush);
  s = play(s, 'B', guard);
  s = pass(pass(s, 'A'), 'B');
  assert.equal(powerOf(s, paladin), 20, 'реакция разрешается первой');
  s = pass(pass(s, 'A'), 'B');
  assert.equal(powerOf(s, wyvern), 19);
  assert.equal(s.players.A.mana, 1);
  assert.equal(s.players.B.mana, 0);

  s = pass(pass(s, 'A'), 'B');
  const clash = lastEvent(s, 'clash');
  assert.equal(clash.attacker.total, 19);
  assert.equal(clash.defender.total, 20);
  assert.equal(clash.winner, paladin);
  assert.equal(s.players.B.sigils, 1);
  // All three went to recovery: loser k+2 (A: k=1), winner and support k+1 (B: k=0, so ready on B's first turn).
  const readyOn = Object.fromEntries(s.log.filter(e => e.t === 'recovery').map(e => [e.unit, e.readyOn]));
  assert.deepEqual(readyOn, { [wyvern]: 3, [paladin]: 1, [knight]: 1 });
});
