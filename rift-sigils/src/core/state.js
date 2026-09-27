// Small mutators shared by the engine and ability logic. They work on the clone that apply() owns,
// and every visible change goes to the event list (the Presentation layer only replays events).
import { PLATFORMS } from './board.js';

export const HAND_MAX = 8;
export const SEATS = ['A', 'B'];
export const other = p => (p === 'A' ? 'B' : 'A');

export class BudgetError extends Error {}

export function emit(ctx, ev) {
  const e = { seq: ctx.s.log.length, ...ev };
  ctx.events.push(e);
  ctx.s.log.push(e);
  return e;
}

// GDD §13: more than 128 effect resolutions in one action is a content error, the match is voided.
export function tick(ctx) {
  if (--ctx.budget < 0) throw new BudgetError('resolution limit');
}

export const livePlatforms = s => PLATFORMS.filter(q => !s.board[q].removed);
export const emptyPlatforms = s => livePlatforms(s).filter(q => !s.board[q].unit);
export const fieldUnits = (s, p) => s.players[p].units.filter(u => s.units[u].zone === 'field');

// Копейщик плато has a permanent Anchor while on the field; Крепкий шаг gives a temporary one.
export function hasAnchor(s, uid) {
  const u = s.units[uid];
  return u.zone === 'field' && (u.def === 'RS-C006' || u.anchorUntil !== null);
}

// Draw one card. Over the hand limit the card is revealed and discarded; an empty deck does nothing (§04).
export function draw(ctx, p, { limit = true } = {}) {
  const s = ctx.s, pl = s.players[p];
  if (!pl.deck.length) {
    emit(ctx, { t: 'drawEmpty', player: p });
    return null;
  }
  const cid = pl.deck.shift();
  if (pl.knownTop[0] === cid) pl.knownTop.shift();
  else pl.knownTop = [];
  if (limit && pl.hand.length >= HAND_MAX) {
    pl.discard.push(cid);
    emit(ctx, { t: 'burn', player: p, card: cid, def: s.cards[cid].def });
    return null;
  }
  pl.hand.push(cid);
  emit(ctx, { t: 'draw', player: p, secret: { to: p, card: cid, def: s.cards[cid].def } });
  return cid;
}

export function discardFromHand(ctx, p, cid, why) {
  const pl = ctx.s.players[p];
  pl.hand = pl.hand.filter(c => c !== cid);
  pl.discard.push(cid);
  emit(ctx, { t: 'discard', player: p, card: cid, def: ctx.s.cards[cid].def, why });
}

export function placeOnField(ctx, uid, q) {
  const s = ctx.s, u = s.units[uid];
  u.zone = 'field';
  u.platform = q;
  u.hold = 0;
  u.epoch++;
  s.board[q].unit = uid;
}

// Any movement resets the hold counter, even a forced one (§08, Сдвиг опоры).
export function relocate(ctx, uid, q, how) {
  const s = ctx.s, u = s.units[uid], from = u.platform;
  if (from && s.board[from].unit === uid) s.board[from].unit = null;
  s.board[q].unit = uid;
  u.platform = q;
  u.hold = 0;
  u.epoch++;
  emit(ctx, { t: 'relocate', unit: uid, from, to: q, how });
}

function leaveField(s, uid) {
  const u = s.units[uid];
  if (u.platform && s.board[u.platform].unit === uid) s.board[u.platform].unit = null;
  u.platform = null;
  u.hold = 0;
  u.anchorUntil = null; // a temporary Anchor is removed when the colossus leaves the field
  u.epoch++;
}

export function toReserve(ctx, uid, why) {
  leaveField(ctx.s, uid);
  ctx.s.units[uid].zone = 'reserve';
  emit(ctx, { t: 'toReserve', unit: uid, why });
}

// ready_on_own_turn = k + delta, where k is the owner's last started own turn (0 before the first one).
export function toRecovery(ctx, uid, delta, why) {
  const s = ctx.s, u = s.units[uid];
  leaveField(s, uid);
  u.zone = 'exhausted';
  u.readyOn = s.players[u.owner].turnIndex + delta;
  emit(ctx, { t: 'recovery', unit: uid, readyOn: u.readyOn, why });
}
