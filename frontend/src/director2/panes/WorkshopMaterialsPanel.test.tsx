import { isValidElement, type ComponentProps, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { Button, Checkbox, Collapse, Image } from "antd"
import { describe, expect, it, vi } from "vitest"
import WorkshopMaterialsPanel from "./WorkshopMaterialsPanel"

type Props = ComponentProps<typeof WorkshopMaterialsPanel>
function fixture(): Props {
  return {
    beat: { id: "shot-1", sequence: 1, character_ids: ["hero"], character_look_ids: { hero: "period" }, scene_id: "library", prop_ids: ["book"], workshop_writing_refs: ["/hero.png"], sketch_url: "/sketch.png" },
    assets: [
      { id: "hero", kind: "character", name: "沈砚", image_url: "/hero.png", extra: { identities: [{ id: "modern", name: "现代造型", image_url: "/hero.png" }, { id: "period", name: "古代造型", image_url: "/period.png" }] } },
      { id: "library", kind: "scene", name: "图书馆", image_url: "/scene.png" },
      { id: "book", kind: "prop", name: "古籍", image_url: "" },
      { id: "other", kind: "character", name: "不在本镜的人物", image_url: "/other.png" },
    ].map(asset => ({ project_id: "project-test", role: null, description: null, visual_prompt: null, voice_id: null, extra: {}, created_at: "2026-09-27", updated_at: "2026-09-27", ...asset })),
    assetRefs: [
      { asset_id: "hero", name: "沈砚 · 现代", image_url: "/hero.png", kind: "character", index: 0, token: "" },
      { asset_id: "hero", name: "沈砚 · 古代", image_url: "/period.png", kind: "character", index: 0, token: "" },
      { asset_id: "other", name: "未关联参考", image_url: "/other.png", kind: "character", index: 0, token: "" },
    ],
    group: { id: "g1", beat_ids: ["shot-1"], common_prompt: "共用设定", reference_slots: [{ token: "<Picture 1>", index: 1, asset_id: "hero", kind: "character", name: "正式参考", image_url: "/video.png" }] },
    disabled: false,
    onSelectAssets: vi.fn(), onGroupSettings: vi.fn(), onWritingReferences: vi.fn(),
    onGenerateSketch: vi.fn(), onGenerateTriptych: vi.fn(), onOpenPrompts: vi.fn(),
  }
}
function nodes(node: ReactNode, type: unknown): Array<Record<string, any>> {
  if (Array.isArray(node)) return node.flatMap(child => nodes(child, type))
  if (!isValidElement<{ children?: ReactNode }>(node)) return []
  return [...(node.type === type ? [node.props] : []), ...nodes(node.props.children, type)]
}

describe("workshop full-width materials", () => {
  it("exposes assets, final references, sketches and writing references without nested accordions", () => {
    const input = fixture()
    const tree = WorkshopMaterialsPanel(input)
    const html = renderToStaticMarkup(tree)
    for (const label of ["本镜人物", "本镜场景", "本镜道具", "最终视频参考", "画面草图", "本镜写稿参考"]) expect(html).toContain(label)
    expect(nodes(tree, Collapse)).toHaveLength(0)
    expect(html).not.toContain("动作预演")
    expect(html).not.toContain("h3-material-left")
    expect(html).toContain("同组共享编号")
    expect(html).toContain("不会自动作为视频输入")
  })
  it("keeps the selected character look, image previews and full asset names", () => {
    const tree = WorkshopMaterialsPanel(fixture())
    expect(nodes(tree, Image).find(image => image.alt === "沈砚")?.src).toBe("/period.png")
    const html = renderToStaticMarkup(tree)
    expect(html).toContain("古代造型")
    expect(html).toContain("暂无图片")
    expect(html).not.toContain("不在本镜的人物")
    expect(html).not.toContain("未关联参考")
    expect(html).toContain("&lt;Picture 1&gt;")
  })
  it("provides useful empty states without fabricating references", () => {
    const input = fixture(); input.assets = []; input.assetRefs = []; input.group = undefined; input.beat = { id: "empty", sequence: 2 }
    const html = renderToStaticMarkup(<WorkshopMaterialsPanel {...input} />)
    for (const label of ["尚未关联人物", "尚未关联场景", "尚未关联道具", "尚未配置视频参考图", "关联带图片的资产"]) expect(html).toContain(label)
  })
  it("opens the original asset pickers and group settings without submitting generation", () => {
    const input = fixture(); const buttons = nodes(WorkshopMaterialsPanel(input), Button)
    for (const label of ["选择人物与造型", "选择场景", "选择道具"]) buttons.find(button => button.children === label)!.onClick()
    expect(input.onSelectAssets).toHaveBeenNthCalledWith(1, "character")
    expect(input.onSelectAssets).toHaveBeenNthCalledWith(2, "scene")
    expect(input.onSelectAssets).toHaveBeenNthCalledWith(3, "prop")
    buttons.find(button => button.children === "管理本组参考")!.onClick()
    expect(input.onGroupSettings).toHaveBeenCalledOnce()
    expect(input.onGenerateSketch).not.toHaveBeenCalled()
    expect(input.onGenerateTriptych).not.toHaveBeenCalled()
  })
  it("keeps optional generation explicit and routes to the prompt tab", () => {
    const input = fixture(); const buttons = nodes(WorkshopMaterialsPanel(input), Button)
    buttons[0].onClick()
    buttons.find(button => button.children === "重新生成")!.onClick()
    buttons.find(button => button.children === "生成三联关键帧")!.onClick()
    expect(input.onOpenPrompts).toHaveBeenCalledOnce()
    expect(input.onGenerateSketch).toHaveBeenCalledOnce()
    expect(input.onGenerateTriptych).toHaveBeenCalledOnce()
  })
  it("changes writing references only, preserves order, and does not mutate input", () => {
    const input = fixture(); const original = structuredClone(input.beat)
    const checks = nodes(WorkshopMaterialsPanel(input), Checkbox)
    checks.find(check => check["aria-label"] === "写稿参考：沈砚 · 古代")!.onChange({ target: { checked: true } })
    expect(input.onWritingReferences).toHaveBeenLastCalledWith(["/hero.png", "/period.png"])
    checks.find(check => check["aria-label"] === "写稿参考：沈砚 · 现代")!.onChange({ target: { checked: false } })
    expect(input.onWritingReferences).toHaveBeenLastCalledWith([])
    expect(input.beat).toEqual(original)
    expect(input.group?.reference_slots[0].image_url).toBe("/video.png")
  })
  it("deduplicates writing image choices and keeps sketches selectable", () => {
    const input = fixture(); input.assetRefs.push(input.assetRefs[0])
    const checks = nodes(WorkshopMaterialsPanel(input), Checkbox)
    expect(checks).toHaveLength(3)
    expect(checks.map(check => check["aria-label"])).toContain("写稿参考：本镜草图")
    checks[0].onChange({ target: { checked: true } })
    expect(input.onWritingReferences).toHaveBeenLastCalledWith(["/hero.png"])
  })
  it("locks edits while busy or without a plan but leaves prompt navigation available", () => {
    const input = fixture(); input.disabled = true
    const tree = WorkshopMaterialsPanel(input)
    expect(nodes(tree, Button)[0].disabled).not.toBe(true)
    expect(nodes(tree, Button).slice(1).every(button => button.disabled)).toBe(true)
    expect(nodes(tree, Checkbox).every(check => check.disabled)).toBe(true)
  })
})
