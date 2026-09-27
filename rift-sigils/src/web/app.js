// Presentation layer: renders viewFor(state, seat) and turns clicks into commands. It never evaluates rules itself:
// everything the player may do comes from legalActions(), every number shown comes from the view.
import * as R from '../core/index.js';
import { GLYPH, REASONS, esc, signed, namer as namerFor, eventLine } from './text.js';

const { COLOSSI, GATES, ABILITIES, ASPECTS, ASPECT_NAMES, WINDOW_NAMES, PRESET_DECKS } = R;
const DECKS = {
  attack: PRESET_DECKS.attack.name, control: PRESET_DECKS.control.name, answers: PRESET_DECKS.answers.name,
  random: 'Случайная легальная колода',
};
const SPEED = { fast: 150, normal: 500, slow: 1100 };
const DEFAULTS = { you: 'attack', bot: 'answers', botKind: 'simple', mode: 'human', seed: '', speed: 'normal' };
const STORE = 'rift-sigils:settings';

const root = document.getElementById('app');
root.innerHTML = '<header class="top" id="top"></header><div class="table" id="table"></div>';
const topEl = root.querySelector('#top');
const tableEl = root.querySelector('#table');

let settings = loadSettings();
let game = null;
let ui = freshUi();
let botTimer = null;

function freshUi(keep = {}) {
  return { unit: null, card: null, gate: null, mull: [], order: [], flash: '', options: [], acts: [],
    duelOnly: keep.duelOnly ?? false, record: '' };
}

function loadSettings() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORE) ?? '{}') }; } catch { return { ...DEFAULTS }; }
}
function saveSettings() {
  try { localStorage.setItem(STORE, JSON.stringify(settings)); } catch { /* storage may be unavailable */ }
}

// ---------------------------------------------------------------- game control

function newGame() {
  clearTimeout(botTimer);
  const seed = String(settings.seed).trim() || String(Date.now() % 1e9);
  const rng = R.newBotRng(seed);
  const deckFor = key => (key === 'random' ? R.randomDeck(rng) : structuredClone(PRESET_DECKS[key]));
  const human = settings.mode === 'human';
  const players = [
    { name: human ? 'Вы' : 'Бот 1', deck: deckFor(settings.you) },
    { name: human ? 'Бот' : 'Бот 2', deck: deckFor(settings.bot) },
  ];
  const { record, state } = R.newRecord({ seed, matchId: `local-${seed}`, players });
  startWith(record, state);
}

function startWith(record, state) {
  const human = settings.mode === 'human' ? (state.players.A.entrant === 0 ? 'A' : 'B') : null;
  const kind = R.BOTS[settings.botKind] ?? R.simpleBot;
  game = { record, state, human, botRng: R.newBotRng(`${record.setup.seed}:${record.commands.length}`),
    bots: { A: human === 'A' ? null : kind, B: human === 'B' ? null : kind } };
  ui = freshUi(ui);
  topEl.innerHTML = header();
  render();
  pump();
}

function act(p, action) {
  const r = R.applyRecorded(game.record, game.state, { ...action, player: p });
  if (!r.ok) {
    ui.flash = `Действие отклонено движком (${r.error}).`;
    render();
    return;
  }
  game.state = r.state;
  ui = freshUi(ui);
  render();
  pump();
}

function pump() {
  clearTimeout(botTimer);
  const s = game.state;
  if (s.result) return;
  for (const p of ['A', 'B']) {
    if (p === game.human || !R.legalActions(s, p).length) continue;
    botTimer = setTimeout(() => {
      const a = game.bots[p](game.state, p, game.botRng);
      if (a) act(p, a);
    }, SPEED[settings.speed] ?? SPEED.normal);
    return;
  }
}

const namer = v => namerFor(v, game.human);

// ---------------------------------------------------------------- rendering

function render() {
  const s = game.state;
  const viewer = game.human ?? 'A';
  const v = R.viewFor(s, viewer);
  const acts = game.human ? R.legalActions(s, game.human) : [];
  ui.acts = acts;
  const N = namer(v);
  const c = { s, v, viewer, acts, N, opp: R.other(viewer) };
  const handScroll = root.querySelector('.hand')?.scrollLeft ?? 0;
  const logScroll = root.querySelector('.journal')?.scrollTop ?? 0;
  tableEl.innerHTML = `
      <section class="center" aria-label="Стол">${prompt(c)}${arena(c)}${duelPanel(c)}${hand(c)}</section>
      <aside class="side" aria-label="Игроки">${player(c, c.opp)}${player(c, viewer)}</aside>
      <aside class="log" aria-label="Журнал">${journal(c)}${allActions(c)}${help()}</aside>`;
  const clock = root.querySelector('#clock');
  if (clock) clock.textContent = s.phase === 'setupGates' ? 'Выкладка ворот' : s.phase === 'mulligan' ? 'Обмен руки' : `Раунд ${s.round} · ход ${s.turnNo} из ${R.TURN_LIMIT}`;
  const h = root.querySelector('.hand');
  if (h) h.scrollLeft = handScroll;
  const j = root.querySelector('.journal');
  if (j) j.scrollTop = logScroll;
}

