import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { UPSCALE_ENGINE_LABEL, UPSCALE_ENGINE_RELAYVSR, UPSCALE_ENGINE_RTX, UPSCALE_ENGINE_SEEDVR2 } from "../generation/upscale"
import VideoUpscaleTool from "./VideoUpscaleTool"

describe("video upscale tool default creation form", () => {
  it("offers every upscale engine and keeps the submit button disabled without a source video", () => {
    const html = renderToStaticMarkup(<MemoryRouter>
      <VideoUpscaleTool csrfToken="" />
    </MemoryRouter>)
    expect(html).toContain("视频超分")
    expect(html).toContain(UPSCALE_ENGINE_LABEL[UPSCALE_ENGINE_RTX])
    expect(html).toContain(UPSCALE_ENGINE_LABEL[UPSCALE_ENGINE_SEEDVR2])
    expect(html).toContain(UPSCALE_ENGINE_LABEL[UPSCALE_ENGINE_RELAYVSR])
    expect(html).toContain("开始增强")
    expect(html).toContain('aria-label="增强引擎"')
  })
})
