import { describe, expect, it } from "vitest"
import {
  KEYFRAME_MAX,
  KEYFRAME_MIN,
  evenAnchorSeconds,
  keyframeAnchorError,
  keyframeDurationSeconds,
  keyframeReferenceError,
  serializeKeyframeAnchors,
  type KeyframeAnchor,
} from "./keyframe"

describe("keyframe reference validation", () => {
  it("accepts images and rejects empty, oversized and non-image files", () => {
    expect(keyframeReferenceError({ type: "image/png", name: "a.png", size: 10 }, "关键帧 2")).toBe("")
    expect(keyframeReferenceError({ type: "image/png", name: "a.png", size: 0 }, "关键帧 2")).toContain("不能为空文件")
    expect(keyframeReferenceError({ type: "image/png", name: "a.png", size: 51 * 1024 * 1024 }, "关键帧 2")).toContain("50 MB")
    expect(keyframeReferenceError({ type: "video/mp4", name: "a.mp4", size: 10 }, "关键帧 2")).toContain("必须是图片文件")
  })

  it("keeps 2-4 keyframe bounds", () => {
    expect(KEYFRAME_MIN).toBe(2)
    expect(KEYFRAME_MAX).toBe(4)
  })
})

describe("keyframe anchor helpers", () => {
  it("parses duration option to nominal seconds", () => {
    expect(keyframeDurationSeconds("5s")).toBe(5)
    expect(keyframeDurationSeconds("10s")).toBe(10)
    expect(keyframeDurationSeconds(undefined)).toBe(5)
    expect(keyframeDurationSeconds("junk")).toBe(5)
  })

  it("prefills manual anchors from even distribution", () => {
    expect(evenAnchorSeconds(2, 5)).toEqual([5])
    expect(evenAnchorSeconds(3, 5)).toEqual([2.5, 5])
    expect(evenAnchorSeconds(4, 15)).toEqual([5, 10, 15])
  })

  it("validates manual anchors", () => {
    expect(keyframeAnchorError([{ seconds: 2.5, end: false }, { seconds: 5, end: true }], 5)).toBe("")
    expect(keyframeAnchorError([{ seconds: 0, end: false }], 5)).toContain("必须大于 0")
    expect(keyframeAnchorError([{ seconds: 6, end: false }], 5)).toContain("不能超过 5 秒")
    expect(keyframeAnchorError([{ seconds: 3, end: false }, { seconds: 3, end: false }], 5)).toContain("依次增大")
    expect(keyframeAnchorError([{ seconds: 4, end: false }, { seconds: 2, end: false }], 5)).toContain("依次增大")
  })

  it("serializes anchors with end flag as -1", () => {
    const anchors: KeyframeAnchor[] = [{ seconds: 2.5, end: false }, { seconds: 0, end: true }]
    expect(serializeKeyframeAnchors(anchors)).toBe("2.5,-1")
    expect(serializeKeyframeAnchors([])).toBe("")
  })
})
