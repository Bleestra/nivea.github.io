// PresentationBridge: plays engine events as animations, then reconciles the scene with the final public view.
// Animations only show what the rules already decided (GDD §01): they never change an outcome.
import * as THREE from 'three';
import { ABILITIES, ASPECT_NAMES, COLOSSI, GATES } from '../core/index.js';
import { Colossus } from './colossi.js';
import { ASPECT_GLOW, OWNER_GLOW } from './fx.js';
import { ease } from './world.js';
import { signed } from '../web/text.js';

const DUEL_OFFSET = 4.2;
const SHORT = {
  'RS-C001': 'Виверн', 'RS-C002': 'Рыцарь', 'RS-C003': 'Левиафан', 'RS-C004': 'Мудрец', 'RS-C005': 'Титан', 'RS-C006': 'Копейщик',
  'RS-C007': 'Грифон', 'RS-C008': 'Дуэлянт', 'RS-C009': 'Паладин', 'RS-C010': 'Птица', 'RS-C011': 'Охотник', 'RS-C012': 'Хранитель',
};

export class Director {
  constructor({ world, fx, field, hud, sfx, settings }) {
    Object.assign(this, { world, fx, field, hud, sfx, settings });
    this.units = new Map();
    this.duel = null;
    this.viewer = 'A';
  }

  side(p) { return p === this.viewer ? 'me' : 'foe'; }
  get dyn() { return this.settings().camera; }

  // ---------------------------------------------------------------- unit models

  spawn(uid, def, owner) {
    const m = new Colossus(this.world, COLOSSI[def], { ownerColor: OWNER_GLOW[this.side(owner)] });
    m.root.rotation.y = this.side(owner) === 'me' ? Math.PI : 0;
    m.root.traverse(o => { o.userData.unit = uid; });
    this.world.scene.add(m.root);
    const u = { uid, def, owner, model: m, platform: null, extras: {} };
    this.units.set(uid, u);
    this.hud.trackUnit(uid, m.head, this.side(owner));
    this.hud.setUnitBadge(uid, { name: SHORT[def] });
    return u;
  }

  drop(uid) {
    const u = this.units.get(uid);
    if (!u) return;
    for (const x of Object.values(u.extras)) x?.remove?.();
    u.model.dispose();
    this.hud.untrackUnit(uid);
    this.units.delete(uid);
  }

  // Where a colossus stands: the card centre, or in a duel your fighter on the near half and the other on the far half.
  slot(uid, platform) {
    const p = this.field.pos(platform);
    const d = this.duel;
    const u = this.units.get(uid);
    if (d && d.platform === platform && (uid === d.attacker || uid === d.defender)) {
      p.z += (this.side(u?.owner ?? this.viewer) === 'me' ? 1 : -1) * DUEL_OFFSET;
    }
    return p;
  }

  pickables() { return [...this.units.values()].map(u => u.model.root); }

  async glide(uid, to, { height = 5, duration = 0.7, forced = false } = {}) {
    const u = this.units.get(uid);
    if (!u) return;
    const from = u.model.root.position.clone();
    await this.world.tween(duration, (e, t) => {
      u.model.root.position.lerpVectors(from, to, e);
      u.model.root.position.y = Math.sin(Math.PI * t) * height;
      if (forced) u.model.root.rotation.z = Math.sin(t * Math.PI * 4) * 0.08 * (1 - t);
    }, ease.inOutCubic);
    u.model.root.position.copy(to);
    u.model.root.rotation.z = 0;
  }

  // ---------------------------------------------------------------- whole-scene reconcile

  reset(v) {
    for (const uid of [...this.units.keys()]) this.drop(uid);
    this.viewer = v.viewer;
    this.duel = null;
    this.field.layout(v.viewer);
    this.world.goOverview(true);
    this.sync(v);
  }

