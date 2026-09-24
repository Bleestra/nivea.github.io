// Mineflayer body for SynapseBrain: full player controls, senses, a reference book of all recipes and
// advancements. The body only makes every action technically possible - WHEN to do what, the brain
// learns by itself.
//
//   npm install
//   node bot.js --host localhost --port 25565 --brain 5555 [--viewer 3007] [--version 1.20.4]
const mineflayer = require('mineflayer')
const net = require('net')
const readline = require('readline')
const fs = require('fs')
const path = require('path')
const Vec3 = require('vec3')

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d }
const bot = mineflayer.createBot({
  host: arg('host', 'localhost'), port: +arg('port', 25565),
  username: arg('name', 'SynapseBrain'), auth: arg('auth', 'offline'), version: arg('version', undefined)
})
const SELFTEST = process.argv.includes('--selftest')
const brain = SELFTEST ? null : net.connect(+arg('brain', 5555), arg('brainhost', '127.0.0.1'))
const replies = SELFTEST ? { on () {} } : readline.createInterface({ input: brain })
const VIEWER = +arg('viewer', 0)   // first-person 3D view for the brain's eyes, e.g. --viewer 3007
const WANDER = +arg('wander', 0)   // teleport somewhere new every N steps (needs op; for data collection)
const STEP_MS = +arg('step', 100)
const DIRS = [[0, -1], [1, 0], [0, 1], [-1, 0]]  // N E S W as (dx, dz)
const dbg = (...a) => { if (process.env.DEBUG) console.log('[debug]', ...a) }

// ---------------------------------------------------------------- the action repertoire
// The first 5 keep the numbers they had in MiniCraft, so skills from childhood carry over.
const ACTIONS = ['forward', 'turn_left', 'turn_right', 'dig_front', 'wait',
  'craft_new', 'eat', 'back', 'strafe_left', 'strafe_right', 'jump', 'toggle_sprint', 'toggle_sneak',
  'look_up', 'look_down', 'attack', 'use_item', 'dig_down', 'equip_armor', 'equip_weapon',
  'equip_tool', 'place_block', 'craft_gear', 'smelt', 'sleep', 'drop_junk']

// ---------------------------------------------------------------- knowledge: recipes + advancements
const K = path.join(__dirname, 'knowledge')
const RECIPES = fs.existsSync(path.join(K, 'recipes.json')) ? JSON.parse(fs.readFileSync(path.join(K, 'recipes.json'))) : {}
const ADV = fs.existsSync(path.join(K, 'advancements.json')) ? JSON.parse(fs.readFileSync(path.join(K, 'advancements.json'))) : {}
const ADV_BY_TITLE = Object.fromEntries(Object.entries(ADV).map(([id, a]) => [a.title, id]))

let mcData = null
let step = 0; let heading = 0; let pitch = 0; let sprint = false; let sneak = false
let lastHealth = 20; let lastLogs = 0; let lastStone = 0; let lastNear = 9; let deathMsg = ''
let waiting = null; let canCraftNew = false; let canCraftGear = false
const everHeld = new Set()
const advancements = new Set()
const heard = []
const newAdvancements = []

// ---------------------------------------------------------------- senses
function blockClass (b) {
  if (!b) return 5
  const n = b.name
  if (n.includes('lava')) return 3
  if (n.includes('water')) return 4
  if (n.endsWith('_log') || n.endsWith('_wood')) return 1
  if (n === 'stone' || n.includes('ore') || n === 'cobblestone' || n === 'deepslate') return 2
  if (b.boundingBox === 'empty') return 0
  return 5
}

