import { recipeShotPreferredTake, type RecipeProject, type RecipeShot } from "./recipe-model"

export const RECIPE_STAGE_IDS = [
  "script",
  "art_style",
  "characters",
  "locations",
  "storyboard",
  "shots",
  "voice",
  "music",
  "export",
] as const

export type RecipeStageId = (typeof RECIPE_STAGE_IDS)[number]
export type RecipeReadinessLevel = "empty" | "draft" | "partial" | "ready"

export interface RecipeReadinessItem {
  level: RecipeReadinessLevel
  done: number
  total: number
}

export type RecipeReadiness = Record<RecipeStageId, RecipeReadinessItem>

export const RECIPE_STAGE_LABELS: Record<RecipeStageId, string> = {
  script: "剧本",
  art_style: "画风",
  storyboard: "分镜设计",
  characters: "角色定妆",
  locations: "场景定妆",
  shots: "镜头生成",
  voice: "配音",
  music: "配乐",
  export: "成片",
}

export const RECIPE_STAGE_GROUPS = [
  { id: "plan", label: "方案", stages: ["script", "art_style"] },
  { id: "production", label: "视觉制作", stages: ["characters", "locations", "storyboard", "shots"] },
  { id: "sound", label: "声音", stages: ["voice", "music"] },
  { id: "delivery", label: "交付", stages: ["export"] },
] as const

export const RECIPE_READINESS_LABELS: Record<RecipeReadinessLevel, string> = {
  empty: "未开始",
  draft: "草稿",
  partial: "部分完成",
  ready: "已就绪",
}

export const RECIPE_READINESS_TAG_COLOR: Record<RecipeReadinessLevel, string> = {
  empty: "default",
  draft: "processing",
  partial: "warning",
  ready: "success",
}

const LEGACY_RECIPE_STAGES: Record<string, RecipeStageId> = {
  story: "script",
  style: "art_style",
  assets: "characters",
  board: "storyboard",
}

export function parseRecipeStage(value: string | null | undefined): RecipeStageId | null {
  const key = (value || "").trim()
  if (RECIPE_STAGE_IDS.includes(key as RecipeStageId)) return key as RecipeStageId
  return LEGACY_RECIPE_STAGES[key] || null
}

export const DIRECTOR_RECIPE_VIEWS = ["plan", "timeline"] as const
export type DirectorRecipeView = (typeof DIRECTOR_RECIPE_VIEWS)[number]

export const DIRECTOR_RECIPE_VIEW_LABELS: Record<DirectorRecipeView, string> = {
  plan: "方案",
  timeline: "剪辑",
}

export function parseDirectorRecipeView(value: string | null | undefined): DirectorRecipeView {
  return (value || "").trim().toLowerCase() === "timeline" ? "timeline" : "plan"
}

export function resolveDirectorRecipeView(
  value: string | null | undefined,
  options?: { mobile?: boolean },
): DirectorRecipeView {
  if (options?.mobile) return "plan"
  return parseDirectorRecipeView(value)
}

function readinessItem(level: RecipeReadinessLevel, done: number, total: number): RecipeReadinessItem {
  return { level, done, total }
}

function ratioReadiness(done: number, total: number): RecipeReadinessItem {
  if (total <= 0) return readinessItem("empty", 0, 0)
  if (done <= 0) return readinessItem("draft", 0, total)
  if (done >= total) return readinessItem("ready", total, total)
  return readinessItem("partial", done, total)
}

function shots(recipe: RecipeProject): RecipeShot[] {
  return recipe.scenes.flatMap((scene) => scene.shots)
}

function placeholderBoard(items: RecipeShot[], goal: string, fullStory: string): boolean {
  if (!items.length) return true
  if (items.length > 1) return false
  const shot = items[0]
  const description = (shot.description || "").trim()
  const prompt = (shot.promptText || "").trim()
  const idea = goal.trim()
  const story = fullStory.trim()
  const dummyTitle = !shot.title || shot.title === "主镜头" || shot.title === "开场"
  const descriptionIsIdea = !description || description === idea || description === story
  const noPrompt = !prompt || prompt === description || prompt === idea
  return dummyTitle && descriptionIsIdea && noPrompt
}

function isMuxable(shot: RecipeShot): boolean {
  const failed = new Set(["failed", "interrupted", "cancelled", "stopped"])
  const take = recipeShotPreferredTake(shot)
  if (take) return true
  if (failed.has(shot.status)) return false
  return shot.status === "succeeded" && Boolean(shot.outputVideoUrl || shot.jobId)
}

/** Pure payload-derived readiness; agent execution status is deliberately ignored. */
export function recipeReadiness(recipe: RecipeProject, goal: string = ""): RecipeReadiness {
  const story = (recipe.script.fullStory || "").trim()
  const title = (recipe.script.title || "").trim()
  const summary = (recipe.script.summary || "").trim()
  const script = story
    ? readinessItem("ready", 1, 1)
    : title || summary
      ? readinessItem("draft", 0, 1)
      : readinessItem("empty", 0, 1)
  const artStyle = recipe.artStyle && (recipe.artStyle.id || recipe.artStyle.name)
    ? readinessItem("ready", 1, 1)
    : readinessItem("empty", 0, 1)
  const allShots = shots(recipe)
  const designedShots = placeholderBoard(allShots, goal, story) ? [] : allShots
  const storyboard = designedShots.length
    ? readinessItem("ready", designedShots.length, designedShots.length)
    : readinessItem("empty", 0, 0)
  const characters = ratioReadiness(
    recipe.characters.filter((item) => Boolean(item.imageUrl)).length,
    recipe.characters.length,
  )
  const locations = ratioReadiness(
    recipe.locations.filter((item) => Boolean(item.imageUrl)).length,
    recipe.locations.length,
  )
  const shotRenders = ratioReadiness(designedShots.filter(isMuxable).length, designedShots.length)
  const dialogueShots = designedShots.filter((shot) => (shot.dialogue || "").trim())
  const voicedShots = dialogueShots.filter((shot) => shot.ttsStatus === "succeeded")
  const voiceAssigned = recipe.characters.some((item) => Boolean(item.voiceId))
  const voice = dialogueShots.length
    ? ratioReadiness(voicedShots.length, dialogueShots.length)
    : voiceAssigned
      ? readinessItem("draft", 0, 0)
      : readinessItem("empty", 0, 0)
  const bgmUrl = (recipe.audio?.bgmUrl || "").trim()
  const musicHint = (recipe.globalMusic || "").trim()
  const music = bgmUrl
    ? readinessItem("ready", 1, 1)
    : musicHint
      ? readinessItem("draft", 0, 1)
      : readinessItem("empty", 0, 1)
  const muxStatus = recipe.export?.muxStatus || "idle"
  const exported = muxStatus === "succeeded"
    ? readinessItem("ready", 1, 1)
    : muxStatus === "queued" || muxStatus === "running"
      ? readinessItem("draft", 0, 1)
      : muxStatus === "failed"
        ? readinessItem("partial", 0, 1)
        : readinessItem("empty", 0, 1)

  return {
    script,
    art_style: artStyle,
    storyboard,
    characters,
    locations,
    shots: shotRenders,
    voice,
    music,
    export: exported,
  }
}
