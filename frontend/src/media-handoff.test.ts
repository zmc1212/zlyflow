import { afterEach, describe, expect, it, vi } from "vitest"
import { fetchHandoffFile, isMediaHandoffSource, mediaHandoffPath, outputDownloadUrl, readMediaHandoff, type MediaHandoffSource } from "./media-handoff"

const PNG_HEADER = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0, 0, 0, 0, 0])
const source = (overrides: Partial<MediaHandoffSource> = {}): MediaHandoffSource => ({
  jobId: "job 1", generationItemId: "item/2", outputIndex: 1, kind: "image", ...overrides,
})

function queryOf(path: string | null) {
  return new URLSearchParams((path ?? "").split("?")[1] ?? "")
}

describe("media handoff contract", () => {
  it("carries the locator and the media role in the tool URL", () => {
    expect(mediaHandoffPath("/tools/image-inpaint", source())).toBe(
      "/tools/image-inpaint?sourceJob=job+1&generation=item%2F2&output=1&kind=image",
    )
    expect(queryOf(mediaHandoffPath("/tools/x", source({ kind: "video" }))).get("kind")).toBe("video")
  })

  it("refuses to build a path from an incomplete locator", () => {
    expect(mediaHandoffPath("/tools/x", source({ jobId: "  " }))).toBeNull()
    expect(mediaHandoffPath("/tools/x", source({ generationItemId: "" }))).toBeNull()
    expect(mediaHandoffPath("/tools/x", source({ outputIndex: -1 }))).toBeNull()
    expect(mediaHandoffPath("/tools/x", source({ outputIndex: 1.5 }))).toBeNull()
    expect(mediaHandoffPath("/tools/x", { ...source(), kind: "audio" })).toBeNull()
    expect(mediaHandoffPath("/tools/x", undefined)).toBeNull()
    expect(isMediaHandoffSource(null)).toBe(false)
  })

  it("round-trips through the query string", () => {
    const path = mediaHandoffPath("/tools/photo-edit", source())
    expect(readMediaHandoff(queryOf(path))).toEqual(source())
  })

  it("treats a missing or unparsable output index as absent, not as version zero", () => {
    expect(readMediaHandoff(new URLSearchParams({ sourceJob: "a", generation: "b", kind: "image" }))).toBeNull()
    expect(readMediaHandoff(new URLSearchParams({ sourceJob: "a", generation: "b", output: "x", kind: "image" }))).toBeNull()
    expect(readMediaHandoff(new URLSearchParams({ sourceJob: "a", generation: "b", output: "0", kind: "image" }))).toMatchObject({ outputIndex: 0 })
    expect(readMediaHandoff(new URLSearchParams({ sourceJob: "a", generation: "b", output: "0" }))).toBeNull()
  })

  it("reads the file back through the same-origin output route", async () => {
    expect(outputDownloadUrl(source())).toBe("/api/jobs/job%201/generations/item%2F2/outputs/1/download")
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob([PNG_HEADER], { type: "application/octet-stream" })))
    vi.stubGlobal("fetch", fetchMock)
    const file = await fetchHandoffFile(source())
    expect(fetchMock.mock.calls[0][0]).toBe("/api/jobs/job%201/generations/item%2F2/outputs/1/download")
    expect(file.type).toBe("image/png")
    vi.unstubAllGlobals()
  })

  afterEach(() => { vi.unstubAllGlobals() })
})
