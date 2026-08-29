import {
  createEmptyRecipe,
  parseRecipeStage,
  recipeReadiness,
  RECIPE_STAGE_GROUPS,
  RECIPE_STAGE_IDS,
  RecipeProject,
  RecipeShot,
} from "./types"

function sampleShot(overrides?: Partial<RecipeShot>): RecipeShot {
  return {
    id: "shot-1",
    shotNumber: 1,
    title: "雨夜追车",
    description: "侦探穿过霓虹暗巷",
    promptText: "A medium shot of a detective walking through a neon alley.",
    dialogue: "",
    characterNames: ["侦探"],
    locationName: "暗巷",
    durationSec: 5,
    compiledPrompt: "",
    status: "idle",
    takes: [],
    ...overrides,
  }
}

function withShot(recipe: RecipeProject, shot: RecipeShot): RecipeProject {
  return {
    ...recipe,
    scenes: [{
      id: "sc1",
      sceneNumber: 1,
      title: "开场",
      description: "",
      locationName: shot.locationName,
      shots: [shot],
    }],
  }
}

/** Compile-time + runtime contract checks used by `pnpm --dir frontend build`. */
export function assertRecipeReadinessContract(): void {
  const empty = createEmptyRecipe()
  const emptyReady = recipeReadiness(empty)
  for (const stage of RECIPE_STAGE_IDS) {
    if (emptyReady[stage].level !== "empty") {
      throw new Error(`empty recipe ${stage} must be empty, got ${emptyReady[stage].level}`)
    }
  }

  const lyingAgents = createEmptyRecipe()
  lyingAgents.agentStatus = lyingAgents.agentStatus.map((item) => ({
    ...item,
    status: "completed",
    message: "已完成",
  }))
  const ignoredAgents = recipeReadiness(lyingAgents)
  if (ignoredAgents.script.level !== "empty" || ignoredAgents.voice.level !== "empty" || ignoredAgents.export.level !== "empty") {
    throw new Error("recipeReadiness must ignore agentStatus and derive from payload artifacts")
  }

  const titled = createEmptyRecipe("雨夜")
  if (recipeReadiness(titled).script.level !== "draft") {
    throw new Error("title without fullStory must be script draft")
  }
  titled.script.fullStory = "侦探在雨夜里穿过霓虹暗巷，追上撑红伞的女人。"
  if (recipeReadiness(titled).script.level !== "ready") {
    throw new Error("fullStory must make script ready")
  }

  titled.artStyle = { id: "as_1001", name: "电影感", promptPrefix: "cinematic" }
  if (recipeReadiness(titled).art_style.level !== "ready") {
    throw new Error("artStyle must make art_style ready")
  }

  const placeholder = withShot(titled, sampleShot({
    title: "主镜头",
    description: titled.script.fullStory,
    promptText: titled.script.fullStory,
  }))
  if (recipeReadiness(placeholder, "").storyboard.level !== "empty") {
    throw new Error("placeholder board must not count as designed storyboard")
  }

  const boarded = withShot(titled, sampleShot())
  const boardedReady = recipeReadiness(boarded)
  if (boardedReady.storyboard.level !== "ready" || boardedReady.shots.level !== "draft") {
    throw new Error("real shots without takes must be storyboard ready and shots draft")
  }

  boarded.characters = [{
    id: "c1", name: "侦探", description: "风衣", promptText: "detective", gender: "male", type: "character",
  }]
  boarded.locations = [{
    id: "l1", name: "暗巷", description: "霓虹", promptText: "alley",
  }]
  const looksEmpty = recipeReadiness(boarded)
  if (looksEmpty.characters.level !== "draft" || looksEmpty.locations.level !== "draft") {
    throw new Error("named assets without imageUrl must be draft")
  }
  boarded.characters[0].imageUrl = "/api/jobs/c1/outputs/0/download"
  boarded.locations[0].imageUrl = "/api/jobs/l1/outputs/0/download"
  const looksReady = recipeReadiness(boarded)
  if (looksReady.characters.level !== "ready" || looksReady.locations.level !== "ready") {
    throw new Error("imageUrl must make character/location ready")
  }

  boarded.characters.push({
    id: "c2", name: "女人", description: "红伞", promptText: "woman", gender: "female", type: "character",
  })
  if (recipeReadiness(boarded).characters.level !== "partial") {
    throw new Error("some looks must be characters partial")
  }

  const oneTake = withShot(boarded, sampleShot({
    status: "succeeded",
    outputVideoUrl: "/api/media/shot.mp4",
    takes: [{
      id: "take-1",
      takeNumber: 1,
      status: "succeeded",
      progress: 100,
      videoUrl: "/api/media/shot.mp4",
      createdAt: "2026-08-30T00:00:00.000Z",
    }],
  }))
  if (recipeReadiness(oneTake).shots.level !== "ready") {
    throw new Error("muxable take must make shots ready")
  }

  const voicedDraft = withShot(boarded, sampleShot({ dialogue: "站住！" }))
  voicedDraft.characters[0].voiceId = "onyx"
  const voiceReady = recipeReadiness(voicedDraft)
  if (voiceReady.voice.level !== "draft") {
    throw new Error("voiceId without ttsUrl must be voice draft")
  }
  voicedDraft.scenes[0].shots[0].ttsStatus = "succeeded"
  voicedDraft.scenes[0].shots[0].ttsUrl = "/api/media/line.mp3"
  if (recipeReadiness(voicedDraft).voice.level !== "ready") {
    throw new Error("succeeded dialogue tts must make voice ready")
  }

  boarded.globalMusic = "低沉电子脉冲"
  if (recipeReadiness(boarded).music.level !== "draft") {
    throw new Error("globalMusic hint without bgmUrl must be music draft")
  }
  boarded.audio = { bgmUrl: "/api/media/bgm.mp3", bgmVolume: 0.25, bgmFadeInSec: 1, bgmFadeOutSec: 2 }
  if (recipeReadiness(boarded).music.level !== "ready") {
    throw new Error("bgmUrl must make music ready")
  }

  boarded.export = { muxStatus: "running" }
  if (recipeReadiness(boarded).export.level !== "draft") {
    throw new Error("mux running must be export draft")
  }
  boarded.export = { muxStatus: "succeeded", muxUrl: "/api/media/film.mp4" }
  if (recipeReadiness(boarded).export.level !== "ready") {
    throw new Error("mux succeeded must make export ready")
  }

  if (parseRecipeStage(null) !== null || parseRecipeStage("research") !== null) {
    throw new Error("unknown stage query must be rejected")
  }
  if (parseRecipeStage("script") !== "script" || parseRecipeStage("board") !== "storyboard") {
    throw new Error("stage query must accept current ids and legacy tab keys")
  }
  const grouped = RECIPE_STAGE_GROUPS.flatMap((group) => group.stages)
  if (grouped.join(",") !== RECIPE_STAGE_IDS.join(",")) {
    throw new Error("stage groups must cover every user task and omit research/media")
  }
}

assertRecipeReadinessContract()
