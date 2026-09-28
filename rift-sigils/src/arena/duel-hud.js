// HUD of the hybrid duel. Renders a model prepared by duel-main.js and reports intents; it never decides rules.
import * as THREE from 'three';
import { ASPECTS, CARDS, COLOSSI, GATE_KIND_NAMES, GATES, RULES } from '../duel/content.js';
import { backCard, duelCard, duelGateBack, duelGateCard } from './cardart.js';
import { esc, GLYPH } from '../web/text.js';

const tmp = new THREE.Vector3();

function fan(i, n) {
  const o = i - (n - 1) / 2, spread = Math.min(1, 7 / Math.max(n, 1));
  return `--o:${o.toFixed(2)};--r:${(o * 5 * spread).toFixed(2)}deg;--y:${(Math.abs(o) ** 2 * 2.4 * spread).toFixed(1)}px;--z:${i + 1}`;
}

export class DuelHud {
  constructor(root, world, onIntent) {
    this.root = root;
    this.world = world;
    this.emit = onIntent;
    root.innerHTML = '<div class="labels"></div><div class="ui"></div><div class="fxl"></div><div class="tip" hidden></div>';
    this.labels = root.querySelector('.labels');
    this.ui = root.querySelector('.ui');
    this.fxl = root.querySelector('.fxl');
    this.tipEl = root.querySelector('.tip');
    this.cards = {};
    this.floats = new Set();
    this.prevHand = new Set();
    this.drag = null;
    world.onUpdate(() => this.place());
    this.bind();
  }

  // ---------------------------------------------------------------- fighter G cards anchored to the models

  setFighter(side, info) {
    this.cards[side]?.el.remove();
    if (!info) { delete this.cards[side]; return; }
    const el = document.createElement('div');
    el.className = `gcard ${side}`;
    this.labels.appendChild(el);
    this.cards[side] = { el, obj: info.obj, data: { ...info } };
    this.drawFighter(side);
  }

  patchFighter(side, patch) {
    const c = this.cards[side];
    if (!c) return;
    const before = c.data.g;
    Object.assign(c.data, patch);
    this.drawFighter(side);
    if (patch.g !== undefined && patch.g !== before) {
      c.el.querySelector('.gnum')?.animate([{ transform: 'scale(1.35)', color: patch.g > before ? '#6dffc0' : '#ff6b5e' }, { transform: 'scale(1)' }], { duration: 500 });
    }
  }

  drawFighter(side) {
    const { el, data: d } = this.cards[side];
    const k = COLOSSI[d.def];
    const top = Math.max(d.startG ?? k.g, d.g, 1);
    const gPct = Math.max(0, Math.min(100, (d.g / top) * 100));
    el.innerHTML = `<div class="gc-top"><span class="gc-pt asp-${k.aspect}">${d.portrait ? `<img src="${d.portrait}" alt="">` : `<i>${GLYPH[k.aspect]}</i>`}</span>
      <span class="gc-g"><span class="gnum">${Math.max(0, Math.round(d.g))}</span><small>G</small>${this.forecast(d)}</span></div>
      <div class="gc-name">${esc(k.name)}</div>
      <div class="gc-hp"><i style="width:${gPct}%"></i><span>сила ${Math.max(0, Math.round(d.g))} из ${Math.round(top)}</span></div>
      ${d.shield > 0 ? `<div class="gc-shield">щит ${Math.round(d.shield)}</div>` : ''}`;
  }

  // What this fighter's G becomes when the queued cards of the round take effect.
  forecast(d) {
    if (!d.preview) return '';
    if (d.preview.down) return '<em class="fc down">→ вылет</em>';
    const to = Math.round(d.preview.g);
    if (to === Math.round(d.g)) return '';
    return `<em class="fc ${to > d.g ? 'up' : 'dn'}">→ ${to}</em>`;
  }

