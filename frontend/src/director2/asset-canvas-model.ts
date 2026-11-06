import type { Edge, Node, XYPosition } from "@xyflow/react"
import type { Director2Asset, Director2Job } from "./api"
import { MAX_SOURCE_REFERENCES, sourceReferencesOf } from "./asset-source-references"
import type { AssetIdentity } from "./panes/assets/shared"

export type AssetImageSlot = "identity" | "scene_master" | "scene_reverse" | "scene_pano" | "prop_reference" | "prop_turnaround" | "prop_detail"
export type AssetCanvasTarget = { type: AssetImageSlot; identityId?: string }
export type AssetCanvasData = Record<string, unknown> & {
  asset: Director2Asset
  role: "group" | "definition" | "references" | "image"
  key: string
  title: string
  target?: AssetCanvasTarget
  image?: string
}
export type AssetCanvasNode = Node<AssetCanvasData, "assetGroup" | "assetCreation">
export type AssetCanvasLink = { sourceAssetId: string; sourceKey: string; url: string }
export type AssetCanvasLayout = { version: 1; positions: Record<string, XYPosition>; links: AssetCanvasLink[] }

export const assetNodeId = (assetId: string, key: string) => `${assetId}::${key}`
export const targetKey = (target: AssetCanvasTarget) => target.type === "identity" ? `look:${target.identityId}` : target.type

export function assetCanvasJobNode(job: Director2Job): string | null {
  const payload = job.payload || {}
  const type = String(payload.target_type || "") as AssetImageSlot
  if (job.job_type !== "image_generation" || !payload.asset_id || !["identity", "scene_master", "scene_reverse", "scene_pano", "prop_reference", "prop_turnaround", "prop_detail"].includes(type)) return null
  if (type === "identity" && !payload.identity_id) return null
  return assetNodeId(String(payload.asset_id), targetKey({ type, identityId: payload.identity_id }))
}

export function canvasIdentities(asset: Director2Asset): AssetIdentity[] {
  const looks = Array.isArray(asset.extra?.identities) ? asset.extra.identities as AssetIdentity[] : []
  return looks.length ? looks.map((look, i) => ({ ...look, id: look.id || `look-${asset.id}-${i}` })) : [{
    id: `look-${asset.id}-default`, name: "初始造型", description: asset.description || asset.visual_prompt || "", image_url: asset.image_url || "",
  }]
}

export function assetImageSlots(asset: Director2Asset): { target: AssetCanvasTarget; title: string }[] {
  if (asset.kind === "character") return canvasIdentities(asset).map(look => ({ target: { type: "identity", identityId: look.id }, title: look.name || "角色形象" }))
  const slots: { target: AssetCanvasTarget; title: string }[] = asset.kind === "scene" ? [
    { target: { type: "scene_master" }, title: "场景设定图" },
  ] : [
    { target: { type: "prop_reference" }, title: "道具设定图" },
  ]
  return slots.map(slot => ({ ...slot, title: String(asset.extra?.canvas_node_names?.[targetKey(slot.target)] || slot.title) }))
}

export function assetSlotImage(asset: Director2Asset, target: AssetCanvasTarget): string {
  if (target.type === "identity") return String(canvasIdentities(asset).find(look => look.id === target.identityId)?.image_url || "")
  const key = ({ scene_master: "master_url", scene_reverse: "reverse_url", scene_pano: "pano_url", prop_reference: "reference_url", prop_turnaround: "turnaround_url", prop_detail: "detail_url" } as const)[target.type]
  return String(asset.extra?.[key] || (["scene_master", "prop_reference"].includes(target.type) ? asset.image_url : "") || "")
}

export function assetSlotPrompt(asset: Director2Asset, target: AssetCanvasTarget): string {
  if (target.type === "identity") {
    const look = canvasIdentities(asset).find(look => look.id === target.identityId)
    return String(look?.description || look?.appearance_details || asset.description || "")
  }
  const key = ({ scene_master: "environment_prompt", scene_reverse: "reverse_prompt", scene_pano: "pano_prompt", prop_reference: "visual_prompt", prop_turnaround: "turnaround_prompt", prop_detail: "detail_prompt" } as const)[target.type]
  return String(asset.extra?.[key] || (["scene_master", "prop_reference"].includes(target.type) ? asset.visual_prompt || asset.description : "") || "")
}

export function patchAssetSlotPrompt(asset: Director2Asset, target: AssetCanvasTarget, prompt: string): Record<string, unknown> {
  if (target.type === "identity") return { identities: canvasIdentities(asset).map(look => look.id === target.identityId ? { ...look, description: prompt, appearance_details: prompt } : look) }
  const key = ({ scene_master: "environment_prompt", scene_reverse: "reverse_prompt", scene_pano: "pano_prompt", prop_reference: "visual_prompt", prop_turnaround: "turnaround_prompt", prop_detail: "detail_prompt" } as const)[target.type]
  return { [key]: prompt }
}

export function assetSlotBlocker(asset: Director2Asset, target: AssetCanvasTarget): string {
  if (["scene_reverse", "scene_pano"].includes(target.type) && !assetSlotImage(asset, { type: "scene_master" })) return "先完善主视角，再创作其他机位"
  if (["prop_turnaround", "prop_detail"].includes(target.type) && !assetSlotImage(asset, { type: "prop_reference" })) return "先完善道具参考图，再创作三视图或细节"
  if (target.type === "identity" && !assetSlotPrompt(asset, target).trim() && !sourceReferencesOf(asset).length) return "先描述角色造型，或添加人物参考图"
  return ""
}

