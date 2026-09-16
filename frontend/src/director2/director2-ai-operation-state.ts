import type { Director2AiOperation, Director2AiStage } from "./api"

/** Worker 占用状态：Prompt Bar 锁定，需订阅 SSE。不含 awaiting_review（用户在思考）。 */
export const DIRECTOR2_ACTIVE_AI_STATUSES = new Set(["queued", "running", "clarifying", "revising"])

/** 占用项目唯一 AI 槽位的状态：含暂停待确认，刷新后仍需接管，禁止再开新任务。 */
export const DIRECTOR2_OCCUPYING_AI_STATUSES = new Set(["queued", "running", "clarifying", "revising", "awaiting_review"])

export const DIRECTOR2_PIPELINE_STAGES: Director2AiStage[] = ["script", "assets", "episodes", "storyboard"]

/** 项目里五个创作阶段对应的真实内容存量（与手动编辑模式共享同一批数据）。 */
export type Director2ContentSummary = {
  scriptCount: number
  assetCount: number
  episodeCount: number
  shotCount: number
}

export type Director2RailStageStatus = "completed" | "failed" | "running" | "review" | "pending"

export function isDirector2AiOperationActive(operation: Director2AiOperation | null): boolean {
  return Boolean(operation && DIRECTOR2_ACTIVE_AI_STATUSES.has(operation.status))
}

export function isDirector2AiOperationOccupying(operation: Director2AiOperation | null): boolean {
  return Boolean(operation && DIRECTOR2_OCCUPYING_AI_STATUSES.has(operation.status))
}

export function isDirector2AwaitingReview(operation: Director2AiOperation | null): boolean {
  return operation?.status === "awaiting_review"
}

export function director2AwaitingStage(operation: Director2AiOperation | null): Director2AiStage | null {
  if (!operation) return null
  if (operation.status !== "awaiting_review" && operation.status !== "revising") return null
  return operation.awaiting_stage || (operation.current_stage && operation.current_stage !== "clarify" ? operation.current_stage : null)
}

export function director2ReviewStepNumber(stage: Director2AiStage | null | undefined): number {
  const index = DIRECTOR2_PIPELINE_STAGES.indexOf(stage as Director2AiStage)
  return index >= 0 ? index + 1 : 0
}

export function isDirector2LastPipelineStage(stage: Director2AiStage | null | undefined): boolean {
  return stage === "storyboard"
}

export function director2CheckpointHeadline(operation: Director2AiOperation | null): string | null {
  if (!operation) return null
  if (operation.status === "revising") return "正在按你的反馈重新规划…"
  if (operation.status === "awaiting_review") {
    const step = director2ReviewStepNumber(director2AwaitingStage(operation) || operation.current_stage)
    return step ? `第 ${step} 步已生成，请确认` : "该阶段已生成，请确认"
  }
  return null
}

export function markDirector2AiOperationCancelling(operation: Director2AiOperation): Director2AiOperation {
  return {
    ...operation,
    cancel_requested: true,
    result: { ...operation.result, message: "正在停止当前生成…" },
  }
}

export function mergeDirector2AiStatusEvent(
  operation: Director2AiOperation,
  data: Record<string, unknown>,
): Director2AiOperation {
  return {
    ...operation,
    status: (data.status as Director2AiOperation["status"]) || operation.status,
    progress: typeof data.progress === "number" ? data.progress : operation.progress,
    current_stage: (data.stage as Director2AiStage) || operation.current_stage,
    awaiting_stage: "awaiting_stage" in data
      ? ((data.awaiting_stage as Director2AiStage | null) ?? null)
      : operation.awaiting_stage,
    cancel_requested: typeof data.cancel_requested === "boolean" ? data.cancel_requested : operation.cancel_requested,
    result: {
      ...operation.result,
      message: typeof data.message === "string" ? data.message : operation.result.message,
      completed_stages: Array.isArray(data.completed_stages)
        ? data.completed_stages as Director2AiStage[]
        : operation.result.completed_stages,
      questions: Array.isArray(data.questions) ? data.questions as Director2AiOperation["result"]["questions"] : operation.result.questions,
    },
  }
}