// Rendered once per match, so the new-game form keeps its focus and open state while the bots play.
function header() {
  const opt = (map, cur) => Object.entries(map).map(([k, label]) => `<option value="${k}"${k === cur ? ' selected' : ''}>${esc(label)}</option>`).join('');
  return `
    <div class="brand"><span class="title">Печати Разлома</span><span class="sub">ядро правил v${esc(R.RULES_VERSION)} · этап B</span></div>
    <span class="clock" id="clock"></span>
    <details class="newgame" id="ng">
      <summary>Новая партия</summary>
      <form class="ng-form" id="ng-form">
        <label for="ng-mode">Режим<select id="ng-mode">${opt({ human: 'Вы против бота', bots: 'Бот против бота' }, settings.mode)}</select></label>
        <label for="ng-you">Колода игрока 1 (вы в режиме против бота)<select id="ng-you">${opt(DECKS, settings.you)}</select></label>
        <label for="ng-bot">Колода игрока 2 (бот)<select id="ng-bot">${opt(DECKS, settings.bot)}</select></label>
        <label for="ng-kind">Бот<select id="ng-kind">${opt({ simple: 'Простой: считает ответы в поединке', random: 'Случайный: любое законное действие' }, settings.botKind)}</select></label>
        <label for="ng-speed">Темп бота<select id="ng-speed">${opt({ fast: 'Быстро', normal: 'Обычно', slow: 'Медленно' }, settings.speed)}</select></label>
        <label for="ng-seed">Зерно (пусто — случайное)<input id="ng-seed" value="${esc(settings.seed)}" placeholder="например, 42" autocomplete="off"></label>
        <div class="ng-row"><button class="btn primary" type="submit">Начать</button></div>
        <p class="prompt-hint">Кто ходит первым, решает жребий. Зерно ${esc(game.record.setup.seed)} повторит эту партию.</p>
      </form>
    </details>`;
}

function promptBox(cls, text, hint, buttons, extra = '') {
  return `<div class="prompt ${cls}" role="status">
    <div class="prompt-text">${text}</div>
    ${hint ? `<div class="prompt-hint">${hint}</div>` : ''}
    ${ui.flash ? `<div class="flash">${esc(ui.flash)}</div>` : ''}
    ${buttons ? `<div class="btns">${buttons}</div>` : ''}
    ${extra}
  </div>`;
}

const btn = (label, doIt, data = '', cls = '') => `<button class="btn ${cls}" type="button" data-do="${doIt}" ${data}>${label}</button>`;

function optionList(c, actions) {
  ui.options = actions;
  return `<div class="opts">${actions.map((a, i) => btn(c.N.action(a), 'opt', `data-i="${i}"`)).join('')}</div>`;
}

