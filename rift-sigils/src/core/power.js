// PowerEvaluator (GDD §11): Power = max(0, base + passives + gate aspect bonus + active support + ability modifiers).
// Everything is recomputed from the duel state; nothing is cached, so the UI can always show the breakdown.
import { ABILITIES, ASPECTS, ASPECT_NAMES, COLOSSI, GATES } from './content.js';

export const fighterOf = (s, p) => (s.units[s.duel.attacker].owner === p ? s.duel.attacker : s.duel.defender);
export const enemyOf = (s, uid) => (uid === s.duel.attacker ? s.duel.defender : s.duel.attacker);
export const isAttacker = (s, uid) => s.duel.attacker === uid;
export const duelGate = s => GATES[s.gates[s.duel.gate].def];

// "Выбран союзник" — the link exists even when suppressed.
export const supportChosen = (s, p) => !!s.duel.support[p];
// "Действующая поддержка" / "есть поддержка": a suppressed link or one on Каменный круг counts as absent (§12).
export function supportActive(s, p) {
  const sp = s.duel.support[p];
  return !!sp && !sp.suppressed && duelGate(s).id !== 'RS-G006';
}

export const currentAspect = (s, uid) => s.duel?.aspect[uid] ?? COLOSSI[s.units[uid].def].aspect;

function passive(s, uid) {
  const d = s.duel, me = COLOSSI[s.units[uid].def], p = s.units[uid].owner;
  const foe = enemyOf(s, uid), foeDef = COLOSSI[s.units[foe].def];
  const attacking = isAttacker(s, uid);
  switch (me.id) {
    case 'RS-C001': return attacking ? 2 : 0;
    case 'RS-C002': return supportActive(s, p) ? 0 : 1;
    case 'RS-C003': return foeDef.base > me.base ? 2 : 0;
    case 'RS-C005': return attacking ? -3 : 0;
    case 'RS-C007': return supportActive(s, p) ? 2 : 0; // an addition to the link: gone with the link (T20)
    case 'RS-C008': return attacking && d.viaMove ? 2 : 0;
    case 'RS-C009': return attacking ? 0 : 1;
    case 'RS-C011': return supportActive(s, s.units[foe].owner) ? 2 : 0;
    case 'RS-C012': return foeDef.aspect === currentAspect(s, foe) ? 1 : 0;
    default: return 0; // C004, C006, C010 act through other rules
  }
}

export function breakdown(s, uid) {
  const d = s.duel, me = COLOSSI[s.units[uid].def], p = s.units[uid].owner;
  const gate = duelGate(s), attacking = isAttacker(s, uid);
  const parts = [{ kind: 'base', label: 'База', value: me.base }];

  if (d.silenced[uid]) parts.push({ kind: 'passive', label: 'Пассив под Немотой', value: 0 });
  else {
    const v = passive(s, uid);
    if (v) parts.push({ kind: 'passive', label: 'Пассив', value: v });
  }

  const aspect = currentAspect(s, uid);
  let gb = gate.bonus[ASPECTS.indexOf(aspect)], gl = `Ворота: ${ASPECT_NAMES[aspect]}`;
  if (d.aspectBonusOff) { gb = 0; gl += ' (бонусы отключены)'; }
  else if (gate.id === 'RS-G011' && me.base >= 15) { gb = 0; gl += ' (Пустой престол: база ≥ 15)'; }
  parts.push({ kind: 'gate', label: gl, value: gb });
  if (gate.id === 'RS-G001' && attacking) parts.push({ kind: 'gateRule', label: 'Кузница: нападающий', value: 1 });
  if (gate.id === 'RS-G005' && !attacking) parts.push({ kind: 'gateRule', label: 'Корни: защитник', value: 1 });

  const linkOn = supportActive(s, p);
  if (linkOn) {
    parts.push({ kind: 'support', label: 'Поддержка', value: 2 });
    if (gate.id === 'RS-G007') parts.push({ kind: 'support', label: 'Галерея: связь', value: 1 });
  } else if (supportChosen(s, p)) {
    parts.push({ kind: 'support', label: d.support[p].suppressed ? 'Поддержка подавлена' : 'Поддержка: Каменный круг', value: 0 });
  }

  for (const m of d.mods) {
    if (m.target !== uid) continue;
    const on = !m.linkBound || linkOn;
    parts.push({
      kind: 'mod', label: ABILITIES[m.def].name + (m.linkBound ? ' (связь)' : ''), value: on ? m.amount : 0,
      mod: m.id, removable: m.removable,
    });
  }
  const raw = parts.reduce((a, x) => a + x.value, 0);
  return { total: Math.max(0, raw), raw, parts };
}

export const power = (s, uid) => breakdown(s, uid).total;

// §09 B5: higher power wins; a tie goes to the defender unless the gate says otherwise.
export function duelWinner(s) {
  const d = s.duel, a = power(s, d.attacker), b = power(s, d.defender);
  if (a !== b) return a > b ? d.attacker : d.defender;
  return duelGate(s).id === 'RS-G012' ? d.attacker : d.defender;
}