  sync(v) {
    this.field.sync(v);
    const d = v.duel;
    this.duel = d ? { platform: d.platform, attacker: d.attacker, defender: d.defender } : null;
    for (const [uid, unit] of Object.entries(v.units)) {
      if (unit.zone !== 'field') { if (this.units.has(uid)) this.drop(uid); continue; }
      const u = this.units.get(uid) ?? this.spawn(uid, unit.def, unit.owner);
      u.platform = unit.platform;
      u.model.root.position.copy(this.slot(uid, unit.platform));
      u.model.setAspect(d?.aspect?.[uid] ?? COLOSSI[unit.def].aspect);
      // duel statuses
      const inDuel = d && (uid === d.attacker || uid === d.defender);
      const wantShroud = inDuel && d.shroud[uid];
      if (wantShroud && !u.extras.shroud) u.extras.shroud = this.fx.bubble(u.model.root, 0xbfe9ff);
      if (!wantShroud && u.extras.shroud) { u.extras.shroud.remove(); u.extras.shroud = null; }
      const wantMute = inDuel && d.silenced[uid];
      if (wantMute && !u.extras.mute) u.extras.mute = this.fx.chains(u.model.root);
      if (!wantMute && u.extras.mute) { u.extras.mute.remove(false); u.extras.mute = null; }
      const sp = d && Object.entries(d.support).find(([, x]) => x?.unit === uid);
      const wantBeam = sp && !sp[1].suppressed;
      if (wantBeam && !u.extras.beam) {
        const fighter = this.units.get(v.units[d.attacker].owner === unit.owner ? d.attacker : d.defender);
        if (fighter) u.extras.beam = this.fx.beam(u.model.anchor, fighter.model.anchor, OWNER_GLOW[this.side(unit.owner)]);
      }
      if (!wantBeam && u.extras.beam) { u.extras.beam.remove(); u.extras.beam = null; }
      this.hud.setUnitBadge(uid, { hold: unit.hold, anchor: unit.def === 'RS-C006' || unit.anchorUntil !== null, fighter: !!inDuel });
    }
    if (!d && this.world.focused) this.world.goOverview();
  }

  // ---------------------------------------------------------------- events

  async play(events, v) {
    this.v = v;
    for (const e of events) {
      try {
        await this.handle(e, v);
      } catch (err) {
        console.error('animation', e.t, err);
      }
    }
    this.sync(v);
  }

  popup(uid, text, cls) {
    const u = this.units.get(uid);
    if (u) this.hud.popupAt(u.model.head, text, cls);
  }

