import { describe, expect, it } from "vitest"
import {
  DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
  DIRECTOR2_VIDEO_FALLBACK_FIELDS,
  beatHasUpscaled,
  beatPlaybackUrl,
  beatUpscaleDisabledReason,
  buildVideoJobOptions,
  defaultVideoOptionValues,
  episodeFilmSource,
  episodeFilmUrl,
  episodeVideoRenderMode,
  formatEpisodeVideoSubmitMessage,
  formatSelectedShotSubmitMessage,
  generatedResolutionLabel,
  groupedVideoWorkflowOptions,
  jobCanShowUpscaleAction,
  jobPreviewVideoUrl,
  jobRefineShotCount,
  jobCanConfirmRefine,
  jobUpscaleDisabledReason,
  jobUpscaleHint,
  optionChoices,
  playbackAspectIsPortrait,
  playbackAspectRatio,
  formatRefineDuration,
  refineEffectiveMegapixels,
  refineForceWarning,
  refinePlan,
  resolutionLabelForMegapixels,
  sanitizeVideoOptionValues,
  shotVideoActionLabel,
  selectedShotGenerateExtra,
  shotVideoReadyCount,
  timelineVideoWorkflows,
  videoOptionVisible,
  videoResolutionQuality,
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
          weight_profile: { label: "模型体积", type: "string", default: "full", ui_group: "primary", ui_options: [{ value: "full", label: "完整（32 GB）" }, { value: "pruned", label: "精简（20 GB）" }], ui_visible_when: { refine_enabled: false } },
          quality: {
            label: "分辨率", type: "string", default: "0.4", ui_group: "advanced",
            megapixels_by_quality: { "0.4": 0.4, "1.0": 1.0 },
            ui_resolution_preview: { multiple: 32 },
            ui_visible_when: { refine_enabled: false },
            ui_options: [{ value: "0.4", label: "0.4 MP" }, { value: "1.0", label: "1.0 MP" }],
          },
          speed: { label: "生成质量", type: "string", default: "balanced", ui_group: "advanced", ui_options: [{ value: "balanced", label: "均衡（20 步）" }, { value: "quality", label: "精细（25 步）" }], ui_visible_when: { refine_enabled: false } },
          megapixels: { label: "内部像素面积", type: "number", default: 0.4, ui_group: "internal" },
          steps: { label: "采样步数", type: "integer", default: 20, ui_group: "internal" },
          refine_enabled: { label: "二采精修", type: "boolean", default: false, ui_group: "primary" },
          refine_quality_mode: {
            label: "清晰度策略", type: "string", default: "auto", ui_group: "primary",
            enum: ["auto", "force"],
            ui_visible_when: { refine_enabled: true },
            ui_options: [{ value: "auto", label: "自动（推荐）" }, { value: "force", label: "强制高清" }],
          },
          refine_quality: {
            label: "目标清晰度", type: "string", default: "1.0", ui_group: "primary",
            enum: ["1.0", "2.0"],
            ui_visible_when: { refine_enabled: true },
            ui_options: [{ value: "1.0", label: "高清 1.0 MP" }, { value: "2.0", label: "超清 2.0 MP" }],
          },
        },
      },
    }],
  }
}

