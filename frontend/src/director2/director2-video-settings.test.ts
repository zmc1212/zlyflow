import { describe, expect, it } from "vitest"
import {
  DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
  DIRECTOR2_VIDEO_FALLBACK_FIELDS,
  beatHasFilmTakes,
  beatHasUpscaled,
  beatPlaybackUrl,
  beatUpscaleDisabledReason,
  beatUpscaleLabel,
  collectBeatVideoTakes,
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
  jobUpscaleDisabledReason,
  jobUpscaleHint,
  jobUpscaleScale,
  optionChoices,
  playbackAspectIsPortrait,
  playbackAspectRatio,
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
          upscale_after: {
            label: "出片后超分", type: "string", default: "off", ui_group: "advanced",
            enum: ["off", "2", "4"],
            ui_options: [
              { value: "off", label: "关闭" },
              { value: "2", label: "2x（推荐）" },
              { value: "4", label: "4x" },
            ],
          },
        },
      },
    }],
  }
}

describe("director2 video settings", () => {
  it("exposes registry primary and advanced options and hides duration plus internals", () => {
    const fields = visibleVideoOptionFields(directorAccelMode())
    expect(fields.map((item) => item.name)).toEqual(["aspect_ratio", "weight_profile", "quality", "speed", "upscale_after"])
    expect(defaultVideoOptionValues(fields)).toEqual({
      aspect_ratio: "16:9",
      weight_profile: "pruned",
      quality: "0.4",
      speed: "balanced",
      upscale_after: "off",
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
      upscale_after: "off",
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
    expect(videoSettingsSummary(fields, values)).toBe("16:9 · 0.4 MP · 精简")
    expect(buildVideoJobOptions(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, values, { duration_per_beat: 8 })).toEqual({
      workflow: DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
      aspect_ratio: "16:9",
      weight_profile: "pruned",
      quality: "0.4",
      speed: "balanced",
      upscale_after: "off",
      duration_per_beat: 8,
    })
    expect(videoSettingsSummary(fields, { ...values, upscale_after: "2" })).toBe("16:9 · 0.4 MP · 精简 · 2x 超分")
    expect(buildVideoJobOptions(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, { ...values, upscale_after: "2" }).upscale_after).toBe("2")
    expect(videoSettingsSummary(fields, { ...values, upscale_after: "4" })).toBe("16:9 · 0.4 MP · 精简 · 4x 超分")
    expect(buildVideoJobOptions(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, { ...values, upscale_after: "4" }).upscale_after).toBe("4")
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
    expect(formatEpisodeVideoSubmitMessage({ render_mode: "episode", render_scope: "episode", job_ids: ["job-1"],
      submitted: 1, skipped: 2, blocked: [{ part_id: "p4", reason: "待审" }] })).toBe("已提交 1 个生成组，跳过 2 组，1 组待处理")
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

  it("prefers the upscaled clip for workshop playback and keeps the jobs-list thumbnail on the original", () => {
    expect(beatPlaybackUrl({ video_url: "https://cdn/orig.mp4", upscaled_video_url: "https://cdn/2x.mp4" })).toBe("https://cdn/2x.mp4")
    expect(beatHasUpscaled({ video_url: "https://cdn/orig.mp4" })).toBe(false)
    expect(beatUpscaleLabel({ upscaled_video_url: "https://cdn/4x.mp4", upscale_scale: 4 })).toBe("4x")
    expect(beatUpscaleDisabledReason({ video_url: "" })).toBe("成片成功后才能超分")
    expect(beatUpscaleDisabledReason({ video_url: "https://cdn/orig.mp4" }, { scope: "upscale" })).toBe("正在超分")
    expect(beatUpscaleDisabledReason({ video_url: "https://cdn/orig.mp4" }, { status: "running" })).toBe("出片进行中")
    expect(beatUpscaleDisabledReason({ video_url: "https://cdn/orig.mp4" })).toBeUndefined()
    expect(jobPreviewVideoUrl({
      result_url: "https://cdn/orig.mp4",
      payload: { upscaled_video_url: "https://cdn/2x.mp4", upscale_scale: 2 },
    })).toBe("https://cdn/orig.mp4")
    expect(jobUpscaleScale({
      payload: { upscaled_video_url: "https://cdn/4x.mp4", upscale_scale: 4 },
    })).toBe(4)
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
    }])).toBe("正在超分")
    expect(jobUpscaleHint({ payload: { render_scope: "episode" } })).toContain("整段")
  })

  it("collects beat takes from video_takes and jobs, oldest first, without duplicates", () => {
    const takes = collectBeatVideoTakes(
      {
        id: "beat-1",
        video_url: "https://cdn/new.mp4",
        video_takes: [
          { id: "take-old", url: "https://cdn/old.mp4", created_at: "2026-09-20 01:00:00", scope: "shot" },
          { id: "take-new", url: "https://cdn/new.mp4", created_at: "2026-09-20 03:00:00", scope: "shot" },
        ],
      },
      [{
        id: "job-old",
        job_type: "video_generation",
        status: "completed",
        result_url: "https://cdn/old.mp4",
        created_at: "2026-09-20 01:00:00",
        payload: { episode_id: "e1", render_scope: "shot", beat_id: "beat-1" },
      }],
      "e1",
    )
    expect(takes.map((item) => item.url)).toEqual(["https://cdn/old.mp4", "https://cdn/new.mp4"])
    expect(takes[0].job_id).toBe("job-old")
  })

  it("uses the per-shot url from a multi-shot job instead of the timeline result", () => {
    const takes = collectBeatVideoTakes(
      { id: "beat-1" },
      [{
        id: "job-sel",
        job_type: "video_generation",
        status: "completed",
        result_url: "https://cdn/timeline.mp4",
        created_at: "2026-09-20 02:00:00",
        payload: {
          episode_id: "e1",
          render_scope: "selection",
          beat_ids: ["beat-1", "beat-2"],
          shots: [
            { beat_id: "beat-1", video_url: "https://cdn/sel-1.mp4" },
            { beat_id: "beat-2", video_url: "https://cdn/sel-2.mp4" },
          ],
        },
      }],
      "e1",
    )
    expect(takes.map((item) => item.url)).toEqual(["https://cdn/sel-1.mp4"])
  })

  it("attaches upscale jobs to the matching original and excludes episode or compose results", () => {
    const takes = collectBeatVideoTakes(
      { id: "beat-1", video_url: "https://cdn/orig.mp4" },
      [
        {
          id: "job-ep",
          job_type: "video_generation",
          status: "completed",
          result_url: "https://cdn/episode.mp4",
          payload: { episode_id: "e1", render_scope: "episode", beat_id: "beat-1" },
        },
        {
          id: "job-co",
          job_type: "video_generation",
          status: "completed",
          result_url: "https://cdn/compose.mp4",
          payload: { episode_id: "e1", render_scope: "compose", beat_ids: ["beat-1"] },
        },
        {
          id: "job-vsr",
          job_type: "video_generation",
          status: "completed",
          result_url: "https://cdn/2x.mp4",
          payload: {
            episode_id: "e1",
            render_scope: "upscale",
            source_video_url: "https://cdn/orig.mp4",
            upscaled_video_url: "https://cdn/2x.mp4",
          },
        },
      ],
      "e1",
    )
    expect(takes.map((item) => item.url)).toEqual(["https://cdn/orig.mp4"])
    expect(takes[0].upscaled_url).toBe("https://cdn/2x.mp4")
    expect(beatHasFilmTakes({ id: "beat-1", video_url: "https://cdn/orig.mp4" }, [], "e1")).toBe(true)
  })
})