  pulseQueue(id, cls = 'go') {
    const el = this.ui.querySelector(`.queue [data-q="${id}"]`);
    if (!el) return;
    el.classList.add(cls);
    el.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.12)' }, { transform: 'scale(1)' }], { duration: 380 });
  }

  place() {
    for (const [side, c] of Object.entries(this.cards)) {
      c.obj.getWorldPosition(tmp);
      const p = this.world.project(tmp);
      const dx = side === 'me' ? -1.12 : 0.12;
      c.el.style.transform = `translate(${p.x}px, ${p.y}px) translate(${dx * 100}%, -50%)`;
      c.el.style.visibility = p.visible ? 'visible' : 'hidden';
    }
    for (const f of this.floats) {
      f.obj.getWorldPosition(tmp);
      const p = this.world.project(tmp);
      f.el.style.transform = `translate(${p.x}px, ${p.y + f.dy}px) translate(-50%, -100%)`;
    }
  }

  popupAt(obj, text, cls = 'info') {
    const el = document.createElement('div');
    el.className = `pop ${cls}`;
    el.textContent = text;
    this.labels.appendChild(el);
    const f = { el, obj, dy: 0 };
    this.floats.add(f);
    const start = performance.now();
    const step = () => {
      const k = (performance.now() - start) / 1400;
      f.dy = -70 * k;
      el.style.opacity = String(k < 0.7 ? 1 : 1 - (k - 0.7) / 0.3);
      if (k < 1) requestAnimationFrame(step);
      else { el.remove(); this.floats.delete(f); }
    };
    requestAnimationFrame(step);
    // a hidden pane pauses requestAnimationFrame: make sure the popup still goes away
    setTimeout(() => { el.remove(); this.floats.delete(f); }, 1600);
  }

  // The life gauge drops as damage lands, before the next full render.
  flashLife(side, life) {
    const el = this.ui.querySelector(`.life.${side}`);
    if (!el) return;
    const pct = Math.max(0, life) / RULES.life * 100;
    el.querySelector('.lf-num').textContent = String(Math.max(0, life));
    el.querySelectorAll('.lf-bar i').forEach((seg, i) => { seg.className = (i + 1) * 10 <= pct + 0.001 ? 'on' : i * 10 < pct ? 'part' : ''; });
    el.animate([{ transform: 'translateX(-4px)' }, { transform: 'translateX(4px)' }, { transform: 'none' }], { duration: 260 });
  }

  // ---------------------------------------------------------------- transient effects

  banner(title, sub = '', seconds = 0.9) {
    const el = document.createElement('div');
    el.className = 'banner-fx';
    el.innerHTML = `<b>${esc(title)}</b>${sub ? `<span>${esc(sub)}</span>` : ''}`;
    this.fxl.appendChild(el);
    const ms = (seconds * 1000) / this.world.speed;
    el.animate([{ opacity: 0, transform: 'translate(-50%,-50%) scale(.92)' }, { opacity: 1, transform: 'translate(-50%,-50%) scale(1)', offset: 0.2 },
      { opacity: 1, offset: 0.75 }, { opacity: 0, transform: 'translate(-50%,-50%) scale(1.04)' }], { duration: ms });
    return new Promise(r => setTimeout(() => { el.remove(); r(); }, ms));
  }

  toast(text, ms = 1800) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = text;
    this.fxl.appendChild(el);
    el.animate([{ opacity: 0 }, { opacity: 1, offset: 0.1 }, { opacity: 1, offset: 0.85 }, { opacity: 0 }], { duration: ms });
    setTimeout(() => el.remove(), ms);
  }

  bubble(side, text) {
    const anchor = this.ui.querySelector(`.life.${side}`);
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    const el = document.createElement('div');
    el.className = `bubble ${side}`;
    el.textContent = text;
    // beside the life gauge, clear of the round queues (below it on narrow screens)
    const narrow = window.innerWidth <= 900;
    el.style.left = `${narrow ? r.left + r.width / 2 : side === 'me' ? r.right + 12 : r.left - 12}px`;
    el.style.top = `${narrow ? r.bottom + 8 : r.top + r.height / 2}px`;
    el.style.transform = narrow ? 'translateX(-50%)' : side === 'me' ? 'translateY(-50%)' : 'translate(-100%, -50%)';
    this.fxl.appendChild(el);
    el.animate([{ opacity: 0 }, { opacity: 1, offset: 0.15 }, { opacity: 1, offset: 0.8 }, { opacity: 0 }], { duration: 1100 });
    setTimeout(() => el.remove(), 1100);
  }

  // Played cards fly to the centre; a fusion shows its cards merging into one.
  async showActivation(e, side) {
    const holder = document.createElement('div');
    holder.className = `flyset${e.fusion ? ' fusion' : ''}`;
    holder.innerHTML = e.defs.map((d, i) => duelCard(d, { style: `--k:${i - (e.defs.length - 1) / 2}` })).join('') +
      (e.fusion ? `<b class="fusion-tag">Слияние · ${e.cost} маны</b>` : '');
    this.fxl.appendChild(holder);
    for (const cid of e.cards ?? []) {
      const el = this.ui.querySelector(`.hand .card[data-card="${cid}"]`);
      if (el) el.style.visibility = 'hidden';
    }
    const from = side === 'me' ? 'translate(-50%, 40vh) scale(.5)' : 'translate(-50%, -60vh) scale(.5)';
    const ms = (e.fusion ? 1500 : 1100) / this.world.speed;
    const frames = [
      { transform: from, opacity: 0.3 },
      { transform: 'translate(-50%, -50%) scale(1)', opacity: 1, offset: 0.25 },
      { transform: 'translate(-50%, -50%) scale(1)', opacity: 1, offset: 0.75 },
      { transform: 'translate(-50%, -50%) scale(.4)', opacity: 0 },
    ];
    const anim = holder.animate(frames, { duration: ms, easing: 'cubic-bezier(.2,.8,.2,1)' });
    await Promise.race([anim.finished.catch(() => {}), new Promise(r => setTimeout(r, ms + 100))]);
    holder.remove();
  }

  // The opponent played something: only a card back flies in, what it is stays hidden until the end of the round.
  async showHidden(side) {
    const holder = document.createElement('div');
    holder.className = 'flyset hidden-play';
    holder.innerHTML = `${backCard('', '--k:0')}<b class="fusion-tag">${side === 'me' ? 'Вы' : 'Соперник'} что-то сыграл</b>`;
    this.fxl.appendChild(holder);
    const from = side === 'me' ? 'translate(-50%, 40vh) scale(.5)' : 'translate(-50%, -60vh) scale(.5)';
    const ms = 1000 / this.world.speed;
    const anim = holder.animate([
      { transform: from, opacity: 0.3 },
      { transform: 'translate(-50%, -50%) scale(.8)', opacity: 1, offset: 0.3 },
      { transform: 'translate(-50%, -50%) scale(.8)', opacity: 1, offset: 0.7 },
      { transform: 'translate(80%, -120%) scale(.3)', opacity: 0 },
    ], { duration: ms, easing: 'cubic-bezier(.2,.8,.2,1)' });
    await Promise.race([anim.finished.catch(() => {}), new Promise(r => setTimeout(r, ms + 100))]);
    holder.remove();
  }

  // End of the round: the face-down chips in the queue panels turn over.
  revealQueue(actions) {
    for (const a of actions) {
      const el = this.ui.querySelector(`.queue [data-q="${a.id}"]`);
      if (!el || !el.classList.contains('hidden')) continue;
      el.classList.remove('hidden', 'pick');
      el.classList.toggle('fusion', a.fusion);
      el.innerHTML = a.kind === 'gate' ? '<span class="gopen">Открыть ворота</span>' : a.defs.map(d => `<span class="asp-${CARDS[d].aspect}">${esc(CARDS[d].name)}</span>`).join('<i>+</i>');
      el.animate([{ transform: 'rotateY(90deg)' }, { transform: 'rotateY(0deg)' }], { duration: 360 });
    }
  }

  // Everything both sides did this round, face up at once.
  async showReveal(actions, viewer, v) {
    const foe = actions.filter(a => a.player !== viewer), mine = actions.filter(a => a.player === viewer);
    if (!foe.length) return;
    const owner = v?.bout?.owner;
    const faces = a => (a.kind === 'gate'
      ? (a.player === owner && v?.bout?.gateDef ? duelGateCard(v.bout.gateDef, { cls: 'mini' }) : duelGateBack('mini'))
      : a.defs.map(d => duelCard(d)).join(''));
    const row = (list, who) => `<div class="rv-row"><span class="rv-who">${who}</span>${list.length ? list.map(a => `<div class="rv-act${a.fusion ? ' fusion' : ''}">${faces(a)}${a.kind === 'gate' ? '<small>открывает ворота</small>' : a.fusion ? '<small>слияние</small>' : ''}</div>`).join('') : '<em>ничего</em>'}</div>`;
    const el = document.createElement('div');
    el.className = 'revealset';
    el.innerHTML = `<b class="rv-title">Вскрытие</b>${row(foe, 'Соперник')}${row(mine, 'Вы')}`;
    this.fxl.appendChild(el);
    const ms = (1600 + 500 * actions.length) / this.world.speed;
    el.querySelectorAll('.rv-act').forEach((c, i) => c.animate([{ transform: 'rotateY(90deg)', opacity: 0 }, { transform: 'rotateY(0)', opacity: 1 }], { duration: 420, delay: 120 * i, fill: 'backwards' }));
    const anim = el.animate([{ opacity: 0 }, { opacity: 1, offset: 0.08 }, { opacity: 1, offset: 0.88 }, { opacity: 0 }], { duration: ms });
    await Promise.race([anim.finished.catch(() => {}), new Promise(r => setTimeout(r, ms + 100))]);
    el.remove();
  }

  tip(html, x, y) {
    if (!html) { this.tipEl.hidden = true; return; }
    this.tipEl.hidden = false;
    this.tipEl.innerHTML = html;
    const w = this.tipEl.offsetWidth, h = this.tipEl.offsetHeight;
    this.tipEl.style.left = `${Math.min(window.innerWidth - w - 8, x + 16)}px`;
    this.tipEl.style.top = `${Math.max(8, Math.min(window.innerHeight - h - 8, y - h / 2))}px`;
  }

  // The round clock ticks between renders.
  setClock(msLeft, total) {
    const el = this.ui.querySelector('.clock');
    if (!el) return;
    const k = total ? Math.max(0, msLeft) / total : 0;
    el.querySelector('.ring')?.setAttribute('stroke-dashoffset', String(163.4 * (1 - k)));
    const n = el.querySelector('.secs');
    if (n) n.textContent = total ? String(Math.ceil(Math.max(0, msLeft) / 1000)) : '—';
    el.classList.toggle('hurry', total > 0 && msLeft < 6000);
  }

  // ---------------------------------------------------------------- render

  render(m) {
    this.m = m;
    const { v, viewer } = m;
    const opp = viewer === 'A' ? 'B' : 'A';
    const me = v.players[viewer], foe = v.players[opp];
    const hand = me.hand ?? [];
    const fresh = new Set(hand.map(h => h.card).filter(id => !this.prevHand.has(id)));
    this.prevHand = new Set(hand.map(h => h.card));
    this.ui.classList.toggle('picking', m.sel.cards.length > 0);
    this.ui.innerHTML = `
      ${this.life(m, opp, 'foe')}
      ${this.life(m, viewer, 'me')}
      ${this.clock(m)}
      <div class="corner left"><button class="ibtn" type="button" data-i="journal">Журнал</button><button class="ibtn" type="button" data-i="menu">Меню</button></div>
      ${this.gatePanel(m)}
      ${this.queue(m, 'foe')}
      ${this.queue(m, 'me')}
      ${this.handHtml(m, hand, fresh)}
      ${this.fusionBar(m)}
      ${this.mana(me, m)}
      <button class="endturn${m.readyGlow ? ' glow' : ''}" type="button" data-i="ready" ${m.canReady ? '' : 'disabled'}>${esc(m.readyLabel)}</button>
      ${m.prompt ? `<div class="prompt${m.prompt.wait ? ' wait' : ''}"><div class="ptext">${m.prompt.text}</div>${m.prompt.hint ? `<div class="phint">${m.prompt.hint}</div>` : ''}</div>` : ''}
      ${m.sel.journal ? this.journal(m) : ''}
      ${this.overlay(m)}`;
    this.setClock(m.clock.left, m.clock.total);
  }

  life(m, p, side) {
    const pl = m.v.players[p];
    const pct = Math.max(0, pl.life) / RULES.life * 100;
    const segs = Array.from({ length: 10 }, (_, i) => `<i class="${(i + 1) * 10 <= pct + 0.001 ? 'on' : (i * 10 < pct ? 'part' : '')}"></i>`).join('');
    const name = side === 'me' ? 'Вы' : pl.name;
    return `<section class="life ${side}${pl.ready ? ' ready' : ''}" aria-label="шкала жизни ${esc(name)}">
      <div class="lf-emb"><svg viewBox="0 0 40 40" aria-hidden="true"><polygon points="20,2 36,11 36,29 20,38 4,29 4,11"/></svg><b>${esc(name.slice(0, 1))}</b></div>
      <div class="lf-body"><div class="lf-top"><span class="lf-name">${esc(name)}</span><span class="lf-num">${Math.max(0, pl.life)}</span></div>
        <div class="lf-bar" style="--pct:${pct}%">${segs}</div>
        <div class="lf-sub">${pl.units.map(u => `<span class="dot ${m.v.units[u].zone}" title="${esc(COLOSSI[m.v.units[u].def].name)}"></span>`).join('')}
          <span>рука ${pl.handCount} · колода ${pl.deckCount}</span>${pl.ready ? '<span class="rdy">готов</span>' : ''}</div></div>
    </section>`;
  }

  queue(m, side) {
    const items = m.queue[side];
    if (!items.length) return '';
    return `<div class="queue ${side}"><span class="qt">${side === 'me' ? 'вы сыграли · сработает в конце раунда' : 'соперник сыграл · скрыто до конца раунда'}</span>${items.map(a => {
      const body = a.hidden ? `<span class="qback" aria-hidden="true">?</span><span class="qh">Скрытое действие ${a.n}</span>`
        : a.kind === 'gate' ? '<span class="gopen">Открыть ворота</span>'
          : a.defs.map(d => `<span class="asp-${CARDS[d].aspect}">${esc(CARDS[d].name)}</span>`).join('<i>+</i>');
      return `<div class="qi${a.hidden ? ' hidden' : ''}${a.fusion ? ' fusion' : ''}" data-q="${a.id}">
        ${body}${a.counterNote ? `<small>${esc(a.counterNote)}</small>` : ''}</div>`;
    }).join('')}</div>`;
  }

  // The bout's gate: your own is known to you even while closed and opens by your order; the opponent's is a mystery.
  gatePanel(m) {
    const g = m.gate;
    if (!g) return '';
    if (!g.def) {
      return `<div class="gatebox foe"><span class="gk">Ворота соперника</span><b>Закрыты</b>
        <small>Бонус, поле или ловушка — откроются, когда соперник захочет.</small></div>`;
    }
    const gate = GATES[g.def];
    const bonus = g.bonus ? `<span class="gbon">при открытии: вашему бойцу +${g.bonus} G</span>` : '';
    const state = g.open ? '<span class="gst open">открыты</span>'
      : g.ordered ? '<span class="gst">откроются в конце раунда</span>'
        : g.mine ? '<span class="gst">закрыты · соперник не знает, что это</span>' : '';
    return `<div class="gatebox gk-${gate.kind}${g.mine ? ' mine' : ''}${g.open ? ' open' : ''}">
      <span class="gk"><span class="gown">${g.mine ? 'Ваши ворота' : 'Ворота соперника'} · </span><b>${GATE_KIND_NAMES[gate.kind]}</b></span>
      <b>${esc(gate.name)}</b><small>${esc(gate.text)}</small>${g.open ? '' : bonus}${state}
      ${g.canOpen ? '<button class="pbtn gate-open" type="button" data-i="openGate">Открыть ворота</button>' : ''}</div>`;
  }

  clock(m) {
    const v = m.v;
    const label = v.phase === 'round' ? `Раунд ${v.round}` : v.phase === 'gate' ? 'Ворота' : v.phase === 'choose' ? 'Выбор бойцов' : v.phase === 'ended' ? 'Конец' : '';
    return `<div class="clock" aria-label="таймер раунда"><svg viewBox="0 0 60 60" aria-hidden="true"><circle cx="30" cy="30" r="26" class="track"/><circle cx="30" cy="30" r="26" class="ring" stroke-dasharray="163.4" stroke-dashoffset="0"/></svg>
      <b class="secs">—</b><span class="clabel">${esc(label)} · бой ${v.boutNo}</span>
      ${v.bout?.gateDef ? `<span class="cgate">${esc(GATES[v.bout.gateDef].name)}</span>` : ''}</div>`;
  }

  mana(pl, m) {
    const cap = pl.manaMax || RULES.mana(Math.max(1, m.v.round));
    const gems = Array.from({ length: 10 }, (_, i) => `<i class="${i < pl.mana ? 'full' : i < cap ? 'spent' : 'locked'}"></i>`).join('');
    return `<div class="mana me"><span class="mnum">${pl.mana}/${cap}</span><span class="gems">${gems}</span></div>`;
  }

  handHtml(m, hand, fresh) {
    const playable = new Set(m.playableCards);
    return `<div class="hand" aria-label="рука">${hand.map((h, i) => duelCard(h.def, {
      cid: h.card, style: fan(i, hand.length),
      cls: `${playable.has(h.card) ? 'can' : ''}${m.sel.cards.includes(h.card) ? ' sel' : ''}${fresh.has(h.card) ? ' enter' : ''}`,
    })).join('')}</div>`;
  }

  fusionBar(m) {
    const n = m.sel.cards.length;
    if (!n) return '';
    const cost = m.selCost;
    const ok = m.selLegal;
    const label = n > 1 ? `Слияние ${n} карт` : 'Сыграть карту';
    return `<div class="fusionbar${n > 1 ? ' multi' : ''}"><span>${label} · ${cost} маны</span>
      <button class="pbtn primary" type="button" data-i="activate" ${ok ? '' : 'disabled'}>${n > 1 ? 'Слить и активировать' : 'Активировать'}</button>
      <button class="pbtn" type="button" data-i="clear">Сброс</button>
      ${!ok ? `<span class="why">${esc(m.selWhy)}</span>` : m.counterNote ? `<span class="note">${esc(m.counterNote)}</span>` : ''}</div>`;
  }

  journal(m) {
    const lines = m.journal.slice().reverse().map(l => (l.sep ? `<li class="sep">${esc(l.sep)}</li>` : `<li${l.big ? ' class="big"' : ''}>${l.html}</li>`)).join('');
    return `<aside class="journal"><header><b>Журнал</b><button class="ibtn" type="button" data-i="copy">Скопировать запись</button><button class="ibtn" type="button" data-i="journal">Закрыть</button></header>
      <ol>${lines}</ol>${m.recordText ? `<textarea readonly id="rec">${esc(m.recordText)}</textarea>` : ''}</aside>`;
  }

  overlay(m) {
    const { v, viewer } = m;
    if (m.sel.menu) return this.menu(m);
    if (m.result) {
      return `<div class="overlay result ${m.result.cls}"><div class="rbox"><h1>${esc(m.result.title)}</h1><p>${esc(m.result.sub)}</p>
        <div class="pbtns"><button class="pbtn primary" type="button" data-i="again">Ещё партия</button><button class="pbtn" type="button" data-i="menu">Настройки</button><button class="pbtn" type="button" data-i="dismiss">Смотреть арену</button></div></div></div>`;
    }
    if (m.mode === 'gate') {
      const gates = v.players[viewer].gates.filter(g => !g.used);
      return `<div class="overlay light"><div class="obox"><h2>Ваши ворота</h2><p>Выберите карту ворот: она ляжет в центр арены <b>закрытой</b> на весь бой. Соперник не узнает, что это. Открыть её можете только вы — в любом раунде, кнопкой «Открыть ворота»: при открытии ваш боец получает бонус своего аспекта, затем срабатывает эффект ворот. Бонус помогает вам, поле меняет правила, ловушка бьёт по сопернику. Если не откроете, с концом боя ворота вернутся к вам.</p>
        <div class="row wrap">${gates.map(g => `<div class="pick" data-i="gate" data-x="${g.gate}">${duelGateCard(g.def)}</div>`).join('')}</div></div></div>`;
    }
    if (m.mode === 'choose') {
      const gate = v.bout?.gateDef ? GATES[v.bout.gateDef] : null;
      const opts = v.players[viewer].units.filter(u => v.units[u].zone === 'reserve').map(uid => {
        const k = COLOSSI[v.units[uid].def];
        const bonus = gate ? gate.bonus[ASPECTS.indexOf(k.aspect)] : 0;
        return `<button class="ctile big asp-${k.aspect}" type="button" data-i="choose" data-x="${uid}">
          <span class="pt">${m.portraits[k.id] ? `<img src="${m.portraits[k.id]}" alt="">` : `<i>${GLYPH[k.aspect]}</i>`}</span>
          <span class="cinfo"><b>${esc(k.name)}</b><span class="cbase"><i>${GLYPH[k.aspect]}</i> ${k.g} G${bonus ? ` <em>+${bonus} при открытии ворот</em>` : ''}</span><span class="cstat">уникальная карта: ${esc(CARDS[k.signature].name)}</span></span></button>`;
      }).join('');
      const foe = v.players[viewer === 'A' ? 'B' : 'A'];
      const gateLine = gate ? `Ваши ворота «${esc(gate.name)}» (${GATE_KIND_NAMES[gate.kind].toLowerCase()}) лежат закрытыми. `
        : v.bout?.gate ? 'Ворота соперника закрыты: что под ними, вы узнаете, только когда он их откроет. ' : '';
      return `<div class="overlay light"><div class="obox small"><h2>Выбор бойца</h2>
        <p>${gateLine}${foe.fighter ? `Против вас остаётся ${esc(COLOSSI[v.units[foe.fighter].def].name)}.` : 'Соперник выбирает одновременно с вами, его выбор скрыт.'}</p>
        <div class="row wrap">${opts}</div></div></div>`;
    }
    return '';
  }

  menu(m) {
    const s = m.settings;
    const opt = (map, cur) => Object.entries(map).map(([k, l]) => `<option value="${k}"${k === cur ? ' selected' : ''}>${esc(l)}</option>`).join('');
    return `<div class="overlay"><form class="obox menu" id="menu-form"><h2>Печати Разлома</h2>
      <label>Ваша колода<select id="set-you">${opt(m.deckNames, s.you)}</select></label>
      <label>Колода бота<select id="set-bot">${opt(m.deckNames, s.bot)}</select></label>
      <label>Бот<select id="set-botKind">${opt({ simple: 'Простой: просчитывает атаку', random: 'Случайный' }, s.botKind)}</select></label>
      <label>Скорость анимаций<select id="set-speed">${opt({ fast: 'Быстро', normal: 'Обычно', slow: 'Медленно' }, s.speed)}</select></label>
      <label>Качество графики<select id="set-quality">${opt({ high: 'Высокое', medium: 'Среднее', low: 'Низкое' }, s.quality)}</select></label>
      <label class="check"><input type="checkbox" id="set-sound"${s.sound ? ' checked' : ''}> Звук</label>
      <label>Зерно партии (пусто — случайное)<input id="set-seed" value="${esc(s.seed)}" autocomplete="off" placeholder="например, 42"></label>
      <div class="pbtns"><button class="pbtn primary" type="submit">Новая партия</button><button class="pbtn" type="button" data-i="menu">Закрыть</button>
        ${m.classicUrl ? `<a class="pbtn" href="${esc(m.classicUrl)}">Классические правила</a>` : ''}</div>
      <p class="fine">Правила v${esc(m.rulesVersion)}: шкала жизни ${RULES.life}, до ${RULES.activationsPerRound} активаций за раунд, слияние до ${RULES.fusionMax} карт. Зерно: ${esc(m.seed)}.</p>
    </form></div>`;
  }

  // ---------------------------------------------------------------- input

  bind() {
    const ui = this.ui;
    ui.addEventListener('click', e => {
      const el = e.target.closest('[data-i]');
      if (el && !el.disabled) this.emit(el.dataset.i, el.dataset.x ?? null);
    });
    ui.addEventListener('change', e => {
      const id = e.target.id;
      if (id?.startsWith('set-')) this.emit('setting', { key: id.slice(4), value: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
    });
    ui.addEventListener('input', e => { if (e.target.id === 'set-seed') this.emit('setting', { key: 'seed', value: e.target.value }); });
    ui.addEventListener('submit', e => { e.preventDefault(); this.emit('newGame'); });
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
      if (e.clientY < window.innerHeight * 0.64) this.emit('dragPlay', d.id);
    });
  }
}
