import { describe, expect, it } from "vitest"
import type { Director2Asset, Director2Beat } from "./api"
import { initialPromptText, promptDocument, promptPatch, promptReferences, promptText, referenceNode, segmentAt, workshopAssets, workshopSegments } from "./workshop-editor"

const assets: Director2Asset[] = [
  { id: "a", name: "张伟", kind: "character", extra: { identities: [{ id: "a1", name: "张伟（日常）", image_url: "a.png" }] } },
  { id: "b", name: "张伟女友", kind: "character", extra: { identities: [{ id: "b1", name: "礼服", image_url: "b.png" }] } },
  { id: "s", name: "西餐厅", kind: "scene", extra: { master_url: "scene.png" } },
].map(asset => ({ project_id: "p", role: null, description: null, visual_prompt: null, image_url: null, voice_id: null, created_at: "", updated_at: "", ...asset }))
const beat = { id: "beat", sequence: 1, characters: ["张伟", "张伟女友"], character_ids: ["a", "b"], character_look_ids: { a: "a1", b: "b1" }, scene: "西餐厅", scene_id: "s", action: "张伟女友看向张伟。", dialogue: "张伟：“你好。”", camera: "近景", video_duration: "12秒" } as Director2Beat

describe("workshop prompt documents", () => {
  it("uses stable asset/look ids and longest names, keeping dialogue/camera in the editable text", () => {
    const entries = workshopAssets(assets)
    const doc = promptDocument(beat, entries)
    expect(promptText(doc)).toBe(initialPromptText(beat))
    expect(promptReferences(doc, entries).map(a => a.key)).toEqual(["s:", "a:a1", "b:b1"])
    const patch = promptPatch(doc, entries)
    expect(patch.character_ids).toEqual(["a", "b"])
    expect(patch.character_look_ids).toEqual({ a: "a1", b: "b1" })
    expect(patch.dialogue).toBe("张伟：“你好。”")
    expect(patch.camera).toBe("近景")
    expect(patch.action).not.toContain("对白：")
  })
  it("preserves a saved document instead of guessing names again, but rejects stale metadata", () => {
    const entries = workshopAssets(assets)
    const doc = promptDocument(beat, entries)
    const saved = { ...beat, workshop_prompt_document: doc, video_prompt_zh: promptText(doc) }
    expect(promptDocument(saved, entries)).toBe(doc)
    expect(promptText(promptDocument({ ...saved, video_prompt_zh: "来自新任务的正文" }, entries))).toContain("来自新任务的正文")
  })
  it("does not silently pick a costume for an ambiguous character", () => {
    const entries = workshopAssets([{ ...assets[0], extra: { identities: [{ id: "x", name: "学生" }, { id: "y", name: "成年" }] } }])
    const doc = promptDocument({ id: "b", sequence: 1, action: "张伟走来", characters: ["张伟"] }, entries)
    expect(promptReferences(doc, entries)[0]?.lookId).toBe(null)
    const conflicting = { type: "doc" as const, content: [{ type: "paragraph", content: entries.filter(a => a.lookId).map(referenceNode) }] }
    expect(() => promptPatch(conflicting, entries)).toThrow("同一造型")
  })
  it("handles an empty editor document without losing the draft", () => {
    const doc = { type: "doc" as const, content: [{ type: "paragraph" }] }
    expect(promptPatch(doc, []).video_prompt_zh).toBe("")
  })
  it("keeps linked assets that are described by a pronoun in the action", () => {
    const entries = workshopAssets(assets)
    const doc = promptDocument({ ...beat, characters: undefined, action: "她跟着他走开。" }, entries)
    expect(promptPatch(doc, entries).character_ids).toEqual(["a", "b"])
    expect(promptText(doc)).toContain("出场人物：张伟、张伟女友。")
  })
})

describe("segmented playback mapping", () => {
  const beats = [{ id: "1", sequence: 1, video_url: "one.mp4", video_duration: "12" }, { id: "2", sequence: 2, video_url: "two.mp4", video_duration: "15" }, { id: "3", sequence: 3, video_duration: "10" }] as Director2Beat[]
  it("uses measured video lengths and changes the selected script exactly at a segment boundary", () => {
    const segments = workshopSegments(beats, { "one.mp4": 12.25, "two.mp4": 15.08 })
    expect(segmentAt(segments, 12.24)?.segment.id).toBe("1")
    expect(segmentAt(segments, 12.25)).toEqual({ segment: segments[1], offset: 0 })
    expect(segmentAt(segments, 13.25)?.offset).toBe(1)
    expect(segments[2].start).toBeCloseTo(27.33)
  })
  it("preserves missing-video segments and clamps invalid/end seeks", () => {
    const segments = workshopSegments(beats)
    expect(segmentAt(segments, 30)?.segment.src).toBe("")
    expect(segmentAt(segments, -1)?.offset).toBe(0)
    expect(segmentAt(segments, 999)?.segment.id).toBe("3")
    expect(segmentAt(segments, 999)?.offset).toBe(10)
    expect(segmentAt([], 0)).toBe(null)
  })
})
