import { describe, expect, it, vi } from "vitest"
import { DIMENSIONS, characterCount, citationLabel, durationLabel, moveItem, reportMarkdown, sliceCharacters, type Diagnosis } from "./model"
import { cancelDiagnosis, createDiagnosis, deleteDiagnosis, extractFiles, retryDiagnosis } from "./api"

describe("script diagnosis", () => {
  it("preserves upload order and handles reorder boundaries", () => {
    expect(moveItem(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"])
    expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"])
    expect(moveItem(["a", "b"], 1, 0)).toEqual(["b", "a"])
  })
  it("uses Python code point offsets for emoji and Chinese citations", () => {
    const text = "😀序言\n母亲回头"
    expect(characterCount(text)).toBe(8)
    expect(sliceCharacters(text, 4, 8)).toBe("母亲回头")
    expect(citationLabel([{ id: "s1", name: "一.md", text }], { source_id: "s1", block_id: "s1-b1", quote: "母亲", start: 4, end: 6 }))
      .toBe("一.md · 第 2 行")
  })
  it("formats ranges and explicit durations", () => {
    expect(durationLabel({ min_seconds: 30, max_seconds: 50 })).toBe("30 秒 – 50 秒")
    expect(durationLabel({ min_seconds: 60, max_seconds: 60 })).toBe("1 分钟")
    expect(durationLabel({ min_seconds: 90, max_seconds: 90 })).toBe("1 分 30 秒")
  })
  it("exports all dimensions, evidence and advice from the stored snapshot", () => {
    const issue = { title: "人物转折", priority: "high" as const, explanation: "缺少铺垫", suggestion: "补一个迟疑动作",
      evidence: [{ source_id: "s1", block_id: "s1-b1", quote: "母亲回头", start: 0, end: 4 }] }
    const task: Diagnosis = {
      id: "d1", title: "雨夜", status: "succeeded", model: "configured", created_at: "2026-10-20T01:00:00Z",
      project_id: null, document_id: null, stage: "succeeded", completed: 1, total: 1, error: null, updated_at: "2026-10-20T01:00:00Z",
      sources: [{ id: "s1", name: "第一集.md", text: "母亲回头" }],
      report: { schema_version: 1, summary: "悬念明确", duration: { min_seconds: 60, max_seconds: 90, basis: "对白估算", episodes: [] },
        dimensions: DIMENSIONS.map(item => ({ key: item.key, conclusion: "结论", strengths: ["优点"], issues: [issue] })),
        priorities: [{ ...issue, dimension: "pacing", issue_index: 0 }] },
    }
    const markdown = reportMarkdown(task)
    DIMENSIONS.forEach(item => expect(markdown).toContain("## " + item.label))
    expect(markdown).toContain("> 母亲回头")
    expect(markdown).toContain("补一个迟疑动作")
    expect(markdown).toContain("第一集.md · 第 1 行")
    expect(markdown).not.toContain("undefined")
  })
  it("sends JSON mutations and CSRF with the correct HTTP methods", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ id: "d1" }), {
      headers: { "content-type": "application/json" },
    })))
    vi.stubGlobal("fetch", fetch)
    try {
      await createDiagnosis("csrf", { client_request_id: "request-123", sources: [] })
      expect(fetch.mock.calls[0][1]).toMatchObject({ method: "POST", headers: { "X-CSRF-Token": "csrf" } })
      expect(JSON.parse(fetch.mock.calls[0][1].body)).toHaveProperty("client_request_id", "request-123")
      await cancelDiagnosis("csrf", "d1")
      expect(fetch.mock.calls[1][1].method).toBe("POST")
      await retryDiagnosis("csrf", "d1", "retry-123")
      expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({ client_request_id: "retry-123" })
      await deleteDiagnosis("csrf", "d1")
      expect(fetch.mock.calls[3][1].method).toBe("DELETE")
      await extractFiles("csrf", [new File(["test"], "a.md")])
      expect(fetch.mock.calls[4][1].body.get("files").name).toBe("a.md")
      expect(fetch.mock.calls[4][1].headers).toEqual({ "X-CSRF-Token": "csrf" })
    } finally { vi.unstubAllGlobals() }
  })
})
