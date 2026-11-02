import { describe, expect, it } from "vitest"
import type { AssistantResource } from "./api"
import { filterResources, quickResources, resourceCategories, resourceCover, resourceSource } from "./resource-market"

function resource(patch: Partial<AssistantResource> & Pick<AssistantResource, "id" | "name" | "resource_type">): AssistantResource {
  return {
    description: "", category: "剧本", instructions: "", references: {}, builtin: false,
    version_id: `${patch.id}-v1`, created_at: "now", updated_at: "now", ...patch,
  } as AssistantResource
}

const skill = (id: string, patch: Partial<AssistantResource> = {}) => resource({ id, name: id, resource_type: "skill", ...patch })
const expert = (id: string, patch: Partial<AssistantResource> = {}) => resource({ id, name: id, resource_type: "expert", ...patch })

const resources = [
  skill("script-platform", { category: "剧本", platform: true, description: "短剧剧本结构" }),
  skill("storyboard-platform", { category: "分镜", platform: true }),
  skill("prompt-personal", { category: "提示词", favorite: true }),
  skill("editing-builtin", { category: "剪辑", builtin: true }),
  skill("unknown-cover", { category: "节奏" }),
  expert("director-expert", { category: "导演", platform: true }),
]

describe("resource market presentation", () => {
  it("labels the resource source with platform precedence over personal ownership", () => {
    expect(resourceSource({ builtin: true })).toBe("builtin")
    expect(resourceSource({ builtin: false, platform: true })).toBe("platform")
    expect(resourceSource({ builtin: false })).toBe("personal")
  })
  it("maps categories to cover art and falls back to the default cover", () => {
    expect(resourceCover("剧本")).toBe("/assistant-covers/script.webp")
    expect(resourceCover(" 分镜 ")).toBe("/assistant-covers/storyboard.webp")
    expect(resourceCover("未知分类")).toBe("/assistant-covers/default.webp")
    expect(resourceCover("")).toBe("/assistant-covers/default.webp")
  })
  it("lists kind-specific categories in catalog order", () => {
    expect(resourceCategories(resources, "skill")).toEqual(["剧本", "分镜", "提示词", "剪辑", "节奏"])
    expect(resourceCategories(resources, "expert")).toEqual(["导演"])
  })
})

describe("resource market filtering", () => {
  it("keeps only the active kind and category", () => {
    expect(filterResources(resources, "skill").map(item => item.id)).not.toContain("director-expert")
    expect(filterResources(resources, "skill", "分镜").map(item => item.id)).toEqual(["storyboard-platform"])
    expect(filterResources(resources, "expert", "分镜")).toEqual([])
  })
  it("splits platform, favorite and personal scopes", () => {
    expect(filterResources(resources, "skill", "全部", "平台").map(item => item.id)).toEqual(["script-platform", "storyboard-platform"])
    expect(filterResources(resources, "skill", "全部", "收藏").map(item => item.id)).toEqual(["prompt-personal"])
    expect(filterResources(resources, "skill", "全部", "我的").map(item => item.id)).toEqual(["prompt-personal", "unknown-cover"])
  })
  it("searches name, description and category case-insensitively", () => {
    expect(filterResources(resources, "skill", "全部", "全部", " 结构 ").map(item => item.id)).toEqual(["script-platform"])
    expect(filterResources(resources, "skill", "全部", "全部", "PROMPT").map(item => item.id)).toEqual(["prompt-personal"])
    expect(filterResources(resources, "skill", "全部", "全部", "剧本").map(item => item.id)).toEqual(["script-platform"])
  })
})

describe("resource market quick list", () => {
  it("pins the active resource, then favorites, personal, builtin and platform resources", () => {
    expect(quickResources(resources, "skill", "editing-builtin-v1").map(item => item.id)).toEqual([
      "editing-builtin", "prompt-personal", "unknown-cover", "script-platform", "storyboard-platform",
    ])
  })
  it("never repeats a resource and respects the limit", () => {
    const duplicated = [...resources, skill("prompt-personal", { category: "提示词", favorite: true })]
    expect(quickResources(duplicated, "skill", null, 3).map(item => item.id)).toEqual(["prompt-personal", "unknown-cover", "editing-builtin"])
    expect(quickResources(resources, "expert").map(item => item.id)).toEqual(["director-expert"])
  })
})
