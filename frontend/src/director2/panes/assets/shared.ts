// 资产库面板公共类型与工具 —— 逐行复刻自 dev0914 z-admin/src/views/project/AssetsLibraryPane.vue <script setup> 中的纯函数部分
import { message } from "antd"
import { MapPin, Package, Users } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { Director2Asset } from "../../api"

// 造型身份（原版 identities 数组元素为 JS 对象，这里按取值字段补全类型）
export type AssetIdentity = {
  id?: string
  name?: string
  description?: string
  appearance_details?: string
  visual_prompt?: string
  image_url?: string
} & Record<string, any>

// generateAssetImage 响应中用到的字段（原版为 JS 未标注）
export type GenerateImageResult = {
  image_url?: string
  asset?: Director2Asset
} & Record<string, any>

// 仅保留 角色、场景、道具
export const ASSET_TABS = [
  { key: "character", label: "角色" },
  { key: "scene", label: "场景" },
  { key: "prop", label: "道具" },
]

export function kindLabel(k: string): string {
  const map: Record<string, string> = { character: "角色", scene: "场景", prop: "道具" }
  return map[k] || k || "资产"
}

export function getKindColor(k: string): string {
  const map: Record<string, string> = { character: "purple", scene: "blue", prop: "orange" }
  return map[k] || "default"
}

export function getKindIcon(k: string): LucideIcon {
  if (k === "character") return Users
  if (k === "scene") return MapPin
  return Package
}

export function getKindMetaBadge(ast: Director2Asset): string {
  if (ast.kind === "character") return "角色"
  if (ast.kind === "scene") {
    return ast.extra?.scene_type === "interior" ? "内景" : "实景"
  }
  return getPropTypeLabel(ast.extra?.prop_type)
}

export function getPropTypeLabel(pt?: string | null): string {
  const map: Record<string, string> = {
    weapon: "武器",
    accessory: "饰品",
    artifact: "神器/法器",
    document: "文书",
    furniture: "家具",
    object: "其他物件",
    key_prop: "核心信物",
    stationery: "文房器具",
    daily: "日常随身",
    decor: "场景固定",
  }
  if (!pt) return "物件"
  return map[pt] || pt
}

export function getSubRoleDisplay(ast: Director2Asset): string {
  if (ast.role) return ast.role
  if (ast.kind === "character") return "主要角色"
  if (ast.kind === "scene") return "拍摄场景"
  return ast.extra?.owner || "随行道具"
}

export function getAssetDisplayAvatar(ast: Director2Asset): string {
  if (!ast) return ""
  if (ast.kind === "character" && ast.extra?.avatar_url) {
    return ast.extra.avatar_url
  }
  if (ast.kind === "scene" && (ast.extra?.master_url || ast.image_url)) {
    return ast.extra?.master_url || ast.image_url
  }
  if (ast.kind === "prop") {
    return ast.extra?.reference_url || ast.extra?.turnaround_url || ast.extra?.detail_url || ast.image_url || ""
  }
  return ast.image_url || ""
}

export function getAssetGradient(name: string): { background: string } {
  const gradients = [
    "linear-gradient(135deg, #6366f1 0%, #a855f7 100%)",
    "linear-gradient(135deg, #0ea5e9 0%, #22c55e 100%)",
    "linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)",
    "linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)",
    "linear-gradient(135deg, #7047f6 0%, #10b981 100%)",
  ]
  let hash = 0
  for (let i = 0; i < (name || "").length; i++) {
    hash = (hash << 5) - hash + name.charCodeAt(i)
    hash |= 0
  }
  return { background: gradients[Math.abs(hash) % gradients.length] }
}

export function copyText(text: string | null | undefined) {
  const p = (text || "").trim()
  if (!p) {
    message.warning("内容为空")
    return
  }
  navigator.clipboard.writeText(p).then(() => {
    message.success("已复制到剪贴板")
  }).catch(() => {
    message.info("请手动复制")
  })
}

// 点击放大查看图片（原版第二个参数 title 未使用，保留入参形状）
export function openImageLightbox(url: string | null | undefined, _title?: string) {
  if (!url) return
  window.open(url, "_blank")
}

// 场景类型选项（场景工作区与编辑场景弹窗共用）
export const SCENE_TYPE_OPTIONS = [
  { value: "interior", label: "室内内景 (Interior)" },
  { value: "exterior", label: "室外实景 (Exterior)" },
  { value: "pano", label: "宏观航拍/远景 (Panoramic)" },
]

// 道具类型选项（道具工作区与编辑道具弹窗共用）
export const PROP_TYPE_OPTIONS = [
  { value: "weapon", label: "武器 (Weapon)" },
  { value: "accessory", label: "饰品 (Accessory)" },
  { value: "artifact", label: "神器/法器 (Artifact)" },
  { value: "document", label: "文书 (Document)" },
  { value: "furniture", label: "家具 (Furniture)" },
  { value: "object", label: "其他物件 (Object)" },
]
