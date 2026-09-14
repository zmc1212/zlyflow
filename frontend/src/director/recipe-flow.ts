import { flattenRecipeShots, recipeShotPreferredTake, shotIsMuxable, type RecipeProject, type RecipeShot } from "./recipe-model"
import { placeholderBoard, recipeReadiness, type RecipeStageId } from "./recipe-readiness"
import { directorStatusLabel } from "./status-labels"

/** Execution and adopted media are independent: a failed retry never hides an older usable take. */
export function recipeShotFlow(shot: RecipeShot) {
  const latest = shot.takes?.at(-1)
  const running = ["queued", "running", "submitting"].includes(shot.status)
  const status = running ? shot.status : latest?.status || shot.status
  const usable = shotIsMuxable(shot)
  const preferred = recipeShotPreferredTake(shot)
  const adopted = Boolean(preferred && (preferred.id || preferred.jobId) === shot.approvedTakeId)
  return {
    status, usable, running: running || ["queued", "running"].includes(status),
    label: `视频${directorStatusLabel(status)} · ${adopted ? "已采用版本" : usable ? "有可用版本" : "未采用版本"}`,
    error: latest?.error || shot.error || "",
  }
}

export function recipeStageFlow(recipe: RecipeProject, stage: RecipeStageId, goal = "") {
  const allShots = flattenRecipeShots(recipe)
  const readiness = recipeReadiness(recipe, goal)
  const boardIsPlaceholder = placeholderBoard(allShots, goal, (recipe.script.fullStory || "").trim())
  const shots = boardIsPlaceholder ? [] : allShots
  const missing = shots.filter((shot) => !shotIsMuxable(shot))
  const pending = missing.filter((shot) => !recipeShotFlow(shot).running)
  const next: Record<RecipeStageId, RecipeStageId> = {
    script: "characters", art_style: "characters",
    characters: "shots", locations: "shots", props: "shots", shots: "voice", voice: "music", music: "export", export: "shots",
  }
  let summary = `${readiness[stage].done} / ${readiness[stage].total} 项已准备`
  if (stage === "shots" || stage === "export") summary = shots.length
    ? `${shots.length} 镜已设计 · ${shots.length - missing.length} / ${shots.length} 镜可用`
    : "还没有分镜，可生成或手动导入"
  if (stage === "voice" && !shots.some((shot) => shot.dialogue.trim())) summary = shots.length ? "无需配音：当前镜头没有对白" : "先设计镜头，再检查对白与配音"
  if (stage === "music" && !recipe.audio?.bgmUrl) summary = "配乐可选，可上传音频或直接进入成片"
  if ((stage === "characters" && !recipe.characters.length) || (stage === "locations" && !recipe.locations.length) || (stage === "props" && !(recipe.props || []).length)) summary = "暂无参考素材，可直接制作文生镜头，也可导入素材"
  return { summary, nextStage: next[stage], missing, pending }
}
