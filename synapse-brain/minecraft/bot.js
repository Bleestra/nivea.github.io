// Mineflayer body for SynapseBrain: senses the world, asks the brain for an action, acts.
//
//   npm install mineflayer
//   node bot.js --host localhost --port 25565 --name SynapseBrain --brain 5555
//
// Observation = the same 5x5 egocentric grid as MiniCraft (rows = distance ahead 0..4,
// columns = left..right), one block class per cell at the bot's feet level:
//   0 walkable (air/grass/flowers)  1 tree (log/leaves)  2 stone/ore  3 lava  4 water  5 other solid
// Reward: +1 per log picked up, +0.3 per stone/cobblestone, -1 when hurt, -0.01 per step.
const mineflayer = require('mineflayer')
const net = require('net')
const readline = require('readline')

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d }
const bot = mineflayer.createBot({
  host: arg('host', 'localhost'), port: +arg('port', 25565),
  username: arg('name', 'SynapseBrain'), auth: arg('auth', 'offline'), version: arg('version', undefined)
})
const brain = net.connect(+arg('brain', 5555), '127.0.0.1')
const VIEWER = +arg('viewer', 0)
const WANDER = +arg('wander', 0)  // e.g. --wander 150: teleport somewhere new every 150 steps (needs op)
const replies = readline.createInterface({ input: brain })
const STEP_MS = +arg('step', 250)
const DIRS = [[0, -1], [1, 0], [0, 1], [-1, 0]]  // N E S W as (dx, dz)

let step = 0, lastNear = 9, heading = 0, lastHealth = 20, lastLogs = 0, lastStone = 0, waiting = null

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

function observe () {
  const p = bot.entity.position.floored()
  const [fx, fz] = DIRS[heading]
  const [rx, rz] = DIRS[(heading + 1) % 4]
  const obs = []
  for (let a = 0; a < 5; a++) {
    for (let b = -2; b <= 2; b++) {
      const x = p.x + fx * a + rx * b, z = p.z + fz * a + rz * b
      const feet = blockClass(bot.blockAt(p.offset(x - p.x, 0, z - p.z)))
      const head = blockClass(bot.blockAt(p.offset(x - p.x, 1, z - p.z)))
      const above = blockClass(bot.blockAt(p.offset(x - p.x, 2, z - p.z)))
      let c
      if (feet === 1 || head === 1) c = 1                 // a tree trunk or leaves
      else if (feet === 3 || head === 3) c = 3            // lava
      else if (feet === 4) c = 4                          // water
      else if (feet === 2 || head === 2) c = 2            // stone / ore
      else if (head === 0 && (feet === 0 || above === 0)) c = 0  // walkable (or a 1-block step up)
      else c = 5                                          // wall
      obs.push(c)
    }
  }
  return obs
}

function goal () {  // far vision: direction + distance bucket of the nearest log (0 = none)
  const y = bot.entity.position.y  // only logs we can actually reach (feet or head level)
  const t = bot.findBlock({ matching: b => b.name.endsWith('_log') && b.position.y >= Math.floor(y) - 1 &&
    b.position.y <= Math.floor(y) + 1, useExtraInfo: true, maxDistance: 32 })
  if (!t) return 0
  const p = bot.entity.position.floored()
  const dx = t.position.x - p.x, dz = t.position.z - p.z
  const [fx, fz] = DIRS[heading], [rx, rz] = DIRS[(heading + 1) % 4]
  const ahead = dx * fx + dz * fz, right = dx * rx + dz * rz
  const dir = Math.abs(ahead) >= Math.abs(right) ? (ahead > 0 ? 1 : 3) : (right > 0 ? 2 : 4)
  const dist = Math.abs(dx) + Math.abs(dz)
  return dir * 4 + (dist <= 1 ? 0 : dist <= 3 ? 1 : dist <= 8 ? 2 : 3)
}

let mcData = null
let deathMsg = ''
const everHeld = new Set()
let canCraftNew = false

function inventory () {
  const inv = {}
  for (const i of bot.inventory.items()) { inv[i.name] = (inv[i.name] || 0) + i.count; everHeld.add(i.name) }
  return inv
}

function craftableNew () {  // recipes (by hand or at a nearby table) that give something never held
  const table = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 4 })
  const out = []
  for (const it of mcData.itemsArray) {
    if (everHeld.has(it.name)) continue
    const rs = bot.recipesFor(it.id, null, 1, table)
    if (rs.length) out.push([rs[0], table])
    if (out.length >= 3) break
  }
  return out
}

async function placeTable () {  // put a crafting table on the ground in front
  const t = bot.inventory.items().find(i => i.name === 'crafting_table')
  if (!t) return false
  const p = bot.entity.position.floored(), [fx, fz] = DIRS[heading]
  const ground = bot.blockAt(p.offset(fx, -1, fz)), spot = bot.blockAt(p.offset(fx, 0, fz))
  if (!ground || ground.boundingBox !== 'block' || !spot || spot.boundingBox !== 'empty') return false
  try { await bot.equip(t, 'hand'); await bot.placeBlock(ground, new (require('vec3'))(0, 1, 0)); return true } catch (e) { return false }
}

