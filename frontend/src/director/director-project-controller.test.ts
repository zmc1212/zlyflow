import { describe, expect, it } from "vitest"
import { ApiRequestError } from "../api"
import { createEmptyRecipe, createEmptyRecipeShot } from "./types"
import {
  directorFailureMessage,
  mergeInsertedDirectorAssets,
  readDirectorContentConflict,
  reconcileDirectorShotSelection,
  shouldPreserveLocalDirectorContent,
} from "./director-project-controller"

describe("director project controller", () => {
  it("reads a structured optimistic concurrency conflict", () => {
    const remote = { id: "project-1", content_revision: 4 }
    const error = new ApiRequestError(409, {
      detail: { code: "DIRECTOR_CONTENT_CONFLICT", current_project: remote },
    })
    expect(readDirectorContentConflict(error)).toEqual(remote)
    expect(readDirectorContentConflict(new ApiRequestError(409, { detail: "busy" }))).toBeNull()
  })

  it("preserves local creative state only while execution or unsaved work is present", () => {
    expect(shouldPreserveLocalDirectorContent({
      contentRevision: 2, dirty: true, executionOnly: false, hasConflict: false, runningPlan: false,
    })).toBe(true)
    expect(shouldPreserveLocalDirectorContent({
      contentRevision: 2, dirty: true, executionOnly: false, hasConflict: false, runningPlan: true,
    })).toBe(false)
  })

  it("prunes deleted shot selections and summarizes failures", () => {
    const shot = { ...createEmptyRecipeShot(1), id: "shot-1" }
    expect(reconcileDirectorShotSelection([shot], "deleted", ["shot-1", "deleted"])).toEqual({
      selectedShotId: "shot-1", checkedShotIds: ["shot-1"],
    })
    expect(directorFailureMessage("", "保存失败")).toBe("保存失败")
  })

  it("adds only requested library assets without replacing local edits", () => {
    const current = createEmptyRecipe("本地标题")
    current.characters = [{
      id: "local-character",
      name: "本地人物",
      type: "character",
      description: "刚改的描述",
      promptText: "local",
      gender: "",
      libraryAssetId: "library-local",
    }]
    const incoming = createEmptyRecipe("服务端旧标题")
    incoming.characters = [
      { ...current.characters[0], description: "服务端旧描述" },
      {
        id: "new-character",
        name: "资产人物",
        type: "character",
        description: "资产库",
        promptText: "asset",
        gender: "",
        libraryAssetId: "library-new",
      },
    ]
    const merged = mergeInsertedDirectorAssets(current, incoming, ["library-new"])
    expect(merged.script.title).toBe("本地标题")
    expect(merged.characters.map((item) => item.id)).toEqual(["local-character", "new-character"])
    expect(merged.characters[0].description).toBe("刚改的描述")
  })
})