function prompt(c) {
  const { s, v, acts, N } = c;
  if (s.result) {
    const w = s.result.winner;
    const text = s.result.void ? 'Матч аннулирован' : !w ? 'Ничья' : game.human ? (w === game.human ? 'Победа' : 'Поражение') : `Победа: ${esc(v.players[w].name)}`;
    return promptBox('over', `<b>${text}</b> · ${esc(REASONS[s.result.reason] ?? s.result.reason)}. Печати ${v.players.A.sigils}:${v.players.B.sigils}.`,
      'Запись партии можно скопировать в журнале и воспроизвести тем же движком.', btn('Новая партия', 'new', '', 'primary'));
  }
  if (!game.human) {
    return promptBox('waiting', `Наблюдение: ${esc(v.players.A.name)} против ${esc(v.players.B.name)}.`, 'Боты видят только то, что видит игрок их места.', '');
  }
  if (!acts.length) {
    const d = v.duel;
    const text = s.phase === 'duel' && d?.step === 'cards' ? 'Приоритет у бота…'
      : s.phase === 'duel' ? 'Бот выбирает поддержку…'
        : s.phase === 'mulligan' ? 'Бот решает, менять ли руку…'
          : s.phase === 'setupGates' ? 'Бот выкладывает ворота…' : 'Ход бота…';
    return promptBox('waiting', text, '', '');
  }
  switch (s.phase) {
    case 'setupGates': {
      const hint = 'Порядок выкладки A–B–B–A–A–B. Первые две карты ложатся в центр, на сторону соперника; остальные — в любую свободную крайнюю клетку.';
      if (!ui.gate) return promptBox('', '<b>Выложите ворота</b> рубашкой вверх: выберите карту ворот внизу.', hint, '');
      return promptBox('', `<b>${N.gn(v.players[c.viewer].gatesToPlace.find(g => g.gate === ui.gate).def)}</b>: выберите подсвеченную клетку.`, hint, btn('Другая карта', 'cancel'));
    }
    case 'mulligan': {
      const n = ui.mull.length;
      return promptBox('', '<b>Стартовая рука.</b> Отметьте карты, которые хотите обменять, — один раз, любое число.',
        'Замены выдаются до того, как возвращённые карты уйдут в колоду: те же экземпляры сразу не вернутся.',
        n ? btn(`Обменять ${n}`, 'mull', '', 'primary') + btn('Сбросить отметки', 'cancel') : btn('Оставить руку', 'mull', '', 'primary'));
    }
    case 'choice': {
      if (s.choice.kind === 'discard') {
        return promptBox('', '<b>Тактический резерв:</b> выберите карту для сброса.', '', '', optionList(c, acts));
      }
      const cards = v.choice.cards.map(x => x.card);
      const picked = ui.order.map(cid => N.an(N.known[cid])).join(' → ');
      const rest = cards.filter(cid => !ui.order.includes(cid));
      const buttons = rest.map(cid => btn(N.an(N.known[cid]), 'order', `data-c="${cid}"`)).join('') +
        (ui.order.length ? btn('Заново', 'cancel', '', 'quiet') : '');
      return promptBox('', `<b>Чтение намерений:</b> нажимайте карты в порядке сверху вниз.${picked ? ` Сейчас: ${picked}.` : ''}`, '', buttons +
        (rest.length ? '' : btn('Готово', 'arrange', '', 'primary')));
    }
    case 'duel': {
      const d = v.duel;
      if (d.step === 'support') {
        const circle = GATES[v.board[d.platform].gate.def].id === 'RS-G006';
        return promptBox('', `<b>Поединок на ${d.platform}:</b> выберите союзника поддержки с соседней платформы или откажитесь.`,
          (circle ? '<b>Каменный круг:</b> здесь связь не даёт силы, но союзник всё равно уйдёт на восстановление. ' : '') +
          'Поддержка даёт +2 и обнуляет удержание союзника; после поединка он восстанавливается один свой ход. Выбор тайный, раскрывается одновременно.',
          '', optionList(c, acts));
      }
      const passes = d.passes, chain = d.chain.length;
      const next = passes === 1 ? (chain ? 'Соперник спасовал: ваш пас разрешит верхнюю карту цепочки.' : 'Соперник спасовал: ваш пас начнёт столкновение.')
        : (chain ? 'В цепочке есть карты: сейчас можно играть только Реакции.' : 'Цепочка пуста: можно играть Бой или Реакцию.');
      if (ui.card) {
        const mine = acts.filter(a => a.card === ui.card);
        return promptBox('', `<b>${N.an(N.known[ui.card])}</b>: выберите цель.`, next, btn('Отмена', 'cancel', '', 'quiet'), optionList(c, mine));
      }
      return promptBox('', '<b>Ваш приоритет.</b> Сыграйте карту из руки или спасуйте.', next, btn('Пас', 'pass', '', 'primary'));
    }
    case 'turn': {
      const hint = v.turn.prepPlayed ? 'Подготовка уже сыграна в этом ходу.' : 'Можно сыграть одну Подготовку, затем одно основное действие.';
      if (ui.card) {
        const mine = acts.filter(a => a.card === ui.card);
        return promptBox('', `<b>${N.an(N.known[ui.card])}</b>: выберите цель.`, 'Подготовка разрешается сразу, без окна ответа.',
          btn('Отмена', 'cancel', '', 'quiet'), optionList(c, mine));
      }
      if (ui.unit) {
        const extra = acts.filter(a => (a.type === 'recall' || a.type === 'capture') && a.unit === ui.unit);
        const u = v.units[ui.unit];
        return promptBox('', `Выбран ${N.un(ui.unit)}. ${u.zone === 'reserve' ? 'Нажмите платформу для запуска.' : 'Нажмите платформу для перемещения или атаки.'}`,
          'Соседняя клетка — 0 маны, несоседняя — 1. Любое перемещение обнуляет удержание.',
          extra.map(a => btn(N.action(a), 'opt2', `data-k="${esc(R.actionKey(a))}"`, a.type === 'capture' ? 'primary' : '')).join('') +
          btn('Отмена', 'cancel', '', 'quiet'));
      }
      const capture = acts.find(a => a.type === 'capture');
      return promptBox('', `<b>Ваш ход.</b> Выберите своего колосса на поле или в панели «Вы» либо карту Подготовки в руке.`, hint,
        (capture ? btn(N.action(capture), 'opt2', `data-k="${esc(R.actionKey(capture))}"`, 'primary') : '') + btn('Отдых', 'rest'));
    }
    default:
      return promptBox('', 'Ожидание.', '', '');
  }
}

