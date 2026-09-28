// Content of the hybrid rules (v0.3): colossi with G (power, attack and health) and an ability each, gates, and a shared
// ability card pool.
// Names and looks of colossi and gates come from the v0.1 content; numbers are on the Bakugan-like G scale.
import { ASPECTS, ASPECT_NAMES, COLOSSI as BASE_COLOSSI, GATES as BASE_GATES } from '../core/content.js';
import { hashString } from '../core/rng.js';

export const DUEL_RULES_VERSION = '0.3.1';
export { ASPECTS, ASPECT_NAMES };

// Tunable numbers of the format. Everything the rules count lives here.
export const RULES = {
  life: 500,               // player life gauge
  removeOver: 500,         // knocked out with a difference in power over this, a colossus is removed from the game
  koLife: 60,              // life a knockout costs on top of the minus below zero
  startHand: 4,
  handMax: 8,
  activationsPerRound: 2,
  fusionMax: 3,            // cards in one fusion activation
  // Mana and the round timer grow while both fighters survive, and start over with every new bout.
  mana: boutRound => Math.min(10, 2 + boutRound),
  timerMs: boutRound => Math.min(45000, 20000 + (boutRound - 1) * 5000),
  roundLimit: 90,          // safety net: then more life wins
  colossi: 3, gates: 3, deck: 24, maxCopies: 2,
  // The attack: the weaker fighter loses the difference, the stronger one loses `recoil` of it (the blow comes back),
  // and the loser of the attack rallies with extra mana for the next round.
  recoil: 0.6,
  minLoss: 40,             // the loser of the attack loses at least this much; with equal forces both lose it
  rally: 1,
  aspectEdge: 100,         // attack bonus against the aspect you beat
  restFloor: 0.5,          // back from a bout a colossus keeps its G, but not less than this share of its base
};

// The aspect cycle: each aspect beats the next one. Прилив гасит Жар, Жар сжигает Ветер, Ветер точит Камень,
// Камень заслоняет Свет, Свет рассеивает Тень, Тень поглощает Прилив.
export const BEATS = { tide: 'fire', fire: 'wind', wind: 'stone', stone: 'light', light: 'shadow', shadow: 'tide' };
export const ASPECT_CYCLE = ['tide', 'fire', 'wind', 'stone', 'light', 'shadow'];

// G is power, attack and health at once. A colossus falls when its G goes below zero.
// Every colossus has one passive ability; the lower its G, the stronger the ability.
const STATS = {
  'RS-C001': [440, 'D-U01', 'Жар атаки', 'В атаке +120 G.', { attack: 120 }],
  'RS-C002': [420, 'D-U02', 'Упорство', 'В начале каждого раунда боя, кроме первого, +20 G.', { roundGain: 20 }],
  'RS-C003': [460, 'D-U03', 'Глубина', 'Проигрывая атаку, теряет вдвое меньше.', { lossScale: 0.5 }],
  'RS-C004': [380, 'D-U04', 'Прозрение', 'Видит вид скрытых карт соперника (атака, защита, сила…). В начале боя берёт на карту больше.', { seesKinds: true, extraDraw: 1 }],
  'RS-C005': [480, 'D-U05', 'Тяжесть', 'Самый крепкий, но в атаке −20 G.', { attack: -20 }],
  'RS-C006': [420, 'D-U06', 'Стойкость', 'Щиты на нём на пятую часть прочнее; его силу нельзя украсть.', { shieldScale: 1.2, stealImmune: true }],
  'RS-C007': [420, 'D-U07', 'Вихрь', 'Каждое его слияние даёт ещё +60 G.', { fusionGain: 60 }],
  'RS-C008': [440, 'D-U08', 'Быстрые руки', '3 активации за раунд, и первая в раунде на 1 ману дешевле.', { activations: 3, discount: 1 }],
  'RS-C009': [400, 'D-U09', 'Страж', 'В начале боя получает щит 120.', { startShield: 120 }],
  'RS-C010': [410, 'D-U10', 'Маяк', 'В начале каждого раунда восстанавливает 100 G; из боя возвращается без усталости.', { roundHeal: 100, noFatigue: true }],
  'RS-C011': [420, 'D-U11', 'Из тени', 'Если враг сильнее, в атаке +80 G.', { attackIfWeaker: 80 }],
  'RS-C012': [400, 'D-U12', 'Поглощение', 'Его кражи силы забирают на треть больше.', { stealScale: 1.3 }],
};

