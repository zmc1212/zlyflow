import { renderToStaticMarkup } from "react-dom/server"
import type { ComponentProps } from "react"
import { describe, expect, it } from "vitest"
import type { CompareSource } from "./image-compare"
import ImageStudioModule, { type ImageResult } from "./ImageStudioModule"
import { mediaActions } from "./media-actions"
import type { MediaHandoffSource } from "../media-handoff"
import { IMAGE_INPAINT_WORKFLOW, IMAGE_OUTPAINT_WORKFLOW } from "../generation/image-edit"

const MODES = [
  { id: "grs-gpt-image-2.5", name: "GRS 改图", media_type: "image", available: true },
  { id: IMAGE_INPAINT_WORKFLOW, media_type: "image", available: true },
  { id: IMAGE_OUTPAINT_WORKFLOW, media_type: "image", available: true },
]

const resolveActions = (source: MediaHandoffSource) => mediaActions({
  kind: "image",
  source,
  modes: MODES,
  host: { createVideo: true, canvas: true },
})

function result(status: ImageResult["output"]["delivery_status"] = "cloud", src: string | undefined = "/image.png"): ImageResult {
  return { jobId: "job-1", generationItemId: "item-1", outputIndex: 0, src, output: {
    kind: "image", path: "image.png", label: "测试图片", delivery_status: status, cloud_url: "/image.png",
  } }
}

function render(results: ImageResult[], props: { compare?: CompareSource } & Partial<ComponentProps<typeof ImageStudioModule>> = {}) {
  return renderToStaticMarkup(<ImageStudioModule results={results} roundCount={1} onDownload={() => {}} onPreview={() => {}} resolveActions={resolveActions} {...props} />)
}

function buttonByLabel(html: string, label: string): string | undefined {
  const match = [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].find(([, attributes]) => attributes.includes(`aria-label="${label}"`))
  return match && `${match[1]}${match[2]}`
}

describe("image result availability", () => {
  it("keeps preview and download bound to the original image without imposing dimensions", () => {
    const html = render([result()])
    expect(html).toContain('src="/image.png"')
    expect(html).toContain('aria-label="放大预览测试图片"')
    expect(html).toContain('aria-label="下载测试图片"')
    expect(html).not.toMatch(/<img[^>]+(?:width|height)=/)
  })

  it("keeps expired media unavailable even if its old cloud URL is still present", () => {
    const html = render([result("expired")])
    expect(html).toContain("云端文件已过期")
    expect(html).not.toContain('<img ')
    expect(html).not.toContain('aria-label="放大预览测试图片"')
    expect(buttonByLabel(html, "下载测试图片")).toContain('disabled=""')
  })

  it("offers a direct download when the preview is missing, without exposing a broken image", () => {
    const item = result("local")
    item.src = undefined
    const html = render([item])
    expect(html).toContain("图片暂不可用")
    expect(html).toContain("已保存到员工电脑")
    expect(html).not.toContain('<img ')
    expect(html).not.toContain('aria-label="放大预览测试图片"')
  })
})

describe("image result hover actions", () => {
  it("renders the registry bar as icons and the rest behind 更多", () => {
    const html = render([result()])
    expect(html).toContain('aria-label="图片编辑测试图片"')
    expect(html).toContain('aria-label="局部重绘测试图片"')
    expect(html).toContain('aria-label="生成视频测试图片"')
    expect(html).toContain('aria-label="更多测试图片操作"')
    // 扩图在注册表里归「更多」，不该出现在悬浮图标条里
    expect(html).not.toContain('aria-label="扩图测试图片"')
  })

  it("holds the quick tools back but keeps task actions when the media cannot be previewed", () => {
    const missing = result("local")
    missing.src = undefined
    const html = render([missing])
    expect(html).not.toContain('aria-label="图片编辑测试图片"')
    expect(html).toContain('aria-label="更多测试图片操作"')
  })

  it("drops actions whose workflow is unavailable without touching the rest", () => {
    const withoutInpaint = (source: MediaHandoffSource) => mediaActions({
      kind: "image", source, modes: MODES.filter((mode) => mode.id !== IMAGE_INPAINT_WORKFLOW), host: { createVideo: true },
    })
    const html = render([result()], { resolveActions: withoutInpaint })
    expect(html).not.toContain('aria-label="局部重绘测试图片"')
    expect(html).toContain('aria-label="图片编辑测试图片"')
  })

  it("shows nothing when the caller cannot locate the output", () => {
    const orphan = result()
    delete orphan.jobId
    const html = render([orphan])
    expect(html).not.toContain('aria-label="图片编辑测试图片"')
    expect(html).toContain('aria-label="下载测试图片"')
  })
})

describe("image result compare", () => {
  const compare: CompareSource = { src: "/api/jobs/j/rounds/r/references/1", label: "原图" }

  it("offers the source-image toggle only for pixel-aligned workflows", () => {
    expect(render([result()])).not.toContain("对比原图")
    const html = render([result()], { compare })
    expect(html).toContain('aria-label="对比原图"')
    expect(html).toContain('aria-pressed="false"')
    expect(html).toContain('src="/image.png"')
    expect(html).not.toContain(compare.src)
  })

  it("hides the toggle when there is no result to compare against", () => {
    expect(render([result("expired")], { compare })).not.toContain("对比原图")
    const missing = result("local")
    missing.src = undefined
    expect(render([missing], { compare })).not.toContain("对比原图")
  })
})
