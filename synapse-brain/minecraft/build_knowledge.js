// Builds the bot's reference book: every crafting recipe and every advancement of the game version.
//   node build_knowledge.js [version] [path/to/server.jar]
// Writes knowledge/recipes.json, knowledge/recipes.txt, knowledge/advancements.json (+ .txt)
const fs = require('fs')
const path = require('path')
const version = process.argv[2] || '1.20.4'
const d = require('minecraft-data')(version)
const L = d.language || {}
const name = id => { const it = d.items[id]; return it ? it.displayName : String(id) }
const out = path.join(__dirname, 'knowledge')
fs.mkdirSync(out, { recursive: true })

const recipes = {}
const lines = []
for (const [id, rs] of Object.entries(d.recipes)) {
  const it = d.items[id]
  if (!it) continue
  recipes[it.name] = rs.map(r => {
    const ing = {}
    const add = x => { if (x === null || x === undefined) return; const k = Array.isArray(x) ? x[0] : (typeof x === 'object' ? x.id : x); if (k === null || k === undefined) return; ing[name(k)] = (ing[name(k)] || 0) + 1 }
    if (r.inShape) r.inShape.flat().forEach(add)
    if (r.ingredients) r.ingredients.forEach(add)
    return { makes: r.result.count, shaped: !!r.inShape, needs_table: !!((r.inShape && (r.inShape.length > 2 || r.inShape[0].length > 2)) || (r.ingredients && r.ingredients.length > 4)), ingredients: ing }
  })
  const r0 = recipes[it.name][0]
  lines.push(`To craft ${it.displayName} (x${r0.makes}${r0.needs_table ? ', at a crafting table' : ''}): ` +
    Object.entries(r0.ingredients).map(([k, v]) => `${v} ${k}`).join(', ') + '.')
}
fs.writeFileSync(path.join(out, 'recipes.json'), JSON.stringify(recipes, null, 1))
fs.writeFileSync(path.join(out, 'recipes.txt'), lines.join('\n') + '\n')

const adv = {}
const jar = process.argv[3]
if (jar && fs.existsSync(jar)) {
  const { execSync } = require('child_process')
  const list = execSync(`python3 -c "import zipfile,json,sys; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps({n: z.read(n).decode() for n in z.namelist() if n.startswith('data/minecraft/advancements/') and n.endswith('.json')}))" "${jar}"`, { maxBuffer: 1 << 26 })
  for (const [file, text] of Object.entries(JSON.parse(list))) {
    const a = JSON.parse(text)
    const id = file.replace('data/minecraft/advancements/', '').replace('.json', '')
    if (id.startsWith('recipes/')) continue
    const t = a.display && a.display.title && (a.display.title.translate || a.display.title)
    const ds = a.display && a.display.description && (a.display.description.translate || a.display.description)
    adv[id] = { title: L[t] || t || id, description: L[ds] || ds || '', parent: a.parent ? a.parent.replace('minecraft:', '') : null,
      criteria: Object.keys(a.criteria || {}) }
  }
}
fs.writeFileSync(path.join(out, 'advancements.json'), JSON.stringify(adv, null, 1))
fs.writeFileSync(path.join(out, 'advancements.txt'), Object.entries(adv).map(([id, a]) =>
  `Advancement "${a.title}" (${id}): ${a.description}${a.parent ? ` Comes after ${a.parent}.` : ''}`).join('\n') + '\n')
console.log(`recipes: ${Object.keys(recipes).length} items, advancements: ${Object.keys(adv).length}`)
