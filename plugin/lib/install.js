/**
 * 一键把机器人运行环境装好：找系统 Python → 建 venv → 装依赖 → 复制随包代码 →
 * 写配置 → 拉起守护进程。只用 Node 标准库，Windows / macOS / Linux 通用。
 * 安装器不认识设置面板，只认参数与回调，方便离线测试。
 */
import { spawn } from 'node:child_process'
import { cp, mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import { join, relative, resolve, sep } from 'node:path'

export const STEPS = ['查找 Python', '创建 venv', '安装依赖', '复制机器人代码', '写入配置', '启动守护进程']

/** 复制代码时跳过的目录 / 文件：机器人的状态与凭据不进安装目录。 */
const SKIP_DIRS = new Set(['state', 'logs', '__pycache__', '.pytest_cache', '.git', '.idea', '.vscode'])
// .env 里是 AppID / AppSecret，绝不能随包或进安装目录
const SKIP_FILES = new Set(['config.json', '.env', 'state.json', 'groups.json', 'members.json', 'store.json'])

const REQUIREMENTS = ['aiohttp>=3.7,<4', 'Pillow>=10', 'viseron-qqbotpy>=0.4.4']
const MIRROR = 'https://pypi.tuna.tsinghua.edu.cn/simple'
const ALIYUN = 'https://mirrors.aliyun.com/pypi/simple'

/** 跑一条外部命令，把 stdout/stderr 合并返回；失败时把尾部输出带进错误。 */
export function runCommand(command, args, options = {}) {
  return new Promise((done, fail) => {
    let output = ''
    let settled = false
    const settle = (error, value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (error) fail(error)
      else done(value)
    }
    const child = spawn(command, args, { cwd: options.cwd, windowsHide: true, shell: false })
    const timer = setTimeout(() => {
      child.kill()
      settle(new Error(`${command} 超时（${options.timeoutMs ?? 120000}ms）`))
    }, options.timeoutMs ?? 120000)
    const collect = (chunk) => {
      const text = chunk.toString()
      output += text
      if (output.length > 12000) output = output.slice(-12000)
      options.onText?.(text)
    }
    child.stdout?.on('data', collect)
    child.stderr?.on('data', collect)
    child.once('error', (error) => settle(new Error(`${command} 启动失败：${error.message}`)))
    child.once('close', (code) => {
      if (code === 0) settle(undefined, output)
      else settle(new Error(`${command} ${args.join(' ')} 退出码 ${code}：${output.trim().slice(-600)}`))
    })
  })
}

/** venv 里的解释器路径。 */
export function venvPython(venvDir) {
  return process.platform === 'win32' ? join(venvDir, 'Scripts', 'python.exe') : join(venvDir, 'bin', 'python')
}

/** 已安装记录（install.json），没有就是 undefined。 */
export async function readInstall(dataDir) {
  try {
    const parsed = JSON.parse(await readFile(join(dataDir, 'install.json'), 'utf8'))
    if (parsed !== null && typeof parsed === 'object') return parsed
  } catch {
    // 没装过 / 文件坏了都按未安装处理
  }
  return undefined
}

async function exists(path) {
  try {
    await stat(path)
    return true
  } catch {
    return false
  }
}

export class Installer {
  #dataDir
  /** 随包机器人源码目录（可先留空，安装前再解析）。 */
  sourceDir
  #log
  #run
  #launch
  #busy = false
  #installed
  #state

  /**
   * @param {{dataDir: string, sourceDir: string, log?: (line: string) => void,
   *          run?: typeof runCommand, launch?: (pythonPath: string, botDir: string) => Promise<number|undefined>}} options
   */
  constructor({ dataDir, sourceDir, log = () => {}, run = runCommand, launch }) {
    this.#dataDir = dataDir
    this.sourceDir = sourceDir
    this.#log = log
    this.#run = run
    this.#launch = launch
    this.botDir = join(dataDir, 'bot')
    this.venvDir = join(dataDir, 'venv')
    this.pythonPath = venvPython(this.venvDir)
    // 注意：这里不能叫 ok —— HTTP 回执里的 ok 是"请求成功"，会被这个字段覆盖成 400
    this.#state = { running: false, done: false, succeeded: false, step: -1, steps: STEPS, lines: [], error: '', botDir: this.botDir, pythonPath: this.pythonPath }
  }

  /** 当前安装状态（含历史日志行，供面板轮询）。 */
  state() {
    return { ...this.#state, lines: [...this.#state.lines], installed: this.#installed }
  }

  /** 已完成安装时返回记录，供自动启动复用。 */
  async load() {
    this.#installed = await readInstall(this.#dataDir)
    return this.#installed
  }

  #say(line) {
    const text = String(line).trim()
    if (text === '') return
    this.#state.lines.push(text)
    if (this.#state.lines.length > 400) this.#state.lines.splice(0, this.#state.lines.length - 400)
    this.#log(text)
  }

  /** 后台开始安装；重复点击不会并行跑第二份。 */
  start(options = {}) {
    if (this.#busy) return { ok: true, alreadyRunning: true, state: this.state() }
    this.#busy = true
    this.#state = { ...this.#state, running: true, done: false, succeeded: false, step: 0, lines: [], error: '' }
    void this.#runAll(options)
    return { ok: true, started: true, state: this.state() }
  }

  async #runAll({ appid = '', appsecret = '', autoGroupRoot = '', bridgeUrl = '', bridgeToken = '' } = {}) {
    try {
      const python = await this.#step(0, () => this.#findPython())
      const venv = await this.#step(1, () => this.#ensureVenv(python))
      await this.#step(2, () => this.#installDeps(venv))
      await this.#step(3, () => this.#copySources())
      await this.#step(4, () => this.#writeConfig({ appid, appsecret, autoGroupRoot, bridgeUrl, bridgeToken }))
      const record = await this.#step(5, () => this.#record(python))
      this.#installed = record
      this.#state = { ...this.#state, running: false, done: true, succeeded: true, step: STEPS.length }
      this.#say('安装完成：机器人目录 ' + this.botDir)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.#state = { ...this.#state, running: false, done: true, succeeded: false, error: message }
      this.#say('安装失败：' + message)
    } finally {
      this.#busy = false
    }
  }

  async #step(index, work) {
    this.#state = { ...this.#state, step: index }
    this.#say('▶ ' + STEPS[index])
    return await work()
  }

  /** 找一个 3.10+ 的解释器（py 启动器优先，其次 PATH 里的 python）。 */
  async #findPython() {
    const candidates = process.platform === 'win32'
      ? [['py', '-3.12'], ['py', '-3.11'], ['py', '-3'], ['python'], ['python3']]
      : [['python3'], ['python']]
    const probe = 'import sys;print("%d.%d" % sys.version_info[:2])'
    for (const candidate of candidates) {
      const [command, ...args] = candidate
      const label = [command, ...args].join(' ')
      try {
        const output = await this.#run(command, [...args, '-c', probe], { timeoutMs: 20000 })
        const match = /^(\d+)\.(\d+)/m.exec(output.trim())
        if (match === null) continue
        const version = Number(match[1]) + Number(match[2]) / 100
        if (Number(match[1]) === 3 && Number(match[2]) >= 10) {
          this.#say(`用 ${label}（Python ${match[1]}.${match[2]}）`)
          return { command, args, label, max: String(match[1]) + '.' + String(match[2]) }
        }
        this.#say(`${label} 是 Python ${match[1]}.${match[2]}，需要 3.10+`)
      } catch (error) {
        this.#say(`${label} 不可用`)
      }
    }
    throw new Error('没找到 Python 3.10+。装个 Python 3.12（https://www.python.org/downloads/，勾选 Add to PATH）后再点一次。')
  }

  /** 建（或复用）venv；返回 venv 解释器路径。 */
  async #ensureVenv(python) {
    if (await exists(this.pythonPath)) {
      this.#say('venv 已存在，直接复用：' + this.venvDir)
      return this.pythonPath
    }
    await mkdir(this.#dataDir, { recursive: true })
    await this.#run(python.command, [...python.args, '-m', 'venv', this.venvDir], { timeoutMs: 180000, onText: (text) => this.#say(text) })
    if (!(await exists(this.pythonPath))) throw new Error('venv 建好了但找不到 ' + this.pythonPath)
    this.#say('venv 就绪：' + this.pythonPath)
    return this.pythonPath
  }

  /** pip 装 aiohttp / Pillow / viseron-qqbotpy：配置源 → 清华 → 阿里云，每个源都有硬超时。 */
  async #installDeps(pythonPath) {
    // 顺序有讲究：配置源最常见就是清华/阿里，所以第二、三个用彼此不同的镜像再兜一遍
    const sources = [
      { label: 'pip 配置的源', extra: [] },
      { label: '阿里云镜像', extra: ['-i', ALIYUN] },
      { label: '清华镜像', extra: ['-i', MIRROR] },
    ]
    for (const source of sources) {
      this.#say('尝试安装源：' + source.label)
      try {
        // -u 让 pip 的输出实时流到面板；每个源 4 分钟封顶，卡住就换下一个，不会无限等
        await this.#run(
          pythonPath,
          ['-u', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '--progress-bar', 'off',
            '--timeout', '20', '--retries', '1', ...source.extra, ...REQUIREMENTS],
          { timeoutMs: 240000, onText: (text) => this.#say(text) },
        )
        this.#say('依赖安装完成（' + source.label + '）')
        break
      } catch (error) {
        this.#say('这个源没装上：' + (error instanceof Error ? error.message.split('\n')[0] : String(error)))
        if (source === sources[sources.length - 1]) throw new Error('三个安装源都没成功，检查网络后重试（或手动在 venv 里 pip install）')
      }
    }
    // 机器人自己 import 的是 viseron_qqbotpy（PyPI 包名 viseron-qqbotpy），不是 botpy
    await this.#run(pythonPath, ['-c', 'import aiohttp, PIL, viseron_qqbotpy; print("deps ok")'], { timeoutMs: 30000 })
      .then(() => this.#say('依赖自检通过（aiohttp / Pillow / viseron_qqbotpy）'))
      .catch(() => this.#say('依赖自检没通过，机器人启动时可能报错'))
  }

  /** 把随包的 bot/ 复制到安装目录（跳过状态与凭据）。 */
  async #copySources() {
    if (!(await exists(this.sourceDir))) throw new Error('找不到随包的机器人代码：' + this.sourceDir)
    await mkdir(this.botDir, { recursive: true })
    let copied = 0
    await cp(this.sourceDir, this.botDir, {
      recursive: true,
      force: true,
      filter: (source) => {
        const parts = relative(this.sourceDir, source).split(sep)
        if (parts[0] === '') return true
        if (parts.some((part) => SKIP_DIRS.has(part))) return false
        if (SKIP_FILES.has(parts[parts.length - 1])) return false
        copied += 1
        return true
      },
    })
    this.#say(`已复制 ${copied} 项到 ${this.botDir}`)
  }

  /** 写 bot/config.json 与 bot/.env：面板可改的进 json，启动时读的进 .env。 */
  async #writeConfig({ appid, appsecret, autoGroupRoot, bridgeUrl, bridgeToken }) {
    // 面板回传的密钥是打码值（ab12****yz），写进去等于没有，必须跳过
    const clean = (value) => {
      const text = typeof value === 'string' ? value.trim() : ''
      return text.includes('****') ? '' : text
    }
    const realAppid = clean(appid)
    const realSecret = clean(appsecret)
    if ((typeof appid === 'string' && appid.trim() !== '') && realAppid === '') this.#say('AppID 是打码值，跳过写入')
    if ((typeof appsecret === 'string' && appsecret.trim() !== '') && realSecret === '') this.#say('AppSecret 是打码值，跳过写入（请在设置里填真实值）')

    const configPath = join(this.botDir, 'config.json')
    let current = {}
    try {
      const parsed = JSON.parse(await readFile(configPath, 'utf8'))
      if (parsed !== null && typeof parsed === 'object') current = parsed
    } catch {
      current = {}
    }
    if (realAppid !== '') current.appid = realAppid
    if (realSecret !== '') current.appsecret = realSecret
    if (typeof autoGroupRoot === 'string' && autoGroupRoot.trim() !== '') current.auto_group_root = autoGroupRoot.trim()
    await writeFile(configPath, JSON.stringify(current, null, 2), 'utf8')
    this.#say('配置已写入 ' + configPath)

    // load_config() 只看 .env，config.json 是后来的覆盖；缺 .env 会直接 "APPID / APPSECRET missing"
    const envPath = join(this.botDir, '.env')
    const existing = {}
    try {
      for (const line of (await readFile(envPath, 'utf8')).split('\n')) {
        const match = /^([A-Z_]+)=(.*)$/.exec(line.trim())
        if (match !== null) existing[match[1]] = match[2]
      }
    } catch {
      // 第一次安装没有 .env，按空处理
    }
    const env = { ...existing }
    if (realAppid !== '') env.APPID = realAppid
    if (realSecret !== '') env.APPSECRET = realSecret
    if (typeof bridgeUrl === 'string' && bridgeUrl.trim() !== '') env.BRIDGE_URL = bridgeUrl.trim()
    if (typeof bridgeToken === 'string' && bridgeToken.trim() !== '') env.BRIDGE_TOKEN = bridgeToken.trim()
    env.QQ_SANDBOX = env.QQ_SANDBOX ?? '0'
    const body = Object.entries(env).map(([key, value]) => key + '=' + value).join('\n') + '\n'
    await writeFile(envPath, body, 'utf8')
    this.#say('凭据已写入 ' + envPath + (realSecret === '' ? '（AppSecret 待填）' : ''))
  }

  /** 拉起守护进程并落 install.json。 */
  async #record(python) {
    const record = {
      botDir: this.botDir,
      pythonPath: this.pythonPath,
      basePython: python.label,
      pythonVersion: python.max,
      installedAt: new Date().toISOString(),
    }
    await writeFile(join(this.#dataDir, 'install.json'), JSON.stringify(record, null, 2), 'utf8')
    if (typeof this.#launch === 'function') {
      const pid = await this.#launch(this.pythonPath, this.botDir)
      this.#say(pid === undefined ? '守护进程已申请启动' : `守护进程已启动（pid ${pid}）`)
    }
    return record
  }
}

/** 随包源码在哪：发布包里是 <plugin>/bot，开发仓库里是 <repo>/bot。 */
export async function resolveSourceDir(pluginRoot) {
  const packaged = resolve(pluginRoot, 'bot')
  if (await exists(join(packaged, 'main.py'))) return packaged
  const dev = resolve(pluginRoot, '..', 'bot')
  if (await exists(join(dev, 'main.py'))) return dev
  return packaged
}
