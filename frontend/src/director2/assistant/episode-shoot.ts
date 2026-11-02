import {
  DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
  buildVideoJobOptions,
  episodeVideoRenderMode,
  sanitizeVideoOptionValues,
  timelineVideoWorkflows,
  videoResolutionQuality,
  videoSettingsSummary,
  videoWorkflowRenderLabel,
  visibleVideoOptionFields,
  type Director2VideoOptionField,
  type Director2WorkflowMode,
  type EpisodeVideoRenderMode,
} from "../director2-video-settings"

export type EpisodeShootPlan = {
  workflowId: string
  workflowName: string
  renderLabel: string
  renderMode: EpisodeVideoRenderMode
  values: Record<string, string>
  fields: Director2VideoOptionField[]
}

export function resolveEpisodeShootPlan(
  modes: Director2WorkflowMode[],
  saved: Record<string, string> | null,
  resolution?: string | null,
): EpisodeShootPlan {
  const workflows = timelineVideoWorkflows(modes)
  const episodeModes = workflows.filter((mode) => episodeVideoRenderMode(mode) === "episode")
  const selected = episodeModes.find((mode) => mode.id === saved?.workflow) || episodeModes[0] || workflows[0]
  const fields = visibleVideoOptionFields(selected)
  const values = sanitizeVideoOptionValues(fields, saved)
  const lockedQuality = videoResolutionQuality(resolution)
  const lockedRefine = videoResolutionQuality(resolution, true)
  if (lockedQuality) values.quality = lockedQuality
  if (lockedRefine) values.refine_quality = lockedRefine
  return {
    workflowId: selected?.id || saved?.workflow || DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
    workflowName: selected?.name || "",
    renderLabel: selected ? videoWorkflowRenderLabel(selected) : "",
    renderMode: selected ? episodeVideoRenderMode(selected) : "episode",
    values,
    fields,
  }
}

export function episodeShotTaskSummary(plan: EpisodeShootPlan, maxShotDurationSec: number): string {
  const settings = videoSettingsSummary(plan.fields, plan.values, maxShotDurationSec, true)
  return [plan.workflowName, "逐镜任务", settings].filter(Boolean).join(" · ")
}

export function episodeShootOptions(plan: EpisodeShootPlan): Record<string, unknown> {
  return { ...buildVideoJobOptions(plan.workflowId, plan.values), prompt_mode: "h3" }
}

export function episodeShotTaskConfirmLines(input: {
  episodeLabel: string
  shotCount: number
  maxShotDurationSec: number
  plan: EpisodeShootPlan
}): string[] {
  return [
    `将为「${input.episodeLabel || "当前分集"}」一次性提交 ${input.shotCount} 个逐镜视频任务，每个镜头可单独查看和重新生成。`,
    `工作流：${episodeShotTaskSummary(input.plan, input.maxShotDurationSec)}`,
    "每个镜头独立出片并独立计费，全部完成后可在工坊合成整集。",
  ]
}
