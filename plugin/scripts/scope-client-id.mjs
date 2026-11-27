/**
 * 发布前把浏览器半身注册的模块 id 改成和 npm 包名一致。
 * 宿主按包名去 import client.js，bundle 必须用同一个 id 调用
 * __ModuleLoader__.load，否则报 "loaded without registering …"。
 * 本地 link 开发保持裸名，所以这个改写只在 npm publish 前跑。
 */
import { readFile, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const pkg = JSON.parse(await readFile(join(pluginRoot, 'package.json'), 'utf8'))
const target = String(pkg.name ?? '').trim()
if (target === '') {
  console.error('[scope-client-id] package.json 里没有 name')
  process.exit(1)
}

const clientPath = join(pluginRoot, 'lib', 'client.js')
const source = await readFile(clientPath, 'utf8')
const pattern = /^ {2}id: "([^"]+)",$/m
const match = pattern.exec(source)
if (match === null) {
  console.error('[scope-client-id] client.js 里找不到 id 行')
  process.exit(1)
}
const current = match[1]
if (current === target) {
  console.log('[scope-client-id] id 已经是 ' + target + '，不用改')
  process.exit(0)
}
await writeFile(clientPath, source.replace(pattern, '  id: "' + target + '",'), 'utf8')
console.log('[scope-client-id] ' + current + ' → ' + target)
