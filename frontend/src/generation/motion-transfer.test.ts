import { describe, expect, it } from "vitest"
import {
  motionDurationError,
  motionReferenceError,
  motionToolDefaults,
  motionToolOptions,
  motionToolPayload,
  REFERENCE_MAX_BYTES,
} from "./motion-transfer"

describe("motion transfer reference roles", () => {
  const image = { name: "character.png", type: "image/png", size: 500 }
  const video = { name: "dance.mp4", type: "video/mp4", size: 2000 }

  it("requires exactly the right media kind in each slot", () => {
    expect(motionReferenceError(image, "image")).toBe("")
    expect(motionReferenceError(video, "video")).toBe("")
    expect(motionReferenceError(image, "video")).toContain("视频")
    expect(motionReferenceError(video, "image")).toContain("图片")
    expect(motionReferenceError({ ...video, type: "application/octet-stream" }, "video")).toBe("")
    expect(motionReferenceError({ ...video, name: "payload.exe" }, "video")).toContain("视频")
  })

  it("rejects empty and oversized uploads before submission", () => {
    expect(motionReferenceError({ ...video, size: 0 }, "video")).toContain("空")
    expect(motionReferenceError({ ...video, size: REFERENCE_MAX_BYTES + 1 }, "video")).toContain("50 MB")
    expect(motionReferenceError({ ...image, size: REFERENCE_MAX_BYTES + 1 }, "image")).toContain("50 MB")
  })

  it("checks nominal duration and tolerates harmless container rounding", () => {
    expect(motionDurationError(5, "5s")).toBe("")
    expect(motionDurationError(4.98, "5s")).toBe("")
    expect(motionDurationError(5.17, "10s")).toContain("更短")
    expect(motionDurationError(15, "15s")).toBe("")
    expect(motionDurationError(undefined, "5s")).toBe("")
  })
})

describe("motion tool page schema helpers", () => {
  const schema = {
    control_strength: {
      label: "动作跟随强度", type: "number" as const, default: 1.0, ui_group: "primary" as const,
      minimum: 0.1, maximum: 1.0, step: 0.05,
    },
    aspect_ratio: {
      label: "画面比例", type: "string" as const, default: "16:9", ui_group: "primary" as const,
      enum: ["16:9", "9:16", "1:1"],
    },
    duration: {
      label: "生成时长", type: "string" as const, default: "5s", ui_group: "primary" as const,
      enum: ["5s", "10s", "15s"],
    },
    render_quality: {
      label: "生成质量", type: "string" as const, default: "standard", ui_group: "advanced" as const,
      enum: ["preview", "standard", "fine"],
      ui_options: [{ value: "preview", label: "快速预览" }, { value: "standard", label: "标准成片" }, { value: "fine", label: "精细成片" }],
    },
    seed: {
      label: "随机种子", type: "integer" as const, default: 0, ui_group: "advanced" as const,
      minimum: 0, maximum: 2147483647, step: 1,
    },
    width: { label: "画布宽", type: "integer" as const, default: 864, ui_group: "internal" as const },
  }

  it("derives controls from the registry without exposing internal fields", () => {
    const controls = motionToolOptions(schema)
    expect(controls.map((control) => control.name)).toEqual([
      "control_strength", "aspect_ratio", "duration", "render_quality", "seed",
    ])
    const byName = Object.fromEntries(controls.map((control) => [control.name, control]))
    expect(byName.control_strength?.control).toBe("slider")
    expect(byName.aspect_ratio?.control).toBe("select")
    expect(byName.render_quality?.options.map((option) => option.label)).toEqual(["快速预览", "标准成片", "精细成片"])
    expect(byName.seed?.control).toBe("number")
  })

  it("seeds defaults and tolerates an absent schema", () => {
    expect(motionToolDefaults(schema)).toEqual({
      control_strength: 1.0, aspect_ratio: "16:9", duration: "5s", render_quality: "standard", seed: 0,
    })
    expect(motionToolDefaults(undefined)).toEqual({})
    expect(motionToolOptions(undefined)).toEqual([])
  })

  it("keeps explicit payload values and drops empties", () => {
    expect(motionToolPayload({ seed: 7, duration: "10s", prompt: "" })).toEqual({ seed: 7, duration: "10s" })
  })
})
