import { isValidElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { Button } from "antd"
import { describe, expect, it, vi } from "vitest"
import WorkshopPromptCandidates, { workshopCandidatePresentation, workshopPendingCandidateIds, workshopCanRegenerate } from "./WorkshopPromptCandidates"
import type { WorkshopGroup, WorkshopJob, WorkshopPlan } from "../workshop-api"

const group: WorkshopGroup = { id: "group-1", beat_ids: ["shot-1", "shot-2"], common_prompt: "共同主体", reference_slots: [] }
const plan: WorkshopPlan = { schema_version: 7, id: "plan", revision: 1, planning_revision: 1, source_revision: 1, workflow_id: "h3", aspect_ratio: "16:9", max_shots_per_group: 3, groups: [group], shot_prompts: {} }
const context = { beatId: "shot-1", group, groupWriting: true, plan, sourceChanged: false, busy: false, dirty: false }
function candidate(id = "job-pending-12345678"): WorkshopJob {
  return { id, kind: "workshop_prompt", status: "completed", payload: { message: "已生成", applied_ids: [], failures: {}, prompt_scope: "group", candidates: { "shot-1": { h3_prompt: "第一镜候选正文" }, "shot-2": { h3_prompt: "第二镜候选正文" } }, base_plan: structuredClone(plan) } }
}
function props(jobs: WorkshopJob[]) {
  return { ...context, jobs, beats: [{ id: "shot-1", sequence: 1 }, { id: "shot-2", sequence: 2 }], onApply: vi.fn() }
}
// Inspect the business render tree, including collapsed content, without a DOM dependency.
function buttons(node: ReactNode): Array<{ disabled?: boolean; onClick?: () => void; children?: ReactNode }> {
  if (Array.isArray(node)) return node.flatMap(buttons)
  if (!isValidElement<{ children?: ReactNode; items?: Array<{ children?: ReactNode }>; disabled?: boolean; onClick?: () => void }>(node)) return []
  return [...(node.type === Button ? [node.props] : []), ...buttons(node.props.children), ...(node.props.items || []).flatMap(item => buttons(item.children))]
}

describe("workshop candidate grouping", () => {
  it("keeps pending candidates visible while adopted history starts collapsed", () => {
    const adopted = candidate("job-adopted-abcdefgh")
    adopted.payload.applied_ids = group.beat_ids
    const html = renderToStaticMarkup(<WorkshopPromptCandidates {...props([adopted, candidate()])} />)
    expect(html).toContain("待采纳提示词候选")
    expect(html).toContain("第一镜候选正文")
    expect(html).toContain("采用整组候选")
    expect(html).toContain("候选与返修历史（1）")
    expect(html).toContain("12345678")
    expect(html).not.toContain("abcdefgh")
  })
  it("does not show an empty candidates container", () => {
    expect(WorkshopPromptCandidates(props([]))).toBeNull()
  })
  it("can place pending work before the editor and history after it without duplication", () => {
    const adopted = candidate("adopted"); adopted.payload.applied_ids = group.beat_ids
    const input = props([adopted, candidate()])
    const pending = renderToStaticMarkup(<WorkshopPromptCandidates {...input} display="pending" />)
    const history = renderToStaticMarkup(<WorkshopPromptCandidates {...input} display="history" />)
    expect(pending).toContain("待采纳提示词候选")
    expect(pending).not.toContain("候选与返修历史")
    expect(history).toContain("候选与返修历史（1）")
    expect(history).not.toContain("待采纳提示词候选")
    expect(WorkshopPromptCandidates({ ...props([adopted]), display: "pending" })).toBeNull()
  })
  it("keeps rejected evidence inside history without offering adoption", () => {
    const rejected = candidate()
    rejected.status = "failed"
    rejected.payload.candidates = {}
    rejected.payload.authoring = { writing_history: [{ group_id: group.id, attempt: 1, raw: "原始稿", input: "输入", errors: ["未通过"] }] }
    const node = WorkshopPromptCandidates(props([rejected]))
    const html = renderToStaticMarkup(node)
    expect(html).toContain("候选与返修历史（1）")
    expect(html).not.toContain("待采纳提示词候选")
    expect(buttons(node)).toHaveLength(0)
  })
  it("shows only history for adopted, stale, and legacy candidates", () => {
    const adopted = candidate("adopted")
    adopted.payload.applied_ids = group.beat_ids
    const stale = candidate("stale")
    stale.payload.base_plan!.groups = [{ ...group, common_prompt: "旧设定" }]
    const legacy = candidate("legacy")
    delete legacy.payload.prompt_scope
    const html = renderToStaticMarkup(<WorkshopPromptCandidates {...props([adopted, stale, legacy])} />)
    expect(html).toContain("候选与返修历史（3）")
    expect(html).not.toContain("待采纳提示词候选")
  })
})

describe("workshop pending navigation", () => {
  it("deduplicates ready candidate shots across multiple jobs", () => {
    expect([...workshopPendingCandidateIds([candidate(), candidate("second")], plan, true, false)]).toEqual(group.beat_ids)
  })
  it("excludes adopted, incomplete, stale, legacy, failed and unrelated candidates", () => {
    const adopted = candidate("adopted"); adopted.payload.applied_ids = group.beat_ids
    const incomplete = candidate("incomplete"); delete incomplete.payload.candidates["shot-2"]
    const stale = candidate("stale"); stale.payload.base_plan!.groups = [{ ...group, common_prompt: "旧设定" }]
    const legacy = candidate("legacy"); delete legacy.payload.prompt_scope
    const failed = candidate("failed"); failed.status = "failed"
    const unrelated = candidate("unrelated"); unrelated.payload.candidates = { "removed-shot": { h3_prompt: "不在规划内" } }
    expect(workshopPendingCandidateIds([adopted, incomplete, stale, legacy, failed, unrelated], plan, true, false).size).toBe(0)
  })
  it("does not advertise adoption without a current plan or source", () => {
    expect(workshopPendingCandidateIds([candidate()], null, true, false).size).toBe(0)
    expect(workshopPendingCandidateIds([candidate()], plan, true, true).size).toBe(0)
  })
  it("honors the authoritative applied map without mutating jobs", () => {
    const job = candidate(); const before = structuredClone(job)
    expect(workshopPendingCandidateIds([job], { ...plan, applied_candidates: { [job.id]: group.beat_ids } }, true, false).size).toBe(0)
    expect(job).toEqual(before)
  })
})

describe("workshop adoption scope and guards", () => {
  it("offers a separate new-contract task for finished historical drafts", () => {
    const job = candidate()
    job.status = "failed"
    job.payload.candidates = {}
    job.payload.authoring = { contracts: { [group.id]: { version: "h3-skill-direct-v1", skill_sha256: "old", system: "old", context_policy: "frozen" } },
      writing_history: [{ group_id: group.id, attempt: 1, raw: "旧原稿", input: "旧输入", errors: ["失败"] }] }
    const input = { ...props([job]), onRegenerate: vi.fn() }
    const actions = buttons(WorkshopPromptCandidates(input))
    expect(actions).toHaveLength(1)
    expect(actions[0].children).toBe("按新方式重新生成")
    actions[0].onClick!()
    expect(input.onRegenerate).toHaveBeenCalledExactlyOnceWith(job)
    expect(input.onApply).not.toHaveBeenCalled()
    for (const guard of [{ dirty: true }, { busy: true }, { sourceChanged: true }]) {
      expect(buttons(WorkshopPromptCandidates({ ...input, ...guard }))[0].disabled).toBe(true)
    }
    job.status = "running"
    expect(workshopCanRegenerate(job)).toBe(false)
    job.status = "failed"
    job.payload.authoring.contracts![group.id].version = "h3-skill-direct-v2"
    expect(workshopCanRegenerate(job)).toBe(true)
    job.payload.authoring.contracts![group.id].version = "h3-skill-direct-v3"
    expect(workshopCanRegenerate(job)).toBe(false)
    job.payload.authoring.contracts![group.id].version = "unknown-future"
    expect(workshopCanRegenerate(job)).toBe(false)
  })
  it("passes the complete group unchanged to the original apply action", () => {
    const job = candidate()
    const input = props([job])
    const apply = buttons(WorkshopPromptCandidates(input))[0]
    expect(apply.disabled).toBe(false)
    apply.onClick!()
    expect(input.onApply).toHaveBeenCalledExactlyOnceWith(job, ["shot-1", "shot-2"], true)
  })
  it("keeps a shot revision scoped to the current shot", () => {
    const job = candidate()
    job.payload.prompt_scope = "shot_revision"
    const input = props([job])
    buttons(WorkshopPromptCandidates(input))[0].onClick!()
    expect(input.onApply).toHaveBeenCalledExactlyOnceWith(job, ["shot-1"], false)
  })
  it("preserves normal per-shot workflows", () => {
    const job = candidate()
    delete job.payload.prompt_scope
    const presentation = workshopCandidatePresentation(job, { ...context, groupWriting: false })
    expect(presentation.ids).toEqual(["shot-1"])
    expect(presentation.pending).toBe(true)
    expect(presentation.disabled).toBe(false)
  })
  it.each([{ busy: true }, { dirty: true }, { sourceChanged: true }])("retains disabled guards %j", state => {
    expect(workshopCandidatePresentation(candidate(), { ...context, ...state }).disabled).toBe(true)
  })
  it("disables incomplete, partially applied, unfinished, and legacy group candidates", () => {
    const incomplete = candidate(); delete incomplete.payload.candidates["shot-2"]
    const partial = candidate(); partial.payload.applied_ids = ["shot-2"]
    const running = candidate(); running.status = "running"
    const legacy = candidate(); delete legacy.payload.prompt_scope
    for (const job of [incomplete, partial, running, legacy]) expect(workshopCandidatePresentation(job, context).disabled).toBe(true)
  })
  it("uses the plan's authoritative adoption map and preserves candidate objects", () => {
    const job = candidate()
    const before = structuredClone(job)
    const result = workshopCandidatePresentation(job, { ...context, plan: { ...plan, applied_candidates: { [job.id]: group.beat_ids } } })
    expect(result.adopted).toBe(true)
    expect(result.pending).toBe(false)
    expect(result.disabled).toBe(true)
    expect(job).toEqual(before)
  })
})
