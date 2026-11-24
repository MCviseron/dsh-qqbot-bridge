/**
 * dsh-qq-bridge — Host half.
 *
 * One QQ conversation (a group or a private chat) owns one DSH Session. This
 * plugin keeps that mapping, turns every inbound QQ message into a Session
 * prompt, captures the assistant text of each finished turn, keeps a rolling
 * transcript of group chatter, and asks the bot owner before a tool needs
 * approval.
 */
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { appendFile, mkdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { HttpBridge } from './server.js'
import { ConversationStore } from './store.js'

export const name = 'dsh-qq-bridge'

/** Fields a profile patch may override; everything else is fixed policy. */
export const DEFAULT_CONFIG = {
  enabled: true,
  host: '127.0.0.1',
  port: 39061,
  panelPort: 39062,
  token: '',
  cwd: '',
  statePath: '',
  approvalTimeoutMs: 150000,
  approvalDefault: 'reject',
  contextLines: 30,
  argumentPreviewChars: 600,
  quoteContextChars: 300,
  historyMax: 200,
  autoGroup: true,
  autoGroupRoot: 'D:\\dsh-qqbot-temp',
  streamEnabled: true,
  streamIntervalMs: 250,
  autoStartBot: true,
  botDir: 'D:/Program/QQ-Bot-Class/dsh-bot/bot',
  pythonPath: 'C:/Users/25639/.conda/envs/ChatClone-BotPy/python.exe',
  modelProvider: '',
  model: '',
  reasoningEffort: '',
}

const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])

/** Profile config → absolute, defaulted runtime configuration. */
function resolveConfig(raw) {
  const config = { ...DEFAULT_CONFIG, ...(raw ?? {}) }
  const home = typeof process.env.DSH_HOME === 'string' && process.env.DSH_HOME !== ''
    ? process.env.DSH_HOME
    : join(process.cwd(), '.dsh')
  const dataDir = join(home, 'qq-bridge')
  return {
    ...config,
    port: Number(config.port ?? DEFAULT_CONFIG.port),
    approvalTimeoutMs: Number(config.approvalTimeoutMs ?? DEFAULT_CONFIG.approvalTimeoutMs),
    contextLines: Number(config.contextLines ?? DEFAULT_CONFIG.contextLines),
    dataDir,
    cwd: resolve(config.cwd !== '' ? config.cwd : join(dataDir, 'workspace')),
    statePath: config.statePath !== '' ? resolve(config.statePath) : join(dataDir, 'state.json'),
  }
}

/** Text parts of one assistant message, ignoring reasoning and tool calls. */
function textOf(message) {
  const content = message?.content
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  const parts = []
  for (const part of content) {
    if (part === null || typeof part !== 'object') continue
    if (part.type === 'text' && typeof part.text === 'string') parts.push(part.text)
  }
  return parts.join('')
}

/** One-line, length-bounded preview of a text or JSON blob. */
function preview(value, limit) {
  const text = typeof value === 'string' ? value : JSON.stringify(value ?? '')
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat
}