export const COLOSSI = Object.fromEntries(Object.values(BASE_COLOSSI).map(c => {
  const [g, signature, abilityName, abilityText, passive] = STATS[c.id];
  return [c.id, { id: c.id, name: c.name, aspect: c.aspect, look: c.look, g, signature, ability: { name: abilityName, text: abilityText }, passive }];
}));

// Gates lie face down until their owner chooses to open them (at the end of a round, before the cards).
// On opening the owner's fighter gets the gate's bonus for its aspect, then the gate's own effect happens.
// kind: bonus — a gift to the owner; field — a rule while the gate stays open; trap — a blow to the opponent.
// rule: while open (forge, circle, gallery) or only in the round of opening (reflect, weakerWins).
// A gate nobody opened goes back to its owner at the end of the bout.
// bonus order: fire / tide / stone / wind / light / shadow.
const GATE_DESIGN = {
  'RS-G001': ['field', [150, 0, 50, 0, 50, 0], [], 'forge', 'Пока открыты, в начале каждого раунда оба бойца получают +40 G, а боец владельца — ещё +40.'],
  'RS-G002': ['trap', [100, 0, 0, 100, 0, 50], [['pierce', 200]], null, 'При открытии боец соперника теряет 200 G, щиты не защищают.'],
  'RS-G003': ['bonus', [0, 150, 50, 0, 50, 0], [['draw', 2], ['mana', 1]], null, 'При открытии владелец берёт 2 карты и получает +1 ману в следующем раунде.'],
  'RS-G004': ['trap', [0, 100, 0, 50, 100, 0], [], 'reflect', 'В раунде открытия урон и кражи карт соперника бьют по его собственному бойцу.'],
  'RS-G005': ['bonus', [50, 0, 150, 0, 50, 0], [['shield', 200]], null, 'При открытии боец владельца получает щит 200.'],
  'RS-G006': ['field', [0, 50, 100, 0, 0, 100], [], 'circle', 'Пока открыты, восстановление и кража силы не действуют у соперника владельца.'],
  'RS-G007': ['field', [50, 0, 0, 150, 0, 50], [], 'gallery', 'Пока открыты, каждое слияние владельца даёт его бойцу ещё +120 G.'],
  'RS-G008': ['trap', [0, 50, 0, 100, 50, 50], [['drainMana', 3]], null, 'При открытии у соперника на 3 маны меньше в следующем раунде.'],
  'RS-G009': ['bonus', [0, 50, 50, 0, 150, 0], [['restore', 1], ['shield', 100]], null, 'При открытии сила бойца владельца снова полная, плюс щит 100.'],
  'RS-G010': ['trap', [50, 0, 50, 0, 100, 50], [], 'weakerWins', 'В атаке раунда открытия проигрывает не слабый, а сильный.'],
  'RS-G011': ['trap', [50, 0, 0, 50, 0, 150], [['swap', 1]], null, 'При открытии сила бойцов меняется местами.'],
  'RS-G012': ['trap', [0, 50, 50, 0, 0, 100], [['punishStronger', 300]], null, 'При открытии, если боец соперника сильнее, он теряет 300 G.'],
};
export const GATE_KIND_NAMES = { bonus: 'Бонус', field: 'Поле', trap: 'Ловушка' };
export const ROUND_RULES = ['reflect', 'weakerWins'];
export const GATES = Object.fromEntries(Object.values(BASE_GATES).map(g => {
  const [kind, bonus, open, rule, text] = GATE_DESIGN[g.id];
  return [g.id, { id: g.id, name: g.name, kind, bonus, open, rule, text }];
}));

