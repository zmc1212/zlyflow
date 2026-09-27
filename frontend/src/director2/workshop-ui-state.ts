type VideoReadiness = {
  hasPlan: boolean
  busy: boolean
  dirty: boolean
  sourceChanged: boolean
  referencesMissing: boolean
  shots: Array<{ id: string; sequence: number; h3_prompt_reference_state?: string | null }>
  prompts: Record<string, { h3_prompt?: string } | null | undefined>
}

// UI guidance only. The server remains authoritative for revision and readiness.
export function workshopVideoBlockReason(state: VideoReadiness): string {
  if (!state.hasPlan) return "先确认镜头规划，再准备提示词和视频。"
  if (state.busy) return "正在提交操作，请稍候。"
  if (state.dirty) return "先保存提示词修改，再生成视频；不会使用未保存的正文。"
  if (state.sourceChanged) return "来源剧本已变化，请先调整镜头规划。"
  if (state.referencesMissing) return "本组参考素材尚未就绪，请先检查素材与参考。"
  if (!state.shots.length) return "先选择一个镜头。"
  const missing = state.shots.filter(shot => !state.prompts[shot.id]?.h3_prompt?.trim())
  if (missing.length) return "镜头 " + missing.map(shot => shot.sequence).join("、") + " 尚无已采纳提示词，请先生成并采纳候选。"
  const stale = state.shots.filter(shot => shot.h3_prompt_reference_state !== "current")
  if (stale.length) return "镜头 " + stale.map(shot => shot.sequence).join("、") + " 的提示词需要重新检查，请保存确认或重新生成候选。"
  return ""
}

export function workshopNextAction(state: { hasPlan: boolean; dirty: boolean; pending: boolean; hasPrompt: boolean; videoBlocked: boolean }): "plan" | "save" | "review" | "write" | "generate" | "check" {
  if (state.dirty) return "save"
  if (!state.hasPlan) return "plan"
  if (state.pending) return "review"
  if (!state.hasPrompt) return "write"
  return state.videoBlocked ? "check" : "generate"
}
