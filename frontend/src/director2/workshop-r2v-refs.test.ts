import { describe, expect, it } from "vitest"

import {
  H3_REFERENCE_REGENERATE_LABEL,
  authoringContextImages,
  h3ReferenceWarning,
  videoReferenceImages,
} from "./workshop-r2v-refs"

describe("workshop H3 reference policy", () => {
  it("keeps only authoritative character and prop images for video", () => {
    const refs = videoReferenceImages([
      { id: "char", url: "https://x/char.png", name: "沈砚", category: "character" },
      { id: "scene", url: "https://x/scene.png", name: "图书馆", category: "scene" },
      { id: "prop", url: "https://x/prop.png", name: "古籍", category: "prop" },
      { id: "panel", url: "https://x/start.png", name: "起幅", category: "composition" },
    ])

    expect(refs.map((item) => item.url)).toEqual(["https://x/char.png", "https://x/prop.png"])
  })

  it("deduplicates video slots and caps them at nine", () => {
    const refs = videoReferenceImages([
      { id: "char", url: "https://x/same.png", name: "角色", category: "character" },
      { id: "prop-duplicate", url: "https://x/same.png", name: "重复", category: "prop" },
      ...Array.from({ length: 12 }, (_, index) => ({
        id: `prop-${index}`,
        url: `https://x/prop-${index}.png`,
        name: `道具 ${index}`,
        category: "prop",
      })),
    ])

    expect(refs).toHaveLength(9)
    expect(refs[0].id).toBe("char")
    expect(refs[1].id).toBe("prop-0")
  })

  it("keeps scene and triptych images in authoring context only", () => {
    const refs = authoringContextImages({
      id: "beat-2",
      triptych_url: "https://x/triptych.png",
      triptych_panels: {
        start: "https://x/start.png",
        mid: "https://x/mid.png",
        end: "https://x/end.png",
      },
    }, [
      { id: "char", url: "https://x/char.png", name: "沈砚", category: "character" },
      { id: "scene", url: "https://x/scene.png", name: "图书馆", category: "scene" },
      { id: "prop", url: "https://x/prop.png", name: "古籍", category: "prop" },
    ])

    expect(refs.map((item) => item.url)).toEqual([
      "https://x/scene.png",
      "https://x/triptych.png",
      "https://x/start.png",
      "https://x/mid.png",
      "https://x/end.png",
    ])
  })

  it("maps stale state to the regeneration warning", () => {
    expect(h3ReferenceWarning("current", "ok")).toBeNull()
    expect(h3ReferenceWarning("stale", "上下文已变化")).toEqual({
      title: "H3 提示词已过期",
      description: "上下文已变化",
    })
    expect(H3_REFERENCE_REGENERATE_LABEL).toBe("按新规则重新生成")
  })
})
