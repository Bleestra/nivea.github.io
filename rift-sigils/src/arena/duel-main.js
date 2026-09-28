// Hybrid duel client: a real-time round clock around the pure duel engine, the bot, animations and input.
// The engine decides everything; this file only keeps time, queues commands and waits for animations.
import * as D from '../duel/index.js';
import { CelestialWorld } from './celestial-world.js';
import { Fx } from './fx.js';
import { DuelStage } from './duel-stage.js';
import { DuelDirector } from './duel-director.js';
import { DuelHud } from './duel-hud.js';
import { Sfx } from './sfx.js';
import { portraitsFor } from './portraits.js';
import { preloadFighterModels } from './fighter-models.js';
import { esc, GLYPH } from '../web/text.js';

const STORE = 'rift-sigils:duel';
const SPEEDS = { fast: 1.7, normal: 1, slow: 0.7 };
const DECK_NAMES = Object.fromEntries(Object.entries(D.DUEL_DECKS).map(([k, d]) => [k, d.name]));
const coarse = window.matchMedia?.('(pointer: coarse)').matches;
const DEFAULTS = { you: 'attack', bot: 'answers', botKind: 'simple', speed: 'normal', quality: coarse ? 'medium' : 'high', sound: true, seed: '' };
const REASONS = { life: 'шкала жизни на нуле', 'no-colossi': 'не осталось бойцов', concede: 'сдача', 'round-limit': 'предел раундов' };

let settings = load();
const world = new CelestialWorld(document.getElementById('stage'), { quality: settings.quality });
world.renderer.toneMappingExposure = 0.95;
world.bloom.strength = 0.2;
world.bloom.threshold = 1.5;
world.speed = SPEEDS[settings.speed] ?? 1;
// Low side-on composition, with space reserved for the portrait rails and hand.
world.fitOverview = function fitDuel() {
  const aspect = this.camera.aspect;
  const distance = Math.max(42, 60 / Math.max(aspect, .6));
  this.overview.target.set(-3, 5.8, 0);
  this.overview.pos.set(distance, 17 + (distance - 42) * .15, 3);
  if (!this.focused) this.goOverview(true);
};
world.fitOverview();
const fx = new Fx(world);
const stage = new DuelStage(world, fx);
const sfx = new Sfx();
sfx.enabled = settings.sound;
const hud = new DuelHud(document.getElementById('hud'), world, onIntent);
const director = new DuelDirector({ world, fx, stage, hud, sfx, portraits: {} });
window.__duel = { world, stage, director, D, get game() { return game; } };

let game = null;
let sel = freshSel();
let busy = false;
let queue = Promise.resolve();
let clock = { round: 0, left: 0, total: 0, ending: false };
let botTimer = null, botPlan = { round: 0, thoughts: 0 };
let recordText = '', resultDismissed = false;

function freshSel(keep = {}) { return { cards: [], target: null, journal: keep.journal ?? false, menu: false }; }
function load() { try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORE) ?? '{}') }; } catch { return { ...DEFAULTS }; } }
function save() { try { localStorage.setItem(STORE, JSON.stringify(settings)); } catch { /* per-viewer convenience */ } }
const view = () => D.viewDuel(game.state, game.human);
const botSeat = () => (game.human === 'A' ? 'B' : 'A');

// ---------------------------------------------------------------- session

function newGame() {
  const seed = String(settings.seed).trim() || String(Date.now() % 1e9);
  const deck = k => structuredClone(D.DUEL_DECKS[k] ?? D.DUEL_DECKS.attack);
  const showcase = new URLSearchParams(location.search).get('fighters') === 'reference';
  const { record, state } = D.newDuelRecord({ seed, matchId: `duel-${seed}`, players: [{ name: 'Вы', deck: deck(showcase ? 'attack' : settings.you) }, { name: 'Бот', deck: deck(showcase ? 'answers' : settings.bot) }] });
  let opening = state;
  if (showcase) {
    // A playable showcase uses exactly the same validated commands as normal setup.
    const owner = ['A', 'B'].find(p => D.legalActions(opening, p).some(a => a.type === 'placeGate'));
    const gate = D.legalActions(opening, owner).find(a => a.type === 'placeGate');
    const placed = D.applyDuelRecorded(record, opening, { ...gate, player: owner });
    if (placed.ok) opening = placed.state;
    for (const player of ['A', 'B']) {
      const def = opening.players[player].entrant === 0 ? 'RS-C001' : 'RS-C011';
      const unit = opening.players[player].units.find(id => opening.units[id].def === def);
      const chosen = D.applyDuelRecorded(record, opening, { type: 'choose', player, unit });
      if (chosen.ok) opening = chosen.state;
    }
  }
  start(record, opening);
}