function observe () {  // 5x5 cells in front (rows = distance ahead, cols = left..right)
  const p = bot.entity.position.floored()
  const [fx, fz] = DIRS[heading]; const [rx, rz] = DIRS[(heading + 1) % 4]
  const obs = []
  for (let a = 0; a < 5; a++) {
    for (let b = -2; b <= 2; b++) {
      const dx = fx * a + rx * b; const dz = fz * a + rz * b
      const feet = blockClass(bot.blockAt(p.offset(dx, 0, dz)))
      const head = blockClass(bot.blockAt(p.offset(dx, 1, dz)))
      const above = blockClass(bot.blockAt(p.offset(dx, 2, dz)))
      let c
      if (feet === 1 || head === 1) c = 1
      else if (feet === 3 || head === 3) c = 3
      else if (feet === 4) c = 4
      else if (feet === 2 || head === 2) c = 2
      else if (head === 0 && (feet === 0 || above === 0)) c = 0
      else c = 5
      obs.push(c)
    }
  }
  return obs
}

function relDir (pos) {  // direction (1 ahead, 2 right, 3 behind, 4 left) and distance bucket (0..3)
  const p = bot.entity.position
  const dx = pos.x - p.x; const dz = pos.z - p.z
  const [fx, fz] = DIRS[heading]; const [rx, rz] = DIRS[(heading + 1) % 4]
  const ahead = dx * fx + dz * fz; const right = dx * rx + dz * rz
  const dir = Math.abs(ahead) >= Math.abs(right) ? (ahead > 0 ? 1 : 3) : (right > 0 ? 2 : 4)
  const dist = Math.abs(dx) + Math.abs(dz)
  return dir * 4 + (dist <= 2 ? 0 : dist <= 5 ? 1 : dist <= 12 ? 2 : 3)
}

function goal () {  // far vision: nearest reachable log
  const y = Math.floor(bot.entity.position.y)
  const t = bot.findBlock({ matching: b => b.name.endsWith('_log') && b.position.y >= y - 1 && b.position.y <= y + 1, useExtraInfo: true, maxDistance: 32 })
  return t ? relDir(t.position) : 0
}

const isHostile = e => e && e.type !== 'player' && e.kind && /hostile/i.test(e.kind)
const isAnimal = e => e && e.kind && /passive/i.test(e.kind)

function nearest (pred, maxDist = 24) {
  return bot.nearestEntity(e => pred(e) && e.position.distanceTo(bot.entity.position) < maxDist)
}

const TIERS = ['wooden', 'stone', 'iron', 'golden', 'diamond', 'netherite']
const ARMOR = ['leather', 'golden', 'chainmail', 'iron', 'diamond', 'netherite']
const tier = n => { const i = TIERS.findIndex(t => n.startsWith(t + '_')); return i < 0 ? 0 : i + 1 }
const armorRank = n => { const i = ARMOR.findIndex(t => n.startsWith(t + '_')); return i < 0 ? 0 : i + 1 }
const items = () => bot.inventory.items()

function heldClass () {
  const h = bot.heldItem
  if (!h) return 0
  const n = h.name
  if (n.endsWith('_pickaxe')) return 1
  if (n.endsWith('_axe')) return 2
  if (n.endsWith('_sword')) return 3
  if (mcData.foodsByName[n]) return 4
  if (mcData.blocksByName[n]) return 5
  return 6
}

function features () {  // small integers the brain turns into sensory cells
  const hostile = nearest(isHostile); const animal = nearest(isAnimal)
  const armor = [5, 6, 7, 8].filter(s => bot.inventory.slots[s]).length
  const pick = Math.max(0, ...items().filter(i => i.name.endsWith('_pickaxe')).map(i => tier(i.name)))
  const time = bot.time && bot.time.timeOfDay
  return [hostile ? relDir(hostile.position) : 0, animal ? relDir(animal.position) : 0,
    Math.min(4, Math.floor(bot.health / 5)), Math.min(4, Math.floor(bot.food / 5)), armor, heldClass(), pick,
    time > 13000 && time < 23000 ? 1 : 0, sprint ? 1 : 0, sneak ? 1 : 0, pitch + 1, canCraftGear ? 1 : 0,
    Math.min(15, advancements.size)]
}

