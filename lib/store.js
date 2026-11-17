/**
 * Conversation ↔ Session mapping, persisted as JSON so a Host restart keeps
 * every QQ conversation attached to the Session that already holds its history.
 */
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'

/** Empty mapping document. */
function emptyState() {
  return { version: 1, conversations: {}, sessions: {}, approvalTargets: {}, returns: {} }
}

export class ConversationStore {
  #path
  #data = emptyState()
  #writing = Promise.resolve()

  /** @param {string} path absolute state file path. */
  constructor(path) {
    this.#path = path
  }

  /** Read the persisted document; a missing file starts an empty mapping. */
  async load() {
    try {
      const parsed = JSON.parse(await readFile(this.#path, 'utf8'))
      if (parsed !== null && typeof parsed === 'object') {
        this.#data = {
          version: 1,
          conversations: { ...(parsed.conversations ?? {}) },
          sessions: { ...(parsed.sessions ?? {}) },
          approvalTargets: { ...(parsed.approvalTargets ?? {}) },
          returns: { ...(parsed.returns ?? {}) },
        }
      }
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
    return this
  }

  /** Session bound to one QQ conversation, if any. */
  sessionOf(convKey) {
    return this.#data.conversations[convKey]
  }

  /** QQ conversation owning one Session, if any. */
  convOf(sessionId) {
    return this.#data.sessions[sessionId]
  }

  /** Conversation that receives this conversation's approval questions. */
  approvalTargetOf(convKey) {
    return this.#data.approvalTargets[convKey]
  }

  /** Number of bound conversations, for /status. */
  size() {
    return Object.keys(this.#data.conversations).length
  }

  /** Bind (or rebind) one conversation to a Session. */
  async bind(convKey, sessionId, approvalTarget) {
    this.#data.conversations[convKey] = sessionId
    this.#data.sessions[sessionId] = convKey
    if (typeof approvalTarget === 'string' && approvalTarget !== '') {
      this.#data.approvalTargets[convKey] = approvalTarget
    }
    await this.#flush()
  }

  /** Drop one conversation binding (the Session itself is left untouched). */
  async unbind(convKey) {
    const sessionId = this.#data.conversations[convKey]
    delete this.#data.conversations[convKey]
    delete this.#data.approvalTargets[convKey]
    delete this.#data.returns[convKey]
    if (sessionId !== undefined) delete this.#data.sessions[sessionId]
    await this.#flush()
  }

  /** Session remembered by switchTo so the conversation can go back. */
  returnOf(convKey) {
    return this.#data.returns[convKey]
  }

  /** Every conversation that has a remembered return target. */
  returnEntries() {
    return Object.entries(this.#data.returns)
  }

  /** Rebind a conversation onto another existing Session, remembering the old one. */
  async switchTo(convKey, sessionId) {
    const current = this.#data.conversations[convKey]
    if (current !== undefined && current !== sessionId) {
      this.#data.returns[convKey] = current
      if (this.#data.sessions[current] === convKey) delete this.#data.sessions[current]
    }
    this.#data.conversations[convKey] = sessionId
    this.#data.sessions[sessionId] = convKey
    await this.#flush()
  }

  /** Undo one switchTo; resolves with the restored Session id, or undefined. */
  async switchBack(convKey) {
    const previous = this.#data.returns[convKey]
    if (previous === undefined) return undefined
    delete this.#data.returns[convKey]
    const temporary = this.#data.conversations[convKey]
    if (temporary !== undefined && this.#data.sessions[temporary] === convKey) delete this.#data.sessions[temporary]
    this.#data.conversations[convKey] = previous
    this.#data.sessions[previous] = convKey
    await this.#flush()
    return previous
  }

  /** Every bound conversation, newest state first seen order. */
  entries() {
    return Object.entries(this.#data.conversations)
  }

  /** Serialized atomic write so concurrent binds cannot interleave. */
  #flush() {
    this.#writing = this.#writing.then(async () => {
      await mkdir(dirname(this.#path), { recursive: true })
      const temporary = `${this.#path}.tmp`
      await writeFile(temporary, JSON.stringify(this.#data, null, 2), 'utf8')
      await rename(temporary, this.#path)
    })
    return this.#writing
  }
}
