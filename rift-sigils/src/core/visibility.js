// VisibilityFilter (§06, §20): what a client of one seat is allowed to receive. Hidden cards are not sent at all —
// not even their instance ids: the opponent's hand and both decks are counts, unknown gates carry only an owner.
import { PLATFORMS } from './board.js';
import { breakdown } from './power.js';
import { other, SEATS } from './state.js';

export function eventFor(e, viewer) {
  if (!e.secret) return e;
  const { secret, ...pub } = e;
  if (secret.to !== viewer) return pub;
  const { to, ...data } = secret;
  return { ...pub, ...data };
}

export function viewFor(s, viewer) {
  const opp = other(viewer);
  const cardRef = c => ({ card: c, def: s.cards[c].def });
  const players = {};
  for (const p of SEATS) {
    const pl = s.players[p];
    players[p] = {
      name: pl.name, mana: pl.mana, sigils: pl.sigils, turnIndex: pl.turnIndex, idleTurns: pl.idleTurns,
      units: pl.units.slice(), handCount: pl.hand.length, deckCount: pl.deck.length,
      discard: pl.discard.map(cardRef), gatesToPlaceCount: pl.gatesToPlace.length,
    };
    if (p === viewer) {
      players[p].hand = pl.hand.map(cardRef);
      players[p].gatesToPlace = pl.gatesToPlace.map(g => ({ gate: g, def: s.gates[g].def }));
      players[p].knownTop = pl.knownTop.map(cardRef);
    }
  }
  const board = {};
  for (const q of PLATFORMS) {
    const c = s.board[q];
    let gate = null;
    if (c.gate) {
      const g = s.gates[c.gate], seen = g.seenBy.includes(viewer);
      gate = g.revealed || g.owner === viewer || seen
        ? { gate: c.gate, def: g.def, owner: g.owner, revealed: g.revealed, scouted: seen && !g.revealed }
        : { owner: g.owner, revealed: false };
    }
    board[q] = { removed: c.removed, unit: c.unit, gate };
  }
  let duel = null;
  if (s.duel) {
    const { supportChoice, ...rest } = s.duel;
    duel = structuredClone(rest);
    duel.supportChoice = {
      [viewer]: supportChoice[viewer],
      [opp]: supportChoice[opp] === 'pending' ? 'pending' : 'submitted',
    };
    // Everything in the breakdown is public, so the client shows the decomposition without evaluating rules.
    duel.power = { [s.duel.attacker]: breakdown(s, s.duel.attacker), [s.duel.defender]: breakdown(s, s.duel.defender) };
  }
  return {
    rulesVersion: s.rulesVersion, contentHash: s.contentHash, matchId: s.matchId, revision: s.revision, viewer,
    phase: s.phase, round: s.round, active: s.active, turnNo: s.turnNo, result: s.result,
    setup: { step: s.setup.step },
    mulligan: s.phase === 'mulligan' ? { mine: s.mulligan[viewer], opponentReady: !!s.mulligan[opp] } : null,
    turn: s.turn ? { prepPlayed: s.turn.prepPlayed } : null,
    choice: s.choice
      ? (s.choice.player === viewer
        ? { ...structuredClone(s.choice), cards: (s.choice.cards ?? []).map(c => ({ card: c, def: s.cards[c].def })) }
        : { player: s.choice.player, kind: s.choice.kind })
      : null,
    players, units: structuredClone(s.units), board, duel,
    log: s.log.map(e => eventFor(e, viewer)),
  };
}
