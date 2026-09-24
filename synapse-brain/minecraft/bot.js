// Mineflayer body for SynapseBrain: full player controls, senses, a reference book of all recipes and
// advancements. The body only makes every action technically possible - WHEN to do what, the brain
// learns by itself.
//
//   npm install
//   node bot.js --host localhost --port 25565 --brain 5555 [--viewer 3007] [--version 1.20.4]
const mineflayer = require('mineflayer')
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder')
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
  'equip_tool', 'place_block', 'craft_gear', 'smelt', 'sleep', 'drop_junk', 'pillar_up', 'dig_up',
  'fish', 'interact', 'store', 'take', 'place_chest', 'trade', 'read',
  // motor programs aimed by the brain's attention (reply.target): reach, dig, craft, walk to a remembered place
  'approach', 'mine_target', 'craft_target', 'goto_place', 'explore']

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

const solid = b => b && b.boundingBox === 'block' && !b.name.includes('leaves')
function seesSky () {  // nothing solid above the head (leaves let light through)
  const p = bot.entity.position.floored()
  for (let dy = 2; dy < 64; dy++) { const b = bot.blockAt(p.offset(0, dy, 0)); if (b === null) break; if (solid(b)) return 0 }
  return 1
}

function around () {  // touch and balance: what is right next to me on every side, above and below
  const p = bot.entity.position.floored(); const out = []
  for (let k = 0; k < 4; k++) {  // relative: front, right, back, left
    const [fx, fz] = DIRS[(heading + k) % 4]
    out.push(blockClass(bot.blockAt(p.offset(fx, 0, fz))) * 6 + blockClass(bot.blockAt(p.offset(fx, 1, fz))))
  }
  out.push(blockClass(bot.blockAt(p.offset(0, 2, 0))), blockClass(bot.blockAt(p.offset(0, -1, 0))))
  return out
}

// ---------------------------------------------------------------- senses for feelings
// Who is around, by kind (as a child tells a cat from a zombie); what happened to beings nearby;
// explosions; what became of the blocks I placed myself (efference copy, not a script about houses).
const mine = new Set()            // ids of animals I tamed
let lastHit = null
const built = new Map()           // "x,y,z" -> block name I placed
const feelEv = { deaths: [], hurt: [], lost: [], boom: false, gift: false, tamed: null, carerDid: null, ate: null, trades: [], traded: null, read: null }
const kindOf = e => {
  if (!e || e === bot.entity) return null
  if (e.type === 'player') return 'carer'
  const n = (e.name || '').toLowerCase()
  if (n === 'creeper') return 'creeper'
  if (n === 'villager' || n === 'wandering_trader') return 'villager'
  if (n === 'iron_golem') return 'golem'
  if (/zombie|husk|drowned/.test(n)) return 'zombie'
  if (n === 'cat' || n === 'ocelot' || n === 'wolf' || n === 'parrot') return mine.has(e.id) ? 'mycat' : 'cat'
  if (isHostile(e)) return 'hostile'
  if (isAnimal(e)) return 'animal'
  return null
}
function nearList () {
  const out = []
  for (const e of Object.values(bot.entities)) {
    const k = kindOf(e); if (!k) continue
    const d = Math.floor(e.position.distanceTo(bot.entity.position))
    if (d <= 8) out.push([k, e.id, d])
  }
  return out
}
function takeFeelEv () { const e = { ...feelEv }; feelEv.deaths = []; feelEv.hurt = []; feelEv.lost = []; feelEv.boom = false; feelEv.gift = false; feelEv.tamed = null; feelEv.carerDid = null; feelEv.ate = null; feelEv.trades = []; feelEv.traded = null; feelEv.read = null; return e }
function bookText (it) {  // the pages of a written book (JSON text components)
  try {
    const pages = it.nbt.value.pages.value.value
    return pages.map(p => { try { const j = JSON.parse(p); return typeof j === 'string' ? j : (j.text || '') } catch (e) { return p } }).join(' ')
  } catch (e) { return '' }
}
// ---------------------------------------------------------------- what the eyes see (visible only)
function visible (b) {  // a ray from the eyes reaches this block first (the eye cannot see through walls)
  const p = bot.entity.position
  if (b.position.distanceTo(p) < 2.5) return true
  const eye = p.offset(0, bot.entity.height * 0.9, 0)
  for (const [ox, oy, oz] of [[0.5, 0.5, 0.5], [0.5, 0.95, 0.5], [0.5, 0.05, 0.5]]) {
    const c = b.position.offset(ox, oy, oz)
    const dir = c.minus(eye).normalize()
    const hit = bot.world.raycast(eye, dir, c.distanceTo(eye) + 0.5)
    if (hit && hit.position.equals(b.position)) return true
  }
  return false
}
let seenCache = { t: -99, list: [] }
function seenThings () {  // nearest visible block of each kind + visible creatures: [name, distance]
  if (step - seenCache.t < 5) return seenCache.list
  const p = bot.entity.position
  const found = new Map()
  const blocks = bot.findBlocks({ matching: b => b && b.name !== 'air' && b.name !== 'cave_air' && b.name !== 'void_air', maxDistance: 12, count: 600 })
  blocks.sort((a, b) => a.distanceTo(p) - b.distanceTo(p))
  for (const q of blocks) {
    const b = bot.blockAt(q); if (!b || found.has(b.name)) continue
    if (!visible(b)) continue
    found.set(b.name, Math.floor(q.distanceTo(p)))
  }
  for (const e of Object.values(bot.entities)) {
    if (e === bot.entity || !e.name) continue
    const d = e.position.distanceTo(p)
    if (d < 16 && (!found.has(e.name) || found.get(e.name) > d)) found.set(e.name, Math.floor(d))
  }
  seenCache = { t: step, list: [...found.entries()] }
  return seenCache.list
}
function nearestSeenBlock (name) {
  const p = bot.entity.position
  const bs = bot.findBlocks({ matching: b => b && b.name === name, maxDistance: 16, count: 40 }).sort((a, b) => a.distanceTo(p) - b.distanceTo(p))
  for (const q of bs) { const b = bot.blockAt(q); if (b && visible(b)) return b }
  return null
}
async function goNear (pos, range = 1) {
  try { await bot.pathfinder.goto(new goals.GoalNear(pos.x, pos.y, pos.z, range)) } catch (e) { dbg('path', e.message) } finally { bot.pathfinder.setGoal(null) }
}