// Cells that are valid click targets right now, with a short label.
function cellTargets(c) {
  const out = {};
  for (const a of c.acts) {
    if (a.type === 'placeGate' && a.gate === ui.gate) out[a.platform] = { a, hint: 'сюда' };
    if ((a.type === 'launch' || a.type === 'move') && a.unit === ui.unit) {
      const enemy = !!c.v.board[a.platform].unit;
      const far = a.type === 'move' && !R.adjacent(c.v.units[a.unit].platform, a.platform);
      out[a.platform] = { a, hint: enemy ? 'атака' : a.type === 'launch' ? 'запуск' : far ? '1 мана' : 'сюда' };
    }
  }
  return out;
}

function arena(c) {
  const { v, viewer } = c;
  const rows = viewer === 'A' ? ['1', '2'] : ['2', '1']; // your side is always at the bottom (GDD §05 mirroring)
  const cols = ['A', 'B', 'C'];
  const targets = cellTargets(c);
  const cells = [];
  rows.forEach((r, ri) => {
    cols.forEach((col, ci) => {
      cells.push(cell(c, col + r, targets[col + r]));
      if (ci < 2) cells.push(`<div class="link-h${v.board[col + r].removed || v.board[cols[ci + 1] + r].removed ? ' cut' : ''}" aria-hidden="true"></div>`);
    });
    if (ri === 0) {
      cols.forEach((col, ci) => {
        const cut = v.board[col + '1'].removed || v.board[col + '2'].removed;
        cells.push(`<div class="link-v${cut ? ' cut' : ''}" aria-hidden="true"></div>`);
        if (ci < 2) cells.push('<div aria-hidden="true"></div>');
      });
    }
  });
  const sideOf = r => (r === '1' ? 'B' : 'A');
  const caption = r => {
    const p = sideOf(r);
    return `<div class="row-caption"><span class="swatch" style="background:var(--${p === viewer ? 'me' : 'foe'})"></span>Ряд ${r} · сторона ${esc(c.N.who(p) === 'вы' ? 'ваша' : v.players[p].name)}</div>`;
  };
  return `<div class="arena-wrap">${caption(rows[0])}<div class="arena">${cells.join('')}</div>${caption(rows[1])}</div>`;
}

function bonusRow(def) {
  return `<div class="bonus">${ASPECTS.map((a, i) => {
    const n = GATES[def].bonus[i];
    return `<span class="${n ? '' : 'zero'}" title="${ASPECT_NAMES[a]}"><span class="asp ${a}">${GLYPH[a]}</span>${n}</span>`;
  }).join('')}</div>`;
}

function cell(c, q, target) {
  const { v, viewer, N } = c;
  const b = v.board[q];
  if (b.removed) {
    const e = [...v.log].reverse().find(x => x.t === 'sigil' && x.platform === q);
    return `<div class="cell gone"><div class="cell-head"><span class="qid">${q}</span><span class="tag plain">захвачено</span></div>
      <div class="gate"><span class="gate-name">${e ? esc(GATES[e.gateDef].name) : ''}</span><span>печать: ${e ? esc(N.who(e.player)) : ''}</span></div></div>`;
  }
  const d = v.duel;
  const cls = ['cell', target ? 'target' : '', d?.platform === q ? 'duel' : ''].join(' ');
  let gate = '<div class="gate closed">пусто</div>';
  if (b.gate) {
    const mine = b.gate.owner === viewer;
    const ownerTag = `<span class="tag ${mine ? 'me' : 'foe'}">${mine ? 'ваши' : esc(v.players[b.gate.owner].name)}</span>`;
    if (b.gate.def) {
      const state = b.gate.revealed ? 'открыты' : b.gate.scouted ? 'разведаны' : 'закрыты';
      gate = `<div class="gate"><span class="gate-name">${esc(GATES[b.gate.def].name)}</span>${bonusRow(b.gate.def)}
        <span class="gate-rule">${esc(GATES[b.gate.def].rule)}</span><span>${ownerTag} <span class="tag plain">${state}</span></span></div>`;
    } else {
      gate = `<div class="gate closed">Закрытые ворота<span>${ownerTag}</span></div>`;
    }
  }
  const units = [];
  if (d?.platform === q) units.push(token(c, d.attacker, 'нападает'), token(c, d.defender, 'защищается'));
  else if (b.unit) units.push(token(c, b.unit));
  const head = `<div class="cell-head"><span class="qid">${q}</span>${target ? `<span class="hint">${target.hint}</span>` : ''}</div>`;
  if (target) return `<button class="${cls}" type="button" data-do="cell" data-q="${q}" aria-label="${q}: ${target.hint}">${head}${gate}${units.join('')}</button>`;
  return `<div class="${cls}">${head}${gate}${units.join('')}</div>`;
}

