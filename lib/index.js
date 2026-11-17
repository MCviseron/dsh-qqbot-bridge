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

  const remember = (convKey, line) => {
    const list = contexts.get(convKey) ?? []
    list.push(line)
    if (list.length > config.contextLines) list.splice(0, list.length - config.contextLines)
    contexts.set(convKey, list)
  }

  /** Model-facing preamble: where the message came from and who is speaking. */
  const composePrompt = ({ text, convKey, senderName, isOwner, chime }) => {
    const isGroup = convKey.startsWith('group:')
    const header = isGroup ? 'QQ 群聊' : 'QQ 单聊'
    const who = isOwner
      ? `${senderName || '主人'}（机器人主人本人：可以远程办公，直接读写工作目录、执行命令、查资料，做完再回答）`
      : `${senderName || '群友'}（普通群友：自然聊天为主；要改文件或跑命令时先说明理由，主人批准后才继续）`
    const recent = contexts.get(convKey) ?? []
    const parts = [`[${header}] ${who}：`, text]
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
      const label = text.trim() === '' ? '[图片]' : preview(text, 200)

      // Background group chatter: keep it as context, never start a turn for it.
      if (body?.contextOnly === true) {
        remember(convKey, `${senderName || '群友'}: ${label}`)
        return { ok: true, buffered: true }
      }

      const sessionController = host.sessionController
      if (sessionController === undefined) return { ok: false, error: 'sessionController unavailable' }

      let sessionId = store.sessionOf(convKey)
      if (sessionId === undefined) {
        const created = await sessionController.create({ cwd: config.cwd })
        sessionId = String(created.sessionId)
        log(`session created: ${convKey} → ${sessionId}`)
      }
      await store.bind(convKey, sessionId, typeof body?.approvalTarget === 'string' ? body.approvalTarget : undefined)

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

      const content = [{ type: 'text', text: composePrompt({ text, convKey, senderName, isOwner: body?.isOwner === true, chime: body?.chime === true }) }]
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
      remember(convKey, `${senderName || '群友'}: ${label}`)
      return { ok: true, sessionId, accepted: true }
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

  // Capture each finished turn so the bot can answer the QQ message.
  ctx.on('session/event', (session, event) => {
    const sessionId = String(session?.id ?? '')
    if (sessionId === '') return
    const convKey = store.convOf(sessionId)
    if (convKey === undefined) return
    const data = event?.data ?? {}
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
  ctx.inject(['sessionController'], (sctx) => {
    host.sessionController = sctx.sessionController
    log('sessionController attached')
  })
}
