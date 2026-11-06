import { describe, expect, it } from "vitest"
import {
  ACTION_SHOT_MAX_BYTES,
  actionShotPictureToken,
  actionShotPromptTemplate,
  actionShotReferenceError,
  insertActionShotPicture,
  missingActionShotPicture,
} from "./action-shot"

function fakeFile(patch: Partial<Pick<File, "name" | "type" | "size">> = {}) {
  return { name: "hero.png", type: "image/png", size: 1024, ...patch }
}

describe("action-shot", () => {
  it("numbers <Picture n> from the upload order", () => {
    expect(actionShotPictureToken(0)).toBe("<Picture 1>")
    expect(actionShotPictureToken(8)).toBe("<Picture 9>")
  })

  it("inserts a picture token at the caret with padded spaces", () => {
    expect(insertActionShotPicture("", 0)).toEqual({ prompt: "<Picture 1>", cursor: 11 })
    expect(insertActionShotPicture("角色", 1, 2)).toEqual({ prompt: "角色 <Picture 2>", cursor: 14 })
    expect(insertActionShotPicture("与对手", 0, 0)).toEqual({ prompt: "<Picture 1> 与对手", cursor: 12 })
    // 越界光标收敛到末尾，避免把 token 插到不存在的偏移。
    expect(insertActionShotPicture("abc", 2, 99).prompt).toBe("abc <Picture 3>")
  })

  it("requires the prompt to reference an uploaded picture", () => {
    expect(missingActionShotPicture("", 0)).toBe("请先添加至少 1 张参考图")
    expect(missingActionShotPicture("两人对打", 2)).toBe("提示词里需要引用参考图，例如 <Picture 1>")
    expect(missingActionShotPicture("<Picture 2> 侧身反击", 2)).toBe("")
    // 引用了不存在的编号仍然算未引用。
    expect(missingActionShotPicture("<Picture 5> 侧身反击", 2)).toBe("提示词里需要引用参考图，例如 <Picture 1>")
  })

  it("builds a template that matches the reference count", () => {
    const single = actionShotPromptTemplate(0)
    expect(single.startsWith("<Picture 1> 中的角色独自练习连招")).toBe(true)
    expect(single).not.toContain("<Picture 2>")

    const duel = actionShotPromptTemplate(2)
    expect(duel).toContain("<Picture 1> 与 <Picture 2> 近身格斗")
    expect(duel).not.toContain("<Picture 3>")

    const staged = actionShotPromptTemplate(3)
    expect(staged).toContain("场景与光线参考 <Picture 3>")
    expect(missingActionShotPicture(staged, 3)).toBe("")
  })

  it("rejects oversized or non-image references", () => {
    expect(actionShotReferenceError(fakeFile(), 0)).toBe("")
    expect(actionShotReferenceError(fakeFile({ name: "hero.webp", type: "image/webp" }), 1)).toBe("")
    expect(actionShotReferenceError(fakeFile({ size: ACTION_SHOT_MAX_BYTES + 1 }), 0)).toBe("参考图 1 不能超过 50 MB")
    expect(actionShotReferenceError(fakeFile({ size: 0 }), 0)).toBe("参考图 1 不能为空文件")
    expect(actionShotReferenceError(fakeFile({ name: "clip.mp4", type: "video/mp4" }), 2)).toBe("参考图 3 必须是 PNG / JPG / WebP 图片")
  })
})
