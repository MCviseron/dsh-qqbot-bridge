/** Offline test of the one-click environment installer: no real python, no pip. */
import { mkdir, mkdtemp, readFile, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { Installer, STEPS, venvPython } from '../lib/install.js'

let failures = 0
function check(condition, label) {
  console.log((condition ? 'ok   ' : 'FAIL ') + label)
  if (!condition) failures += 1
}

async function exists(path) {
  try {
    await stat(path)
    return true
  } catch {
    return false
  }
}

/** Fake bot sources that look like the real tree, secrets included on purpose. */
const sourceDir = join(await mkdtemp(join(tmpdir(), 'qq-install-src-')), 'bot')
await mkdir(join(sourceDir, 'panels'), { recursive: true })
await mkdir(join(sourceDir, 'state'), { recursive: true })
await mkdir(join(sourceDir, 'logs'), { recursive: true })
await writeFile(join(sourceDir, 'main.py'), 'print("bot")\n', 'utf8')
await writeFile(join(sourceDir, 'panel.py'), 'print("panel")\n', 'utf8')
await writeFile(join(sourceDir, 'panels', 'p.txt'), 'panel asset\n', 'utf8')
await writeFile(join(sourceDir, 'config.json'), '{"appid":"dev-only"}\n', 'utf8')
await writeFile(join(sourceDir, '.env'), 'APPSECRET=dev-only\n', 'utf8')
await writeFile(join(sourceDir, '.env.example'), 'APPSECRET=\n', 'utf8')
await writeFile(join(sourceDir, 'state', 'metrics.json'), '{}', 'utf8')
await writeFile(join(sourceDir, 'logs', 'bot.log'), 'x', 'utf8')

const calls = []
/** Stand-in for runCommand: records argv, fakes version probes and venv creation. */
async function fakeRun(command, args, options = {}) {
  calls.push([command, ...args].join(' '))
  if (args.includes('-c') && args.some((arg) => arg.includes('sys.version_info'))) return '3.12\n'
  if (args.includes('venv')) {
    const venvDir = args[args.indexOf('venv') + 1]
    const python = venvPython(venvDir)
    await mkdir(dirname(python), { recursive: true })
    await writeFile(python, '', 'utf8')
    return ''
  }
  options.onText?.('pip output line\n')
  return ''
}

const dataDir = await mkdtemp(join(tmpdir(), 'qq-install-home-'))
let launched
const installer = new Installer({
  dataDir,
  sourceDir,
  run: fakeRun,
  log: () => {},
  launch: async (pythonPath, botDir) => {
    launched = { pythonPath, botDir }
    return 4242
  },
})

const status = installer.state()
check(status.steps.length === STEPS.length && status.running === false, 'initial state is idle with the step list')
check(status.installed === undefined, 'nothing installed before the first run')

installer.start({
  appid: '102000000',
  appsecret: 'secret-value',
  autoGroupRoot: 'D:/tmp/qq',
  bridgeUrl: 'http://127.0.0.1:39061',
  bridgeToken: 'tok-123',
})
check(installer.state().running === true || installer.state().done === true, 'start() kicks the job off')

for (let attempt = 0; attempt < 100 && !installer.state().done; attempt += 1) {
  await new Promise((resolve) => setTimeout(resolve, 50))
}

const done = installer.state()
check(done.done === true && done.succeeded === true, 'install finishes successfully')
check(done.error === '', 'no error recorded')
check(done.step === STEPS.length, 'all steps ran')

const botDir = join(dataDir, 'bot')
const venvPythonPath = venvPython(join(dataDir, 'venv'))
check(await exists(join(botDir, 'main.py')), 'bot sources copied')
check(await exists(join(botDir, 'panels', 'p.txt')), 'subdirectories copied')
const envAfterCopy = await readFile(join(botDir, '.env'), 'utf8')
check(!envAfterCopy.includes('dev-only'), "the developer's .env is NOT copied")
check((await exists(join(botDir, 'state'))) === false, 'state/ is NOT copied')
check((await exists(join(botDir, 'logs'))) === false, 'logs/ is NOT copied')
check((await exists(join(botDir, '.env.example'))) === true, '.env.example is copied')

const config = JSON.parse(await readFile(join(botDir, 'config.json'), 'utf8'))
check(config.appid === '102000000' && config.appsecret === 'secret-value', 'config.json carries the AppID / AppSecret')
check(config.auto_group_root === 'D:/tmp/qq', 'config.json carries the auto-group root')
check(config.appid !== 'dev-only', "the developer's config.json was not reused")

const env = await readFile(join(botDir, '.env'), 'utf8')
check(env.includes('APPID=102000000') && env.includes('APPSECRET=secret-value'), '.env carries the credentials load_config() needs')
check(env.includes('BRIDGE_URL=http://127.0.0.1:39061'), '.env points the bot at the plugin')
check(env.includes('BRIDGE_TOKEN='), '.env carries the bridge token line')

const record = JSON.parse(await readFile(join(dataDir, 'install.json'), 'utf8'))
check(record.botDir === botDir, 'install.json records the bot dir')
check(record.pythonPath === venvPythonPath, 'install.json records the venv interpreter')
check(record.pythonVersion === '3.12', 'install.json records the detected version')
check(launched !== undefined && launched.pythonPath === venvPythonPath, 'supervisor launched with the venv interpreter')
check(done.lines.some((line) => line.includes('依赖自检通过')), 'dependency self-check is reported')
check(calls.some((line) => line.includes('pip install')), 'pip install was actually invoked')

// Second run must reuse the venv instead of rebuilding it.
const reuse = new Installer({ dataDir, sourceDir, run: fakeRun, log: () => {}, launch: async () => 1 })
reuse.start({})
for (let attempt = 0; attempt < 100 && !reuse.state().done; attempt += 1) {
  await new Promise((resolve) => setTimeout(resolve, 50))
}
check(reuse.state().succeeded === true, 'second install succeeds')
check(reuse.state().lines.some((line) => line.includes('venv 已存在')), 'existing venv is reused')

// 设置面板回传的打码密钥（ab12****yz）不能写进 .env，否则机器人根本起不来
const maskedDir = await mkdtemp(join(tmpdir(), 'qq-install-masked-'))
const masked = new Installer({ dataDir: maskedDir, sourceDir, run: fakeRun, log: () => {}, launch: async () => 1 })
masked.start({ appid: '102000000', appsecret: 'ab12****yz' })
for (let attempt = 0; attempt < 100 && !masked.state().done; attempt += 1) {
  await new Promise((resolve) => setTimeout(resolve, 50))
}
const maskedEnv = await readFile(join(maskedDir, 'bot', '.env'), 'utf8')
check(!maskedEnv.includes('****'), 'masked AppSecret never reaches .env')
check(maskedEnv.includes('APPID=102000000'), 'the real AppID still lands in .env')
check(masked.state().lines.some((line) => line.includes('AppSecret 是打码值')), 'the panel explains the masked secret was skipped')

// 安装源轮换：配置源失败 -> 阿里云镜像成功，并且每次都有硬超时
const fallbackCalls = []
const fallback = new Installer({
  dataDir: await mkdtemp(join(tmpdir(), 'qq-install-mirror-')),
  sourceDir,
  log: () => {},
  run: async (command, args, options = {}) => {
    fallbackCalls.push({ args, timeoutMs: options.timeoutMs })
    if (args.includes('-c') && args.some((arg) => arg.includes('sys.version_info'))) return '3.12\n'
    if (args.includes('venv')) {
      const venvDir = args[args.indexOf('venv') + 1]
      await mkdir(dirname(venvPython(venvDir)), { recursive: true })
      await writeFile(venvPython(venvDir), '', 'utf8')
      return ''
    }
    if (args.includes('install') && !args.includes('-i')) throw new Error('network unreachable')
    return ''
  },
})
fallback.start({})
for (let attempt = 0; attempt < 100 && !fallback.state().done; attempt += 1) {
  await new Promise((resolve) => setTimeout(resolve, 50))
}
const fallbackLines = fallback.state().lines.join('\n')
check(fallback.state().succeeded === true, 'install survives a dead default index')
check(fallbackLines.includes('尝试安装源：pip 配置的源') && fallbackLines.includes('尝试安装源：阿里云镜像'), 'installer walks the source list')
check(fallbackLines.includes('依赖安装完成（阿里云镜像）'), 'successful mirror is reported')
const pipCall = fallbackCalls.find((call) => call.args.includes('install'))
check(pipCall !== undefined && pipCall.timeoutMs === 240000, 'each pip attempt has a hard timeout')
check(pipCall.args.includes('-u'), 'pip runs unbuffered so output streams to the panel')

// No usable Python -> clear, actionable failure.
const failing = new Installer({
  dataDir: await mkdtemp(join(tmpdir(), 'qq-install-bad-')),
  sourceDir,
  run: async () => {
    throw new Error('not found')
  },
  log: () => {},
})
failing.start({})
for (let attempt = 0; attempt < 100 && !failing.state().done; attempt += 1) {
  await new Promise((resolve) => setTimeout(resolve, 50))
}
check(failing.state().succeeded === false, 'missing python fails the install')
check(failing.state().error.includes('Python 3.10+'), 'failure message tells the user what to install')

console.log(failures === 0 ? 'ALL PASS' : failures + ' FAILED')
process.exit(failures === 0 ? 0 : 1)
