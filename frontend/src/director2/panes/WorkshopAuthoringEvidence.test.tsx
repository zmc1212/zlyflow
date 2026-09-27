import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import WorkshopAuthoringEvidence from "./WorkshopAuthoringEvidence"
import { workshopCandidateStaleReason, type WorkshopGroup, type WorkshopJob, type WorkshopPlan } from "../workshop-api"

const group: WorkshopGroup = { id: "g", beat_ids: ["b"], common_prompt: "原公共设定", reference_slots: [] }
const plan: WorkshopPlan = { schema_version: 7, id: "p", revision: 1, planning_revision: 1, source_revision: 1,
  workflow_id: "h3", aspect_ratio: "16:9", max_shots_per_group: 3, groups: [group], shot_prompts: {} }
function fixture(): WorkshopJob {
  return { id: "j", kind: "workshop_prompt", status: "completed", payload: { message: "", applied_ids: [],
    candidates: {}, failures: {}, base_plan: structuredClone(plan), writing_author: { model: "requested-author", profile_id: "provider" },
    authoring: { writing_history: [{ attempt: 1, group_id: "g", raw: "原稿", input: "输入", errors: [],
      author: { requested_model: "requested-author", actual_model: null },
      review: { structure_status: "passed", content_status: "rules_clear", semantic_status: "pending_human", media_status: "not_reviewed", issues: [] } }] } } }
}
describe("writing evidence truthfulness", () => {
  it.each(["h3-skill-direct-v1", "h3-skill-direct-v2", "h3-skill-direct-v3"])("distinguishes %s drafts and retained failures from quality acceptance", (version) => {
    const job = fixture()
    job.payload.authoring!.contracts = { g: { version, skill_sha256: "skill", system: "完整 Skill", user: "完整材料", context_policy: "full_source_no_truncation" } }
    job.payload.authoring!.rejected_groups = { g: { ...job.payload.authoring!.writing_history![0], not_approved: true } }
    const html = renderToStaticMarkup(<WorkshopAuthoringEvidence job={job} group={group} />)
    expect(html).toContain("单次写稿")
    expect(html).toContain("冻结输入与来源（可复制）")
    expect(html).toContain("原稿已保留，待人工处理；未自动返修，不可直接出片")
    expect(html).toContain("成片：未验收")
    if (version === "h3-skill-direct-v2") expect(html).toContain("素材与表演 · v2")
    if (version === "h3-skill-direct-v3") expect(html).toContain("原始 Skill · 仅执行校验")
    job.payload.authoring!.contracts.g.revision_beat_id = "b"
    expect(renderToStaticMarkup(<WorkshopAuthoringEvidence job={job} group={group} />)).toContain("人工定点返修")
  })
  it("shows image use and explicit fallback warnings", () => {
    const job = fixture()
    job.payload.authoring!.writing_history![0].author = { requested_model: "vision-author", actual_model: "text-author", attach_images: false, vision_status: "failed_text_fallback", fallback_from: "vision-author", warning: "参考图未参与写稿" }
    const html = renderToStaticMarkup(<WorkshopAuthoringEvidence job={job} group={group} />)
    expect(html).toContain("纯文本写稿")
    expect(html).toContain("已降级，需复核")
    expect(html).toContain("参考图未参与写稿")
    expect(html).not.toContain("未发生自动降级")
  })
  it("does not invent routing evidence for old tasks", () => {
    const html = renderToStaticMarkup(<WorkshopAuthoringEvidence job={fixture()} group={group} />)
    expect(html).toContain("历史任务未记录是否带图")
    expect(html).toContain("路由未记录")
  })
  it("keeps text checks separate from semantic and media acceptance", () => {
    const html = renderToStaticMarkup(<WorkshopAuthoringEvidence job={fixture()} group={group} />)
    expect(html).toContain("结构：通过")
    expect(html).toContain("规则未见问题 · 人工待核")
    expect(html).toContain("成片：未验收")
    expect(html).toContain("供应商未返回，不能确认")
    expect(html).not.toContain("效果恢复成功")
  })
  it("shows actual response identity and joint common-setting adoption", () => {
    const job = fixture()
    job.payload.authoring!.writing_history![0].author = { actual_model: "actual-response", fact_extraction: "vlm" }
    job.payload.common_prompt_candidates = { g: "新公共设定" }
    const html = renderToStaticMarkup(<WorkshopAuthoringEvidence job={job} group={group} />)
    expect(html).toContain("actual-response")
    expect(html).toContain("这不是满意版原样复现")
    expect(html).toContain("采纳时与全组正文一起生效")
  })
  it("retains rejected drafts without labeling them passed", () => {
    const job = fixture()
    job.payload.authoring!.writing_history![0].errors = ["需整组返修"]
    job.payload.authoring!.rejected_groups = { g: { ...job.payload.authoring!.writing_history![0], not_approved: true } }
    const html = renderToStaticMarkup(<WorkshopAuthoringEvidence job={job} group={group} />)
    expect(html).toContain("结构：未通过")
    expect(html).toContain("仍未通过，不可采纳")
  })
})
describe("candidate preview concurrency guards", () => {
  it("keeps unchanged groups available across unrelated revisions", () => {
    expect(workshopCandidateStaleReason(fixture(), { ...plan, revision: 2 }, group, false)).toBe("")
  })
  it("flags source, common-setting, lock and new-draft changes", () => {
    expect(workshopCandidateStaleReason(fixture(), plan, group, true)).toContain("来源剧本")
    expect(workshopCandidateStaleReason(fixture(), plan, { ...group, common_prompt: "改稿" }, false)).toContain("公共设定")
    expect(workshopCandidateStaleReason(fixture(), plan, { ...group, locked_common_lines: ["锁定"] }, false)).toContain("公共设定")
    expect(workshopCandidateStaleReason(fixture(), { ...plan, shot_prompts: { b: { h3_prompt: "手工稿", fingerprint: "new" } } }, group, false)).toContain("不能覆盖")
  })
})
