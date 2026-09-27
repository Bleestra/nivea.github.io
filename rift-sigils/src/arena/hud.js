// HTML layer over the 3D stage. It renders a model prepared by main.js and reports intents; it never decides rules.
import * as THREE from 'three';
import { ABILITIES, COLOSSI, GATES } from '../core/index.js';
import { abilityCard, backCard, colossusTile, gateCard } from './cardart.js';
import { esc, eventLine, GLYPH, signed } from '../web/text.js';

const tmp = new THREE.Vector3();

export class Hud {
  constructor(root, world, onIntent) {
    this.root = root;
    this.world = world;
    this.emit = onIntent;
    root.innerHTML = '<div class="labels"></div><div class="ui"></div><div class="fxl"></div><div class="tip" hidden></div>';
    this.labelsEl = root.querySelector('.labels');
    this.ui = root.querySelector('.ui');
    this.fxl = root.querySelector('.fxl');
    this.tipEl = root.querySelector('.tip');
    this.tracked = new Map();
    this.floats = new Set();
    this.prevHand = new Set();
    this.drag = null;
    world.onUpdate(() => this.placeLabels());
    this.bindInput();
  }

  // ---------------------------------------------------------------- 3D-anchored labels

  trackUnit(uid, obj, side) {
    const el = document.createElement('div');
    el.className = `badge ${side}`;
    this.labelsEl.appendChild(el);
    this.tracked.set(uid, { el, obj, data: { hold: 0, anchor: false, fighter: false, name: '' } });
  }
  untrackUnit(uid) {
    const t = this.tracked.get(uid);
    if (t) { t.el.remove(); this.tracked.delete(uid); }
  }
  setUnitBadge(uid, data) {
    const t = this.tracked.get(uid);
    if (!t) return;
    Object.assign(t.data, data);
    const d = t.data;
    const pips = d.fighter ? '' : `<span class="pips">${'●'.repeat(Math.min(2, d.hold))}${'○'.repeat(Math.max(0, 2 - d.hold))}</span>`;
    t.el.innerHTML = `${d.name ? `<span class="nm">${esc(d.name)}</span>` : ''}${pips}${d.anchor ? '<span class="anc">якорь</span>' : ''}`;
  }
  setCellHints(list) {
    for (const h of this.hints ?? []) h.el.remove();
    this.hints = list.map(({ obj, text, hostile }) => {
      const el = document.createElement('div');
      el.className = `hint${hostile ? ' hostile' : ''}`;
      el.textContent = text;
      this.labelsEl.appendChild(el);
      return { el, obj };
    });
  }
  place(el, obj, dy = 0) {
    obj.getWorldPosition(tmp);
    const p = this.world.project(tmp);
    el.style.transform = `translate(${p.x}px, ${p.y + dy}px) translate(-50%, -100%)`;
    el.style.visibility = p.visible ? 'visible' : 'hidden';
  }
  placeLabels() {
    for (const t of this.tracked.values()) this.place(t.el, t.obj);
    for (const h of this.hints ?? []) this.place(h.el, h.obj);
    for (const f of this.floats) this.place(f.el, f.obj, f.dy);
  }
  popupAt(obj, text, cls = 'info') {
    const el = document.createElement('div');
    el.className = `pop ${cls}`;
    el.textContent = text;
    this.labelsEl.appendChild(el);
    const f = { el, obj, dy: 0 };
    this.floats.add(f);
    const start = performance.now();
    const step = () => {
      const k = (performance.now() - start) / 1400;
      f.dy = -60 * k;
      el.style.opacity = String(k < 0.7 ? 1 : 1 - (k - 0.7) / 0.3);
      if (k < 1) requestAnimationFrame(step);
      else { el.remove(); this.floats.delete(f); }
    };
    requestAnimationFrame(step);
  }

  // ---------------------------------------------------------------- transient overlays

