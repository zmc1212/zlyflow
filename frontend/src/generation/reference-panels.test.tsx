import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { AvatarReferencePanel, ReferencePanel, type ReferencePanelWorkflow } from "./ReferencePanels"

const noop = () => {}

const keyframesWorkflow: ReferencePanelWorkflow = {
  reference_mode: "keyframes",
  max_references: 2,
  reference_labels: ["首帧", "尾帧（可选）"],
}

const avatarWorkflow: ReferencePanelWorkflow = {
  reference_mode: "collection",
  max_references: 2,
  reference_labels: ["人物形象图（建议正面高清、光线均匀）", "口播音频（WAV 或 MP3，五秒以内）"],
}

const renderKeyframes = () => renderToStaticMarkup(
  <ReferencePanel
    workflow={keyframesWorkflow}
    references={[]}
    onAppend={noop}
    onReplaceKeyframe={noop}
    onRemove={noop}
    onMove={noop}
    onPreview={noop}
    fileInputRef={{ current: null }}
  />,
)

const renderAvatar = () => renderToStaticMarkup(
  <AvatarReferencePanel
    workflow={avatarWorkflow}
    audio={null}
    onPickAudio={noop}
    onRemoveAudio={noop}
    onReplacePortrait={noop}
    onRemovePortrait={noop}
    onPreview={noop}
  />,
)

/** 取带 title 的文本 span 的 class，用来断言省略规则确实加在标签上。 */
function classOfTagWithTitle(html: string, title: string) {
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  const tag = html.match(new RegExp(`<span title="${escaped}"[^>]*>`))?.[0] ?? ""
  return tag.match(/class="([^"]*)"/)?.[1] ?? ""
}

describe("窄栏参考面板通用规则", () => {
  it("首尾帧与数字人面板复用 studio-reference-stack 两行容器", () => {
    const keyframes = renderKeyframes()
    const avatar = renderAvatar()
    for (const html of [keyframes, avatar]) {
      expect(html).toContain('class="studio-reference-panel studio-reference-stack grid gap-2"')
      // 两个槽位都在同一个两行容器里，不再各自写死高度或宽度。
      expect(html.match(/studio-reference-slot/g)).toHaveLength(2)
      expect(html).not.toContain("h-[106px]")
      expect(html).not.toContain("flex-1 cursor-pointer")
    }
  })

  it("首尾帧长标签单行省略，并保留完整标题与上传提示", () => {
    const html = renderKeyframes()
    expect(classOfTagWithTitle(html, "尾帧（可选）")).toContain("truncate")
    expect(classOfTagWithTitle(html, "尾帧（可选）")).toContain("block")
    expect(classOfTagWithTitle(html, "首帧")).toContain("truncate")
    expect(html).toContain('title="尾帧（可选）"')
    expect(html).toContain("点击上传")
    expect(html.match(/truncate/g)?.length ?? 0).toBeGreaterThanOrEqual(3)
  })

  it("数字人长标签和提示都走省略，两个图标底座尺寸一致", () => {
    const html = renderAvatar()
    expect(classOfTagWithTitle(html, avatarWorkflow.reference_labels![0])).toContain("truncate")
    expect(classOfTagWithTitle(html, avatarWorkflow.reference_labels![1])).toContain("truncate")
    expect(html).toContain(`title="${avatarWorkflow.reference_labels![0]}"`)
    expect(html).toContain(`title="${avatarWorkflow.reference_labels![1]}"`)
    expect(html.match(/size-9/g)).toHaveLength(2)
    expect(html).not.toContain("size-[42px]")
    expect(html).not.toContain("size-8 ")
    expect(html.match(/truncate/g)?.length ?? 0).toBeGreaterThanOrEqual(4)
  })
})
