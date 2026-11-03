import { describe, expect, it } from "vitest"
import { formatHomeProjectDate, homeProjectImages } from "./home-project-cards"

describe("home project previews", () => {
  it("uses the project's explicit cover before its asset images", () => {
    expect(homeProjectImages({ cover_url: " /cover.jpg " }, [{ image_url: "/character.png", kind: "character" }])).toEqual([{ url: "/cover.jpg", fit: "cover" }])
  })
  it("skips missing and repeated images, preserves project order and limits the collage to three", () => {
    expect(homeProjectImages({ cover_url: null }, [
      { image_url: null, kind: "character" }, { image_url: " /role.png ", kind: "character" },
      { image_url: "/role.png", kind: "prop" }, { image_url: "/room.png", kind: "scene" },
      { image_url: "/watch.png", kind: "prop" }, { image_url: "/extra.png", kind: "scene" },
    ])).toEqual([{ url: "/role.png", fit: "contain" }, { url: "/room.png", fit: "cover" }, { url: "/watch.png", fit: "contain" }])
    expect(homeProjectImages({ cover_url: " " })).toEqual([])
  })
  it("shows a compact local edit time and handles missing legacy timestamps", () => {
    expect(formatHomeProjectDate("2026-11-03T09:04:00")).toBe("11-03 09:04")
    expect(formatHomeProjectDate("")).toBe("编辑时间未知")
  })
})