function start(record, state) {
  clearTimeout(botTimer);
  const human = state.players.A.entrant === 0 ? 'A' : 'B';
  game = { record, state, human, bot: D.DUEL_BOTS[settings.botKind] ?? D.simpleDuelBot, botRng: seededBotRng(record) };
  director.portraits = portraitsFor(Object.values(state.units).map(u => u.def));
  director.viewer = human;
  sel = freshSel(sel);
  busy = false;
  recordText = '';
  resultDismissed = false;
  clock = { round: 0, left: 0, total: 0, ending: false };
  botPlan = { round: 0, thoughts: 0 };
  queue = Promise.resolve();
  director.reset(view());
  if (record.commands.length) { refresh(); afterBatch(); return; }
  // a fresh match: the coin flip and the first bout are animated like any other batch
  busy = true;
  refresh();
  director.play(state.log, view()).then(() => { busy = false; refresh(); afterBatch(); });
}

function seededBotRng(record) {
  let x = 0;
  for (const ch of `${record.setup.seed}:bot`) x = (x * 31 + ch.charCodeAt(0)) >>> 0;
  return [x ^ 0x9e3779b9, x * 7 + 1, x * 13 + 5, x * 17 + 11].map(n => n >>> 0);
}

function commit(p, cmd) {
  queue = queue.then(async () => {
    if (!game || game.state.result) return;
    const before = view();
    const r = D.applyDuelRecorded(game.record, game.state, { ...cmd, player: p });
    if (!r.ok) {
      if (p === game.human) hud.toast(`Нельзя: ${r.error}`);
      return;
    }
    game.state = r.state;
    if (p === game.human) sel = freshSel(sel);
    busy = true;
    refresh(before);
    await director.play(r.events, view());
    busy = false;
    if (cmd.type === 'activate' && p === game.human) botPlan.react = true;
    refresh();
    afterBatch();
  }).catch(err => { console.error(err); busy = false; refresh(); });
}

function afterBatch() {
  const s = game.state;
  if (s.result) { clock.total = 0; refresh(); return; }
  if (s.phase === 'round' && clock.round !== s.round) clock = { round: s.round, left: s.timerMs, total: s.timerMs, ending: false };
  scheduleBot();
}

// The bot thinks a while into the round, and again after you play something.
function scheduleBot() {
  clearTimeout(botTimer);
  const s = game.state, p = botSeat();
  if (s.result || !D.legalActions(s, p).length) return;
  let delay = 900;
  if (s.phase === 'round') {
    if (botPlan.round !== s.round) botPlan = { round: s.round, thoughts: 0 };
    delay = botPlan.thoughts === 0 ? clock.total * (0.2 + Math.random() * 0.3) : 1400 + Math.random() * 1600;
    if (botPlan.react) { delay = Math.min(delay, 1500 + Math.random() * 1000); botPlan.react = false; }
  }
  botTimer = setTimeout(() => {
    if (busy) { scheduleBot(); return; }
    const a = game.bot(game.state, p, game.botRng);
    if (!a) return;
    if (game.state.phase === 'round') botPlan.thoughts++;
    commit(p, a);
  }, delay);
}

// The round clock runs only while nothing is animating, so nobody loses time to effects.
let last = performance.now();
setInterval(() => {
  const now = performance.now(), dt = now - last;
  last = now;
  if (!game || busy || game.state.result || game.state.phase !== 'round' || clock.round !== game.state.round) return;
  clock.left -= dt;
  hud.setClock(clock.left, clock.total);
  if (clock.left <= 0 && !clock.ending) {
    clock.ending = true;
    commit('system', { type: 'endRound' });
  }
}, 100);

function act(cmd) {
  if (busy || !game) return;
  sfx.unlock();
  commit(game.human, cmd);
}

// ---------------------------------------------------------------- HUD model

function modeOf(s) {
  if (s.result) return 'ended';
  const acts = D.legalActions(s, game.human);
  if (s.phase === 'gate' && acts.length) return 'gate';
  if (s.phase === 'choose' && acts.length) return 'choose';
  if (s.phase === 'round') return 'round';
  return 'wait';
}

