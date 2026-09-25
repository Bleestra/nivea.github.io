// Export the real Minecraft rules the simulated world needs: recipes, block drops and tools, foods.
//   node export_sim_data.js 1.20.4 > knowledge/sim_rules.json
const mcData = require('minecraft-data')(process.argv[2] || '1.20.4')
const name = id => (mcData.items[id] || mcData.blocks[id] || {}).name
const WOOD = n => n && n.replace(/^(spruce|birch|jungle|acacia|dark_oak|mangrove|cherry|bamboo|crimson|warped)_(planks|log)$/, 'oak_$2')
const recipes = {}
for (const [id, rs] of Object.entries(mcData.recipes)) {
  const out = name(+id); if (!out) continue
  for (const r of rs) {
    const need = {}
    const cells = r.inShape ? r.inShape.flat() : (r.ingredients || [])
    for (const c of cells) {
      if (c === null || c === undefined) continue
      const iid = typeof c === 'object' ? c.id : c
      if (iid === null || iid === undefined || iid < 0) continue
      const n = WOOD(name(iid)); need[n] = (need[n] || 0) + 1
    }
    const table = r.inShape ? (r.inShape.length > 2 || r.inShape.some(row => row.length > 2)) : cells.length > 4
    const key = JSON.stringify(need)
    recipes[out] = recipes[out] || []
    if (!recipes[out].some(x => JSON.stringify(x.need) === key)) recipes[out].push({ need, makes: r.result.count, table })
  }
}
const blocks = {}
for (const b of mcData.blocksArray) {
  blocks[b.name] = {
    hardness: b.hardness, diggable: b.diggable,
    tools: b.harvestTools ? Object.keys(b.harvestTools).map(t => name(+t)) : null,
    drops: (b.drops || []).map(d => name(typeof d === 'object' ? (d.drop && d.drop.id !== undefined ? d.drop.id : d.drop) : d)).filter(Boolean)
  }
}
const foods = {}
for (const f of mcData.foodsArray) foods[f.name] = { points: f.foodPoints, saturation: f.saturation }
const mobs = {}
for (const [n, e] of Object.entries(mcData.entityLoot || {})) mobs[n] = e.drops.map(d => [d.item, d.dropChance])
const gravel = mcData.blockLoot && mcData.blockLoot.gravel ? mcData.blockLoot.gravel.drops.filter(d => d.item === 'flint' && d.noSilkTouch).map(d => d.dropChance)[0] : 0.1
const ent = {}
for (const e of mcData.entitiesArray) ent[e.name] = { type: e.type, category: e.category }
console.log(JSON.stringify({ version: mcData.version.minecraftVersion, recipes, blocks, foods, mobs, flint_from_gravel: gravel, entities: ent }))
