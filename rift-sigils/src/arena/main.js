// 3D client: a match session on the rules core, played through the director and the HUD.
// Commands are queued; the HUD keeps showing the previous view until the animations of a command have finished.
import * as R from '../core/index.js';
import { World } from './world.js';
import { Fx } from './fx.js';
import { Field } from './field.js';
import { Director } from './director.js';
import { Hud } from './hud.js';
import { Sfx } from './sfx.js';
import { portraitsFor } from './portraits.js';
import { esc, GLYPH, namer, REASONS } from '../web/text.js';

const STORE = 'rift-sigils:arena';
const SPEEDS = { fast: { anim: 1.8, think: 200 }, normal: { anim: 1, think: 550 }, slow: { anim: 0.7, think: 1000 } };
const DECK_NAMES = { attack: R.PRESET_DECKS.attack.name, control: R.PRESET_DECKS.control.name, answers: R.PRESET_DECKS.answers.name, random: 'Случайная легальная колода' };
const coarse = window.matchMedia?.('(pointer: coarse)').matches;
const DEFAULTS = { you: 'attack', bot: 'answers', botKind: 'simple', speed: 'normal', quality: coarse ? 'medium' : 'high', camera: true, sound: true, seed: '' };

let settings = load();
const world = new World(document.getElementById('stage'), { quality: settings.quality });
world.speed = SPEEDS[settings.speed]?.anim ?? 1;
const fx = new Fx(world);
const field = new Field(world, fx);
const sfx = new Sfx();
sfx.enabled = settings.sound;
const hud = new Hud(document.getElementById('hud'), world, onIntent);
const director = new Director({ world, fx, field, hud, sfx, settings: () => settings });
// Debug handle for the console (camera experiments, scene inspection); not used by the game itself.
window.__arena = { world, field, fx, director, R, get game() { return game; }, act: a => act(a), acts: () => R.legalActions(game.state, game.human), get busy() { return busy; } };

let game = null;
let sel = freshSel();
let busy = false;
let queue = Promise.resolve();
let botTimer = null;
let options = [];
let targets = {};
let recordText = '';
let resultDismissed = false;

function freshSel(keep = {}) {
  return { card: null, unit: null, gate: null, mull: [], order: [], journal: keep.journal ?? false, menu: false, details: keep.details ?? false };
}
function load() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORE) ?? '{}') }; } catch { return { ...DEFAULTS }; }
}
function save() {
  try { localStorage.setItem(STORE, JSON.stringify(settings)); } catch { /* per-viewer convenience only */ }
}

// ---------------------------------------------------------------- session

function newGame() {
  clearTimeout(botTimer);
  const seed = String(settings.seed).trim() || String(Date.now() % 1e9);
  const rng = R.newBotRng(seed);
  const deck = key => (key === 'random' ? R.randomDeck(rng) : structuredClone(R.PRESET_DECKS[key]));
  const { record, state } = R.newRecord({ seed, matchId: `arena-${seed}`, players: [{ name: 'Вы', deck: deck(settings.you) }, { name: 'Бот', deck: deck(settings.bot) }] });
  start(record, state);
}

function start(record, state) {
  clearTimeout(botTimer);
  const human = state.players.A.entrant === 0 ? 'A' : 'B';
  const bot = R.BOTS[settings.botKind] ?? R.simpleBot;
  game = { record, state, human, bots: { A: human === 'A' ? null : bot, B: human === 'B' ? null : bot }, botRng: R.newBotRng(`${record.setup.seed}:${record.commands.length}`) };
  game.portraits = portraitsFor(Object.values(state.units).map(u => u.def));
  sel = freshSel(sel);
  busy = false;
  recordText = '';
  resultDismissed = false;
  queue = Promise.resolve();
  const v = view();
  director.reset(v);
  refresh();
  schedule();
}

const view = () => R.viewFor(game.state, game.human);

function commit(p, action) {
  queue = queue.then(async () => {
    if (!game || game.state.result) return;
    const before = view();
    const r = R.applyRecorded(game.record, game.state, { ...action, player: p });
    if (!r.ok) { hud.toast(`Движок отклонил действие (${r.error}).`); return; }
    game.state = r.state;
    if (p === game.human) sel = freshSel(sel);
    busy = true;
    refresh(before);
    const after = view();
    await director.play(r.events, after);
    busy = false;
    refresh();
    schedule();
  }).catch(err => {
    console.error(err);
    busy = false;
    refresh();
  });
}