function oreSeen () {  // a diamond ore my eyes can actually see (not through walls)
  const b = bot.findBlock({ matching: x => x.name === 'diamond_ore' || x.name === 'deepslate_diamond_ore', maxDistance: 8, count: 1, useExtraInfo: x => visible(x) })
  return b ? relDir(b.position) : 0
}
const itemName = it => it ? `${it.count}x${it.name}` : ''
async function villagerNear () { return bot.nearestEntity(e => (e.name === 'villager' || e.name === 'wandering_trader') && e.position.distanceTo(bot.entity.position) < 4) }
async function seeTrades (t) {  // right-click a villager: its trading window opens, the eyes read the offers
  const v = await bot.openVillager(t)
  feelEv.trades = (v.trades || []).map(x => [itemName(x.inputItem1) + (x.inputItem2 && x.inputItem2.name ? '+' + itemName(x.inputItem2) : ''), itemName(x.outputItem), !!x.tradeDisabled])
  return v
}

const trail = []  // where I have been in the last steps (for the feeling of being stuck)
function stuck () {
  const p = bot.entity.position
  trail.push(p.clone()); if (trail.length > 12) trail.shift()
  if (trail.length < 12) return 0
  let far = 0; for (const q of trail) far = Math.max(far, q.distanceTo(p))
  return far < 1.5 ? 1 : 0
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
    try { await bot.equip(item, 'hand'); await bot.placeBlock(ground, new Vec3(0, 1, 0)); const q = ground.position.offset(0, 1, 0); built.set(`${q.x},${q.y},${q.z}`, item.name); return true } catch (e) { dbg('place', item.name, e.message) }
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
  lastHit = target.id
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

async function pillarUp () {
  const full = n => mcData.blocksByName[n] && mcData.blocksByName[n].boundingBox === 'block' &&
    !/table|furnace|bed|chest|sapling|torch|slab|stairs|wall|fence|door|trapdoor|sand|gravel|leaves|glass/.test(n)
  const blk = items().filter(i => full(i.name)).sort((a, b) => b.count - a.count)[0]
  if (!blk) { dbg('pillar: no blocks'); return }
  const below = bot.blockAt(bot.entity.position.offset(0, -0.5, 0).floored())
  if (!solid(below)) { dbg('pillar: nothing under me', below && below.name); return }
  try {
    await bot.equip(blk, 'hand'); await bot.look(bot.entity.yaw, -Math.PI / 2, true)
    const y0 = bot.entity.position.y
    bot.setControlState('jump', true)
    for (let t = 0; t < 10 && bot.entity.position.y < y0 + 1.0; t++) await bot.waitForTicks(1)
    bot.setControlState('jump', false)
    dbg('pillar: jumped', y0, '->', bot.entity.position.y, 'placing on', below.name)
    await bot.placeBlock(below, new Vec3(0, 1, 0))
    { const q = below.position.offset(0, 1, 0); built.set(`${q.x},${q.y},${q.z}`, blk.name) }
    dbg('pillar: placed, y', bot.entity.position.y)
  } catch (e) { bot.setControlState('jump', false); dbg('pillar', e.message) }
  await face()
}

async function digAt (dx, dy, dz) {
  const b = bot.blockAt(bot.entity.position.floored().offset(dx, dy, dz))
  if (b && b.boundingBox === 'block' && bot.canDigBlock(b)) { try { await bot.dig(b) } catch (e) {} }
}

let target = null
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
    case 'eat': { const fs = items().filter(i => mcData.foodsByName[i.name]); const f = fs[Math.floor(Math.random() * fs.length)]; if (f && bot.food < 20) { try { await bot.equip(f, 'hand'); await bot.consume(); feelEv.ate = f.name } catch (e) {} } break }
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
    case 'fish': { const rod = items().find(i => i.name === 'fishing_rod'); if (rod) { try { await bot.equip(rod, 'hand'); await Promise.race([bot.fish(), bot.waitForTicks(400)]) } catch (e) { dbg('fish', e.message) } } break }
    case 'interact': {  // right-click the nearest being: feed, tame, greet - or open a villager's trades
      const t = bot.nearestEntity(e => e !== bot.entity && (isAnimal(e) || e.type === 'player' || /cat|ocelot|wolf|villager|trader/.test(e.name || '')) && e.position.distanceTo(bot.entity.position) < 4)
      if (t && /villager|trader/.test(t.name || '')) {
        try { await bot.lookAt(t.position.offset(0, 1.5, 0), true); const v = await seeTrades(t); await bot.waitForTicks(10); v.close() } catch (e) { dbg('villager', e.message) }
      } else if (t) {
        const food = items().find(i => /^(cod|salmon|bone|wheat|carrot|seeds|wheat_seeds)$/.test(i.name)) || items().find(i => mcData.foodsByName[i.name])
        try { if (food) await bot.equip(food, 'hand'); await bot.lookAt(t.position.offset(0, t.height * 0.7, 0), true); await bot.activateEntity(t) } catch (e) { dbg('interact', e.message) }
      }
      break
    }
    case 'store': case 'take': {
      const c = bot.findBlock({ matching: b => b.name === 'chest', maxDistance: 4 })
      if (!c) break
      try {
        const box = await bot.openContainer(c)
        if (name === 'store') { for (const i of items()) { if (!/_(pickaxe|sword|axe|shovel)$|fishing_rod/.test(i.name)) await box.deposit(i.type, null, i.count) } } else { for (const i of box.containerItems()) await box.withdraw(i.type, null, i.count) }
        box.close()
      } catch (e) { dbg(name, e.message) }
      break
    }
    case 'place_chest': await placeFront(items().find(i => i.name === 'chest')); break
    case 'approach': {  // walk to the thing my attention picked (a visible block or creature)
      const t = String(target || '')
      const e = bot.nearestEntity(x => x.name === t && x !== bot.entity && x.position.distanceTo(bot.entity.position) < 16)
      const b = e ? null : nearestSeenBlock(t)
      if (e) await goNear(e.position, 2); else if (b) await goNear(b.position, 1)
      break
    }
    case 'mine_target': {  // reach the attended block and dig it out with the right tool
      const b = nearestSeenBlock(String(target || ''))
      if (!b) break
      if (b.position.distanceTo(bot.entity.position) > 4) await goNear(b.position, 2)
      try { const kind = b.material && b.material.includes('pickaxe') ? /_pickaxe$/ : b.material && b.material.includes('axe') ? /_axe$/ : b.material && b.material.includes('shovel') ? /_shovel$/ : null; if (kind) await equipBest(kind, tier); if (bot.canDigBlock(b)) await bot.dig(b) } catch (e) { dbg('mine', e.message) }
      break
    }
    case 'craft_target': await craftFrom(() => craftable([String(target || '')]), true); break  // make the item the mind wants
    case 'goto_place': if (Array.isArray(target)) { try { await bot.pathfinder.goto(new goals.GoalXZ(target[0], target[1])) } catch (e) { dbg('goto', e.message) } finally { bot.pathfinder.setGoal(null) } } break
    case 'explore': { const a = Math.random() * 2 * Math.PI; const p = bot.entity.position; try { await bot.pathfinder.goto(new goals.GoalXZ(Math.floor(p.x + 24 * Math.cos(a)), Math.floor(p.z + 24 * Math.sin(a)))) } catch (e) { dbg('explore', e.message) } finally { bot.pathfinder.setGoal(null) } break }
    case 'read': { const b = items().find(i => i.name === 'written_book' || i.name === 'writable_book'); if (b) feelEv.read = bookText(b); break }
    case 'trade': {  // try the first offer I can pay for
      const t = await villagerNear()
      if (!t) break
      try {
        const v = await seeTrades(t)
        const have = n => items().filter(i => i.name === n).reduce((s, i) => s + i.count, 0)
        const k = (v.trades || []).findIndex(x => !x.tradeDisabled && have(x.inputItem1.name) >= x.inputItem1.count &&
          (!x.inputItem2 || have(x.inputItem2.name) >= x.inputItem2.count))
        if (k >= 0) { await bot.trade(v, k, 1); feelEv.traded = v.trades[k].outputItem.name }
        v.close()
      } catch (e) { dbg('trade', e.message) }
      break
    }
    case 'pillar_up': await pillarUp(); break  // jump and put a block under my feet
    case 'dig_up': await digAt(0, 2, 0); break
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
  let y0 = 0
  await check('pillar_up', () => give('cobblestone 8').then(() => { y0 = bot.entity.position.y }), () => bot.entity.position.y >= y0 + 0.9)
  await check('dig_up', () => { bot.chat('/setblock ~ ~2 ~ dirt'); return bot.waitForTicks(10) }, () => { const b = bot.blockAt(bot.entity.position.floored().offset(0, 2, 0)); return b && b.name === 'air' })
  await check('place_chest', () => give('chest 1'), () => bot.findBlock({ matching: b => b.name === 'chest', maxDistance: 4 }))
  await check('store', () => give('cobblestone 5'), () => !items().some(i => i.name === 'cobblestone'))
  await check('take', async () => {}, () => items().some(i => i.name === 'cobblestone'))
  await check('interact', async () => { bot.chat('/summon cat ^ ^ ^2'); await give('cod 5'); await bot.waitForTicks(20) }, () => true)
  await check('fish', () => give('fishing_rod 1'), () => true)
  let p0 = null
  await check('approach', async () => { bot.chat('/setblock ~6 ~ ~ oak_log'); await bot.waitForTicks(10); target = 'oak_log'; dbg('seen log', !!nearestSeenBlock('oak_log'), bot.findBlocks({ matching: x => x.name === 'oak_log', maxDistance: 16, count: 5 }).map(String)) }, () => { const b = nearestSeenBlock('oak_log'); dbg('after', b && b.position.distanceTo(bot.entity.position)); return b && b.position.distanceTo(bot.entity.position) < 3.5 })
  await check('mine_target', async () => { target = 'oak_log' }, () => items().some(i => i.name === 'oak_log'))
  await check('craft_target', async () => { await give('oak_planks 4'); await give('stick 2'); target = 'wooden_shovel' }, () => items().some(i => i.name === 'wooden_shovel'))
  await check('goto_place', async () => { p0 = bot.entity.position.clone(); target = [Math.floor(p0.x) + 7, Math.floor(p0.z)] }, () => bot.entity.position.distanceTo(p0) > 4)
  await check('explore', async () => { p0 = bot.entity.position.clone() }, () => bot.entity.position.distanceTo(p0) > 5)
  console.log('SELFTEST ' + JSON.stringify(res))
  process.exit(0)
}