  async handle(e, v) {
    const W = this.world, fx = this.fx, sfx = this.sfx;
    const speed = 1;
    switch (e.t) {
      case 'gatePlaced': {
        sfx.play('whoosh');
        const own = this.side(e.player);
        await this.field.throwCard(e.platform, own, e.gateDef ? `ваши: ${GATES[e.gateDef].name}` : '', speed);
        sfx.play('land');
        break;
      }
      case 'roundStart':
        if (e.round > 1) await this.hud.banner(`Раунд ${e.round}`, `мана ${e.mana}`, 0.9);
        break;
      case 'turnStart':
        sfx.play('turn');
        await this.hud.banner(e.player === this.viewer ? 'Ваш ход' : `Ход: ${v.players[e.player].name}`, `ход ${e.turnNo} из 36`, 0.8);
        break;
      case 'launch': {
        const unit = v.units[e.unit];
        const u = this.spawn(e.unit, unit.def, e.player);
        u.model.root.visible = false;
        u.platform = e.platform;
        const target = this.field.pos(e.platform);
        u.model.root.position.copy(target);
        const enemy = [...this.units.values()].find(x => x.platform === e.platform && x.uid !== e.unit && x.owner !== e.player);
        if (enemy) {
          this.duel = { platform: e.platform, attacker: e.unit, defender: enemy.uid };
          target.copy(this.slot(e.unit, e.platform));
          this.glide(enemy.uid, this.slot(enemy.uid, e.platform), { height: 0.6, duration: 0.5 });
        }
        const near = this.side(e.player) === 'me';
        const from = new THREE.Vector3(near ? 4 : -4, 7, near ? 34 : -34);
        sfx.play('whoosh');
        await fx.seal(from, target, OWNER_GLOW[this.side(e.player)]);
        sfx.play('land');
        sfx.play('summon');
        u.model.root.position.copy(target);
        u.model.root.visible = true;
        fx.pillar(target, ASPECT_GLOW[COLOSSI[unit.def].aspect], { height: 24, radius: 3, duration: 1.1 });
        await u.model.assemble();
        break;
      }
      case 'move': {
        const u = this.units.get(e.unit);
        if (!u) break;
        u.platform = e.to;
        const enemy = [...this.units.values()].find(x => x.platform === e.to && x.uid !== e.unit && x.owner !== u.owner);
        if (enemy) {
          this.duel = { platform: e.to, attacker: e.unit, defender: enemy.uid };
          this.glide(enemy.uid, this.slot(enemy.uid, e.to), { height: 0.6, duration: 0.5 });
        }
        sfx.play('whoosh');
        await this.glide(e.unit, this.slot(e.unit, e.to), { height: e.cost ? 9 : 5, duration: e.cost ? 0.9 : 0.7 });
        sfx.play('land');
        fx.ring(this.field.pos(e.to), OWNER_GLOW[this.side(u.owner)], { radius: 7, duration: 0.5 });
        break;
      }
      case 'relocate': {
        const u = this.units.get(e.unit);
        if (!u) break;
        u.platform = e.to;
        sfx.play(e.how === 'forced' ? 'debuff' : 'whoosh');
        if (e.how === 'forced') fx.emit(u.model.root.position.clone().setY(2), 40, { color: 0xffffff, speed: 8, life: 0.5 });
        await this.glide(e.unit, this.field.pos(e.to), { height: e.how === 'forced' ? 2 : 5, duration: 0.65, forced: e.how === 'forced' });
        this.hud.setUnitBadge(e.unit, { hold: 0 });
        break;
      }
      case 'swap': {
        const [a, b] = e.units;
        const ua = this.units.get(a), ub = this.units.get(b);
        if (ua && ub) {
          [ua.platform, ub.platform] = [e.platforms[0], e.platforms[1]];
          sfx.play('whoosh');
          await Promise.all([this.glide(a, this.field.pos(e.platforms[0]), { height: 6 }), this.glide(b, this.field.pos(e.platforms[1]), { height: 3 })]);
        }
        break;
      }
      case 'toReserve': {
        const u = this.units.get(e.unit);
        if (!u) break;
        await u.model.dissolve(fx, { color: OWNER_GLOW[this.side(u.owner)], up: true });
        this.drop(e.unit);
        break;
      }
      case 'recovery': {
        const u = this.units.get(e.unit);
        if (!u) break;
        const lost = e.why === 'lost' || e.why === 'lost-bird';
        await u.model.dissolve(fx, { color: lost ? 0xff4a3a : ASPECT_GLOW[COLOSSI[u.def].aspect], up: !lost });
        this.drop(e.unit);
        break;
      }
      case 'duelStart': {
        this.duel = { platform: e.platform, attacker: e.attacker, defender: e.defender };
        if (this.dyn) W.focus(this.field.pos(e.platform));
        await this.hud.banner(`Поединок на ${e.platform}`, e.viaMove ? 'атака перемещением' : 'ворота открываются', 0.7);
        break;
      }
      case 'gateRevealed': {
        sfx.play('reveal');
        await this.field.reveal(e.platform, e.gateDef, this.side(e.owner), speed);
        this.hud.toast(`${GATES[e.gateDef].name}: ${GATES[e.gateDef].rule}`, 2600);
        break;
      }
      case 'shroud': {
        const u = this.units.get(e.unit);
        if (u && !u.extras.shroud) { u.extras.shroud = fx.bubble(u.model.root, 0xbfe9ff); sfx.play('shield'); }
        this.popup(e.unit, 'Покров', 'good');
        await W.wait(0.35);
        break;
      }
      case 'supportRevealed': {
        for (const p of ['A', 'B']) {
          const s = e[p];
          if (!s || !this.duel) continue;
          const su = this.units.get(s), fighterId = v.units[this.duel.attacker].owner === p ? this.duel.attacker : this.duel.defender;
          const f = this.units.get(fighterId);
          if (su && f && !su.extras.beam) {
            su.extras.beam = fx.beam(su.model.anchor, f.model.anchor, OWNER_GLOW[this.side(p)]);
            this.popup(s, 'поддержка +2', 'good');
          }
        }
        if (e.A || e.B) { sfx.play('buff'); await W.wait(0.5); }
        break;
      }
      case 'play':
        sfx.play('card');
        await this.hud.showPlayedCard(e, this.side(e.player));
        break;
      case 'prep':
        sfx.play('card');
        await this.hud.showPlayedCard({ ...e, oid: null }, this.side(e.player));
        break;
      case 'pass':
        sfx.play('pass');
        this.hud.passBubble(this.side(e.player));
        await W.wait(0.2);
        break;
      case 'resolve':
        this.hud.pulseChain(e.oid);
        await W.wait(0.25);
        break;
      case 'mod': {
        const u = this.units.get(e.unit);
        if (!u) break;
        const pos = e.amount > 0;
        fx.aura(u.model.root, pos ? ASPECT_GLOW[COLOSSI[u.def].aspect] : 0x8a3cff, pos);
        sfx.play(pos ? 'buff' : 'debuff');
        this.popup(e.unit, signed(e.amount), pos ? 'good' : 'bad');
        await W.wait(0.55);
        break;
      }
      case 'modRemoved':
        this.popup(e.unit, `снято ${signed(e.amount)}`, 'info');
        sfx.play('break');
        await W.wait(0.4);
        break;
      case 'shroudAlready':
        this.popup(e.unit, 'Покров уже есть', 'info');
        break;
      case 'shroudSpent':
      case 'shroudRemoved': {
        const u = this.units.get(e.unit);
        if (u?.extras.shroud) { await u.extras.shroud.shatter(); u.extras.shroud = null; }
        sfx.play('break');
        this.popup(e.unit, e.t === 'shroudSpent' ? 'Покров поглотил' : 'Покров снят', 'info');
        await W.wait(0.2);
        break;
      }
      case 'sageIgnores': {
        const u = this.units.get(e.unit);
        if (u) fx.ring(u.model.root.position, ASPECT_GLOW.tide, { radius: 6, duration: 0.5 });
        this.popup(e.unit, `игнор −${e.amount}`, 'good');
        sfx.play('shield');
        await W.wait(0.45);
        break;
      }
      case 'silenced': {
        const u = this.units.get(e.unit);
        if (u && !u.extras.mute) u.extras.mute = fx.chains(u.model.root);
        sfx.play('silence');
        this.popup(e.unit, 'Немота', 'bad');
        await W.wait(0.45);
        break;
      }
      case 'unsilenced': {
        const u = this.units.get(e.unit);
        if (u?.extras.mute) { await u.extras.mute.remove(true); u.extras.mute = null; }
        this.popup(e.unit, 'Немота снята', 'good');
        break;
      }
      case 'aspect': {
        const u = this.units.get(e.unit);
        if (u) {
          u.model.setAspect(e.aspect);
          fx.aura(u.model.root, ASPECT_GLOW[e.aspect], true);
        }
        this.popup(e.unit, ASPECT_NAMES[e.aspect], 'info');
        sfx.play('buff');
        await W.wait(0.5);
        break;
      }
      case 'linkSuppressed': {
        const u = this.units.get(e.unit);
        if (u?.extras.beam) { await u.extras.beam.break(); u.extras.beam = null; }
        this.popup(e.unit, 'связь подавлена', 'bad');
        sfx.play('break');
        break;
      }
      case 'countered':
        sfx.play('counter');
        await this.hud.shatterChain(e.oid);
        break;
      case 'gateBonusesOff':
        this.hud.popupAt(this.field.cards[e.platform].holder, 'бонусы ворот отключены', 'info');
        await W.wait(0.5);
        break;
      case 'fizzle':
        this.hud.toast(`«${ABILITIES[e.def].name}»: без эффекта, цели больше нет`, 1800);
        break;
      case 'clash':
        await this.clash(e);
        break;
      case 'sigil': {
        const col = OWNER_GLOW[this.side(e.player)];
        sfx.play('sigil');
        const holder = this.field.cards[e.platform].holder;
        this.hud.flySigil(holder, this.side(e.player));
        await this.field.shatter(e.platform, col, speed);
        break;
      }
      case 'duelEnd':
        for (const u of this.units.values()) {
          for (const k of ['shroud', 'mute', 'beam']) { u.extras[k]?.remove?.(); u.extras[k] = null; }
        }
        this.duel = null;
        if (this.world.focused) this.world.goOverview();
        break;
      case 'anchor':
        this.popup(e.unit, 'Якорь', 'info');
        { const u = this.units.get(e.unit); if (u) fx.ring(u.model.root.position, 0xffa53a, { radius: 5, duration: 0.6 }); }
        await W.wait(0.3);
        break;
      case 'anchorHeld':
        this.popup(e.unit, 'Якорь удержал', 'good');
        W.shake(0.4);
        await W.wait(0.4);
        break;
      case 'scout':
        fx.ring(this.field.pos(e.platform), ASPECT_GLOW.shadow, { radius: 8, duration: 0.7 });
        this.hud.popupAt(this.field.cards[e.platform].holder, e.gateDef ? GATES[e.gateDef].name : 'разведка', 'info');
        await W.wait(0.5);
        break;
      case 'burn':
        this.hud.toast(`Рука полна: «${ABILITIES[e.def].name}» сгорает`, 1800);
        break;
      case 'rest':
        this.hud.toast(e.player === this.viewer ? 'Вы отдыхаете' : `${v.players[e.player].name} отдыхает`, 1200);
        await W.wait(0.3);
        break;
      case 'hold': {
        this.hud.setUnitBadge(e.unit, { hold: e.hold });
        if (e.hold >= 2) this.popup(e.unit, 'удержание созрело', 'good');
        break;
      }
      case 'matchEnd':
        sfx.play(e.winner === this.viewer ? 'win' : e.winner ? 'lose' : 'turn');
        break;
      default:
    }
  }