export function apply(ctx, rawConfig) {
  const config = resolveConfig(rawConfig)
  const logPath = join(dirname(config.statePath), 'bridge.log')

  const log = (message) => {
    console.log(`[dsh-qq-bridge] ${message}`)
    void appendFile(logPath, `${new Date().toISOString()} ${message}\n`, 'utf8').catch(() => {})
  }

  if (config.enabled === false) {
    log('disabled by config')
    return
  }

  const store = new ConversationStore(config.statePath)
  const bridge = new HttpBridge({ host: config.host, port: config.port, token: config.token, log })
  /** @type {{ sessionController?: any }} */
  const host = {}
  /** Live per-session turn capture: sessionId → { texts, tools }. */
  const turns = new Map()
  /** Recent group chatter per conversation, so a mention carries context. */
  const contexts = new Map()
  /** Truncated tool arguments per "sessionId:callId", shown in approvals. */
  const callArguments = new Map()
  /** Pending approval questions: approvalId → finish(outcome). */
  const approvals = new Map()
  /** Sessions this process already applied the model selection to. */
  const selected = new Set()
  /** Last time the bot long-polled us; approvals go to QQ only while this is fresh. */
  let lastPullAt = 0

  const ready = Promise.all([store.load(), mkdir(config.cwd, { recursive: true }), mkdir(dirname(logPath), { recursive: true })]).catch(error => {
    log(`state init failed: ${error instanceof Error ? error.message : String(error)}`)
  })

  const stripHints = (line) => {
    // the bot appends a sticker hint to the prompt; keep it out of the transcript
    const at = line.indexOf('（想发个表情包时')
    return at === -1 ? line : line.slice(0, at).trimEnd()
  }

  // Longer per-conversation history (with timestamps) the model can search.
  const history = new Map()
  const stamp = () => {
    const now = new Date()
    return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  }
  const pushHistory = (convKey, line) => {
    const list = history.get(convKey) ?? []
    list.push(`[${stamp()}] ${stripHints(line)}`)
    const cap = Number.isFinite(config.historyMax) ? config.historyMax : 200
    if (list.length > cap) list.splice(0, list.length - cap)
    history.set(convKey, list)
  }

  // One workspace per QQ conversation when auto-grouping is on; falls back to cwd.
  const workspaceFor = async (convKey, overrides) => {
    const enabled = overrides?.autoGroup === undefined ? config.autoGroup === true : overrides.autoGroup === true
    if (!enabled) return config.cwd
    const root = String(overrides?.autoGroupRoot || config.autoGroupRoot || 'D:\\dsh-qqbot-temp')
    const name = convKey.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'qq'
    const dir = join(root, name)
    try {
      await mkdir(dir, { recursive: true })
      return dir
    } catch (error) {
      log(`workspace mkdir failed (${dir}): ${error instanceof Error ? error.message : String(error)}`)
      return config.cwd
    }
  }

  // 会话搬家：优先调用 dsh-edit-file-workspace 的 /move 路由（保留上下文），
  // 失败才退化成"新建会话"（丢上下文）。该路由要求请求来自回环，我们的桥就在本机。
  const moveSessionTo = async (sessionId, targetPath) => {
    let webServer
    try {
      webServer = typeof ctx.get === 'function' ? ctx.get('webServer') : undefined
    } catch (error) {
      webServer = undefined
    }
    const port = webServer && typeof webServer.port === 'number' ? webServer.port : 0
    if (port === 0) return { ok: false, reason: 'webServer 不可用' }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/dsh-edit-file-workspace/move`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ sessionId, path: targetPath }),
      })
      const payload = await response.json().catch(() => ({}))
      if (response.ok) return { ok: true, sandbox: payload?.sandbox }
      return { ok: false, reason: payload?.error || ('HTTP ' + response.status) }
    } catch (error) {
      return { ok: false, reason: error instanceof Error ? error.message : String(error) }
    }
  }
  // 提问通道：pending 表 + QQ 卡片投递（单题单选；多题/多选下一步）
  const questionPending = new Map()
  const sessionToConv = new Map()
  const askOnQq = async (convKey, id, question, options) => {
    const port = Number(config.panelPort) || 39062
    const response = await fetch(`http://127.0.0.1:${port}/api/question`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ convKey, id, question, options }),
    })
    if (!response.ok) throw new Error(`bot question endpoint HTTP ${response.status}`)
  }

  const installQuestionChannel = () => {
    if (typeof ctx.on !== 'function') return () => {}
    const sessionToConv = new Map()
    const refreshMap = async () => {
      try {
        const listed = await bridge.listConversations?.()
        if (Array.isArray(listed?.conversations)) {
          for (const item of listed.conversations) {
            const convKey = String(item.convKey ?? item.key ?? "")
            const sessionId = store.sessionOf(convKey)
            if (sessionId !== undefined) sessionToConv.set(String(sessionId), convKey)
          }
        }
      } catch (error) { /* map stays as-is */ }
    }
    void refreshMap()
    // 官方契约：waterfall answerer 要 { global: true, prepend: true }，
    // 回调返回 Promise<UserQuestionResult>；不是 QQ 会话就 return next()。
    return ctx.on('user-questions/request', (request, next) => {
      const agentId = String(request?.agent?.id ?? "")
      // store.convOf 是持久化的反查（sessionId → convKey），插件重启也不会丢
      const convKey = sessionToConv.get(agentId) ?? store.convOf(agentId)
      log(`question request: agent=${agentId} conv=${convKey ?? '-'}`)
      const questions = Array.isArray(request?.questions) ? request.questions : []
      const first = questions[0]
      const options = Array.isArray(first?.options) ? first.options : []
      if (convKey === undefined || first === undefined || options.length === 0) return next()
      const id = randomUUID()
      const labels = options.map((item) => String(item.label ?? item))
      return new Promise((resolve, reject) => {
        // 超时兜底：QQ 那边一直没人点也不能把 ask_user_question 挂死
        const timeoutMs = Number(config.approvalTimeoutMs) || 150000
        const deadline = setTimeout(() => {
          if (!questionPending.has(id)) return
          questionPending.delete(id)
          const error = new Error("ask_user_question timed out waiting for a QQ answer")
          error.code = "ASK_ABORTED"
          reject(error)
        }, timeoutMs)
        questionPending.set(id, {
          deadline,
          resolve: (answer) => {
            const index = Number(answer?.index)
            const picked = labels[index]
            questionPending.delete(id)
            resolve({ answers: [{ questionIndex: 0, selected: picked === undefined ? [] : [picked] }] })
          },
        })
        const signal = request?.signal
        if (signal !== undefined && typeof signal.addEventListener === "function") {
          signal.addEventListener("abort", () => {
            questionPending.delete(id)
            const error = new Error("ask_user_question was aborted before the user answered")
            error.code = "ASK_ABORTED"
            reject(error)
          })
        }
        void askOnQq(convKey, id, String(first.question ?? ""), labels).catch((error) => {
          questionPending.delete(id)
          reject(error instanceof Error ? error : new Error(String(error)))
        })
      })
    }, { global: true, prepend: true })
  }
  // 提示词形状的文本（机器人自己拼的判断/闲聊提示）不许进历史，否则会被当成群友发言回灌给模型
  const looksLikePrompt = (value) => {
    const text = String(value ?? '')
    return text.includes('【闲聊模式】') || text.includes('【群聊插话判断】')
  }

  const remember = (convKey, line) => {
    if (looksLikePrompt(line)) return
    const list = contexts.get(convKey) ?? []
    const stamped = `[${stamp()}] ${stripHints(line)}`
    list.push(stamped)
    if (list.length > config.contextLines) list.splice(0, list.length - config.contextLines)
    contexts.set(convKey, list)
    pushHistory(convKey, line)
  }

  /** Model-facing preamble: where the message came from and who is speaking. */
  const composePrompt = ({ text, convKey, senderName, isOwner, chime, quote }) => {
    const isGroup = convKey.startsWith('group:')
    const header = isGroup ? 'QQ 群聊' : 'QQ 单聊'
    const who = isOwner
      ? `${senderName || '主人'}（机器人主人本人：可以远程办公，直接读写工作目录、执行命令、查资料，做完再回答）`
      : `${senderName || '群友'}（普通群友：自然聊天为主；要改文件或跑命令时先说明理由，主人批准后才继续）`
    const recent = contexts.get(convKey) ?? []
    const parts = [`[${header}] ${who}：`]
    if (quote !== undefined) {
      // Structured by the bot: text / image / file / other, plus the author when known.
      const who = quote.author || '一条更早的消息'
      const kind = typeof quote.kind === 'string' ? quote.kind : 'text'
      if (quote.resolved === true && kind === 'image') {
        parts.push(`【引用了${who}发的一张图片】`, '')
      } else if (quote.resolved === true && kind === 'file') {
        parts.push(`【引用了${who}发的文件：${String(quote.text ?? '') || '（未命名）'}】`, '')
      } else if (quote.resolved === true && kind === 'other') {
        parts.push(`【引用了${who}发的一条非文本消息】`, '')
      } else if (quote.resolved === true) {
        const limit = Number.isFinite(config.quoteContextChars) ? config.quoteContextChars : 300
        const full = String(quote.text ?? '')
        const cut = full.length > limit
        const quoted = cut ? `${full.slice(0, limit)}…` : full
        parts.push(`【引用了${who}的消息】`, `“${quoted || '（空）'}”`, '')
      } else {
        const hint = quote.author ? `（可能来自${quote.author}）` : ''
        parts.push(`【对方引用了一条我这边看不到内容的消息${hint}】`, '')
      }
    }
    parts.push(text)
    if (isGroup && recent.length > 0) {
      parts.push('', '最近的群聊记录（只作上下文，不必逐条回应）：', ...recent)
    }
    if (chime) {
      parts.push('', '这条不是点名问你，是你自己决定要不要插话：觉得没必要就只回 [NO_REPLY]。')
    }
    parts.push('', isGroup && !isOwner
      ? '（这是群聊：像真人一样回 1~3 句口语，别用标题/列表/表格，除非对方明确要步骤。想清楚再说完，不要复述工具过程。）'
      : '（先直接回答，别铺垫；默认简短，需要细节时再用 Markdown 展开。）')
    parts.push('', '（QQ 侧支持 Markdown 渲染：标题/列表/代码块/表格都能用，表情符号可以直接用。要把本地图片或文件发给对方，先把文件写到工作目录里，再在回复里单独一行写 [[send_file: 绝对路径]]，机器人会把它作为文件发出。）')
    return parts.join('\n')
  }

  /** Ask the bot owner, then translate the answer into an approval outcome. */
  const requestDecision = ({ approvalId, convKey, approvalTarget, toolName, reason, argumentPreview, signal }) => new Promise((resolveDecision) => {
    const settle = (outcome) => {
      clearTimeout(timer)
      signal?.removeEventListener?.('abort', onAbort)
      approvals.delete(approvalId)
      resolveDecision(outcome)
    }
    const finish = (outcome) => {
      if (!approvals.has(approvalId)) return
      settle(outcome)
    }
    const timer = setTimeout(() => {
      if (!approvals.has(approvalId)) return
      bridge.push({ type: 'notice', convKey, target: approvalTarget, text: `审批超时（${toolName}），已按拒绝处理。` })
      log(`approval timeout: ${toolName}`)
      settle('rejected')
    }, config.approvalTimeoutMs)
    const onAbort = () => finish('cancelled')
    approvals.set(approvalId, finish)
    signal?.addEventListener?.('abort', onAbort, { once: true })
    bridge.push({
      type: 'approval',
      convKey,
      target: approvalTarget,
      approvalId,
      toolName,
      reason,
      argumentPreview,
      expiresAt: Date.now() + config.approvalTimeoutMs,
    })
    log(`approval asked: ${toolName} (${convKey})`)
  })

  /** Ask the Host for its Session list, tolerating builds without a list API. */
  const listSessions = async () => {
    const controller = host.sessionController
    if (controller === undefined) return { source: 'none', sessions: [] }
    for (const method of ['list', 'listSessions', 'listAll', 'all', 'sessions', 'query']) {
      const fn = controller[method]
      if (typeof fn !== 'function') continue
      try {
        const value = await fn.call(controller, {})
        const rows = Array.isArray(value) ? value : (Array.isArray(value?.sessions) ? value.sessions : [])
        return {
          source: method,
          sessions: rows
            .map(row => ({
              id: String(row?.sessionId ?? row?.id ?? ''),
              title: String(row?.title ?? row?.name ?? ''),
              cwd: String(row?.cwd ?? ''),
            }))
            .filter(row => row.id !== ''),
        }
      } catch (error) {
        return { source: method, sessions: [], error: error instanceof Error ? error.message : String(error) }
      }
    }
    return { source: 'unavailable', sessions: [] }
  }

  const markPull = () => { lastPullAt = Date.now() }
  const botIsListening = () => lastPullAt !== 0 && Date.now() - lastPullAt < 45000
  bridge.setOnPull(markPull)

  bridge.setHandlers({
    health: () => ({
      ok: true,
      plugin: 'dsh-qq-bridge',
      service: host.sessionController === undefined ? 'waiting' : 'ready',
      conversations: store.size(),
      pendingApprovals: approvals.size,
    }),
    status: () => ({
      ok: true,
      cwd: config.cwd,
      statePath: config.statePath,
      service: host.sessionController === undefined ? 'waiting' : 'ready',
      conversations: store.entries(),
      bufferedContexts: [...contexts.entries()].map(([key, lines]) => [key, lines.length]),
      pendingApprovals: [...approvals.keys()],
      cursor: bridge.cursor,
    }),
    reset: async (body) => {
      const convKey = typeof body?.convKey === 'string' ? body.convKey : ''
      if (convKey === '') return { ok: false, error: 'convKey required' }
      await store.unbind(convKey)
      contexts.delete(convKey)
      log(`conversation reset: ${convKey}`)
      return { ok: true, convKey }
    },
    /** Move one QQ conversation onto another existing Session ('' = go back). */
    switch: async (body) => {
      await ready
      const convKey = typeof body?.convKey === 'string' ? body.convKey.trim() : ''
      const sessionId = typeof body?.sessionId === 'string' ? body.sessionId.trim() : ''
      if (convKey === '') return { ok: false, error: 'convKey required' }
      if (sessionId === '') {
        const restored = await store.switchBack(convKey)
        if (restored === undefined) return { ok: false, error: '没有可切回的会话' }
        contexts.delete(convKey)
        log(`switched back: ${convKey} → ${restored}`)
        return { ok: true, convKey, sessionId: restored }
      }
      const previous = store.sessionOf(convKey)
      await store.switchTo(convKey, sessionId)
      contexts.delete(convKey)
      log(`switched: ${convKey} → ${sessionId} (was ${previous ?? 'none'})`)
      return { ok: true, convKey, sessionId, previous: previous ?? '' }
    },
    sessions: async () => {
      await ready
      return { ok: true, bound: store.entries(), returns: store.returnEntries(), host: await listSessions() }
    },
    inbound: async (body) => {
      await ready
      const convKey = typeof body?.convKey === 'string' ? body.convKey.trim() : ''
      const text = typeof body?.text === 'string' ? body.text : ''
      const images = Array.isArray(body?.images) ? body.images : []
      if (convKey === '') return { ok: false, error: 'convKey required' }
      if (text.trim() === '' && images.length === 0) return { ok: false, error: 'text or images required' }

      const senderName = typeof body?.senderName === 'string' ? body.senderName : ''
      // quoted message resolved by the bot (see bot/main.py _resolve_quote)
      const quote = body?.quote !== null && typeof body?.quote === 'object' ? body.quote : undefined
      const quoteMark = quote !== undefined && quote.resolved === true
        ? ` ↩[${quote.author || '引用'}]`
        : ''
      const label = (text.trim() === '' ? '[图片]' : preview(text, 200)) + quoteMark

      // Background group chatter: keep it as context, never start a turn for it.
      if (body?.contextOnly === true) {
        if (!looksLikePrompt(text)) remember(convKey, `${senderName || '群友'}: ${label}`)
        return { ok: true, buffered: true }
      }

      const sessionController = host.sessionController
      if (sessionController === undefined) return { ok: false, error: 'sessionController unavailable' }

      let sessionId = store.sessionOf(convKey)
      if (sessionId === undefined) {
        const created = await sessionController.create({ cwd: await workspaceFor(convKey, { autoGroup: body?.autoGroup, autoGroupRoot: body?.autoGroupRoot }) })
        sessionId = String(created.sessionId)
        log(`session created: ${convKey} → ${sessionId}`)
      }
      await store.bind(convKey, sessionId, typeof body?.approvalTarget === 'string' ? body.approvalTarget : undefined)
        sessionToConv.set(String(sessionId), convKey)

      // Casual chat is latency-bound: pin the session to the configured model /
      // reasoning effort once, without losing the Session's history.
      if (!selected.has(sessionId) && config.modelProvider !== '' && config.model !== '') {
        try {
          await sessionController.selectModel({
            sessionId,
            provider: config.modelProvider,
            model: config.model,
            ...(config.reasoningEffort !== '' ? { reasoningEffort: config.reasoningEffort } : {}),
          })
          log(`model pinned for ${sessionId}: ${config.modelProvider}/${config.model} effort=${config.reasoningEffort || 'default'}`)
        } catch (error) {
          log(`selectModel failed for ${sessionId}: ${error instanceof Error ? error.message : String(error)}`)
        }
        selected.add(sessionId)
      }

      const content = [{ type: 'text', text: composePrompt({ text, convKey, senderName, isOwner: body?.isOwner === true, chime: body?.chime === true, quote }) }]
      for (const image of images.slice(0, 4)) {
        const mediaType = typeof image?.mediaType === 'string' ? image.mediaType : ''
        const data = typeof image?.data === 'string' ? image.data : ''
        if (!IMAGE_TYPES.has(mediaType) || data === '') continue
        content.push({ type: 'image', mediaType, data })
      }

      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), 120000)
      try {
        await sessionController.prompt({
          requestId: randomUUID(),
          sessionId,
          mode: 'queue',
          content,
          clientTimeZone: 'Asia/Shanghai',
        }, controller.signal)
      } finally {
        clearTimeout(timer)
      }
      if (!looksLikePrompt(text)) remember(convKey, `${senderName || '群友'}: ${label}`)
      return { ok: true, sessionId, accepted: true }
    },
    rebind: async (body) => {
      await ready
      const convKey = typeof body?.convKey === 'string' ? body.convKey.trim() : ''
      if (convKey === '') return { ok: false, error: 'convKey required' }
      const sessionController = host.sessionController
      if (sessionController === undefined) return { ok: false, error: 'sessionController unavailable' }
      const dir = await workspaceFor(convKey, { autoGroup: body?.autoGroup, autoGroupRoot: body?.autoGroupRoot })
      const existing = store.sessionOf(convKey)
      let fallbackReason = ""
      if (existing !== undefined) {
        const moved = await moveSessionTo(existing, dir)
        if (moved.ok) return { ok: true, sessionId: existing, cwd: dir, moved: true, sandbox: moved.sandbox }
        fallbackReason = String(moved.reason || 'move failed')
        log(`session move failed (${convKey}): ${fallbackReason}; falling back to a new session`)
      }
      try {
        const created = await sessionController.create({ cwd: dir })
        const sessionId = String(created.sessionId)
        await store.bind(convKey, sessionId, typeof body?.approvalTarget === 'string' ? body.approvalTarget : undefined)
        sessionToConv.set(String(sessionId), convKey)
        return { ok: true, sessionId, cwd: dir, moved: false, fallbackReason, previous: body?.previous || null }
      } catch (error) {
        return { ok: false, error: 'create failed: ' + (error instanceof Error ? error.message : String(error)) }
      }
    },

    answer: async (body) => {
      await ready
      const id = typeof body?.id === 'string' ? body.id : ''
      if (id === '') return { ok: false, error: 'id required' }
      const pending = questionPending.get(id)
      if (pending?.deadline) clearTimeout(pending.deadline)
      if (pending === undefined) return { ok: false, error: 'this question is no longer pending' }
      questionPending.delete(id)
      try { pending.resolve(body) } catch (error) { /* already settled */ }
      return { ok: true }
    },
    commands: async (body) => {
      await ready
      const convKey = typeof body?.convKey === 'string' ? body.convKey.trim() : ''
      const ctxOf = (name) => { try { return typeof ctx.get === 'function' ? ctx.get(name) : undefined } catch (error) { return undefined } }
      const agents = ctxOf('agents')
      const runtime = ctxOf('commands')
      if (agents === undefined || runtime === undefined) return { ok: false, error: 'agents/commands 服务不可用' }
      const sessionId = store.sessionOf(convKey)
      if (sessionId === undefined) return { ok: false, error: '这个会话还没有 DSH 会话' }
      const agent = typeof agents.get === 'function' ? agents.get(sessionId) : undefined
      if (agent === undefined) return { ok: false, error: '会话未加载（先聊一句）' }
      let list = []
      try {
        list = runtime.list(agent).map((item) => ({
          name: item.name,
          description: item.description || item.summary || '',
          source: item.source || '',
        }))
      } catch (error) {
        return { ok: false, error: 'list failed: ' + (error instanceof Error ? error.message : String(error)) }
      }
      return { ok: true, count: list.length, commands: list }
    },

    command: async (body) => {
      await ready
      const convKey = typeof body?.convKey === 'string' ? body.convKey.trim() : ''
      const line = typeof body?.line === 'string' ? body.line.trim() : ''
      if (line === '') return { ok: false, error: 'line required' }
      const ctxOf = (name) => { try { return typeof ctx.get === 'function' ? ctx.get(name) : undefined } catch (error) { return undefined } }
      const agents = ctxOf('agents')
      const runtime = ctxOf('commands')
      if (agents === undefined || runtime === undefined) return { ok: false, error: 'agents/commands 服务不可用' }
      const sessionId = store.sessionOf(convKey)
      if (sessionId === undefined) return { ok: false, error: '这个会话还没有 DSH 会话' }
      const agent = typeof agents.get === 'function' ? agents.get(sessionId) : undefined
      if (agent === undefined) return { ok: false, error: '会话未加载（先聊一句）' }
      try {
        const result = await runtime.execute(agent, line, [], new AbortController().signal)
        return { ok: true, handled: result !== undefined, line }
      } catch (error) {
        return { ok: false, error: 'execute failed: ' + (error instanceof Error ? error.message : String(error)) }
      }
    },
    permission: async (body) => {
      await ready
      const convKey = typeof body?.convKey === 'string' ? body.convKey.trim() : ''
      const preset = typeof body?.preset === 'string' ? body.preset.trim() : ''
      let service = host.permissionPresets
      if (service === undefined && typeof ctx.get === 'function') service = ctx.get('permissionPresets')
      const names = service && Array.isArray(service.names) ? service.names.slice() : []
      // 该会话"当下生效"的权限值（会话投影），读不到就退回默认值
      const liveCurrent = () => {
        try {
          const sid = store.sessionOf(convKey)
          if (sid === undefined) return ''
          const pick = (name) => { try { return typeof ctx.get === 'function' ? ctx.get(name) : undefined } catch (error) { return undefined } }
          const sessions = pick('sessions')
          let session = sessions && typeof sessions.get === 'function' ? sessions.get(sid) : undefined
          if (session === undefined) {
            const agents = pick('agents')
            session = agents && typeof agents.get === 'function' ? agents.get(sid) : undefined
          }
          if (session !== undefined && service && typeof service.current === 'function') return service.current(session)
        } catch (error) {
          return ''
        }
        return ''
      }
      if (preset === '') {
        return {
          ok: names.length > 0,
          names,
          current: liveCurrent() || (service && typeof service.defaultPreset === 'string' ? service.defaultPreset : ''),
          note: names.length > 0 ? '' : 'permissionPresets 服务不可用（这条 DSH 没启用权限预设）',
        }
      }
      if (names.length > 0 && !names.includes(preset)) {
        return { ok: false, error: 'unknown preset: ' + preset, names }
      }
      const sessionController = host.sessionController
      let sessionId = store.sessionOf(convKey)
      if (sessionController === undefined && sessionId === undefined) {
        return { ok: false, error: 'sessionController unavailable' }
      }
      if (sessionId === undefined) {
        // 还没聊过：先给这个 QQ 会话建 DSH 会话（自动工作区开启时自带独立目录），
        // 否则 /pr 没法把命令投递进去。
        try {
          const created = await sessionController.create({
            cwd: await workspaceFor(convKey, { autoGroup: body?.autoGroup, autoGroupRoot: body?.autoGroupRoot }),
          })
          sessionId = String(created.sessionId)
          await store.bind(convKey, sessionId, typeof body?.approvalTarget === 'string' ? body.approvalTarget : undefined)
        sessionToConv.set(String(sessionId), convKey)
        } catch (error) {
          return { ok: false, error: 'create session failed: ' + (error instanceof Error ? error.message : String(error)) }
        }
      }
      // 官方写入口：permissionPresets.set(session, name)（/permission 命令内部走的就是它）。
      // 之前用 sessionController.prompt 发文本，斜杠命令不会被解释，只会变成一条用户消息。
      let sessions = undefined
      try { sessions = typeof ctx.get === 'function' ? ctx.get('sessions') : undefined } catch (error) { sessions = undefined }
      const session = sessions && typeof sessions.get === 'function' ? sessions.get(sessionId) : undefined
      if (session === undefined) return { ok: false, error: '会话还没加载，先聊一句再试' }
      if (service === undefined || typeof service.set !== 'function') {
        return { ok: false, error: 'permissionPresets 服务不可用' }
      }
      try {
        service.set(session, preset)
      } catch (error) {
        return { ok: false, error: 'set failed: ' + (error instanceof Error ? error.message : String(error)) }
      }
      let landed = ''
      try { landed = typeof service.current === 'function' ? service.current(session) : '' } catch (error) { landed = '' }
      return { ok: true, switched: preset, current: landed, names }
    },

    judge: async (body) => {
      await ready
      const convKey = typeof body?.convKey === 'string' ? body.convKey.trim() : ''
      const transcript = typeof body?.transcript === 'string' ? body.transcript.trim() : ''
      if (convKey === '' || transcript === '') return { ok: false, error: 'convKey/transcript required' }
      const sessionController = host.sessionController
      if (sessionController === undefined) return { ok: false, error: 'sessionController unavailable' }

      let sessionId = judgeSessions.get(convKey)
      try {
        if (sessionId === undefined) {
          const created = await sessionController.create({ cwd: config.cwd })
          sessionId = String(created.sessionId)
          judgeSessions.set(convKey, sessionId)
          log(`judge session for ${convKey}: ${sessionId}`)
        }
      } catch (error) {
        return { ok: false, error: `judge session failed: ${error instanceof Error ? error.message : String(error)}` }
      }

      judgeTexts.set(sessionId, [])
      const verdict = new Promise(resolve => {
        judgeWaiters.set(sessionId, resolve)
        setTimeout(() => {
          if (judgeWaiters.get(sessionId) === resolve) {
            judgeWaiters.delete(sessionId)
            resolve('')
          }
        }, 90000)
      })

      const instruction = [
        '【群聊插话判断器】你是一个独立判断器，不参与聊天，只做判断。',
        '下面是这个群里最近的消息原文（每行 发言人: 内容）：',
        transcript,
        '',
        '判断现在是否需要一个机器人插话/回答。只输出两行：',
        '第一行：REPLY 或 SKIP',
        '第二行：一句话理由（不超过40字）',
      ].join('\n')

      try {
        await sessionController.prompt({
          requestId: randomUUID(),
          sessionId,
          mode: 'queue',
          content: [{ type: 'text', text: instruction }],
          clientTimeZone: 'Asia/Shanghai',
        }, new AbortController().signal)
      } catch (error) {
        judgeWaiters.delete(sessionId)
        return { ok: false, error: `judge prompt failed: ${error instanceof Error ? error.message : String(error)}` }
      }

      const answer = String(await verdict)
      const lines = answer.split('\n').map(line => line.trim()).filter(line => line !== '')
      const head = (lines[0] ?? '').toUpperCase()
      const needReply = head.startsWith('REPLY')
      const decisive = head.startsWith('REPLY') || head.startsWith('SKIP')
      return {
        ok: decisive,
        needReply,
        note: lines.slice(1).join(' ').slice(0, 200),
        raw: answer.slice(0, 200),
      }
    },
    approval: async (body) => {
      const approvalId = typeof body?.approvalId === 'string' ? body.approvalId : ''
      const decision = body?.decision === 'allow' ? 'allowed-once' : body?.decision === 'cancel' ? 'cancelled' : 'rejected'
      const finish = approvals.get(approvalId)
      if (finish === undefined) return { ok: false, error: 'unknown or expired approval' }
      finish(decision)
      log(`approval ${approvalId} → ${decision}`)
      return { ok: true, approvalId, decision }
    },
  })

  // Keep the QQ bot alive across DSH restarts: DSH owns its own lifecycle, so
  // the host half re-spawns the supervised bot whenever the panel is missing.
  const ensureBot = async () => {
    if (config.autoStartBot !== true) return
    try {
      const response = await fetch(`http://127.0.0.1:${config.panelPort ?? 39062}/health`, { signal: AbortSignal.timeout(1500) })
      if (response.ok) return
    } catch {
      // panel unreachable -> the supervisor is gone, start it
    }
    try {
      const { spawn } = await import('node:child_process')
      const child = spawn(config.pythonPath, ['-u', 'main.py', '--supervise'], {
        cwd: config.botDir,
        detached: true,
        stdio: 'ignore',
        windowsHide: true,
      })
      child.unref()
      log(`bot supervisor spawned (pid ${child.pid})`)
    } catch (error) {
      log(`bot autostart failed: ${error instanceof Error ? error.message : String(error)}`)
    }
  }
  ctx.effect(() => {
    const first = setTimeout(() => { void ensureBot() }, 8000)
    const ticker = setInterval(() => { void ensureBot() }, 60000)
    return () => { clearTimeout(first); clearInterval(ticker) }
  }, 'dsh-qq-bridge: keep the bot process alive')

  // Serve the loopback port for as long as this plugin entry stays loaded.
  ctx.effect(() => {
    // 提问通道默认关闭：DSH 的 user-questions/request 是瀑布事件，
    // 处理不当会让宿主 abort 并崩溃（crash-…-host.log）。稳定性验证通过后再打开。
    if (config.questionChannel === false) return () => {}
    const dispose = installQuestionChannel()
    return () => { try { dispose() } catch (error) { /* already gone */ } }
  }, 'dsh-qq-bridge: question channel')

  ctx.effect(() => {
    void bridge.start()
      .then(() => log(`listening on http://${config.host}:${bridge.port} (cwd: ${config.cwd})`))
      .catch(error => log(`listen failed: ${error instanceof Error ? error.message : String(error)}`))
    return () => { void bridge.stop() }
  }, 'dsh-qq-bridge: local http bridge')

  // Live token stream: the official plugin listens to the transient
  // 'agent/assistant-stream' event and reads frame.chunk.text, so do the same
  // instead of sessionController.follow() (which only yields step snapshots).
  const streams = new Map()          // sessionId -> convKey
  const agentSessions = new Map()    // agentId -> sessionId

  const startStream = (sessionId, convKey) => {
    if (config.streamEnabled !== true) return
    streams.set(sessionId, convKey)
  }

  const stopStream = (sessionId) => {
    streams.delete(sessionId)
    for (const [agentId, mapped] of agentSessions) {
      if (mapped === sessionId) agentSessions.delete(agentId)
    }
  }

  ctx.on('agent/assistant-stream', (payload) => {
    if (config.streamEnabled !== true || streams.size === 0) return
    const agentId = payload?.agent?.id
    const frame = payload?.frame
    if (typeof agentId !== 'string' || agentId === '' || frame == null) return

    let sessionId = agentSessions.get(agentId)
    if (sessionId === undefined) {
      const newest = [...streams.keys()].pop()
      if (newest === undefined) return
      agentSessions.set(agentId, newest)
      sessionId = newest
    }
    const convKey = streams.get(sessionId)
    if (convKey === undefined) return
    if (frame.type !== 'chunk') return
    const chunk = frame.chunk
    if (chunk?.type !== 'text-delta' || typeof chunk.text !== 'string' || chunk.text === '') return
    bridge.push({
      type: 'stream',
      convKey,
      turnId: turns.get(sessionId)?.turnId ?? '',
      text: chunk.text,
      final: false,
    })
  })

  // Independent judge sessions (Plan B): one per conversation, no shared history.
  const judgeTexts = new Map()     // sessionId -> collected assistant text
  const judgeWaiters = new Map()   // sessionId -> resolve(text)
  const judgeSessions = new Map()  // convKey  -> sessionId

  // Capture each finished turn so the bot can answer the QQ message.
  ctx.on('session/event', (session, event) => {
    const sessionId = String(session?.id ?? '')
    if (sessionId === '') return
    const convKey = store.convOf(sessionId)
    if (convKey === undefined) return
    const data = event?.data ?? {}
    if (judgeTexts.has(sessionId)) {
      if (event.type === 'assistant/message') {
        const t = textOf(data.message)
        if (t.trim() !== '') judgeTexts.get(sessionId).push(t)
      }
      if (event.type === 'turn/end') {
        const done = judgeWaiters.get(sessionId)
        if (done !== undefined) {
          judgeWaiters.delete(sessionId)
          done(judgeTexts.get(sessionId).join('\n').trim())
        }
      }
      return
    }
    if (event.type === 'turn/start') {
      turns.set(sessionId, { texts: [], tools: [], turnId: `${Date.now().toString(36)}-${sessionId.slice(-6)}` })
      startStream(sessionId, convKey)
      return
    }
    if (event.type === 'assistant/message') {
      const state = turns.get(sessionId)
      if (state === undefined) return
      const text = textOf(data.message)
      if (text.trim() !== '') state.texts.push(text)
      return
    }
    if (event.type === 'tool/call') {
      const state = turns.get(sessionId)
      if (state === undefined) return
      if (typeof data.name === 'string') state.tools.push(data.name)
      if (typeof data.callId === 'string') {
        callArguments.set(`${sessionId}:${data.callId}`, preview(data.arguments, config.argumentPreviewChars))
        if (callArguments.size > 200) callArguments.delete(callArguments.keys().next().value)
      }
      return
    }
    if (event.type === 'turn/end') {
      const state = turns.get(sessionId) ?? { texts: [], tools: [] }
      turns.delete(sessionId)
      stopStream(sessionId)
      bridge.push({ type: 'stream', convKey, turnId: state.turnId ?? '', text: state.texts.join('\n\n').trim(), final: true })
      // data.reason is an object on this host generation; never ship "[object Object]"
      const rawReason = data.reason
      const reason = typeof rawReason === 'string'
        ? rawReason
        : (rawReason && typeof rawReason === 'object' ? String(rawReason.kind ?? rawReason.type ?? '') : '')
      bridge.push({
        type: 'reply',
        convKey,
        turnId: state.turnId ?? '',
        text: state.texts.join('\n\n').trim(),
        tools: state.tools,
        reason,
      })
    }
  })

  // Route approvals of bridged Sessions to their owner FIRST: the Web GUI also
  // answers approvals, and only a prepended listener wins that waterfall.
  // Sessions this plugin does not own fall through with next().
  ctx.on('approval/request', async (request, next) => {
    const sessionId = String(request?.agent?.session?.id ?? '')
    const convKey = sessionId === '' ? undefined : store.convOf(sessionId)
    if (convKey === undefined) return next()
    if (!botIsListening()) {
      // Nobody is polling the bridge: never swallow the approval, let the GUI ask.
      log(`approval for ${convKey} handed to the GUI (bot not polling)`)
      return next()
    }
    const approvalTarget = store.approvalTargetOf(convKey) ?? convKey
    const callId = typeof request?.callId === 'string' ? request.callId : ''
    try {
      return await requestDecision({
        approvalId: randomUUID(),
        convKey,
        approvalTarget,
        toolName: String(request?.toolName ?? 'unknown'),
        reason: String(request?.reason ?? ''),
        argumentPreview: callId === '' ? '' : (callArguments.get(`${sessionId}:${callId}`) ?? ''),
        signal: request?.signal,
      })
    } catch (error) {
      log(`approval relay failed: ${error instanceof Error ? error.message : String(error)}`)
      return 'rejected'
    }
  }, { prepend: true })

  // The Session service may arrive after this entry; wait for it instead of
  // failing the whole profile boot when it is absent.
  // Model-facing retrieval over the timestamped history buffer.
  ctx.inject(['tools'], (scope) => {
    const tools = scope.tools ?? (typeof scope.get === 'function' ? scope.get('tools') : undefined)
    if (tools === undefined || typeof tools.register !== 'function') {
      log('qq_history tool unavailable (tools service missing)')
      return
    }
    const definition = {
      name: 'qq_history',
      description:
        '搜索 QQ 群聊/私聊最近的历史消息（每行带 [HH:MM] 时间戳）。' +
        '当对方提到你没见过的内容、或需要确认「谁在什么时候说过什么」时调用。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          convKey: { type: 'string', description: '会话键，如 group:XXXX 或 c2c:XXXX；留空表示所有会话' },
          query: { type: 'string', description: '关键词，留空返回最近若干条' },
          limit: { type: 'number', description: '返回条数上限，默认 30，最大 100' },
        },
      },
      output: {
        schema: { type: 'object' },
        render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
      },
      async execute(args) {
        const limit = Math.max(1, Math.min(Number(args?.limit ?? 30) || 30, 100))
        const needle = typeof args?.query === 'string' ? args.query.trim() : ''
        const convFilter = typeof args?.convKey === 'string' ? args.convKey.trim() : ''
        const keys = convFilter !== '' ? [convFilter] : [...history.keys()]
        const lines = []
        for (const key of keys) {
          for (const line of history.get(key) ?? []) {
            if (needle === '' || line.includes(needle)) lines.push(`${key} ${line}`)
          }
        }
        return { ok: true, count: lines.slice(-limit).length, lines: lines.slice(-limit) }
      },
    }
    try {
      tools.register(definition)
      log('qq_history tool registered')
    } catch (error) {
      log(`qq_history registration failed: ${error instanceof Error ? error.message : String(error)}`)
    }

    // ── 群管理工具（禁言 / 踢人 / 成员索引） ──
    const adminCall = async (payload) => {
      const port = Number(config.panelPort) || 39062
      const response = await fetch(`http://127.0.0.1:${port}/api/admin`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      })
      return await response.json().catch(() => ({}))
    }

    const readMembers = () => {
      try {
        const file = join(String(config.botDir || "."), "state", "members.json")
        const raw = readFileSync(file, "utf8")
        return JSON.parse(raw)
      } catch (error) {
        return {}
      }
    }

    const resolveMember = (convKey, member) => {
      const known = readMembers()[convKey] || {}
      const raw = String(member || "").trim().replace(/^@/, "").replace(/^群友/i, "").toUpperCase()
      if (raw === "") return undefined
      for (const [tail, info] of Object.entries(known)) {
        if (tail.toUpperCase() === raw) return info?.openid ?? info
      }
      for (const [tail, info] of Object.entries(known)) {
        if (raw.length >= 4 && tail.toUpperCase().includes(raw)) return info?.openid ?? info
      }
      // 按昵称找人：群里 @ 出来的名字或自己记得的名字都能用
      const wanted = String(member || "").trim().replace(/^@/, "").replace(/^群友/i, "")
      if (wanted) {
        for (const [tail, info] of Object.entries(known)) {
          const name = String((info && typeof info === "object" && info.name) || "").trim()
          if (name && name.toLowerCase() === wanted.toLowerCase()) return info?.openid ?? info
        }
        for (const [tail, info] of Object.entries(known)) {
          const name = String((info && typeof info === "object" && info.name) || "").trim()
          if (name && wanted.length >= 2 && name.toLowerCase().includes(wanted.toLowerCase())) return info?.openid ?? info
        }
      }
      if (/^[0-9A-F]{32}$/.test(raw)) return raw
      return undefined
    }

    const adminTools = [
      {
        name: "qq_members",
        description: "列出本群/本会话里发过言的成员（短号 → openid）。禁言/踢人前先查这个拿短号。",
        parameters: { type: "object", additionalProperties: false, properties: { convKey: { type: "string", description: "会话键，如 group:XXXX" } } },
        async execute(args) {
          const convKey = String(args?.convKey || "")
          const all = readMembers()
          const people = convKey !== "" ? { [convKey]: all[convKey] || {} } : all
          const lines = []
          for (const [key, members] of Object.entries(people)) {
            for (const [tail, info] of Object.entries(members || {})) {
              lines.push({
                convKey: key,
                tail,
                name: (info && typeof info === "object" && info.name) || "",
                openid: (info && typeof info === "object" ? info.openid : info) || "",
                avatar: (info && typeof info === "object" && info.avatar) || "",
              })
            }
          }
          return { ok: true, count: lines.length, members: lines }
        },
      },
      {
        name: "qq_mute",
        description: "禁言群里某个成员（需要机器人是群管理员且有接口权限）。member 可以是短号（如 1B6CBB）或 @群友XXXX。",
        parameters: {
          type: "object", additionalProperties: false,
          required: ["convKey", "member", "minutes"],
          properties: {
            convKey: { type: "string", description: "会话键，如 group:XXXX" },
            member: { type: "string", description: "被禁言的成员：短号或 @群友XXXX" },
            minutes: { type: "number", description: "禁言分钟数（720=12 小时）；传 0 表示解除禁言" },
          },
        },
        async execute(args) {
          const convKey = String(args?.convKey || "")
          const openid = resolveMember(convKey, args?.member)
          if (openid === undefined) return { ok: false, error: "找不到这个成员，先调用 qq_members 看短号" }
          const group = convKey.startsWith("group:") ? convKey.slice(6) : convKey
          // minutes <= 0 表示解除禁言（op=del）；注意不能用 `|| 10`，否则 0 会被吞成 10
          const raw = Number(args?.minutes)
          const minutes = Number.isFinite(raw) ? raw : 10
          const seconds = minutes <= 0 ? 0 : Math.min(Math.round(minutes * 60), 60 * 60 * 24 * 30)
          const result = await adminCall({ action: "mute", convKey, group, member: openid, seconds })
          return {
            ok: result.ok === true,
            member: args?.member,
            op: seconds > 0 ? "add" : "del",
            minutes: seconds / 60,
            error: result.error,
          }
        },
      },
      {
        name: "qq_unmute",
        description: "解除某个成员的禁言（等价 op=del）。语义独立，避免把 0 分钟误当禁言时长。",
        parameters: {
          type: "object", additionalProperties: false,
          required: ["convKey", "member"],
          properties: {
            convKey: { type: "string", description: "会话键，如 group:XXXX" },
            member: { type: "string", description: "成员：短号或 @群友XXXX" },
          },
        },
        async execute(args) {
          const convKey = String(args?.convKey || "")
          const openid = resolveMember(convKey, args?.member)
          if (openid === undefined) return { ok: false, error: "找不到这个成员，先调用 qq_members 看短号" }
          const group = convKey.startsWith("group:") ? convKey.slice(6) : convKey
          const result = await adminCall({ action: "mute", convKey, group, member: openid, seconds: 0 })
          return { ok: result.ok === true, member: args?.member, op: "del", error: result.error }
        },
      },
      {
        name: "qq_mute_state",
        description: "查询本群当前的禁言设置（平台原样返回），用于确认禁言/解禁是否真的生效。",
        parameters: {
          type: "object", additionalProperties: false,
          required: ["convKey"],
          properties: { convKey: { type: "string", description: "会话键，如 group:XXXX" } },
        },
        async execute(args) {
          const convKey = String(args?.convKey || "")
          const group = convKey.startsWith("group:") ? convKey.slice(6) : convKey
          const result = await adminCall({ action: "mute_state", convKey, group })
          return { ok: result.ok === true, state: result.state, error: result.error }
        },
      },
      {
        name: "qq_kick",
        description: "把某个成员移出群（需要机器人是群管理员且有接口权限）。member 可以是短号或 @群友XXXX。",
        parameters: {
          type: "object", additionalProperties: false,
          required: ["convKey", "member"],
          properties: {
            convKey: { type: "string", description: "会话键，如 group:XXXX" },
            member: { type: "string", description: "被移出的成员：短号或 @群友XXXX" },
            blacklist: { type: "boolean", description: "是否同时拉黑，默认否" },
          },
        },
        async execute(args) {
          const convKey = String(args?.convKey || "")
          const openid = resolveMember(convKey, args?.member)
          if (openid === undefined) return { ok: false, error: "找不到这个成员，先调用 qq_members 看短号" }
          const group = convKey.startsWith("group:") ? convKey.slice(6) : convKey
          const result = await adminCall({ action: "kick", convKey, group, member: openid, blacklist: args?.blacklist === true })
          if (result.pending === true) {
            // 还没执行：明确告诉模型"等待确认"，不要说已经踢了
            return {
              ok: false,
              pending: true,
              member: args?.member,
              error: null,
              hint: result.hint || "已发送私聊二次确认，等主人点头后才执行；现在还没有踢人",
            }
          }
          return { ok: result.ok === true, member: args?.member, error: result.error }
        },
      },
    ]

    const infoTools = [
      {
        name: "qq_group",
        description: "查看当前群资料：群名、群简介、分类、标签、成员数，以及全群禁言规则。",
        parameters: { type: "object", properties: { convKey: { type: "string", description: "会话键，如 group:XXXX" } } },
        async execute(args) {
          const convKey = String(args?.convKey || "")
          const group = convKey.startsWith("group:") ? convKey.slice(6) : convKey
          const result = await adminCall({ action: "group", convKey, group })
          return { ok: result.ok === true, group: result.group, mute_rule: result.mute_rule, known_members: result.known_members, error: result.error }
        },
      },
      {
        name: "qq_muted",
        description: "列出本群当前被禁言的成员（名字、openid、短号、到期时间）。",
        parameters: { type: "object", properties: { convKey: { type: "string", description: "会话键，如 group:XXXX" } } },
        async execute(args) {
          const convKey = String(args?.convKey || "")
          const group = convKey.startsWith("group:") ? convKey.slice(6) : convKey
          const result = await adminCall({ action: "muted", convKey, group })
          return { ok: result.ok === true, count: result.count || 0, muted: result.muted || [], error: result.error }
        },
      },
      {
        name: "qq_member",
        description: "查看某个群成员的资料：昵称、头像地址、openid、短号、最后发言时间、是否被禁言。member 可传短号/昵称/openid。",
        parameters: {
          type: "object",
          properties: {
            convKey: { type: "string", description: "会话键，如 group:XXXX" },
            member: { type: "string", description: "短号、昵称或 openid" },
          },
        },
        async execute(args) {
          const convKey = String(args?.convKey || "")
          const openid = resolveMember(convKey, args?.member)
          if (openid === undefined) return { ok: false, error: "找不到这个成员，先调用 qq_members 看短号" }
          const group = convKey.startsWith("group:") ? convKey.slice(6) : convKey
          const result = await adminCall({ action: "member", convKey, group, member: openid })
          return { ok: result.ok === true, member: result.member, error: result.error }
        },
      },
      {
        name: "qq_stats",
        description: "查看机器人统计：私聊/群聊消息数、插话判断与开口次数、流式次数、文件发送、审批、提问、禁言踢人次数、最近事件。",
        parameters: { type: "object", properties: {} },
        async execute() {
          const result = await adminCall({ action: "stats" })
          return { ok: result.ok === true, counters: result.counters, events: result.events, error: result.error }
        },
      },
    ]

    // DSH 拒收非无损 JSON（undefined / NaN / Infinity），工具返回值先过一遍
    const jsonSafe = (value) => {
      if (value === null) return null
      const kind = typeof value
      if (kind === "undefined" || kind === "function" || kind === "symbol") return undefined
      if (kind === "number") return Number.isFinite(value) ? value : null
      if (kind === "bigint") return String(value)
      if (kind !== "object") return value
      if (Array.isArray(value)) return value.map((item) => {
        const clean = jsonSafe(item)
        return clean === undefined ? null : clean
      })
      const out = {}
      for (const [key, item] of Object.entries(value)) {
        const clean = jsonSafe(item)
        if (clean !== undefined) out[key] = clean
      }
      return out
    }

    for (const tool of [...infoTools, ...adminTools]) {
      try {
        tools.register({
          ...tool,
          execute: async (...args) => jsonSafe(await tool.execute(...args)),
          output: { schema: { type: "object" }, render: (_a, value) => [{ type: "text", text: JSON.stringify(value) }] },
        })
        log(`${tool.name} tool registered`)
      } catch (error) {
        log(`${tool.name} registration failed: ${error instanceof Error ? error.message : String(error)}`)
      }
    }
  })

  ctx.inject(['sessionController'], (sctx) => {
    host.sessionController = sctx.sessionController
    log('sessionController attached')
  })
}
