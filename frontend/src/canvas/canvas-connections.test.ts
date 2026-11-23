import { describe, expect, it } from "vitest"
import { canvasAcceptsNodeInput, canvasConnectEdge, canvasConnectInputs, canvasConnectMenuPosition, canvasConnectTargets, canvasVisibleTargetHandle } from "./canvas-connections"
import { incomingGeneratorPromptNodes, incomingGeneratorReferenceNodes, type CanvasWorkflowMode } from "./canvas-generation"
import { createArtboardNode, createAudioNode, createGeneratorNode, createImageNode, createTextNode, createVideoNode } from "./canvas-model"

const origin = { x: 0, y: 0 }
const imageMode: CanvasWorkflowMode = {
  id: "image-ref", name: "参考图生图", media_type: "image", min_references: 1, max_references: 3,
}
const videoMode: CanvasWorkflowMode = {
  id: "video-ref", name: "首帧生视频", media_type: "video", reference_mode: "keyframes", min_references: 1, max_references: 2,
}
const textMode: CanvasWorkflowMode = {
  id: "image-text", name: "文字生图", media_type: "image", min_references: 0, max_references: 0,
}
const depthMode: CanvasWorkflowMode = {
  id: "depth", name: "深度捕捉", media_type: "video", min_references: 1, max_references: 1, reference_slots: ["video"],
}
const avatarMode: CanvasWorkflowMode = {
  id: "avatar", name: "数字人口播", media_type: "video", min_references: 2, max_references: 2, accepts_audio_reference: true,
}
const modes = [imageMode, textMode, videoMode]

describe("canvas connection targets", () => {
  it("lists the image and video workflows that can use the upstream picture", () => {
    const photo = createImageNode(origin, "/api/files/ref.png")
    const generator = createGeneratorNode(origin, { mediaKind: "image", workflowId: textMode.id })
    generator.data = { ...generator.data, resultUrl: "/api/files/out.png" }
    for (const source of [photo, generator]) {
      expect(canvasConnectTargets(source, modes)).toEqual([
        { kind: "image", mode: imageMode },
        { kind: "video", mode: videoMode },
      ])
    }
  })

  it("recommends text, image and video from a text node in menu order", () => {
    const textVideo = { ...textMode, id: "text-video", media_type: "video" } as const
    const text = createTextNode(origin, "")
    expect(canvasConnectTargets(text, [...modes, textVideo])).toEqual([
      { kind: "text" },
      { kind: "image", mode: textMode },
      { kind: "video", mode: textVideo },
    ])
    expect(canvasConnectTargets(text, [])).toEqual([{ kind: "text" }])
  })

  it("skips unavailable workflows and workflows with incompatible required slots", () => {
    const source = createImageNode(origin, "/ref.png")
    expect(canvasConnectTargets(source, [
      { ...imageMode, available: false },
      { ...videoMode, reference_slots: ["image", "video"], min_references: 2 },
      { ...videoMode, reference_slots: ["video"] },
      textMode,
    ])).toEqual([])
  })

  it("can create a downstream generator before an image result is ready", () => {
    expect(canvasConnectTargets(createGeneratorNode(origin, { mediaKind: "image" }), modes).map(({ kind }) => kind))
      .toEqual(["image", "video"])
  })

  it("recommends text for video sources and text and audio for audio sources", () => {
    const allModes = [...modes, depthMode, avatarMode]
    for (const source of [createVideoNode(origin), createGeneratorNode(origin, { mediaKind: "video" })]) {
      expect(canvasConnectTargets(source, allModes)).toEqual([{ kind: "text" }, { kind: "video", mode: depthMode }])
      expect(canvasConnectTargets(source, [])).toEqual([{ kind: "text" }])
    }
    const audio = createAudioNode(origin)
    expect(canvasConnectTargets(audio, allModes)).toEqual([{ kind: "text" }, { kind: "video", mode: avatarMode }, { kind: "audio" }])
    expect(canvasConnectTargets(audio, [depthMode, { ...avatarMode, available: false }])).toEqual([{ kind: "text" }, { kind: "audio" }])
  })

  it("recommends upstream nodes only for compatible unfilled slots", () => {
    const audio = createAudioNode(origin)
    const generator = createGeneratorNode(origin, { workflowId: avatarMode.id, mediaKind: "video" })
    expect(canvasConnectInputs(generator, [avatarMode], [])).toEqual([{ kind: "text" }, { kind: "image" }, { kind: "audio" }])
    expect(canvasConnectInputs(generator, [avatarMode], [audio])).toEqual([{ kind: "text" }, { kind: "image" }])
  })

  it("uses the same media rules for upstream menus and direct connections", () => {
    const text = createTextNode(origin)
    const audio = createAudioNode(origin)
    const video = createVideoNode(origin)
    const generatedVideo = createGeneratorNode(origin, { mediaKind: "video" })
    const image = createImageNode(origin, "/ref.png")
    expect(canvasConnectInputs(text, [], [])).toEqual([{ kind: "text" }, { kind: "video" }, { kind: "audio" }])
    expect(canvasConnectInputs(audio, [], [])).toEqual([{ kind: "text" }, { kind: "audio" }])
    expect(canvasAcceptsNodeInput(video, "text")).toBe(true)
    expect(canvasAcceptsNodeInput(generatedVideo, "text")).toBe(true)
    expect(canvasAcceptsNodeInput(audio, "text")).toBe(true)
    expect(canvasAcceptsNodeInput(audio, "audio")).toBe(true)
    expect(canvasAcceptsNodeInput(text, "text")).toBe(true)
    expect(canvasAcceptsNodeInput(text, "audio")).toBe(true)
    expect(canvasAcceptsNodeInput(video, "audio")).toBe(false)
    expect(canvasAcceptsNodeInput(image, "text")).toBe(false)
  })

  it("has no target for unsupported outputs or unfilled image nodes", () => {
    for (const source of [createArtboardNode(origin), createImageNode(origin), createGeneratorNode(origin), undefined]) {
      expect(canvasConnectTargets(source, modes)).toEqual([])
    }
  })
})