function promptFor(v, mode) {
  if (busy || v.result) return null;
  const foe = v.players[game.human === 'A' ? 'B' : 'A'];
  if (mode === 'wait') {
    if (v.phase === 'gate') return { text: `${esc(foe.name)} выкладывает ворота…`, wait: true };
    if (v.phase === 'choose') return { text: 'Ждём, пока соперник выберет бойца…', wait: true };
    return null;
  }
  if (mode !== 'round') return null;
  const me = v.players[game.human];
  if (me.ready) return { text: 'Вы готовы. Ждём соперника или конца таймера.', wait: true };
  return v.round <= 1 && v.boutNo <= 1
    ? { text: 'Выберите карты · до 3 карт в слиянии · затем «Готов»', hint: 'Карты раскрываются и срабатывают в конце раунда.' }
    : null;
}

function journalLines(v) {
  const k = uid => { const u = v.units[uid]; return u ? `<b class="${u.owner === game.human ? 'me' : 'foe'}">${esc(D.COLOSSI[u.def].name)}</b>` : ''; };
  const who = p => (p === game.human ? 'вы' : esc(v.players[p].name));
  const card = d => `«${esc(D.CARDS[d].name)}»`;
  const gate = d => `«${esc(D.GATES[d].name)}»`;
  const acted = a => (a.kind === 'gate' ? 'открыть ворота' : `${a.fusion ? 'слияние ' : ''}${a.defs.map(card).join(' + ')}`);
  const out = [];
  for (const e of v.log) {
    switch (e.t) {
      case 'coin': out.push({ html: `Монетка: первыми ворота выкладывает ${who(e.first)}`, big: true }); break;
      case 'boutStart': out.push({ sep: `Бой ${e.n}` }); break;
      case 'gatePlaced': out.push({ html: e.gateDef ? `вы: закрытые ворота ${gate(e.gateDef)}` : `${who(e.player)}: ворота рубашкой вверх` }); break;
      case 'fighters': out.push({ html: `Бойцы: ${k(e.A)} и ${k(e.B)}` }); break;
      case 'gateRevealed': out.push({ html: `${who(e.owner)} открывает ворота ${gate(e.gateDef)} — ${D.GATE_KIND_NAMES[D.GATES[e.gateDef].kind].toLowerCase()}: ${esc(D.GATES[e.gateDef].text)}`, big: true }); break;
      case 'fighterReady': out.push({ html: `${k(e.unit)}: ${e.g} G` }); break;
      case 'roundStart': out.push({ sep: `Раунд ${e.round} · мана ${e.mana[game.human]} · ${Math.round(e.timerMs / 1000)} с` }); break;
      case 'activate': out.push({ html: e.kind === 'gate' ? 'вы: приказ открыть ворота' : e.defs ? `вы: ${acted(e)} за ${e.cost}` : `${who(e.player)}: скрытое действие` }); break;
      case 'roundEnd': out.push({ html: 'Конец раунда: вскрытие' }); break;
      case 'reveal': for (const a of e.actions) if (a.player !== game.human) out.push({ html: `${who(a.player)} сыграл: ${acted(a)}` }); break;
      case 'countered': out.push({ html: e.kind === 'gate' ? `Отменено открытие ворот (${who(e.player)})` : `Отменено: ${e.defs.map(card).join(' + ')} (${who(e.player)})` }); break;
      case 'recall': out.push({ html: `${k(e.unit)} возвращается в резерв` }); break;
      case 'gain': out.push({ html: `${k(e.unit)} +${e.amount} G${e.why === 'gateBonus' ? ' от ворот' : ''} → ${e.g}` }); break;
      case 'swap': out.push({ html: `Обмен силой: ${e.units.map(u => `${k(u)} ${e.g[u]} G`).join(', ')}` }); break;
      case 'reflected': out.push({ html: `Ловушка отражает ${card(e.def)} на бойца ${who(e.player) === 'вы' ? 'вашего' : 'соперника'}` }); break;
      case 'trapMissed': out.push({ html: `Ловушка ${gate(e.gate)} не сработала` }); break;
      case 'stealBlocked': out.push({ html: 'Кража силы не действует' }); break;
      case 'healBlocked': out.push({ html: 'Восстановление не действует' }); break;
      case 'mana': out.push({ html: `${who(e.player)}: ${e.amount > 0 ? '+' : '−'}${Math.abs(e.amount)} маны в следующем раунде` }); break;
      case 'boutEnd': if (e.gate && !e.gateOpened && e.gateDef) out.push({ html: `Ворота ${gate(e.gateDef)} так и не открылись и сгорели` }); break;
      case 'damage': out.push({ html: `${k(e.unit)} −${e.amount} G → ${e.g}${e.over ? `, <b class="bad">ушёл в минус на ${e.over}: −${e.over} жизни</b>` : ''}` }); break;
      case 'shield': out.push({ html: `${k(e.unit)}: щит ${e.shield}` }); break;
      case 'shieldAbsorb': out.push({ html: `${k(e.unit)}: щит поглотил ${e.amount}` }); break;
      case 'heal': out.push({ html: `${k(e.unit)} восстанавливает ${e.amount} G → ${e.g}` }); break;
      case 'attack': out.push({ html: `Атака: ${k(e.A.unit)} ${e.A.g} G — ${k(e.B.unit)} ${e.B.g} G${e.inverted ? ' (ловушка: теряет сильный)' : ''}`, big: true }); break;
      case 'knockout': out.push({ html: `${k(e.unit)} ${e.removed ? `удалён из игры (минус ${e.over})` : 'выбыл и вернулся в резерв'}`, big: true }); break;
      case 'matchEnd': out.push({ html: e.winner ? `Партия окончена: побеждает ${who(e.winner)} — ${REASONS[e.reason] ?? e.reason}` : 'Ничья', big: true }); break;
      default:
    }
  }
  return out;
}

