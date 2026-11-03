import { describe, expect, it } from "vitest"
import type { Director2Asset } from "./api"
import { reconcileAssetGeneration } from "./asset-generation-result"

const character: Director2Asset = { id: "c", project_id: "p", kind: "character", name: "林夏", description: "女店主", role: null, visual_prompt: null, image_url: null, voice_id: null, created_at: "", updated_at: "", extra: { identities: [{ id: "look", name: "日常", image_url: "" }] } }
const scene: Director2Asset = { ...character, id: "s", kind: "scene", name: "咖啡店", extra: {} }

describe("asset image completion", () => {
  it("keeps the selected character intact when a scene finishes after switching", () => {
    const result = reconcileAssetGeneration([character, scene], character, "s", { ...scene, image_url: "scene.png", extra: { master_url: "scene.png" } })!
    expect(result.selected).toBe(character)
    expect(result.assets[0]).toBe(character)
    expect(result.assets.map(asset => asset.kind)).toEqual(["character", "scene"])
    expect(result.assets[1].extra?.master_url).toBe("scene.png")
  })

  it("preserves a pending text edit while adding the generated identity image by ID", () => {
    const selected = { ...character, description: "正在修改的描述", extra: { identities: [{ id: "look", name: "新造型名", image_url: "" }] } }
    const result = reconcileAssetGeneration([character, scene], selected, "c", { ...character, image_url: "look.png", extra: { identities: [{ id: "look", name: "日常", image_url: "look.png", object_key: "asset-image/look.png" }] } })!
    expect(result.selected?.description).toBe("正在修改的描述")
    expect(result.selected?.extra?.identities?.[0]).toMatchObject({ id: "look", name: "新造型名", image_url: "look.png", object_key: "asset-image/look.png" })
  })

  it("rejects an image result for a different asset or kind", () => {
    expect(reconcileAssetGeneration([character, scene], character, "c", scene)).toBeNull()
    expect(reconcileAssetGeneration([character, scene], character, "c", { ...character, kind: "prop" })).toBeNull()
  })
})
