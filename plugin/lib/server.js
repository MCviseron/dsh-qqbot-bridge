/**
 * Loopback HTTP carrier between the external QQ bot process and this Host
 * plugin: inbound prompts go in, replies and approval questions come out
 * through a long-poll event log.
 */
import { createServer } from 'node:http'

const MAX_BODY_BYTES = 1 << 20
const LOOPBACK = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1'])
const ROUTES = new Set(['health', 'status', 'pull', 'inbound', 'approval', 'reset', 'switch', 'sessions'])

/** Write one JSON response. */
function respond(res, status, value) {
  const body = Buffer.from(JSON.stringify(value), 'utf8')
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': body.length,
    'cache-control': 'no-store',
  })
  res.end(body)
}

/** Read one bounded JSON request body. */
async function readJson(req) {
  const chunks = []
  let size = 0
  for await (const chunk of req) {
    size += chunk.length
    if (size > MAX_BODY_BYTES) throw new Error('request body too large')
    chunks.push(chunk)
  }
  if (chunks.length === 0) return {}
  const text = Buffer.concat(chunks).toString('utf8')
  if (text.trim() === '') return {}
  return JSON.parse(text)
}

export class HttpBridge {
  #events = []
  #seq = 0
  #waiters = new Set()
  #handlers = {}
  #onPull
  #server

  /** @param {{host?: string, port: number, token?: string, log?: (message: string) => void, capacity?: number}} options */
  constructor({ host = '127.0.0.1', port, token = '', log = () => {}, capacity = 1000 }) {
    this.host = host
    this.port = port
    this.token = token
    this.log = log
    this.capacity = capacity
  }

  /** Register the business handlers the routes delegate to. */
  setHandlers(handlers) {
    this.#handlers = { ...handlers }
  }

  /** Called on every /pull so the host knows the bot is alive and listening. */
  setOnPull(callback) {
    this.#onPull = callback
  }

  /** Append one outbound event and wake every waiting poll. */
  push(event) {
    const entry = { seq: ++this.#seq, at: Date.now(), ...event }
    this.#events.push(entry)
    if (this.#events.length > this.capacity) this.#events.splice(0, this.#events.length - this.capacity)
    const waiters = [...this.#waiters]
    this.#waiters.clear()
    for (const wake of waiters) wake()
    return entry
  }

  /** Events strictly newer than `since`. */
  take(since) {
    return this.#events.filter(event => event.seq > since)
  }

  /** Current sequence number, so a fresh client can begin at "now". */
  get cursor() {
    return this.#seq
  }

  /** Resolve once a newer event exists or the wait elapses. */
  #waitFor(since, timeoutMs) {
    if (this.take(since).length > 0) return Promise.resolve()
    return new Promise(resolve => {
      const finish = () => {
        clearTimeout(timer)
        this.#waiters.delete(finish)
        resolve()
      }
      const timer = setTimeout(finish, timeoutMs)
      this.#waiters.add(finish)
    })
  }

  /** Bind the loopback port; resolves with the effective address. */
  async start() {
    this.#server = createServer((req, res) => {
      void this.#dispatch(req, res).catch(error => {
        this.log(`request failed: ${error instanceof Error ? error.message : String(error)}`)
        if (!res.headersSent) respond(res, 500, { ok: false, error: 'internal error' })
      })
    })
    await new Promise((resolve, reject) => {
      this.#server.once('error', reject)
      this.#server.listen(this.port, this.host, () => {
        this.#server.off('error', reject)
        resolve()
      })
    })
    const address = this.#server.address()
    if (address !== null && typeof address === 'object') this.port = address.port
    return address
  }

  /** Release the port. */
  async stop() {
    const server = this.#server
    this.#server = undefined
    this.#waiters.clear()
    if (server === undefined) return
    await new Promise(resolve => server.close(() => resolve()))
  }

  /** Route, authenticate, and answer one request. */
  async #dispatch(req, res) {
    const remote = req.socket.remoteAddress ?? ''
    if (!LOOPBACK.has(remote)) {
      respond(res, 403, { ok: false, error: 'loopback only' })
      return
    }
    if (this.token !== '' && req.headers['x-bridge-token'] !== this.token) {
      respond(res, 401, { ok: false, error: 'bad token' })
      return
    }

    const url = new URL(req.url ?? '/', `http://${this.host}:${this.port}`)
    const path = url.pathname.replace(/^\/+|\/+$/g, '')
    if (!ROUTES.has(path)) {
      respond(res, 404, { ok: false, error: 'unknown route' })
      return
    }

    if (path === 'pull') {
      if (req.method !== 'GET') {
        respond(res, 405, { ok: false, error: 'GET only' })
        return
      }
      const sinceRaw = url.searchParams.get('since')
      const since = sinceRaw === null ? this.#seq : Number.parseInt(sinceRaw, 10)
      const waitRaw = Number.parseInt(url.searchParams.get('wait') ?? '0', 10)
      const wait = Number.isFinite(waitRaw) ? Math.min(Math.max(waitRaw, 0), 55000) : 0
      if (!Number.isFinite(since)) {
        respond(res, 400, { ok: false, error: 'bad since' })
        return
      }
      try {
        this.#onPull?.()
      } catch {
        // a broken observer must never break the pull route
      }
      await this.#waitFor(since, wait)
      respond(res, 200, { ok: true, cursor: this.#seq, events: this.take(since) })
      return
    }

    const handler = this.#handlers[path]
    if (typeof handler !== 'function') {
      respond(res, 503, { ok: false, error: `${path} not ready` })
      return
    }

    let body = {}
    if (req.method === 'POST') {
      try {
        body = await readJson(req)
      } catch (error) {
        respond(res, 400, { ok: false, error: `bad body: ${error instanceof Error ? error.message : String(error)}` })
        return
      }
    } else if (req.method !== 'GET') {
      respond(res, 405, { ok: false, error: 'method not allowed' })
      return
    }

    try {
      const value = await handler(body)
      const status = value !== null && typeof value === 'object' && value.ok === false ? 400 : 200
      respond(res, status, value)
    } catch (error) {
      respond(res, 400, { ok: false, error: error instanceof Error ? error.message : String(error) })
    }
  }
}