function refresh(v = view()) {
  const s = game.state, mode = busy ? 'wait' : modeOf(s);
  const me = s.players[game.human];
  const acts = busy ? [] : D.legalActions(s, game.human);
  const singles = new Set(acts.filter(a => a.type === 'activate').flatMap(a => a.cards));
  const selKey = sel.cards.slice().sort().join();
  const targeting = sel.cards.some(c => D.CARDS[s.cards[c].def].ops.some(o => o[0] === 'counter'));
  const selLegal = acts.some(a => a.type === 'activate' && a.cards.slice().sort().join() === selKey && (a.target ?? null) === (targeting ? sel.target : null));
  const queue = { me: [], foe: [] };
  const foeActs = (v.bout?.queue ?? []).filter(a => a.player !== game.human);
  const hiddenName = id => `скрытое действие ${foeActs.findIndex(x => x.id === id) + 1}`;
  for (const a of v.bout?.queue ?? []) {
    if (a.player === game.human) queue.me.push({ ...a, targetName: a.target ? hiddenName(a.target) : '' });
    else queue.foe.push({ ...a, n: foeActs.indexOf(a) + 1 });
  }
  let gate = null;
  if (v.bout?.gate && s.phase !== 'gate') {
    const mine = v.bout.owner === game.human;
    const f = p => v.players[p].fighter && v.units[v.players[p].fighter];
    const bonusOf = u => (u && v.bout.gateDef ? D.GATES[v.bout.gateDef].bonus[D.ASPECTS.indexOf(D.COLOSSI[u.def].aspect)] : 0);
    gate = {
      def: v.bout.gateDef, mine, open: v.bout.gateOpen,
      ordered: mine && (v.bout.queue ?? []).some(a => a.kind === 'gate'),
      canOpen: acts.some(a => a.type === 'openGate'),
      bonus: v.bout.gateDef && f(game.human) && f(botSeat()) ? { me: bonusOf(f(game.human)), foe: bonusOf(f(botSeat())) } : null,
    };
  }
  const selCost = sel.cards.length ? D.activationCost(s, game.human, sel.cards) : 0;
  const selWhy = me.ready ? 'вы уже нажали «Готов»' : me.activations >= D.RULES.activationsPerRound ? 'активации в этом раунде закончились'
    : selCost > me.mana ? 'не хватает маны' : 'сейчас не сыграть';
  const w = v.result?.winner;
  hud.render({
    v, viewer: game.human, mode, sel, portraits: director.portraits, playableCards: [...singles], queue, targeting, gate,
    selCost, selLegal, selWhy, prompt: promptFor(v, mode),
    canReady: !busy && mode === 'round' && !me.ready, readyGlow: mode === 'round' && !me.ready && !singles.size,
    readyLabel: mode === 'round' ? (me.ready ? 'Ждём…' : 'Готов') : mode === 'ended' ? 'Конец' : 'Ждём',
    clock: { left: clock.round === s.round ? clock.left : 0, total: s.phase === 'round' ? clock.total : 0 },
    journal: journalLines(v), recordText, settings, deckNames: DECK_NAMES, rulesVersion: D.DUEL_RULES_VERSION,
    seed: game.record.setup.seed, classicUrl: window.RS_CLASSIC_URL ?? '',
    result: v.result && !resultDismissed ? {
      title: v.result.winner ? (w === game.human ? 'Победа' : 'Поражение') : 'Ничья',
      sub: `${REASONS[v.result.reason] ?? v.result.reason} · жизнь ${Math.max(0, v.players[game.human].life)} : ${Math.max(0, v.players[botSeat()].life)}`,
      cls: !w ? 'draw' : w === game.human ? 'win' : 'lose',
    } : null,
  });
}

