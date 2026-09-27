// EffectResolver: each of the 48 abilities translated by hand into typed operations (GDD §20 forbids loading effect
// text into the engine). targets() lists every legal choice at declaration; resolve() re-checks legality and
// returns false when every target became illegal (the card then goes to the discard without effect, §13).
import { ABILITIES, ASPECTS, COLOSSI } from './content.js';
import { adjacent, PLATFORMS } from './board.js';
import {
  enemyOf, fighterOf, isAttacker, power, supportActive, supportChosen,
} from './power.js';
import * as S from './state.js';

const mine = (s, p) => fighterOf(s, p);
const theirs = (s, p) => enemyOf(s, fighterOf(s, p));
const defending = (s, uid) => !isAttacker(s, uid);
const self = () => [{}];

// Numeric modifiers from abilities: source, recipient, amount, removability; all end with the duel (§11).
function addMod(ctx, o, target, amount, { removable = true, linkBound = false } = {}) {
  const d = ctx.s.duel;
  const m = { id: `m${d.nextMod++}`, target, amount, def: o.def, card: o.card, owner: o.owner, removable, linkBound };
  d.mods.push(m);
  S.emit(ctx, { t: 'mod', mod: m.id, unit: target, amount, def: o.def, removable, linkBound });
}

const modsOf = (s, uid, sign) =>
  s.duel.mods.filter(m => m.target === uid && m.removable && (sign > 0 ? m.amount > 0 : m.amount < 0));
const modAlive = (s, id, uid) => s.duel.mods.some(m => m.id === id && m.target === uid && m.removable);

function removeMod(ctx, id) {
  const d = ctx.s.duel, i = d.mods.findIndex(m => m.id === id && m.removable);
  if (i < 0) return false;
  const [m] = d.mods.splice(i, 1);
  S.emit(ctx, { t: 'modRemoved', mod: m.id, unit: m.target, amount: m.amount, def: m.def });
  return true;
}

function giveShroud(ctx, uid) {
  const d = ctx.s.duel;
  if (d.shroud[uid]) return S.emit(ctx, { t: 'shroudAlready', unit: uid }); // at most one charge
  d.shroud[uid] = true;
  S.emit(ctx, { t: 'shroud', unit: uid });
}

function silence(ctx, uid) {
  ctx.s.duel.silenced[uid] = true;
  S.emit(ctx, { t: 'silenced', unit: uid });
}

// The hostile parts of an enemy ability against one fighter (§11). Покров absorbs every negative part of the card;
// otherwise a defending, unsilenced Мудрец глубин ignores the first power reduction of the duel.
function hostile(ctx, o, target, { reduce = 0, silence: mute = false, removeMod: rm = null } = {}) {
  const s = ctx.s, d = s.duel;
  const removable = rm && modAlive(s, rm, target);
  if (!(reduce > 0 || (mute && !d.silenced[target]) || removable)) return;
  if (d.shroud[target]) {
    delete d.shroud[target];
    S.emit(ctx, { t: 'shroudSpent', unit: target, def: o.def });
    return;
  }
  if (reduce > 0 && s.units[target].def === 'RS-C004' && defending(s, target) && !d.silenced[target] && !d.sageUsed) {
    d.sageUsed = true;
    S.emit(ctx, { t: 'sageIgnores', unit: target, amount: reduce, def: o.def });
    reduce = 0;
  }
  if (reduce > 0) addMod(ctx, o, target, -reduce);
  if (mute && !d.silenced[target]) silence(ctx, target);
  if (removable) removeMod(ctx, rm);
}

function counter(ctx, o) {
  const s = ctx.s, d = s.duel, i = d.chain.findIndex(c => c.oid === o.targets.object);
  if (i < 0) return false;
  const [c] = d.chain.splice(i, 1);
  s.players[c.owner].discard.push(c.card);
  S.emit(ctx, { t: 'countered', oid: c.oid, card: c.card, def: c.def, owner: c.owner, by: o.def });
  return true;
}

const boost = f => ({
  targets: self,
  resolve(ctx, o) {
    addMod(ctx, o, mine(ctx.s, o.owner), f(ctx.s, o.owner));
    return true;
  },
});

