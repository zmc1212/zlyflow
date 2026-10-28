import { describe, expect, it } from "vitest"
import { recentCreations, type HomeJob, type HomeOutput } from "./generation-home"

const output = (path: string, overrides: Partial<HomeOutput> = {}): HomeOutput => ({ kind: "video", path, label: path, ...overrides })
const job = (id: string, overrides: Partial<HomeJob> = {}): HomeJob => ({
  id, prompt: "镜头描述", media_type: "video", created_at: "2026-10-28T08:00:00Z", outputs: [output(id + ".mp4")], ...overrides,
})

describe("generation home real results", () => {
  it("chooses the latest available round and its own aspect, duration and Chinese prompt", () => {
    const source = job("a", { rounds: [
      { prompt: "old", generation_items: [{ outputs: [output("old.mp4")] }] },
      { prompt: "English prompt", display_prompt: "中文镜头", options: { aspect_ratio: "9:16", duration: 65 }, generation_items: [{ outputs: [output("new.mp4")] }] },
    ] })
    const [item] = recentCreations([source])
    expect(item.output.path).toBe("new.mp4")
    expect(item.title).toBe("中文镜头")
    expect(item.aspectRatio).toBeCloseTo(9 / 16)
    expect(item.duration).toBe("01:05")
  })

  it("keeps a previous successful result when a newer round has no output", () => {
    const [item] = recentCreations([job("a", { rounds: [
      { generation_items: [{ outputs: [output("previous.mp4")] }] },
      { generation_items: [{ outputs: [] }] },
    ] })])
    expect(item.output.path).toBe("previous.mp4")
  })

  it("skips expired or empty output without discarding other available work", () => {
    const entries = recentCreations([
      job("expired", { outputs: [output("expired.mp4", { delivery_status: "expired" })] }),
      job("empty", { outputs: [output("")] }),
      job("usable", { outputs: [output("expired.mp4", { delivery_status: "expired" }), output("ok.mp4")] }),
    ])
    expect(entries.map((entry) => entry.jobId)).toEqual(["usable"])
    expect(entries[0].output.path).toBe("ok.mp4")
  })

  it("prefers the edited task title and retains exact cloud URLs for opening media", () => {
    const url = "https://media.example/video.mp4?token=original"
    const [item] = recentCreations([job("a", { title: " 自定义标题 ", outputs: [output("a.mp4", { cloud_url: url })] })])
    expect(item.title).toBe("自定义标题")
    expect(item.src).toBe(url)
    expect(item.thumbnail).toBe(url + "&vframe/jpg/offset/1/w/640")
  })

  it("does not invent a five-second duration and does not attach durations to images", () => {
    const entries = recentCreations([
      job("video", { options: { duration: -1 } }),
      job("image", { media_type: "image", outputs: [output("image.png", { kind: "image" })], options: { duration: 10 } }),
    ])
    expect(entries.every((entry) => entry.duration === undefined)).toBe(true)
  })

  it("sorts before limiting and leaves the query cache arrays untouched", () => {
    const older = job("older", { created_at: "2026-10-26T08:00:00Z" })
    const newer = job("newer")
    const sources = [older, newer]
    expect(recentCreations(sources, 1).map((item) => item.jobId)).toEqual(["newer"])
    expect(sources).toEqual([older, newer])
    expect(recentCreations(sources, 0)).toEqual([])
  })
})