// ---------------------------------------------------------------- intents

function onIntent(type, x) {
  sfx.unlock();
  if (!game) return;
  const s = game.state;
  switch (type) {
    case 'journal': sel.journal = !sel.journal; refresh(); break;
    case 'menu': sel.menu = !sel.menu; refresh(); break;
    case 'dismiss': resultDismissed = true; refresh(); break;
    case 'again': newGame(); break;
    case 'newGame': sel.menu = false; newGame(); break;
    case 'setting':
      settings[x.key] = x.value;
      save();
      if (x.key === 'speed') world.renderer.toneMappingExposure = 0.95;
world.bloom.strength = 0.2;
world.bloom.threshold = 1.5;
world.speed = SPEEDS[x.value] ?? 1;
      if (x.key === 'quality') world.setQuality(x.value);
      if (x.key === 'sound') sfx.enabled = x.value;
      break;
    case 'copy': {
      const text = JSON.stringify(game.record);
      const fallback = () => { recordText = text; refresh(); document.getElementById('rec')?.select(); };
      if (!navigator.clipboard?.writeText) { fallback(); break; }
      navigator.clipboard.writeText(text).then(() => hud.toast('Запись партии скопирована.'), fallback);
      break;
    }
    case 'gate': act({ type: 'placeGate', gate: x }); break;
    case 'choose': act({ type: 'choose', unit: x }); break;
    case 'ready': act({ type: 'ready' }); break;
    case 'openGate': act({ type: 'openGate' }); break;
    case 'clear': sel.cards = []; refresh(); break;
    case 'activate': act({ type: 'activate', cards: sel.cards.slice(), ...(sel.target ? { target: sel.target } : {}) }); break;
    case 'dragPlay': {
      const counter = D.CARDS[s.cards[x].def].ops.some(o => o[0] === 'counter');
      if (counter) { sel.cards = [x]; refresh(); hud.toast('Выберите скрытое действие соперника, которое отменить'); break; }
      act({ type: 'activate', cards: [x] });
      break;
    }
    case 'target': sel.target = sel.target === x ? null : x; refresh(); break;
    case 'card': {
      if (s.phase !== 'round' || busy) break;
      if (sel.cards.includes(x)) sel.cards = sel.cards.filter(c => c !== x);
      else if (sel.cards.length < D.RULES.fusionMax) sel.cards.push(x);
      if (!sel.cards.some(c => D.CARDS[s.cards[c].def].ops.some(o => o[0] === 'counter'))) sel.target = null;
      else hud.toast(`В слиянии не больше ${D.RULES.fusionMax} карт`);
      refresh();
      break;
    }
    default:
  }
}

// Hover over a fighter for its numbers.
const canvas = world.renderer.domElement;
canvas.addEventListener('pointermove', e => {
  if (!game || e.pointerType === 'touch') return;
  const hit = world.pick(e.clientX, e.clientY, director.pickables())[0];
  let o = hit?.object;
  while (o && !o.userData.unit) o = o.parent;
  if (!o) { hud.tip(''); return; }
  const u = game.state.units[o.userData.unit], k = D.COLOSSI[u.def];
  hud.tip(`<b>${esc(k.name)}</b> <span class="muted">(${u.owner === game.human ? 'ваш' : 'соперника'})</span><br><span class="asp-${k.aspect}">${GLYPH[k.aspect]} ${D.ASPECT_NAMES[k.aspect]}</span> · ${u.g} G из ${u.startG}${u.shield ? ` · щит ${u.shield}` : ''}<br><span class="muted">${esc(k.look)}</span><br>Уникальная карта: ${esc(D.CARDS[k.signature].name)} — ${esc(D.CARDS[k.signature].text)}`, e.clientX, e.clientY);
});
canvas.addEventListener('pointerdown', () => sfx.unlock());
canvas.addEventListener('pointerleave', () => hud.tip(''));

// ---------------------------------------------------------------- boot (keeps the match across live page updates)

function boot(data = {}) {
  if (data?.settings) settings = { ...DEFAULTS, ...data.settings };
  if (data?.duelRecord) {
    try { start(data.duelRecord, D.replayDuel(data.duelRecord)); return; } catch { /* older rules: start fresh */ }
  }
  newGame();
}

try { window.claude?.hot?.snapshot?.(() => ({ settings, duelRecord: game?.record })); } catch { /* not in an artifact */ }
const bootWithModels = data => preloadFighterModels().then(() => boot(data));
if (window.claude?.hot?.ready) window.claude.hot.ready(bootWithModels);
else bootWithModels(window.claude?.hot?.data ?? {});