export function assetDefinitionText(asset: Director2Asset): string {
  return String(asset.extra?.canvas_definition || asset.description || asset.extra?.description || asset.visual_prompt || "")
}

export function readAssetCanvasLayout(asset: Director2Asset): AssetCanvasLayout {
  const raw = asset.extra?.creation_canvas
  const positions: Record<string, XYPosition> = {}
  if (raw && raw.version === 1 && raw.positions && typeof raw.positions === "object") {
    for (const [key, value] of Object.entries(raw.positions)) {
      const point = value as XYPosition | null
      if (point && Number.isFinite(point.x) && Number.isFinite(point.y) && Math.abs(point.x) <= 100_000 && Math.abs(point.y) <= 100_000) positions[key] = { x: point.x, y: point.y }
    }
  }
  const links: AssetCanvasLink[] = Array.isArray(raw?.links) ? raw.links.filter((link: AssetCanvasLink) => link && typeof link.sourceAssetId === "string" && typeof link.sourceKey === "string" && typeof link.url === "string" && /^https?:\/\//.test(link.url)).slice(0, MAX_SOURCE_REFERENCES) : []
  return { version: 1, positions, links }
}

export function appendCanvasReference(asset: Director2Asset, url: string, name: string) {
  const refs = sourceReferencesOf(asset)
  if (!/^https?:\/\//i.test(url)) throw new Error("参考图地址无效")
  if (refs.some(ref => ref.url === url)) return refs
  if (refs.length >= MAX_SOURCE_REFERENCES) throw new Error(`最多添加 ${MAX_SOURCE_REFERENCES} 张参考图`)
  return [...refs, { id: `link-${crypto.randomUUID()}`, url, filename: name }]
}

export function buildAssetCanvas(assets: Director2Asset[]): { nodes: AssetCanvasNode[]; edges: Edge[] } {
  const nodes: AssetCanvasNode[] = [], edges: Edge[] = []
  const groups = ["character", "scene", "prop"]
  groups.forEach((kind, row) => {
    let cursor = 60
    assets.filter(asset => asset.kind === kind).sort((a, b) => (a.created_at || "").localeCompare(b.created_at || "") || a.id.localeCompare(b.id)).forEach(asset => {
      const layout = readAssetCanvasLayout(asset), slots = assetImageSlots(asset)
      const groupId = assetNodeId(asset.id, "group"), width = 490 + Math.max(1, slots.length) * 430
      nodes.push({ id: groupId, type: "assetGroup", position: layout.positions.group || { x: cursor, y: row * 850 + 50 }, style: { width, height: 710 }, data: { asset, key: "group", role: "group", title: asset.name } })
      const add = (key: string, role: AssetCanvasData["role"], title: string, position: XYPosition, size: { width: number; height: number }, target?: AssetCanvasTarget) => {
        nodes.push({ id: assetNodeId(asset.id, key), parentId: groupId, type: "assetCreation", position: layout.positions[key] || position, style: size, data: { asset, key, role, title, target, image: target ? assetSlotImage(asset, target) : undefined } })
      }
      add("definition", "definition", kind === "character" ? "角色档案" : kind === "scene" ? "场景设定" : "道具设定", { x: 30, y: 45 }, { width: 300, height: 310 })
      add("references", "references", kind === "character" ? "人物参考图" : kind === "scene" ? "场景参考图" : "道具参考图", { x: 30, y: 405 }, { width: 300, height: 320 })
      slots.forEach(({ target, title }, index) => {
        const key = targetKey(target)
        add(key, "image", title, { x: 430 + index * 430, y: 100 }, { width: 392, height: kind === "character" ? 524 : 460 }, target)
        const primary = kind === "scene" ? "scene_master" : kind === "prop" ? "prop_reference" : null
        const inputs = primary && target.type !== primary ? [primary] : ["definition", "references"]
        for (const input of inputs) edges.push({ id: `${asset.id}:${input}>${key}`, source: assetNodeId(asset.id, input), target: assetNodeId(asset.id, key), type: "default", selectable: false, deletable: false, style: { stroke: "var(--studio-border-strong, var(--studio-text-muted))", strokeWidth: 1 } })
      })
      cursor += width + 160
    })
  })
  for (const asset of assets) {
    for (const link of readAssetCanvasLayout(asset).links) {
      const source = assetNodeId(link.sourceAssetId, link.sourceKey)
      if (!nodes.some(node => node.id === source) || !sourceReferencesOf(asset).some(ref => ref.url === link.url)) continue
      edges.push({ id: `ref:${asset.id}:${source}`, source, target: assetNodeId(asset.id, "references"), label: "参考图快照", selectable: false, deletable: false, style: { stroke: "var(--studio-text-muted)", strokeWidth: 1, strokeDasharray: "4 4" }, labelStyle: { fill: "var(--studio-text-muted)", fontSize: 10 }, labelBgStyle: { fill: "var(--studio-surface)" } })
    }
  }
  return { nodes, edges }
}