export function director2AiHeadlineDetail(
  operation: Director2AiOperation | null,
  stageMessage: string | undefined,
  fallback: string,
): string {
  if (!operation) return fallback
  if (operation.cancel_requested) return "正在停止当前生成，已完成的内容会保留。"
  if (operation.status === "revising") {
    return stageMessage || operation.result.message || "正在按你的反馈重新规划…"
  }
  if (operation.status === "awaiting_review") {
    return stageMessage || operation.result.message || "该阶段已生成，请确认或提出调整"
  }
  if (operation.status === "failed" || operation.status === "cancelled") {
    return operation.error || stageMessage || operation.result.message || fallback
  }
  return stageMessage || operation.result.message || fallback
}

export function director2RailStageStatus(
  stage: Director2AiStage,
  operation: Director2AiOperation | null,
  completed: Set<Director2AiStage>,
): Director2RailStageStatus {
  const awaitingStage = director2AwaitingStage(operation)
  if (operation?.status === "awaiting_review" && awaitingStage === stage) return "review"
  const current = operation?.current_stage
  const clarifyReady = operation?.kind === "pipeline" || (operation?.kind === "clarify" && operation.status === "succeeded")
  if (completed.has(stage) || (clarifyReady && stage === "clarify")) return "completed"
  const failedStage = operation?.result?.failed_stage || (["failed", "cancelled"].includes(operation?.status || "") ? current : null)
  if (failedStage === stage) return "failed"
  if (current === stage && operation && DIRECTOR2_ACTIVE_AI_STATUSES.has(operation.status)) return "running"
  return "pending"
}

type DocumentLike = { raw_text?: string | null; analysis?: Record<string, any> | null }
type EpisodeLike = { shots_count?: number | null }

function analysisEpisodes(analysis: Record<string, any> | null | undefined): any[] {
  return Array.isArray(analysis?.episodes) ? analysis.episodes : []
}

function analysisShotCount(analysis: Record<string, any> | null | undefined): number {
  return analysisEpisodes(analysis).reduce((acc, ep) => acc + (Array.isArray(ep?.shots) ? ep.shots.length : 0), 0)
}

/**
 * 从项目实际数据（剧本文档 / 资产库 / 剧集工坊）统计五个创作阶段的产出存量。
 * AI 流水和手动导入写的是同一批表，因此无论内容从哪个模式来都能统计到；
 * 分集与分镜同时计入剧本文档解析结果，与内容库展示口径一致。
 */
export function deriveDirector2ContentSummary(input: {
  documents?: DocumentLike[] | null
  assets?: Array<{ id?: string }> | null
  episodes?: EpisodeLike[] | null
}): Director2ContentSummary {
  const documents = input.documents || []
  const assets = input.assets || []
  const episodes = input.episodes || []
  let analysisEpisodeCount = 0
  let analysisShotTotal = 0
  for (const doc of documents) {
    analysisEpisodeCount = Math.max(analysisEpisodeCount, analysisEpisodes(doc.analysis).length)
    analysisShotTotal = Math.max(analysisShotTotal, analysisShotCount(doc.analysis))
  }
  return {
    scriptCount: documents.filter((doc) => Boolean(String(doc.raw_text || "").trim() || doc.analysis)).length,
    assetCount: assets.length,
    episodeCount: Math.max(episodes.length, analysisEpisodeCount),
    shotCount: Math.max(
      episodes.reduce((acc, ep) => acc + (Number(ep.shots_count) || 0), 0),
      analysisShotTotal,
    ),
  }
}

/** 按存量推导已就绪的创作阶段：有内容即视为该阶段已完成，创意确认跟随任意内容。 */
export function director2ContentStages(summary: Director2ContentSummary | null): Director2AiStage[] {
  if (!summary) return []
  const stages: Director2AiStage[] = []
  if (summary.scriptCount > 0 || summary.assetCount > 0 || summary.episodeCount > 0) stages.push("clarify")
  if (summary.scriptCount > 0) stages.push("script")
  if (summary.assetCount > 0) stages.push("assets")
  if (summary.episodeCount > 0) stages.push("episodes")
  if (summary.shotCount > 0) stages.push("storyboard")
  return stages
}

/** 左侧步骤的完成集合 = AI 任务记录 ∪ 项目真实内容存量。待确认/调整中的当前步不计入完成。 */
export function mergeDirector2StageCompletion(
  operation: Director2AiOperation | null,
  contentSummary: Director2ContentSummary | null,
): Set<Director2AiStage> {
  const completed = new Set<Director2AiStage>([
    ...(operation?.result?.completed_stages || []),
    ...director2ContentStages(contentSummary),
  ])
  const awaiting = director2AwaitingStage(operation)
  if (awaiting) completed.delete(awaiting)
  return completed
}
