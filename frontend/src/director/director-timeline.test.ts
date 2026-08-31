import { describe, expect, it } from "vitest"
import { snapH3DurationSec } from "./prompt-compiler"
import {
  directorFramesToSeconds,
  directorSecondsToFrames,
  directorTimelineFrameLayout,
  directorTimelineMoveTargetIndex,
  directorTimelineResizeDraftFrames,
  directorTimelineSnapFrame,
} from "./director-timeline-engine"
import {
  clampTransportFrame,
  formatTransportTimecode,
  playbackStartFrame,
  stepTransportFrame,
} from "./opencut-timeline/transport"
import {
  RECIPE_TRACK_MIN_CLIP_PX,
  assignRecipeShotPlate,
  createEmptyRecipe,
  createEmptyRecipeCharacter,
  createEmptyRecipeLocation,
  createEmptyRecipeShot,
  duplicateRecipeShot,
  flattenRecipeShots,
  insertRecipeShotAfter,
  moveRecipeShotToIndex,
  recipePlayableShots,
  recipeRulerSeekSec,
  recipeRulerShotEdges,
  recipeRulerTicks,
  recipeShotAtPlayhead,
  recipeShotHasEndFrame,
  recipeShotHasFirstFrame,
  recipeShotLayout,
  recipeShotSubjectLabels,
  recipeShotsToPlayer,
  recipeShotVideoUrl,
  recipeTimelineMinimumPixelsPerSecond,
  recipeTrackCanvasWidth,
  recipeTrackClipIdsInRange,
  recipeTrackLayout,
  removeRecipeShot,
  RecipeProject,
  RecipeShot,
} from "./types"

function sampleShot(overrides?: Partial<RecipeShot>): RecipeShot {
  return {
    ...createEmptyRecipeShot(overrides?.shotNumber || 1, overrides?.durationSec || 5),
    id: overrides?.id || "shot-1",
    title: "雨夜追车",
    description: "侦探穿过霓虹暗巷",
    characterNames: ["侦探"],
    locationName: "暗巷",
    ...overrides,
  }
}

function withShots(shots: RecipeShot[]): RecipeProject {
  const recipe = createEmptyRecipe("雨夜")
  return {
    ...recipe,
    characters: [
      createEmptyRecipeCharacter({ id: "c1", name: "侦探", description: "风衣", promptText: "detective", gender: "male", imageUrl: "/c1.png" }),
      createEmptyRecipeCharacter({ id: "c2", name: "女人", description: "红伞", promptText: "woman", gender: "female", imageUrl: "/c2.png" }),
    ],
    locations: [
      createEmptyRecipeLocation({ id: "l1", name: "暗巷", description: "霓虹", promptText: "alley", imageUrl: "/l1.png" }),
    ],
    scenes: [{
      id: "sc1",
      sceneNumber: 1,
      title: "开场",
      description: "",
      locationName: "暗巷",
      shots,
    }],
  }
}

