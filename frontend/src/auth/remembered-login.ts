export type RememberedLogin = { username: string; password: string }

const PAYLOAD_KEY = "zly-ai-video-studio.remembered-login"
const DEVICE_KEY = "zly-ai-video-studio.remembered-login.key"
const DEVICE_KEY_BYTES = 32

type ProtectedPassword =
  | { scheme: "aes-gcm"; iv: string; data: string }
  | { scheme: "obfuscated"; iv: ""; data: string }

type StoredPayload = ProtectedPassword & { version: 1; username: string }

function storage(): Storage | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
    return null
  }
}

function subtle(): SubtleCrypto | null {
  return globalThis.crypto?.subtle ?? null
}

function randomBytes(length: number): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(new ArrayBuffer(length))
  globalThis.crypto.getRandomValues(bytes)
  return bytes
}

function toBase64(bytes: Uint8Array): string {
  let binary = ""
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

function fromBase64(value: string): Uint8Array<ArrayBuffer> {
  const binary = atob(value)
  const bytes = new Uint8Array(new ArrayBuffer(binary.length))
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes
}

function readDeviceSecret(): Uint8Array<ArrayBuffer> | null {
  const stored = storage()?.getItem(DEVICE_KEY)
  if (!stored) return null
  try {
    const bytes = fromBase64(stored)
    return bytes.length === DEVICE_KEY_BYTES ? bytes : null
  } catch {
    return null
  }
}

function ensureDeviceSecret(): Uint8Array<ArrayBuffer> {
  const existing = readDeviceSecret()
  if (existing) return existing
  const bytes = randomBytes(DEVICE_KEY_BYTES)
  storage()?.setItem(DEVICE_KEY, toBase64(bytes))
  return bytes
}

function xorBytes(input: Uint8Array, mask: Uint8Array): Uint8Array<ArrayBuffer> {
  const output = new Uint8Array(new ArrayBuffer(input.length))
  for (let index = 0; index < input.length; index += 1) output[index] = input[index] ^ mask[index % mask.length]
  return output
}

async function protectPassword(password: string): Promise<ProtectedPassword> {
  const plain = new TextEncoder().encode(password)
  const api = subtle()
  if (api) {
    const key = await api.importKey("raw", ensureDeviceSecret(), "AES-GCM", false, ["encrypt", "decrypt"])
    const iv = randomBytes(12)
    const cipher = await api.encrypt({ name: "AES-GCM", iv }, key, plain)
    return { scheme: "aes-gcm", iv: toBase64(iv), data: toBase64(new Uint8Array(cipher)) }
  }
  // 局域网 http 源不是安全上下文，crypto.subtle 不存在；退回设备密钥混淆，记住密码在局域网仍可用。
  return { scheme: "obfuscated", iv: "", data: toBase64(xorBytes(plain, ensureDeviceSecret())) }
}

async function revealPassword(payload: ProtectedPassword): Promise<string | null> {
  const secret = readDeviceSecret()
  if (!secret) return null
  const decoder = new TextDecoder("utf-8", { fatal: true })
  if (payload.scheme === "aes-gcm") {
    const api = subtle()
    if (!api) return null
    const key = await api.importKey("raw", secret, "AES-GCM", false, ["encrypt", "decrypt"])
    return decoder.decode(await api.decrypt({ name: "AES-GCM", iv: fromBase64(payload.iv) }, key, fromBase64(payload.data)))
  }
  return decoder.decode(xorBytes(fromBase64(payload.data), secret))
}

function parsePayload(raw: string): StoredPayload | null {
  const value = JSON.parse(raw) as Partial<StoredPayload> | null
  if (!value || value.version !== 1 || typeof value.username !== "string" || !value.username.trim()) return null
  if (typeof value.data !== "string" || !value.data) return null
  if (value.scheme === "aes-gcm" && typeof value.iv === "string" && value.iv) {
    return { version: 1, username: value.username, scheme: "aes-gcm", iv: value.iv, data: value.data }
  }
  if (value.scheme === "obfuscated") {
    return { version: 1, username: value.username, scheme: "obfuscated", iv: "", data: value.data }
  }
  return null
}

export async function loadRememberedLogin(): Promise<RememberedLogin | null> {
  const store = storage()
  if (!store) return null
  try {
    const raw = store.getItem(PAYLOAD_KEY)
    if (!raw) return null
    const payload = parsePayload(raw)
    const password = payload ? await revealPassword(payload) : null
    if (!payload || !password) {
      clearRememberedLogin()
      return null
    }
    return { username: payload.username, password }
  } catch {
    clearRememberedLogin()
    return null
  }
}

export async function saveRememberedLogin(value: RememberedLogin): Promise<boolean> {
  const store = storage()
  const username = value.username.trim()
  if (!store || !username || !value.password) return false
  try {
    const payload: StoredPayload = { version: 1, username, ...(await protectPassword(value.password)) }
    store.setItem(PAYLOAD_KEY, JSON.stringify(payload))
    return true
  } catch {
    return false
  }
}

export function clearRememberedLogin(): void {
  const store = storage()
  if (!store) return
  try {
    store.removeItem(PAYLOAD_KEY)
    store.removeItem(DEVICE_KEY)
  } catch {
    // 隐私模式禁止写入时本来就没有落盘的凭据。
  }
}