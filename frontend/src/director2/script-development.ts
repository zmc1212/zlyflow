import { jsonMutation, requestJson } from "../api"

export type EpisodeStoryPlan = {
  episode_num: number; title: string; duration_seconds: number
  opening_hook: string; goal: string; obstacle: string; choice_and_consequence: string
  emotion: string; ending_hook: string; next_episode_bridge: string
}
export type StoryPlan = {
  title: string; mainline: string; ending: string; locked_facts: string[]
  characters: Array<string | Record<string, unknown>>; episodes: EpisodeStoryPlan[]
  diagnosis?: { kind: string; reasons: string | string[] }; scale_reason?: string
}
export type ScriptDevelopment = {
  job_id: string; status: string; revision: string; error?: string
  data: {
    phase: string; message: string; plan?: StoryPlan; script_text?: string
    episodes?: Array<{ episode_num: number; title: string; body: string; summary?: string }>
    unresolved_issues?: Array<{ episode_num: number; category: string; evidence: string; suggestion: string }>
  }
}
const path = (project: string, doc: string) => `/api/projects/${encodeURIComponent(project)}/documents/${encodeURIComponent(doc)}/script-developments`
export const getScriptDevelopment = (project: string, doc: string) => requestJson<ScriptDevelopment | null>(path(project, doc))
export const startScriptDevelopment = (csrf: string, project: string, doc: string, preferences: Record<string, unknown> = {}) =>
  requestJson<ScriptDevelopment>(path(project, doc), jsonMutation(csrf, preferences, "POST"))
export const actScriptDevelopment = (csrf: string, project: string, doc: string, job: ScriptDevelopment, action: string, fields: Record<string, unknown> = {}) =>
  requestJson<ScriptDevelopment>(`${path(project, doc)}/${encodeURIComponent(job.job_id)}/actions`, jsonMutation(csrf, { action, revision: job.revision, ...fields }, "POST"))
export const scriptDevelopmentWorking = (job: ScriptDevelopment | null) => !!job && ["queued", "running"].includes(job.status)
