import { createContext, useContext } from "react"
import type { EditAsset } from "./model"
import { uploadMedia } from "./api"

const MEDIA_EXTENSION_BY_MIME: Record<string, string> = {
  "image/jpeg": ".jpg",
  "image/png": ".png",
  "image/webp": ".webp",
  "image/gif": ".gif",
  "video/mp4": ".mp4",
  "video/webm": ".webm",
  "video/quicktime": ".mov",
  "audio/mpeg": ".mp3",
  "audio/wav": ".wav",
  "audio/x-wav": ".wav",
  "audio/ogg": ".ogg",
  "audio/mp4": ".m4a",
  "audio/flac": ".flac",
  "audio/aac": ".m4a"
}

const EXTENSION_BY_KIND: Record<EditAsset["kind"], string> = {
  image: ".png",
  video: ".mp4",
  audio: ".mp3"
}

/**
 * 剪辑工程只接受 HTTP(S) 与本机引用地址；画布节点可能是 `/api/media/...`
 * 这类站内交付地址。加入时间线前先把媒体转入剪辑素材存储，返回可持久化的素材。
 */
export async function ensureEditableAsset(
  csrfToken: string,
  scopeProjectId: string,
  sequence: string,
  asset: EditAsset,
): Promise<EditAsset> {
  if (/^https?:\/\//i.test(asset.url) || asset.url.startsWith("/api/local-media/")) return asset
  const response = await fetch(asset.url)
  if (!response.ok) throw new Error("素材暂时无法读取，请稍后重试")
  const blob = await response.blob()
  const extension =
    MEDIA_EXTENSION_BY_MIME[blob.type] ||
    (asset.url.match(/(\.[a-z0-9]{1,8})$/i)?.[1]?.toLowerCase()) ||
    EXTENSION_BY_KIND[asset.kind]
  const base = (asset.name || "画布素材").replace(/[\\/:*?"<>|]+/g, "-").slice(0, 60)
  const file = new File([blob], `${base}${extension}`, { type: blob.type || undefined })
  const uploaded = await uploadMedia(csrfToken, scopeProjectId, sequence, file)
  return {
    ...asset,
    url: uploaded.url,
    duration: uploaded.duration > 0 ? uploaded.duration : asset.duration,
    ...(asset.kind === "image" ? { thumbnail: uploaded.url } : {})
  }
}

/**
 * 时间线编辑共享工具：迷你节点与全屏编辑器共用的会话互斥、节点上下文。
 *
 * 同一个剪辑工程（scope + sequence）同一时间只应有一个「写入者」：
 * 全屏编辑器打开时会话互斥生效，迷你节点暂停自动保存并在关闭后重载文档，
 * 避免双写 revision 冲突。
 */

export const editorSessionKey = (scopeProjectId: string, sequence: string) =>
  `${scopeProjectId}\u0000${sequence}`

type SessionListener = () => void

const sessionListeners = new Set<SessionListener>()
const sessionCounts = new Map<string, number>()

function emitSession() {
  for (const listener of sessionListeners) listener()
}

/** 全屏编辑器挂载时占用写入会话；返回释放函数。 */
export function acquireEditSession(key: string): () => void {
  sessionCounts.set(key, (sessionCounts.get(key) || 0) + 1)
  emitSession()
  let released = false
  return () => {
    if (released) return
    released = true
    const count = sessionCounts.get(key) || 0
    if (count <= 1) sessionCounts.delete(key)
    else sessionCounts.set(key, count - 1)
    emitSession()
  }
}

/** 是否有全屏编辑器正占用该工程（迷你节点据此暂停自动保存）。 */
export function isEditSessionActive(key: string): boolean {
  return (sessionCounts.get(key) || 0) > 0
}

export function subscribeEditSession(listener: SessionListener): () => void {
  sessionListeners.add(listener)
  return () => sessionListeners.delete(listener)
}

/** 迷你节点宿主提供的运行环境（无限画布 / 导演台画布各自装配）。 */
export type EditingNodeContextValue = {
  csrfToken: string
  /** 工程 scope：ai_projects 工程号或 `canvas:<画布id>`。 */
  scopeProjectId: (nodeId: string) => string
  /** 时间线节点对应的剪辑序列（导演台沿用 `canvas-<nodeId>`，无限画布用 `tl-<nodeId>`）。 */
  sequenceFor: (nodeId: string) => string
  /** 画布域可用的素材（画布媒体节点 / 导演资产），自动出现在资产列表。 */
  canvasAssets: () => EditAsset[]
  openFullscreen: (nodeId: string) => void
}

export const EditingNodeContext = createContext<EditingNodeContextValue | null>(null)

export function useEditingNodeContext(): EditingNodeContextValue | null {
  return useContext(EditingNodeContext)
}

/** 画布媒体节点 → 剪辑素材；url 与时长来自节点 data，画布不改媒体本体。 */
export function mergeEditAssetPool(
  docAssets: EditAsset[],
  canvasAssets: EditAsset[],
): EditAsset[] {
  const seen = new Set(docAssets.map((asset) => asset.url))
  const additions = canvasAssets.filter((asset) => {
    if (!asset.url || seen.has(asset.url)) return false
    seen.add(asset.url)
    return true
  })
  return additions.length ? [...docAssets, ...additions] : docAssets
}

/**
 * 派生画布域素材池：画布上的图片 / 视频 / 音频（含生成结果）自动成为时间线可用素材。
 * 时长未知时给保守默认值，素材进入时间线后被预览探针纠正。
 */
export function canvasTimelineAssets(
  nodes: Array<{ type?: string | null; data?: Record<string, unknown> }>,
): EditAsset[] {
  const assets: EditAsset[] = []
  for (const node of nodes) {
    const data = (node.data || {}) as Record<string, unknown>
    const label = String(data.label || data.title || "")
    const resultUrl = String(data.resultUrl || "")
    const url = String(data.url || data.image || "")
    const kind =
      node.type === "image" ? "image"
        : node.type === "video" ? "video"
          : node.type === "audio" ? "audio"
            : node.type === "generator" ? (String(data.resultKind || "video") === "image" ? "image" : "video")
              : ""
    if (!kind) continue
    let assetUrl = url
    let duration = 5
    let thumbnail: string | undefined
    let name = label
    if (node.type === "audio") {
      assetUrl = resultUrl || url
      duration = Math.max(1, Number(data.durationSeconds) || 30)
      name = label || "画布音频"
    } else if (node.type === "generator") {
      assetUrl = resultUrl || url
      duration = Math.max(1, Number(data.duration) || 5)
      name = label || (kind === "image" ? "生成图片" : "生成视频")
      thumbnail = kind === "image" ? assetUrl : undefined
    } else {
      duration = Math.max(1, Number(data.duration) || 5)
      name = label || (kind === "image" ? "画布图片" : "画布视频")
      thumbnail = kind === "image" ? assetUrl : undefined
    }
    if (!assetUrl || !/^https?:\/\//i.test(assetUrl) && !assetUrl.startsWith("/")) continue
    assets.push({
      id: `canvas-node-${String((node as { id?: string }).id || assets.length)}-${assets.length}`,
      name: name.slice(0, 60) || "画布素材",
      kind: kind as EditAsset["kind"],
      url: assetUrl,
      duration,
      ...(thumbnail ? { thumbnail } : {})
    })
  }
  return assets
}