  // The final clash (3–4 s at normal speed): wind-up, lunge, impact, the loser thrown back.
  async clash(e) {
    const W = this.world, fx = this.fx;
    const a = this.units.get(e.attacker.unit), d = this.units.get(e.defender.unit);
    if (!a || !d) return;
    const mid = a.model.root.position.clone().add(d.model.root.position).multiplyScalar(0.5);
    if (this.dyn) W.focus(mid, { dist: 44, elev: 20 });
    this.hud.clashBanner(e, this.side(a.owner));
    this.hud.ui.classList.add('clashing');
    const pa = a.model.root.position.clone(), pd = d.model.root.position.clone();
    const dir = pd.clone().sub(pa).normalize();
    await W.tween(0.7, e2 => {
      a.model.root.position.copy(pa).addScaledVector(dir, -0.9 * e2);
      d.model.root.position.copy(pd).addScaledVector(dir, 0.9 * e2);
      a.model.kit.glow.emissiveIntensity = a.model.kit.baseGlow + e2 * 5;
      d.model.kit.glow.emissiveIntensity = d.model.kit.baseGlow + e2 * 5;
    }, ease.outCubic);
    await W.tween(0.28, e2 => {
      a.model.root.position.copy(pa).addScaledVector(dir, -0.9 + 2.3 * e2);
      d.model.root.position.copy(pd).addScaledVector(dir, 0.9 - 2.3 * e2);
    }, ease.inCubic);
    const winner = this.units.get(e.winner), loser = winner === a ? d : a;
    const wc = ASPECT_GLOW[COLOSSI[winner.def].aspect];
    this.sfx.play('clash');
    W.shake(1.6);
    fx.flash(mid.clone().setY(4), 0xffffff, { intensity: 2200, distance: 70, duration: 0.8 });
    fx.emit(mid.clone().setY(3.5), 220, { color: wc, speed: 18, spread: 1, up: 0.4, life: 1.2, size: 1.8, gravity: -5 });
    fx.emit(mid.clone().setY(3.5), 120, { color: 0xffffff, speed: 24, spread: 0.3, up: 0.1, life: 0.6, size: 1.2, gravity: 0 });
    fx.ring(mid, wc, { radius: 22, duration: 1.0, width: 1.2 });
    fx.pillar(mid, wc, { height: 40, radius: 2.2, duration: 0.9 });
    const lp = loser.model.root.position.clone();
    const away = lp.clone().sub(mid).setY(0).normalize();
    await W.tween(0.6, (e2, t) => {
      loser.model.root.position.copy(lp).addScaledVector(away, 3.5 * e2);
      loser.model.root.position.y = Math.sin(Math.PI * t) * 2;
      loser.model.root.rotation.x = -away.z * 0.5 * e2;
      winner.model.pose.scale.setScalar(1 + Math.sin(Math.PI * t) * 0.08);
    }, ease.outCubic);
    a.model.kit.glow.emissiveIntensity = a.model.kit.baseGlow;
    d.model.kit.glow.emissiveIntensity = d.model.kit.baseGlow;
    await W.wait(0.5);
    this.hud.ui.classList.remove('clashing');
  }
}