function token(c, uid, role = '') {
  const { v, viewer } = c;
  const u = v.units[uid], def = COLOSSI[u.def];
  const selectable = c.acts.some(a => a.unit === uid && ['launch', 'move', 'recall', 'capture'].includes(a.type));
  const pips = u.zone === 'field' ? `<span class="pips" title="удержание">${'●'.repeat(Math.min(u.hold, 2))}${'○'.repeat(Math.max(0, 2 - u.hold))}</span>` : '';
  const anchor = u.zone === 'field' && (u.def === 'RS-C006' || u.anchorUntil !== null) ? '<span class="tag plain">якорь</span>' : '';
  const sup = v.duel && Object.values(v.duel.support).some(x => x?.unit === uid) ? '<span class="tag plain">поддержка</span>' : '';
  const inner = `<span class="tname">${esc(def.name)}</span>
    <span class="tmeta"><span class="asp ${def.aspect}">${GLYPH[def.aspect]}</span><span>${def.base}</span>${pips}${anchor}${sup}${role ? `<span>${role}</span>` : ''}</span>`;
  const cls = `token ${u.owner === viewer ? 'me' : 'foe'}${ui.unit === uid ? ' sel' : ''}`;
  if (selectable && !v.duel) return `<button class="${cls}" type="button" data-do="unit" data-u="${uid}">${inner}</button>`;
  return `<div class="${cls}">${inner}</div>`;
}

function duelPanel(c) {
  const { v, N, viewer } = c;
  const d = v.duel;
  if (!d) {
    const e = [...v.log].reverse().find(x => x.t === 'clash');
    if (!e) return '';
    return `<div class="duel"><div class="duel-head"><span class="eyebrow">Последний поединок · ${e.platform}</span></div>
      <div class="lead">${N.un(e.attacker.unit)} ${e.attacker.total} — ${N.un(e.defender.unit)} ${e.defender.total}. Победил ${N.un(e.winner)}.</div></div>`;
  }
  const gateDef = v.board[d.platform].gate.def;
  const fighter = (uid, role) => {
    const u = v.units[uid], p = u.owner, bd = d.power[uid];
    const st = [];
    if (d.shroud[uid]) st.push('Покров');
    if (d.silenced[uid]) st.push('Немота');
    if (d.aspect[uid]) st.push(`аспект: ${GLYPH[d.aspect[uid]]} ${ASPECT_NAMES[d.aspect[uid]]}`);
    if (u.def === 'RS-C004' && !d.sageUsed && role === 'Защитник') st.push('Мудрец: защита готова');
    const sp = d.support[p];
    if (sp) st.push(`поддержка: ${COLOSSI[v.units[sp.unit].def].name}${sp.suppressed ? ' (подавлена)' : ''}`);
    return `<div class="fighter ${p === viewer ? 'me' : 'foe'}">
      <span class="role">${role} · ${esc(N.who(p))}</span>
      <span class="fname">${esc(COLOSSI[u.def].name)}</span>
      <span class="power" aria-label="сила">${bd.total}</span>
      <div class="statuses">${st.map(x => `<span class="tag plain">${esc(x)}</span>`).join('')}</div>
      <ul class="parts">${bd.parts.map(x => `<li><span>${esc(x.label)}</span><span class="v ${x.value ? '' : 'zero'}">${signed(x.value)}</span></li>`).join('')}
        ${bd.raw < 0 ? '<li><span>Итог не ниже нуля</span><span class="v">0</span></li>' : ''}</ul>
    </div>`;
  };
  const a = d.power[d.attacker].total, b = d.power[d.defender].total;
  const mirror = gateDef === 'RS-G012';
  const leader = a !== b ? (a > b ? d.attacker : d.defender) : (mirror ? d.attacker : d.defender);
  const chain = d.chain.slice().reverse();
  const chainHtml = `<div class="chain"><span class="eyebrow">Цепочка${chain.length ? ' · сверху разрешается первой' : ''}</span>
    ${chain.length ? `<ol>${chain.map((o, i) => `<li class="${o.owner === viewer ? 'me' : 'foe'}${i === 0 ? ' top' : ''}">${N.an(o.def)} · ${esc(N.who(o.owner))} · ${o.cost} маны${N.targets(o.targets) ? `<br>${N.targets(o.targets)}` : ''}</li>`).join('')}</ol>` : '<span class="prompt-hint">пусто</span>'}
    ${d.step === 'cards' ? `<span class="lead">Приоритет: <b class="${d.priority === viewer ? 'me' : 'foe'}">${esc(N.who(d.priority))}</b> · пасов подряд ${d.passes}/2</span>` : '<span class="lead">Выбор поддержки…</span>'}
    <span class="lead">Сейчас впереди ${N.un(leader)}${a === b ? ' (равенство)' : ''}${chain.length ? '; цепочка ещё не разрешена' : ''}. Ответы ещё возможны.</span>
  </div>`;
  return `<section class="duel" aria-label="Поединок">
    <div class="duel-head"><span class="duel-title">Поединок на ${d.platform}</span>
      <span class="tag plain">${esc(GATES[gateDef].name)}</span>${d.aspectBonusOff ? '<span class="tag plain">бонусы аспектов отключены</span>' : ''}
      ${d.viaMove ? '<span class="tag plain">атака перемещением</span>' : ''}</div>
    <div class="duel-grid">${fighter(d.attacker, 'Нападающий')}${chainHtml}${fighter(d.defender, 'Защитник')}</div>
  </section>`;
}

