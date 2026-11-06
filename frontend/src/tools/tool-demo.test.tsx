import { existsSync } from "node:fs"
import { join } from "node:path"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import ToolDemoModal, { hasToolDemoSeen, markToolDemoSeen } from "./ToolDemoModal"
import { STUDIO_TOOLS, type StudioTool } from "./tool-registry"

const demoTools = STUDIO_TOOLS.filter((tool) => tool.demo)

describe("tool demo registry", () => {
  it("only ships demos for available tools with local comparison assets", () => {
    expect(demoTools.length).toBeGreaterThanOrEqual(8)
    for (const tool of demoTools) {
      expect(tool.status).toBe("available")
      expect(tool.demo?.src.startsWith("/tool-demos/")).toBe(true)
      expect(tool.demo?.caption.length).toBeGreaterThan(8)
      expect(existsSync(join(process.cwd(), "public", tool.demo!.src))).toBe(true)
    }
  })

  it("keeps the motion transfer demo as the flagship video comparison", () => {
    const tool = demoTools.find((item) => item.id === "motion-transfer")
    expect(tool?.demo?.kind).toBe("video")
    expect(tool?.demo?.src).toBe("/tool-demos/motion-transfer.mp4")
  })

  it("ships the character swap demo built from the verified task", () => {
    const tool = demoTools.find((item) => item.id === "character-replace")
    expect(tool?.demo?.kind).toBe("video")
    expect(tool?.demo?.src).toBe("/tool-demos/character-replace.mp4")
    expect(tool?.demo?.caption).toContain("女主")
  })
})

describe("tool demo first-open bookkeeping", () => {
  it("persists the seen flag per tool in localStorage", () => {
    const store = new Map<string, string>()
    const previous = (globalThis as { localStorage?: unknown }).localStorage
    ;(globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value) },
    }
    try {
      expect(hasToolDemoSeen("video-upscale")).toBe(false)
      markToolDemoSeen("video-upscale")
      expect(hasToolDemoSeen("video-upscale")).toBe(true)
      expect(hasToolDemoSeen("depth-capture")).toBe(false)
    } finally {
      ;(globalThis as { localStorage?: unknown }).localStorage = previous
    }
  })

  it("survives environments without localStorage", () => {
    expect(() => {
      expect(hasToolDemoSeen("motion-transfer")).toBe(false)
      markToolDemoSeen("motion-transfer")
    }).not.toThrow()
  })
})

describe("tool demo modal markup", () => {
  const tool = demoTools[0] as StudioTool
  it("renders nothing while closed so portals stay out of static markup", () => {
    const client = new QueryClient()
    const html = renderToStaticMarkup(
      <MemoryRouter><QueryClientProvider client={client}>
        <ToolDemoModal tool={tool} open={false} onClose={() => undefined} />
      </QueryClientProvider></MemoryRouter>,
    )
    client.clear()
    expect(html).toBe("")
  })
})
