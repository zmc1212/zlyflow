import type { AssistantResource } from "./api"

export type ResourceKind = "skill" | "expert"
export type ResourceScope = "全部" | "平台" | "收藏" | "我的"
export type ResourceSource = "builtin" | "platform" | "personal"

const CATEGORY_COVERS: Record<string, string> = {
  剧本: "script",
  策划: "planning",
  分镜: "storyboard",
  资产: "assets",
  提示词: "prompt",
  全流程: "workflow",
  审查: "review",
  剪辑: "editing",
  短视频: "shortvideo",
  导演: "director",
}

export const resourceSourceLabels: Record<ResourceSource, string> = { builtin: "内置", platform: "平台", personal: "个人" }

export function resourceSource(resource: Pick<AssistantResource, "builtin" | "platform">): ResourceSource {
  return resource.builtin ? "builtin" : resource.platform ? "platform" : "personal"
}

export function resourceCover(category: string) {
  return `/assistant-covers/${CATEGORY_COVERS[category.trim()] || "default"}.webp`
}

export function resourceCategories(resources: AssistantResource[], kind: ResourceKind) {
  return [...new Set(resources.filter(r => r.resource_type === kind).map(r => r.category).filter(Boolean))]
}

export function filterResources(resources: AssistantResource[], kind: ResourceKind, category = "全部", scope: ResourceScope = "全部", search = "") {
  const query = search.trim().toLowerCase()
  return resources.filter(resource => resource.resource_type === kind
    && (category === "全部" || resource.category === category)
    && (scope === "全部" || (scope === "平台" ? !!resource.platform : scope === "收藏" ? !!resource.favorite : !resource.builtin && !resource.platform))
    && (!query || `${resource.name} ${resource.description} ${resource.category}`.toLowerCase().includes(query)))
}

export function quickResources(resources: AssistantResource[], kind: ResourceKind, selectedVersionId?: string | null, limit = 8) {
  const ordered = [
    ...resources.filter(r => r.resource_type === kind && r.version_id === selectedVersionId),
    ...resources.filter(r => r.resource_type === kind && r.favorite),
    ...resources.filter(r => r.resource_type === kind && !r.builtin && !r.platform),
    ...resources.filter(r => r.resource_type === kind && r.builtin),
    ...resources.filter(r => r.resource_type === kind && r.platform),
  ]
  const seen = new Set<string>()
  return ordered.filter(resource => {
    if (seen.has(resource.id)) return false
    seen.add(resource.id)
    return true
  }).slice(0, limit)
}