function cardHtml(c, cid, def, { playable, marked, sel }) {
  const a = ABILITIES[def];
  const cost = c.s.duel ? R.costOf(c.s, c.viewer, a) : a.cost;
  const cls = ['card', playable ? 'playable' : 'dim', marked ? 'marked' : '', sel ? 'sel' : ''].join(' ');
  return `<button class="${cls}" type="button" data-do="card" data-c="${cid}"${playable ? '' : ' aria-disabled="true"'}>
    <span class="card-top"><span class="cost" title="стоимость">${cost}</span><span class="cname">${esc(a.name)}</span></span>
    <span class="cmeta"><span class="asp ${a.aspect}">${GLYPH[a.aspect]} ${ASPECT_NAMES[a.aspect]}</span> · ${WINDOW_NAMES[a.window]}${a.tags.includes('counter') ? ' · отмена' : ''}</span>
    <span class="ctext">${esc(a.text)}</span>
  </button>`;
}

function hand(c) {
  const { v, viewer, acts, s } = c;
  const me = v.players[viewer];
  if (s.phase === 'setupGates' && me.gatesToPlace?.length) {
    return `<section class="hand-wrap" aria-label="Ваши ворота"><div class="hand-head"><span class="eyebrow">Ваши ворота к выкладке</span></div>
      <div class="hand">${me.gatesToPlace.map(g => {
        const can = acts.some(a => a.gate === g.gate);
        return `<button class="card gatecard ${can ? 'playable' : 'dim'}${ui.gate === g.gate ? ' sel' : ''}" type="button" data-do="gate" data-g="${g.gate}">
          <span class="cname">${esc(GATES[g.def].name)}</span>${bonusRow(g.def)}<span class="ctext">${esc(GATES[g.def].rule)}</span></button>`;
      }).join('')}</div></section>`;
  }
  if (!me.hand) return '';
  const cards = me.hand.map(h => {
    const playable = s.phase === 'mulligan' || s.phase === 'choice' ? acts.length > 0
      : acts.some(a => a.card === h.card);
    return cardHtml(c, h.card, h.def, { playable, marked: ui.mull.includes(h.card), sel: ui.card === h.card });
  }).join('');
  const top = me.knownTop?.length ? ` · сверху колоды: ${me.knownTop.map(k => esc(ABILITIES[k.def].name)).join(' → ')}` : '';
  return `<section class="hand-wrap" aria-label="Ваша рука">
    <div class="hand-head"><span class="eyebrow">Рука ${me.hand.length}/8</span><span class="prompt-hint">Колода ${me.deckCount} · сброс ${me.discard.length}${top}</span></div>
    <div class="hand">${cards || '<span class="prompt-hint">Рука пуста.</span>'}</div>
  </section>`;
}

