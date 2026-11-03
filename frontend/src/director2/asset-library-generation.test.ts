import { describe, expect, it } from "vitest"
import type { Director2Asset } from "./api"
import { planAssetGeneration, visibleAssetSelection } from "./asset-library-generation"

const asset = (id: string, kind: string, extra = {}): Director2Asset => ({ id, project_id: "p", kind, name: id, description: "剧本中的外观描述", visual_prompt: null, role: null, image_url: null, voice_id: null, extra, created_at: "", updated_at: "" })

describe("production asset generation selection", () => {
  it("generates only selected missing looks and retains completed looks", () => {
    const first = asset("a", "character", { identities: [{ id: "day", name: "日常", image_url: "day.png" }, { id: "night", name: "夜晚", description: "黑色外套" }] })
    const other = asset("b", "character")
    const plan = planAssetGeneration([first, other], ["a", "a"])
    expect(plan.items).toHaveLength(1)
    expect(plan.items[0]).toMatchObject({ assetId: "a", target: { type: "identity", identityId: "night" }, payload: { target_type: "identity", identity_id: "night", prompt: "黑色外套" } })
    expect(plan.blocked).toEqual([])
    expect(first.extra.identities[0].image_url).toBe("day.png")
  })

  it("supports one or several assets through the same primary-image plan", () => {
    const scene = asset("s", "scene", { reverse_url: "old-reverse.png" })
    const prop = asset("p", "prop", { detail_url: "old-detail.png" })
    expect(planAssetGeneration([scene, prop], ["s"]).items.map(item => item.payload.target_type)).toEqual(["scene_master"])
    expect(planAssetGeneration([scene, prop], ["s", "p"]).items.map(item => item.payload.target_type)).toEqual(["scene_master", "prop_reference"])
    expect(scene.extra.reverse_url).toBe("old-reverse.png")
    expect(prop.extra.detail_url).toBe("old-detail.png")
  })

  it("uses a stable initial look for an old character and does not overwrite an existing legacy image", () => {
    const old = asset("old", "character")
    const plan = planAssetGeneration([old], [old.id])
    expect(plan.items[0]).toMatchObject({ target: { type: "identity", identityId: "look-old-default" }, payload: { prompt: old.description } })
    expect(old.extra).not.toHaveProperty("identities")
    expect(planAssetGeneration([{ ...old, image_url: "legacy.png" }], [old.id]).items).toEqual([])
  })

  it("reports missing character descriptions while allowing reference-driven generation", () => {
    const empty = { ...asset("a", "character"), description: "" }
    const result = planAssetGeneration([empty], [empty.id])
    expect(result.items).toEqual([])
    expect(result.blocked[0]).toMatchObject({ assetId: "a", reason: "先描述角色造型，或添加人物参考图" })
    const referenced = { ...empty, extra: { source_references: [{ id: "r", url: "https://cdn/ref.png" }] } }
    expect(planAssetGeneration([referenced], [empty.id]).items).toHaveLength(1)
  })

  it("scopes selection to visible assets after searching, changing categories, or deleting", () => {
    const visible = [asset("s", "scene"), asset("t", "scene")]
    expect(visibleAssetSelection(visible, ["character", "s", "deleted", "s"])).toEqual(["s"])
    expect(planAssetGeneration(visible, ["character", "deleted"]).items).toEqual([])
    expect(visibleAssetSelection([], ["s"])).toEqual([])
  })
})
