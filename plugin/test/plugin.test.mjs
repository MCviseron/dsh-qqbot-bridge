/**
 * End-to-end test of the plugin against a fake cordis Context: proves the glue
 * (session create/prompt, turn capture, approval relay) without a DSH host.
 */
import { mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../lib/index.js'

const failures = []
function check(condition, label) {
  if (condition) console.log(`ok   ${label}`)
  else {
    failures.push(label)
    console.log(`FAIL ${label}`)
  }
}

const dataDir = await mkdtemp(join(tmpdir(), 'qq-bridge-plugin-'))
const port = 39099
const token = 'test-token'
const calls = { create: 0, prompt: [], approval: [] }

const controller = {
  async create(request) {
    calls.create += 1
    if (typeof request.cwd !== 'string' || request.cwd === '') throw new Error('cwd missing')
    return { sessionId: 'session-1' }
  },
  async prompt(request) {
    calls.prompt.push(request)
    return { accepted: true }
  },
}

const listeners = new Map()
const disposers = []
const ctx = {
  effect(fn, label) {
    const dispose = fn()
    disposers.push({ dispose, label })
  },
  on(event, handler) {
    listeners.set(event, handler)
  },
  inject(_services, callback) {
    callback({ sessionController: controller, effect: ctx.effect })
  },
}

process.env.DSH_HOME = dataDir
apply(ctx, { port, token, cwd: join(dataDir, 'workspace'), statePath: join(dataDir, 'state.json'), approvalTimeoutMs: 5000 })

const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms))
const auth = { 'x-bridge-token': token, 'content-type': 'application/json' }
const url = `http://127.0.0.1:${port}`
const get = (path, init) => fetch(url + path, { ...init, headers: auth })

let health
for (let attempt = 0; attempt < 40; attempt += 1) {
  try {
    health = await get('/health').then(r => r.json())
    break
  } catch {
    await delay(50)
  }
}
check(health?.ok === true, 'health answers')
check(health?.service === 'ready', 'sessionController reported ready')

// 设置页的「下载 / 配置机器人」轮询：走自定义头免 token，回执必须是 200 + ok:true
const installResponse = await get('/install', {
  method: 'POST',
  headers: { 'content-type': 'application/json', 'x-qqbridge-install': '1' },
  body: JSON.stringify({ action: 'status' }),
})
const installBody = await installResponse.json()
check(installResponse.status === 200, 'install status answers 200 (not 400)')
check(installBody.ok === true && Array.isArray(installBody.steps) && installBody.running === false, 'install status reports the step list')
check(typeof installBody.succeeded === 'boolean', 'install status reports success separately from the HTTP receipt')

const inbound = await get('/inbound', { method: 'POST', body: JSON.stringify({ convKey: 'group:g1', text: '你好', senderName: '群友A', isOwner: false, approvalTarget: 'c2c:owner', persona: '你是一条会说话的鱼喵' }) }).then(r => r.json())
check(inbound.ok === true && inbound.sessionId === 'session-1', 'inbound binds a session')
check(calls.create === 1, 'session created once')
check(calls.prompt.length === 1 && calls.prompt[0].content[0].text.includes('你好'), 'prompt carries the QQ text')
check(calls.prompt[0].mode === 'queue' && typeof calls.prompt[0].requestId === 'string', 'prompt uses queue mode with a request id')

check(calls.prompt[0].content[0].text.includes('人设：') && calls.prompt[0].content[0].text.includes('你是一条会说话的鱼喵'), 'persona rides the first message of a new session')

await get('/inbound', { method: 'POST', body: JSON.stringify({ convKey: 'group:g1', text: '再来一次', persona: '你是一条会说话的鱼喵' }) }).then(r => r.json())
check(calls.create === 1 && calls.prompt.length === 2, 'second message reuses the session')
check(!calls.prompt[1].content[0].text.includes('人设：'), 'persona is not repeated once the session has history')

// Turn capture: reply must travel back through the outbox.
const onEvent = listeners.get('session/event')
check(typeof onEvent === 'function', 'session/event listener registered')
onEvent({ id: 'session-1' }, { type: 'turn/start', data: { turn: 1 } })
onEvent({ id: 'session-1' }, { type: 'assistant/message', data: { message: { role: 'assistant', content: [{ type: 'text', text: '第一段' }, { type: 'tool-call', name: 'bash' }] } } })
onEvent({ id: 'session-1' }, { type: 'tool/call', data: { name: 'bash' } })
onEvent({ id: 'session-1' }, { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '第二段' }] } } })
onEvent({ id: 'session-1' }, { type: 'turn/end', data: { turn: 1, reason: 'success' } })

const pulled = await get('/pull?since=0&wait=2000').then(r => r.json())
const reply = pulled.events.find(event => event.type === 'reply')
check(reply?.text === '第一段\n\n第二段', 'assistant text is captured')
check(reply?.tools?.length === 1 && reply.tools[0] === 'bash', 'tool usage is reported')
check(reply?.convKey === 'group:g1', 'reply is routed to the conversation')

// Unknown sessions must never leak into the QQ outbox.
onEvent({ id: 'someone-else' }, { type: 'turn/start', data: { turn: 1 } })
onEvent({ id: 'someone-else' }, { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'private' }] } } })
onEvent({ id: 'someone-else' }, { type: 'turn/end', data: { turn: 1, reason: 'success' } })
const pulled2 = await get(`/pull?since=${pulled.cursor}&wait=300`).then(r => r.json())
check(pulled2.events.length === 0, 'unrelated sessions stay private')

// Approval relay: the owner decides, the outcome reaches the agent.
const approvalHandler = listeners.get('approval/request')
check(typeof approvalHandler === 'function', 'approval/request listener registered')
const decisionPromise = approvalHandler({ agent: { session: { id: 'session-1' } }, toolName: 'bash', reason: 'rm -rf build' }, async () => 'delegated')
await delay(50)
const approvalEvent = await get(`/pull?since=${pulled2.cursor}&wait=1000`).then(r => r.json()).then(body => body.events.find(event => event.type === 'approval'))
check(approvalEvent?.target === 'c2c:owner', 'approval goes to the owner conversation')
check(approvalEvent?.toolName === 'bash', 'approval carries the tool name')
const answered = await get('/approval', { method: 'POST', body: JSON.stringify({ approvalId: approvalEvent.approvalId, decision: 'allow' }) }).then(r => r.json())
check(answered.ok === true, 'approval route accepts the decision')
check(await decisionPromise === 'allowed-once', 'owner decision becomes allowed-once')

const delegated = await approvalHandler({ agent: { session: { id: 'other-session' } }, toolName: 'bash' }, async () => 'delegated')
check(delegated === 'delegated', 'foreign sessions keep their own answerer chain')

const reset = await get('/reset', { method: 'POST', body: JSON.stringify({ convKey: 'group:g1' }) }).then(r => r.json())
check(reset.ok === true, 'reset unbinds the conversation')

for (const { dispose } of disposers.reverse()) if (typeof dispose === 'function') dispose()
await delay(100)
console.log(failures.length === 0 ? '\nALL PASS' : `\n${failures.length} FAILED`)
process.exit(failures.length === 0 ? 0 : 1)
