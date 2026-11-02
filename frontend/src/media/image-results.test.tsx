import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import ImageStudioModule, { type ImageResult } from "./ImageStudioModule"

function result(status: ImageResult["output"]["delivery_status"] = "cloud", src: string | undefined = "/image.png"): ImageResult {
  return { generationItemId: "item-1", outputIndex: 0, src, output: {
    kind: "image", path: "image.png", label: "测试图片", delivery_status: status, cloud_url: "/image.png",
  } }
}

function render(results: ImageResult[]) {
  return renderToStaticMarkup(<ImageStudioModule results={results} roundCount={1} onDownload={() => {}} onPreview={() => {}} onCreateVideo={() => {}} />)
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
    const buttons = [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)]
    expect(buttons.find(([, attributes]) => attributes.includes('aria-label="下载测试图片"'))?.[1]).toContain('disabled=""')
    expect(buttons.find(([, , content]) => content.includes("生成视频"))?.[1]).toContain('disabled=""')
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