function player(c, p) {
  const { v, viewer, acts, N } = c;
  const pl = v.players[p];
  const mine = p === viewer;
  const units = pl.units.map(uid => {
    const u = v.units[uid], def = COLOSSI[u.def];
    const where = u.zone === 'reserve' ? 'готов в резерве'
      : u.zone === 'field' ? `на поле ${u.platform} · удержание ${u.hold}${u.hold >= 2 ? ' (зрелое)' : ''}`
        : `восстанавливается до своего хода ${u.readyOn}`;
    const inner = `<span class="uname"><span class="asp ${def.aspect}">${GLYPH[def.aspect]}</span> ${esc(def.name)} · ${def.base}</span>
      <span class="ustate">${where}</span><span class="ustate">${esc(def.passive)}</span>`;
    const can = mine && acts.some(a => a.unit === uid && ['launch', 'move', 'recall', 'capture'].includes(a.type));
    return `<li>${can ? `<button type="button" class="can${ui.unit === uid ? ' sel' : ''}" data-do="unit" data-u="${uid}">${inner}</button>` : `<div class="rowunit">${inner}</div>`}</li>`;
  }).join('');
  const sig = [0, 1, 2].map(i => `<span class="sigil${i < pl.sigils ? ' on' : ''}"></span>`).join('');
  const first = p === 'A' ? 'ходит первым' : 'ходит вторым';
  return `<section class="player ${mine ? 'me' : 'foe'}" aria-label="${esc(pl.name)}">
    <div class="player-head"><span class="pname">${esc(mine && game.human ? 'Вы' : pl.name)}</span><span class="seat" title="место">${p}</span><span class="prompt-hint">${first}</span></div>
    <dl class="stats">
      <dt>Печати</dt><dd><span class="sigils" aria-label="${pl.sigils} из 3">${sig}</span> ${pl.sigils}/3</dd>
      <dt>Мана</dt><dd>${c.s.round ? `${pl.mana} из ${Math.min(6, c.s.round + 1)}` : '—'}</dd>
      <dt>Рука</dt><dd>${pl.handCount}</dd>
      <dt>Колода</dt><dd>${pl.deckCount}</dd>
      <dt>Ход №</dt><dd>${pl.turnIndex}</dd>
    </dl>
    <ul class="roster">${units}</ul>
    <details class="pile"><summary>Сброс: ${pl.discard.length}</summary>${pl.discard.length ? `<ul>${pl.discard.map(x => `<li>${esc(ABILITIES[x.def].name)}</li>`).join('')}</ul>` : ''}</details>
  </section>`;
}

function journal(c) {
  const { v, N } = c;
  let events = v.log;
  if (ui.duelOnly) {
    const start = [...events].reverse().find(e => e.t === 'duelStart');
    if (start) {
      const end = events.find(e => e.seq > start.seq && e.t === 'duelEnd');
      events = events.filter(e => e.seq >= start.seq && (!end || e.seq <= end.seq));
    } else events = [];
  }
  const lines = [];
  for (const e of events) {
    const l = eventLine(N, v, e);
    if (!l) continue;
    lines.push(l.sep ? `<li class="sep">${esc(l.sep)}</li>` : `<li${l.big ? ' class="big"' : ''}>${l.html}</li>`);
  }
  lines.reverse();
  return `<section class="panel" aria-label="Журнал">
    <div class="panel-head"><span class="panel-title">Журнал</span>
      <label for="duel-only"><input type="checkbox" id="duel-only"${ui.duelOnly ? ' checked' : ''}> только последний поединок</label></div>
    <ol class="journal">${lines.join('') || '<li class="prompt-hint">Пока пусто.</li>'}</ol>
    <div class="btns">${btn('Скопировать запись партии', 'copy', '', 'quiet')}</div>
    ${ui.record ? `<textarea class="record-out" id="record-out" readonly>${esc(ui.record)}</textarea>` : ''}
  </section>`;
}

function allActions(c) {
  if (!game.human || !c.acts.length) return '';
  return `<details class="panel allacts"><summary>Все допустимые действия (${c.acts.length})</summary>
    <div class="opts">${c.acts.map((a, i) => btn(c.N.action(a), 'act', `data-i="${i}"`)).join('')}</div></details>`;
}

function help() {
  return `<details class="panel help"><summary>Коротко о правилах</summary><ul>
    <li>Побеждает тот, кто первым получит три печати. Печать дают победа в поединке на воротах или захват удержанием.</li>
    <li>Ход: не более одной Подготовки, затем одно основное действие — запуск, перемещение, отзыв, захват или отдых.</li>
    <li>Мана раунда: 2, 3, 4, 5, 6, дальше 6. Потраченная на ответ в чужой ход не вернётся до следующего раунда.</li>
    <li>Поединок: ворота открываются, стороны тайно выбирают поддержку (+2), затем цепочка карт. Сыгранная последней разрешается первой.</li>
    <li>Два паса подряд разрешают верхнюю карту цепочки; при пустой цепочке — столкновение. Равенство выигрывает защитник.</li>
    <li>Удержание: колосс, простоявший два окончания ходов соперника, может захватить печать своим основным действием.</li>
  </ul></details>`;
}

