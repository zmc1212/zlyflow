import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { IMAGE_BACKGROUND_REMOVE_WORKFLOW } from "../generation/image-edit"
import ImageBgRemoveEditor from "./ImageBgRemoveEditor"
import ImageBgRemoveTool from "./ImageBgRemoveTool"

function renderWithClient(ui: React.ReactElement, client: QueryClient) {
  return renderToStaticMarkup(<MemoryRouter><QueryClientProvider client={client}>{ui}</QueryClientProvider></MemoryRouter>)
}

describe("image bg remove landing", () => {
  it("renders jimeng-style upload entry with local upload and asset picker", () => {
    const client = new QueryClient()
    client.setQueryData(["tool-workflow", IMAGE_BACKGROUND_REMOVE_WORKFLOW], { id: IMAGE_BACKGROUND_REMOVE_WORKFLOW, available: true })
    const html = renderWithClient(<ImageBgRemoveTool csrfToken="" />, client)
    expect(html).toContain("图片去背景")
    expect(html).toContain("将文件拖至此处添加")
    expect(html).toContain("从本地上传")
    expect(html).toContain("从资产选取")
    // 落地页不暴露任何工作流参数控件（参数由后端托管）。
    expect(html).not.toContain("更多设置")
    client.clear()
  })

  it("shows unavailable banner when the workflow is offline", () => {
    const client = new QueryClient()
    client.setQueryData(["tool-workflow", IMAGE_BACKGROUND_REMOVE_WORKFLOW], {
      id: IMAGE_BACKGROUND_REMOVE_WORKFLOW,
      available: false,
      unavailable_reason: "视频服务连接不可用",
    })
    const html = renderWithClient(<ImageBgRemoveTool csrfToken="" />, client)
    expect(html).toContain("视频服务连接不可用")
    client.clear()
  })
})

describe("image bg remove canvas editor", () => {
  it("renders an empty state without a job id and touches no canvas api", () => {
    const client = new QueryClient()
    const html = renderWithClient(<ImageBgRemoveEditor csrfToken="" />, client)
    expect(html).toContain("画布任务不存在")
    expect(html).toContain("去上传图片")
    client.clear()
  })

  it("renders the running canvas shell for a queued job", () => {
    const client = new QueryClient()
    client.setQueryData(["bg-remove-editor-job", "job-1"], {
      id: "job-1",
      mode: IMAGE_BACKGROUND_REMOVE_WORKFLOW,
      status: "running",
      outputs: [],
      references: [{ index: 1, url: "/api/jobs/job-1/references/1", kind: "image" }],
      rounds: [{ id: "round-1", reference_count: 1, references: [{ index: 1, url: "/api/jobs/job-1/references/1", kind: "image" }] }],
    })
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/tools/image-bg-remove/editor?job=job-1"]}>
        <QueryClientProvider client={client}><ImageBgRemoveEditor csrfToken="" /></QueryClientProvider>
      </MemoryRouter>,
    )
    expect(html).toContain("节点 1 · 生成中")
    expect(html).toContain("正在读取原图")
    expect(html).toContain('aria-label="画笔"')
    expect(html).toContain('aria-label="橡皮擦"')
    // 运行中不允许重复生成
    expect(html).toContain("bgremove-toolbar-generate")
    client.clear()
  })

  it("shows failed overlay with retry when the job failed", () => {
    const client = new QueryClient()
    client.setQueryData(["bg-remove-editor-job", "job-2"], {
      id: "job-2",
      mode: IMAGE_BACKGROUND_REMOVE_WORKFLOW,
      status: "failed",
      error: "视频服务连接中断",
      outputs: [],
    })
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/tools/image-bg-remove/editor?job=job-2"]}>
        <QueryClientProvider client={client}><ImageBgRemoveEditor csrfToken="" /></QueryClientProvider>
      </MemoryRouter>,
    )
    expect(html).toContain("去背景任务失败")
    expect(html).toContain("重新生成")
    client.clear()
  })
})
