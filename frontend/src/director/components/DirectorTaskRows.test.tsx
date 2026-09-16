import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import DirectorTaskRows from "./DirectorTaskRows"

describe("DirectorTaskRows rail", () => {
  it("stays always-open and does not grow nested episode accordion substeps", () => {
    const html = renderToStaticMarkup(
      <DirectorTaskRows
        rows={[
          { id: "script", label: "剧本", status: "completed", message: "剧本已完成" },
          { id: "episodes", label: "分集", status: "running", message: "正在拆分每集结构" },
        ]}
        running
        elapsedSec={8}
        variant="rail"
        onOpen={() => undefined}
      />,
    )
    expect(html).toContain("director-task-rows is-rail is-open")
    expect(html).toContain("生成任务")
    expect(html).toContain("查看这一步的产出")
    expect(html).not.toContain("is-collapsed")
    expect(html).not.toContain("director-task-rows-head")
    expect(html).not.toContain("director-episode-row")
    expect(html).not.toContain("aria-expanded")
    expect(html).not.toContain("Capsules")
  })
})