bot.once('spawn', async () => {
  mcData = require('minecraft-data')(bot.version)
  bot.loadPlugin(pathfinder)
  const mv = new Movements(bot); mv.canDig = true; mv.allowParkour = false; bot.pathfinder.setMovements(mv)
  if (SELFTEST) { await bot.waitForTicks(40); return selftest() }
  if (VIEWER) require('prismarine-viewer').mineflayer(bot, { port: VIEWER, firstPerson: true, viewDistance: 4 })
  console.log(`spawned; ${ACTIONS.length} actions, ${Object.keys(RECIPES).length} recipes, ${Object.keys(ADV).length} advancements known`)
  lastHealth = bot.health
  let done = false
  bot.on('death', () => { done = true })
  bot.on('chat', (user, message) => { if (user !== bot.username) heard.push([user, message]) })
  let digging = null
  bot.on('diggingCompleted', b => { digging = `${b.position.x},${b.position.y},${b.position.z}` })
  bot.on('blockUpdate', (oldB, newB) => {  // a block I placed is gone, and not because I dug it
    if (!oldB) return
    const k = `${oldB.position.x},${oldB.position.y},${oldB.position.z}`
    if (built.has(k) && newB && newB.name !== built.get(k)) {
      if (k !== digging) feelEv.lost.push([oldB.position.x, oldB.position.z, built.get(k)])
      built.delete(k)
    }
  })
  bot.on('entityDead', e => {
    const k = kindOf(e); if (!k) return
    const d = e.position.distanceTo(bot.entity.position)
    if (d <= 16) feelEv.deaths.push([k, e.id, mine.has(e.id), '', d <= 12])
    const p = bot.nearestEntity(x => x.type === 'player' && x.position.distanceTo(e.position) < 4)
    if (p && (k === 'zombie' || k === 'hostile' || k === 'creeper')) feelEv.carerDid = 'killed'
  })
  bot.on('entityHurt', e => {
    if (e === bot.entity) return
    const k = kindOf(e); if (!k || e.position.distanceTo(bot.entity.position) > 12) return
    feelEv.hurt.push([k, e.id, 1, lastHit === e.id ? 'self' : ''])
  })
  bot.on('entityTamed', e => { mine.add(e.id); feelEv.tamed = e.id })
  bot.on('entityTaming', e => { if (e.position.distanceTo(bot.entity.position) < 5) { mine.add(e.id); feelEv.tamed = e.id } })
  bot.on('hardcodedSoundEffectHeard', () => {})
  bot.on('soundEffectHeard', (name, pos) => { if (/explode/.test(name) && pos.distanceTo(bot.entity.position) < 24) feelEv.boom = true })
  bot.on('playerCollect', (collector, item) => {
    if (collector !== bot.entity) return
    const p = bot.nearestEntity(x => x.type === 'player' && x.position.distanceTo(bot.entity.position) < 5)
    if (p) feelEv.gift = true   // picked up something while a person stood by: most likely a gift
  })

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
      sky: seesSky(), around: around(), stuck: stuck(), y: Math.floor(pos.y),
      near: nearList(), fev: takeFeelEv(), time: bot.time ? bot.time.timeOfDay : 6000, heading, pitch,
      xz: [Math.floor(pos.x), Math.floor(pos.z)], held: bot.heldItem ? bot.heldItem.name : '', diamond_seen: oreSeen(), seen: seenThings(),
      carer_holds: (() => { const p = bot.nearestEntity(x => x.type === 'player' && x.position.distanceTo(bot.entity.position) < 8); return p && p.heldItem ? p.heldItem.name : null })(),
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
    target = reply.target
    try { await Promise.race([act(reply.action), new Promise(res => setTimeout(res, 8000))]) } catch (e) {}  // no action may hang the body
    if (bot.pathfinder) bot.pathfinder.setGoal(null)
    await new Promise(res => setTimeout(res, STEP_MS))
  }
})
bot.on('kicked', console.log)
bot.on('error', console.log)
