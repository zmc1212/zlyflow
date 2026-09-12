import { flattenRecipeShots, type RecipeProject } from "./recipe-model"

/** Pipeline steps that ask the user a few confirm questions before generating. */
export const GUIDED_STEP_AGENTS = ["art_style", "characters", "locations", "storyboard", "voice", "music"] as const

export type GuidedStepAgent = (typeof GUIDED_STEP_AGENTS)[number]

/**
 * First guided step the project still needs, in creation order; null when every
 * step already has output. Derived from the payload so the chain survives refresh.
 * 产出存在或对应 agent 已跑过（agentStatus completed）都视为完成：
 * 归一化会给角色填默认 voiceId，所以配音只能用执行状态判断。
 */
export function nextGuidedStep(recipe: RecipeProject): GuidedStepAgent | null {
  const status = (agentId: string) =>
    (recipe.agentStatus || []).find((item) => item.id === agentId)?.status
  const done = (agentId: string) => status(agentId) === "completed"
  if (!recipe.artStyle?.id && !done("art_style")) return "art_style"
  if (!recipe.characters.length && !done("characters")) return "characters"
  if (!recipe.locations.length && !done("locations")) return "locations"
  if (!flattenRecipeShots(recipe).length && !done("storyboard")) return "storyboard"
  if (!done("voice")) return "voice"
  if (!(recipe.globalMusic || "").trim() && !done("music")) return "music"
  return null
}

/** Whether the guided chain can start from the current project (a script or a brief must exist). */
export function guidedFlowHasBrief(recipe: RecipeProject, goal: string): boolean {
  return Boolean(
    goal.trim()
    || recipe.script.fullStory.trim()
    || recipe.script.summary.trim()
    || recipe.script.title.trim(),
  )
}

export type GuidedClarifyAnswer = { id?: string; agent?: string; question: string; answer: string }

/** Tag answers with the step they belong to so the backend injects them into that agent only. */
export function tagClarifyAnswers<T extends { id?: string; question: string; answer: string }>(
  answers: T[],
  agent?: string,
): Array<T & { agent?: string }> {
  if (!agent) return answers.map((item) => ({ ...item }))
  return answers.map((item) => ({ ...item, agent }))
}

export type ClarifyScope = { agent?: string; questions: GuidedClarifyQuestion[] }

export type GuidedClarifyOption = { label: string; value: string; recommended?: boolean }

export type GuidedClarifyQuestion = {
  id: string
  question: string
  why?: string
  options: GuidedClarifyOption[]
  allowCustom?: boolean
}

/** Parse the persisted clarify scope; tolerates the legacy bare-question-array shape. */
export function parseClarifyScope(raw: string | null | undefined): ClarifyScope | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return parsed.length ? { questions: parsed as GuidedClarifyQuestion[] } : null
    }
    if (parsed && typeof parsed === "object" && Array.isArray(parsed.questions) && parsed.questions.length) {
      return { agent: typeof parsed.agent === "string" && parsed.agent ? parsed.agent : undefined, questions: parsed.questions }
    }
    return null
  } catch {
    return null
  }
}
