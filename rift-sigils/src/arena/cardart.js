// Hand cards in the Hearthstone manner: cost gem, arched art window, name banner, rules text, window ribbon.
// Art is a procedural sigil per ability (stable per id) with an icon for what the card does.
import { ABILITIES, ASPECT_NAMES, ASPECTS, COLOSSI, GATES, WINDOW_NAMES } from '../core/index.js';
import { esc, GLYPH } from '../web/text.js';

const KIND = {
  'RS-A001': 'up', 'RS-A002': 'up', 'RS-A003': 'blade', 'RS-A004': 'cleanse', 'RS-A005': 'up', 'RS-A006': 'up',
  'RS-A007': 'dispel', 'RS-A008': 'shield', 'RS-A009': 'move', 'RS-A010': 'down', 'RS-A011': 'aspect', 'RS-A012': 'dispel',
  'RS-A013': 'up', 'RS-A014': 'up', 'RS-A015': 'shield', 'RS-A016': 'silence', 'RS-A017': 'anchor', 'RS-A018': 'up',
  'RS-A019': 'move', 'RS-A020': 'up', 'RS-A021': 'cut', 'RS-A022': 'up', 'RS-A023': 'cleanse', 'RS-A024': 'swap',
  'RS-A025': 'shield', 'RS-A026': 'cleanse', 'RS-A027': 'up', 'RS-A028': 'aspect', 'RS-A029': 'up', 'RS-A030': 'dawn',
  'RS-A031': 'blade', 'RS-A032': 'silence', 'RS-A033': 'dispel', 'RS-A034': 'down', 'RS-A035': 'eye', 'RS-A036': 'counter',
  'RS-A037': 'up', 'RS-A038': 'up', 'RS-A039': 'draw', 'RS-A040': 'push', 'RS-A041': 'counter', 'RS-A042': 'up',
  'RS-A043': 'balance', 'RS-A044': 'draw', 'RS-A045': 'shield', 'RS-A046': 'up', 'RS-A047': 'recall', 'RS-A048': 'eye',
};

const ICON = {
  up: '<path d="M26 58 50 34 74 58M26 78 50 54 74 78"/>',
  down: '<path d="M26 42 50 66 74 42M26 22 50 46 74 22"/>',
  blade: '<path d="M50 10 58 60 50 68 42 60Z"/><path d="M32 66H68M50 68V90"/>',
  shield: '<path d="M50 12 79 24 75 56Q67 80 50 90 33 80 25 56L21 24Z"/><path d="M50 30V72"/>',
  dispel: '<circle cx="50" cy="50" r="30"/><path d="M28 50Q39 34 50 50T72 50"/>',
  cleanse: '<path d="M50 14Q74 46 72 62A22 22 0 0 1 28 62Q26 46 50 14Z"/>',
  move: '<path d="M16 50H82M66 34 82 50 66 66"/>',
  swap: '<path d="M18 38H78M64 24 78 38 64 52M82 62H22M36 48 22 62 36 76"/>',
  push: '<path d="M22 30V70M34 50H84M68 34 84 50 68 66"/>',
  aspect: '<circle cx="50" cy="50" r="32"/><path d="M50 18A16 16 0 0 1 50 50 16 16 0 0 0 50 82"/>',
  silence: '<circle cx="50" cy="50" r="32"/><path d="M28 28 72 72M34 50H66"/>',
  anchor: '<path d="M50 18V82M34 32H66M22 60Q50 96 78 60"/><circle cx="50" cy="16" r="6"/>',
  cut: '<rect x="12" y="38" width="32" height="24" rx="12"/><rect x="56" y="38" width="32" height="24" rx="12"/><path d="M44 28 56 72"/>',
  dawn: '<path d="M18 68H82M30 68A20 20 0 0 1 70 68M50 24V36M24 38 32 46M76 38 68 46"/>',
  eye: '<path d="M12 50Q50 16 88 50 50 84 12 50Z"/><circle cx="50" cy="50" r="12"/>',
  counter: '<circle cx="50" cy="50" r="32"/><path d="M27 73 73 27"/>',
  draw: '<rect x="24" y="22" width="36" height="50" rx="5"/><rect x="40" y="30" width="36" height="50" rx="5"/>',
  balance: '<path d="M50 18V84M22 32H78M22 32 12 58H32ZM78 32 68 58H88Z"/>',
  recall: '<path d="M74 34A28 28 0 1 0 78 58M74 18V36H56"/>',
};

function hash(s) {
  let h = 2166136261;
  for (const ch of s) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}

// Background sigil: rings, spokes and a polygon derived from the id, so every card looks different but stable.
function sigil(id) {
  const h = hash(id), spokes = 5 + (h % 7), sides = 3 + ((h >> 4) % 5), rot = (h >> 9) % 360;
  const poly = Array.from({ length: sides }, (_, i) => {
    const a = (i / sides) * Math.PI * 2;
    return `${50 + Math.cos(a) * 30},${50 + Math.sin(a) * 30}`;
  }).join(' ');
  const lines = Array.from({ length: spokes }, (_, i) => {
    const a = (i / spokes) * Math.PI * 2;
    return `<path d="M${50 + Math.cos(a) * 36} ${50 + Math.sin(a) * 36}L${50 + Math.cos(a) * 46} ${50 + Math.sin(a) * 46}"/>`;
  }).join('');
  return `<g class="sig" transform="rotate(${rot} 50 50)"><circle cx="50" cy="50" r="44"/><circle cx="50" cy="50" r="36" stroke-dasharray="3 5"/>${lines}<polygon points="${poly}"/></g>`;
}

