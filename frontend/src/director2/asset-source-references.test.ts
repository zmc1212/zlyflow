import { describe, expect, it } from "vitest"
import type { Director2Asset } from "./api"
import {
  MAX_SOURCE_REFERENCES,
  asImageFile,
  hasSourceReferences,
  remainingSourceReferenceSlots,
  sourceReferenceHint,
  sourceReferencesOf,
} from "./asset-source-references"

function asset(extra: Record<string, unknown>): Director2Asset {
  return {
    id: "ast-1",
    project_id: "proj-1",
    kind: "character",
    name: "吴耐",
    role: "主角",
    description: null,
    visual_prompt: null,
    image_url: null,
    voice_id: null,
    extra,
    created_at: "",
    updated_at: "",
  }
}

describe("asset source references", () => {
  it("reads objects and string urls without duplicates", () => {
    const items = sourceReferencesOf(asset({
      source_references: [
        "https://cdn.example/a.jpg",
        { id: "ref-b", url: "https://cdn.example/b.png", filename: "b.png" },
        { url: "https://cdn.example/a.jpg" },
      ],
    }))
    expect(items).toEqual([
      { id: "https://cdn.example/a.jpg", url: "https://cdn.example/a.jpg", filename: "" },
      { id: "ref-b", url: "https://cdn.example/b.png", filename: "b.png" },
    ])
    expect(hasSourceReferences(asset({ source_references: items }))).toBe(true)
  })

  it("caps remaining slots at nine", () => {
    const extra = {
      source_references: Array.from({ length: MAX_SOURCE_REFERENCES }, (_, index) => ({
        id: `ref-${index}`,
        url: `https://cdn.example/${index}.jpg`,
      })),
    }
    expect(remainingSourceReferenceSlots(asset(extra))).toBe(0)
  })

  it("uses kind-specific hints", () => {
    expect(sourceReferenceHint("character")).toContain("正脸")
    expect(sourceReferenceHint("scene")).toContain("空镜")
    expect(sourceReferenceHint("prop")).toContain("道具特写")
  })

  it("unwraps antd upload file objects", () => {
    const raw = new File(["x"], "face.jpg", { type: "image/jpeg" })
    expect(asImageFile(raw)).toBe(raw)
    expect(asImageFile({ originFileObj: raw })).toBe(raw)
    expect(asImageFile({})).toBeNull()
  })
})
