#!/usr/bin/env node
/**
 * Token accounting for DSH Sessions.
 *
 *   node usage.mjs <sessionId>   one Session
 *   node usage.mjs --all         the most recent Sessions (newest 20)
 *
 * DSH stores each Session as multi-frame zstd (one frame per appended batch);
 * Node's zstdDecompressSync stops after the first frame, so the buffer is split
 * on the frame magic and decompressed batch by batch. Usage numbers live on
 * every assistant/message event, the title on session/title.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { zstdDecompressSync } from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const FILE = 'session.v4.jsonl.zstd'

/** Every zstd frame in one buffer, decoded in order. */
function decodeFrames(buffer) {
  const offsets = []
  let cursor = 0
  while (cursor < buffer.length - 4) {
    const at = buffer.indexOf(MAGIC, cursor)
    if (at < 0) break
    offsets.push(at)
    cursor = at + 4
  }
  const parts = []
  for (let index = 0; index < offsets.length; index += 1) {
    const start = offsets[index]
    for (let next = index + 1; next <= offsets.length; next += 1) {
      const end = next < offsets.length ? offsets[next] : buffer.length
      try {
        parts.push(zstdDecompressSync(buffer.subarray(start, end)))
        index = next - 1
        break
      } catch {
        // Frame boundary sat inside the payload; extend to the next magic.
      }
    }
  }
  return Buffer.concat(parts).toString('utf8')
}

/** DSH home: DSH_HOME, else ~/.dsh. */
function dshHome() {
  return process.env.DSH_HOME && process.env.DSH_HOME !== '' ? process.env.DSH_HOME : join(homedir(), '.dsh')
}

/** Aggregate usage fields over every assistant message of one Session log. */
function sumUsage(text) {
  const totals = {
    messages: 0,
    inputTokens: 0,
    outputTokens: 0,
    cacheReadTokens: 0,
    cacheWriteTokens: 0,
    totalTokens: 0,
    firstAt: null,
    lastAt: null,
  }
  const models = new Set()
  let title = ''
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue
    let event
    try {
      event = JSON.parse(line)
    } catch {
      continue
    }
    if (event.type === 'session/title' && typeof event.data?.title === 'string') title = event.data.title
    if (event.type !== 'assistant/message' || event.data === null || typeof event.data !== 'object') continue
    const usage = event.data.usage
    if (usage === null || typeof usage !== 'object') continue
    totals.messages += 1
    totals.inputTokens += Number(usage.inputTokens) || 0
    totals.outputTokens += Number(usage.outputTokens) || 0
    totals.cacheReadTokens += Number(usage.cacheReadTokens) || 0
    totals.cacheWriteTokens += Number(usage.cacheWriteTokens) || 0
    totals.totalTokens += Number(usage.totalTokens) || 0
    if (totals.firstAt === null) totals.firstAt = event.time
    totals.lastAt = event.time
    const model = event.data.message?.source?.model
    if (typeof model === 'string' && model !== '') models.add(model)
  }
  return { ...totals, title, models: [...models] }
}

/** Absolute path of one Session's event log, or undefined. */
function findSessionFile(sessionId) {
  const root = join(dshHome(), 'sessions')
  let groups = []
  try {
    groups = readdirSync(root)
  } catch {
    return undefined
  }
  for (const group of groups) {
    const candidate = join(root, group, sessionId, FILE)
    try {
      statSync(candidate)
      return candidate
    } catch {
      // Next workspace group.
    }
  }
  return undefined
}

/** The most recently written Session logs, newest first. */
function recentSessionFiles(limit) {
  const root = join(dshHome(), 'sessions')
  const found = []
  let groups = []
  try {
    groups = readdirSync(root)
  } catch {
    return found
  }
  for (const group of groups) {
    let ids = []
    try {
      ids = readdirSync(join(root, group))
    } catch {
      continue
    }
    for (const id of ids) {
      const path = join(root, group, id, FILE)
      try {
        found.push({ sessionId: id, path, mtimeMs: statSync(path).mtimeMs })
      } catch {
        // Not a Session directory.
      }
    }
  }
  found.sort((left, right) => right.mtimeMs - left.mtimeMs)
  return found.slice(0, limit)
}

function emit(value) {
  console.log(JSON.stringify(value))
}

const argument = process.argv[2] ?? ''

if (argument === '--all') {
  const sessions = []
  for (const entry of recentSessionFiles(20)) {
    try {
      const totals = sumUsage(decodeFrames(readFileSync(entry.path)))
      if (totals.messages === 0) continue
      sessions.push({ sessionId: entry.sessionId, ...totals })
    } catch {
      // A corrupt log must not hide the other Sessions.
    }
  }
  emit({ ok: true, sessions })
} else if (argument === '') {
  emit({ ok: false, error: 'session id required' })
} else {
  const file = findSessionFile(argument)
  if (file === undefined) {
    emit({ ok: false, error: 'session log not found' })
  } else {
    try {
      emit({ ok: true, sessionId: argument, file, ...sumUsage(decodeFrames(readFileSync(file))) })
    } catch (error) {
      emit({ ok: false, error: error instanceof Error ? error.message : String(error) })
    }
  }
}