  banner(title, sub = '', seconds = 0.9) {
    const el = document.createElement('div');
    el.className = 'banner-fx';
    el.innerHTML = `<b>${esc(title)}</b>${sub ? `<span>${esc(sub)}</span>` : ''}`;
    this.fxl.appendChild(el);
    const ms = seconds * 1000 / this.world.speed;
    el.animate([{ opacity: 0, transform: 'translate(-50%,-50%) scale(.92)' }, { opacity: 1, transform: 'translate(-50%,-50%) scale(1)', offset: 0.2 },
      { opacity: 1, offset: 0.75 }, { opacity: 0, transform: 'translate(-50%,-50%) scale(1.04)' }], { duration: ms, easing: 'ease-out' });
    return new Promise(r => setTimeout(() => { el.remove(); r(); }, ms));
  }

  toast(text, ms = 1600) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = text;
    this.fxl.appendChild(el);
    el.animate([{ opacity: 0, transform: 'translate(-50%, -8px)' }, { opacity: 1, transform: 'translate(-50%, 0)', offset: 0.1 }, { opacity: 1, offset: 0.85 }, { opacity: 0 }], { duration: ms });
    setTimeout(() => el.remove(), ms);
  }

  passBubble(side) {
    const anchor = this.ui.querySelector(`.seat.${side}`);
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    const el = document.createElement('div');
    el.className = `bubble ${side}`;
    el.textContent = 'Пас';
    el.style.left = `${r.left + r.width / 2}px`;
    el.style.top = `${side === 'me' ? r.top - 10 : r.bottom + 34}px`;
    this.fxl.appendChild(el);
    el.animate([{ opacity: 0, transform: 'translate(-50%,-100%) scale(.8)' }, { opacity: 1, transform: 'translate(-50%,-100%) scale(1)', offset: 0.15 }, { opacity: 1, offset: 0.8 }, { opacity: 0 }], { duration: 900 });
    setTimeout(() => el.remove(), 900);
  }

  // A played card flies to the centre, shows itself (the opponent's card is revealed here), then drops into the chain.
  async showPlayedCard(e, side) {
    const html = abilityCard(e.def, { cost: e.cost, cls: 'played' });
    const holder = document.createElement('div');
    holder.className = 'flycard';
    holder.innerHTML = html;
    this.fxl.appendChild(holder);
    const src = side === 'me' ? this.ui.querySelector(`.hand .card[data-card="${e.card}"]`) : this.ui.querySelector('.opp-hand');
    if (src && side === 'me') src.style.visibility = 'hidden';
    const W = window.innerWidth, H = window.innerHeight;
    const r = src?.getBoundingClientRect() ?? { left: W / 2, top: side === 'me' ? H : 0, width: 0, height: 0 };
    const sx = r.left + r.width / 2 - W / 2, sy = r.top + r.height / 2 - H / 2;
    const chainEl = this.ui.querySelector('.chain');
    const cr = chainEl?.getBoundingClientRect();
    const ex = cr ? cr.left + cr.width / 2 - W / 2 : 0, ey = cr ? cr.top + cr.height / 2 - H / 2 : -H * 0.3;
    const ms = 1150 / this.world.speed;
    const anim = holder.animate([
      { transform: `translate(${sx}px, ${sy}px) scale(.55) rotate(${side === 'me' ? 0 : 180}deg)`, opacity: 0.4 },
      { transform: 'translate(0px, -4vh) scale(1.35) rotate(0deg)', opacity: 1, offset: 0.28 },
      { transform: 'translate(0px, -4vh) scale(1.35)', opacity: 1, offset: 0.72 },
      { transform: `translate(${ex}px, ${ey}px) scale(.3)`, opacity: 0 },
    ], { duration: ms, easing: 'cubic-bezier(.2,.8,.2,1)' });
    await anim.finished.catch(() => {});
    holder.remove();
  }

  pulseChain(oid) {
    this.ui.querySelector(`.chain [data-oid="${oid}"]`)?.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.18)' }, { transform: 'scale(1)' }], { duration: 300 });
  }

  async shatterChain(oid) {
    const el = this.ui.querySelector(`.chain [data-oid="${oid}"]`);
    if (!el) return;
    await el.animate([{ transform: 'scale(1) rotate(0)', opacity: 1, filter: 'brightness(1)' }, { transform: 'scale(1.3) rotate(-8deg)', filter: 'brightness(2.5)', offset: 0.3 }, { transform: 'scale(.2) rotate(25deg)', opacity: 0 }], { duration: 600, fill: 'forwards' }).finished.catch(() => {});
  }

  clashBanner(e, attackerSide) {
    const el = document.createElement('div');
    el.className = 'clash-fx';
    const win = e.winner === e.attacker.unit ? 'a' : 'd';
    el.innerHTML = `<span class="n ${attackerSide} ${win === 'a' ? 'w' : 'l'}">${e.attacker.total}</span><i>против</i><span class="n ${attackerSide === 'me' ? 'foe' : 'me'} ${win === 'd' ? 'w' : 'l'}">${e.defender.total}</span>`;
    this.fxl.appendChild(el);
    const ms = 2600 / this.world.speed;
    el.animate([{ opacity: 0, transform: 'translate(-50%,-50%) scale(1.6)' }, { opacity: 1, transform: 'translate(-50%,-50%) scale(1)', offset: 0.15 }, { opacity: 1, offset: 0.8 }, { opacity: 0 }], { duration: ms });
    setTimeout(() => el.remove(), ms);
  }

  flySigil(obj, side) {
    obj.getWorldPosition(tmp);
    const p = this.world.project(tmp);
    const slot = this.ui.querySelector(`.seat.${side} .sig:not(.on)`) ?? this.ui.querySelector(`.seat.${side}`);
    if (!slot) return;
    const r = slot.getBoundingClientRect();
    const el = document.createElement('div');
    el.className = `sigil-fx ${side}`;
    this.fxl.appendChild(el);
    el.animate([{ left: `${p.x}px`, top: `${p.y}px`, transform: 'translate(-50%,-50%) scale(2.4)', opacity: 0 },
      { opacity: 1, offset: 0.2 }, { left: `${r.left + r.width / 2}px`, top: `${r.top + r.height / 2}px`, transform: 'translate(-50%,-50%) scale(1)', opacity: 1 }],
    { duration: 1100 / this.world.speed, easing: 'cubic-bezier(.5,0,.2,1)', fill: 'forwards' });
    setTimeout(() => el.remove(), 1300 / this.world.speed);
  }

  tip(html, x, y) {
    if (!html) { this.tipEl.hidden = true; return; }
    this.tipEl.hidden = false;
    this.tipEl.innerHTML = html;
    const w = this.tipEl.offsetWidth, h = this.tipEl.offsetHeight;
    this.tipEl.style.left = `${Math.min(window.innerWidth - w - 8, x + 16)}px`;
    this.tipEl.style.top = `${Math.max(8, Math.min(window.innerHeight - h - 8, y - h / 2))}px`;
  }

  // ---------------------------------------------------------------- full render

  render(m) {
    this.m = m;
    const { v, viewer } = m;
    const opp = viewer === 'A' ? 'B' : 'A';
    const me = v.players[viewer], foe = v.players[opp];
    const handIds = (me.hand ?? []).map(h => h.card);
    const fresh = new Set(handIds.filter(id => !this.prevHand.has(id)));
    this.prevHand = new Set(handIds);
    this.ui.classList.toggle('has-sel', !!m.sel.card);
    this.ui.innerHTML = `
      ${this.seat(m, opp, 'foe')}
      <div class="opp-hand">${Array.from({ length: foe.handCount }, (_, i) => backCard('', fanStyle(i, foe.handCount, true))).join('')}</div>
      ${this.roster(m, opp, 'foe')}
      ${this.duelBar(m)}
      ${this.roster(m, viewer, 'me')}
      ${this.seat(m, viewer, 'me')}
      ${this.hand(m, fresh)}
      ${this.mana(me, v.round, 'me')}
      ${this.endButton(m)}
      ${this.promptBox(m)}
      <div class="corner">
        <button class="ibtn" type="button" data-i="journal" aria-pressed="${m.sel.journal}">Журнал</button>
        <button class="ibtn" type="button" data-i="menu">Меню</button>
      </div>
      ${m.sel.journal ? this.journal(m) : ''}
      ${this.overlay(m)}`;
  }

  seat(m, p, side) {
    const pl = m.v.players[p];
    const sig = [0, 1, 2].map(i => `<span class="sig${i < pl.sigils ? ' on' : ''}"></span>`).join('');
    const active = m.v.active === p && m.v.phase !== 'ended';
    const name = side === 'me' && m.human ? 'Вы' : pl.name;
    return `<section class="seat ${side}${active ? ' active' : ''}">
      <div class="emb" aria-hidden="true"><svg viewBox="0 0 40 40"><polygon points="20,2 36,11 36,29 20,38 4,29 4,11"/><circle cx="20" cy="20" r="7"/></svg><b>${p}</b></div>
      <div class="sinfo"><span class="sname">${esc(name)}</span><span class="sigs" aria-label="печати ${pl.sigils} из 3">${sig}</span>
        <span class="scount">рука ${pl.handCount} · колода ${pl.deckCount} · сброс ${pl.discard.length}</span></div>
      ${side === 'foe' ? this.mana(pl, m.v.round, 'foe') : ''}
    </section>`;
  }

  mana(pl, round, side) {
    const cap = round ? Math.min(6, round + 1) : 0;
    const gems = Array.from({ length: 6 }, (_, i) => `<i class="${i < pl.mana ? 'full' : i < cap ? 'spent' : 'locked'}"></i>`).join('');
    return `<div class="mana ${side}" aria-label="мана ${pl.mana} из ${cap}"><span class="mnum">${pl.mana}/${cap}</span><span class="gems">${gems}</span></div>`;
  }

  roster(m, p, side) {
    const { v, portraits, acts, sel } = m;
    const tiles = v.players[p].units.map(uid => {
      const u = v.units[uid];
      const status = u.zone === 'reserve' ? 'готов' : u.zone === 'field' ? `${u.platform} · удерж. ${u.hold}` : `вернётся на ход ${u.readyOn}`;
      const can = side === 'me' && acts.some(a => a.unit === uid && (a.type === 'launch' || a.type === 'move' || a.type === 'recall' || a.type === 'capture'));
      return colossusTile(u.def, { portrait: portraits[u.def], status, uid, cls: `${u.zone}${can ? ' can' : ''}${sel.unit === uid ? ' sel' : ''}` });
    }).join('');
    return `<section class="roster ${side}" aria-label="колоссы">${tiles}</section>`;
  }

  hand(m, fresh) {
    const { v, viewer, acts, sel } = m;
    const me = v.players[viewer];
    if (v.phase === 'setupGates' && me.gatesToPlace?.length) {
      const n = me.gatesToPlace.length;
      return `<div class="hand">${me.gatesToPlace.map((g, i) => gateCard(g.def, { gid: g.gate, cls: `${acts.some(a => a.gate === g.gate) ? 'can' : ''}${sel.gate === g.gate ? ' sel' : ''}` }).replace('class="card', `style="${fanStyle(i, n)}" class="card`)).join('')}</div>`;
    }
    const hand = me.hand ?? [];
    const cards = hand.map((h, i) => {
      const can = m.mode === 'play' && acts.some(a => a.card === h.card);
      const cls = `${can ? 'can' : ''}${sel.card === h.card ? ' sel' : ''}${fresh.has(h.card) ? ' enter' : ''}`;
      return abilityCard(h.def, { cost: m.costOf(h.def), cid: h.card, cls, style: fanStyle(i, hand.length) });
    }).join('');
    return `<div class="hand" aria-label="рука">${cards}</div>`;
  }

  endButton(m) {
    const b = m.endBtn;
    return `<button class="endturn${b.glow ? ' glow' : ''}" type="button" data-i="${b.intent ?? ''}" ${b.enabled ? '' : 'disabled'}>${esc(b.label)}</button>`;
  }

  promptBox(m) {
    const p = m.prompt;
    if (!p) return '';
    const btns = (p.buttons ?? []).map(b => `<button class="pbtn${b.primary ? ' primary' : ''}" type="button" data-i="${b.intent}" ${b.data ? `data-x="${esc(b.data)}"` : ''}>${b.label}</button>`).join('');
    const opts = m.options?.length ? `<div class="opts">${m.options.map((o, i) => `<button class="opt" type="button" data-i="opt" data-x="${i}">${o.label}</button>`).join('')}</div>` : '';
    return `<div class="prompt${p.wait ? ' wait' : ''}" role="status">${opts}<div class="ptext">${p.text}</div>${p.hint ? `<div class="phint">${p.hint}</div>` : ''}${btns ? `<div class="pbtns">${btns}</div>` : ''}</div>`;
  }

  duelBar(m) {
    const d = m.v.duel;
    if (!d || d.step !== 'cards' && d.step !== 'support') return '';
    const { v, viewer, N } = m;
    const plaque = uid => {
      const u = v.units[uid], bd = d.power[uid], side = u.owner === viewer ? 'me' : 'foe';
      const tags = [];
      if (d.shroud[uid]) tags.push('Покров');
      if (d.silenced[uid]) tags.push('Немота');
      if (d.aspect[uid]) tags.push(`${GLYPH[d.aspect[uid]]} аспект`);
      const sp = d.support[u.owner];
      if (sp) tags.push(sp.suppressed ? 'связь подавлена' : `поддержка: ${COLOSSI[v.units[sp.unit].def].name}`);
      const parts = m.sel.details ? `<ul class="parts">${bd.parts.map(x => `<li><span>${esc(x.label)}</span><b>${signed(x.value)}</b></li>`).join('')}</ul>` : '';
      return `<button class="plaque ${side}${d.priority === u.owner && d.step === 'cards' ? ' prio' : ''}" type="button" data-i="details">
        <span class="role">${uid === d.attacker ? 'нападает' : 'защищается'}</span>
        <span class="pname">${esc(COLOSSI[u.def].name)}</span><span class="pw">${bd.total}</span>
        <span class="ptags">${tags.map(t => `<i>${esc(t)}</i>`).join('')}</span>${parts}</button>`;
    };
    const mine = v.units[d.attacker].owner === viewer ? d.attacker : d.defender;
    const theirs = mine === d.attacker ? d.defender : d.attacker;
    const chain = d.chain.slice().reverse().map((o, i) => `<div class="link ${o.owner === viewer ? 'me' : 'foe'}${i === 0 ? ' top' : ''}" data-oid="${o.oid}" title="${esc(ABILITIES[o.def].text)}">
      <b>${esc(ABILITIES[o.def].name)}</b><span>${o.cost} · ${o.owner === viewer && m.human ? 'вы' : esc(v.players[o.owner].name)}</span></div>`).join('');
    const gate = GATES[v.board[d.platform].gate.def];
    return `<section class="duelbar" aria-label="поединок">
      <div class="dhead">Поединок на ${d.platform} · ${esc(gate.name)}${d.aspectBonusOff ? ' · бонусы отключены' : ''}</div>
      <div class="drow">${plaque(theirs)}<div class="chain">${chain || '<span class="empty">цепочка пуста</span>'}
        ${d.step === 'cards' ? `<span class="passes">пасов подряд ${d.passes}/2</span>` : '<span class="passes">выбор поддержки</span>'}</div>${plaque(mine)}</div>
      <div class="dfoot">${m.sel.details ? 'Нажмите на табличку, чтобы свернуть расчёт' : 'Нажмите на табличку бойца, чтобы увидеть расчёт силы'}</div>
    </section>`;
  }

  journal(m) {
    const lines = [];
    for (const e of m.v.log) {
      const l = eventLine(m.N, m.v, e);
      if (!l) continue;
      lines.push(l.sep ? `<li class="sep">${esc(l.sep)}</li>` : `<li${l.big ? ' class="big"' : ''}>${l.html}</li>`);
    }
    return `<aside class="journal" aria-label="журнал"><header><b>Журнал</b><button class="ibtn" type="button" data-i="copy">Скопировать запись</button><button class="ibtn" type="button" data-i="journal">Закрыть</button></header>
      <ol>${lines.reverse().join('')}</ol>${m.recordText ? `<textarea readonly id="rec">${esc(m.recordText)}</textarea>` : ''}</aside>`;
  }

  overlay(m) {
    const { v, viewer, sel } = m;
    if (sel.menu) return this.menu(m);
    if (m.result) {
      const r = m.result;
      return `<div class="overlay result ${r.cls}"><div class="rbox"><h1>${esc(r.title)}</h1><p>${esc(r.sub)}</p>
        <div class="pbtns"><button class="pbtn primary" type="button" data-i="again">Ещё партия</button><button class="pbtn" type="button" data-i="menu">Настройки</button><button class="pbtn" type="button" data-i="dismiss">Смотреть поле</button></div></div></div>`;
    }
    if (m.mode === 'mulligan') {
      const hand = v.players[viewer].hand ?? [];
      return `<div class="overlay mull"><div class="obox"><h2>Стартовая рука</h2><p>Отметьте карты для обмена. Замены придут раньше, чем отмеченные вернутся в колоду.</p>
        <div class="row">${hand.map(h => `<div class="pick${sel.mull.includes(h.card) ? ' x' : ''}" data-i="mull" data-x="${h.card}">${abilityCard(h.def, { cid: h.card })}</div>`).join('')}</div>
        <div class="pbtns"><button class="pbtn primary" type="button" data-i="mullDone">${sel.mull.length ? `Обменять ${sel.mull.length}` : 'Оставить руку'}</button></div></div></div>`;
    }
    if (m.mode === 'discard') {
      const hand = v.players[viewer].hand ?? [];
      return `<div class="overlay"><div class="obox"><h2>Тактический резерв</h2><p>Выберите карту, которую сбросить.</p>
        <div class="row wrap">${hand.map(h => `<div class="pick" data-i="discard" data-x="${h.card}">${abilityCard(h.def, { cid: h.card })}</div>`).join('')}</div></div></div>`;
    }
    if (m.mode === 'arrange') {
      const cards = v.choice.cards;
      return `<div class="overlay"><div class="obox"><h2>Чтение намерений</h2><p>Нажимайте карты в порядке сверху вниз. ${sel.order.length ? `Выбрано: ${sel.order.length} из ${cards.length}.` : ''}</p>
        <div class="row">${cards.map(c => {
          const n = sel.order.indexOf(c.card);
          return `<div class="pick${n >= 0 ? ' picked' : ''}" data-i="order" data-x="${c.card}">${n >= 0 ? `<b class="ord">${n + 1}</b>` : ''}${abilityCard(c.def, { cid: c.card })}</div>`;
        }).join('')}</div>
        <div class="pbtns"><button class="pbtn" type="button" data-i="orderReset">Заново</button><button class="pbtn primary" type="button" data-i="orderDone" ${sel.order.length === cards.length ? '' : 'disabled'}>Готово</button></div></div></div>`;
    }
    if (m.mode === 'support') {
      const circle = GATES[v.board[v.duel.platform].gate.def].id === 'RS-G006';
      const opts = m.acts.map(a => {
        if (!a.unit) return `<button class="pbtn" type="button" data-i="support" data-x="">Без поддержки</button>`;
        const u = v.units[a.unit];
        return colossusTile(u.def, { portrait: m.portraits[u.def], status: `на ${u.platform}, удержание ${u.hold} → 0`, uid: a.unit, cls: 'can sup' }).replace('data-unit=', 'data-i="support" data-x=');
      }).join('');
      return `<div class="overlay light"><div class="obox small"><h2>Поддержка</h2>
        <p>${circle ? 'Каменный круг: связь не даст силы, но союзник всё равно уйдёт на восстановление. ' : ''}Союзник с соседней платформы даёт +2, его удержание обнуляется, после поединка он восстанавливается один ход. Выбор тайный.</p>
        <div class="row wrap">${opts}</div></div></div>`;
    }
    return '';
  }

  menu(m) {
    const s = m.settings;
    const opt = (map, cur) => Object.entries(map).map(([k, l]) => `<option value="${k}"${k === cur ? ' selected' : ''}>${esc(l)}</option>`).join('');
    return `<div class="overlay"><form class="obox menu" id="menu-form">
      <h2>Печати Разлома</h2>
      <label>Ваша колода<select id="set-you">${opt(m.deckNames, s.you)}</select></label>
      <label>Колода бота<select id="set-bot">${opt(m.deckNames, s.bot)}</select></label>
      <label>Бот<select id="set-botKind">${opt({ simple: 'Простой: считает ответы в поединке', random: 'Случайный' }, s.botKind)}</select></label>
      <label>Темп анимаций<select id="set-speed">${opt({ fast: 'Быстро', normal: 'Обычно', slow: 'Медленно' }, s.speed)}</select></label>
      <label>Качество графики<select id="set-quality">${opt({ high: 'Высокое', medium: 'Среднее', low: 'Низкое' }, s.quality)}</select></label>
      <label class="check"><input type="checkbox" id="set-camera"${s.camera ? ' checked' : ''}> Динамическая камера в поединках</label>
      <label class="check"><input type="checkbox" id="set-sound"${s.sound ? ' checked' : ''}> Звук</label>
      <label>Зерно партии (пусто — случайное)<input id="set-seed" value="${esc(s.seed)}" autocomplete="off" placeholder="например, 42"></label>
      <div class="pbtns"><button class="pbtn primary" type="submit">Новая партия</button><button class="pbtn" type="button" data-i="menu">Закрыть</button>
        ${m.tableUrl ? `<a class="pbtn" href="${esc(m.tableUrl)}">2D-стол для отладки</a>` : ''}</div>
      <p class="fine">Правила — ядро v${esc(m.rulesVersion)} (GDD v0.1). Первым ходит тот, на кого выпал жребий. Зерно этой партии: ${esc(m.seed)}.</p>
    </form></div>`;
  }

  // ---------------------------------------------------------------- input

  bindInput() {
    const ui = this.ui;
    ui.addEventListener('click', e => {
      const el = e.target.closest('[data-i]');
      if (el && !el.disabled) { this.emit(el.dataset.i, el.dataset.x ?? null); return; }
      const unit = e.target.closest('[data-unit]');
      if (unit) { this.emit('unit', unit.dataset.unit); return; }
      const gate = e.target.closest('.hand [data-gate]');
      if (gate) this.emit('gate', gate.dataset.gate);
    });
    ui.addEventListener('change', e => {
      const id = e.target.id;
      if (id?.startsWith('set-')) this.emit('setting', { key: id.slice(4), value: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
    });
    ui.addEventListener('input', e => {
      if (e.target.id === 'set-seed') this.emit('setting', { key: 'seed', value: e.target.value });
    });
    ui.addEventListener('submit', e => { e.preventDefault(); this.emit('newGame'); });

    // Hand cards: tap to select, drag upward to play (Hearthstone style).
    ui.addEventListener('pointerdown', e => {
      const card = e.target.closest('.hand .card[data-card]');
      if (!card || e.button > 0) return;
      this.drag = { card, id: card.dataset.card, x: e.clientX, y: e.clientY, moved: false, pid: e.pointerId };
    });
    window.addEventListener('pointermove', e => {
      const d = this.drag;
      if (!d || e.pointerId !== d.pid) return;
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (!d.moved && Math.hypot(dx, dy) > 12) {
        if (!d.card.classList.contains('can')) { this.drag = null; return; }
        d.moved = true;
        d.card.classList.add('dragging');
      }
      if (d.moved) d.card.style.translate = `${dx}px ${dy}px`;
    });
    window.addEventListener('pointerup', e => {
      const d = this.drag;
      if (!d || e.pointerId !== d.pid) return;
      this.drag = null;
      if (!d.moved) { this.emit('card', d.id); return; }
      d.card.classList.remove('dragging');
      d.card.style.translate = '';
      if (e.clientY < window.innerHeight * 0.66) this.emit('dragPlay', d.id);
    });
  }
}

// Fan layout for a hand of n cards: spread, arc and tilt as CSS variables.
function fanStyle(i, n, top = false) {
  const mid = (n - 1) / 2, o = i - mid;
  const spread = Math.min(1, 7 / Math.max(n, 1));
  const rot = o * 5 * spread * (top ? -1 : 1);
  const y = Math.abs(o) ** 2 * 2.4 * spread * (top ? -1 : 1);
  return `--o:${o.toFixed(2)};--r:${rot.toFixed(2)}deg;--y:${y.toFixed(1)}px;--z:${i + 1}`;
}

