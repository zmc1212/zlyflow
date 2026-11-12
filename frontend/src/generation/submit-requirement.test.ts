import { describe, expect, it } from "vitest"
import { referenceRequirementHint, submitBlockReason, type SubmitRequirementInput } from "./submit-requirement"

const base: SubmitRequirementInput = {
  referenceMode: "collection",
  minReferences: 1,
  maxReferences: 9,
  referenceCount: 0,
  imageCount: 0,
  hasAudioReference: false,
  hasVideoReference: false,
  prompt: "444444",
}

describe("generation submit requirement", () => {
  it("asks for the missing reference image instead of offering the shortcut", () => {
    expect(referenceRequirementHint(base)).toBe("还需上传 1 张参考图（至少 1 张），才能开始生成")
    expect(submitBlockReason(base)).toBe("还需上传 1 张参考图（至少 1 张），才能开始生成")
    expect(submitBlockReason({ ...base, referenceCount: 1, imageCount: 1 })).toBe("")
  })

  it("requires the first keyframe for keyframe workflows", () => {
    expect(submitBlockReason({ ...base, referenceMode: "keyframes", minReferences: 1, maxReferences: 2 }))
      .toBe("首帧为必填，上传后即可开始生成")
  })

  it("names the missing portrait and audio for avatar workflows", () => {
    const avatar = { ...base, referenceMode: "collection" as const, minReferences: 2, maxReferences: 2, acceptsAudioReference: true }
    expect(referenceRequirementHint(avatar)).toBe("先上传人物形象图，才能开始生成")
    expect(referenceRequirementHint({ ...avatar, referenceCount: 1, imageCount: 1 }))
      .toBe("先上传口播音频（5 秒以内），才能开始生成")
  })

  it("names the missing character and motion video", () => {
    const motion = { ...base, referenceMode: "collection" as const, minReferences: 2, maxReferences: 2, acceptsVideoReference: true }
    expect(referenceRequirementHint(motion)).toBe("先上传角色形象图和动作参考视频，才能开始生成")
    expect(referenceRequirementHint({ ...motion, referenceCount: 1, imageCount: 1 }))
      .toBe("先上传动作参考视频，才能开始生成")
    expect(submitBlockReason({ ...motion, referenceCount: 2, imageCount: 1, hasVideoReference: true })).toBe("")
  })

  it("asks for the prompt only when references are complete", () => {
    expect(submitBlockReason({ ...base, prompt: "   ", referenceCount: 1, imageCount: 1 }))
      .toBe("写一句创作提示词后即可开始生成")
    expect(submitBlockReason({ ...base, prompt: "", defaultPrompt: "默认迁移提示词", referenceCount: 1, imageCount: 1 })).toBe("")
  })

  it("keeps unavailable, overflow and validation errors explicit", () => {
    expect(submitBlockReason({ ...base, available: false, unavailableReason: "远端 ComfyUI 未连接" }))
      .toBe("远端 ComfyUI 未连接")
    expect(submitBlockReason({ ...base, referenceCount: 10, imageCount: 10 }))
      .toBe("参考图最多 9 张，请先移除多余图片")
    expect(submitBlockReason({ ...base, referenceCount: 1, imageCount: 1, optionError: "二采画幅超出预算" }))
      .toBe("二采画幅超出预算")
    expect(submitBlockReason({ ...base, referenceCount: 1, imageCount: 1, pending: true })).toBe("正在提交…")
  })
})
