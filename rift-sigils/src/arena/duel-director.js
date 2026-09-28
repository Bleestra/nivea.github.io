// Plays duel engine events as animations and keeps the scene in line with the public view.
import * as THREE from 'three';
import { CARDS, COLOSSI, GATE_KIND_NAMES, GATES, RULES } from '../duel/content.js';
import { COLOSSI as BASE } from '../core/content.js';
import { Colossus } from './colossi.js';
import { ASPECT_GLOW, OWNER_GLOW } from './fx.js';
import { ease } from './world.js';

export class DuelDirector {
  constructor({ world, fx, stage, hud, sfx, portraits }) {
    Object.assign(this, { world, fx, stage, hud, sfx, portraits });
    this.models = new Map();
    this.viewer = 'A';
    this.shields = new Map();
  }

  side(p) { return p === this.viewer ? 'me' : 'foe'; }

  spawn(uid, def, owner) {
    const side = this.side(owner);
    const m = new Colossus(this.world, BASE[def], { ownerColor: OWNER_GLOW[side] });
    m.root.rotation.y = side === 'me' ? Math.PI : 0;
    m.root.position.copy(this.stage.pos(side));
    m.root.traverse(o => { o.userData.unit = uid; });
    this.world.scene.add(m.root);
    this.models.set(uid, { m, def, owner, side });
    return m;
  }

  drop(uid) {
    const x = this.models.get(uid);
    if (!x) return;
    this.shields.get(uid)?.remove();
    this.shields.delete(uid);
    x.m.dispose();
    this.models.delete(uid);
    if (this.hud.cards[x.side]?.data.uid === uid) this.hud.setFighter(x.side, null);
  }

  fighterCard(uid, v) {
    const x = this.models.get(uid), u = v.units[uid];
    const preview = v.preview?.[x.owner] ?? null;
    this.hud.setFighter(x.side, { uid, def: u.def, g: u.g, startG: u.startG, shield: u.shield, preview, obj: x.m.anchor, portrait: this.portraits[u.def] });
  }

  setShield(uid, amount) {
    const x = this.models.get(uid);
    if (!x) return;
    const has = this.shields.get(uid);
    if (amount > 0 && !has) this.shields.set(uid, this.fx.bubble(x.m.root, 0xbfe9ff, 6));
    if (amount <= 0 && has) { has.shatter(); this.shields.delete(uid); }
  }

  pickables() { return [...this.models.values()].map(x => x.m.root); }

  // Rebuild the scene from a public view, without animation.
  sync(v) {
    this.viewer = v.viewer;
    const gate = v.bout?.gate;
    const owner = gate ? this.side(v.bout.owner ?? v.bout.placer) : 'me';
    this.stage.show(gate ? (v.bout.gateDef ?? 'RS-G002') : null, owner, !!v.bout?.gateOpen);
    for (const p of ['A', 'B']) {
      const uid = v.players[p].fighter;
      for (const [id, x] of this.models) if (x.owner === p && id !== uid) this.drop(id);
      if (!uid) continue;
      if (!this.models.has(uid)) this.spawn(uid, v.units[uid].def, p);
      this.fighterCard(uid, v);
      this.setShield(uid, v.units[uid].shield);
    }
  }

  reset(v) {
    for (const uid of [...this.models.keys()]) this.drop(uid);
    this.hud.setFighter('me', null);
    this.hud.setFighter('foe', null);
    this.world.goOverview(true);
    this.sync(v);
  }

  async play(events, v) {
    this.v = v;
    for (const e of events) {
      try { await this.handle(e, v); } catch (err) { console.error('animation', e.t, err); }
    }
    this.sync(v);
  }

  pop(uid, text, cls) {
    const x = this.models.get(uid);
    if (x) this.hud.popupAt(x.m.head, text, cls);
  }

