import { describe, expect, it } from "vitest"
import {
  blankDocument,
  duplicateClip,
  endOf,
  makeClip,
  moveClip,
  packLane,
  parseDocument,
  patchClip,
  reorderClip,
  roughCut,
  splitClip,
  timecode,
  wrapText,
  type EditAsset
} from "./model"

const source: EditAsset = {
  id: "v1",
  kind: "video",
  name: "镜头一",
  url: "https://media.example/one.mp4",
  duration: 8,
  beat_id: "b1"
}
function fixture() {
  const doc = blankDocument()
  doc.assets = [source]
  doc.clips = [makeClip(doc, source)]
  return doc
}
describe("smart editing timeline", () => {
  it("uses source time for speed changes and preserves source interval on split", () => {
    let doc = fixture()
    doc = patchClip(doc, doc.clips[0].id, { speed: 2 })
    expect(endOf(doc)).toBe(4)
    doc = splitClip(doc, doc.clips[0].id, 1.5)
    expect(
      doc.clips.map((c) => [c.start, c.duration, c.in_point, c.speed])
    ).toEqual([
      [0, 1.5, 0, 2],
      [1.5, 2.5, 3, 2]
    ])
  })
  it("aligns split points and new materials to actual frames", () => {
    let doc = fixture()
    doc.settings.fps = 30
    doc = splitClip(doc, doc.clips[0].id, 1.2345)
    for (const clip of doc.clips)
      expect(clip.start * 30).toBeCloseTo(Math.round(clip.start * 30))
    expect(doc.clips.reduce((sum, clip) => sum + clip.duration, 0)).toBeCloseTo(
      8
    )
  })
  it("prevents overlap and out-of-source edits", () => {
    let doc = fixture()
    const first = doc.clips[0].id
    doc = duplicateClip(doc, first)
    expect(() => moveClip(doc, doc.clips[1].id, 4, false)).toThrow("重叠")
    expect(() => patchClip(doc, first, { duration: 10 })).toThrow("原始素材")
    expect(() => patchClip(doc, first, { in_point: 3 })).toThrow("原始素材")
  })
  it("snaps both sides and removes gaps without changing source windows", () => {
    let doc = fixture()
    doc = duplicateClip(doc, doc.clips[0].id)
    const id = doc.clips[1].id
    doc = moveClip(doc, id, 8.1)
    expect(doc.clips[1].start).toBe(8)
    doc = moveClip(doc, id, 12, false)
    doc = packLane(doc, "video")
    expect(doc.clips[1].start).toBe(8)
    expect(doc.clips[1].in_point).toBe(0)
  })
  it("reorders clips deterministically without dropping trims", () => {
    let doc = fixture()
    doc = splitClip(doc, doc.clips[0].id, 3)
    const id = doc.clips[1].id
    doc = reorderClip(doc, id, -1)
    expect(doc.clips.find((c) => c.id === id)?.start).toBe(0)
    expect(doc.clips.find((c) => c.id === id)?.in_point).toBe(3)
    expect(endOf(doc)).toBe(8)
  })
  it("粗剪 uses the latest adopted take once per beat and lines up audio", () => {
    const doc = fixture()
    doc.assets.push(
      { ...source, id: "v2", duration: 5 },
      {
        id: "a",
        name: "旁白",
        kind: "audio",
        url: "https://media.example/a.wav",
        duration: 2,
        beat_id: "b1"
      }
    )
    const result = roughCut(doc)
    expect(result.clips.filter((c) => c.track === "video")).toHaveLength(1)
    expect(result.clips[0].asset_id).toBe("v2")
    expect(result.clips.find((c) => c.track === "audio")?.start).toBe(0)
  })
  it("round-trips full JSON and rejects corrupt imports", () => {
    const doc = fixture()
    expect(parseDocument(JSON.stringify(doc))).toEqual(doc)
    expect(() => parseDocument('{"version":2}')).toThrow("有效")
    doc.clips[0].duration = 500
    expect(() => parseDocument(JSON.stringify(doc))).toThrow("原始素材")
    doc.clips[0].duration = 8
    doc.clips[0].speed = -1
    expect(() => parseDocument(JSON.stringify(doc))).toThrow("参数")
  })
  it("opens signed local media projects and rejects raw or malformed paths", () => {
    const doc = fixture()
    doc.assets = [{ ...source, url: `/api/local-media/dGVzdA.${"a".repeat(32)}` }]
    expect(parseDocument(JSON.stringify(doc)).assets[0].url).toBe(doc.assets[0].url)
    for (const url of ["file:///G:/clips/video.mp4", "G:/clips/video.mp4", "/api/local-media/unsigned", "/api/local-media/../../secret", "/api/local-media/dGVzdA.bad"]) {
      doc.assets[0].url = url
      expect(() => parseDocument(JSON.stringify(doc))).toThrow("素材无效")
    }
  })
  it("formats frame timecodes across minute boundaries", () => {
    expect(timecode(60 + 23 / 24)).toBe("01:00:23")
    expect(timecode(59 + 24 / 25, 25)).toBe("00:59:24")
  })
  it("rejects imported timing between output frames", () => {
    const doc = fixture()
    doc.clips[0].start = 0.001
    expect(() => parseDocument(JSON.stringify(doc))).toThrow("参数")
  })
  it("wraps long captions explicitly and preserves manual line breaks", () => {
    expect(wrapText("一二三四五六七八九十\n手动换行", 192)).toBe(
      "一二三四五六七八\n九十\n手动换行"
    )
    expect(wrapText("第一行\r\n\r\n第二行", 64)).toBe("第一行\n\n第二行")
  })
})
