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
const replies = readline.createInterface({ input: brain })
const STEP_MS = +arg('step', 250)
const DIRS = [[0, -1], [1, 0], [0, 1], [-1, 0]]  // N E S W as (dx, dz)

let heading = 0, lastHealth = 20, lastLogs = 0, lastStone = 0, waiting = null

function blockClass (b) {
  if (!b) return 5
  const n = b.name
  if (n.includes('lava')) return 3
  if (n.includes('water')) return 4
  if (n.endsWith('_log') || n.endsWith('_leaves') || n.endsWith('_wood')) return 1
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
      obs.push(feet === 0 ? head : feet)
    }
  }
  return obs
}

const count = (pred) => bot.inventory.items().filter(i => pred(i.name)).reduce((s, i) => s + i.count, 0)

function reward () {
  const logs = count(n => n.endsWith('_log'))
  const stone = count(n => n === 'cobblestone' || n === 'stone')
  let r = -0.01 + (logs - lastLogs) * 1.0 + (stone - lastStone) * 0.3
  if (bot.health < lastHealth) r -= 1.0
  lastLogs = logs; lastStone = stone; lastHealth = bot.health
  return { r, logs }
}

async function act (a) {
  const face = () => { const [fx, fz] = DIRS[heading]; return bot.lookAt(bot.entity.position.offset(fx * 3, 1.6, fz * 3), true) }
  if (a === 0) { await face(); bot.setControlState('forward', true); await bot.waitForTicks(4); bot.setControlState('forward', false) }
  if (a === 1) { heading = (heading + 3) % 4; await face() }
  if (a === 2) { heading = (heading + 1) % 4; await face() }
  if (a === 3) {
    const p = bot.entity.position.floored(), [fx, fz] = DIRS[heading]
    for (const dy of [1, 0]) {
      const b = bot.blockAt(p.offset(fx, dy, fz))
      if (b && b.boundingBox === 'block' && bot.canDigBlock(b)) { try { await bot.dig(b) } catch (e) {} break }
    }
  }
}

replies.on('line', (line) => { if (waiting) { const w = waiting; waiting = null; w(JSON.parse(line).action) } })
const ask = (msg) => new Promise(res => { waiting = res; brain.write(JSON.stringify(msg) + '\n') })

bot.once('spawn', async () => {
  console.log('spawned, brain connected - learning starts')
  lastHealth = bot.health
  let done = false
  bot.on('death', () => { done = true })
  for (;;) {
    const { r, logs } = reward()
    const a = await ask({ obs: observe(), inv: logs, reward: done ? r - 1 : r, done })
    done = false
    await act(a)
    await new Promise(res => setTimeout(res, STEP_MS))
  }
})
bot.on('kicked', console.log)
bot.on('error', console.log)
