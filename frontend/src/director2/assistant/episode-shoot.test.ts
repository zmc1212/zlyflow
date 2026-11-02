import { describe, expect, it } from "vitest"
import type { Director2OptionDefinition, Director2WorkflowMode } from "../director2-video-settings"
import { episodeShootOptions, episodeShotTaskConfirmLines, resolveEpisodeShootPlan } from "./episode-shoot"

const OPTIONS: Record<string, Director2OptionDefinition> = {
  aspect_ratio: {
    label: "画面比例",
    type: "string",
    default: "16:9",
    ui_group: "primary",
    ui_options: [{ value: "16:9", label: "16:9 横屏" }, { value: "9:16", label: "9:16 竖屏" }],
  },
  refine_enabled: { label: "二采精修", type: "boolean", default: false, ui_group: "primary" },
  refine_quality: { label: "目标清晰度", type: "string", default: "1.0", ui_group: "primary", enum: ["1.0", "2.0"] },
  quality: {
    label: "分辨率",
    type: "string",
    default: "0.4",
    ui_group: "advanced",
    ui_options: [{ value: "0.4", label: "0.4 MP" }, { value: "0.98", label: "0.98 MP" }],
  },
}

function mode(
  id: string,
  name: string,
  options: Record<string, Director2OptionDefinition> = {},
  overrides: Partial<Director2WorkflowMode> = {},
): Director2WorkflowMode {
  return {
    id,
    name,
    media_type: "video",
    reference_mode: "collection",
    max_references: 9,
    supports_timeline: true,
    supports_multi_segment: true,
    parameters: Object.keys(options).length ? [{ name: "options", schema: { properties: options } }] : [],
    ...overrides,
  }
}

describe("episode shoot plan", () => {
  it("uses the saved workflow and applies saved options plus the confirmed resolution", () => {
    const plan = resolveEpisodeShootPlan(
      [mode("wf-a", "工作流 A", OPTIONS), mode("wf-b", "工作流 B", OPTIONS)],
      { workflow: "wf-b", aspect_ratio: "9:16", refine_enabled: "true", refine_quality: "2.0" },
      "768p",
    )
    expect(plan.workflowId).toBe("wf-b")
    expect(plan.workflowName).toBe("工作流 B")
    expect(plan.renderLabel).toBe("整集直出")
    expect(plan.values).toMatchObject({
      aspect_ratio: "9:16",
      refine_enabled: "true",
      refine_quality: "1.0",
      quality: "0.98",
    })
  })

  it("falls back to the first timeline workflow when the saved one is gone", () => {
    const plan = resolveEpisodeShootPlan(
      [mode("wf-a", "工作流 A", OPTIONS), mode("wf-b", "工作流 B", OPTIONS)],
      { workflow: "missing", aspect_ratio: "9:16" },
    )
    expect(plan.workflowId).toBe("wf-a")
    expect(plan.values.aspect_ratio).toBe("9:16")
  })

  it("ignores shot-only modes when choosing the episode workflow", () => {
    const plan = resolveEpisodeShootPlan([
      mode("wf-shot", "逐镜", OPTIONS, { reference_mode: "single", max_references: 1 }),
      mode("wf-collection-shot", "多参考逐镜", OPTIONS, { supports_timeline: false, supports_multi_segment: false }),
      mode("wf-episode", "整集", OPTIONS),
    ], null)
    expect(plan.workflowId).toBe("wf-episode")
    expect(plan.renderMode).toBe("episode")
  })

  it("keeps the saved workflow when the workflow registry is unavailable", () => {
    const plan = resolveEpisodeShootPlan([], { workflow: "wf-x", aspect_ratio: "9:16" })
    expect(plan.workflowId).toBe("wf-x")
    expect(plan.workflowName).toBe("")
    expect(plan.values.aspect_ratio).toBe("9:16")
  })

  it("builds job options with boolean flags converted", () => {
    const plan = resolveEpisodeShootPlan([mode("wf-a", "工作流 A", OPTIONS)], {
      workflow: "wf-a",
      refine_enabled: "true",
    })
    expect(episodeShootOptions(plan)).toMatchObject({ workflow: "wf-a", refine_enabled: true })
  })

  it("always asks the backend for saved H3 prompts instead of program packing", () => {
    const plan = resolveEpisodeShootPlan([mode("wf-a", "工作流 A", OPTIONS)], { workflow: "wf-a" })
    expect(episodeShootOptions(plan).prompt_mode).toBe("h3")
  })

  it("describes the per-shot tasks before submitting them", () => {
    const plan = resolveEpisodeShootPlan([mode("wf-a", "工作流 A", OPTIONS)], { workflow: "wf-a" })
    const lines = episodeShotTaskConfirmLines({
      episodeLabel: "第 1 集 · 午夜禁地",
      shotCount: 11,
      maxShotDurationSec: 8,
      plan,
    })
    expect(lines[0]).toBe("将为「第 1 集 · 午夜禁地」一次性提交 11 个逐镜视频任务，每个镜头可单独查看和重新生成。")
    expect(lines[1]).toBe("工作流：工作流 A · 逐镜任务 · 16:9 · 0.4 MP")
    expect(lines[2]).toContain("独立计费")
  })
})
