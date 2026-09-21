import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const paneSource = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "ContentLibraryPane.tsx"),
  "utf8",
)

describe("content library shot-plan copy", () => {
  it("lets planned documents replan a selected episode before overwrite", () => {
    expect(paneSource).toContain("重新规划镜头")
    expect(paneSource).toContain("重新规划会覆盖所选分集已有的出片镜头")
    expect(paneSource).toContain("工坊中已经生成的 Take 不会自动删除")
    expect(paneSource).toContain("enqueueDocumentShotPlan(csrfToken, projectId, doc.id, aspect, force, episodeNum)")
    expect(paneSource).toContain("重新规划哪一集？")
    expect(paneSource).toContain("全部分集（谨慎使用）")
    expect(paneSource).toContain("documentCanReplanShots")
  })
})