export function abilityCard(def, { cost = null, cid = '', cls = '', style = '' } = {}) {
  const a = ABILITIES[def];
  const shown = cost ?? a.cost;
  const kind = KIND[def] ?? 'up';
  return `<div class="card asp-${a.aspect} win-${a.window} ${cls}" data-card="${cid}" style="${style}">
    <div class="card-face">
      <div class="art"><svg viewBox="0 0 100 100" aria-hidden="true">${sigil(def)}<g class="ico">${ICON[kind]}</g></svg></div>
      <div class="gem${shown !== a.cost ? (shown < a.cost ? ' cheaper' : ' dearer') : ''}"><span>${shown}</span></div>
      <div class="banner"><span>${esc(a.name)}</span></div>
      <div class="ctext">${esc(a.text)}</div>
      <div class="ribbon">${WINDOW_NAMES[a.window]}${a.tags.includes('counter') ? ' · отмена' : ''} · <span class="aspg">${GLYPH[a.aspect]}</span> ${ASPECT_NAMES[a.aspect]}</div>
    </div>
  </div>`;
}

export function gateCard(def, { gid = '', cls = '' } = {}) {
  const g = GATES[def];
  const bonus = ASPECTS.map((x, i) => `<span class="${g.bonus[i] ? '' : 'zero'} asp-${x}"><i>${GLYPH[x]}</i>${g.bonus[i]}</span>`).join('');
  return `<div class="card gatecard ${cls}" data-gate="${gid}">
    <div class="card-face">
      <div class="art"><svg viewBox="0 0 100 100" aria-hidden="true">${sigil(def)}</svg></div>
      <div class="banner"><span>${esc(g.name)}</span></div>
      <div class="bonus">${bonus}</div>
      <div class="ctext">${esc(g.rule)}</div>
      <div class="ribbon">Ворота</div>
    </div>
  </div>`;
}

export const backCard = (cls = '', style = '') => `<div class="card back ${cls}" style="${style}"><div class="card-face"><svg viewBox="0 0 100 100" aria-hidden="true">${sigil('back')}</svg></div></div>`;

export function colossusTile(def, { portrait = '', status = '', cls = '', uid = '', hold = 0 } = {}) {
  const c = COLOSSI[def];
  return `<button class="ctile asp-${c.aspect} ${cls}" type="button" data-unit="${uid}" title="${esc(c.name)}: ${esc(c.passive)}">
    <span class="pt">${portrait ? `<img src="${portrait}" alt="">` : `<i>${GLYPH[c.aspect]}</i>`}</span>
    <span class="cinfo"><b>${esc(c.name)}</b><span class="cbase"><i>${GLYPH[c.aspect]}</i> ${c.base}</span><span class="cstat">${status}</span></span>
  </button>`;
}

// ---------------------------------------------------------------- hybrid duel cards (rules v0.2)
import { CARDS as DUEL_CARDS, GATES as DUEL_GATES, GATE_KIND_NAMES } from '../duel/content.js';

const DUEL_ICON = { attack: 'blade', defense: 'shield', power: 'up', tactic: 'draw', counter: 'counter' };
const KIND_NAMES = { attack: 'Атака', defense: 'Защита', power: 'Сила', tactic: 'Тактика', counter: 'Отмена' };

export function duelCard(def, { cid = '', cls = '', style = '', cost = null } = {}) {
  const c = DUEL_CARDS[def];
  const kind = c.ops.some(o => o[0] === 'heal') && c.kind === 'defense' && !c.ops.some(o => o[0] === 'shield') ? 'cleanse' : DUEL_ICON[c.kind];
  const shown = cost ?? c.cost;
  const tag = c.unique ? 'уникальная' : c.once ? 'одноразовая' : KIND_NAMES[c.kind];
  return `<div class="card asp-${c.aspect} ${c.unique ? 'unique' : ''} ${cls}" data-card="${cid}" style="${style}">
    <div class="card-face">
      <div class="art"><svg viewBox="0 0 100 100" aria-hidden="true">${sigil(def)}<g class="ico">${ICON[kind]}</g></svg></div>
      <div class="gem${shown !== c.cost ? (shown < c.cost ? ' cheaper' : ' dearer') : ''}"><span>${shown}</span></div>
      <div class="banner"><span>${esc(c.name)}</span></div>
      <div class="ctext">${esc(c.text)}</div>
      <div class="ribbon">${esc(tag)} · <span class="aspg">${GLYPH[c.aspect]}</span> ${ASPECT_NAMES[c.aspect]}</div>
    </div>
  </div>`;
}

export function duelGateCard(def, { gid = '', cls = '' } = {}) {
  const g = DUEL_GATES[def];
  const bonus = ASPECTS.map((x, i) => `<span class="${g.bonus[i] ? '' : 'zero'} asp-${x}"><i>${GLYPH[x]}</i>${g.bonus[i]}</span>`).join('');
  return `<div class="card gatecard gk-${g.kind} ${cls}" data-gate="${gid}">
    <div class="card-face">
      <div class="art"><svg viewBox="0 0 100 100" aria-hidden="true">${sigil(def)}</svg></div>
      <div class="banner"><span>${esc(g.name)}</span></div>
      <div class="bonus">${bonus}</div>
      <div class="ctext">${esc(g.text)}</div>
      <div class="ribbon">Ворота · <b class="gkind">${GATE_KIND_NAMES[g.kind]}</b></div>
    </div>
  </div>`;
}

// A face-down gate: the back of a gate card, in the owner's colour.
export const duelGateBack = (cls = '') => `<div class="card back gateback ${cls}"><div class="card-face"><svg viewBox="0 0 100 100" aria-hidden="true">${sigil('back')}</svg><b>Ворота</b></div></div>`;
