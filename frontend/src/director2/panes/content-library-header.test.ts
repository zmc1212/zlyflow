import { describe, expect, it } from "vitest"
import { contentLibraryHeaderTagText } from "./content-library-header"

describe("contentLibraryHeaderTagText", () => {
  it("keeps short genre chips", () => {
    expect(contentLibraryHeaderTagText("都市 / 穿越 / 寿命系统 / 房东逆袭 / 喜剧")).toBe(
      "都市 / 穿越 / 寿命系统 / 房东逆袭 / 喜剧",
    )
  })

  it("drops paragraph worldview so header actions stay in the card", () => {
    expect(
      contentLibraryHeaderTagText(
        "现代老旧开放式小区 9 楼。原主吴耐癌症晚期只剩 14 天；穿越者上身，靠收取他人「惊讶」续命。",
      ),
    ).toBeNull()
  })

  it("ignores empty values", () => {
    expect(contentLibraryHeaderTagText("")).toBeNull()
    expect(contentLibraryHeaderTagText("   ")).toBeNull()
    expect(contentLibraryHeaderTagText(undefined)).toBeNull()
  })
})
