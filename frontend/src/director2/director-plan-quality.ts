import type { DirectorPromptPlan } from "./api"

export function directorPlanNeedsReview(plan: DirectorPromptPlan): boolean {
  return Boolean(plan.quality_version && (!plan.creative_review || plan.quality_status === "not_reviewed"
    || plan.creative_review.issues.some(issue => issue.severity !== "advisory")))
}

export function directorRevisionStopMessage(reason?: string): string {
  return ({
    planning_required: "需要先调整分镜、时长或公共设定，局部返修无法解决。",
    no_progress: "本轮未减少阻断问题，已停止返修并保留上一版。请明确修改意见或调整分镜。",
    invalid_patch: "返修未通过校验，已保留上一版，请查看修订记录。",
    round_limit: "已完成两轮返修，仍有问题待处理。请补充具体意见或调整分镜。",
  } as Record<string, string>)[reason || ""] || ""
}
