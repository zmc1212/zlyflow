import { describe, expect, it } from "vitest"
import { createHomeDrafts, homeDiagnosisPayload, homeProjectExtra, homeProjectMessage, homeProjectRequest, homeTextLimit, novelSource } from "./home-creation"

const options = { style: "都市写实", aspectRatio: "9:16", episodeCount: 3 }

describe("home creation entry semantics", () => {
  it("keeps independent drafts when moving between ideas, originals and diagnosis", () => {
    const drafts = createHomeDrafts()
    drafts.create.text = "一个故事想法"
    drafts.novel.text = "原作的第一章"
    drafts.novel.requirements = "改成悬疑短剧"
    expect(drafts.create.text).toBe("一个故事想法")
    expect(drafts.import.text).toBe("")
    expect(drafts.diagnose.text).toBe("")
    expect(createHomeDrafts().novel.text).toBe("")
  })

  it("imports a script directly but never interprets an uploaded creative reference as an import", () => {
    const draft = { ...createHomeDrafts().import, text: " 剧本正文 ", filename: "剧本.docx" }
    expect(homeProjectRequest("import", draft, options).filename).toBe("剧本")
    expect(homeProjectRequest("import", draft, options).text).toBe(draft.text)
    expect(homeProjectRequest("create", draft, options).filename).toBeUndefined()
    expect(homeProjectRequest("create", draft, options).adaptation).toBeUndefined()
  })

  it("stores a novel verbatim separately from the generated script and adaptation instructions", () => {
    const original = "\n第一章\n　雨还没停。\n\n"
    const draft = { ...createHomeDrafts().novel, text: original, filename: "雨夜.txt", requirements: " 保留结尾反转 " }
    const request = homeProjectRequest("novel", draft, options)
    expect(request.filename).toBeUndefined()
    expect(request.adaptation).toEqual({ sourceName: "雨夜", requirements: "保留结尾反转" })
    const saved = novelSource(homeProjectExtra(request))
    expect(saved).toEqual({ kind: "novel", name: "雨夜", text: original })
    expect(homeProjectMessage(request)).toContain(original)
    expect(homeProjectMessage(request)).toContain("保留结尾反转")
    expect(homeProjectMessage(request)).toContain("不覆盖原作")
  })

  it("leaves enough room for adaptation instructions within the assistant's 50,000 character contract", () => {
    const draft = { ...createHomeDrafts().novel, text: "文".repeat(homeTextLimit("novel")), requirements: "要".repeat(1000) }
    expect(homeProjectMessage(homeProjectRequest("novel", draft, options)).length).toBeLessThanOrEqual(50_000)
    expect(homeTextLimit("diagnose", 120_000)).toBe(120_000)
    expect(homeTextLimit("import")).toBe(500_000)
  })

  it("sends diagnosis text without project or document writes and preserves its original whitespace", () => {
    const draft = { ...createHomeDrafts().diagnose, text: "\n原文  \n", filename: "待审阅剧本.pdf" }
    expect(homeDiagnosisPayload(draft)).toEqual({ title: "待审阅剧本", sources: [{ name: "待审阅剧本", text: draft.text }] })
  })

  it("ignores malformed and unrelated source metadata on existing projects", () => {
    expect(novelSource({ source_material: "legacy" })).toBeNull()
    expect(novelSource({ source_material: { kind: "novel", name: "标题" } })).toBeNull()
    expect(novelSource(homeProjectExtra(homeProjectRequest("create", createHomeDrafts().create, options)))).toBeNull()
  })
})