  async handle(e, v) {
    const W = this.world, fx = this.fx, sfx = this.sfx;
    const who = p => (p === this.viewer ? 'Вы' : v.players[p].name);
    switch (e.t) {
      case 'coin':
        sfx.play('turn');
        await this.hud.banner('Монетка', `первыми ворота выкладывает: ${who(e.first)}`, 1.4);
        break;
      case 'boutStart':
        await this.hud.banner(`Бой ${e.n}`, e.placer ? `ворота кладёт: ${who(e.placer)}` : 'ворот больше нет', 0.9);
        break;
      case 'gatePlaced':
        sfx.play('whoosh');
        await this.stage.throwGate(e.gateDef ?? 'RS-G002', this.side(e.player));
        sfx.play('land');
        this.hud.toast(e.gateDef ? `Ваши ворота «${GATES[e.gateDef].name}» лежат закрытыми. Откроете, когда захотите.` : 'Соперник положил ворота рубашкой вверх.', 2200);
        break;
      case 'chosen':
        if (e.player !== this.viewer) this.hud.toast('Соперник выбрал бойца', 1200);
        break;
      case 'fighters': {
        for (const p of ['A', 'B']) {
          const uid = e[p];
          if (this.models.has(uid)) continue;
          const side = this.side(p);
          const def = v.units[uid].def;
          const m = this.spawn(uid, def, p);
          m.root.visible = false;
          const target = this.stage.pos(side);
          const from = new THREE.Vector3(side === 'me' ? 6 : -6, 8, side === 'me' ? 36 : -36);
          sfx.play('whoosh');
          await fx.seal(from, target, OWNER_GLOW[side]);
          sfx.play('summon');
          m.root.visible = true;
          fx.pillar(target, ASPECT_GLOW[COLOSSI[def].aspect], { height: 26, radius: 3.4, duration: 1.1 });
          await m.assemble();
        }
        break;
      }
      case 'gateRevealed': {
        const g = GATES[e.gateDef];
        sfx.play('reveal');
        if (g.kind === 'trap') { W.shake(0.6); fx.flash(new THREE.Vector3(0, 4, 0), 0xff3322, { intensity: 700, duration: 0.6 }); }
        await this.stage.reveal(e.gateDef, this.side(e.owner));
        await this.hud.banner(`${GATE_KIND_NAMES[g.kind]}: ${g.name}`, `${e.owner === this.viewer ? 'ваши ворота' : 'ворота соперника'} · ${g.text}`, 1.8);
        break;
      }
      case 'fighterReady': {
        const x = this.models.get(e.unit);
        if (!x) break;
        this.fighterCard(e.unit, { units: { [e.unit]: { def: x.def, g: e.g, startG: e.startG ?? e.g, shield: 0 } } }); // a tired fighter starts below full
        this.setShield(e.unit, 0);
        await W.wait(0.3);
        break;
      }
      case 'roundStart':
        sfx.play('turn');
        await this.hud.banner(`Раунд ${e.round}`, `мана ${e.mana[this.viewer]} · ${Math.round(e.timerMs / 1000)} секунд`, 0.8);
        break;
      case 'activate':
        sfx.play('card');
        if (e.kind === 'gate') { this.hud.toast('Ворота откроются в конце раунда. Соперник видит только, что вы что-то сделали.', 2200); await W.wait(0.3); }
        else if (e.defs) await this.hud.showActivation(e, this.side(e.player));
        else await this.hud.showHidden(this.side(e.player));
        break;
      case 'roundEnd':
        // the forecast only knew your own cards: from here on the real numbers play out
        for (const side of ['me', 'foe']) this.hud.patchFighter(side, { preview: null });
        if (e.queued) await this.hud.banner('Конец раунда', 'вскрытие', 0.7);
        break;
      case 'reveal':
        sfx.play('reveal');
        this.hud.revealQueue(e.actions);
        await this.hud.showReveal(e.actions, this.viewer, this.v);
        break;
      case 'resolve':
        this.hud.pulseQueue(e.id);
        await W.wait(0.3);
        break;
      case 'countered':
        sfx.play('counter');
        this.hud.pulseQueue(e.id, 'off');
        this.hud.toast(e.kind === 'gate' ? 'Отмена попала в открытие ворот: ворота остаются закрытыми' : `Отменено: ${e.defs.map(d => `«${CARDS[d].name}»`).join(' + ')}`, 1800);
        W.shake(0.4);
        await W.wait(0.45);
        break;
      case 'fizzle':
        this.hud.pulseQueue(e.id, 'off');
        break;
      case 'recall': {
        const x = this.models.get(e.unit);
        if (!x) break;
        await x.m.dissolve(fx, { color: OWNER_GLOW[x.side], up: true });
        this.drop(e.unit);
        break;
      }
      case 'gain': {
        const x = this.models.get(e.unit);
        if (!x) break;
        fx.aura(x.m.root, ASPECT_GLOW[COLOSSI[x.def].aspect], true);
        sfx.play('buff');
        this.pop(e.unit, `+${e.amount} G${e.why === 'gateBonus' ? ' от ворот' : ''}`, 'good');
        this.hud.patchFighter(x.side, { g: e.g });
        await W.wait(0.4);
        break;
      }
      case 'shield':
        this.setShield(e.unit, e.shield);
        sfx.play('shield');
        this.pop(e.unit, `щит ${e.shield}`, 'good');
        this.hud.patchFighter(this.models.get(e.unit)?.side, { shield: e.shield });
        await W.wait(0.35);
        break;
      case 'shieldAbsorb':
        this.pop(e.unit, `щит −${e.amount}`, 'info');
        this.hud.patchFighter(this.models.get(e.unit)?.side, { shield: e.shield });
        if (e.shield <= 0) { this.setShield(e.unit, 0); sfx.play('break'); }
        break;
      case 'shieldBroken':
        this.setShield(e.unit, 0);
        sfx.play('break');
        this.pop(e.unit, 'щиты сняты', 'bad');
        this.hud.patchFighter(this.models.get(e.unit)?.side, { shield: 0 });
        await W.wait(0.3);
        break;
      case 'damage': {
        const x = this.models.get(e.unit);
        if (!x) break;
        const p = x.m.anchor.getWorldPosition(new THREE.Vector3());
        if (e.why !== 'attack') {
          fx.emit(p, 50, { color: 0xff5a4a, speed: 9, life: 0.6, size: 1.3 });
          sfx.play('debuff');
        }
        if (e.amount) this.pop(e.unit, `−${e.amount} G`, 'bad');
        this.hud.patchFighter(x.side, { g: e.g });
        if (e.over > 0) {
          // G went below zero: the colossus falls, and the rest plus the knockout cost hit its player's life gauge
          fx.flash(p, 0xff3322, { intensity: 900, duration: 0.6 });
          W.shake(0.9);
          setTimeout(() => this.pop(e.unit, `−${e.over + (e.ko ?? 0)} жизни`, 'bad'), 250);
          this.hud.flashLife?.(x.side, e.life);
        }
        await W.wait(e.why === 'attack' ? 0.25 : 0.45);
        break;
      }
      case 'heal':
        fx.aura(this.models.get(e.unit)?.m.root ?? this.stage.holder, 0x6dffc0, true);
        this.pop(e.unit, `+${e.amount} G`, 'good');
        this.hud.patchFighter(this.models.get(e.unit)?.side, { g: e.g });
        sfx.play('buff');
        await W.wait(0.35);
        break;
      case 'healBlocked':
        this.pop(e.unit, 'восстановление не действует', 'info');
        break;
      case 'stealBlocked':
        this.pop(e.unit, 'кража силы не действует', 'info');
        break;
      case 'reflected': {
        // the player's own card turns back onto their fighter
        const [uid, x] = [...this.models].find(([, m]) => m.owner === e.player) ?? [];
        if (x) { fx.aura(x.m.root, 0xff5a4a, true); this.pop(uid, 'отражено!', 'bad'); }
        await W.wait(0.3);
        break;
      }
      case 'swap': {
        sfx.play('whoosh');
        const ms = e.units.map(u => this.models.get(u)).filter(Boolean);
        const link = ms.length === 2 ? fx.beam(ms[0].m.anchor, ms[1].m.anchor, 0xc9a0ff) : null;
        for (const u of e.units) {
          const x = this.models.get(u);
          if (!x) continue;
          this.pop(u, `обмен: ${e.g[u]} G`, 'info');
          this.hud.patchFighter(x.side, { g: e.g[u] });
        }
        await W.wait(0.7);
        await link?.break();
        break;
      }
      case 'trapMissed':
        this.hud.toast('Ловушка не сработала: боец соперника не сильнее', 1600);
        break;
      case 'mana':
        if (e.amount === undefined) break; // the opponent's tactic mana stays hidden until the reveal
        this.hud.bubble(this.side(e.player), `${e.amount > 0 ? '+' : '−'}${Math.abs(e.amount)} маны в следующем раунде`);
        break;
      case 'attack':
        await this.attack(e);
        break;
      case 'knockout': {
        const x = this.models.get(e.unit);
        if (!x) break;
        sfx.play(e.removed ? 'lose' : 'break');
        await x.m.dissolve(fx, { color: e.removed ? 0xff3322 : OWNER_GLOW[x.side], up: !e.removed });
        this.drop(e.unit);
        await this.hud.banner(e.removed ? 'Удалён из игры' : 'Боец выбыл', `${COLOSSI[x.def].name}: ${e.removed ? `разница сил ${e.diff} — больше ${RULES.removeOver}` : `минус ${e.over} G, вернётся в резерв`}`, 1.1);
        break;
      }
      case 'boutEnd':
        if (e.gateReturned) {
          // a gate nobody opened goes back to its owner face down: the opponent never learns what it was
          this.hud.toast(e.owner === this.viewer ? 'Ваши ворота не открылись и вернулись к вам' : 'Ворота соперника не открылись и вернулись к нему', 1800);
          await this.stage.returnGate(this.side(e.owner));
        } else await this.stage.burn(0xffd27a);
        break;
      case 'ready':
        this.hud.bubble(this.side(e.player), 'Готов');
        break;
      case 'handFull':
        if (e.player === this.viewer) this.hud.toast('Рука полна: карта не взята');
        break;
      case 'drawNone':
        if (e.player === this.viewer) this.hud.toast('В колоде нет карт для этого бойца');
        break;
      case 'matchEnd':
        sfx.play(e.winner === this.viewer ? 'win' : e.winner ? 'lose' : 'turn');
        break;
      default:
    }
  }

