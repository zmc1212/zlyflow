import { snapH3DurationSec } from "./prompt-compiler"
import {
  RECIPE_TRACK_MIN_CLIP_PX,
  assignRecipeShotPlate,
  createEmptyRecipe,
  createEmptyRecipeShot,
  duplicateRecipeShot,
  flattenRecipeShots,
  insertRecipeShotAfter,
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
      { id: "c1", name: "侦探", description: "风衣", promptText: "detective", gender: "male", type: "character", imageUrl: "/c1.png" },
      { id: "c2", name: "女人", description: "红伞", promptText: "woman", gender: "female", type: "character", imageUrl: "/c2.png" },
    ],
    locations: [
      { id: "l1", name: "暗巷", description: "霓虹", promptText: "alley", imageUrl: "/l1.png" },
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
  const short = recipeTrackLayout([sampleShot({ id: "tiny", durationSec: 1 })], 24)
  if (short[0].width !== RECIPE_TRACK_MIN_CLIP_PX) {
    throw new Error("very short clips must keep a readable min width")
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
  crowdedRecipe.characters = Array.from({ length: 9 }, (_, index) => ({
    id: `c${index + 1}`,
    name: String(index + 1),
    description: "",
    promptText: "",
    gender: "unspecified" as const,
    type: "character" as const,
    imageUrl: `/${index + 1}.png`,
  }))
  crowdedRecipe.locations = [{ id: "l1", name: "暗巷", description: "", promptText: "", imageUrl: "/l1.png" }]
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
    }],
  })
  if (recipeShotVideoUrl(playable) !== "/take.mp4") {
    throw new Error("recipeShotVideoUrl must prefer the active take")
  }
  if (recipePlayableShots([a, playable]).map((shot) => shot.id).join(",") !== "p1") {
    throw new Error("recipePlayableShots must only include muxable takes")
  }
  if (recipeShotsToPlayer([playable])[0].outputVideoUrl !== "/take.mp4") {
    throw new Error("player adapter must expose the take video for 串播")
  }
  if (snapH3DurationSec(1) !== 2 || snapH3DurationSec(16) !== 15) {
    throw new Error("timeline duration edits must still snap to H3 2–15s")
  }
}

assertDirectorTimelineContract()
