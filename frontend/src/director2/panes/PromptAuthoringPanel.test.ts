import { readFileSync } from "node:fs"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { Director2Asset, Director2Beat, Director2EpisodeDetail, Director2Job, DirectorPromptPlan } from "../api"
import {
  formatDirectorPromptPlanForClipboard,
  findActivePromptPreview,
  isValidatedPromptPreview,
  isContinuousDirectorSelection,
  normalizeSlots,
  promptAuthoringCopy,
  referenceCandidates,
  ShotPromptSummary,
} from "./PromptAuthoringPanel"

function plan(status: "current" | "stale" = "current"): DirectorPromptPlan {
  return {
    kind: "director_segments",
    id: "plan-1",
    revision: 2,
    status,
    template_version: "prompt-master/continuous-story@1",
    language: "zh-CN",
    source_fingerprint: "fp",
    workflow_id: "director",
    common_setting: { subject_definitions: "公共设定", prompt_text: "公共设定" },
    reference_slots: [],
    parts: [{
      id: "part-1",
      index: 1,
      frame_count: 576,
      segments: [1, 2, 3].map((index) => ({
        id: `segment-${index}`,
        index,
        title: `段 ${index}`,
        frame_count: 192,
        duration_seconds: 8,
        source_beat_ids: [`beat-${index}`],
        shots: [{ shot_number: index, source_beat_id: `beat-${index}` }],
        sections: {
          summary: "摘要",
          retention_analysis: "保留",
          detailed_description: "详细描述",
          overall_soundscape: "声景",
          non_diegetic_music: "配乐",
        },
        prompt_text: `提示词 ${index}`,
        continuity_from_prev: index > 1,
      })),
    }],
  }
}

describe("PromptAuthoringPanel helpers", () => {
  it("shows only related prompts in a shot and exposes cross-shot scope without episode actions", () => {
    const saved = plan()
    saved.parts[0].segments[0].source_beat_ids = ["beat-1", "beat-2"]
    saved.parts[0].segments[0].sections.summary = "共享生成段的内容"
    saved.parts[0].segments[2].sections.summary = "不相关镜头的内容"
    const beats = [1, 2, 3].map(n => ({ id: `beat-${n}` })) as Director2Beat[]
    const episode = { beats, prompt_authoring: { director_plan: saved } } as Director2EpisodeDetail
    const html = renderToStaticMarkup(createElement(ShotPromptSummary, { episode, beat: beats[0], onOpenPlan: () => {} }))
    expect(html).toContain("共享生成段的内容")
    expect(html).toContain("关联镜头 1、2")
    expect(html).toContain("前往制作方案")
    expect(html).not.toContain("不相关镜头的内容")
    expect(html).not.toContain("AI 优化本集提示词")
    expect(html).not.toContain("公共主体定义")
  })
  it("recovers only running preview jobs for the current episode and prompt target", () => {
    const job = (id: string, status: string, episode = "ep-1", profile = "director_segments", beat = "beat-1") => ({
      id, status, job_type: "prompt_expansion", payload: { episode_id: episode, prompt_profile: profile, beat_id: beat },
      project_id: "project-1", title: "预览", progress: 0, result_url: null,
      error_message: null, created_at: "2026-09-22", updated_at: "2026-09-22",
    }) as Director2Job
    const jobs = [job("done", "succeeded"), job("other", "running", "ep-2"), job("active", "running"), job("queued", "queued")]
    expect(findActivePromptPreview(jobs, "ep-1", "director_segments")?.id).toBe("active")
    expect(findActivePromptPreview(jobs, "ep-1", "full_reference", "beat-1")).toBeUndefined()
    const beats = [job("wrong-beat", "running", "ep-1", "full_reference", "beat-2"), job("right-beat", "preparing", "ep-1", "full_reference")]
    expect(findActivePromptPreview(beats, "ep-1", "full_reference", "beat-1")?.id).toBe("right-beat")
    expect(findActivePromptPreview([job("failed", "failed")], "ep-1", "director_segments")).toBeUndefined()
  })
  it("switches copy from Beat template to Director template by prompt_profile", () => {
    expect(promptAuthoringCopy("full_reference").title).toContain("六段式")
    expect(promptAuthoringCopy("director_segments").title).toContain("Director")
    expect(promptAuthoringCopy("director_segments").description).toContain("镜头原文保留")
  })

  it("sorts character looks before scenes and props, then assigns stable Picture tokens", () => {
    const assets = [
      { id: "prop-1", kind: "prop", name: "伞", image_url: "prop.png", extra: {} },
      { id: "scene-1", kind: "scene", name: "车站", image_url: "scene.png", extra: {} },
      { id: "char-1", kind: "character", name: "主角", image_url: "char.png", extra: { identities: [{ id: "look-1", name: "雨衣", image_url: "look.png" }] } },
    ] as Director2Asset[]
    const candidates = referenceCandidates(assets)
    expect(candidates.map((item) => item.kind)).toEqual(["character", "character", "scene", "prop"])
    expect(normalizeSlots(candidates.slice(0, 3)).map((item) => item.token)).toEqual([
      "<Picture 1>",
      "<Picture 2>",
      "<Picture 3>",
    ])
  })

  it("accepts only continuous segment selections in one Part", () => {
    expect(isContinuousDirectorSelection(plan(), "part-1", ["segment-1", "segment-2"])).toBe(true)
    expect(isContinuousDirectorSelection(plan(), "part-1", ["segment-1", "segment-3"])).toBe(false)
    expect(isContinuousDirectorSelection(plan(), "part-2", ["segment-1"])).toBe(false)
  })

  it("formats the complete Director plan in display order for one-click copying", () => {
    expect(formatDirectorPromptPlanForClipboard(plan())).toBe([
      "Director 出片方案",
      "公共主体定义",
      "公共设定",
      "Part 1",
      "段 1 · 8s",
      "提示词 1",
      "段 2 · 8s",
      "提示词 2",
      "段 3 · 8s",
      "提示词 3",
    ].join("\n\n"))
  })

  it("does not open an incomplete Director preview", () => {
    expect(isValidatedPromptPreview({ ...plan(), validation_status: "pending" })).toBe(false)
    expect(isValidatedPromptPreview({ ...plan(), validation_status: "invalid" })).toBe(false)
    expect(isValidatedPromptPreview({ ...plan(), validation_status: "valid" })).toBe(true)
  })

  it("keeps stale plan state and mobile layout rules explicit", () => {
    expect(plan("stale").status).toBe("stale")
    const css = readFileSync(new URL("./episode-workshop.css", import.meta.url), "utf8")
    expect(css).toContain("@media (max-width: 760px)")
    expect(css).toContain(".prompt-authoring-header")
    expect(css).toContain("flex-direction: column")
  })

  it("renders the shared streaming live card while a prompt preview is running", () => {
    const source = readFileSync(new URL("./PromptAuthoringPanel.tsx", import.meta.url), "utf8")
    const css = readFileSync(new URL("./episode-workshop.css", import.meta.url), "utf8")
    expect(source).toContain("applyPromptStreamEvent")
    expect(source).toContain("提示词预览直播")
    expect(source).toContain('<WorkshopPromptLive state={previewLive} showStage={profile === "director_segments"} />')
    expect(source).toContain("重试失败部分")
    expect(source).toContain("重新生成全部")
    expect(source).toContain('label: "技术详情"')
    expect(source).toContain("message.destroy(\"prompt-preview\")")
    expect(css).toContain(".prompt-preview-live-card .workshop-prompt-live")
  })
})