function inventory () {
  const inv = {}
  for (const i of items()) { inv[i.name] = (inv[i.name] || 0) + i.count; everHeld.add(i.name) }
  for (const s of [5, 6, 7, 8]) { const i = bot.inventory.slots[s]; if (i) inv['worn:' + i.name] = 1 }
  return inv
}

// ---------------------------------------------------------------- actions
const face = () => { const [fx, fz] = DIRS[heading]; return bot.lookAt(bot.entity.position.offset(fx * 3, 1.6 - pitch * 2, fz * 3), true) }
const hold = async (ctrl, ticks) => { bot.setControlState(ctrl, true); await bot.waitForTicks(ticks); bot.setControlState(ctrl, false) }
const tableNear = () => bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 4 })
const furnaceNear = () => bot.findBlock({ matching: ['furnace', 'lit_furnace'].filter(n => mcData.blocksByName[n]).map(n => mcData.blocksByName[n].id), maxDistance: 4 })

async function placeFront (item) {  // put a block from the inventory on the ground: in front, else any side
  if (!item) return false
  const p = bot.entity.position.floored()
  const spots = []
  for (let k = 0; k < 4; k++) spots.push(DIRS[(heading + k) % 4])
  for (let dx = -2; dx <= 2; dx++) for (let dz = -2; dz <= 2; dz++) if (Math.abs(dx) + Math.abs(dz) >= 2) spots.push([dx, dz])
  for (const [fx, fz] of spots) {
    const ground = bot.blockAt(p.offset(fx, -1, fz)); const spot = bot.blockAt(p.offset(fx, 0, fz))
    if (!ground || ground.boundingBox !== 'block' || !spot || spot.boundingBox !== 'empty') continue
    try { await bot.equip(item, 'hand'); await bot.placeBlock(ground, new Vec3(0, 1, 0)); return true } catch (e) { dbg('place', item.name, e.message) }
  }
  dbg('no place for', item.name)
  return false
}

function craftable (names) {
  const table = tableNear(); const out = []
  for (const n of names) {
    const it = mcData.itemsByName[n]
    if (!it) continue
    const rs = bot.recipesFor(it.id, null, 1, table)
    if (rs.length) out.push([rs[0], table, n])
  }
  return out
}

const newNames = () => mcData.itemsArray.filter(i => !everHeld.has(i.name) && RECIPES[i.name]).map(i => i.name)
const GEAR = Object.keys(RECIPES).filter(n => /_(pickaxe|sword|axe|shovel|helmet|chestplate|leggings|boots)$/.test(n) || n === 'shield')
const gearValue = n => (tier(n) || armorRank(n)) * 10 + (n.endsWith('_pickaxe') ? 3 : n.endsWith('_sword') ? 2 : 1)

async function craftFrom (opts, placeTableIfNeeded) {
  if (!opts().length && placeTableIfNeeded && !tableNear()) await placeFront(items().find(i => i.name === 'crafting_table'))
  for (const [r, table] of opts()) { try { await bot.craft(r, 1, table); return true } catch (e) {} }
  return false
}

async function equipArmor () {
  const slots = { head: /_helmet$/, torso: /_chestplate$/, legs: /_leggings$/, feet: /_boots$/ }
  for (const [dest, re] of Object.entries(slots)) {
    const best = items().filter(i => re.test(i.name)).sort((a, b) => armorRank(b.name) - armorRank(a.name))[0]
    if (best) { try { await bot.equip(best, dest) } catch (e) {} }
  }
}

async function equipBest (re, rank) {
  const best = items().filter(i => re.test(i.name)).sort((a, b) => rank(b.name) - rank(a.name))[0]
  if (best) { try { await bot.equip(best, 'hand') } catch (e) {} }
}

