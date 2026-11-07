/**
 * i18n consistency check.
 *
 * Verifies that every static `t('...')` key used in src/ exists in BOTH locale
 * dictionaries, and that the en/zh key sets are identical.
 *
 * Run from anywhere:  node frontend/scripts/i18n-check.mjs
 * Or via pnpm:        pnpm check:i18n
 */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
// esbuild is a transitive dependency of Vite. Under pnpm it is not hoisted to
// the top level, so resolve it from Vite's own location instead.
const nodeRequire = createRequire(path.join(ROOT, 'package.json'))
const viteEntry = nodeRequire.resolve('vite', { paths: [ROOT] })
const esbuild = createRequire(viteEntry)('esbuild')
const OUT = path.join(os.tmpdir(), 'ailp-locales-check.mjs')

await esbuild.build({
  entryPoints: [path.join(ROOT, 'src/i18n/locales.ts')],
  outfile: OUT,
  format: 'esm',
  platform: 'node',
  bundle: true,
})
const { messages } = await import(pathToFileURL(OUT).href + '?t=' + Date.now())

function leaves(obj, prefix = '', acc = []) {
  for (const [k, v] of Object.entries(obj || {})) {
    const p = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object') leaves(v, p, acc)
    else acc.push(p)
  }
  return acc
}

const en = new Set(leaves(messages.en))
const zh = new Set(leaves(messages.zh))
const used = new Map()

function walk(dir) {
  for (const f of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, f.name)
    if (f.isDirectory()) walk(p)
    else if (/\.(ts|tsx)$/.test(f.name)) {
      const source = fs.readFileSync(p, 'utf8')
      for (const m of source.matchAll(/\bt\(\s*['"]([^'"]+)['"]/g)) {
        const key = m[1]
        if (!used.has(key)) used.set(key, [])
        used.get(key).push(path.relative(ROOT, p))
      }
    }
  }
}
walk(path.join(ROOT, 'src'))

const missingEn = [...used.keys()].filter((k) => !en.has(k) && !k.includes('${'))
const missingZh = [...en].filter((k) => !zh.has(k))
const extraZh = [...zh].filter((k) => !en.has(k))

console.log(`en leaves: ${en.size} | zh leaves: ${zh.size} | used static keys: ${used.size}`)
console.log(`\nMISSING EN (${missingEn.length}):`)
missingEn.forEach((k) => console.log(' ', k, '<-', used.get(k).join(', ')))
console.log(`\nMISSING ZH (${missingZh.length}):`)
missingZh.forEach((k) => console.log(' ', k))
console.log(`\nEXTRA ZH (${extraZh.length}):`)
extraZh.forEach((k) => console.log(' ', k))

if (missingEn.length || missingZh.length || extraZh.length) process.exitCode = 1
