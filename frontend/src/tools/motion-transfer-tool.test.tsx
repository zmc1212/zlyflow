import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import {
  MOTION_REF_VIDEO_WORKFLOW,
  MOTION_SKELETON_WORKFLOW,
  MOTION_TRANSFER_WORKFLOW,
} from "../generation/motion-transfer"
import MotionTransferTool from "./MotionTransferTool"

const option = (label: string, definition: Record<string, unknown>) => ({ label, ...definition })

const WORKFLOWS = [
  {
    id: MOTION_TRANSFER_WORKFLOW,
    name: "人物替换迁移",
    description: "SAM3 跟踪指定人物，迁移原片动作与表情。",
    reference_labels: ["角色形象图", "动作参考视频"],
    accepts_video_reference: true,
    parameters: [{ name: "options", schema: { properties: {
      duration: option("生成时长", { type: "string", default: "5s", ui_group: "primary", enum: ["5s", "full"] }),
      subject_count: option("替换人数", { type: "string", default: "1", ui_group: "primary", enum: ["1", "2"] }),
      seed: option("随机种子", { type: "integer", default: 0, ui_group: "advanced" }),
      steps: option("采样步数", { type: "integer", default: 20, ui_group: "internal" }),
    } } }],
  },
  {
    id: MOTION_SKELETON_WORKFLOW,
    name: "骨架驱动迁移",
    description: "SDPose 骨架锁定动作节奏。",
    reference_labels: ["角色形象图", "动作参考视频"],
    accepts_video_reference: true,
    parameters: [{ name: "options", schema: { properties: {
      control_strength: option("动作跟随强度", { type: "number", default: 1, ui_group: "primary", minimum: 0.1, maximum: 1, step: 0.05 }),
      aspect_ratio: option("画面比例", { type: "string", default: "16:9", ui_group: "primary", enum: ["16:9", "9:16", "1:1"] }),
      render_quality: option("生成质量", { type: "string", default: "standard", ui_group: "advanced", enum: ["standard"] }),
      seed: option("随机种子", { type: "integer", default: 0, ui_group: "advanced" }),
      steps: option("采样步数", { type: "integer", default: 20, ui_group: "internal" }),
    } } }],
  },
  {
    id: MOTION_REF_VIDEO_WORKFLOW,
    name: "多人参考视频版",
    description: "动作视频直接作为表演来源。",
    reference_labels: ["角色形象图 1", "角色形象图 2", "角色形象图 3", "角色形象图 4", "角色形象图 5", "角色形象图 6", "动作参考视频"],
    reference_slots: ["image", "image", "image", "image", "image", "image", "video"],
    accepts_video_reference: true,
    parameters: [{ name: "options", schema: { properties: {
      aspect_ratio: option("画面比例", { type: "string", default: "9:16", ui_group: "primary", enum: ["16:9", "9:16", "1:1"] }),
      duration: option("生成时长", { type: "string", default: "5s", ui_group: "primary", enum: ["5s", "10s", "15s"] }),
      preserve_audio: option("保留原片声音", { type: "boolean", default: true, ui_group: "advanced" }),
      seed: option("随机种子", { type: "integer", default: 0, ui_group: "advanced" }),
      steps: option("采样步数", { type: "integer", default: 20, ui_group: "internal" }),
    } } }],
  },
]

function render(path = "/tools/motion-transfer") {
  const client = new QueryClient()
  client.setQueryData(["motion-tool-workflows"], WORKFLOWS)
  const html = renderToStaticMarkup(
    <MemoryRouter initialEntries={[path]}><QueryClientProvider client={client}>
      <MotionTransferTool csrfToken="" />
    </QueryClientProvider></MemoryRouter>,
  )
  client.clear()
  return html
}

describe("motion transfer tool workflow selector", () => {
  it("defaults to the SCAIL person replacement method with its picker and registry params", () => {
    const html = render()
    expect(html).toContain('aria-label="迁移方式"')
    expect(html).toContain("人物替换迁移")
    expect(html).toContain("选择形象图人物")
    expect(html).toContain("选择视频中要替换的人物")
    expect(html).toContain('aria-label="生成时长"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain("更多设置")
    // advanced/internal 不进默认表单。
    expect(html).not.toContain("随机种子")
    expect(html).not.toContain("采样步数")
    expect(html).toContain('aria-label="提示词（可选）"')
    expect(html).toContain("开始生成")
  })

  it("renders the skeleton method without subject picking but with control strength", () => {
    const html = render(`/tools/motion-transfer?mode=${MOTION_SKELETON_WORKFLOW}`)
    expect(html).toContain("骨架驱动迁移")
    expect(html).not.toContain("选择视频中要替换的人物")
    expect(html).toContain('aria-label="动作跟随强度"')
    expect(html).toContain('aria-label="画面比例"')
    expect(html).not.toContain("添加角色")
  })

  it("renders the multi-person method with the character list and no subject picking", () => {
    const html = render(`/tools/motion-transfer?mode=${MOTION_REF_VIDEO_WORKFLOW}`)
    expect(html).toContain("多人参考视频版")
    expect(html).toContain("添加角色")
    expect(html).toContain("已添加 0 / 6")
    expect(html).not.toContain("选择形象图人物")
    expect(html).not.toContain("动作跟随强度")
    expect(html).toContain('aria-label="画面比例"')
  })
})

describe("character swap dedicated tool card", () => {
  it("locks the multi-person workflow, hides the method selector and applies custom copy", () => {
    const client = new QueryClient()
    client.setQueryData(["motion-tool-workflows", MOTION_REF_VIDEO_WORKFLOW], [WORKFLOWS[2]])
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/tools/character-replace"]}><QueryClientProvider client={client}>
        <MotionTransferTool csrfToken="" lockedWorkflow={MOTION_REF_VIDEO_WORKFLOW}
          copy={{ title: "视频换人", description: "换掉主角，重演同一段表演" }} />
      </QueryClientProvider></MemoryRouter>,
    )
    client.clear()
    expect(html).toContain("<h1>视频换人</h1>")
    expect(html).toContain("换掉主角，重演同一段表演")
    // 锁定单一方式：不渲染迁移方式选择器，也不复用动作迁移副标题。
    expect(html).not.toContain('aria-label="迁移方式"')
    // 多人换人素材区正常呈现。
    expect(html).toContain("添加角色")
    expect(html).toContain('aria-label="画面比例"')
  })
})