describe("director2 video settings", () => {
  it("exposes registry primary and advanced options and hides duration plus internals", () => {
    const fields = visibleVideoOptionFields(directorAccelMode())
    expect(fields.map((item) => item.name)).toEqual([
      "aspect_ratio", "weight_profile", "quality", "speed", "refine_enabled", "refine_quality_mode", "refine_quality",
    ])
    expect(defaultVideoOptionValues(fields)).toEqual({
      aspect_ratio: "16:9",
      weight_profile: "full",
      quality: "0.4",
      speed: "balanced",
      refine_enabled: "false",
      refine_quality_mode: "auto",
      refine_quality: "1.0",
    })
  })

  it("keeps two-pass controls in the primary group", () => {
    const fields = visibleVideoOptionFields(directorAccelMode())
    expect(fields.filter((item) => item.ui_group === "primary").map((item) => item.name)).toEqual([
      "aspect_ratio", "weight_profile", "refine_enabled", "refine_quality_mode", "refine_quality",
    ])
    expect(fields.filter((item) => item.ui_group === "advanced").map((item) => item.name)).toEqual([
      "quality", "speed",
    ])
  })

  it("hides quality, model size and generation quality when two-pass is enabled", () => {
    const fields = visibleVideoOptionFields(directorAccelMode())
    const quality = fields.find((item) => item.name === "quality")!
    const weightProfile = fields.find((item) => item.name === "weight_profile")!
    const speed = fields.find((item) => item.name === "speed")!
    const refineQuality = fields.find((item) => item.name === "refine_quality")!
    expect(videoOptionVisible(quality, { refine_enabled: "false" })).toBe(true)
    expect(videoOptionVisible(quality, { refine_enabled: "true" })).toBe(false)
    expect(videoOptionVisible(weightProfile, { refine_enabled: "false" })).toBe(true)
    expect(videoOptionVisible(weightProfile, { refine_enabled: "true" })).toBe(false)
    expect(videoOptionVisible(speed, { refine_enabled: "false" })).toBe(true)
    expect(videoOptionVisible(speed, { refine_enabled: "true" })).toBe(false)
    expect(videoOptionVisible(refineQuality, { refine_enabled: "false" })).toBe(false)
    expect(videoOptionVisible(refineQuality, { refine_enabled: "true" })).toBe(true)
  })

  it("falls back when the catalog has not loaded", () => {
    expect(visibleVideoOptionFields(undefined)).toEqual(DIRECTOR2_VIDEO_FALLBACK_FIELDS)
    const fallbackQuality = DIRECTOR2_VIDEO_FALLBACK_FIELDS.find((item) => item.name === "quality")!
    expect(videoOptionVisible(fallbackQuality, { refine_enabled: "false" })).toBe(true)
    expect(videoOptionVisible(fallbackQuality, { refine_enabled: "true" })).toBe(false)
  })

  it("rejects stale 4-step speed and 0.2 MP values that this workflow does not use", () => {
    const fields = visibleVideoOptionFields(directorAccelMode())
    expect(sanitizeVideoOptionValues(fields, { quality: "0.2", speed: "fast", refine_preview: "yes" })).toEqual({
      aspect_ratio: "16:9",
      weight_profile: "full",
      quality: "0.4",
      speed: "balanced",
      refine_enabled: "false",
      refine_quality_mode: "auto",
      refine_quality: "1.0",
    })
  })

  it("labels quality with the actual 16:9 canvas size", () => {
    const quality = visibleVideoOptionFields(directorAccelMode()).find((item) => item.name === "quality")
    expect(quality).toBeTruthy()
    expect(generatedResolutionLabel(quality!.definition, "0.4", "16:9")).toBe("864 × 480")
    expect(optionChoices(quality!, { aspect_ratio: "16:9" })[0].label).toContain("864 × 480")
  })

  it("reads the playback frame ratio from generation settings", () => {
    expect(playbackAspectRatio(undefined)).toBe("16:9")
    expect(playbackAspectRatio({})).toBe("16:9")
    expect(playbackAspectRatio({ aspect_ratio: " 9:16 " })).toBe("9:16")
    expect(playbackAspectIsPortrait("9:16")).toBe(true)
    expect(playbackAspectIsPortrait("16:9")).toBe(false)
    expect(playbackAspectIsPortrait("1:1")).toBe(false)
  })

  it("summarizes and serializes job options without duration", () => {
    const fields = visibleVideoOptionFields(directorAccelMode())
    const values = defaultVideoOptionValues(fields)
    expect(videoSettingsSummary(fields, values)).toBe("16:9 · 0.4 MP · 完整")
    expect(buildVideoJobOptions(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, values, { duration_per_beat: 8 })).toEqual({
      workflow: DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
      aspect_ratio: "16:9",
      weight_profile: "full",
      quality: "0.4",
      speed: "balanced",
      refine_enabled: false,
      refine_quality_mode: "auto",
      refine_quality: "1.0",
      duration_per_beat: 8,
    })
    const defaultRefined = { ...values, refine_enabled: "true" }
    expect(videoSettingsSummary(fields, defaultRefined)).toBe("16:9 · 二采 1.0 MP · 先预览")
    const refined = { ...values, refine_enabled: "true", refine_quality: "2.0" }
    expect(videoSettingsSummary(fields, refined)).toBe("16:9 · 二采 2.0 MP · 先预览")
    expect(videoSettingsSummary(fields, refined, 13)).toBe("16:9 · 二采 0.6 MP · 自动降档 · 先预览")
    expect(videoSettingsSummary(fields, refined, 2)).toBe("16:9 · 二采 2.0 MP · 先预览")
    expect(videoSettingsSummary(fields, refined, undefined, false)).toBe("16:9 · 二采 2.0 MP")
    expect(videoSettingsSummary(fields, refined, 13, false)).toBe("16:9 · 二采 0.6 MP · 自动降档")
    const forced = { ...values, refine_enabled: "true", refine_quality: "1.0", refine_quality_mode: "force" }
    expect(videoSettingsSummary(fields, forced, 13)).toBe("16:9 · 二采 1.0 MP · 强制 · 先预览")
    expect(videoSettingsSummary(fields, forced)).toBe("16:9 · 二采 1.0 MP · 强制 · 先预览")
    const refinedOptions = buildVideoJobOptions(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, refined)
    expect(refinedOptions.refine_enabled).toBe(true)
    expect(refinedOptions.refine_quality).toBe("2.0")
    expect(refinedOptions.refine_quality_mode).toBe("auto")
    expect(refinedOptions.refine_preview).toBeUndefined()
  })

  it("caps refine megapixels by clip length like the backend", () => {
    expect(refineEffectiveMegapixels(2, 2)).toBe(2)
    expect(refineEffectiveMegapixels(2, 5)).toBe(1.6)
    expect(refineEffectiveMegapixels(1, 5)).toBe(1)
    expect(refineEffectiveMegapixels(1, 8)).toBe(1)
    expect(refineEffectiveMegapixels(2, 13)).toBe(0.6)
    expect(refineEffectiveMegapixels(1, 13)).toBe(0.6)
    expect(refineEffectiveMegapixels(1, 15)).toBe(0.5)
    expect(refineEffectiveMegapixels(1, 13, "force")).toBe(1)
    expect(refineEffectiveMegapixels(2, 13, "force")).toBe(2)
  })

  it("shows the effective refine canvas and estimates time only inside the safe budget", () => {
    const auto = refinePlan("1.0", "auto", 13, "16:9")
    expect(auto.effectiveMegapixels).toBe(0.6)
    expect(auto.capped).toBe(true)
    expect(auto.overBudget).toBe(false)
    expect(auto.resolutionLabel).toBe("1056 × 608")
    expect(auto.estimatedSeconds).toBeGreaterThan(600)
    expect(auto.estimatedSeconds).toBeLessThan(720)
    expect(formatRefineDuration(auto.estimatedSeconds)).toMatch(/分钟/)

    const forced = refinePlan("1.0", "force", 13, "16:9")
    expect(forced.effectiveMegapixels).toBe(1)
    expect(forced.capped).toBe(false)
    expect(forced.overBudget).toBe(true)
    expect(forced.resolutionLabel).toBe("1376 × 768")
    expect(forced.estimatedSeconds).toBeUndefined()

    const safeForce = refinePlan("2.0", "force", 2, "16:9")
    expect(safeForce.overBudget).toBe(false)
    expect(safeForce.resolutionLabel).toBe("1920 × 1088")
    expect(safeForce.estimatedSeconds).toBeTruthy()
    expect(resolutionLabelForMegapixels(0.4, "9:16")).toBe("480 × 864")
  })

  it("warns only when forced quality exceeds the platform budget", () => {
    expect(refineForceWarning({ refine_enabled: "true" }, 13)).toBeUndefined()
    expect(refineForceWarning({ refine_enabled: "true", refine_quality_mode: "auto", refine_quality: "1.0" }, 13)).toBeUndefined()
    expect(refineForceWarning({ refine_enabled: "true", refine_quality_mode: "force", refine_quality: "1.0" }, 2)).toBeUndefined()
    expect(refineForceWarning({ refine_enabled: "true", refine_quality_mode: "force", refine_quality: "1.0" }, 13)).toMatch(/超出平台安全预算/)
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

  it("prefers the 2x clip for playback and disables upscale without a finished original", () => {
    expect(beatPlaybackUrl({ video_url: "https://cdn/orig.mp4", upscaled_video_url: "https://cdn/2x.mp4" })).toBe("https://cdn/2x.mp4")
    expect(beatHasUpscaled({ video_url: "https://cdn/orig.mp4" })).toBe(false)
    expect(beatUpscaleDisabledReason({ video_url: "" })).toBe("成片成功后才能超分")
    expect(beatUpscaleDisabledReason({ video_url: "https://cdn/orig.mp4" }, { scope: "upscale" })).toBe("正在 2x 超分")
    expect(beatUpscaleDisabledReason({ video_url: "https://cdn/orig.mp4" }, { status: "running" })).toBe("出片进行中")
    expect(beatUpscaleDisabledReason({ video_url: "https://cdn/orig.mp4" })).toBeUndefined()
    expect(jobPreviewVideoUrl({
      result_url: "https://cdn/orig.mp4",
      payload: { upscaled_video_url: "https://cdn/2x.mp4" },
    })).toBe("https://cdn/2x.mp4")
  })

  it("lets completed video jobs request 2x from the jobs center", () => {
    const shot = {
      id: "job-shot",
      job_type: "video_generation",
      status: "completed",
      result_url: "https://cdn/shot.mp4",
      payload: { render_scope: "shot", beat_id: "beat-1" },
    }
    expect(jobCanShowUpscaleAction(shot)).toBe(true)
    expect(jobCanShowUpscaleAction({ ...shot, status: "awaiting_refine" })).toBe(false)
    expect(jobUpscaleDisabledReason(shot)).toBeUndefined()
    expect(jobCanShowUpscaleAction({ ...shot, payload: { render_scope: "upscale" } })).toBe(false)
    expect(jobUpscaleDisabledReason({ ...shot, status: "running" })).toBe("成片成功后才能超分")
    expect(jobUpscaleDisabledReason({
      ...shot,
      payload: { render_scope: "selection", beat_ids: ["a", "b"] },
    })).toBe("多镜任务请到剧集工坊逐镜点「超分」")
    expect(jobUpscaleDisabledReason(shot, [{
      id: "job-vsr",
      status: "running",
      payload: { render_scope: "upscale", source_job_id: "job-shot" },
    }])).toBe("正在 2x 超分")
    expect(jobUpscaleHint({ payload: { render_scope: "episode" } })).toContain("整段")
  })

  it("only offers refine decisions for awaiting single-shot and selection jobs", () => {
    expect(jobCanConfirmRefine({
      job_type: "video_generation",
      status: "awaiting_refine",
      payload: { render_scope: "shot", beat_id: "beat-1" },
    })).toBe(true)
    expect(jobCanConfirmRefine({
      job_type: "video_generation",
      status: "awaiting_refine",
      payload: { render_scope: "selection", beat_ids: ["beat-1", "beat-2"] },
    })).toBe(true)
    expect(jobCanConfirmRefine({
      job_type: "video_generation",
      status: "running",
      payload: { render_scope: "shot", beat_id: "beat-1" },
    })).toBe(false)
    expect(jobCanConfirmRefine({
      job_type: "video_generation",
      status: "awaiting_refine",
      payload: { render_scope: "episode" },
    })).toBe(false)
    expect(jobRefineShotCount({ payload: { render_scope: "shot", beat_id: "beat-1" } })).toBe(1)
    expect(jobRefineShotCount({ payload: { beat_ids: ["beat-1", "beat-1", "beat-2"] } })).toBe(2)
    expect(jobRefineShotCount(null)).toBe(0)
  })

  it("maps a confirmed project resolution to the locked quality presets", () => {
    expect(videoResolutionQuality("768p")).toBe("0.98")
    expect(videoResolutionQuality("768P", true)).toBe("1.0")
    expect(videoResolutionQuality("2k")).toBe("2.0")
    expect(videoResolutionQuality("2K", true)).toBe("2.0")
    expect(videoResolutionQuality("")).toBeUndefined()
  })
})