// Ability cards. kind: attack / defense / power / tactic / counter. once: removed from the game after use.
// ops are applied in order to the activating player's fighter ("self") and the opposing fighter ("foe").
// Tactic cards are not combat cards: they take effect as soon as they are played and cannot be cancelled.
// A counter is a condition, not a target: at the end of the round it cancels the first matching action of the opponent
// (in the order they were played), whenever it was played. ['counter', what, drawOnMiss].
export const COUNTER_WHAT = {
  any: 'первое боевое действие соперника или открытие ворот', attack: 'первую атаку соперника', defense: 'первую защиту соперника',
  gate: 'открытие ворот соперника', counter: 'первую отмену соперника',
};
export const KIND_NAMES = { attack: 'Атака', defense: 'Защита', power: 'Сила', tactic: 'Тактика', counter: 'Отмена' };
const C = (id, name, aspect, cost, kind, once, text, ops, unique = null) => [id, { id, name, aspect, cost, kind, once, text, ops, unique }];
export const CARDS = Object.fromEntries([
  // ---- нейтральные
  C('D-N01', 'Удар', 'neutral', 1, 'attack', false, 'Враг теряет 70 G.', [['damage', 70]]),
  C('D-N02', 'Рывок', 'neutral', 2, 'power', false, 'Свой боец +150 G.', [['gain', 150]]),
  C('D-N03', 'Щит', 'neutral', 2, 'defense', false, 'Щит 150: поглощает урон до конца боя.', [['shield', 150]]),
  C('D-N04', 'Перевязка', 'neutral', 2, 'defense', false, 'Восстановить 180 G, но не выше полной силы.', [['heal', 180]]),
  C('D-N05', 'Отмена', 'neutral', 3, 'counter', false, 'В конце раунда отменяет первое боевое действие соперника или открытие ворот.', [['counter', 'any']]),
  C('D-N06', 'Тактический резерв', 'neutral', 0, 'tactic', true, 'Сразу взять 2 карты.', [['draw', 2]]),
  C('D-N07', 'Прилив сил', 'neutral', 0, 'tactic', true, 'Сразу взять карту; +2 маны в следующем раунде.', [['mana', 2], ['draw', 1]]),
  C('D-N08', 'Сокрушение', 'neutral', 4, 'attack', false, 'Враг теряет 280 G.', [['damage', 280]]),
  C('D-N09', 'Второе дыхание', 'neutral', 4, 'power', true, 'Сила своего бойца снова полная.', [['restore', 1]]),
  C('D-N10', 'Кража силы', 'neutral', 3, 'attack', false, 'Перенести 150 G от врага своему бойцу.', [['steal', 150]]),
  C('D-N11', 'Замок ворот', 'neutral', 1, 'counter', false, 'Отменяет открытие ворот соперника в этом раунде. Промах — возьмите карту.', [['counter', 'gate', 1]]),
  C('D-N12', 'Встречный знак', 'neutral', 2, 'counter', false, 'Отменяет первую отмену соперника в этом раунде. Промах — возьмите карту.', [['counter', 'counter', 1]]),
  // ---- Жар
  C('D-F01', 'Угольный рывок', 'fire', 1, 'power', false, 'Свой боец +90 G.', [['gain', 90]]),
  C('D-F02', 'Раскалённый клинок', 'fire', 3, 'attack', false, 'Враг теряет 150 G, свой боец +100 G.', [['damage', 150], ['gain', 100]]),
  C('D-F03', 'Огненный вал', 'fire', 5, 'attack', false, 'Враг теряет 380 G.', [['damage', 380]]),
  C('D-F04', 'Догорающий след', 'fire', 2, 'power', false, 'Свой боец +160 G.', [['gain', 160]]),
  // ---- Прилив
  C('D-T01', 'Смыть чары', 'tide', 1, 'counter', false, 'Отменяет первую защиту соперника и снимает все его щиты.', [['counter', 'defense'], ['breakShield', 1]]),
  C('D-T02', 'Тихая заводь', 'tide', 2, 'defense', false, 'Щит 150 и восстановить 120 G.', [['shield', 150], ['heal', 120]]),
  C('D-T03', 'Тяжесть глубин', 'tide', 3, 'attack', false, 'Враг теряет 230 G.', [['damage', 230]]),
  C('D-T04', 'Отлив', 'tide', 4, 'attack', false, 'Перенести 220 G от врага своему бойцу.', [['steal', 220]]),
  // ---- Камень
  C('D-S01', 'Гранитная стойка', 'stone', 2, 'defense', false, 'Щит 200.', [['shield', 200]]),
  C('D-S02', 'Окаменение', 'stone', 3, 'attack', false, 'Враг теряет 210 G.', [['damage', 210]]),
  C('D-S03', 'Вес бастиона', 'stone', 4, 'power', false, 'Свой боец +320 G.', [['gain', 320]]),
  C('D-S04', 'Крепкий шаг', 'stone', 1, 'defense', false, 'Щит 100.', [['shield', 100]]),
  // ---- Ветер
  C('D-W01', 'Восходящий поток', 'wind', 2, 'power', false, 'Свой боец +170 G.', [['gain', 170]]),
  C('D-W02', 'Разрыв строя', 'wind', 3, 'attack', false, 'Перенести 150 G от врага своему бойцу.', [['steal', 150]]),
  C('D-W03', 'Штормовая связка', 'wind', 4, 'attack', false, 'Враг теряет 160 G, свой боец +160 G.', [['damage', 160], ['gain', 160]]),
  C('D-W04', 'Попутный ветер', 'wind', 0, 'tactic', true, 'Сразу взять карту; +2 маны в следующем раунде.', [['mana', 2], ['draw', 1]]),
  // ---- Свет
  C('D-L01', 'Световой щит', 'light', 1, 'defense', false, 'Щит 110.', [['shield', 110]]),
  C('D-L02', 'Очищение', 'light', 2, 'defense', false, 'Восстановить 200 G, но не выше полной силы.', [['heal', 200]]),
  C('D-L03', 'Клятва стража', 'light', 3, 'power', false, 'Свой боец +250 G.', [['gain', 250]]),
  C('D-L04', 'Рассвет', 'light', 4, 'power', true, 'Сила снова полная и щит 150.', [['restore', 1], ['shield', 150]]),
  // ---- Тень
  C('D-D01', 'Тихий приказ', 'shadow', 2, 'counter', false, 'Отменяет первую атаку соперника в этом раунде.', [['counter', 'attack']]),
  C('D-D02', 'Долг силы', 'shadow', 3, 'attack', false, 'Перенести 150 G от врага своему бойцу.', [['steal', 150]]),
  C('D-D03', 'Цена самоуверенности', 'shadow', 3, 'attack', false, 'Враг теряет 300 G, если у него не меньше 430 G; иначе 130.', [['damageIfStrong', 300, 130, 430]]),
  C('D-D04', 'Скрытая тропа', 'shadow', 0, 'tactic', false, 'Сразу взять карту.', [['draw', 1]]),
  // ---- уникальные способности колоссов
  C('D-U01', 'Пепельное дыхание', 'fire', 5, 'attack', false, 'Враг теряет 320 G, Виверн +120 G.', [['damage', 320], ['gain', 120]], 'RS-C001'),
  C('D-U02', 'Печное сердце', 'fire', 4, 'power', false, 'Рыцарь +280 G.', [['gain', 280]], 'RS-C002'),
  C('D-U03', 'Прилив глубин', 'tide', 3, 'defense', false, 'Левиафан восстанавливает 200 G и получает щит 200.', [['heal', 200], ['shield', 200]], 'RS-C003'),
  C('D-U04', 'Архив раковины', 'tide', 2, 'tactic', false, 'Сразу взять 2 карты; +1 мана в следующем раунде.', [['draw', 2], ['mana', 1]], 'RS-C004'),
  C('D-U05', 'Базальтовый обвал', 'stone', 6, 'attack', false, 'Враг теряет 520 G.', [['damage', 520]], 'RS-C005'),
  C('D-U06', 'Стена копий', 'stone', 3, 'defense', false, 'Щит 300.', [['shield', 300]], 'RS-C006'),
  C('D-U07', 'Штормовой порыв', 'wind', 4, 'attack', false, 'Перенести 220 G от врага Грифону.', [['steal', 220]], 'RS-C007'),
  C('D-U08', 'Два клинка', 'wind', 5, 'attack', false, 'Враг дважды теряет 200 G.', [['damage', 200], ['damage', 200]], 'RS-C008'),
  C('D-U09', 'Стеклянная стена', 'light', 4, 'defense', false, 'Щит 400.', [['shield', 400]], 'RS-C009'),
  C('D-U10', 'Свет маяка', 'light', 3, 'defense', false, 'Птица восстанавливает 250 G.', [['heal', 250]], 'RS-C010'),
  C('D-U11', 'Удар из тени', 'shadow', 5, 'attack', false, 'Враг теряет 360 G, щиты не защищают.', [['pierce', 360]], 'RS-C011'),
  C('D-U12', 'Кольца пустоты', 'shadow', 5, 'attack', false, 'Перенести 200 G от врага Хранителю.', [['steal', 200]], 'RS-C012'),
]);

