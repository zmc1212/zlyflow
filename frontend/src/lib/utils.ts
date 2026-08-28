import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Local unique id. Avoids crypto.randomUUID, which is missing on HTTP LAN IPs and older browsers. */
export function createLocalId(): string {
  const cryptoObj = globalThis.crypto
  if (cryptoObj && typeof cryptoObj.randomUUID === "function") {
    return cryptoObj.randomUUID()
  }
  if (cryptoObj && typeof cryptoObj.getRandomValues === "function") {
    const bytes = cryptoObj.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export type MediaAspectSize = { width: number; height: number }

/** Parse `9:16`, `9 / 16` or `768x1344` into numeric width/height. */
export function parseMediaAspect(value?: string | number | boolean | null): MediaAspectSize | undefined {
  const match = String(value ?? "").match(/(\d+(?:\.\d+)?)\s*[:/x×]\s*(\d+(?:\.\d+)?)/i)
  if (!match) return undefined
  const width = Number(match[1])
  const height = Number(match[2])
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return undefined
  return { width, height }
}

export function mediaAspectVars(aspect?: MediaAspectSize): Record<"--media-aspect-w" | "--media-aspect-h", string> | undefined {
  if (!aspect) return undefined
  return {
    "--media-aspect-w": String(aspect.width),
    "--media-aspect-h": String(aspect.height),
  }
}
