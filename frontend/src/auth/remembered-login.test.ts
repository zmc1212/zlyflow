import { webcrypto } from "node:crypto"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { clearRememberedLogin, loadRememberedLogin, saveRememberedLogin } from "./remembered-login"

const PAYLOAD_KEY = "zly-ai-video-studio.remembered-login"
const DEVICE_KEY = "zly-ai-video-studio.remembered-login.key"

function memoryStorage() {
  const entries = new Map<string, string>()
  const store = {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => { entries.set(key, String(value)) },
    removeItem: (key: string) => { entries.delete(key) },
    clear: () => entries.clear(),
    key: (index: number) => [...entries.keys()][index] ?? null,
    get length() { return entries.size },
    entries,
  }
  return store
}

let store: ReturnType<typeof memoryStorage>

beforeEach(() => {
  store = memoryStorage()
  vi.stubGlobal("localStorage", store)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function readPayload() {
  return JSON.parse(store.getItem(PAYLOAD_KEY) ?? "null") as {
    version: number; username: string; scheme: string; iv: string; data: string
  } | null
}

function withoutSubtle() {
  vi.stubGlobal("crypto", { getRandomValues: (bytes: Uint8Array) => webcrypto.getRandomValues(bytes) })
}

describe("remembered login storage", () => {
  it("returns null before anything is saved", async () => {
    expect(await loadRememberedLogin()).toBeNull()
    expect(store.length).toBe(0)
  })

  it("round-trips credentials without leaving the password in plaintext", async () => {
    expect(await saveRememberedLogin({ username: "zlyadmin", password: "qlxing.1" })).toBe(true)
    expect(await loadRememberedLogin()).toEqual({ username: "zlyadmin", password: "qlxing.1" })

    const serialized = [...store.entries.values()].join("|")
    expect(serialized).not.toContain("qlxing.1")
    expect(readPayload()).toMatchObject({ version: 1, username: "zlyadmin", scheme: "aes-gcm" })
    expect(store.getItem(DEVICE_KEY)).toBeTruthy()
  })

  it("encrypts the same password differently on each save", async () => {
    await saveRememberedLogin({ username: "worker", password: "password123456" })
    const first = readPayload()
    await saveRememberedLogin({ username: "worker", password: "password123456" })
    const second = readPayload()
    expect(first?.iv).not.toBe(second?.iv)
    expect(first?.data).not.toBe(second?.data)
    expect(await loadRememberedLogin()).toEqual({ username: "worker", password: "password123456" })
  })

  it("keeps unicode passwords intact and trims the account", async () => {
    await saveRememberedLogin({ username: "  邮箱@例子.com  ", password: "密码·🎬123" })
    expect(await loadRememberedLogin()).toEqual({ username: "邮箱@例子.com", password: "密码·🎬123" })
  })

  it("refuses to save an empty account or password", async () => {
    expect(await saveRememberedLogin({ username: "   ", password: "secret" })).toBe(false)
    expect(await saveRememberedLogin({ username: "worker", password: "" })).toBe(false)
    expect(store.length).toBe(0)
  })

  it("clears the payload together with the device key", async () => {
    await saveRememberedLogin({ username: "worker", password: "password123456" })
    clearRememberedLogin()
    expect(store.length).toBe(0)
    expect(await loadRememberedLogin()).toBeNull()
  })

  it("replaces previously remembered credentials instead of accumulating them", async () => {
    await saveRememberedLogin({ username: "first", password: "password-one" })
    await saveRememberedLogin({ username: "second", password: "password-two" })
    expect(await loadRememberedLogin()).toEqual({ username: "second", password: "password-two" })
  })
})

describe("remembered login corruption and tampering", () => {
  it("drops malformed JSON and unknown payload versions", async () => {
    for (const raw of ["not json", "{}", JSON.stringify({ version: 2, username: "worker", scheme: "aes-gcm", iv: "x", data: "y" })]) {
      store.setItem(PAYLOAD_KEY, raw)
      expect(await loadRememberedLogin()).toBeNull()
      expect(store.getItem(PAYLOAD_KEY)).toBeNull()
    }
  })

  it("drops ciphertext that fails the AES-GCM integrity check", async () => {
    await saveRememberedLogin({ username: "worker", password: "password123456" })
    const payload = readPayload()!
    const bytes = Uint8Array.from(atob(payload.data), (character) => character.charCodeAt(0))
    bytes[0] ^= 0xff
    payload.data = btoa(String.fromCharCode(...bytes))
    store.setItem(PAYLOAD_KEY, JSON.stringify(payload))

    expect(await loadRememberedLogin()).toBeNull()
    expect(store.length).toBe(0)
  })

  it("drops credentials whose device key is missing or malformed", async () => {
    await saveRememberedLogin({ username: "worker", password: "password123456" })
    store.removeItem(DEVICE_KEY)
    expect(await loadRememberedLogin()).toBeNull()

    await saveRememberedLogin({ username: "worker", password: "password123456" })
    store.setItem(DEVICE_KEY, "too-short")
    expect(await loadRememberedLogin()).toBeNull()
    expect(store.length).toBe(0)
  })
})

describe("remembered login on insecure origins", () => {
  it("still remembers credentials when crypto.subtle is unavailable", async () => {
    withoutSubtle()
    expect(await saveRememberedLogin({ username: "zlyadmin", password: "qlxing.1" })).toBe(true)
    expect(readPayload()?.scheme).toBe("obfuscated")
    expect([...store.entries.values()].join("|")).not.toContain("qlxing.1")
    expect(await loadRememberedLogin()).toEqual({ username: "zlyadmin", password: "qlxing.1" })
  })

  it("does not return garbage when an encrypted payload outlives crypto.subtle", async () => {
    await saveRememberedLogin({ username: "worker", password: "password123456" })
    withoutSubtle()
    expect(await loadRememberedLogin()).toBeNull()
    expect(store.length).toBe(0)
  })
})

describe("remembered login without browser storage", () => {
  it("degrades to a no-op when localStorage is missing", async () => {
    vi.stubGlobal("localStorage", undefined)
    expect(await loadRememberedLogin()).toBeNull()
    expect(await saveRememberedLogin({ username: "worker", password: "password123456" })).toBe(false)
    expect(() => clearRememberedLogin()).not.toThrow()
  })

  it("degrades to a no-op when storage access throws", async () => {
    vi.stubGlobal("localStorage", {
      getItem: () => { throw new Error("SecurityError") },
      setItem: () => { throw new Error("SecurityError") },
      removeItem: () => { throw new Error("SecurityError") },
    })
    expect(await loadRememberedLogin()).toBeNull()
    expect(await saveRememberedLogin({ username: "worker", password: "password123456" })).toBe(false)
    expect(() => clearRememberedLogin()).not.toThrow()
  })

  it("reports failure instead of throwing when the storage quota is exceeded", async () => {
    store.setItem = () => { throw new Error("QuotaExceededError") }
    expect(await saveRememberedLogin({ username: "worker", password: "password123456" })).toBe(false)
  })
})