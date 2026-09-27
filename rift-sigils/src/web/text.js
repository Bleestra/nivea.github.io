// Shared wording for both clients: names as the viewer knows them, action labels, journal lines.
import { ABILITIES, ASPECT_NAMES, COLOSSI, GATES, adjacent, TURN_LIMIT } from '../core/index.js';

export const GLYPH = { fire: '▲', tide: '≈', stone: '■', wind: '◆', light: '✦', shadow: '◐', neutral: '○' };
export const REASONS = {
  sigils: 'три печати', idle: 'три хода без ввода', concede: 'сдача',
  'turn-limit-sigils': 'предел 36 ходов, решили печати', 'turn-limit-holds': 'предел 36 ходов, решили зрелые удержания',
  'turn-limit-draw': 'предел 36 ходов, ничья', 'resolution-limit': 'ошибка контента, матч аннулирован',
};
export const esc = x => String(x).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const signed = n => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : '0');

export function namer(v, human) {
  const viewer = v.viewer;
  const sameDef = uid => Object.entries(v.units).some(([id, u]) => id !== uid && u.def === v.units[uid].def);
  const who = p => (human && p === viewer ? 'вы' : v.players[p].name);
  const Who = p => { const w = who(p); return w[0].toUpperCase() + w.slice(1); };
  const side = p => (p === viewer ? 'me' : 'foe');
  const un = uid => {
    const u = v.units[uid];
    const tail = sameDef(uid) ? ` (${human && u.owner === viewer ? 'ваш' : v.players[u.owner].name})` : '';
    return `<b class="${side(u.owner)}">${esc(COLOSSI[u.def].name + tail)}</b>`;
  };
  const an = def => `«${esc(ABILITIES[def].name)}»`;
  const gn = def => `«${esc(GATES[def].name)}»`;
  const known = {};
  for (const p of ['A', 'B']) {
    for (const c of [...(v.players[p].hand ?? []), ...v.players[p].discard, ...(v.players[p].knownTop ?? [])]) known[c.card] = c.def;
  }
  for (const c of v.duel?.chain ?? []) known[c.card] = c.def;
  for (const c of v.choice?.cards ?? []) known[c.card] = c.def;
  const modText = id => {
    const m = v.duel?.mods.find(x => x.id === id);
    return m ? `${signed(m.amount)} от ${an(m.def)}` : 'модификатор';
  };
  const chainText = oid => {
    const c = v.duel?.chain.find(x => x.oid === oid);
    return c ? `${an(c.def)} (${who(c.owner)})` : 'карту в цепочке';
  };
  const targets = t => {
    if (!t) return '';
    const out = [];
    if (t.unit && t.platform) out.push(`${un(t.unit)} → ${t.platform}`);
    else if (t.unit) out.push(un(t.unit));
    if (t.units) out.push(t.units.map(un).join(' ⇄ '));
    if (t.platform && !t.unit) out.push(`закрытые ворота на ${t.platform}`);
    if ('mod' in t) out.push(t.mod ? `снять ${modText(t.mod)}` : 'без снятия модификатора');
    if ('own' in t) out.push(t.own ? `у своего снять ${modText(t.own)}` : 'у своего нечего снимать');
    if ('enemy' in t) out.push(t.enemy ? `у врага снять ${modText(t.enemy)}` : 'у врага нечего снимать');
    if (t.shroud) out.push('снять Покров');
    if (t.object) out.push(`отменить ${chainText(t.object)}`);
    if (t.aspect) out.push(`аспект ${GLYPH[t.aspect]} ${ASPECT_NAMES[t.aspect]}`);
    if (t.discard) out.push(`сбросить ${known[t.discard] ? an(known[t.discard]) : 'карту'}`);
    return out.join(', ');
  };
  const action = a => {
    switch (a.type) {
      case 'placeGate': return `Ворота ${gn(v.players[viewer].gatesToPlace.find(g => g.gate === a.gate).def)} на ${a.platform}`;
      case 'mulligan': return a.cards.length ? `Обменять: ${a.cards.map(c => an(known[c])).join(', ')}` : 'Оставить руку';
      case 'prep':
      case 'play': {
        const t = targets(a.targets);
        return `${an(known[a.card])}${t ? ': ' + t : ''}`;
      }
      case 'launch': return `Запуск ${un(a.unit)} на ${a.platform}${v.board[a.platform].unit ? ' — атака' : ''}`;
      case 'move': return `${un(a.unit)}: ${v.units[a.unit].platform} → ${a.platform}${adjacent(v.units[a.unit].platform, a.platform) ? '' : ' за 1 ману'}${v.board[a.platform].unit ? ' — атака' : ''}`;
      case 'recall': return `Отозвать ${un(a.unit)} в резерв`;
      case 'capture': return `Захватить печать: ${un(a.unit)} на ${v.units[a.unit].platform}`;
      case 'rest': return 'Отдых';
      case 'support': return a.unit ? `Поддержка: ${un(a.unit)}` : 'Без поддержки';
      case 'pass': return 'Пас';
      case 'discard': return `Сбросить ${an(known[a.card])}`;
      case 'arrange': return `Порядок: ${a.order.map(c => an(known[c])).join(' → ')}`;
      default: return a.type;
    }
  };
  return { who, Who, side, un, an, gn, targets, action, known };
}