function schedule() {
  clearTimeout(botTimer);
  if (!game || game.state.result) return;
  for (const p of ['A', 'B']) {
    if (p === game.human || !R.legalActions(game.state, p).length) continue;
    botTimer = setTimeout(() => {
      if (busy) { schedule(); return; }
      const a = game.bots[p](game.state, p, game.botRng);
      if (a) commit(p, a);
    }, SPEEDS[settings.speed]?.think ?? 550);
    return;
  }
}

function act(a) {
  if (busy || !a) return;
  sfx.unlock();
  commit(game.human, a);
}

// ---------------------------------------------------------------- what the HUD shows

function modeOf(v, acts) {
  if (!acts.length) return 'wait';
  switch (v.phase) {
    case 'setupGates': return 'gates';
    case 'mulligan': return 'mulligan';
    case 'choice': return v.choice?.kind === 'discard' ? 'discard' : 'arrange';
    case 'duel': return v.duel.step === 'support' ? 'support' : 'play';
    default: return 'play';
  }
}

function waitText(v) {
  if (v.phase === 'setupGates') return 'Соперник выкладывает ворота…';
  if (v.phase === 'mulligan') return 'Соперник решает, менять ли руку…';
  if (v.phase === 'duel') return v.duel.step === 'support' ? 'Соперник выбирает поддержку…' : 'Соперник думает над ответом…';
  return 'Ход соперника…';
}

function promptFor(v, acts, mode, N) {
  if (busy || v.result) return null;
  if (mode === 'wait') return { text: waitText(v), wait: true };
  const cardName = cid => `«${esc(R.ABILITIES[(v.players[game.human].hand ?? []).find(h => h.card === cid)?.def]?.name ?? '')}»`;
  if (mode === 'gates') {
    return sel.gate
      ? { text: 'Нажмите подсвеченное место на поле: карта ляжет рубашкой вверх.', buttons: [{ label: 'Другая карта', intent: 'cancel' }] }
      : { text: '<b>Выложите ворота.</b> Выберите карту ворот в руке.', hint: 'Порядок A–B–B–A–A–B. Первые две карты ложатся в центр, на сторону соперника.' };
  }
  if (mode !== 'play') return null;
  const inDuel = v.phase === 'duel';
  const hint = inDuel
    ? (v.duel.passes === 1 ? (v.duel.chain.length ? 'Соперник спасовал: ваш пас разрешит верхнюю карту цепочки.' : 'Соперник спасовал: ваш пас начнёт столкновение.')
      : v.duel.chain.length ? 'В цепочке есть карты: сейчас играются только Реакции.' : 'Цепочка пуста: можно Бой или Реакцию.')
    : v.turn?.prepPlayed ? 'Подготовка в этом ходу уже сыграна.' : 'Одна Подготовка, затем одно основное действие.';
  if (sel.card) {
    const mine = acts.filter(a => a.card === sel.card);
    const single = mine.length === 1 && !Object.keys(mine[0].targets).length;
    return single
      ? { text: `${cardName(sel.card)}: нажмите карту ещё раз или перетащите её вверх.`, hint, buttons: [{ label: 'Сыграть', intent: 'playSel', primary: true }, { label: 'Отмена', intent: 'cancel' }] }
      : { text: `${cardName(sel.card)}: выберите цель.`, hint, buttons: [{ label: 'Отмена', intent: 'cancel' }] };
  }
  if (sel.unit) {
    const extra = acts.filter(a => (a.type === 'recall' || a.type === 'capture') && a.unit === sel.unit)
      .map(a => ({ label: a.type === 'capture' ? 'Захватить печать' : 'Отозвать в резерв', intent: 'key', data: R.actionKey(a), primary: a.type === 'capture' }));
    const u = v.units[sel.unit];
    return {
      text: `${N.un(sel.unit)}: ${u.zone === 'reserve' ? 'выберите ворота для броска печати.' : 'выберите платформу для перемещения или атаки.'}`,
      hint: 'Соседняя платформа — 0 маны, дальняя — 1. Перемещение обнуляет удержание.',
      buttons: [...extra, { label: 'Отмена', intent: 'cancel' }],
    };
  }
  if (inDuel) return { text: '<b>Ваш приоритет.</b> Сыграйте карту или спасуйте.', hint };
  const capture = acts.find(a => a.type === 'capture');
  return {
    text: '<b>Ваш ход.</b> Выберите своего колосса или карту Подготовки.',
    hint,
    buttons: capture ? [{ label: `Захватить печать на ${v.units[capture.unit].platform}`, intent: 'key', data: R.actionKey(capture), primary: true }] : [],
  };
}

