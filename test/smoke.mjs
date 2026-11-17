/** Offline smoke test of the HTTP carrier and the conversation store (no DSH needed). */
import { mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { HttpBridge } from '../lib/server.js'
import { ConversationStore } from '../lib/store.js'

const failures = []
function check(condition, label) {
  if (condition) {
    console.log(`ok   ${label}`)
  } else {
    failures.push(label)
    console.log(`FAIL ${label}`)
  }
}

const dir = await mkdtemp(join(tmpdir(), 'qq-bridge-'))
const store = await new ConversationStore(join(dir, 'state.json')).load()
await store.bind('group:abc', 'session-1', 'c2c:owner')
check(store.sessionOf('group:abc') === 'session-1', 'store binds forward')
check(store.convOf('session-1') === 'group:abc', 'store binds reverse')
check(store.approvalTargetOf('group:abc') === 'c2c:owner', 'store keeps approval target')
const reloaded = await new ConversationStore(join(dir, 'state.json')).load()
check(reloaded.sessionOf('group:abc') === 'session-1', 'store survives reload')

const bridge = new HttpBridge({ port: 0, token: 'secret', log: () => {} })
bridge.setHandlers({
  health: () => ({ ok: true }),
  inbound: async (body) => ({ ok: true, echo: body.text }),
  approval: async (body) => ({ ok: true, decision: body.decision }),
})
const address = await bridge.start()
const url = `http://127.0.0.1:${address.port}`
const auth = { 'x-bridge-token': 'secret', 'content-type': 'application/json' }

const health = await fetch(`${url}/health`, { headers: auth }).then(r => r.json())
check(health.ok === true, 'health without token body')

const unauthorized = await fetch(`${url}/health`)
check(unauthorized.status === 401, 'token enforced')

const inbound = await fetch(`${url}/inbound`, { method: 'POST', headers: auth, body: JSON.stringify({ text: 'hi' }) }).then(r => r.json())
check(inbound.echo === 'hi', 'inbound reaches handler')

bridge.push({ type: 'reply', convKey: 'group:abc', text: 'hello' })
const pulled = await fetch(`${url}/pull?since=0&wait=0`, { headers: auth }).then(r => r.json())
check(pulled.events.length === 1 && pulled.events[0].text === 'hello', 'pull returns pushed events')
check(typeof pulled.cursor === 'number', 'pull reports cursor')

const empty = await fetch(`${url}/pull?since=${pulled.cursor}&wait=50`, { headers: auth }).then(r => r.json())
check(empty.events.length === 0, 'long poll returns empty after timeout')

const waiting = fetch(`${url}/pull?since=${pulled.cursor}&wait=2000`, { headers: auth }).then(r => r.json())
setTimeout(() => bridge.push({ type: 'reply', convKey: 'group:abc', text: 'late' }), 100)
const late = await waiting
check(late.events.length === 1 && late.events[0].text === 'late', 'long poll wakes on push')

const unknown = await fetch(`${url}/nope`, { headers: auth })
check(unknown.status === 404, 'unknown route')

await bridge.stop()
console.log(failures.length === 0 ? '\nALL PASS' : `\n${failures.length} FAILED`)
process.exit(failures.length === 0 ? 0 : 1)