/** Compile-time + runtime contract checks used by `pnpm --dir frontend build`. */
export function assertDirectorTimelineContract(): void {
  const a = sampleShot({ id: "a", shotNumber: 1, durationSec: 5 })
  const b = sampleShot({ id: "b", shotNumber: 2, durationSec: 8, title: "追上" })
  const layout = recipeShotLayout([a, b])
  if (layout[0].startSec !== 0 || layout[0].endSec !== 5) {
    throw new Error("first shot must start at 0")
  }
  if (layout[1].startSec !== 5 || layout[1].endSec !== 13) {
    throw new Error("second shot must follow durationSec")
  }
  if (recipeShotAtPlayhead([a, b], 0)?.shot.id !== "a" || recipeShotAtPlayhead([a, b], 4.9)?.shot.id !== "a") {
    throw new Error("playhead in first clip must select first shot")
  }
  if (recipeShotAtPlayhead([a, b], 5)?.shot.id !== "b" || recipeShotAtPlayhead([a, b], 12)?.shot.id !== "b") {
    throw new Error("playhead in second clip must select second shot")
  }
  if (recipeShotAtPlayhead([a, b], 99)?.shot.id !== "b") {
    throw new Error("playhead past the end must clamp to last shot")
  }

  const player = recipeShotsToPlayer([a, b])
  if (player[0].startSec !== 0 || player[1].startSec !== 5) {
    throw new Error("recipeShotsToPlayer must accumulate startSec")
  }
  if (player[0].referencedSubjectIds.join(",") !== "侦探,暗巷") {
    throw new Error("player adapter must carry character and location names")
  }
  if (recipeShotSubjectLabels(a).join(",") !== "侦探,暗巷") {
    throw new Error("track labels must read characterNames and locationName")
  }

  const clips = recipeTrackLayout([a, b], 40)
  if (clips[0].left !== 0 || clips[0].width !== 200) {
    throw new Error("track clips must use durationSec * pixelsPerSecond")
  }
  if (clips[1].left !== 200 || clips[1].width !== 320) {
    throw new Error("second clip must start after the first durationSec")
  }
  const tiny = sampleShot({ id: "tiny", durationSec: 1 })
  const short = recipeTrackLayout([tiny], 24)
  if (short[0].width !== 24) {
    throw new Error("clip width must remain exactly duration * pixelsPerSecond")
  }
  const minimumZoom = recipeTimelineMinimumPixelsPerSecond([tiny])
  if (minimumZoom !== RECIPE_TRACK_MIN_CLIP_PX || recipeTrackLayout([tiny], minimumZoom)[0].width !== RECIPE_TRACK_MIN_CLIP_PX) {
    throw new Error("minimum zoom must make the shortest clip readable without distorting its duration")
  }
  if (recipeTrackClipIdsInRange(clips, 180, 220).join(",") !== "a,b") {
    throw new Error("marquee must select RecipeShot ids that overlap the drag range")
  }
  if (recipeTrackCanvasWidth([a, b], 40) < 13 * 40) {
    throw new Error("track canvas must be at least the RecipeShot duration span")
  }
  if (!recipeShotHasFirstFrame(sampleShot({ stillUrl: "/still.png" })) || recipeShotHasEndFrame(a)) {
    throw new Error("first-frame diamond must treat stillUrl as set")
  }
  if (recipeRulerTicks(13).join(",") !== "0,5,10,15") {
    throw new Error("ruler ticks must cover RecipeShot duration in 5s steps")
  }
  if (recipeRulerShotEdges([a, b]).join(",") !== "0,5,13") {
    throw new Error("ruler must mark RecipeShot boundaries")
  }
  if (recipeRulerSeekSec(200, 40, 13, { snap: true, shots: [a, b] }) !== 5) {
    throw new Error("ruler snap must prefer a RecipeShot edge over a raw pixel time")
  }
  if (recipeRulerSeekSec(90, 40, 13, { snap: false }) !== 2.25) {
    throw new Error("ruler without snap must keep the raw RecipeShot time")
  }

  const missing = sampleShot({ id: "missing", durationSec: 3, status: "idle", outputVideoUrl: null })
  const playableAfterGap = sampleShot({
    id: "playable-after-gap",
    durationSec: 4,
    status: "succeeded",
    outputVideoUrl: "/after-gap.mp4",
  })
  const gappedLayout = recipeShotLayout([missing, playableAfterGap])
  if (recipePlayableShots([missing, playableAfterGap]).map((shot) => shot.id).join(",") !== "playable-after-gap") {
    throw new Error("playable filtering must exclude missing video")
  }
  if (gappedLayout[1].startSec !== 3 || gappedLayout[1].endSec !== 7) {
    throw new Error("a missing first clip must retain its full timeline gap")
  }

  const recipe = withShots([a])
  const addedCharacter = assignRecipeShotPlate(recipe, a, { name: "女人", kind: "character" })
  if (addedCharacter.rejected || !addedCharacter.shot.characterNames.includes("女人")) {
    throw new Error("assigning a dressed character must add characterNames")
  }
  const toggledOff = assignRecipeShotPlate(recipe, addedCharacter.shot, { name: "侦探", kind: "character" })
  if (toggledOff.shot.characterNames.includes("侦探")) {
    throw new Error("assigning an already attached character must toggle it off")
  }
  const locationOff = assignRecipeShotPlate(recipe, a, { name: "暗巷", kind: "location" })
  if (locationOff.shot.locationName !== "") {
    throw new Error("assigning the current location must clear locationName")
  }

  const crowded = sampleShot({
    characterNames: ["1", "2", "3", "4", "5", "6", "7", "8"],
    locationName: "暗巷",
  })
  const crowdedRecipe = createEmptyRecipe()
  crowdedRecipe.characters = Array.from({ length: 9 }, (_, index) => createEmptyRecipeCharacter({
    id: `c${index + 1}`,
    name: String(index + 1),
    imageUrl: `/${index + 1}.png`,
  }))
  crowdedRecipe.locations = [createEmptyRecipeLocation({ id: "l1", name: "暗巷", imageUrl: "/l1.png" })]
  const overflow = assignRecipeShotPlate(crowdedRecipe, crowded, { name: "9", kind: "character" })
  if (!overflow.rejected || overflow.shot.characterNames.includes("9")) {
    throw new Error("assignRecipeShotPlate must reject a 10th packed plate")
  }

  const inserted = insertRecipeShotAfter(recipe, "a")
  const insertedShots = flattenRecipeShots(inserted.recipe)
  if (insertedShots.length !== 2 || insertedShots[1].id !== inserted.shot.id || insertedShots[1].shotNumber !== 2) {
    throw new Error("insertRecipeShotAfter must append and renumber")
  }
  const duplicated = duplicateRecipeShot(inserted.recipe, "a")
  if (!duplicated || flattenRecipeShots(duplicated.recipe).length !== 3 || duplicated.shot.takes.length) {
    throw new Error("duplicateRecipeShot must copy after the source and clear takes")
  }
  const removed = removeRecipeShot(duplicated.recipe, duplicated.shot.id)
  if (flattenRecipeShots(removed).some((shot) => shot.id === duplicated.shot.id)) {
    throw new Error("removeRecipeShot must drop the copy")
  }
  if (flattenRecipeShots(removeRecipeShot(recipe, "a")).length !== 1) {
    throw new Error("removeRecipeShot must keep the last remaining shot")
  }

  const playable = sampleShot({
    id: "p1",
    status: "succeeded",
    outputVideoUrl: "/shot.mp4",
    takes: [{
      id: "t1",
      takeNumber: 1,
      status: "succeeded",
      progress: 100,
      videoUrl: "/take.mp4",
      createdAt: "2026-08-30T00:00:00.000Z",
    }, {
      id: "t2",
      takeNumber: 2,
      status: "succeeded",
      progress: 100,
      videoUrl: "/take-latest.mp4",
      createdAt: "2026-08-30T00:01:00.000Z",
    }, {
      id: "t3",
      takeNumber: 3,
      status: "failed",
      progress: 0,
      error: "new render failed",
      createdAt: "2026-08-30T00:02:00.000Z",
    }],
    activeTakeIndex: 0,
  })
  if (recipeShotVideoUrl(playable) !== "/take-latest.mp4") {
    throw new Error("recipeShotVideoUrl must ignore legacy preview indexes and prefer the latest usable take")
  }
  if (recipePlayableShots([a, playable]).map((shot) => shot.id).join(",") !== "p1") {
    throw new Error("recipePlayableShots must only include muxable takes")
  }
  if (recipeShotsToPlayer([playable])[0].outputVideoUrl !== "/take-latest.mp4") {
    throw new Error("player adapter must expose the take video for 串播")
  }
  if (snapH3DurationSec(1) !== 2 || snapH3DurationSec(16) !== 15) {
    throw new Error("timeline duration edits must still snap to H3 2–15s")
  }

  const frameLayout = directorTimelineFrameLayout([a, b])
  if (frameLayout[0].durationFrames !== 120 || frameLayout[1].startFrame !== 120 || frameLayout[1].endFrame !== 312) {
    throw new Error("OpenCut adapter must represent the contiguous director timeline at 24fps")
  }
  const resizeDraftFrames = directorTimelineResizeDraftFrames(a, 25, 100)
  if (resizeDraftFrames !== 126 || directorFramesToSeconds(resizeDraftFrames) !== 5.25) {
    throw new Error("resize preview must retain frame precision instead of committing each mouse move")
  }
  const snapped = directorTimelineSnapFrame(118, [a, b], 48, { enabled: true })
  if (!snapped.snapped || snapped.frame !== directorSecondsToFrames(5)) {
    throw new Error("OpenCut adapter must snap to neighboring clip boundaries")
  }
  if (directorTimelineMoveTargetIndex([a, b], "a", 999) !== 1) {
    throw new Error("drag resolver must append a clip when dropped beyond the remaining track")
  }
  if (formatTransportTimecode(3 * 24 + 8, 24) !== "00:00:03:08") {
    throw new Error("player timecode must retain OpenCut's HH:MM:SS:FF format")
  }
  if (stepTransportFrame(0, -1, 240) !== 0 || stepTransportFrame(239, 1, 240) !== 240) {
    throw new Error("transport stepping must clamp at the timeline boundaries")
  }
  if (clampTransportFrame(999, 240) !== 240 || playbackStartFrame(240, 240) !== 0) {
    throw new Error("transport end must stay seekable and replay from frame zero")
  }

  const crossSceneRecipe = withShots([a])
  crossSceneRecipe.scenes.push({
    id: "sc2",
    sceneNumber: 2,
    title: "追逐",
    description: "",
    locationName: "暗巷",
    shots: [b],
  })
  const movedAcrossScenes = moveRecipeShotToIndex(crossSceneRecipe, "b", 0)
  if (flattenRecipeShots(movedAcrossScenes).map((shot) => shot.id).join(",") !== "b,a") {
    throw new Error("timeline drag commit must reorder RecipeShot across scene boundaries")
  }
  if (flattenRecipeShots(movedAcrossScenes).map((shot) => shot.shotNumber).join(",") !== "1,2") {
    throw new Error("timeline drag commit must renumber shots after moving")
  }
  if (movedAcrossScenes.scenes.length !== 1 || movedAcrossScenes.scenes.some((scene) => scene.shots.length === 0)) {
    throw new Error("timeline drag commit must remove an emptied source scene before backend normalization")
  }
}

describe("director timeline", () => {
  it("keeps timeline editing and playback contracts", () => {
    expect(() => assertDirectorTimelineContract()).not.toThrow()
  })
})
