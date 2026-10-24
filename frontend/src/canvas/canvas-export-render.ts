import {
  canvasExportPalette,
  type CanvasExportNode,
  type CanvasExportPalette,
  type CanvasExportScene,
} from "./canvas-export"

const FONT_STACK = '"Segoe UI", "Microsoft YaHei", "PingFang SC", ui-sans-serif, sans-serif'
const IMAGE_LOAD_TIMEOUT = 10_000

function font(weight: number, size: number): string {
  return `${weight} ${size}px ${FONT_STACK}`
}

function withAlpha(hex: string, alpha: number): string {
  const clean = hex.replace("#", "")
  const value = Number.parseInt(clean.length === 3
    ? clean.split("").map((char) => char + char).join("")
    : clean.slice(0, 6), 16)
  if (!Number.isFinite(value)) return hex
  const red = (value >> 16) & 255
  const green = (value >> 8) & 255
  const blue = value & 255
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`
}

function nodeAccent(node: CanvasExportNode, palette: CanvasExportPalette): string {
  if (node.type === "text") return palette.textTone
  if (node.type === "image") return palette.imageTone
  if (node.type === "video") return palette.videoTone
  if (node.type === "generator") return palette.generatorTone
  if (node.type === "artboard") return palette.border
  return palette.unknownTone
}

function roundedRectPath(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const safeWidth = Math.max(0, width)
  const safeHeight = Math.max(0, height)
  const r = Math.min(radius, safeWidth / 2, safeHeight / 2)
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + safeWidth - r, y)
  ctx.quadraticCurveTo(x + safeWidth, y, x + safeWidth, y + r)
  ctx.lineTo(x + safeWidth, y + safeHeight - r)
  ctx.quadraticCurveTo(x + safeWidth, y + safeHeight, x + safeWidth - r, y + safeHeight)
  ctx.lineTo(x + r, y + safeHeight)
  ctx.quadraticCurveTo(x, y + safeHeight, x, y + safeHeight - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

function fillRoundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
  color: string,
) {
  ctx.fillStyle = color
  roundedRectPath(ctx, x, y, width, height, radius)
  ctx.fill()
}

function strokeRoundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
  color: string,
  lineWidth = 1,
) {
  ctx.strokeStyle = color
  ctx.lineWidth = lineWidth
  roundedRectPath(ctx, x, y, width, height, radius)
  ctx.stroke()
}

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const source = text.slice(0, 4000)
  const lines: string[] = []
  for (const paragraph of source.split(/\r?\n/)) {
    if (!paragraph.trim()) {
      if (lines.length) lines.push("")
      continue
    }
    let current = ""
    for (const char of Array.from(paragraph)) {
      const next = current + char
      if (current && ctx.measureText(next).width > maxWidth) {
        lines.push(current)
        current = char
      } else {
        current = next
      }
    }
    if (current) lines.push(current)
  }
  return lines
}

function drawWrappedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  maxLines: number,
  lineHeight: number,
  color: string,
  fontStyle: string,
): number {
  if (maxLines < 1) return 0
  ctx.font = fontStyle
  ctx.fillStyle = color
  ctx.textBaseline = "top"
  const lines = wrapText(ctx, text, maxWidth)
  const clipped = lines.slice(0, maxLines)
  if (lines.length > maxLines && clipped.length) {
    let last = clipped[clipped.length - 1]
    while (last.length > 1 && ctx.measureText(`${last}…`).width > maxWidth) {
      last = last.slice(0, -1)
    }
    clipped[clipped.length - 1] = `${last}…`
  }
  clipped.forEach((line, index) => ctx.fillText(line, x, y + index * lineHeight))
  return clipped.length
}

function fitSingleLine(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, fontStyle: string): string {
  ctx.font = fontStyle
  if (ctx.measureText(text).width <= maxWidth) return text
  let value = text
  while (value.length > 1 && ctx.measureText(`${value}…`).width > maxWidth) {
    value = value.slice(0, -1)
  }
  return `${value}…`
}

function drawCoverImage(
  ctx: CanvasRenderingContext2D,
  image: HTMLImageElement,
  x: number,
  y: number,
  width: number,
  height: number,
) {
  const sourceWidth = image.naturalWidth
  const sourceHeight = image.naturalHeight
  if (!sourceWidth || !sourceHeight || width <= 0 || height <= 0) return
  const scale = Math.max(width / sourceWidth, height / sourceHeight)
  const sampleWidth = width / scale
  const sampleHeight = height / scale
  ctx.drawImage(
    image,
    (sourceWidth - sampleWidth) / 2,
    (sourceHeight - sampleHeight) / 2,
    sampleWidth,
    sampleHeight,
    x,
    y,
    width,
    height,
  )
}

function drawPlayMarker(ctx: CanvasRenderingContext2D, x: number, y: number, size: number, palette: CanvasExportPalette) {
  const radius = Math.max(14, Math.min(50, size * 0.16))
  ctx.fillStyle = "rgba(9, 12, 18, 0.55)"
  ctx.beginPath()
  ctx.arc(x, y, radius, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = palette.text
  ctx.beginPath()
  ctx.moveTo(x - radius * 0.28, y - radius * 0.42)
  ctx.lineTo(x + radius * 0.5, y)
  ctx.lineTo(x - radius * 0.28, y + radius * 0.42)
  ctx.closePath()
  ctx.fill()
}

function drawHeader(
  ctx: CanvasRenderingContext2D,
  node: CanvasExportNode,
  headerHeight: number,
  palette: CanvasExportPalette,
) {
  const accent = nodeAccent(node, palette)
  ctx.fillStyle = accent
  ctx.beginPath()
  ctx.arc(node.x + 15, node.y + headerHeight / 2, 3.5, 0, Math.PI * 2)
  ctx.fill()
  const label = fitSingleLine(ctx, node.label, Math.max(20, node.width - 54), font(600, 12))
  ctx.font = font(600, 12)
  ctx.fillStyle = palette.text
  ctx.textBaseline = "middle"
  ctx.fillText(label, node.x + 25, node.y + headerHeight / 2 + 0.5)
  ctx.textBaseline = "top"
}

function drawImageCard(
  ctx: CanvasRenderingContext2D,
  node: CanvasExportNode,
  image: HTMLImageElement | undefined,
  headerHeight: number,
  radius: number,
  palette: CanvasExportPalette,
) {
  const contentY = node.y + headerHeight
  const contentHeight = node.height - headerHeight
  ctx.save()
  roundedRectPath(ctx, node.x, node.y, node.width, node.height, radius)
  ctx.clip()
  ctx.fillStyle = palette.surface
  ctx.fillRect(node.x, node.y, node.width, node.height)
  if (image) {
    drawCoverImage(ctx, image, node.x, contentY, node.width, contentHeight)
  } else {
    ctx.fillStyle = node.type === "video" ? palette.videoSurface : palette.raised
    ctx.fillRect(node.x, contentY, node.width, contentHeight)
    ctx.font = font(500, 12)
    ctx.fillStyle = node.type === "video" ? "rgba(255, 255, 255, 0.72)" : palette.muted
    ctx.textAlign = "center"
    ctx.textBaseline = "middle"
    const message = node.type === "video" ? "视频素材" : node.imageCandidates.length ? "素材无法加载" : "图片占位"
    ctx.fillText(message, node.x + node.width / 2, contentY + contentHeight / 2 + 8)
    ctx.textAlign = "left"
    ctx.textBaseline = "top"
  }
  if (node.type === "video") {
    drawPlayMarker(ctx, node.x + node.width / 2, contentY + contentHeight / 2, Math.min(node.width, contentHeight), palette)
  }
  if (node.caption) {
    const barHeight = Math.min(46, Math.max(28, contentHeight * 0.2))
    const gradient = ctx.createLinearGradient(0, node.y + node.height - barHeight, 0, node.y + node.height)
    gradient.addColorStop(0, "rgba(9, 12, 18, 0)")
    gradient.addColorStop(1, "rgba(9, 12, 18, 0.72)")
    ctx.fillStyle = gradient
    ctx.fillRect(node.x, node.y + node.height - barHeight, node.width, barHeight)
    drawWrappedText(
      ctx,
      node.caption,
      node.x + 14,
      node.y + node.height - barHeight + 9,
      node.width - 28,
      1,
      16,
      "rgba(255, 255, 255, 0.92)",
      font(400, 11),
    )
  }
  ctx.restore()
  drawHeader(ctx, node, headerHeight, palette)
  strokeRoundedRect(ctx, node.x, node.y, node.width, node.height, radius, withAlpha(nodeAccent(node, palette), 0.3))
}

function drawStatusPill(
  ctx: CanvasRenderingContext2D,
  text: string,
  right: number,
  centerY: number,
  palette: CanvasExportPalette,
) {
  ctx.font = font(600, 10)
  const label = fitSingleLine(ctx, text, 96, font(600, 10))
  const width = Math.min(96, ctx.measureText(label).width + 16)
  const x = right - width
  fillRoundedRect(ctx, x, centerY - 9, width, 18, 9, palette.raised)
  ctx.fillStyle = palette.muted
  ctx.textAlign = "center"
  ctx.textBaseline = "middle"
  ctx.fillText(label, x + width / 2, centerY + 0.5)
  ctx.textAlign = "left"
  ctx.textBaseline = "top"
}

function drawGeneratorCard(
  ctx: CanvasRenderingContext2D,
  node: CanvasExportNode,
  image: HTMLImageElement | undefined,
  headerHeight: number,
  radius: number,
  palette: CanvasExportPalette,
) {
  const padding = 13
  const innerWidth = node.width - padding * 2
  ctx.save()
  roundedRectPath(ctx, node.x, node.y, node.width, node.height, radius)
  ctx.clip()
  ctx.fillStyle = palette.surface
  ctx.fillRect(node.x, node.y, node.width, node.height)
  const headerBottom = node.y + headerHeight
  let cursor = headerBottom + 10
  if (image && node.mediaKind === "image") {
    const resultHeight = Math.min(node.height * 0.46, Math.max(60, node.height - headerHeight - 96))
    const resultWidth = innerWidth
    ctx.save()
    roundedRectPath(ctx, node.x + padding, cursor, resultWidth, resultHeight, 8)
    ctx.clip()
    drawCoverImage(ctx, image, node.x + padding, cursor, resultWidth, resultHeight)
    ctx.restore()
    strokeRoundedRect(ctx, node.x + padding, cursor, resultWidth, resultHeight, 8, palette.border)
    cursor += resultHeight + 10
  } else if (node.mediaKind === "video") {
    const resultHeight = Math.min(node.height * 0.4, Math.max(56, node.height - headerHeight - 96))
    fillRoundedRect(ctx, node.x + padding, cursor, innerWidth, resultHeight, 8, palette.videoSurface)
    drawPlayMarker(ctx, node.x + padding + innerWidth / 2, cursor + resultHeight / 2, Math.min(innerWidth, resultHeight), palette)
    cursor += resultHeight + 10
  }
  ctx.font = font(600, 10)
  ctx.fillStyle = palette.muted
  ctx.fillText("提示词", node.x + padding, cursor)
  cursor += 16
  const availableLines = Math.max(1, Math.floor((node.y + node.height - 12 - cursor) / 18))
  if (node.prompt) {
    drawWrappedText(
      ctx,
      node.prompt,
      node.x + padding,
      cursor,
      innerWidth,
      Math.min(6, availableLines),
      18,
      palette.text,
      font(400, 12.5),
    )
  } else {
    drawWrappedText(
      ctx,
      "尚未填写提示词",
      node.x + padding,
      cursor,
      innerWidth,
      Math.min(2, availableLines),
      18,
      palette.muted,
      font(400, 12),
    )
  }
  ctx.restore()
  drawHeader(ctx, node, headerHeight, palette)
  if (node.status) {
    drawStatusPill(ctx, node.status, node.x + node.width - 12, node.y + headerHeight / 2, palette)
  }
  strokeRoundedRect(ctx, node.x, node.y, node.width, node.height, radius, withAlpha(nodeAccent(node, palette), 0.3))
}

function drawTextCard(
  ctx: CanvasRenderingContext2D,
  node: CanvasExportNode,
  headerHeight: number,
  radius: number,
  palette: CanvasExportPalette,
) {
  ctx.save()
  roundedRectPath(ctx, node.x, node.y, node.width, node.height, radius)
  ctx.clip()
  ctx.fillStyle = withAlpha(palette.textTone, 0.03)
  ctx.fillRect(node.x, node.y, node.width, node.height)
  const lineHeight = 20
  const availableLines = Math.max(1, Math.floor((node.height - headerHeight - 18) / lineHeight))
  if (node.text) {
    drawWrappedText(
      ctx,
      node.text,
      node.x + 15,
      node.y + headerHeight + 4,
      node.width - 30,
      Math.min(8, availableLines),
      lineHeight,
      palette.text,
      font(400, 14),
    )
  } else {
    ctx.font = font(400, 12)
    ctx.fillStyle = palette.muted
    ctx.fillText("空文字节点", node.x + 15, node.y + headerHeight + 6)
  }
  ctx.restore()
  drawHeader(ctx, node, headerHeight, palette)
  strokeRoundedRect(ctx, node.x, node.y, node.width, node.height, radius, withAlpha(palette.textTone, 0.3))
}

function drawArtboard(
  ctx: CanvasRenderingContext2D,
  node: CanvasExportNode,
  radius: number,
  palette: CanvasExportPalette,
) {
  ctx.save()
  ctx.globalAlpha = 0.72
  fillRoundedRect(ctx, node.x, node.y, node.width, node.height, radius, palette.surface)
  ctx.globalAlpha = 1
  strokeRoundedRect(ctx, node.x, node.y, node.width, node.height, radius, palette.border)
  ctx.font = font(600, 13)
  ctx.fillStyle = palette.secondary
  ctx.textBaseline = "top"
  const label = fitSingleLine(ctx, node.label, Math.max(24, node.width - 32), font(600, 13))
  ctx.fillText(label, node.x + 16, node.y + 14)
  if (node.caption) {
    drawWrappedText(
      ctx,
      node.caption,
      node.x + 16,
      node.y + 36,
      Math.max(24, node.width - 32),
      2,
      18,
      palette.muted,
      font(400, 12),
    )
  }
  ctx.restore()
}

function drawUnknownCard(
  ctx: CanvasRenderingContext2D,
  node: CanvasExportNode,
  headerHeight: number,
  radius: number,
  palette: CanvasExportPalette,
) {
  ctx.save()
  roundedRectPath(ctx, node.x, node.y, node.width, node.height, radius)
  ctx.clip()
  ctx.fillStyle = palette.surface
  ctx.fillRect(node.x, node.y, node.width, node.height)
  drawHeader(ctx, node, headerHeight, palette)
  const detail = node.originalType ? `原始类型：${node.originalType}` : "该节点类型尚未识别"
  drawWrappedText(
    ctx,
    `${detail}\n内容已保留，升级工作台后可编辑`,
    node.x + 15,
    node.y + headerHeight + 4,
    Math.max(24, node.width - 30),
    3,
    17,
    palette.muted,
    font(400, 11.5),
  )
  ctx.restore()
  ctx.save()
  ctx.setLineDash([7, 5])
  strokeRoundedRect(ctx, node.x, node.y, node.width, node.height, radius, withAlpha(palette.unknownTone, 0.5))
  ctx.restore()
}

function drawNode(
  ctx: CanvasRenderingContext2D,
  node: CanvasExportNode,
  image: HTMLImageElement | undefined,
  palette: CanvasExportPalette,
) {
  const radius = Math.min(14, Math.max(4, Math.min(node.width, node.height) * 0.05))
  const headerHeight = Math.min(36, Math.max(26, node.height * 0.14))
  if (node.type === "artboard") {
    drawArtboard(ctx, node, radius, palette)
    return
  }
  if (node.type === "generator") {
    drawGeneratorCard(ctx, node, image, headerHeight, radius, palette)
    return
  }
  if (node.type === "text") {
    drawTextCard(ctx, node, headerHeight, radius, palette)
    return
  }
  if (node.type === "image" || node.type === "video") {
    drawImageCard(ctx, node, image, headerHeight, radius, palette)
    return
  }
  drawUnknownCard(ctx, node, headerHeight, radius, palette)
}

function drawLink(
  ctx: CanvasRenderingContext2D,
  source: CanvasExportNode,
  target: CanvasExportNode,
  palette: CanvasExportPalette,
) {
  const sourceX = source.x + source.width
  const sourceY = source.y + source.height / 2
  const targetX = target.x
  const targetY = target.y + target.height / 2
  const curve = Math.max(24, Math.min(160, Math.abs(targetX - sourceX) * 0.45))
  ctx.strokeStyle = palette.edge
  ctx.lineWidth = 1.6
  ctx.beginPath()
  ctx.moveTo(sourceX, sourceY)
  ctx.bezierCurveTo(sourceX + curve, sourceY, targetX - curve, targetY, targetX, targetY)
  ctx.stroke()
  const arrow = 6
  ctx.fillStyle = palette.edge
  ctx.beginPath()
  ctx.moveTo(targetX, targetY)
  ctx.lineTo(targetX - arrow, targetY - arrow * 0.55)
  ctx.lineTo(targetX - arrow, targetY + arrow * 0.55)
  ctx.closePath()
  ctx.fill()
}

export function drawCanvasExport(
  canvas: HTMLCanvasElement,
  scene: CanvasExportScene,
  images: Map<string, HTMLImageElement>,
  renderScale = scene.scale,
): { width: number; height: number } {
  const scale = Math.max(0.01, renderScale)
  const width = Math.max(1, Math.round(scene.bounds.width * scale))
  const height = Math.max(1, Math.round(scene.bounds.height * scale))
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("当前浏览器不支持 Canvas 导出")
  const palette = canvasExportPalette(scene.paletteMode)
  ctx.setTransform(scale, 0, 0, scale, -scene.bounds.x * scale, -scene.bounds.y * scale)
  ctx.lineJoin = "round"
  ctx.lineCap = "round"
  if (scene.background) {
    ctx.fillStyle = scene.background
    ctx.fillRect(scene.bounds.x, scene.bounds.y, scene.bounds.width, scene.bounds.height)
  }
  const byId = new Map(scene.nodes.map((node) => [node.id, node]))
  for (const node of scene.nodes) {
    if (node.type === "artboard") drawNode(ctx, node, images.get(node.id), palette)
  }
  for (const link of scene.links) {
    const source = byId.get(link.source)
    const target = byId.get(link.target)
    if (source && target) drawLink(ctx, source, target, palette)
  }
  for (const node of scene.nodes) {
    if (node.type !== "artboard") drawNode(ctx, node, images.get(node.id), palette)
  }
  return { width, height }
}

function loadImage(url: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const image = new Image()
    let settled = false
    const finish = (value: HTMLImageElement | null) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      image.onload = null
      image.onerror = null
      resolve(value)
    }
    const timer = window.setTimeout(() => finish(null), IMAGE_LOAD_TIMEOUT)
    // crossOrigin 只影响跨域素材：拿不到 CORS 头就回退占位，避免画布被污染后无法导出。
    if (!url.startsWith("data:")) image.crossOrigin = "anonymous"
    image.decoding = "async"
    image.onload = () => finish(image.naturalWidth > 0 ? image : null)
    image.onerror = () => finish(null)
    image.src = url
  })
}

export async function loadCanvasExportImages(scene: CanvasExportScene): Promise<Map<string, HTMLImageElement>> {
  const entries = await Promise.all(scene.nodes.map(async (node) => {
    for (const url of node.imageCandidates) {
      const image = await loadImage(url)
      if (image) return [node.id, image] as const
    }
    return null
  }))
  return new Map(entries.filter((entry): entry is readonly [string, HTMLImageElement] => entry !== null))
}
