import {
  recipeShotPreferredTake,
  type RecipeAssetRendition,
  type RecipeCharacter,
  type RecipeLocation,
  type RecipeProject,
  type RecipeProp,
  type RecipeShot,
} from "./recipe-model"
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
const PROP_EXECUTION_FIELDS = ["imageJobId", "imageUrl"] as const
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

function mergeRenditionExecution(
  current: RecipeAssetRendition | undefined,
  incoming: RecipeAssetRendition | undefined,
): RecipeAssetRendition {
  const versions = [...(current?.versions || [])].map((version) => ({ ...version }))
  const positions = new Map(versions.map((version, index) => [version.id, index] as const))
  for (const version of incoming?.versions || []) {
    const position = positions.get(version.id)
    if (position === undefined) {
      positions.set(version.id, versions.length)
      versions.push({ ...version })
    } else {
      versions[position] = { ...versions[position], ...version }
    }
  }
  const incomingApproved = versions.find((version) => version.id === incoming?.approvedVersionId)
  return {
    versions,
    activeVersionId: incoming?.activeVersionId || current?.activeVersionId,
    approvedVersionId: incomingApproved?.autoApprove
      ? incoming?.approvedVersionId
      : current?.approvedVersionId,
  }
}

function mergeCharacterExecution(current: RecipeCharacter, incoming: RecipeCharacter): RecipeCharacter {
  const next = copyFields(current, incoming, CHARACTER_EXECUTION_FIELDS)
  next.portrait = mergeRenditionExecution(current.portrait, incoming.portrait)
  const incomingLooks = new Map((incoming.looks || []).map((look) => [look.id, look]))
  next.looks = (current.looks || []).map((look) => {
    const updated = incomingLooks.get(look.id)
    return updated ? { ...look, sheet: mergeRenditionExecution(look.sheet, updated.sheet) } : look
  })
  return next
}

function mergeLocationExecution(current: RecipeLocation, incoming: RecipeLocation): RecipeLocation {
  return {
    ...copyFields(current, incoming, LOCATION_EXECUTION_FIELDS),
    plate: mergeRenditionExecution(current.plate, incoming.plate),
  }
}

function mergePropExecution(current: RecipeProp, incoming: RecipeProp): RecipeProp {
  return {
    ...copyFields(current, incoming, PROP_EXECUTION_FIELDS),
    turnaround: mergeRenditionExecution(current.turnaround, incoming.turnaround),
  }
}

function mergeAssetsById<T extends { id: string }>(current: T[], incoming: T[], merge: (a: T, b: T) => T): T[] {
  const source = new Map(incoming.map((item) => [item.id, item]))
  return current.map((item) => {
    const updated = source.get(item.id)
    return updated ? merge(item, updated) : item
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
    characters: mergeAssetsById(current.characters, incoming.characters, mergeCharacterExecution),
    locations: mergeAssetsById(current.locations, incoming.locations, mergeLocationExecution),
    props: mergeAssetsById(current.props, incoming.props, mergePropExecution),
    agentStatus: incoming.agentStatus,
    pipelineRun: incoming.pipelineRun,
    audio: audio as RecipeProject["audio"],
    export: exportState as RecipeProject["export"],
  }
}

/** Apply an explicit user approval without dropping unsaved creative edits. */
export function mergeRecipeApprovedAssetState(current: RecipeProject, incoming: RecipeProject): RecipeProject {
  const merged = mergeRecipeExecutionState(current, incoming)
  const characters = new Map(incoming.characters.map((item) => [item.id, item]))
  const locations = new Map(incoming.locations.map((item) => [item.id, item]))
  const props = new Map(incoming.props.map((item) => [item.id, item]))
  return {
    ...merged,
    characters: merged.characters.map((item) => {
      const source = characters.get(item.id)
      if (!source) return item
      return {
        ...item,
        portrait: { ...item.portrait, approvedVersionId: source.portrait?.approvedVersionId ?? item.portrait?.approvedVersionId },
        looks: (item.looks || []).map((look) => {
          const sourceLook = source.looks?.find((entry) => entry.id === look.id)
          return sourceLook
            ? { ...look, sheet: { ...look.sheet, approvedVersionId: sourceLook.sheet?.approvedVersionId ?? look.sheet?.approvedVersionId } }
            : look
        }),
        imageUrl: source.imageUrl ?? item.imageUrl,
        imageJobId: source.imageJobId ?? item.imageJobId,
      }
    }),
    locations: merged.locations.map((item) => {
      const source = locations.get(item.id)
      if (!source) return item
      return {
        ...item,
        plate: { ...item.plate, approvedVersionId: source.plate?.approvedVersionId ?? item.plate?.approvedVersionId },
        imageUrl: source.imageUrl ?? item.imageUrl,
        imageJobId: source.imageJobId ?? item.imageJobId,
      }
    }),
    props: merged.props.map((item) => {
      const source = props.get(item.id)
      if (!source) return item
      return {
        ...item,
        turnaround: { ...item.turnaround, approvedVersionId: source.turnaround?.approvedVersionId ?? item.turnaround?.approvedVersionId },
        imageUrl: source.imageUrl ?? item.imageUrl,
        imageJobId: source.imageJobId ?? item.imageJobId,
      }
    }),
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
