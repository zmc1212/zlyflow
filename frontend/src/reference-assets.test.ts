import { describe, expect, it } from "vitest"
import { fileFromReferenceBlob, roundReferenceSources, sniffImageKind } from "./reference-assets"

const PNG_HEADER = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0, 0, 0, 0, 0])
const JPEG_HEADER = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])

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
})
