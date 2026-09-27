// Invariants of the base format (§03). Used by the fuzz tests after every accepted command.
import { adjacent, PLATFORMS } from './board.js';
import { HAND_MAX, SEATS } from './state.js';
import { SIGILS_TO_WIN, TURN_LIMIT } from './engine.js';

export function checkInvariants(s) {
  const bad = [];
  const fail = m => bad.push(m);
  const inDuel = uid => s.duel && (s.duel.attacker === uid || s.duel.defender === uid);

  for (const p of SEATS) {
    const pl = s.players[p];
    if (pl.units.length !== 3) fail(`${p}: колоссов ${pl.units.length}`);
    if (pl.mana < 0) fail(`${p}: мана ${pl.mana}`);
    if (pl.sigils > SIGILS_TO_WIN) fail(`${p}: печатей ${pl.sigils}`);
    const chain = s.duel ? s.duel.chain.filter(c => c.owner === p).map(c => c.card) : [];
    const all = [...pl.deck, ...pl.hand, ...pl.discard, ...chain];
    if (all.length !== 24) fail(`${p}: карт во всех зонах ${all.length}`);
    if (new Set(all).size !== all.length) fail(`${p}: карта в двух зонах`);
    const limit = s.phase === 'choice' && s.choice?.kind === 'discard' ? HAND_MAX + 2 : HAND_MAX;
    if (pl.hand.length > limit) fail(`${p}: рука ${pl.hand.length}`);
  }

  for (const [uid, u] of Object.entries(s.units)) {
    if (!['reserve', 'field', 'exhausted'].includes(u.zone)) fail(`${uid}: зона ${u.zone}`);
    if (u.hold < 0) fail(`${uid}: удержание < 0`);
    if (u.zone === 'field') {
      if (!u.platform || s.board[u.platform].removed) fail(`${uid}: на поле без платформы`);
      else if (s.board[u.platform].unit !== uid && !(inDuel(uid) && s.duel.platform === u.platform)) fail(`${uid}: платформа не знает о колоссе`);
    } else {
      if (u.platform) fail(`${uid}: вне поля, но с платформой`);
      if (u.hold) fail(`${uid}: вне поля, но с удержанием`);
    }
    if (u.zone === 'exhausted' && u.readyOn <= s.players[u.owner].turnIndex && s.phase !== 'ended' && s.active === u.owner && s.turn) {
      fail(`${uid}: должен был вернуться в резерв`);
    }
  }

  let removed = 0;
  for (const q of PLATFORMS) {
    const c = s.board[q];
    if (c.removed) { removed++; if (c.unit) fail(`${q}: захваченная платформа занята`); continue; }
    if (c.unit && (s.units[c.unit].zone !== 'field' || s.units[c.unit].platform !== q)) fail(`${q}: ссылается на ${c.unit}`);
    if (s.phase !== 'setupGates' && !c.gate) fail(`${q}: нет ворот`);
  }
  const sigils = s.players.A.sigils + s.players.B.sigils;
  if (removed !== sigils) fail(`удалено платформ ${removed}, печатей ${sigils}`);

  if (s.duel) {
    const d = s.duel;
    if (s.units[d.attacker].owner === s.units[d.defender].owner) fail('поединок союзников');
    if (s.board[d.platform].unit !== d.defender) fail('защитник не на платформе поединка');
    for (const p of SEATS) {
      const sp = d.support[p];
      if (!sp) continue;
      const u = s.units[sp.unit];
      if (u.owner !== p || u.zone !== 'field' || inDuel(sp.unit) || !adjacent(u.platform, d.platform)) fail(`${p}: неверная поддержка`);
    }
  }
  if (s.turnNo > TURN_LIMIT) fail(`ходов ${s.turnNo}`);
  if (s.result && s.phase !== 'ended') fail('результат без конца матча');
  return bad;
}