export function eventLine(N, v, e) {
  const u = N.un;
  switch (e.t) {
    case 'matchStart': return { html: `Матч начат. Первым ходит ${esc(N.who('A'))}.`, big: true };
    case 'gatePlaced': return { html: e.gateDef ? `${esc(N.Who(e.player))}: ворота ${N.gn(e.gateDef)} на ${e.platform}` : `${esc(N.Who(e.player))}: закрытые ворота на ${e.platform}` };
    case 'mulliganStart': return { html: 'Колоды перемешаны, розданы руки по 4 карты.' };
    case 'mulligan': return { html: e.returnedDefs ? `${esc(N.Who(e.player))}: обмен ${e.count}${e.returnedDefs.length ? ` (${e.returnedDefs.map(N.an).join(', ')})` : ''}` : `${esc(N.Who(e.player))}: обмен ${e.count} карт` };
    case 'draw': return { html: e.def ? `${esc(N.Who(e.player))}: берёт ${N.an(e.def)}` : `${esc(N.Who(e.player))} берёт карту` };
    case 'drawEmpty': return { html: `${esc(N.Who(e.player))}: колода пуста, добор ничего не даёт` };
    case 'burn': return { html: `${esc(N.Who(e.player))}: рука полна, ${N.an(e.def)} раскрыта и сброшена` };
    case 'discard': return { html: `${esc(N.Who(e.player))} сбрасывает ${N.an(e.def)}` };
    case 'roundStart': return { sep: `Раунд ${e.round} · мана ${e.mana}` };
    case 'turnStart': return { sep: `Ход ${e.turnNo}/${TURN_LIMIT} · ${N.who(e.player)}` };
    case 'ready': return { html: `${u(e.unit)} готов к запуску` };
    case 'hold': return { html: `${u(e.unit)}: удержание ${e.hold}${e.hold >= 2 ? ', можно захватить' : ''}` };
    case 'anchorEnd': return { html: `${u(e.unit)}: временный Якорь снят` };
    case 'rest': return { html: `${esc(N.Who(e.player))}: отдых` };
    case 'launch': return { html: `${esc(N.Who(e.player))} запускает ${u(e.unit)} на ${e.platform}` };
    case 'move': return { html: `${u(e.unit)}: ${e.from} → ${e.to}${e.cost ? ' за 1 ману' : ''}` };
    case 'toReserve': return { html: `${u(e.unit)} возвращается в резерв` };
    case 'recovery': return { html: `${u(e.unit)} восстанавливается до своего хода ${e.readyOn}` };
    case 'sigil': return { html: `${esc(N.Who(e.player))}: печать ${e.sigils}/3 за ${e.platform}, ворота ${N.gn(e.gateDef)}${e.via === 'hold' ? ' (захват удержанием)' : ''}`, big: true };
    case 'matchEnd': return { html: e.winner ? `Партия окончена: побеждает ${esc(N.who(e.winner))} — ${esc(REASONS[e.reason] ?? e.reason)}` : `Партия окончена вничью — ${esc(REASONS[e.reason] ?? e.reason)}`, big: true };
    case 'matchVoid': return { html: 'Матч аннулирован: превышен предел 128 разрешений.', big: true };
    case 'prep': return { html: `${esc(N.Who(e.player))} играет ${N.an(e.def)} за ${e.cost}${N.targets(e.targets) ? ': ' + N.targets(e.targets) : ''}` };
    case 'fizzle': return { html: `${N.an(e.def)} уходит в сброс без эффекта: цели больше нет` };
    case 'relocate': return { html: `${u(e.unit)}: ${e.from} → ${e.to}${e.how === 'forced' ? ' (принудительно)' : ''}` };
    case 'swap': return { html: `${u(e.units[0])} и ${u(e.units[1])} меняются местами` };
    case 'anchor': return { html: `${u(e.unit)}: Якорь до конца хода ${e.until}` };
    case 'anchorHeld': return { html: `${u(e.unit)} удержан Якорем, перемещения нет` };
    case 'recoveryShortened': return { html: `${u(e.unit)}: восстановление до хода ${e.readyOn}` };
    case 'scout': return { html: e.gateDef ? `${esc(N.Who(e.player))}: разведка ${e.platform} — ${N.gn(e.gateDef)}` : `${esc(N.Who(e.player))} разведывает закрытые ворота на ${e.platform}` };
    case 'arranged': return { html: `${esc(N.Who(e.player))}: порядок верхних ${e.count} карт выбран` };
    case 'duelStart': return { html: `Поединок на ${e.platform}: ${u(e.attacker)} против ${u(e.defender)}${e.viaMove ? ' (атака перемещением)' : ''}`, big: true };
    case 'gateRevealed': return { html: `Открыты ворота ${N.gn(e.gateDef)}: ${esc(GATES[e.gateDef].rule)}` };
    case 'shroud': return { html: `${u(e.unit)}: Покров${e.from === 'gate' ? ' от ворот' : ''}` };
    case 'supportRevealed': return { html: `Поддержка: ${esc(N.who('A'))} — ${e.A ? u(e.A) : 'нет'}; ${esc(N.who('B'))} — ${e.B ? u(e.B) : 'нет'}` };
    case 'powers': return { html: `Исходный расчёт: ${e.attacker.total} против ${e.defender.total}` };
    case 'play': return { html: `${esc(N.Who(e.player))} объявляет ${N.an(e.def)} за ${e.cost}${N.targets(e.targets) ? ': ' + N.targets(e.targets) : ''}` };
    case 'pass': return { html: `${esc(N.Who(e.player))}: пас` };
    case 'resolve': return { html: `Разрешается ${N.an(e.def)}` };
    case 'mod': return { html: `${u(e.unit)} ${signed(e.amount)} от ${N.an(e.def)}${e.removable ? '' : ' (неудаляемо)'}${e.linkBound ? ' через связь' : ''}` };
    case 'modRemoved': return { html: `${u(e.unit)}: снят ${signed(e.amount)} от ${N.an(e.def)}` };
    case 'shroudAlready': return { html: `${u(e.unit)}: Покров уже есть, второй не добавляется` };
    case 'shroudSpent': return { html: `${u(e.unit)}: Покров поглощает враждебную часть ${N.an(e.def)}` };
    case 'sageIgnores': return { html: `${u(e.unit)} игнорирует −${e.amount} (пассив Мудреца)` };
    case 'silenced': return { html: `${u(e.unit)}: Немота, пассив отключён` };
    case 'unsilenced': return { html: `${u(e.unit)}: Немота снята` };
    case 'aspect': return { html: `${u(e.unit)}: текущий аспект ${GLYPH[e.aspect]} ${ASPECT_NAMES[e.aspect]}${e.restored ? ' (базовый)' : ''}` };
    case 'aspectAlreadyBase': return { html: `${u(e.unit)} уже в базовом аспекте` };
    case 'linkSuppressed': return { html: `Связь поддержки (${esc(N.who(e.player))}) подавлена` };
    case 'countered': return { html: `${N.an(e.def)} отменена картой ${N.an(e.by)}` };
    case 'gateBonusesOff': return { html: `Бонусы аспектов ворот на ${e.platform} отключены` };
    case 'shroudRemoved': return { html: `${u(e.unit)}: Покров снят` };
    case 'clash': {
      const tie = e.attacker.total === e.defender.total;
      return { html: `Столкновение: ${u(e.attacker.unit)} ${e.attacker.total} — ${u(e.defender.unit)} ${e.defender.total}. Побеждает ${u(e.winner)}${tie ? ' (равенство)' : ''}`, big: true };
    }
    default: return null;
  }
}