  // Both fighters rear back, lunge and strike at once.
  async attack(e) {
    const W = this.world, fx = this.fx;
    const a = this.models.get(e.A.unit), b = this.models.get(e.B.unit);
    if (!a || !b) return;
    const pa = a.m.root.position.clone(), pb = b.m.root.position.clone();
    const dir = pb.clone().sub(pa).normalize();
    const mid = pa.clone().add(pb).multiplyScalar(0.5);
    // the forces that meet: G plus the aspect edge and abilities
    this.hud.banner(`${e[this.viewer].value} против ${e[this.viewer === 'A' ? 'B' : 'A'].value}`, e.inverted ? 'атака · ловушка: разницу теряет сильный' : 'атака', 1.0);
    a.m.strike();
    b.m.strike();
    await W.tween(0.55, k => {
      a.m.root.position.copy(pa).addScaledVector(dir, -1.2 * k);
      b.m.root.position.copy(pb).addScaledVector(dir, 1.2 * k);
      a.m.kit.glow.emissiveIntensity = a.m.kit.baseGlow + k * 5;
      b.m.kit.glow.emissiveIntensity = b.m.kit.baseGlow + k * 5;
    }, ease.outCubic);
    await W.tween(0.25, k => {
      a.m.root.position.copy(pa).addScaledVector(dir, -1.2 + 3.4 * k);
      b.m.root.position.copy(pb).addScaledVector(dir, 1.2 - 3.4 * k);
    }, ease.inCubic);
    this.sfx.play('clash');
    W.shake(1.4);
    const strong = e.A.g >= e.B.g ? a : b;
    const col = ASPECT_GLOW[COLOSSI[strong.def].aspect];
    fx.flash(mid.clone().setY(5), 0xffffff, { intensity: 2000, distance: 70, duration: 0.7 });
    fx.emit(mid.clone().setY(4.5), 200, { color: col, speed: 18, spread: 1, up: 0.4, life: 1.1, size: 1.7, gravity: -5 });
    fx.ring(mid, col, { radius: 20, duration: 0.9, width: 1.2 });
    await W.tween(0.4, k => {
      a.m.root.position.copy(pa).addScaledVector(dir, 2.2 * (1 - k));
      b.m.root.position.copy(pb).addScaledVector(dir, -2.2 * (1 - k));
    }, ease.outCubic);
    a.m.root.position.copy(pa);
    b.m.root.position.copy(pb);
    a.m.kit.glow.emissiveIntensity = a.m.kit.baseGlow;
    b.m.kit.glow.emissiveIntensity = b.m.kit.baseGlow;
  }
}

