import { notifyUnauthorized } from "./api"

export type ReferenceSource = {
  index: number
  url: string
  kind?: "image" | "video" | "audio"
  label?: string | null
}

const IMAGE_KIND_BY_MIME: Record<string, { mime: string; ext: string }> = {
  "image/png": { mime: "image/png", ext: "png" },
  "image/jpeg": { mime: "image/jpeg", ext: "jpg" },
  "image/jpg": { mime: "image/jpeg", ext: "jpg" },
  "image/webp": { mime: "image/webp", ext: "webp" },
  "image/gif": { mime: "image/gif", ext: "gif" },
  "image/bmp": { mime: "image/bmp", ext: "bmp" },
  "image/avif": { mime: "image/avif", ext: "avif" },
}

function headerStartsWith(header: Uint8Array, signature: number[]) {
  return signature.length <= header.length && signature.every((byte, index) => header[index] === byte)
}

export function sniffImageKind(header: Uint8Array, declaredType = ""): { mime: string; ext: string } | undefined {
  if (headerStartsWith(header, [0x89, 0x50, 0x4e, 0x47])) return IMAGE_KIND_BY_MIME["image/png"]
  if (headerStartsWith(header, [0xff, 0xd8, 0xff])) return IMAGE_KIND_BY_MIME["image/jpeg"]
  if (headerStartsWith(header, [0x47, 0x49, 0x46])) return IMAGE_KIND_BY_MIME["image/gif"]
  if (
    headerStartsWith(header, [0x52, 0x49, 0x46, 0x46])
    && header.length >= 12
    && header[8] === 0x57 && header[9] === 0x45 && header[10] === 0x42 && header[11] === 0x50
  ) {
    return IMAGE_KIND_BY_MIME["image/webp"]
  }
  if (headerStartsWith(header, [0x42, 0x4d])) return IMAGE_KIND_BY_MIME["image/bmp"]
  const declared = declaredType.toLowerCase().split(";")[0].trim()
  if (IMAGE_KIND_BY_MIME[declared]) return IMAGE_KIND_BY_MIME[declared]
  if (declared.startsWith("image/") && declared !== "image/*") {
    const subtype = declared.slice("image/".length).replace("jpeg", "jpg")
    return { mime: declared, ext: subtype.split("+")[0] || "png" }
  }
  return undefined
}

export function roundReferenceSources(
  job: { id: string; references: ReferenceSource[] },
  round: { id: string; reference_count: number; references: ReferenceSource[] },
): ReferenceSource[] {
  const listed = [...round.references].sort((left, right) => left.index - right.index)
  if (listed.length > 0) return listed
  const count = Math.max(0, Math.floor(round.reference_count || 0))
  if (count > 0) {
    const legacy = round.id.endsWith(":legacy-round")
    return Array.from({ length: count }, (_, offset) => {
      const index = offset + 1
      const url = legacy
        ? `/api/jobs/${encodeURIComponent(job.id)}/references/${index}`
        : `/api/jobs/${encodeURIComponent(job.id)}/rounds/${encodeURIComponent(round.id)}/references/${index}`
      return { index, url }
    })
  }
  return [...job.references].sort((left, right) => left.index - right.index)
}

export async function fileFromReferenceBlob(
  blob: Blob, index: number, declaredType = "", expectedKind: "image" | "video" | "audio" = "image",
): Promise<File> {
  const header = new Uint8Array(await blob.slice(0, 16).arrayBuffer())
  if (expectedKind !== "image") {
    const declared = (declaredType || blob.type).split(";")[0].trim().toLowerCase()
    const mediaTypes: Record<string, string> = {
      "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm", "video/x-matroska": "mkv",
      "video/x-msvideo": "avi", "video/x-m4v": "m4v",
      "audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp4": "m4a",
      "audio/ogg": "ogg", "audio/flac": "flac", "audio/aac": "aac",
    }
    let mime = declared.startsWith(`${expectedKind}/`) && mediaTypes[declared] ? declared : ""
    if (!mime && expectedKind === "video" && String.fromCharCode(...header.slice(4, 8)) === "ftyp") mime = "video/mp4"
    if (!mime && expectedKind === "video" && headerStartsWith(header, [0x1a, 0x45, 0xdf, 0xa3])) mime = "video/webm"
    if (!mime) throw new Error(`参考素材 ${index} 不是可识别的${expectedKind === "video" ? "视频" : "音频"}`)
    return new File([blob], `reference-${index}.${mediaTypes[mime]}`, { type: mime, lastModified: Date.now() })
  }
  const kind = sniffImageKind(header, declaredType || blob.type)
  if (!kind) throw new Error(`参考图 ${index} 不是可识别的图片`)
  return new File([blob], `reference-${index}.${kind.ext}`, { type: kind.mime, lastModified: Date.now() })
}

export async function restoreReferenceFiles(sources: ReferenceSource[]): Promise<File[]> {
  return Promise.all(sources.map(async (reference) => {
    const response = await fetch(reference.url, { credentials: "include" })
    if (response.status === 401) notifyUnauthorized()
    if (!response.ok) throw new Error(`参考图 ${reference.index} 无法读取`)
    const blob = await response.blob()
    return fileFromReferenceBlob(blob, reference.index, blob.type || response.headers.get("content-type") || "", reference.kind)
  }))
}
