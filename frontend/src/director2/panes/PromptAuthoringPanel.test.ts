import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import type { Director2Asset, DirectorPromptPlan } from "../api"
import {
  formatDirectorPromptPlanForClipboard,
  isContinuousDirectorSelection,
  normalizeSlots,
  promptAuthoringCopy,
  referenceCandidates,
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
  it("switches copy from Beat template to Director template by prompt_profile", () => {
    expect(promptAuthoringCopy("full_reference").title).toContain("六段式")
    expect(promptAuthoringCopy("director_segments").title).toContain("Director")
    expect(promptAuthoringCopy("director_segments").description).toContain("不会覆盖原 Beat")
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

  it("keeps stale plan state and mobile layout rules explicit", () => {
    expect(plan("stale").status).toBe("stale")
    const css = readFileSync(new URL("./episode-workshop.css", import.meta.url), "utf8")
    expect(css).toContain("@media (max-width: 760px)")
    expect(css).toContain(".prompt-authoring-header")
    expect(css).toContain("flex-direction: column")
  })
})