function optionsFor(acts, mode, N) {
  if (busy || mode !== 'play' || !sel.card) return [];
  const mine = acts.filter(a => a.card === sel.card);
  if (mine.length === 1 && !Object.keys(mine[0].targets).length) return [];
  return mine.map(a => ({ label: N.targets(a.targets) || 'Сыграть', action: a }));
}

function endButton(v, acts, mode) {
  if (v.result) return { label: 'Партия окончена', enabled: false };
  if (busy) return { label: '…', enabled: false };
  if (mode === 'play' && v.phase === 'duel') return { label: 'Пас', intent: 'pass', enabled: true, glow: true };
  if (mode === 'play') {
    const moves = acts.some(a => ['launch', 'move', 'capture', 'prep'].includes(a.type));
    return { label: 'Отдых', intent: 'rest', enabled: true, glow: !moves };
  }
  const label = { gates: 'Выкладка ворот', mulligan: 'Обмен руки', support: 'Поддержка', discard: 'Выбор карты', arrange: 'Выбор порядка' }[mode];
  return { label: label ?? (v.phase === 'duel' ? 'Ответ соперника' : 'Ход соперника'), enabled: false };
}

function resultFor(v) {
  if (!v.result || resultDismissed) return null;
  const w = v.result.winner;
  const title = v.result.void ? 'Матч аннулирован' : !w ? 'Ничья' : w === game.human ? 'Победа' : 'Поражение';
  return { title, sub: `${REASONS[v.result.reason] ?? v.result.reason} · печати ${v.players[game.human].sigils}:${v.players[game.human === 'A' ? 'B' : 'A'].sigils}`, cls: !w ? 'draw' : w === game.human ? 'win' : 'lose' };
}

function refresh(v = view()) {
  const s = game.state;
  const acts = busy ? [] : R.legalActions(s, game.human);
  const mode = busy ? 'wait' : modeOf(v, acts);
  const N = namer(v, game.human);
  options = optionsFor(acts, mode, N);
  hud.render({
    v, viewer: game.human, human: true, acts, mode, sel, N, portraits: game.portraits,
    costOf: def => (s.duel ? R.costOf(s, game.human, R.ABILITIES[def]) : R.ABILITIES[def].cost),
    prompt: promptFor(v, acts, mode, N), options, endBtn: endButton(v, acts, mode), settings,
    deckNames: DECK_NAMES, result: resultFor(v), recordText, tableUrl: window.RS_TABLE_URL ?? '', rulesVersion: R.RULES_VERSION,
    seed: game.record.setup.seed,
  });
  updateTargets(v, acts, mode);
}

// Platforms that a click would act on right now.
function updateTargets(v, acts, mode) {
  targets = {};
  const put = (q, a, text, hostile = false) => { if (!targets[q]) targets[q] = { a, text, hostile }; };
  for (const a of acts) {
    if (mode === 'gates' && a.type === 'placeGate' && a.gate === sel.gate) put(a.platform, a, 'сюда');
    if (mode === 'play' && sel.unit && (a.type === 'launch' || a.type === 'move') && a.unit === sel.unit) {
      const enemy = !!v.board[a.platform].unit;
      const far = a.type === 'move' && !R.adjacent(v.units[a.unit].platform, a.platform);
      put(a.platform, a, enemy ? 'атака' : a.type === 'launch' ? 'бросок' : far ? 'за 1 ману' : 'сюда', enemy);
    }
    if (mode === 'play' && sel.card && a.card === sel.card && a.targets?.platform) put(a.targets.platform, a, a.targets.unit ? 'сюда' : 'разведать');
  }
  field.setTargets(Object.fromEntries(Object.entries(targets).map(([q, t]) => [q, { hostile: t.hostile }])));
  hud.setCellHints(Object.entries(targets).map(([q, t]) => ({ obj: field.cards[q].holder, text: t.text, hostile: t.hostile })));
}