// ---------------------------------------------------------------- input

function perform(a) {
  act(game.human, a);
}

function onClick(e) {
  const el = e.target.closest('[data-do]');
  if (!el || !game) return;
  const d = el.dataset;
  const s = game.state;
  ui.flash = '';
  switch (d.do) {
    case 'new': {
      const ng = root.querySelector('#ng');
      ng.open = true;
      ng.scrollIntoView({ block: 'nearest' });
      return;
    }
    case 'cancel': ui.unit = null; ui.card = null; ui.gate = null; ui.mull = []; ui.order = []; render(); return;
    case 'rest': perform({ type: 'rest' }); return;
    case 'pass': perform({ type: 'pass' }); return;
    case 'opt': perform(ui.options[+d.i]); return;
    case 'act': perform(ui.acts[+d.i]); return;
    case 'opt2': perform(ui.acts.find(a => R.actionKey(a) === d.k)); return;
    case 'mull': perform({ type: 'mulligan', cards: ui.mull.slice().sort() }); return;
    case 'order': ui.order.push(d.c); render(); return;
    case 'arrange': perform({ type: 'arrange', order: ui.order.slice() }); return;
    case 'gate': ui.gate = ui.gate === d.g ? null : d.g; render(); return;
    case 'unit':
      ui.card = null;
      ui.unit = ui.unit === d.u ? null : d.u;
      render();
      return;
    case 'cell': {
      const t = cellTargets({ acts: ui.acts, v: R.viewFor(s, game.human) })[d.q];
      if (t) perform(t.a);
      return;
    }
    case 'card': {
      if (s.phase === 'mulligan') {
        ui.mull = ui.mull.includes(d.c) ? ui.mull.filter(x => x !== d.c) : [...ui.mull, d.c];
        render();
        return;
      }
      if (s.phase === 'choice' && s.choice?.kind === 'discard') {
        const a = ui.acts.find(x => x.type === 'discard' && x.card === d.c);
        if (a) perform(a);
        return;
      }
      const mine = ui.acts.filter(a => a.card === d.c);
      if (!mine.length) {
        ui.flash = 'Эту карту сейчас сыграть нельзя: не то окно, не хватает маны или нет законной цели.';
        render();
        return;
      }
      ui.unit = null;
      if (mine.length === 1 && Object.keys(mine[0].targets).length === 0 && ui.card === d.c) { perform(mine[0]); return; }
      ui.card = ui.card === d.c ? null : d.c;
      render();
      return;
    }
    case 'copy': {
      const text = JSON.stringify(game.record);
      const fallback = () => { ui.record = text; render(); root.querySelector('#record-out')?.select(); };
      if (!navigator.clipboard?.writeText) { fallback(); return; }
      navigator.clipboard.writeText(text).then(() => showToast('Запись партии скопирована.'), fallback);
      return;
    }
    default:
  }
}

function showToast(text) {
  ui.flash = '';
  const p = root.querySelector('.prompt-text');
  if (p) p.insertAdjacentHTML('afterend', `<div class="prompt-hint">${esc(text)}</div>`);
}

root.addEventListener('click', onClick);
root.addEventListener('input', e => {
  if (e.target.id === 'ng-seed') { settings.seed = e.target.value; saveSettings(); }
});
root.addEventListener('change', e => {
  const id = e.target.id;
  if (id === 'duel-only') { ui.duelOnly = e.target.checked; render(); return; }
  const key = { 'ng-mode': 'mode', 'ng-you': 'you', 'ng-bot': 'bot', 'ng-kind': 'botKind', 'ng-speed': 'speed', 'ng-seed': 'seed' }[id];
  if (!key) return;
  settings[key] = e.target.value;
  saveSettings();
  if (key === 'speed') pump();
});
root.addEventListener('submit', e => {
  e.preventDefault();
  const seed = root.querySelector('#ng-seed');
  if (seed) settings.seed = seed.value;
  saveSettings();
  newGame();
});

// ---------------------------------------------------------------- boot (keeps the match across live page updates)

function start(data = {}) {
  if (data?.settings) settings = { ...DEFAULTS, ...data.settings };
  if (data?.record) {
    try {
      startWith(data.record, R.replay(data.record));
      return;
    } catch { /* the record came from an older rules version: start fresh */ }
  }
  newGame();
}

try { window.claude?.hot?.snapshot?.(() => ({ settings, record: game?.record })); } catch { /* not in an artifact */ }
if (window.claude?.hot?.ready) window.claude.hot.ready(start);
else start(window.claude?.hot?.data ?? {});
