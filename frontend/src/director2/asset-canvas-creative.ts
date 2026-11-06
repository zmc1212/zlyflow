import type { Node, Edge } from "@xyflow/react"
import { creativeStyleText, type CreativeStyle } from "./creative-presets"
import { targetKey, type AssetCanvasTarget } from "./asset-canvas-model"
import type { Director2Asset } from "./api"
import type { CanvasJobOutput, CanvasWorkflowMode } from "../canvas/canvas-generation"

export const UNIVERSAL_ASSET_NODE_KINDS = ["generator", "image", "video", "text", "audio", "editor"] as const
export type UniversalAssetNodeKind = typeof UNIVERSAL_ASSET_NODE_KINDS[number]
export type CharacterDesign = Record<string, string>
export type AssetCreativeSettings = { style?: CreativeStyle; design?: CharacterDesign; aspectRatio?: string }
export const EMPTY_CREATIVE_STYLE: CreativeStyle = { presetId: "none", custom: "" }

export function isUniversalAssetNodeKind(value: unknown): value is UniversalAssetNodeKind {
  return UNIVERSAL_ASSET_NODE_KINDS.includes(value as UniversalAssetNodeKind)
}

export function assetCreativeSettings(asset: Director2Asset, target: AssetCanvasTarget): AssetCreativeSettings {
  return asset.extra?.canvas_settings?.[targetKey(target)] || {}
}

export function compileAssetCreativePrompt(prompt: string, settings: AssetCreativeSettings = {}): string {
  const design = Object.entries(settings.design || {}).filter(([, value]) => typeof value === "string" && value.trim()).map(([key, value]) => `${key}：${value.trim()}`)
  const style = settings.style ? creativeStyleText(settings.style) : ""
  return [prompt.trim(), design.length ? `角色设计：${design.join("；")}` : "", style ? `视觉风格：${style}` : ""].filter(Boolean).join("\n\n")
}

export function assetCanvasNodeKind(node: Node | undefined): string {
  if (!node) return ""
  if (node.data.origin === "canvas") return String(node.data.canvasKind || node.type || "")
  const asset = node.data.asset as Director2Asset | undefined
  return node.data.role === "image" ? asset?.kind || "image" : node.data.role === "definition" ? "text" : "image"
}

/** 菜单包含可保存的创作关系；执行器提交前再校验媒体与工作流的输入能力。 */
export function assetCanvasOutputKinds(node: Node | undefined): string[] {
  const kind = assetCanvasNodeKind(node)
  if (kind === "character") return ["image", "video", "audio", "character", "text"]
  if (kind === "scene") return ["image", "video", "scene", "text"]
  if (kind === "audio") return ["editor", "text"]
  if (kind === "video" || (kind === "generator" && node?.data.resultKind !== "image")) return ["video", "editor", "text"]
  return ["image", "video", "text", "editor"]
}

export function assetCanvasConnectionIssue(nodes: Node[], edges: Edge[], source: string, target: string): string {
  if (source === target) return "不能连接节点自身"
  const from = nodes.find(node => node.id === source), to = nodes.find(node => node.id === target)
  if (!from || !to) return "节点已不存在"
  if (from.type === "assetGroup" || to.type === "assetGroup") return "请连接组内的具体节点"
  if (edges.some(edge => edge.source === source && edge.target === target)) return "这两个节点已经连接"
  const visited = new Set<string>()
  const pending = [target]
  while (pending.length) {
    const id = pending.pop()!
    if (id === source) return "该连接会形成循环引用"
    if (visited.has(id)) continue
    visited.add(id)
    pending.push(...edges.filter(edge => edge.source === id).map(edge => edge.target))
  }
  return ""
}

export function assetCanvasMedia(node: Node): { url: string; kind: "image" | "video" | "audio"; name: string; duration: number } | null {
  const kind = node.data.origin === "canvas" ? node.data.canvasKind === "generator" ? node.data.resultKind || "video" : node.data.canvasKind : "image"
  if (!["image", "video", "audio"].includes(String(kind))) return null
  const url = String(node.data.image || node.data.url || node.data.resultUrl || "")
  if (!url) return null
  return { url, kind: kind as "image" | "video" | "audio", name: String(node.data.label || node.data.title || "画布素材"), duration: Number(node.data.duration) || 5 }
}

export function canvasWorkflowReferenceKind(mode: CanvasWorkflowMode, index: number, count: number): "image" | "video" | "audio" {
  const slots = mode.reference_slots || []
  if (slots.length && index <= slots.length) return count < slots.length ? index === count ? slots[slots.length - 1] : "image" : slots[index - 1]
  return index === 2 && mode.accepts_video_reference ? "video" : index === 2 && mode.accepts_audio_reference ? "audio" : "image"
}

export function canvasEditingCloudUrl(url: string, data: Record<string, unknown>, kind: string, outputs: CanvasJobOutput[]): string | null {
  const matching = outputs.find(output => output.download_url === url || output.cloud_url === url
    || (typeof data.assetPath === "string" && output.path === data.assetPath)
    || (typeof data.resultPath === "string" && output.path === data.resultPath))
  return matching?.cloud_url || outputs.find(output => output.kind === kind && output.cloud_url)?.cloud_url || null
}

export function moveAssetCanvasReference(edges: Edge[], target: string, source: string, delta: -1 | 1): Edge[] {
  const indices = edges.map((edge, index) => edge.target === target ? index : -1).filter(index => index >= 0)
  const from = indices.findIndex(index => edges[index].source === source), to = from + delta
  if (from < 0 || to < 0 || to >= indices.length) return edges
  const result = [...edges]
  ;[result[indices[from]], result[indices[to]]] = [result[indices[to]], result[indices[from]]]
  return result
}

/** Editing, dragging and progress updates must not restart the polling effect. */
export function assetCanvasPollingKey(nodes: Node[]): string {
  return nodes.filter(node => node.data.origin === "canvas" && typeof node.data.jobId === "string" && node.data.jobId
    && ["queued", "running", "awaiting_refine", "canceling"].includes(String(node.data.jobStatus)))
    .map(node => `${node.id}:${node.data.jobId}`).sort().join("|")
}
