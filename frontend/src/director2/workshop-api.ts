import { jsonMutation, requestJson } from "../api"
import type { Director2Beat, PromptReferenceSlot } from "./api"

export type WorkshopGroup = { id: string; beat_ids: string[]; common_prompt: string; reference_slots: PromptReferenceSlot[]; reference_policy?: "auto" | "manual"; timecode_mode?: "per_shot" | "cumulative"; reference_issues?: string[] }
export type WorkshopPlan = {
  schema_version: 7; id: string; revision: number; planning_revision: number; source_revision: number;
  workflow_id: string; aspect_ratio: string; max_shots_per_group: number; groups: WorkshopGroup[];
  target_duration_seconds?: number | null; applied_candidates?: Record<string, string[]>;
  reference_fingerprint?: string;
  shot_prompts: Record<string, { h3_prompt: string; fingerprint: string; history?: Array<{h3_prompt:string}> }>;
}
export type WorkshopJob = {
  id: string; status: string; kind: string; error?: string;
  payload: { message: string; count_note?: string; applied_ids: string[]; prompt_scope?: "group" | "shot_revision";
    candidate?: { beats: Director2Beat[]; plan: WorkshopPlan };
    candidates: Record<string, { h3_prompt: string }>;
    failures: Record<string, string>;
  }
}
export type WorkshopView = {
  plan: WorkshopPlan | null; legacy_plan: { revision?: number; parts?: Array<{segments?:Array<{id:string;source_beat_ids?:string[]}>}> } | null;
  source: { document_id?: string; revision: number; text: string; unlinked: boolean };
  source_changed: boolean; jobs: WorkshopJob[];
  history?: Array<{ beats: Director2Beat[]; prompt_authoring: unknown; script_text?: string }>;
  historical_media?: Array<{id: string; url: string; title?: string}>;
  legacy_prompts: Record<string, Array<{ source: string; h3_prompt: string; common_prompt?: string }>>;
}
const base = (project: string, episode: string) => `/api/projects/${encodeURIComponent(project)}/episodes/${encodeURIComponent(episode)}`
export const readWorkshop = (project: string, episode: string) => requestJson<WorkshopView>(`${base(project, episode)}/workshop`)
export const writeWorkshop = (csrf: string, project: string, episode: string, data: Record<string, unknown>) => requestJson<WorkshopView>(`${base(project, episode)}/workshop`, jsonMutation(csrf, data, "PATCH"))
export const planWorkshop = (csrf: string, project: string, episode: string, data: Record<string, unknown>) => requestJson<{ job_id: string }>(`${base(project, episode)}/shot-plan`, jsonMutation(csrf, data, "POST"))
export const promptWorkshop = (csrf: string, project: string, episode: string, data: Record<string, unknown>) => requestJson<{ job_id: string }>(`${base(project, episode)}/workshop/prompts`, jsonMutation(csrf, data, "POST"))
export const actWorkshop = (csrf: string, project: string, episode: string, job: string, data: Record<string, unknown>) => requestJson<WorkshopView>(`${base(project, episode)}/workshop/jobs/${encodeURIComponent(job)}/actions`, jsonMutation(csrf, data, "POST"))

export function splitWorkshopGroup(groups: WorkshopGroup[], groupId: string, after: number): WorkshopGroup[] {
  return groups.flatMap(group => group.id !== groupId || after < 1 || after >= group.beat_ids.length ? [group] : [
    { ...group, beat_ids: group.beat_ids.slice(0, after) },
    { ...group, id: `group-${crypto.randomUUID()}`, beat_ids: group.beat_ids.slice(after) },
  ])
}
export function mergeWorkshopGroups(groups: WorkshopGroup[], index: number): WorkshopGroup[] {
  if (!groups[index] || !groups[index + 1]) return groups
  if (JSON.stringify(groups[index].reference_slots) !== JSON.stringify(groups[index + 1].reference_slots) || groups[index].common_prompt !== groups[index + 1].common_prompt) return groups
  return groups.flatMap((group, i) => i === index ? [{ ...group, beat_ids: [...group.beat_ids, ...groups[i + 1].beat_ids] }] : i === index + 1 ? [] : [group])
}
