import { describe, expect, it } from "vitest"
import { withTriptychPanels } from "./workshop-r2v-refs"

const beat = {
  id: "b1",
  triptych_url: "https://x/triptych.png",
  triptych_panels: {
    start: "https://x/start.png",
    mid: "https://x/mid.png",
    end: "https://x/end.png",
  },
}

const identity = [
  { id: "c1", url: "https://x/char.png", name: "沈砚", category: "character" },
  { id: "s1", url: "https://x/scene.png", name: "走廊", category: "scene" },
]

describe("workshop R2V triptych refs", () => {
  it("appends start/mid/end crops and drops the 16:9 master", () => {
    const refs = withTriptychPanels(beat, [
      ...identity,
      { id: "full", url: "https://x/triptych.png", name: "三联母图" },
    ])
    expect(refs.map((item) => item.url)).toEqual([
      "https://x/char.png",
      "https://x/scene.png",
      "https://x/start.png",
      "https://x/mid.png",
      "https://x/end.png",
    ])
    expect(refs.every((item) => item.url !== "https://x/triptych.png")).toBe(true)
    expect(refs).toHaveLength(5)
  })

  it("skips a panel whose url equals the master", () => {
    const refs = withTriptychPanels(
      {
        ...beat,
        triptych_panels: {
          start: "https://x/start.png",
          mid: "https://x/triptych.png",
          end: "https://x/end.png",
        },
      },
      identity,
    )
    expect(refs.map((item) => item.name)).toEqual(["沈砚", "走廊", "起幅构图", "结果构图"])
  })

  it("drops mid before end when identity already fills most of 9 slots", () => {
    const crowded = Array.from({ length: 7 }, (_, index) => ({
      id: `c${index}`,
      url: `https://x/c${index}.png`,
      name: `角色${index}`,
      category: "character",
    }))
    const refs = withTriptychPanels(beat, crowded)
    expect(refs).toHaveLength(9)
    expect(refs.map((item) => item.name)).toContain("起幅构图")
    expect(refs.map((item) => item.name)).toContain("结果构图")
    expect(refs.map((item) => item.name)).not.toContain("中格构图")
  })

  it("keeps only the start crop when a single slot remains", () => {
    const crowded = Array.from({ length: 8 }, (_, index) => ({
      id: `c${index}`,
      url: `https://x/c${index}.png`,
      name: `角色${index}`,
      category: "character",
    }))
    const refs = withTriptychPanels(beat, crowded)
    expect(refs).toHaveLength(9)
    expect(refs.map((item) => item.name)).toContain("起幅构图")
    expect(refs.map((item) => item.name)).not.toContain("中格构图")
    expect(refs.map((item) => item.name)).not.toContain("结果构图")
  })
})
