import type { CanvasPreview, CanvasPreviewItem, CanvasProject } from "./canvas-model"

function timestamp(value?: string | null): number {
  const parsed = value ? Date.parse(value) : NaN
  return Number.isFinite(parsed) ? parsed : 0
}

/** A favorite must not displace the most recently saved project in the feature. */
export function recentCanvasProject(projects: CanvasProject[]): CanvasProject | null {
  let recent: CanvasProject | null = null
  let newest = -1
  for (const project of projects) {
    if (project.deleted_at) continue
    const saved = timestamp(project.draft_updated_at) || timestamp(project.updated_at) || timestamp(project.created_at)
    if (saved > newest) {
      recent = project
      newest = saved
    }
  }
  return recent
}

export function canvasSavedTime(value?: string | null, now = Date.now()): string {
  const saved = timestamp(value)
  if (!saved) return "尚未保存"
  const elapsed = Math.max(0, now - saved)
  if (elapsed < 60_000) return "刚刚"
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`
  if (elapsed < 172_800_000) return "昨天"
  if (elapsed < 604_800_000) return `${Math.floor(elapsed / 86_400_000)} 天前`
  return new Date(saved).toLocaleDateString("zh-CN", { year: "numeric", month: "numeric", day: "numeric" })
}

export type CanvasPreviewLayoutItem = CanvasPreviewItem & { sourceIndex: number }
export type CanvasPreviewLayout = {
  items: CanvasPreviewLayoutItem[]
  links: [number, number][]
  cropped: boolean
}

/** Keep a real connected neighborhood legible; never invent/rearrange canvas nodes. */
export function layoutCanvasPreview(preview: CanvasPreview, width: number, height: number): CanvasPreviewLayout {
  const content = preview.items.map((item, sourceIndex) => ({ ...item, sourceIndex }))
  const ordinary = content.filter((item) => item.type !== "artboard")
  const limit = width > 400 ? 10 : 7
  let selected = content
  if (ordinary.length > limit) {
    const anchor = ordinary.find((item) => item.url || item.cover) ?? ordinary[0]
    const chosen = new Set([anchor.sourceIndex])
    const queue = [anchor.sourceIndex]
    const candidates = new Set(ordinary.map((item) => item.sourceIndex))
    const adjacency = new Map<number, number[]>()
    for (const [left, right] of preview.links) {
      if (!candidates.has(left) || !candidates.has(right)) continue
      adjacency.set(left, [...(adjacency.get(left) ?? []), right])
      adjacency.set(right, [...(adjacency.get(right) ?? []), left])
    }
    while (queue.length && chosen.size < limit) {
      for (const neighbor of adjacency.get(queue.shift()!) ?? []) {
        if (chosen.has(neighbor)) continue
        chosen.add(neighbor)
        queue.push(neighbor)
        if (chosen.size === limit) break
      }
    }
    // Fill a sparse connected component with the closest real neighboring nodes.
    const distance = (item: CanvasPreviewLayoutItem) => Math.hypot(item.x - anchor.x, item.y - anchor.y)
    for (const item of [...ordinary].sort((left, right) => distance(left) - distance(right))) {
      if (chosen.size >= limit) break
      chosen.add(item.sourceIndex)
    }
    selected = ordinary.filter((item) => chosen.has(item.sourceIndex))
  }
  if (!selected.length) return { items: [], links: [], cropped: false }
  const x = Math.min(...selected.map((item) => item.x))
  const y = Math.min(...selected.map((item) => item.y))
  const right = Math.max(...selected.map((item) => item.x + item.width))
  const bottom = Math.max(...selected.map((item) => item.y + item.height))
  const padding = width > 400 ? 28 : 18
  const scale = Math.min((width - padding * 2) / Math.max(1, right - x), (height - padding * 2) / Math.max(1, bottom - y))
  const offsetX = (width - (right - x) * scale) / 2
  const offsetY = (height - (bottom - y) * scale) / 2
  const indexes = new Map(selected.map((item, index) => [item.sourceIndex, index]))
  const links: [number, number][] = []
  for (const [left, rightIndex] of preview.links) {
    const source = indexes.get(left)
    const target = indexes.get(rightIndex)
    if (source !== undefined && target !== undefined && source !== target) links.push([source, target])
  }
  return {
    items: selected.map((item) => ({
      ...item,
      x: offsetX + (item.x - x) * scale,
      y: offsetY + (item.y - y) * scale,
      width: item.width * scale,
      height: item.height * scale,
    })),
    links,
    cropped: selected.length < preview.items.length || preview.nodeCount > preview.items.length,
  }
}

/** Approximate glyph widths for tiny SVG text without DOM measurement or HTML. */
export function canvasPreviewLines(text: string, width: number, fontSize: number, maxLines: number): string[] {
  if (maxLines < 1 || width < fontSize) return []
  const capacity = width / fontSize
  const lines: string[] = []
  let line = ""
  let used = 0
  const glyphs = Array.from(text.trim())
  for (let index = 0; index < glyphs.length; index += 1) {
    const glyph = glyphs[index]
    const advance = /[\u0020-\u007e]/.test(glyph) ? 0.56 : 1
    if (used + advance > capacity && line) {
      if (lines.length === maxLines - 1) {
        lines.push(`${Array.from(line).slice(0, -1).join("")}…`)
        return lines
      }
      lines.push(line)
      line = ""
      used = 0
    }
    line += glyph
    used += advance
  }
  if (line) lines.push(line)
  return lines
}
