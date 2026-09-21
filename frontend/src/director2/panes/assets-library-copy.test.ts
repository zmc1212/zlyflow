import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const paneSource = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "AssetsLibraryPane.tsx"),
  "utf8",
)

describe("assets library prop tab copy", () => {
  it("exposes one-click prop sheets and hides turnaround/detail batch buttons", () => {
    expect(paneSource).toContain("一键生成所有设定板")
    expect(paneSource).toContain("道具设定板")
    expect(paneSource).not.toContain("一键生成所有三视图")
    expect(paneSource).not.toContain("一键生成所有细节图")
    expect(paneSource).not.toContain("一键生成所有参考图")
  })
})
