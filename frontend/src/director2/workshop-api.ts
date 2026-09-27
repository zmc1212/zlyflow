import { jsonMutation, requestJson } from "../api"
import type { Director2Beat, PromptReferenceSlot } from "./api"

export type WritingAuthor = { profile_id?: string; model?: string; reasoning_effort?: string }
export type WorkshopReview = { structure_status: string; content_status: string; semantic_status?: string; media_status: string;
  issues: Array<{ beat_id: string; code: string; severity: string; evidence: string; suggestion: string }>; manual_checks?: string[] }
export type WritingAttempt = { attempt: number; group_id: string; revision_beat_id?: string; raw: string; input: string;
  reason?: string; errors: string[]; diff?: string; skill_sha256?: string; review?: WorkshopReview;
  author?: { requested_model?: string; actual_model?: string | null; provider_profile_id?: string; reasoning_effort?: string;
    request_id?: string | null; elapsed_ms?: number; usage?: unknown; temperature?: number; fact_extraction?: string; fallback_from?: string | null;
    attach_images?: boolean; vision_status?: string; status?: string; warning?: string; decision_reason?: string } }

export type WorkshopGroup = { id: string; beat_ids: string[]; common_prompt: string; reference_slots: PromptReferenceSlot[]; reference_policy?: "auto" | "manual"; timecode_mode?: "per_shot" | "cumulative"; reference_issues?: string[]; locked_common_lines?: string[] }
export type WorkshopPlan = {
  schema_version: 7; id: string; revision: number; planning_revision: number; source_revision: number;
  workflow_id: string; aspect_ratio: string; max_shots_per_group: number; groups: WorkshopGroup[];
  target_duration_seconds?: number | null; applied_candidates?: Record<string, string[]>;
  reference_fingerprint?: string;
  writing_author?: WritingAuthor;
  shot_prompts: Record<string, { h3_prompt: string; fingerprint: string; history?: Array<{h3_prompt:string}> }>;
}
export type WorkshopJob = {
  id: string; status: string; kind: string; error?: string;
  payload: { message: string; count_note?: string; applied_ids: string[]; prompt_scope?: "group" | "shot_revision";
    regenerated_from_job_id?: string;
    candidate?: { beats: Director2Beat[]; plan: WorkshopPlan };
    candidates: Record<string, { h3_prompt: string; review?: WorkshopReview }>;
    common_prompt_candidates?: Record<string, string>;
    writing_author?: WritingAuthor; request?: { revision_note?: string };
    base_plan?: WorkshopPlan;
    authoring?: { writing_history?: WritingAttempt[]; reviews?: Record<string, WorkshopReview>;
      contracts?: Record<string, { version: string; skill_sha256: string; system: string; context_policy: string;
        user?: string; input_sha256?: string; source?: { source_type?: string; document_id?: string; revision?: number }; revision_beat_id?: string }>;
      rejected_groups?: Record<string, WritingAttempt & { not_approved: boolean }> };
    failures: Record<string, string>;
  }
}
export type WorkshopView = {
  plan: WorkshopPlan | null; legacy_plan: { revision?: number; parts?: Array<{segments?:Array<{id:string;source_beat_ids?:string[]}>}> } | null;
  source: { document_id?: string; revision: number; text: string; unlinked: boolean };
  source_changed: boolean; jobs: WorkshopJob[];
  writing_author?: WritingAuthor; writing_profiles?: WritingAuthor[];
  history?: Array<{ beats: Director2Beat[]; prompt_authoring: unknown; script_text?: string }>;
  historical_media?: Array<{id: string; url: string; title?: string}>;
  legacy_prompts: Record<string, Array<{ source: string; h3_prompt: string; common_prompt?: string }>>;
}
const base = (project: string, episode: string) => `/api/projects/${encodeURIComponent(project)}/episodes/${encodeURIComponent(episode)}`

// A preview aid only; the backend rechecks source/shot fingerprints transactionally.
export function workshopCandidateStaleReason(job: WorkshopJob, plan: WorkshopPlan, group: WorkshopGroup, sourceChanged: boolean): string {
  if (sourceChanged) return "来源剧本已变化，请基于最新剧本重新生成"
  const basePlan = job.payload.base_plan
  if (!basePlan) return ""
  const oldGroup = basePlan.groups.find(g => g.id === group.id)
  if (!oldGroup || (["beat_ids", "common_prompt", "reference_slots", "timecode_mode", "locked_common_lines"] as const).some(key => JSON.stringify(oldGroup[key]) !== JSON.stringify(group[key]))) return "镜头组、参考或公共设定已变化，请重新生成"
  if (basePlan.workflow_id !== plan.workflow_id || basePlan.aspect_ratio !== plan.aspect_ratio) return "工作流或画幅已变化，请重新生成"
  if (group.beat_ids.some(id => JSON.stringify(basePlan.shot_prompts?.[id]) !== JSON.stringify(plan.shot_prompts?.[id]))) return "同组已有新稿，旧候选不能覆盖；请重新生成"
  return ""
}
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
