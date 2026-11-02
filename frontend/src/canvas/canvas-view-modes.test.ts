import { describe, expect, it } from "vitest"
import type { Edge } from "@xyflow/react"
import {
  CANVAS_CONNECTION_MODE_OPTIONS,
  CANVAS_GENERATION_MODE_OPTIONS,
  compactCanvasEdgeIds,
  canvasConnectionModeLabel,
  canvasGenerationModeLabel,
} from "./canvas-view-modes"

function edge(id: string, source: string, target: string): Edge {
  return { id, source, target }
}

const chain = [
  edge("e1", "a", "b"),
  edge("e2", "b", "c"),
  edge("e3", "c", "d"),
  edge("e4", "x", "y"),
]

function ids(...values: string[]): Set<string> {
  return new Set(values)
}

describe("canvas view mode options", () => {
  it("lists the three connection modes in reference order", () => {
    expect(CANVAS_CONNECTION_MODE_OPTIONS.map((option) => option.value)).toEqual(["off", "compact", "full"])
    expect(CANVAS_CONNECTION_MODE_OPTIONS.map((option) => option.label)).toEqual(["关闭", "精简", "完全"])
  })

  it("lists independent before aggregate", () => {
    expect(CANVAS_GENERATION_MODE_OPTIONS.map((option) => option.value)).toEqual(["independent", "aggregate"])
    expect(CANVAS_GENERATION_MODE_OPTIONS.map((option) => option.label)).toEqual(["独立", "聚合"])
  })

  it("resolves labels for persisted settings", () => {
    expect(canvasConnectionModeLabel("compact")).toBe("精简")
    expect(canvasGenerationModeLabel("aggregate")).toBe("聚合")
  })
})

describe("compact canvas edge focus", () => {
  it("keeps the whole upstream and downstream chain of a selected node", () => {
    expect(compactCanvasEdgeIds(chain, {
      selectedNodeIds: ids("c"),
      selectedEdgeIds: ids(),
    })).toEqual(ids("e1", "e2", "e3"))
  })

  it("keeps the chain of a hovered node", () => {
    expect(compactCanvasEdgeIds(chain, {
      selectedNodeIds: ids(),
      selectedEdgeIds: ids(),
      hoveredNodeId: "b",
    })).toEqual(ids("e1", "e2", "e3"))
  })

  it("merges hover and selection without touching unrelated components", () => {
    expect(compactCanvasEdgeIds(chain, {
      selectedNodeIds: ids("d"),
      selectedEdgeIds: ids(),
      hoveredNodeId: "y",
    })).toEqual(ids("e1", "e2", "e3", "e4"))
  })

  it("keeps a selected or recently created edge and its nodes", () => {
    expect(compactCanvasEdgeIds(chain, {
      selectedNodeIds: ids(),
      selectedEdgeIds: ids("e4"),
    })).toEqual(ids("e4"))
    expect(compactCanvasEdgeIds(chain, {
      selectedNodeIds: ids(),
      selectedEdgeIds: ids(),
      recentEdgeId: "e2",
    })).toEqual(ids("e1", "e2", "e3"))
  })

  it("shows nothing when no node or edge is focused", () => {
    expect(compactCanvasEdgeIds(chain, {
      selectedNodeIds: ids(),
      selectedEdgeIds: ids(),
      hoveredNodeId: null,
      recentEdgeId: null,
    })).toEqual(ids())
  })
})
