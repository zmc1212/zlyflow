import { describe, expect, it } from "vitest"
import {
  DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
  DIRECTOR2_VIDEO_FALLBACK_FIELDS,
  buildVideoJobOptions,
  defaultVideoOptionValues,
  episodeFilmSource,
  episodeFilmUrl,
  episodeVideoRenderMode,
  formatEpisodeVideoSubmitMessage,
  formatSelectedShotSubmitMessage,
  generatedResolutionLabel,
  groupedVideoWorkflowOptions,
  optionChoices,
  sanitizeVideoOptionValues,
  shotVideoActionLabel,
  selectedShotGenerateExtra,
  shotVideoReadyCount,
  timelineVideoWorkflows,
  videoSettingsSummary,
  videoWorkflowRenderLabel,
  visibleVideoOptionFields,
  type Director2WorkflowMode,
} from "./director2-video-settings"

function directorAccelMode(): Director2WorkflowMode {
  return {
    id: DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
    name: "H3 Director 加速版 多参考视频",
    supports_timeline: true,
    supports_multi_segment: true,
    reference_mode: "collection",
    max_references: 9,
    catalog_group: "h3_director_accel",
    catalog_group_label: "H3 Director 加速版",
    catalog_group_order: 17,
    parameters: [{
      name: "options",
      schema: {
        properties: {
          aspect_ratio: { label: "画面比例", type: "string", default: "16:9", ui_group: "primary", ui_options: [{ value: "16:9", label: "16:9 横屏" }] },
          duration: { label: "时长", type: "number", default: 5, ui_group: "primary" },
          weight_profile: { label: "模型体积", type: "string", default: "pruned", ui_group: "primary", ui_options: [{ value: "pruned", label: "精简（20 GB）" }] },
          quality: {
            label: "分辨率", type: "string", default: "0.4", ui_group: "advanced",
            megapixels_by_quality: { "0.4": 0.4, "1.0": 1.0 },
            ui_resolution_preview: { multiple: 32 },
            ui_options: [{ value: "0.4", label: "0.4 MP" }, { value: "1.0", label: "1.0 MP" }],
          },
          speed: { label: "生成质量", type: "string", default: "balanced", ui_group: "advanced", ui_options: [{ value: "balanced", label: "均衡（20 步）" }, { value: "quality", label: "精细（25 步）" }] },
          megapixels: { label: "内部像素面积", type: "number", default: 0.4, ui_group: "internal" },
          steps: { label: "采样步数", type: "integer", default: 20, ui_group: "internal" },
        },
      },
    }],
  }
}

