import { recipeShotPreferredTake, shotIsMuxable, type RecipeProject, type RecipeShot } from "./recipe-model"

export interface RecipeShotLayoutItem {
  shot: RecipeShot
  startSec: number
  endSec: number
}

export interface RecipeTrackClip extends RecipeShotLayoutItem {
  left: number
  width: number
}

export const RECIPE_TRACK_MIN_CLIP_PX = 72
export const RECIPE_RULER_TICK_SEC = 5

function packedPlateCount(recipe: RecipeProject, shot: RecipeShot): number {
  const names = new Set((shot.characterNames || []).map((name) => name.trim()).filter(Boolean))
  let characters = recipe.characters.filter((item) => item.imageUrl || item.imageJobId)
  if (names.size) characters = characters.filter((item) => names.has(item.name))
  let locations = recipe.locations.filter((item) => item.imageUrl || item.imageJobId)
  if (shot.locationName.trim()) {
    const matched = locations.filter((item) => item.name === shot.locationName)
    if (matched.length) locations = matched
  }
  return characters.length + locations.length
}

export function recipeShotLayout(shots: RecipeShot[]): RecipeShotLayoutItem[] {
  let startSec = 0
  return shots.map((shot) => {
    const duration = Math.max(0, Number(shot.durationSec) || 0)
    const item = { shot, startSec, endSec: startSec + duration }
    startSec += duration
    return item
  })
}

export function recipeShotAtPlayhead(shots: RecipeShot[], timeSec: number): RecipeShotLayoutItem | null {
  const layout = recipeShotLayout(shots)
  if (!layout.length) return null
  const time = Number.isFinite(timeSec) ? Math.max(0, timeSec) : 0
  return layout.find((item) => time >= item.startSec && time < item.endSec) || layout[layout.length - 1]
}

export function recipeShotSubjectLabels(shot: RecipeShot): string[] {
  return [
    ...(shot.characterNames || []).map((name) => name.trim()).filter(Boolean),
    (shot.locationName || "").trim(),
  ].filter(Boolean)
}

export function recipeShotHasFirstFrame(shot: RecipeShot): boolean {
  return Boolean(shot.firstFrameUrl || shot.stillUrl)
}

export function recipeShotHasEndFrame(shot: RecipeShot): boolean {
  return Boolean(shot.endFrameUrl)
}

export function recipeTrackLayout(shots: RecipeShot[], pixelsPerSecond: number): RecipeTrackClip[] {
  const pps = Math.max(1, Number(pixelsPerSecond) || 0)
  return recipeShotLayout(shots).map((item) => ({
    ...item,
    left: item.startSec * pps,
    width: (item.endSec - item.startSec) * pps,
  }))
}

export function recipeTimelineMinimumPixelsPerSecond(shots: RecipeShot[]): number {
  const durations = shots
    .map((shot) => Math.max(0, Number(shot.durationSec) || 0))
    .filter((duration) => duration > 0)
  if (!durations.length) return 24
  return Math.min(120, Math.max(24, Math.ceil(RECIPE_TRACK_MIN_CLIP_PX / Math.min(...durations))))
}

export function recipeTrackCanvasWidth(shots: RecipeShot[], pixelsPerSecond: number, trailingPx = 88): number {
  const layout = recipeShotLayout(shots)
  const total = layout.length ? layout[layout.length - 1].endSec : 0
  return Math.max(total * Math.max(1, Number(pixelsPerSecond) || 0) + trailingPx, 640)
}

export function recipeTrackClipIdsInRange(clips: RecipeTrackClip[], left: number, right: number): string[] {
  const low = Math.min(left, right)
  const high = Math.max(left, right)
  return clips
    .filter((item) => item.left + item.width > low && item.left < high)
    .map((item) => item.shot.id)
}

export function recipeRulerTicks(totalDurationSec: number, stepSec: number = RECIPE_RULER_TICK_SEC): number[] {
  const step = stepSec > 0 ? stepSec : RECIPE_RULER_TICK_SEC
  const maxSec = Math.max(totalDurationSec, 15)
  const ticks: number[] = []
  for (let second = 0; second <= maxSec; second += step) ticks.push(second)
  return ticks
}

export function recipeRulerShotEdges(shots: RecipeShot[]): number[] {
  const edges = new Set<number>()
  for (const item of recipeShotLayout(shots)) {
    edges.add(item.startSec)
    edges.add(item.endSec)
  }
  return Array.from(edges).sort((a, b) => a - b)
}

export function recipeRulerSeekSec(
  offsetPx: number,
  pixelsPerSecond: number,
  totalDurationSec: number,
  options?: { snap?: boolean; shots?: RecipeShot[] },
): number {
  const maxSec = Math.max(0, Number(totalDurationSec) || 0)
  const pps = Math.max(1, Number(pixelsPerSecond) || 0)
  const raw = Math.min(maxSec, Math.max(0, offsetPx / pps))
  if (!options?.snap) return raw
  let nearest = Math.round(raw)
  let best = Math.abs(nearest - raw)
  for (const edge of recipeRulerShotEdges(options.shots || [])) {
    const distance = Math.abs(edge - raw)
    if (distance < best) {
      best = distance
      nearest = edge
    }
  }
  return Math.min(maxSec, Math.max(0, nearest))
}

export function recipeShotVideoUrl(shot: RecipeShot): string {
  return recipeShotPreferredTake(shot)?.videoUrl || shot.outputVideoUrl || ""
}

export function recipeShotStillUrl(shot: RecipeShot): string {
  return shot.stillUrl || shot.firstFrameUrl || ""
}

export function recipePlayableShots(shots: RecipeShot[]): RecipeShot[] {
  return shots.filter((shot) => Boolean(recipeShotVideoUrl(shot)) && shotIsMuxable(shot))
}

export function assignRecipeShotPlate(
  recipe: RecipeProject,
  shot: RecipeShot,
  plate: { name: string; kind: "character" | "location" },
): { shot: RecipeShot; rejected: boolean } {
  const name = plate.name.trim()
  if (!name) return { shot, rejected: true }
  const next: RecipeShot = plate.kind === "location"
    ? { ...shot, locationName: shot.locationName === name ? "" : name }
    : {
      ...shot,
      characterNames: (shot.characterNames || []).includes(name)
        ? (shot.characterNames || []).filter((item) => item !== name)
        : [...(shot.characterNames || []), name],
    }
  return packedPlateCount(recipe, next) > 9
    ? { shot, rejected: true }
    : { shot: next, rejected: false }
}

export function dressedRecipePlates(recipe: RecipeProject): Array<{
  id: string
  name: string
  kind: "character" | "location"
  imageUrl: string
}> {
  return [
    ...recipe.characters
      .filter((item) => Boolean(item.imageUrl))
      .map((item) => ({ id: item.id, name: item.name, kind: "character" as const, imageUrl: item.imageUrl || "" })),
    ...recipe.locations
      .filter((item) => Boolean(item.imageUrl))
      .map((item) => ({ id: item.id, name: item.name, kind: "location" as const, imageUrl: item.imageUrl || "" })),
  ]
}
