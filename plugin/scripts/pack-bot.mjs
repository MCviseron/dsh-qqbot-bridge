/**
 * prepack 钩子：把仓库里的 bot/ 暂存成 plugin/bot，随 npm 包一起发出去。
 * 状态目录与凭据不打包（安装器会在目标机上生成），git 里也不跟踪。
 */
import { access, cp, rm } from 'node:fs/promises'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const SKIP_DIRS = new Set(['state', 'logs', '__pycache__', '.pytest_cache', '.git'])
// .env 里是 AppID / AppSecret，绝不能随包或进安装目录
// store.json 是面板 ID 的本机状态，随包发出去对面也认不得
const SKIP_FILES = new Set(['config.json', '.env', 'state.json', 'groups.json', 'members.json', 'store.json'])

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = resolve(pluginRoot, '..', 'bot')
const target = join(pluginRoot, 'bot')

try {
  await access(join(source, 'main.py'))
} catch {
  console.error('[prepack] 找不到机器人源码：' + source)
  process.exit(1)
}

await rm(target, { recursive: true, force: true })
let copied = 0
await cp(source, target, {
  recursive: true,
  force: true,
  filter: (path) => {
    const parts = relative(source, path).split(sep)
    if (parts[0] === '') return true
    if (parts.some((part) => SKIP_DIRS.has(part))) return false
    if (SKIP_FILES.has(parts[parts.length - 1])) return false
    copied += 1
    return true
  },
})
console.log('[prepack] 已暂存 ' + target + '（' + copied + ' 项）')