async function craftNew () {
  let opts = craftableNew()
  if (!opts.length && !bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 4 })) {
    if (await placeTable()) opts = craftableNew()
  }
  for (const [r, table] of opts) { try { await bot.craft(r, 1, table); return true } catch (e) {} }
  return false
}

async function eat () {
  const food = bot.inventory.items().find(i => mcData.foodsByName[i.name])
  if (!food || bot.food >= 20) return false
  try { await bot.equip(food, 'hand'); await bot.consume(); return true } catch (e) { return false }
}

const count = (pred) => bot.inventory.items().filter(i => pred(i.name)).reduce((s, i) => s + i.count, 0)

function reward () {
  const logs = count(n => n.endsWith('_log'))
  const stone = count(n => n === 'cobblestone' || n === 'stone')
  let r = -0.01 + Math.max(0, logs - lastLogs) * 1.0 + Math.max(0, stone - lastStone) * 0.3
  // appetite: a little dopamine for getting closer to a visible tree, a little less for moving away
  const obs = observe()
  let near = 9
  obs.forEach((c, i) => { if (c === 1) near = Math.min(near, Math.floor(i / 5) + Math.abs(i % 5 - 2)) })
  if (near < lastNear) r += 0.05
  else if (near > lastNear && lastNear < 9) r -= 0.05
  lastNear = near
  if (bot.health < lastHealth) r -= 1.0
  lastLogs = logs; lastStone = stone; lastHealth = bot.health
  return { r, logs }
}

async function act (a) {
  const face = () => { const [fx, fz] = DIRS[heading]; return bot.lookAt(bot.entity.position.offset(fx * 3, 1.6, fz * 3), true) }
  if (a === 0) {  // step forward, hopping up 1-block ledges like a player
    await face(); bot.setControlState('forward', true); bot.setControlState('jump', true)
    await bot.waitForTicks(5); bot.setControlState('forward', false); bot.setControlState('jump', false)
  }
  if (a === 1) { heading = (heading + 3) % 4; await face() }
  if (a === 2) { heading = (heading + 1) % 4; await face() }
  if (a === 5) await craftNew()
  if (a === 6) await eat()
  if (a === 3) {
    const p = bot.entity.position.floored(), [fx, fz] = DIRS[heading]
    for (const dy of [1, 0]) {
      const b = bot.blockAt(p.offset(fx, dy, fz))
      if (b && b.boundingBox === 'block' && bot.canDigBlock(b)) { try { await bot.dig(b) } catch (e) {} break }
    }
  }
}

replies.on('line', (line) => { if (waiting) { const w = waiting; waiting = null; w(JSON.parse(line)) } })
const ask = (msg) => new Promise(res => { waiting = res; brain.write(JSON.stringify(msg) + '\n') })

bot.once('spawn', async () => {
  mcData = require('minecraft-data')(bot.version)
  if (VIEWER) require('prismarine-viewer').mineflayer(bot, { port: VIEWER, firstPerson: true, viewDistance: 4 })
  console.log('spawned, brain connected - learning starts')
  lastHealth = bot.health
  let done = false
  bot.on('death', () => { done = true })
  bot.on('messagestr', (m) => { if (m.startsWith(bot.username + ' ')) deathMsg = m.slice(bot.username.length + 1) })
  for (;;) {
    const { r, logs } = reward()
    if (step % 20 === 0) canCraftNew = craftableNew().length > 0
    const pos = bot.entity.position
    const reply = await ask({ obs: observe(), inv: logs, goal: goal(), reward: done ? r - 1 : r, done,
      items: inventory(), chunk: [Math.floor(pos.x / 16), Math.floor(pos.z / 16)],
      food: bot.food, health: bot.health, can_craft_new: canCraftNew, died: done ? deathMsg : '' })
    const a = reply.action
    if (reply.say) bot.chat(reply.say)
    done = false
    step++
    if (WANDER && step % WANDER === 0) bot.chat('/spreadplayers ~ ~ 0 300 false @s')
    if (step % 100 === 0) {
      const p = bot.entity.position
      const obs = observe()
      const trees = bot.findBlocks({ matching: b => b.name.endsWith('_log'), maxDistance: 16, count: 50 }).length
      console.log(`step ${step} pos ${p.x.toFixed(0)},${p.y.toFixed(0)},${p.z.toFixed(0)} logs ${logs} ` +
        `hp ${bot.health} trees<16m ${trees} goal ${goal()} view ${obs.join('')}`)
    }
    await act(a)
    await new Promise(res => setTimeout(res, STEP_MS))
  }
})
bot.on('kicked', console.log)
bot.on('error', console.log)
