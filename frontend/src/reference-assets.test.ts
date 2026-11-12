import { describe, expect, it } from "vitest"
import { fileFromReferenceBlob, roundReferenceSources, sniffImageKind, sniffMediaKind } from "./reference-assets"

const PNG_HEADER = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0, 0, 0, 0, 0])
const JPEG_HEADER = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
const MP4_HEADER = new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109, 0, 0, 0, 0])
const WAV_HEADER = new Uint8Array([0x52, 0x49, 0x46, 0x46, 0x24, 0x00, 0x00, 0x00, 0x57, 0x41, 0x56, 0x45, 0, 0, 0, 0])
const FLAC_HEADER = new Uint8Array([0x66, 0x4c, 0x61, 0x43, 0, 0, 0, 34, 0, 0, 0, 0, 0, 0, 0, 0])

describe("sniffImageKind", () => {
  it("recognizes PNG and JPEG by magic bytes even when the server type is octet-stream", () => {
    expect(sniffImageKind(PNG_HEADER, "application/octet-stream")).toEqual({ mime: "image/png", ext: "png" })
    expect(sniffImageKind(JPEG_HEADER, "")).toEqual({ mime: "image/jpeg", ext: "jpg" })
  })

  it("falls back to a declared image MIME when bytes are unknown", () => {
    expect(sniffImageKind(new Uint8Array(16), "image/webp")).toEqual({ mime: "image/webp", ext: "webp" })
    expect(sniffImageKind(new Uint8Array(16), "image/heic")).toEqual({ mime: "image/heic", ext: "heic" })
    expect(sniffImageKind(new Uint8Array(16), "application/octet-stream")).toBeUndefined()
  })
})

describe("roundReferenceSources", () => {
  it("keeps the round preview URLs in upload order", () => {
    expect(roundReferenceSources(
      { id: "job-1", references: [] },
      {
        id: "round-1",
        reference_count: 2,
        references: [
          { index: 2, url: "/api/jobs/job-1/rounds/round-1/references/2" },
          { index: 1, url: "/api/jobs/job-1/rounds/round-1/references/1" },
        ],
      },
    )).toEqual([
      { index: 1, url: "/api/jobs/job-1/rounds/round-1/references/1" },
      { index: 2, url: "/api/jobs/job-1/rounds/round-1/references/2" },
    ])
  })

  it("rebuilds round URLs when the API only returned a count", () => {
    expect(roundReferenceSources(
      { id: "job-1", references: [] },
      { id: "round-9", reference_count: 2, references: [] },
    )).toEqual([
      { index: 1, url: "/api/jobs/job-1/rounds/round-9/references/1" },
      { index: 2, url: "/api/jobs/job-1/rounds/round-9/references/2" },
    ])
  })

  it("falls back to job-level URLs for legacy rounds and empty round payloads", () => {
    expect(roundReferenceSources(
      { id: "job-1", references: [{ index: 1, url: "/api/jobs/job-1/references/1" }] },
      { id: "job-1:legacy-round", reference_count: 1, references: [] },
    )).toEqual([{ index: 1, url: "/api/jobs/job-1/references/1" }])
    expect(roundReferenceSources(
      { id: "job-1", references: [{ index: 1, url: "/api/jobs/job-1/references/1" }] },
      { id: "round-1", reference_count: 0, references: [] },
    )).toEqual([{ index: 1, url: "/api/jobs/job-1/references/1" }])
  })
})

describe("fileFromReferenceBlob", () => {
  it("rewrites octet-stream PNG blobs into image files that pass the composer filter", async () => {
    const blob = new Blob([PNG_HEADER], { type: "application/octet-stream" })
    const file = await fileFromReferenceBlob(blob, 2, blob.type)
    expect(file.type).toBe("image/png")
    expect(file.name).toBe("reference-2.png")
    expect(file.type.startsWith("image/")).toBe(true)
  })

  it("restores a motion video from its declared media role, not as an image", async () => {
    const header = new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109])
    const file = await fileFromReferenceBlob(new Blob([header]), 2, "application/octet-stream", "video")
    expect(file.type).toBe("video/mp4")
    expect(file.name).toBe("reference-2.mp4")
    await expect(fileFromReferenceBlob(new Blob([header]), 2, "application/octet-stream")).rejects.toThrow("图片")
  })

  it("does not accept image bytes as a restored motion video", async () => {
    await expect(fileFromReferenceBlob(new Blob([PNG_HEADER]), 2, "image/png", "video")).rejects.toThrow("视频")
  })
})

describe("media reference slots (音频或视频通用槽位)", () => {
  it("resolves audio and video from magic bytes when the API only says media", () => {
    expect(sniffMediaKind(MP4_HEADER, "application/octet-stream")).toEqual({ kind: "video", mime: "video/mp4", ext: "mp4" })
    expect(sniffMediaKind(WAV_HEADER, "application/octet-stream")).toEqual({ kind: "audio", mime: "audio/wav", ext: "wav" })
    expect(sniffMediaKind(FLAC_HEADER, "")).toEqual({ kind: "audio", mime: "audio/flac", ext: "flac" })
  })

  it("trusts a declared audio/video MIME before falling back to magic bytes", () => {
    expect(sniffMediaKind(new Uint8Array(16), "audio/mpeg")).toEqual({ kind: "audio", mime: "audio/mpeg", ext: "mp3" })
    expect(sniffMediaKind(PNG_HEADER, "video/quicktime")).toEqual({ kind: "video", mime: "video/quicktime", ext: "mov" })
    expect(sniffMediaKind(PNG_HEADER, "image/png")).toBeUndefined()
  })

  it("restores a stem-split audio reference as a playable audio file", async () => {
    const file = await fileFromReferenceBlob(new Blob([WAV_HEADER]), 1, "application/octet-stream", "media")
    expect(file.type).toBe("audio/wav")
    expect(file.name).toBe("reference-1.wav")
  })

  it("restores a stem-split video reference as a video file", async () => {
    const file = await fileFromReferenceBlob(new Blob([MP4_HEADER]), 1, "application/octet-stream", "media")
    expect(file.type).toBe("video/mp4")
    expect(file.name).toBe("reference-1.mp4")
  })

  it("reports an unreadable media reference instead of guessing", async () => {
    await expect(fileFromReferenceBlob(new Blob([new Uint8Array(16)]), 1, "application/octet-stream", "media"))
      .rejects.toThrow("音频或视频")
  })
})
