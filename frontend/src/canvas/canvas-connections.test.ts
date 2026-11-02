import { describe, expect, it } from "vitest"
import {
  canvasConnectEdge,
  canvasConnectMenuPosition,
  canvasConnectTargets,
} from "./canvas-connections"
import { createArtboardNode, createGeneratorNode, createImageNode, createTextNode, createVideoNode } from "./canvas-model"

const origin = { x: 0, y: 0 }

describe("canvas connection targets", () => {
  it("offers a prompt generator for text nodes", () => {
    const targets = canvasConnectTargets(createTextNode(origin, "一只猫"))
    expect(targets).toHaveLength(1)
    expect(targets[0]).toMatchObject({ kind: "generator", targetHandle: "prompt" })
  })

  it("offers a reference generator for image nodes", () => {
    const targets = canvasConnectTargets(createImageNode(origin, "/api/files/ref.png"))
    expect(targets).toHaveLength(1)
    expect(targets[0]).toMatchObject({ kind: "generator", targetHandle: "in" })
  })

  it("offers continue and extract actions for image generator results", () => {
    const node = createGeneratorNode(origin, { mediaKind: "image", workflowId: "image-mode" })
    node.data = { ...node.data, resultUrl: "/api/files/out.png", resultKind: "image" }
    const targets = canvasConnectTargets(node)
    expect(targets.map((target) => target.kind)).toEqual(["generator", "image"])
    expect(targets.every((target) => target.targetHandle === "in")).toBe(true)
  })

  it("offers a video result node for video generator results", () => {
    const node = createGeneratorNode(origin, { mediaKind: "video", workflowId: "video-mode" })
    node.data = { ...node.data, resultUrl: "/api/files/out.mp4", resultKind: "video" }
    const targets = canvasConnectTargets(node)
    expect(targets).toHaveLength(1)
    expect(targets[0]).toMatchObject({ kind: "video", targetHandle: "in" })
  })

  it("creates downstream nodes before an image generator has produced a result", () => {
    const targets = canvasConnectTargets(createGeneratorNode(origin, { mediaKind: "image", workflowId: "image-mode" }))
    expect(targets.map((target) => target.kind)).toEqual(["generator", "image"])
    expect(targets[1].description).toBe("创建后自动接收生成结果")
  })

  it("creates a video node before a video generator has produced a result", () => {
    const targets = canvasConnectTargets(createGeneratorNode(origin, { mediaKind: "video", workflowId: "video-mode" }))
    expect(targets.map((target) => target.kind)).toEqual(["video"])
    expect(targets[0].description).toBe("创建后自动接收生成结果")
  })

  it("waits for a known output kind on legacy generators without stored media kind", () => {
    expect(canvasConnectTargets(createGeneratorNode(origin))).toEqual([])
  })

  it("does not offer targets for artboards, video sources or missing nodes", () => {
    expect(canvasConnectTargets(createArtboardNode(origin))).toEqual([])
    expect(canvasConnectTargets(createVideoNode(origin, "/api/files/clip.mp4"))).toEqual([])
    expect(canvasConnectTargets(null)).toEqual([])
  })
})

describe("canvas connection edges", () => {
  it("connects generator outputs to prompt and reference handles", () => {
    expect(canvasConnectEdge("text_1", "generator_1", "prompt")).toMatchObject({
      id: "cc-edge__text_1|out|generator_1|prompt",
      source: "text_1",
      target: "generator_1",
      sourceHandle: "out",
      targetHandle: "prompt",
      type: "smoothstep",
    })
    expect(canvasConnectEdge("image_1", "generator_1", "in").id).toBe("cc-edge__image_1|out|generator_1|in")
  })

  it("keeps a custom source handle for alternate node outputs", () => {
    expect(canvasConnectEdge("image_1", "image_2", "in", "preview")).toMatchObject({
      id: "cc-edge__image_1|preview|image_2|in",
      sourceHandle: "preview",
      targetHandle: "in",
    })
  })
})

describe("canvas connection menu placement", () => {
  it("clamps the menu inside the stage", () => {
    expect(canvasConnectMenuPosition({ x: -20, y: -8 }, { width: 900, height: 600 }, { width: 252, height: 96 }))
      .toEqual({ x: 8, y: 8 })
    expect(canvasConnectMenuPosition({ x: 880, y: 590 }, { width: 900, height: 600 }, { width: 252, height: 96 }))
      .toEqual({ x: 640, y: 496 })
  })

  it("rounds in-bounds positions", () => {
    expect(canvasConnectMenuPosition({ x: 120.4, y: 88.6 }, { width: 900, height: 600 }, { width: 252, height: 96 }))
      .toEqual({ x: 120, y: 89 })
  })
})