async function equipTool () {  // the right tool for the block in front
  const p = bot.entity.position.floored(); const [fx, fz] = DIRS[heading]
  const b = bot.blockAt(p.offset(fx, 1, fz)) || bot.blockAt(p.offset(fx, 0, fz))
  if (!b || !b.material) return
  const kind = b.material.includes('pickaxe') ? /_pickaxe$/ : b.material.includes('axe') ? /_axe$/ : b.material.includes('shovel') ? /_shovel$/ : null
  if (kind) await equipBest(kind, tier)
}

async function attack () {
  const alive = e => ['mob', 'hostile', 'animal', 'passive', 'ambient', 'water_creature'].includes(e.type) || isHostile(e) || isAnimal(e)
  const target = bot.nearestEntity(e => e !== bot.entity && alive(e) && e.type !== 'player' &&
    e.position.distanceTo(bot.entity.position) < 4.5)
  if (!target) { bot.swingArm(); return }
  try { await bot.lookAt(target.position.offset(0, target.height * 0.8, 0), true); bot.attack(target) } catch (e) {}
}

async function smelt () {
  let f = furnaceNear()
  if (!f) { if (!await placeFront(items().find(i => i.name === 'furnace'))) return; f = furnaceNear(); if (!f) return }
  try {
    const fur = await bot.openFurnace(f)
    if (fur.outputItem()) await fur.takeOutput()
    const input = items().find(i => /^raw_|_ore$|^sand$|^cobblestone$|^beef$|^porkchop$|^chicken$|^mutton$|^cod$|^salmon$|^potato$|_log$/.test(i.name))
    const fuel = items().find(i => /^coal$|^charcoal$|_planks$|_log$|^stick$/.test(i.name) && (!input || i.name !== input.name))
    if (fuel && !fur.fuelItem()) await fur.putFuel(fuel.type, null, Math.min(fuel.count, 8))
    if (input && !fur.inputItem()) await fur.putInput(input.type, null, Math.min(input.count, 8))
    fur.close()
  } catch (e) { dbg('smelt', e.message) }
}

async function sleep () {
  const bed = bot.findBlock({ matching: b => b.name.endsWith('_bed'), useExtraInfo: true, maxDistance: 4 })
  if (bed) { try { await bot.sleep(bed) } catch (e) { dbg('sleep', e.message) } } else await placeFront(items().find(i => i.name.endsWith('_bed')))
}

const JUNK = /^(dirt|gravel|rotten_flesh|poisonous_potato|wheat_seeds|andesite|diorite|granite|netherrack|cobbled_deepslate)$/
async function dropJunk () {
  const j = items().filter(i => JUNK.test(i.name)).sort((a, b) => b.count - a.count)[0]
  if (j) { try { await bot.tossStack(j) } catch (e) {} }
}

async function digAt (dx, dy, dz) {
  const b = bot.blockAt(bot.entity.position.floored().offset(dx, dy, dz))
  if (b && b.boundingBox === 'block' && bot.canDigBlock(b)) { try { await bot.dig(b) } catch (e) {} }
}

