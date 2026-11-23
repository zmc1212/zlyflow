import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import { CanvasGeneratorInspector } from "./CanvasGeneratorInspector"
import { type CanvasGeneratorLive, type CanvasWorkflowMode } from "./canvas-generation"
import { createGeneratorNode } from "./canvas-model"

vi.mock("../api", () => ({ requestJson: vi.fn(), notifyUnauthorized: vi.fn() }))

vi.mock("@xyflow/react", () => ({
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  NodeResizer: () => null,
  NodeToolbar: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Handle: () => null,
  useStore: () => 1,
  useUpdateNodeInternals: () => vi.fn(),
  useReactFlow: () => ({ updateNodeData: vi.fn() }),
}))

vi.mock("antd", async (importOriginal) => ({
  ...await importOriginal<typeof import("antd")>(),
  Tooltip: ({ title, children }: { title: ReactNode; children: ReactNode }) => <span data-tooltip={typeof title === "string" ? title : ""}>{children}</span>,
}))

const billedMode: CanvasWorkflowMode = {
  id: "grs-billed", name: "云端生图", media_type: "image", billing: { enabled: true },
  parameters: [{ name: "options", schema: { properties: {} } }],
}

function renderInspector({
  mode = billedMode,
  authenticated = true,
  live = null,
}: {
  mode?: CanvasWorkflowMode | null
  authenticated?: boolean
  live?: CanvasGeneratorLive | null
} = {}) {
  const node = createGeneratorNode({ x: 0, y: 0 }, { workflowId: mode?.id ?? "" })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <CanvasGeneratorInspector
        node={node}
        modes={mode ? [mode] : []}
        modesLoading={false}
        modesError={null}
        onReloadModes={vi.fn()}
        references={[]}
        promptNodes={[]}
        live={live}
        submitting={false}
        authenticated={authenticated}
        onPreview={vi.fn()}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
        onRefine={vi.fn()}
        onInsertResult={vi.fn()}
        onOpenJob={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

describe("generator inspector credit estimate", () => {
  it("shows the per-workflow estimate next to the submit button", () => {
    const html = renderInspector()
    expect(html).toContain("提交生成")
    expect(html).toContain("canvas-composer-cost")
    expect(html).toContain("本次预计消耗积分")
  })

  it("hides the estimate for guests, unbilled workflows and active jobs", () => {
    expect(renderInspector({ authenticated: false })).not.toContain("canvas-composer-cost")
    expect(renderInspector({ mode: { ...billedMode, billing: null } })).not.toContain("canvas-composer-cost")
    expect(renderInspector({ live: { jobId: "job-1", status: "running", progress: 12, updatedAt: 1 } })).not.toContain("canvas-composer-cost")
  })
})