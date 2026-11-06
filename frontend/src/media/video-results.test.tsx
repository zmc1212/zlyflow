import { renderToStaticMarkup } from "react-dom/server"
import type { ComponentProps } from "react"
import { describe, expect, it, vi } from "vitest"
import type { MediaHandoffSource } from "../media-handoff"
import { INPAINT_WORKFLOW } from "../generation/inpaint"
import { LIP_SYNC_WORKFLOW } from "../generation/lip-sync"
import { UPSCALE_ENGINE_SEEDVR2 } from "../generation/upscale"
import { mediaActions } from "./media-actions"
import VideoStudioModule, { type VideoResult } from "./VideoStudioModule"

const MODES = [
  { id: UPSCALE_ENGINE_SEEDVR2, media_type: "video", available: true },
  { id: INPAINT_WORKFLOW, media_type: "video", available: true },
  { id: LIP_SYNC_WORKFLOW, media_type: "video", available: true },
]

const resolveActions = (source: MediaHandoffSource) => mediaActions({
  kind: "video", source, modes: MODES, host: { canvas: true, jianying: true, params: true, remove: true },
})

function result(status: NonNullable<VideoResult["output"]["delivery_status"]> = "cloud", src: string | undefined = "/clip.mp4"): VideoResult {
  return { jobId: "job-1", generationItemId: "item-1", outputIndex: 0, src, output: {
    kind: "video", path: "clip.mp4", label: "测试视频", delivery_status: status, cloud_url: "/clip.mp4",
  } }
}

function render(results: VideoResult[], props: Partial<ComponentProps<typeof VideoStudioModule>> = {}) {
  return renderToStaticMarkup(<VideoStudioModule results={results} roundCount={1} onDownload={() => {}} resolveActions={resolveActions} {...props} />)
}

describe("video result hover actions", () => {
  it("takes the quick tools from the registry instead of hard-coded entries", () => {
    const html = render([result()])
    expect(html).toContain('aria-label="视频超清"')
    expect(html).toContain('aria-label="局部重拍"')
    expect(html).toContain('aria-label="口型同步"')
    expect(html).toContain('aria-label="更多视频操作"')
    // 加入画布、导出剪映 已交给注册表放进「更多」，悬浮条里不再各占一个文字按钮
    expect(html).not.toContain('aria-label="将当前视频加入画布"')
    expect(html).not.toContain('aria-label="导出当前视频到剪映"')
  })

  it("asks the host for actions with this version's own locator", () => {
    const resolve = vi.fn(resolveActions)
    render([result()], { resolveActions: resolve })
    expect(resolve).toHaveBeenCalledWith({ jobId: "job-1", generationItemId: "item-1", outputIndex: 0, kind: "video" })
  })

  it("keeps the in-place SeedVR2 item beside the registry menu", () => {
    const html = render([result()], { onEnhance: () => {}, resolveActions: () => [] })
    expect(html).toContain('aria-label="更多视频操作"')
    expect(html).not.toContain('aria-label="视频超清"')
  })

  it("holds the quick tools back but keeps task actions when the clip cannot be played", () => {
    const html = render([result("expired")])
    expect(html).toContain("云端文件已过期")
    expect(html).not.toContain('aria-label="视频超清"')
    expect(html).toContain('aria-label="更多视频操作"')
  })

  it("shows nothing when the caller cannot locate the output", () => {
    const orphan = result()
    delete orphan.jobId
    const html = render([orphan])
    expect(html).not.toContain('aria-label="视频超清"')
    expect(html).toContain('aria-label="下载当前视频"')
  })
})