// ---------------------------------------------------------------- intents from the HUD

function tapCard(cid, dragged = false) {
  const v = view();
  const mode = modeOf(v, R.legalActions(game.state, game.human));
  if (busy || mode !== 'play') return;
  const mine = R.legalActions(game.state, game.human).filter(a => a.card === cid);
  if (!mine.length) {
    const def = R.ABILITIES[(v.players[game.human].hand ?? []).find(h => h.card === cid)?.def];
    const why = !def ? '' : v.phase !== 'duel' && def.window !== 'prep' ? 'Бой и Реакция играются только в поединке.'
      : v.phase === 'duel' && def.window === 'prep' ? 'Подготовка в поединке запрещена.'
        : v.phase === 'duel' && v.duel.priority !== game.human ? 'Сейчас приоритет у соперника.'
          : v.phase === 'duel' && def.window === 'battle' && v.duel.chain.length ? 'Бой нельзя играть поверх цепочки.'
            : 'Не хватает маны или нет законной цели.';
    hud.toast(`«${def?.name ?? ''}» сейчас не сыграть. ${why}`, 2200);
    return;
  }
  const single = mine.length === 1 && !Object.keys(mine[0].targets).length;
  if (single && (dragged || sel.card === cid)) { act(mine[0]); return; }
  sel.card = sel.card === cid && !dragged ? null : cid;
  sel.unit = null;
  refresh();
}

function onIntent(type, x) {
  sfx.unlock();
  if (!game) return;
  const acts = busy ? [] : R.legalActions(game.state, game.human);
  switch (type) {
    case 'journal': sel.journal = !sel.journal; refresh(); break;
    case 'menu': sel.menu = !sel.menu; refresh(); break;
    case 'details': sel.details = !sel.details; refresh(); break;
    case 'dismiss': resultDismissed = true; refresh(); break;
    case 'again': newGame(); break;
    case 'newGame': sel.menu = false; newGame(); break;
    case 'setting': {
      settings[x.key] = x.value;
      save();
      if (x.key === 'speed') world.speed = SPEEDS[x.value]?.anim ?? 1;
      if (x.key === 'quality') world.setQuality(x.value);
      if (x.key === 'sound') sfx.enabled = x.value;
      break;
    }
    case 'copy': {
      const text = JSON.stringify(game.record);
      const fallback = () => { recordText = text; refresh(); document.getElementById('rec')?.select(); };
      if (!navigator.clipboard?.writeText) { fallback(); break; }
      navigator.clipboard.writeText(text).then(() => hud.toast('Запись партии скопирована.'), fallback);
      break;
    }
    case 'cancel': sel = freshSel(sel); refresh(); break;
    case 'rest': act(acts.find(a => a.type === 'rest')); break;
    case 'pass': act(acts.find(a => a.type === 'pass')); break;
    case 'key': act(acts.find(a => R.actionKey(a) === x)); break;
    case 'opt': act(options[+x]?.action); break;
    case 'playSel': tapCard(sel.card, true); break;
    case 'card': tapCard(x); break;
    case 'dragPlay': tapCard(x, true); break;
    case 'gate': sel.gate = sel.gate === x ? null : x; refresh(); break;
    case 'unit': {
      if (!acts.some(a => a.unit === x && ['launch', 'move', 'recall', 'capture'].includes(a.type))) break;
      sel.unit = sel.unit === x ? null : x;
      sel.card = null;
      refresh();
      break;
    }
    case 'mull': sel.mull = sel.mull.includes(x) ? sel.mull.filter(c => c !== x) : [...sel.mull, x]; refresh(); break;
    case 'mullDone': act({ type: 'mulligan', cards: sel.mull.slice().sort() }); break;
    case 'discard': act(acts.find(a => a.type === 'discard' && a.card === x)); break;
    case 'order': if (!sel.order.includes(x)) sel.order.push(x); refresh(); break;
    case 'orderReset': sel.order = []; refresh(); break;
    case 'orderDone': act({ type: 'arrange', order: sel.order.slice() }); break;
    case 'support': act(acts.find(a => a.type === 'support' && (a.unit ?? '') === (x ?? ''))); break;
    default:
  }
}

// ---------------------------------------------------------------- pointer on the 3D stage

const canvas = world.renderer.domElement;
let down = null;