async function act (a) {
  const name = ACTIONS[a]
  const [fx, fz] = DIRS[heading]
  switch (name) {
    case 'forward': await face(); bot.setControlState('jump', true); await hold('forward', 5); bot.setControlState('jump', false); break
    case 'turn_left': heading = (heading + 3) % 4; await face(); break
    case 'turn_right': heading = (heading + 1) % 4; await face(); break
    case 'dig_front': await digAt(fx, 1, fz); await digAt(fx, 0, fz); break
    case 'wait': break
    case 'craft_new': await craftFrom(() => craftable(newNames()).slice(0, 3), true); break
    case 'eat': { const f = items().find(i => mcData.foodsByName[i.name]); if (f && bot.food < 20) { try { await bot.equip(f, 'hand'); await bot.consume() } catch (e) {} } break }
    case 'back': await hold('back', 5); break
    case 'strafe_left': await hold('left', 5); break
    case 'strafe_right': await hold('right', 5); break
    case 'jump': await hold('jump', 3); break
    case 'toggle_sprint': sprint = !sprint; bot.setControlState('sprint', sprint); break
    case 'toggle_sneak': sneak = !sneak; bot.setControlState('sneak', sneak); break  // holding Shift
    case 'look_up': pitch = Math.max(-1, pitch - 1); await face(); break
    case 'look_down': pitch = Math.min(1, pitch + 1); await face(); break
    case 'attack': await attack(); break
    case 'use_item': bot.activateItem(); await bot.waitForTicks(10); bot.deactivateItem(); break
    case 'dig_down': await digAt(0, -1, 0); break
    case 'equip_armor': await equipArmor(); break
    case 'equip_weapon': await equipBest(/_(sword|axe)$/, n => tier(n) * 2 + (n.endsWith('_sword') ? 1 : 0)); break
    case 'equip_tool': await equipTool(); break
    case 'place_block': await placeFront(items().find(i => mcData.blocksByName[i.name] && !/table|furnace|bed|chest/.test(i.name))); break
    case 'craft_gear': await craftFrom(() => craftable(GEAR).sort((a, b) => gearValue(b[2]) - gearValue(a[2])).slice(0, 2), true); break
    case 'smelt': await smelt(); break
    case 'sleep': await sleep(); break
    case 'drop_junk': await dropJunk(); break
  }
}

// ---------------------------------------------------------------- old shaped reward (only used without --self)
const count = pred => items().filter(i => pred(i.name)).reduce((s, i) => s + i.count, 0)
function reward () {
  const logs = count(n => n.endsWith('_log')); const stone = count(n => n === 'cobblestone' || n === 'stone')
  let r = -0.01 + Math.max(0, logs - lastLogs) + Math.max(0, stone - lastStone) * 0.3
  const obs = observe(); let near = 9
  obs.forEach((c, i) => { if (c === 1) near = Math.min(near, Math.floor(i / 5) + Math.abs(i % 5 - 2)) })
  if (near < lastNear) r += 0.05; else if (near > lastNear && lastNear < 9) r -= 0.05
  lastNear = near
  if (bot.health < lastHealth) r -= 1.0
  lastLogs = logs; lastStone = stone; lastHealth = bot.health
  return { r, logs }
}

// ---------------------------------------------------------------- life loop
replies.on('line', line => { if (waiting) { const w = waiting; waiting = null; w(JSON.parse(line)) } })
const ask = msg => new Promise(res => { waiting = res; brain.write(JSON.stringify(msg) + '\n') })