const rosterAspects = (s, p) => ASPECTS.filter(a => s.players[p].units.some(u => COLOSSI[s.units[u].def].aspect === a));
const pairs = xs => xs.flatMap((a, i) => xs.slice(i + 1).map(b => [a, b].sort()));
const moveTargets = (s, units, near) => units.flatMap(u =>
  S.emptyPlatforms(s).filter(q => !near || adjacent(q, s.units[u].platform)).map(q => ({ unit: u, platform: q })));
const relocateVoluntary = {
  resolve(ctx, o) {
    const u = ctx.s.units[o.targets.unit];
    if (u.zone !== 'field' || ctx.s.board[o.targets.platform].unit || ctx.s.board[o.targets.platform].removed) return false;
    S.relocate(ctx, o.targets.unit, o.targets.platform, 'voluntary');
    return true;
  },
};

export const LOGIC = {
  // ---- Жар
  'RS-A001': boost(() => 3),
  'RS-A002': boost((s, p) => (isAttacker(s, mine(s, p)) ? 6 : 4)),
  'RS-A003': {
    targets: self,
    resolve(ctx, o) {
      addMod(ctx, o, mine(ctx.s, o.owner), 3);
      hostile(ctx, o, theirs(ctx.s, o.owner), { reduce: 2 });
      return true;
    },
  },
  'RS-A004': {
    targets: (s, p) => [{ mod: null }, ...modsOf(s, mine(s, p), -1).map(m => ({ mod: m.id }))],
    resolve(ctx, o) {
      const u = mine(ctx.s, o.owner);
      if (o.targets.mod && modAlive(ctx.s, o.targets.mod, u)) removeMod(ctx, o.targets.mod);
      addMod(ctx, o, u, 2);
      return true;
    },
  },
  'RS-A005': boost((s, p) => (s.players[S.other(p)].sigils >= 2 ? 8 : 5)),
  // The previous own ability that actually resolved in this duel, whatever the opponent played in between.
  'RS-A006': boost((s, p) => {
    const h = s.duel.history[p];
    return h.length && ABILITIES[h[h.length - 1]].aspect === 'fire' ? 4 : 2;
  }),

  // ---- Прилив
  'RS-A007': {
    targets: (s, p) => modsOf(s, theirs(s, p), +1).map(m => ({ mod: m.id })),
    resolve(ctx, o) {
      const t = theirs(ctx.s, o.owner);
      if (!modAlive(ctx.s, o.targets.mod, t)) return false;
      hostile(ctx, o, t, { removeMod: o.targets.mod });
      return true;
    },
  },
  'RS-A008': {
    targets: self,
    resolve(ctx, o) {
      const u = mine(ctx.s, o.owner);
      addMod(ctx, o, u, 2);
      giveShroud(ctx, u);
      return true;
    },
  },
  'RS-A009': { targets: (s, p) => moveTargets(s, S.fieldUnits(s, p), false), ...relocateVoluntary },
  'RS-A010': {
    targets: self,
    resolve(ctx, o) {
      hostile(ctx, o, theirs(ctx.s, o.owner), { reduce: 4 });
      return true;
    },
  },
  'RS-A011': {
    targets: (s, p) => rosterAspects(s, p).map(a => ({ aspect: a })),
    resolve(ctx, o) {
      const u = mine(ctx.s, o.owner);
      ctx.s.duel.aspect[u] = o.targets.aspect;
      S.emit(ctx, { t: 'aspect', unit: u, aspect: o.targets.aspect });
      return true;
    },
  },
  // One positive modifier from each fighter where there is one; at least one must exist.
  'RS-A012': {
    targets(s, p) {
      const own = modsOf(s, mine(s, p), +1).map(m => m.id), foe = modsOf(s, theirs(s, p), +1).map(m => m.id);
      const out = [];
      for (const a of own.length ? own : [null]) for (const b of foe.length ? foe : [null]) if (a || b) out.push({ own: a, enemy: b });
      return out;
    },
    resolve(ctx, o) {
      const s = ctx.s, u = mine(s, o.owner), t = theirs(s, o.owner);
      const okOwn = o.targets.own && modAlive(s, o.targets.own, u), okFoe = o.targets.enemy && modAlive(s, o.targets.enemy, t);
      if (okOwn) removeMod(ctx, o.targets.own);
      if (okFoe) hostile(ctx, o, t, { removeMod: o.targets.enemy });
      return !!(okOwn || okFoe);
    },
  },

  // ---- Камень
  'RS-A013': boost((s, p) => (defending(s, mine(s, p)) ? 3 : 2)),
  'RS-A014': {
    targets: self,
    resolve(ctx, o) {
      const u = mine(ctx.s, o.owner);
      addMod(ctx, o, u, 4);
      if (supportChosen(ctx.s, o.owner)) addMod(ctx, o, u, 1, { linkBound: true });
      return true;
    },
  },
  'RS-A015': {
    targets: self,
    resolve(ctx, o) {
      const u = mine(ctx.s, o.owner);
      giveShroud(ctx, u);
      addMod(ctx, o, u, 3);
      return true;
    },
  },
  'RS-A016': {
    targets: self,
    resolve(ctx, o) {
      hostile(ctx, o, theirs(ctx.s, o.owner), { reduce: 3, silence: true });
      return true;
    },
  },
  'RS-A017': {
    targets: (s, p) => S.fieldUnits(s, p).map(u => ({ unit: u })),
    resolve(ctx, o) {
      const u = ctx.s.units[o.targets.unit];
      if (u.zone !== 'field') return false;
      u.anchorUntil = ctx.s.turnNo + 1; // the opponent's next turn always follows this one
      S.emit(ctx, { t: 'anchor', unit: o.targets.unit, until: u.anchorUntil });
      return true;
    },
  },
  'RS-A018': boost((s, p) => (defending(s, mine(s, p)) ? 7 : 4)),

  // ---- Ветер
  'RS-A019': { targets: (s, p) => moveTargets(s, S.fieldUnits(s, p), true), ...relocateVoluntary },
  'RS-A020': boost((s, p) => (supportActive(s, p) ? 4 : 2)),
  'RS-A021': {
    targets(s, p) {
      const sp = s.duel.support[S.other(p)];
      return sp && !sp.suppressed ? [{}] : [];
    },
    resolve(ctx, o) {
      const sp = ctx.s.duel.support[S.other(o.owner)];
      if (!sp || sp.suppressed) return false;
      sp.suppressed = true;
      S.emit(ctx, { t: 'linkSuppressed', player: S.other(o.owner), unit: sp.unit });
      return true;
    },
  },
  'RS-A022': boost((s, p) => (isAttacker(s, mine(s, p)) && s.duel.viaMove ? 5 : 3)),
  'RS-A023': {
    targets: (s, p) => modsOf(s, mine(s, p), -1).map(m => ({ mod: m.id })),
    resolve(ctx, o) {
      if (!modAlive(ctx.s, o.targets.mod, mine(ctx.s, o.owner))) return false;
      return removeMod(ctx, o.targets.mod);
    },
  },
  'RS-A024': {
    targets: (s, p) => pairs(S.fieldUnits(s, p)).map(units => ({ units })),
    resolve(ctx, o) {
      const s = ctx.s, [a, b] = o.targets.units, ua = s.units[a], ub = s.units[b];
      if (ua.zone !== 'field' || ub.zone !== 'field') return false;
      const qa = ua.platform, qb = ub.platform;
      s.board[qa].unit = b; s.board[qb].unit = a;
      ua.platform = qb; ub.platform = qa;
      ua.hold = 0; ub.hold = 0; ua.epoch++; ub.epoch++;
      S.emit(ctx, { t: 'swap', units: [a, b], platforms: [qb, qa] });
      return true;
    },
  },

  // ---- Свет
  'RS-A025': {
    targets: self,
    resolve(ctx, o) {
      giveShroud(ctx, mine(ctx.s, o.owner));
      return true;
    },
  },
  // Removes Немота if present and, when the fighter has negative modifiers, exactly one of them.
  'RS-A026': {
    targets(s, p) {
      const u = mine(s, p), negs = modsOf(s, u, -1).map(m => ({ mod: m.id }));
      if (negs.length) return negs;
      return s.duel.silenced[u] ? [{ mod: null }] : [];
    },
    resolve(ctx, o) {
      const s = ctx.s, u = mine(s, o.owner);
      let any = false;
      if (s.duel.silenced[u]) {
        delete s.duel.silenced[u];
        S.emit(ctx, { t: 'unsilenced', unit: u });
        any = true;
      }
      if (o.targets.mod && modAlive(s, o.targets.mod, u)) any = removeMod(ctx, o.targets.mod) || any;
      return any;
    },
  },
  'RS-A027': boost((s, p) => (defending(s, mine(s, p)) ? 5 : 4)),
  // Restoring an enemy's aspect is hostile only if it lowers that fighter's power; then Покров absorbs it.
  'RS-A028': {
    targets: s => [{ unit: s.duel.attacker }, { unit: s.duel.defender }],
    resolve(ctx, o) {
      const s = ctx.s, d = s.duel, u = o.targets.unit;
      if (!(u in d.aspect)) {
        S.emit(ctx, { t: 'aspectAlreadyBase', unit: u });
        return true;
      }
      if (s.units[u].owner !== o.owner && d.shroud[u]) {
        const before = power(s, u), saved = d.aspect[u];
        delete d.aspect[u];
        const after = power(s, u);
        d.aspect[u] = saved;
        if (after < before) {
          delete d.shroud[u];
          S.emit(ctx, { t: 'shroudSpent', unit: u, def: o.def });
          return true;
        }
      }
      delete d.aspect[u];
      S.emit(ctx, { t: 'aspect', unit: u, aspect: COLOSSI[s.units[u].def].aspect, restored: true });
      return true;
    },
  },
  'RS-A029': boost((s, p) => {
    const sp = s.duel.support[p];
    const differs = supportActive(s, p) &&
      COLOSSI[s.units[sp.unit].def].aspect !== COLOSSI[s.units[mine(s, p)].def].aspect;
    return differs ? 5 : 3;
  }),
  // Cannot make a colossus ready before the current own turn; reaching it moves the colossus to the ready reserve.
  'RS-A030': {
    targets: (s, p) => s.players[p].units.filter(u => s.units[u].zone === 'exhausted').map(u => ({ unit: u })),
    resolve(ctx, o) {
      const s = ctx.s, u = s.units[o.targets.unit], k = s.players[o.owner].turnIndex;
      if (u.zone !== 'exhausted') return false;
      u.readyOn = Math.max(k, u.readyOn - 1);
      S.emit(ctx, { t: 'recoveryShortened', unit: o.targets.unit, readyOn: u.readyOn });
      if (u.readyOn <= k) {
        u.zone = 'reserve';
        S.emit(ctx, { t: 'ready', unit: o.targets.unit });
      }
      return true;
    },
  },

  // ---- Тень
  'RS-A031': {
    targets: self,
    resolve(ctx, o) {
      hostile(ctx, o, theirs(ctx.s, o.owner), { reduce: 3 });
      addMod(ctx, o, mine(ctx.s, o.owner), 3);
      return true;
    },
  },
  'RS-A032': {
    targets: self,
    resolve(ctx, o) {
      hostile(ctx, o, theirs(ctx.s, o.owner), { silence: true });
      return true;
    },
  },
  // Removing Покров itself is not blocked by that Покров; removing a modifier is (it worsens the fighter).
  'RS-A033': {
    targets(s, p) {
      const t = theirs(s, p), out = modsOf(s, t, +1).map(m => ({ mod: m.id }));
      if (s.duel.shroud[t]) out.unshift({ shroud: true });
      return out;
    },
    resolve(ctx, o) {
      const s = ctx.s, t = theirs(s, o.owner);
      if (o.targets.shroud) {
        if (!s.duel.shroud[t]) return false;
        delete s.duel.shroud[t];
        S.emit(ctx, { t: 'shroudRemoved', unit: t });
        return true;
      }
      if (!modAlive(s, o.targets.mod, t)) return false;
      hostile(ctx, o, t, { removeMod: o.targets.mod });
      return true;
    },
  },
  'RS-A034': {
    targets: self,
    resolve(ctx, o) {
      const t = theirs(ctx.s, o.owner);
      hostile(ctx, o, t, { reduce: COLOSSI[ctx.s.units[t].def].base >= 15 ? 6 : 3 });
      return true;
    },
  },
  'RS-A035': {
    targets: (s, p) => PLATFORMS.filter(q => {
      const c = s.board[q];
      return !c.removed && c.gate && s.gates[c.gate].owner !== p && !s.gates[c.gate].revealed;
    }).map(q => ({ platform: q })),
    resolve(ctx, o) {
      const s = ctx.s, g = s.gates[s.board[o.targets.platform].gate];
      if (!g.seenBy.includes(o.owner)) g.seenBy.push(o.owner);
      S.emit(ctx, { t: 'scout', player: o.owner, platform: o.targets.platform, secret: { to: o.owner, gateDef: g.def } });
      return true;
    },
  },
  // The printed base cost is checked, not the cost after discounts (§10).
  'RS-A036': {
    targets: (s, p) => s.duel.chain.filter(c => c.owner !== p && ABILITIES[c.def].cost <= 2).map(c => ({ object: c.oid })),
    resolve: counter,
  },

  // ---- Нейтральные
  'RS-A037': boost(() => 2),
  'RS-A038': boost(() => 4),
  'RS-A039': {
    targets: self,
    resolve(ctx, o) {
      S.draw(ctx, o.owner, { limit: false });
      S.draw(ctx, o.owner, { limit: false });
      if (ctx.s.players[o.owner].hand.length) ctx.s.choice = { player: o.owner, kind: 'discard', def: o.def };
      return true;
    },
  },
  'RS-A040': {
    targets: (s, p) => moveTargets(s, S.fieldUnits(s, S.other(p)), true),
    resolve(ctx, o) {
      const s = ctx.s, u = o.targets.unit;
      if (s.units[u].zone !== 'field' || s.board[o.targets.platform].unit) return false;
      if (S.hasAnchor(s, u)) {
        S.emit(ctx, { t: 'anchorHeld', unit: u });
        return true;
      }
      S.relocate(ctx, u, o.targets.platform, 'forced');
      return true;
    },
  },
  'RS-A041': {
    targets: (s, p) => s.duel.chain.filter(c => c.owner !== p).map(c => ({ object: c.oid })),
    resolve: counter,
  },
  'RS-A042': boost((s, p) => (supportActive(s, p) ? 3 : 5)),
  'RS-A043': {
    targets: self,
    resolve(ctx) {
      ctx.s.duel.aspectBonusOff = true;
      S.emit(ctx, { t: 'gateBonusesOff', platform: ctx.s.duel.platform });
      return true;
    },
  },
  'RS-A044': {
    targets: (s, p, card) => s.players[p].hand.filter(c => c !== card).map(c => ({ discard: c })),
    resolve(ctx, o) {
      if (!ctx.s.players[o.owner].hand.includes(o.targets.discard)) return false;
      S.discardFromHand(ctx, o.owner, o.targets.discard, o.def);
      S.draw(ctx, o.owner);
      S.draw(ctx, o.owner);
      return true;
    },
  },
  'RS-A045': {
    targets: (s, p) => (defending(s, mine(s, p)) ? [{}] : []),
    resolve(ctx, o) {
      const u = mine(ctx.s, o.owner);
      if (!defending(ctx.s, u)) return false;
      addMod(ctx, o, u, 3);
      return true;
    },
  },
  'RS-A046': {
    targets: self,
    resolve(ctx, o) {
      addMod(ctx, o, mine(ctx.s, o.owner), 6, { removable: false });
      return true;
    },
  },
  'RS-A047': {
    targets: (s, p) => S.fieldUnits(s, p).map(u => ({ unit: u })),
    resolve(ctx, o) {
      if (ctx.s.units[o.targets.unit].zone !== 'field') return false;
      S.toReserve(ctx, o.targets.unit, o.def);
      return true;
    },
  },
  'RS-A048': {
    targets: self,
    resolve(ctx, o) {
      const pl = ctx.s.players[o.owner], top = pl.deck.slice(0, 3);
      if (top.length) ctx.s.choice = { player: o.owner, kind: 'arrange', cards: top, def: o.def };
      return true;
    },
  },
};
