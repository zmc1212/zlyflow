import type { Director2Asset } from "./api"

export type AssetSourceReference = {
  id: string
  url: string
  filename: string
}

export const MAX_SOURCE_REFERENCES = 9
export const MAX_SOURCE_REFERENCE_BYTES = 10 * 1024 * 1024

const HINTS: Record<string, string> = {
  character: "从原片截正脸或半身，生成设定板时会按这些图锁五官、发型与服装。",
  scene: "从原片截空镜，生成主视角时会按这些图对齐空间、光线和陈设。",
  prop: "从原片截道具特写，生成概念图时会按这些图对齐外形和材质。",
}

export function sourceReferencesOf(asset: Director2Asset | null | undefined): AssetSourceReference[] {
  const extra = asset?.extra || {}
  const raw = Array.isArray(extra.source_references)
    ? extra.source_references
    : Array.isArray(extra.source_reference_urls)
      ? extra.source_reference_urls
      : []
  const items: AssetSourceReference[] = []
  const seen = new Set<string>()
  for (const entry of raw) {
    const item = asReference(entry)
    if (!item || seen.has(item.url)) continue
    seen.add(item.url)
    items.push(item)
    if (items.length >= MAX_SOURCE_REFERENCES) break
  }
  return items
}

export function hasSourceReferences(asset: Director2Asset | null | undefined): boolean {
  return sourceReferencesOf(asset).length > 0
}

export function sourceReferenceHint(kind: string): string {
  return HINTS[kind] || HINTS.prop
}

export function remainingSourceReferenceSlots(asset: Director2Asset | null | undefined): number {
  return Math.max(0, MAX_SOURCE_REFERENCES - sourceReferencesOf(asset).length)
}

export function asImageFile(file: File | { originFileObj?: File } | null | undefined): File | null {
  if (file instanceof File) return file
  if (file?.originFileObj instanceof File) return file.originFileObj
  return null
}

function asReference(raw: unknown): AssetSourceReference | null {
  if (typeof raw === "string") {
    const url = raw.trim()
    return url ? { id: url, url, filename: "" } : null
  }
  if (!raw || typeof raw !== "object") return null
  const record = raw as Record<string, unknown>
  const url = String(record.url || "").trim()
  if (!url) return null
  return {
    id: String(record.id || url).trim() || url,
    url,
    filename: String(record.filename || "").trim(),
  }
}
