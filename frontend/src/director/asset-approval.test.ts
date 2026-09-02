import { describe, expect, it } from "vitest"
import {
  recipeApprovableAssetVersion,
  type RecipeAssetRendition,
} from "./recipe-model"

function rendition(versions: RecipeAssetRendition["versions"], overrides: Partial<RecipeAssetRendition> = {}): RecipeAssetRendition {
  return {
    versions,
    activeVersionId: overrides.activeVersionId ?? versions.at(-1)?.id ?? null,
    approvedVersionId: overrides.approvedVersionId ?? null,
  }
}

describe("recipeApprovableAssetVersion", () => {
  it("returns the active succeeded candidate when it is not approved yet", () => {
    const item = rendition([
      { id: "v1", status: "succeeded", imageUrl: "/a.png", promptSnapshot: "", options: {}, createdAt: "" },
    ])
    expect(recipeApprovableAssetVersion(item)?.id).toBe("v1")
  })

  it("skips the approved version and returns a newer succeeded candidate", () => {
    const item = rendition(
      [
        { id: "v1", status: "succeeded", imageUrl: "/a.png", promptSnapshot: "", options: {}, createdAt: "" },
        { id: "v2", status: "succeeded", imageUrl: "/b.png", promptSnapshot: "", options: {}, createdAt: "" },
      ],
      { approvedVersionId: "v1", activeVersionId: "v2" },
    )
    expect(recipeApprovableAssetVersion(item)?.id).toBe("v2")
  })

  it("returns undefined when every succeeded version is already approved", () => {
    const item = rendition(
      [{ id: "v1", status: "succeeded", imageUrl: "/a.png", promptSnapshot: "", options: {}, createdAt: "" }],
      { approvedVersionId: "v1" },
    )
    expect(recipeApprovableAssetVersion(item)).toBeUndefined()
  })
})
