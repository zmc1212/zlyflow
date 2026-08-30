import { recipeShotPreferredTake, type RecipeProject, type RecipeShot } from "./recipe-model"
import type { ShotTake } from "./types"

const SHOT_EXECUTION_FIELDS = [
  "jobId", "status", "progress", "error", "compiledPrompt", "outputVideoUrl", "outputPath",
  "stillUrl", "stillJobId", "stillStatus",
  "ttsStatus", "ttsUrl", "ttsPath", "ttsError",
] as const

const SHOT_FRAME_FIELDS = [
  "firstFrameUrl", "firstFramePath", "firstFrameJobId",
  "endFrameUrl", "endFramePath", "endFrameJobId",
] as const

const CHARACTER_EXECUTION_FIELDS = ["imageJobId", "imageUrl", "voicePreviewUrl"] as const
const LOCATION_EXECUTION_FIELDS = ["imageJobId", "imageUrl"] as const
const EXPORT_EXECUTION_FIELDS = ["muxStatus", "muxUrl", "muxPath", "muxDurationSec", "muxError", "muxAt"] as const

function takeKey(take: ShotTake): string {
  return take.id || take.jobId || ""
}

export function mergeRecipeTakeExecution(current: ShotTake[], incoming: ShotTake[]): ShotTake[] {
  const merged = current.map((take) => ({ ...take }))
  const positions = new Map(merged.map((take, index) => [takeKey(take), index] as const).filter(([key]) => key))
  for (const take of incoming) {
    const key = takeKey(take)
    const position = key ? positions.get(key) : undefined
    if (position === undefined) {
      if (key) positions.set(key, merged.length)
      merged.push({ ...take })
    } else {
      merged[position] = { ...merged[position], ...take }
    }
  }
  return merged
}

function copyFields<T extends object>(
  current: T,
  incoming: T,
  fields: readonly string[],
): T {
  const next = { ...current } as Record<string, unknown>
  const source = incoming as unknown as Record<string, unknown>
  for (const field of fields) {
    if (Object.prototype.hasOwnProperty.call(source, field)) next[field] = source[field]
  }
  return next as unknown as T
}

function mergeShotExecution(current: RecipeShot, incoming: RecipeShot): RecipeShot {
  const next = copyFields(current, incoming, SHOT_EXECUTION_FIELDS)
  next.takes = mergeRecipeTakeExecution(current.takes || [], incoming.takes || [])
  // Approval is a creative decision. Polling execution state must never move it.
  next.approvedTakeId = current.approvedTakeId
  return next
}

function mergeCollectionExecution<T extends { id: string }>(
  current: T[],
  incoming: T[],
  fields: readonly string[],
): T[] {
  const source = new Map(incoming.map((item) => [item.id, item]))
  return current.map((item) => {
    const updated = source.get(item.id)
    return updated ? copyFields(item, updated, fields) : item
  })
}

/**
 * Merge server-owned execution fields while retaining every unsaved creative
 * field and the current scene/shot ordering in the editor.
 */
export function mergeRecipeExecutionState(current: RecipeProject, incoming: RecipeProject): RecipeProject {
  const incomingShots = new Map(
    incoming.scenes.flatMap((scene) => scene.shots).map((shot) => [shot.id, shot] as const),
  )
  const scenes = current.scenes.map((scene) => ({
    ...scene,
    shots: scene.shots.map((shot) => {
      const updated = incomingShots.get(shot.id)
      return updated ? mergeShotExecution(shot, updated) : shot
    }),
  }))
  const audio = {
    ...(current.audio || {}),
    ...(incoming.audio?.bgmUrl !== undefined ? { bgmUrl: incoming.audio.bgmUrl } : {}),
    ...(incoming.audio?.bgmPath !== undefined
      ? { bgmPath: incoming.audio.bgmPath }
      : {}),
  }
  const exportState = copyFields(
    current.export || incoming.export || {},
    incoming.export || current.export || {},
    EXPORT_EXECUTION_FIELDS,
  )
  return {
    ...current,
    scenes,
    characters: mergeCollectionExecution(current.characters, incoming.characters, CHARACTER_EXECUTION_FIELDS),
    locations: mergeCollectionExecution(current.locations, incoming.locations, LOCATION_EXECUTION_FIELDS),
    agentStatus: incoming.agentStatus,
    pipelineRun: incoming.pipelineRun,
    audio: audio as RecipeProject["audio"],
    export: exportState as RecipeProject["export"],
  }
}

/** Apply the server result of an explicit user frame upload to one shot only. */
export function mergeRecipeShotFrameState(
  current: RecipeProject,
  incoming: RecipeProject,
  shotId: string,
): RecipeProject {
  const incomingShot = incoming.scenes.flatMap((scene) => scene.shots).find((shot) => shot.id === shotId)
  if (!incomingShot) return current
  return {
    ...current,
    scenes: current.scenes.map((scene) => ({
      ...scene,
      shots: scene.shots.map((shot) => (
        shot.id === shotId ? copyFields(shot, incomingShot, SHOT_FRAME_FIELDS) : shot
      )),
    })),
  }
}

export function hasLatestShotSubmissionFailure(shot: RecipeShot, mode: "still" | "video"): boolean {
  if (mode === "still") {
    return ["failed", "interrupted", "cancelled"].includes(shot.stillStatus || "idle")
  }
  if (["failed", "interrupted", "cancelled"].includes(shot.status)) return true
  return Boolean(shot.error) && !["queued", "running"].includes(shot.status)
}

export function reconcileShotJobExecution(
  shot: RecipeShot,
  update: {
    status: RecipeShot["status"]
    progress: number
    videoUrl?: string
    error?: string | null
  },
): RecipeShot {
  const failed = ["failed", "interrupted", "cancelled"].includes(update.status)
  const fallbackTake = recipeShotPreferredTake(shot)
  const fallbackUrl = fallbackTake?.videoUrl || shot.outputVideoUrl || undefined
  if (failed && (fallbackTake || fallbackUrl)) {
    return {
      ...shot,
      status: "succeeded",
      progress: 100,
      outputVideoUrl: fallbackUrl,
      error: update.error || shot.error || "生成失败",
    }
  }
  return {
    ...shot,
    status: update.status,
    progress: update.status === "succeeded" ? 100 : update.progress,
    outputVideoUrl: update.videoUrl || shot.outputVideoUrl,
    error: update.status === "succeeded" || update.status === "queued" || update.status === "running"
      ? null
      : (update.error || shot.error),
  }
}
