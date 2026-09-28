// Builds one self-contained page (inline CSS + all local modules in one script) for hosts that only take a single file.
// Three.js stays an external module from the CDN, resolved through an import map.
// The module transform is deliberately narrow: it understands exactly the import/export forms this codebase uses.
// Usage: node tools/build-artifact.js [duel|classic|table] [out.html]
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const src = join(root, 'src');
const THREE_VERSION = '0.170.0';
const CORE = ['rng', 'board', 'content', 'state', 'power', 'abilities', 'engine', 'visibility', 'replay', 'invariants', 'bots'].map(m => `core/${m}`);
const DUEL = ['duel/content', 'duel/engine', 'duel/bots'];
const FONTS = 'family=Exo+2:ital,wght@0,500;0,600;0,700;0,800;0,900;1,700;1,800;1,900&family=Forum&family=Golos+Text:wght@400;600&family=IBM+Plex+Mono:wght@400;600;700';
const TARGETS = {
  duel: {
    modules: [...CORE, 'web/text', ...DUEL, 'arena/world', 'arena/world-day', 'arena/fx', 'arena/colossi', 'arena/cardart', 'arena/portraits', 'arena/sfx', 'arena/duel-stage', 'arena/duel-hud', 'arena/duel-director'],
    entry: 'arena/duel-main', css: ['arena/arena.css', 'arena/duel.css', 'arena/duel-skin.css'], title: 'Печати Разлома',
    body: '<div id="stage"></div>\n<div id="hud"></div>\n<noscript>Игре нужен JavaScript и WebGL.</noscript>',
  },
  classic: {
    modules: [...CORE, 'web/text', ...DUEL, 'arena/world', 'arena/fx', 'arena/colossi', 'arena/field', 'arena/cardart', 'arena/portraits', 'arena/sfx', 'arena/hud', 'arena/director'],
    entry: 'arena/main', css: ['arena/arena.css'], title: 'Печати Разлома — классика',
    body: '<div id="stage"></div>\n<div id="hud"></div>\n<noscript>Игре нужен JavaScript и WebGL.</noscript>',
  },
  table: {
    modules: [...CORE, 'web/text'], entry: 'web/app', css: ['web/style.css'], title: 'Печати Разлома — стол',
    body: '<main id="app"></main>\n<noscript>Прототипу нужен JavaScript.</noscript>',
  },
};
// Barrel files become merged objects of the modules they re-export.
const BARRELS = { 'core/index': { name: '__R', of: CORE }, 'duel/index': { name: '__D', of: DUEL } };

const idOf = file => relative(src, file).replace(/\\/g, '/').replace(/\.js$/, '');
const varOf = id => BARRELS[id]?.name ?? `__${id.replace(/[^\w]/g, '_')}`;
const external = new Set();

function declaredNames(line) {
  const body = line.replace(/^export (const|let) /, '');
  const simple = !body.includes('(') && !body.includes('=>') && body.trim().endsWith(';');
  if (!simple) return [body.match(/^(\w+)/)[1]];
  return body.split(',').map(x => x.trim().match(/^(\w+)\s*=/)?.[1]).filter(Boolean);
}

function transform(code, file, { wrap }) {
  const names = [];
  const ref = spec => varOf(idOf(resolve(dirname(file), spec)));
  const out = code
    .replace(/^import .+ from '([^.'][^']*)';$/gm, line => { external.add(line); return ''; })
    .replace(/^import \* as (\w+) from '(.+?)';$/gm, (_, ns, spec) => `const ${ns} = ${ref(spec)};`)
    .replace(/^import \{([^}]+)\} from '(.+?)';$/gm, (_, list, spec) => `const {${list.replace(/(\w+) as (\w+)/g, '$1: $2')}} = ${ref(spec)};`)
    .replace(/^export \{([^}]+)\};?$/gm, (_, list) => { names.push(...list.split(',').map(x => x.trim()).filter(Boolean)); return ''; })
    .replace(/^export (async )?function (\w+)/gm, (_, a, n) => { names.push(n); return `${a ?? ''}function ${n}`; })
    .replace(/^export class (\w+)/gm, (_, n) => { names.push(n); return `class ${n}`; })
    .replace(/^export (const|let) .*$/gm, line => { names.push(...declaredNames(line)); return line.replace(/^export /, ''); });
  if (/^\s*(import|export)\b/m.test(out)) throw new Error(`${file}: unsupported import/export form left`);
  if (!wrap) return out;
  return `const ${varOf(idOf(file))} = (() => {\n${out}\nreturn { ${[...new Set(names)].join(', ')} };\n})();`;
}

const which = TARGETS[process.argv[2]] ? process.argv[2] : 'duel';
const target = TARGETS[which];
const outArg = TARGETS[process.argv[2]] ? process.argv[3] : process.argv[2];

const parts = [];
const done = new Set();
for (const id of target.modules) {
  const file = join(src, `${id}.js`);
  parts.push(transform(await readFile(file, 'utf8'), file, { wrap: true }));
  done.add(id);
  for (const [barrel, { name, of }] of Object.entries(BARRELS)) {
    if (of.every(m => done.has(m)) && !done.has(barrel)) {
      parts.push(`const ${name} = Object.assign({}, ${of.map(varOf).join(', ')});`);
      done.add(barrel);
    }
  }
}
const entry = join(src, `${target.entry}.js`);
parts.push(transform(await readFile(entry, 'utf8'), entry, { wrap: false }));

const css = (await Promise.all(target.css.map(f => readFile(join(src, f), 'utf8')))).join('\n');
const importMap = external.size ? `<script type="importmap">
{ "imports": {
  "three": "https://cdn.jsdelivr.net/npm/three@${THREE_VERSION}/build/three.module.js",
  "three/addons/": "https://cdn.jsdelivr.net/npm/three@${THREE_VERSION}/examples/jsm/"
} }
</script>
` : '';
const code = [...external].join('\n') + '\n\n' + parts.join('\n\n');
const html = `<title>${target.title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?${FONTS}&display=swap">
<style>
${css}
</style>
${importMap}${target.body}
<script type="module">
${code.replace(/<\/script/gi, '<\\/script')}
</script>
`;
const out = resolve(outArg ?? join(root, `dist/rift-sigils-${which}.html`));
await writeFile(out, html);
console.log(`${which}: ${out} (${(html.length / 1024).toFixed(0)} КБ)`);
