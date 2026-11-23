import type { ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import CanvasProjectInfoModal, { canvasNodeDistribution, collectCanvasJobIds } from "./CanvasProjectInfoModal"
import { type CanvasNode, type CanvasProjectDetail } from "./canvas-model"

vi.mock("./canvas-api", () => ({
  fetchCanvasProjectCreditStats: vi.fn().mockResolvedValue({ total_credits: 0, task_count: 0, groups: [] }),
}))

vi.mock("antd", async (importOriginal) => ({
  ...await importOriginal<typeof import("antd")>(),
  // SSR 下内联弹层内容，让测试能覆盖真实渲染产物。
  Modal: ({ children, title }: { children: ReactNode; title: ReactNode }) => <section>{title}{children}</section>,
  Tabs: ({ items }: { items: Array<{ key: string; label: ReactNode; children: ReactNode }> }) => (
    <div>{items.map((item) => <section key={item.key}>{item.label}{item.children}</section>)}</div>
  ),
}))

function node(id: string, type: string, data: Record<string, unknown>): CanvasNode {
  return { id, type, position: { x: 0, y: 0 }, data } as CanvasNode
}

const project: CanvasProjectDetail = {
  id: "canvas-1",
  title: "测试画布",
  created_at: "2026-11-19T07:21:00Z",
  updated_at: "2026-11-21T16:31:00Z",
  draft_updated_at: "2026-11-21T16:31:00Z",
  version: 1,
  checksum: "abc",
  content: "{}",
  node_count: 3,
}

describe("collectCanvasJobIds", () => {
  it("collects job ids from provenance snapshots and dedupes", () => {
    const snapshot = { jobId: "job-a" }
    const nodes = [
      node("n1", "generator", { jobId: "job-live", lastRun: snapshot, runHistory: [{ jobId: "job-b" }] }),
      node("n2", "image", { sourceRun: { jobId: "job-b" }, sourceJobId: "job-legacy" }),
      node("n3", "video", { resultHistory: [{ url: "u", kind: "video", jobId: "job-c" }, { url: "u2", kind: "video" }] }),
      node("n4", "text", {}),
    ]
    expect(collectCanvasJobIds(nodes)).toEqual(["job-live", "job-a", "job-b", "job-legacy", "job-c"])
  })

  it("returns empty list for nodes without provenance", () => {
    expect(collectCanvasJobIds([node("n1", "image", {}), node("n2", "text", {})])).toEqual([])
  })
})

describe("canvasNodeDistribution", () => {
  it("maps node types to distribution cards and groups unknown types", () => {
    const nodes = [
      node("n1", "image", {}),
      node("n2", "image", {}),
      node("n3", "video", {}),
      node("n4", "audio", {}),
      node("n5", "text", {}),
      node("n6", "generator", {}),
      node("n7", "artboard", {}),
      node("n8", "legacy-custom", {}),
    ]
    const cards = canvasNodeDistribution(nodes)
    expect(cards[0]).toEqual({ label: "全部节点", count: 8, total: true })
    expect(cards.slice(1, -1).map((card) => `${card.label}:${card.count}`)).toEqual([
      "图片:2", "视频:1", "音频:1", "文本:1", "生成:1", "画板:1",
    ])
    expect(cards[cards.length - 1]).toEqual({ label: "其他", count: 1, total: false })
  })
})

describe("CanvasProjectInfoModal", () => {
  it("renders basic info and credit tabs with node distribution", () => {
    const html = renderToStaticMarkup(
      <CanvasProjectInfoModal
        open
        project={project}
        user={{ username: "zlyadmin", display_name: "天啊" }}
        nodes={[node("n1", "image", {}), node("n2", "video", {})]}
        csrfToken="token"
        onClose={() => undefined}
        onViewCreditDetails={() => undefined}
      />,
    )
    expect(html).toContain("项目信息")
    expect(html).toContain("基础信息")
    expect(html).toContain("积分消耗")
    expect(html).toContain("天啊")
    expect(html).toContain("创建时间")
    expect(html).toContain("最新修改")
    expect(html).toContain("节点分布")
    expect(html).toContain("全部节点")
    expect(html).toContain("查看积分明细")
  })
})
