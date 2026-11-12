import { describe, expect, it } from "vitest"
import {
  MOTION_REF_VIDEO_WORKFLOW,
  MOTION_TOOL_WORKFLOWS,
  MOTION_TRANSFER_WORKFLOW,
  motionImageLimit,
  motionDurationError,
  motionReferenceError,
  motionToolDefaults,
  motionToolOptions,
  motionToolPayload,
  motionToolSubmitBlockReason,
  REFERENCE_MAX_BYTES,
  hasSubject,
  hasSubjects,
  subjectPointAt,
} from "./motion-transfer"

describe("motion transfer reference roles", () => {
  it("maps visible image clicks without letterbox padding and requires a positive subject", () => {
    const rect = { left: 100, top: 50, width: 200, height: 400 }
    expect(subjectPointAt(160, 210, rect)).toEqual({ x: 0.3, y: 0.4, exclude: false })
    expect(subjectPointAt(90, 210, rect)).toBeNull()
    expect(subjectPointAt(160, 210, { ...rect, width: 0 })).toBeNull()
    expect(hasSubject([])).toBe(false)
    expect(hasSubject([{ x: 0.3, y: 0.4, exclude: true }])).toBe(false)
    expect(hasSubject([{ x: 0.3, y: 0.4, exclude: false }])).toBe(true)
  })
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
    expect(motionDurationError(15.116, "full", {min_source_seconds:1,max_source_seconds:30})).toBe("")
    expect(motionDurationError(31, "full", {max_source_seconds:30})).toContain("30")
    expect(hasSubjects([{x:.3,y:.4,exclude:false,subject:0}],2)).toBe(false)
    expect(hasSubjects([{x:.3,y:.4,exclude:false,subject:0},{x:.8,y:.5,exclude:false,subject:1}],2)).toBe(true)
    expect(motionDurationError(undefined, "5s")).toBe("")
  })

  it("explains why the submit button is disabled", () => {
    const base = {
      mode: MOTION_TRANSFER_WORKFLOW,
      imageCount: 1,
      hasVideo: true,
      workflowLoaded: true,
      subjectsReady: true,
      durationError: "",
      submitting: false,
      restoring: false,
    }
    expect(motionToolSubmitBlockReason(base)).toBe("")
    expect(motionToolSubmitBlockReason({ ...base, imageCount: 0 })).toBe("先上传角色形象图，才能开始生成")
    expect(motionToolSubmitBlockReason({ ...base, mode: MOTION_REF_VIDEO_WORKFLOW, imageCount: 0 }))
      .toBe("先添加角色形象图（至少 1 张），才能开始生成")
    expect(motionToolSubmitBlockReason({ ...base, hasVideo: false })).toBe("先上传动作参考视频，才能开始生成")
    expect(motionToolSubmitBlockReason({ ...base, durationError: "动作视频只有 3.0 秒，请选择更短的生成时长或更换视频" }))
      .toBe("动作视频只有 3.0 秒，请选择更短的生成时长或更换视频")
    expect(motionToolSubmitBlockReason({ ...base, subjectsReady: false })).toBe("先按编号选定形象图和视频中的人物，才能开始生成")
    expect(motionToolSubmitBlockReason({ ...base, restoring: true })).toBe("正在恢复素材…")
    expect(motionToolSubmitBlockReason({ ...base, submitting: true })).toBe("正在提交…")
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

  it("declares the three coexisting motion transfer methods for the tool page", () => {
    expect(MOTION_TOOL_WORKFLOWS).toEqual(["scail2-replacement", "minimax-h3-motion-transfer", MOTION_REF_VIDEO_WORKFLOW])
  })

  it("derives the character image limit from declared reference slots", () => {
    expect(motionImageLimit(null)).toBe(0)
    expect(motionImageLimit({ accepts_video_reference: false })).toBe(0)
    // 骨架/SCAIL 版未声明 slots：固定 1 图。
    expect(motionImageLimit({ accepts_video_reference: true })).toBe(1)
    expect(motionImageLimit({ accepts_video_reference: true, reference_slots: ["image", "video"] })).toBe(1)
    // 多人版声明 image×6 + video 尾槽。
    expect(motionImageLimit({ accepts_video_reference: true, reference_slots: ["image", "image", "image", "image", "image", "image", "video"] })).toBe(6)
    // 声明槽位中无图片槽时按 1 图兜底（调用方仅限动作迁移族）。
    expect(motionImageLimit({ accepts_video_reference: true, reference_slots: ["video"] })).toBe(1)
  })
})