async function selftest () {  // --selftest: prove every action works (needs op for /give)
  const give = async (x) => { bot.chat(`/give @s ${x}`); await bot.waitForTicks(10) }
  const res = []
  const check = async (name, before, after) => { try { await before(); await act(ACTIONS.indexOf(name)); await bot.waitForTicks(20); res.push([name, !!(await after())]) } catch (e) { res.push([name, false]) } }
  bot.chat('/time set day'); bot.chat('/clear @s'); bot.chat('/spreadplayers ~ ~ 0 20 false @s'); await bot.waitForTicks(60)
  await check('sleep', () => give('red_bed 1').then(() => bot.chat('/time set night')).then(() => bot.waitForTicks(20)), () => bot.findBlock({ matching: b => b.name === 'red_bed', maxDistance: 5 }))
  await act(ACTIONS.indexOf('sleep')); await bot.waitForTicks(20)
  res.push(['sleep(in bed)', bot.isSleeping])
  bot.chat('/time set day')
  await check('equip_armor', () => give('iron_chestplate 1').then(() => give('iron_helmet 1')), () => bot.inventory.slots[6] && bot.inventory.slots[5])
  await check('equip_weapon', () => give('stone_sword 1'), () => bot.heldItem && bot.heldItem.name.endsWith('_sword'))
  await check('toggle_sneak', async () => {}, () => bot.getControlState('sneak'))
  await act(ACTIONS.indexOf('toggle_sneak'))
  await check('toggle_sprint', async () => {}, () => bot.getControlState('sprint'))
  await act(ACTIONS.indexOf('toggle_sprint'))
  await check('craft_gear', () => give('oak_planks 8').then(() => give('stick 4')).then(() => give('crafting_table 1')), () => items().some(i => i.name === 'wooden_pickaxe' || i.name === 'wooden_sword' || i.name === 'wooden_axe'))
  await check('craft_new', async () => {}, () => items().length > 0)
  await check('place_block', () => give('cobblestone 8'), () => true)
  await check('smelt', () => give('furnace 1').then(() => give('raw_iron 3')).then(() => give('coal 3')), () => bot.findBlock({ matching: b => b.name === 'furnace', maxDistance: 5 }))
  await check('attack', async () => { bot.chat('/summon pig ^ ^ ^2'); await bot.waitForTicks(20) }, () => true)
  await check('eat', () => give('bread 3').then(() => bot.chat('/effect give @s hunger 5 20')).then(() => bot.waitForTicks(100)), () => true)
  await check('dig_down', async () => {}, () => true)
  await check('drop_junk', () => give('dirt 5'), () => !items().some(i => i.name === 'dirt'))
  console.log('SELFTEST ' + JSON.stringify(res))
  process.exit(0)
}

bot.once('spawn', async () => {
  mcData = require('minecraft-data')(bot.version)
  if (SELFTEST) { await bot.waitForTicks(40); return selftest() }
  if (VIEWER) require('prismarine-viewer').mineflayer(bot, { port: VIEWER, firstPerson: true, viewDistance: 4 })
  console.log(`spawned; ${ACTIONS.length} actions, ${Object.keys(RECIPES).length} recipes, ${Object.keys(ADV).length} advancements known`)
  lastHealth = bot.health
  let done = false
  bot.on('death', () => { done = true })
  bot.on('chat', (user, message) => { if (user !== bot.username) heard.push([user, message]) })
  bot.on('messagestr', m => {
    if (!m.startsWith(bot.username + ' ')) return
    const adv = m.match(/(?:made the advancement|reached the goal|completed the challenge) \[(.+)\]/)
    if (adv) { advancements.add(adv[1]); newAdvancements.push([ADV_BY_TITLE[adv[1]] || adv[1], adv[1]]) } else deathMsg = m.slice(bot.username.length + 1)
  })
  for (;;) {
    const { r, logs } = reward()
    if (step % 20 === 0) { canCraftNew = craftable(newNames()).length > 0; canCraftGear = craftable(GEAR).length > 0 }
    const pos = bot.entity.position
    const reply = await ask({
      obs: observe(), inv: logs, goal: goal(), reward: done ? r - 1 : r, done, n_actions: ACTIONS.length,
      items: inventory(), chunk: [Math.floor(pos.x / 16), Math.floor(pos.z / 16)], food: bot.food, health: bot.health,
      can_craft_new: canCraftNew, feat: features(), died: done ? deathMsg : '',
      heard: heard.splice(0), advancements: newAdvancements.splice(0)
    })
    if (reply.say) bot.chat(reply.say.slice(0, 250))
    done = false
    step++
    if (WANDER && step % WANDER === 0) bot.chat('/spreadplayers ~ ~ 0 300 false @s')
    if (step % 100 === 0) {
      console.log(`step ${step} pos ${pos.x.toFixed(0)},${pos.y.toFixed(0)},${pos.z.toFixed(0)} hp ${bot.health} food ${bot.food} ` +
        `items ${items().length} adv ${advancements.size} action ${ACTIONS[reply.action]}`)
    }
    try { await act(reply.action) } catch (e) {}
    await new Promise(res => setTimeout(res, STEP_MS))
  }
})
bot.on('kicked', console.log)
bot.on('error', console.log)
