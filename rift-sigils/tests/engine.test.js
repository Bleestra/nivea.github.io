// Stage B acceptance beyond T01-T40: a saved replay gives the same result, random bots never reach an illegal state,
// timeouts behave as §13 says, and hidden simultaneous choices stay hidden.
import { test } from 'node:test';
import { R, assert, act, place, setupMatch, setGate } from './helpers.js';

function playOut(seed, { botA = R.randomBot, botB = R.randomBot, decks, check } = {}) {
  const rng = R.newBotRng(seed);
  const players = decks ?? [{ name: 'A', deck: R.randomDeck(rng) }, { name: 'B', deck: R.randomDeck(rng) }];
  let { record, state } = R.newRecord({ seed, players });
  const bots = { A: botA, B: botB };
  for (let n = 0; !state.result; n++) {
    assert.ok(n < 5000, `партия ${seed} не закончилась`);
    const p = ['A', 'B'].find(x => R.legalActions(state, x).length);
    assert.ok(p, `никто не может ходить: фаза ${state.phase}`);
    const a = bots[p](state, p, rng);
    const r = R.applyRecorded(record, state, { ...a, player: p });
    assert.ok(r.ok, `${seed}: ${p} ${JSON.stringify(a)} отклонено: ${r.error}`);
    state = r.state;
    if (check) check(state, n);
  }
  return { record, state };
}

test('случайные боты: 400 партий без нарушения инвариантов, каждая заканчивается', () => {
  const reasons = {};
  for (let seed = 1; seed <= 400; seed++) {
    const { state } = playOut(seed, {
      check: (s, n) => {
        const bad = R.checkInvariants(s);
        assert.deepEqual(bad, [], `партия ${seed}, команда ${n}`);
      },
    });
    reasons[state.result.reason] = (reasons[state.result.reason] ?? 0) + 1;
  }
  assert.ok(reasons.sigils > 0);
});

test('сохранённый повтор даёт тот же итог и то же состояние', () => {
  for (const seed of [11, 12, 13]) {
    const { record, state } = playOut(seed, { botA: R.simpleBot });
    const again = R.replay(JSON.parse(JSON.stringify(record)));
    assert.equal(R.stateHash(again), R.stateHash(state));
    assert.deepEqual(again.result, state.result);
  }
});

test('простой бот обыгрывает случайного чаще, чем проигрывает', () => {
  let wins = 0, losses = 0;
  for (let seed = 1; seed <= 60; seed++) {
    const simpleIsA = seed % 2 === 0;
    const { state } = playOut(seed, {
      botA: simpleIsA ? R.simpleBot : R.randomBot, botB: simpleIsA ? R.randomBot : R.simpleBot,
      decks: [{ deck: R.PRESET_DECKS.attack }, { deck: R.PRESET_DECKS.control }],
    });
    const w = state.result.winner;
    if (w === (simpleIsA ? 'A' : 'B')) wins++;
    else if (w) losses++;
  }
  assert.ok(wins > losses, `простой ${wins} : случайный ${losses}`);
});

test('тайм-ауты: приоритет — пас, основное решение — отдых, три пропущенных хода — техническое поражение', () => {
  let s = setupMatch();
  place(s, 'Bu1', 'B1');
  s = act(s, 'A', { type: 'launch', unit: 'Au1', platform: 'B1' });
  s = act(s, 'A', { type: 'timeout' });
  assert.equal(s.duel.passes, 1);
  s = act(s, 'B', { type: 'timeout' });
  assert.equal(s.duel, null, 'два паса по тайм-ауту закрывают окно');

  let t = setupMatch();
  for (let i = 0; i < 2; i++) {
    t = act(t, 'A', { type: 'timeout' });
    t = act(t, 'B', { type: 'rest' });
  }
  assert.equal(t.players.A.idleTurns, 2);
  t = act(t, 'A', { type: 'timeout' });
  assert.deepEqual(t.result, { winner: 'B', reason: 'idle' });

  let u = setupMatch();
  u = act(u, 'A', { type: 'timeout' });
  u = act(u, 'B', { type: 'rest' });
  u = act(u, 'A', { type: 'rest' });
  assert.equal(u.players.A.idleTurns, 0, 'ввод сбрасывает счётчик');
});

test('тайный выбор поддержки не виден сопернику до одновременного раскрытия', () => {
  let s = setupMatch();
  place(s, 'Bu1', 'B1');
  place(s, 'Bu2', 'C1');
  place(s, 'Au2', 'A1');
  s = act(s, 'A', { type: 'launch', unit: 'Au1', platform: 'B1' });
  s = act(s, 'B', { type: 'support', unit: 'Bu2' });
  const va = R.viewFor(s, 'A');
  assert.equal(va.duel.supportChoice.B, 'submitted');
  assert.ok(!JSON.stringify(va.duel).includes('Bu2'));
  s = act(s, 'A', { type: 'support', unit: null });
  assert.equal(s.duel.support.B.unit, 'Bu2');
  assert.equal(s.units.Bu2.hold, 0);
});

test('ворота открываются при поединке: Затонувший архив даёт обоим карту, Зал рассвета — Покров', () => {
  let s = setupMatch();
  place(s, 'Bu1', 'B1');
  setGate(s, 'B1', 'RS-G003');
  const [ha, hb] = [s.players.A.hand.length, s.players.B.hand.length];
  s = act(s, 'A', { type: 'launch', unit: 'Au1', platform: 'B1' });
  assert.equal(s.players.A.hand.length, ha + 1);
  assert.equal(s.players.B.hand.length, hb + 1);

  let t = setupMatch();
  place(t, 'Bu1', 'B1');
  setGate(t, 'B1', 'RS-G009');
  t = act(t, 'A', { type: 'launch', unit: 'Au1', platform: 'B1' });
  assert.deepEqual(t.duel.shroud, { Au1: true, Bu1: true });
});