// A card fits a fighter when it is neutral, of the fighter's aspect, and not someone else's signature ability.
export function playableBy(cardId, colossusId) {
  const c = CARDS[cardId], k = COLOSSI[colossusId];
  if (c.unique) return c.unique === colossusId;
  return c.aspect === 'neutral' || c.aspect === k.aspect;
}

const twice = ids => ids.flatMap(id => [id, id]);
export const DUEL_DECKS = {
  attack: {
    name: 'Жар и Свет', colossi: ['RS-C001', 'RS-C002', 'RS-C009'], gates: ['RS-G001', 'RS-G009', 'RS-G002'],
    cards: [...twice(['D-N01', 'D-N02', 'D-N03', 'D-N05', 'D-N08', 'D-F01', 'D-F02', 'D-F04', 'D-L01', 'D-L03']), 'D-U01', 'D-U02', 'D-U09', 'D-N06'],
  },
  control: {
    name: 'Камень и Ветер', colossi: ['RS-C005', 'RS-C006', 'RS-C007'], gates: ['RS-G005', 'RS-G007', 'RS-G008'],
    cards: [...twice(['D-N01', 'D-N03', 'D-N04', 'D-N10', 'D-S01', 'D-S02', 'D-S03', 'D-W01', 'D-W02', 'D-W03']), 'D-U05', 'D-U06', 'D-U07', 'D-N11'],
  },
  answers: {
    name: 'Прилив и Тень', colossi: ['RS-C003', 'RS-C004', 'RS-C011'], gates: ['RS-G004', 'RS-G010', 'RS-G011'],
    cards: [...twice(['D-N01', 'D-N02', 'D-N05', 'D-N08', 'D-T01', 'D-T02', 'D-T03', 'D-D01', 'D-D02', 'D-D03']), 'D-U03', 'D-U04', 'D-U11', 'D-N12'],
  },
  sky: {
    name: 'Небо и Сумрак', colossi: ['RS-C008', 'RS-C010', 'RS-C012'], gates: ['RS-G003', 'RS-G006', 'RS-G012'],
    // three aspects: the deck leans on neutral cards so that each colossus has enough to play
    cards: [...twice(['D-N01', 'D-N02', 'D-N03', 'D-N04', 'D-N05', 'D-N08', 'D-N10', 'D-W01', 'D-D02']), 'D-L02', 'D-L03', 'D-D03', 'D-U08', 'D-U10', 'D-U12'],
  },
};