describe("director2 video settings", () => {
  it("exposes registry primary and advanced options and hides duration plus internals", () => {
    const fields = visibleVideoOptionFields(directorAccelMode())
    expect(fields.map((item) => item.name)).toEqual(["aspect_ratio", "weight_profile", "quality", "speed"])
    expect(defaultVideoOptionValues(fields)).toEqual({
      aspect_ratio: "16:9",
      weight_profile: "pruned",
      quality: "0.4",
      speed: "balanced",
    })
  })

  it("falls back when the catalog has not loaded", () => {
    expect(visibleVideoOptionFields(undefined)).toEqual(DIRECTOR2_VIDEO_FALLBACK_FIELDS)
  })

  it("rejects stale 4-step speed and 0.2 MP values that this workflow does not use", () => {
    const fields = visibleVideoOptionFields(directorAccelMode())
    expect(sanitizeVideoOptionValues(fields, { quality: "0.2", speed: "fast" })).toEqual({
      aspect_ratio: "16:9",
      weight_profile: "pruned",
      quality: "0.4",
      speed: "balanced",
    })
  })

  it("labels quality with the actual 16:9 canvas size", () => {
    const quality = visibleVideoOptionFields(directorAccelMode()).find((item) => item.name === "quality")
    expect(quality).toBeTruthy()
    expect(generatedResolutionLabel(quality!.definition, "0.4", "16:9")).toBe("864 × 480")
    expect(optionChoices(quality!, { aspect_ratio: "16:9" })[0].label).toContain("864 × 480")
  })

  it("summarizes and serializes job options without duration", () => {
    const fields = visibleVideoOptionFields(directorAccelMode())
    const values = defaultVideoOptionValues(fields)
    expect(videoSettingsSummary(fields, values)).toBe("16:9 · 0.4 MP · 精简")
    expect(buildVideoJobOptions(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, values, { duration_per_beat: 8 })).toEqual({
      workflow: DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
      aspect_ratio: "16:9",
      weight_profile: "pruned",
      quality: "0.4",
      speed: "balanced",
      duration_per_beat: 8,
    })
  })

  it("lists all unhidden multi-reference R2V workflows and labels episode vs shot", () => {
    const official: Director2WorkflowMode = {
      id: "minimax-h3-r2v",
      name: "官方 MiniMax H3 多参考视频",
      supports_timeline: false,
      reference_mode: "collection",
      max_references: 9,
      catalog_group: "official_h3",
      catalog_group_label: "官方 MiniMax H3",
      catalog_group_order: 20,
    }
    const light: Director2WorkflowMode = {
      id: "minimax-h3-lightx2v-r2v",
      name: "LightX2V 多参考视频",
      reference_mode: "collection",
      max_references: 9,
      catalog_group: "lightx2v",
      catalog_group_label: "LightX2V",
      catalog_group_order: 10,
    }
    const modes = timelineVideoWorkflows([
      { id: "grs-nano-banana", name: "图片", media_type: "image", reference_mode: "collection", max_references: 9 },
      { id: "minimax-h3-t2v", name: "文生", reference_mode: "none", max_references: 0 },
      { id: "minimax-h3-i2v", name: "首尾帧", reference_mode: "keyframes", max_references: 2 },
      { id: "minimax-h3-t8-dual-clock", name: "双时钟", reference_mode: "collection", max_references: 1 },
      { id: "wan21-vace-depth-v2v", name: "VACE", reference_mode: "collection", max_references: 9, hidden_from_catalog: true },
      official,
      light,
      directorAccelMode(),
    ])
    expect(modes.map((item) => item.id)).toEqual([
      "minimax-h3-r2v",
      "minimax-h3-lightx2v-r2v",
      DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
    ])
    expect(episodeVideoRenderMode(directorAccelMode())).toBe("episode")
    expect(episodeVideoRenderMode(official)).toBe("shot")
    expect(videoWorkflowRenderLabel(directorAccelMode())).toBe("整集直出")
    expect(videoWorkflowRenderLabel(official)).toBe("逐镜")
    expect(groupedVideoWorkflowOptions(modes).map((group) => group.label)).toEqual([
      "LightX2V",
      "H3 Director 加速版",
      "官方 MiniMax H3",
    ])
    expect(groupedVideoWorkflowOptions(modes)[1].options[0].label).toContain("整集直出")
    expect(groupedVideoWorkflowOptions(modes)[2].options[0].label).toContain("逐镜")
  })

  it("formats one-click and shot action copy from render mode", () => {
    expect(formatEpisodeVideoSubmitMessage({ render_mode: "episode", job_id: "job-1" })).toBe("已创建 1 个整集任务")
    expect(formatEpisodeVideoSubmitMessage({ render_mode: "shot", submitted: 4, skipped: 2 })).toBe(
      "已提交 4 镜（跳过 2 镜已有成片）",
    )
    expect(shotVideoActionLabel(false, "官方 MiniMax H3 多参考视频")).toBe("生成本镜（官方 MiniMax H3 多参考视频）")
    expect(shotVideoActionLabel(true, "H3 Director 加速版 多参考视频")).toBe("重新生成本镜")
    expect(formatSelectedShotSubmitMessage({ render_mode: "shot", submitted: 2, skipped: 1 })).toBe(
      "已提交选中的 2 镜（跳过 1 镜正在生成）",
    )
    expect(formatSelectedShotSubmitMessage({ render_mode: "episode", shot_count: 2, submitted: 1 })).toBe(
      "已创建 1 个 Timeline 任务（2 镜）",
    )
    expect(formatSelectedShotSubmitMessage({ render_mode: "episode", shot_count: 1, submitted: 1 })).toBe(
      "已创建 1 个单镜 Timeline 任务",
    )
    expect(selectedShotGenerateExtra(["beat-1", "beat-1", "beat-3"])).toEqual({
      beat_ids: ["beat-1", "beat-3"],
      force: true,
    })
  })

  it("reads episode film fields and shot readiness from detail payloads", () => {
    expect(episodeFilmUrl({
      episode_video_url: "",
      data: { episode_video_url: "https://cdn/ep.mp4" },
    })).toBe("https://cdn/ep.mp4")
    expect(episodeFilmSource({ episode_video_source: "director_direct" })).toBe("director_direct")
    expect(shotVideoReadyCount([
      { video_url: "https://cdn/a.mp4" },
      { video_url: "" },
      { video_url: "https://cdn/c.mp4" },
    ])).toBe(2)
  })
})