describe("canvas connection edges", () => {
  it("uses one input handle for both connected text and reference pictures", () => {
    const text = createTextNode(origin, "镜头提示词")
    const image = createImageNode(origin, "/ref.png")
    const target = createGeneratorNode(origin)
    const nodes = [text, image, target]
    const edges = [canvasConnectEdge(text.id, target.id), canvasConnectEdge(image.id, target.id, "preview")]
    expect(edges.map((edge) => edge.targetHandle)).toEqual(["in", "in"])
    expect(edges[0].id).toBe(`cc-edge__${text.id}|out|${target.id}|in`)
    expect(edges[1].sourceHandle).toBe("preview")
    expect(incomingGeneratorPromptNodes(nodes, edges, target.id)).toEqual([text])
    expect(incomingGeneratorReferenceNodes(nodes, edges, target.id)).toEqual([image])
  })

  it("displays legacy prompt edges on the single input without changing their IDs or payload", () => {
    const edge = { ...canvasConnectEdge("text", "generator"), id: "cc-edge__text|out|generator|prompt", targetHandle: "prompt" }
    expect(canvasVisibleTargetHandle(edge)).toBe("in")
    expect(edge.targetHandle).toBe("prompt")
  })

  it("preserves the destination handle when adding an upstream node", () => {
    expect(canvasConnectEdge("upstream", "selected", "out", "destination")).toMatchObject({
      id: "cc-edge__upstream|out|selected|destination", sourceHandle: "out", targetHandle: "destination",
    })
  })
})

describe("canvas connection menu placement", () => {
  it("clamps the menu inside the stage", () => {
    const stage = { width: 900, height: 600 }
    expect(canvasConnectMenuPosition({ x: -20, y: -8 }, stage, 2)).toEqual({ x: 8, y: 8 })
    expect(canvasConnectMenuPosition({ x: 880, y: 590 }, stage, 2)).toEqual({ x: 660, y: 460 })
  })
})
