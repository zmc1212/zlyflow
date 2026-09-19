import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { emptyShotPlanLiveState } from "../shot-plan-live"
import ShotPlanSlimProgress from "./shot-plan-slim-progress"

describe("shot plan slim progress", () => {
  it("shows episode progress and hides JSON plus thinking by default", () => {
    const live = {
      ...emptyShotPlanLiveState("job-1"),
      working: true,
      episodeNum: 2,
      episodeIndex: 2,
      episodeTotal: 6,
      reasoning: "Planning shot durations...",
      text: '{"shots":[{"title":"开口","action":"站起来"}]}',
    }
    const html = renderToStaticMarkup(
      <ShotPlanSlimProgress live={live} onDismiss={() => undefined} />,
    )
    expect(html).toContain("正在规划 第 2 / 6 集 · 本集已写出 1 条镜头")
    expect(html).toContain("ant-progress")
    expect(html).toContain("模型思路")
    expect(html).not.toContain("ant-collapse-item-active")
    expect(html).not.toContain('{"shots"')
    expect(html).not.toContain("Planning shot durations...")
    expect(html).not.toContain("workshop-prompt-live")
    expect(html).not.toContain("workshop-stream-text")
  })
})