function hit(e) {
  const hits = world.pick(e.clientX, e.clientY, [...field.pickables(), ...director.pickables()]);
  for (const h of hits) {
    let o = h.object;
    while (o && !o.userData.unit && !o.userData.platform) o = o.parent;
    if (o?.userData.unit) return { unit: o.userData.unit };
    if (o?.userData.platform) return { platform: o.userData.platform };
  }
  return null;
}

function tipFor(h) {
  if (!game || !h) return '';
  const v = view();
  if (h.unit) {
    const u = v.units[h.unit], c = R.COLOSSI[u.def];
    const d = v.duel, power = d?.power?.[h.unit];
    const owner = u.owner === game.human ? 'ваш' : v.players[u.owner].name;
    return `<b>${esc(c.name)}</b> <span class="muted">(${esc(owner)})</span><br><span class="asp-${c.aspect}">${GLYPH[c.aspect]} ${esc(R.ASPECT_NAMES[c.aspect])}</span> · база ${c.base}${power ? ` · сила <b>${power.total}</b>` : ''}<br>${esc(c.passive)}<br><span class="muted">${esc(c.look)}</span>${u.zone === 'field' ? `<br>удержание ${u.hold}${u.hold >= 2 ? ' — можно захватить' : ''}` : ''}`;
  }
  const b = v.board[h.platform];
  if (!b?.gate) return '';
  const owner = b.gate.owner === game.human ? 'ваши' : v.players[b.gate.owner].name;
  if (!b.gate.def) return `<b>${h.platform}: закрытые ворота</b><br><span class="muted">владелец: ${esc(owner)}. Откроются при первом поединке здесь.</span>`;
  const g = R.GATES[b.gate.def];
  const bonus = R.ASPECTS.map((a, i) => `<span class="asp-${a}">${GLYPH[a]}${g.bonus[i]}</span>`).join(' ');
  return `<b>${h.platform}: ${esc(g.name)}</b> <span class="muted">(${esc(owner)}${b.gate.revealed ? '' : ', закрыты'})</span><br>${bonus}<br>${esc(g.rule)}`;
}

canvas.addEventListener('pointerdown', e => {
  sfx.unlock();
  down = { x: e.clientX, y: e.clientY };
});
canvas.addEventListener('pointermove', e => {
  if (!game || e.pointerType === 'touch') return;
  const h = hit(e);
  field.setHover(h?.platform ?? null);
  canvas.style.cursor = h && ((h.platform && targets[h.platform]) || (h.unit && ownActive(h.unit))) ? 'pointer' : 'default';
  hud.tip(tipFor(h), e.clientX, e.clientY);
});
canvas.addEventListener('pointerleave', () => hud.tip(''));
canvas.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 10 || !game) return;
  down = null;
  const h = hit(e);
  const v = view();
  const unitPlatform = h?.unit ? v.units[h.unit]?.platform : null;
  const q = h?.platform ?? (unitPlatform && targets[unitPlatform] ? unitPlatform : null);
  if (q && targets[q]) { hud.tip(''); act(targets[q].a); return; }
  if (h?.unit && ownActive(h.unit)) { onIntent('unit', h.unit); return; }
  if (e.pointerType === 'touch') hud.tip(tipFor(h), e.clientX, e.clientY);
  else if (!h && (sel.unit || sel.card || sel.gate)) { sel = freshSel(sel); refresh(); }
});

function ownActive(uid) {
  return !busy && R.legalActions(game.state, game.human).some(a => a.unit === uid && ['launch', 'move', 'recall', 'capture'].includes(a.type));
}

window.addEventListener('keydown', e => {
  if (e.key === 'Escape') { sel = freshSel(sel); refresh(); }
});

// ---------------------------------------------------------------- boot (keeps the match across live page updates)

function boot(data = {}) {
  if (data?.settings) settings = { ...DEFAULTS, ...data.settings };
  if (data?.record) {
    try { start(data.record, R.replay(data.record)); return; } catch { /* an older rules version: start fresh */ }
  }
  newGame();
}

try { window.claude?.hot?.snapshot?.(() => ({ settings, record: game?.record })); } catch { /* not in an artifact */ }
if (window.claude?.hot?.ready) window.claude.hot.ready(boot);
else boot(window.claude?.hot?.data ?? {});