export function validateDuelDeck(deck) {
  const errors = [];
  const colossi = deck?.colossi ?? [], gates = deck?.gates ?? [], cards = deck?.cards ?? [];
  if (colossi.length !== RULES.colossi || new Set(colossi).size !== colossi.length) errors.push('нужно 3 разных колосса');
  for (const id of colossi) if (!COLOSSI[id]) errors.push(`неизвестный колосс ${id}`);
  if (gates.length !== RULES.gates || new Set(gates).size !== gates.length) errors.push('нужно 3 разных ворот');
  for (const id of gates) if (!GATES[id]) errors.push(`неизвестные ворота ${id}`);
  if (cards.length !== RULES.deck) errors.push(`в колоде должно быть ${RULES.deck} карты`);
  const copies = {};
  for (const id of cards) {
    if (!CARDS[id]) { errors.push(`неизвестная карта ${id}`); continue; }
    copies[id] = (copies[id] ?? 0) + 1;
    if (!colossi.some(k => COLOSSI[k] && playableBy(id, k))) errors.push(`${CARDS[id].name}: её не может сыграть ни один колосс состава`);
  }
  for (const [id, n] of Object.entries(copies)) if (n > RULES.maxCopies) errors.push(`${CARDS[id].name}: больше ${RULES.maxCopies} копий`);
  return [...new Set(errors)];
}

export const DUEL_CONTENT_HASH = hashString(JSON.stringify({ DUEL_RULES_VERSION, COLOSSI, GATES, CARDS, RULES: { ...RULES, mana: String(RULES.mana), timerMs: String(RULES.timerMs) } }));
