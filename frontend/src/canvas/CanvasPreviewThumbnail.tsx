import { useId } from "react"
import type { CanvasPreview, CanvasPreviewItem } from "./canvas-model"

type PreparedItem = {
  item: CanvasPreviewItem
  index: number
}

function previewPadding(preview: CanvasPreview): number {
  const shortest = Math.min(preview.width || 0, preview.height || 0)
  return Math.max(16, Math.min(shortest * 0.06, 72))
}

function nodeRadius(item: CanvasPreviewItem): number {
  return Math.min(14, Math.max(2, Math.min(item.width, item.height) * 0.05))
}

function renderNodeDetails(item: CanvasPreviewItem) {
  if (item.type === "text") {
    const lineHeight = Math.max(2, Math.min(item.height * 0.08, 8))
    const gap = lineHeight * 2.1
    const startY = item.y + item.height * 0.3
    return [0.66, 0.48, 0.34].map((ratio, index) => (
      <rect
        key={`line-${index}`}
        className="canvas-preview-line"
        x={item.x + item.width * 0.12}
        y={startY + gap * index}
        width={item.width * 0.7 * ratio}
        height={lineHeight}
        rx={lineHeight / 2}
      />
    ))
  }
  if (item.type === "video") {
    const size = Math.min(item.width, item.height) * 0.2
    const centerX = item.x + item.width / 2
    const centerY = item.y + item.height / 2
    return (
      <path
        className="canvas-preview-play"
        d={`M ${centerX - size * 0.35} ${centerY - size * 0.55} L ${centerX + size * 0.6} ${centerY} L ${centerX - size * 0.35} ${centerY + size * 0.55} Z`}
      />
    )
  }
  return null
}

export default function CanvasPreviewThumbnail({ preview }: { preview: CanvasPreview }) {
  const rawId = useId()
  const clipPrefix = `canvas-preview-clip-${rawId.replace(/[^a-zA-Z0-9_-]/g, "")}`
  const padding = previewPadding(preview)
  const viewBox = [
    preview.x - padding,
    preview.y - padding,
    Math.max(1, preview.width + padding * 2),
    Math.max(1, preview.height + padding * 2),
  ].join(" ")
  const prepared: PreparedItem[] = preview.items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => Number(right.item.type === "artboard") - Number(left.item.type === "artboard"))
  const imageHref = (item: CanvasPreviewItem) => item.type === "video" ? item.cover : item.url
  const clipIds = new Map<number, string>()
  for (const { item, index } of prepared) {
    if (imageHref(item)) clipIds.set(index, `${clipPrefix}-${index}`)
  }

  return (
    <svg
      className="canvas-preview-svg"
      viewBox={viewBox}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        {prepared.map(({ item, index }) => {
          const clipId = clipIds.get(index)
          if (!clipId) return null
          return (
            <clipPath key={clipId} id={clipId}>
              <rect
                x={item.x}
                y={item.y}
                width={item.width}
                height={item.height}
                rx={nodeRadius(item)}
              />
            </clipPath>
          )
        })}
      </defs>

      {preview.links.map(([sourceIndex, targetIndex], index) => {
        const source = preview.items[sourceIndex]
        const target = preview.items[targetIndex]
        if (!source || !target) return null
        const sourceX = source.x + source.width
        const sourceY = source.y + source.height / 2
        const targetX = target.x
        const targetY = target.y + target.height / 2
        const curve = Math.max(24, Math.min(160, Math.abs(targetX - sourceX) * 0.45))
        return (
          <path
            key={`link-${index}`}
            className="canvas-preview-link"
            d={`M ${sourceX} ${sourceY} C ${sourceX + curve} ${sourceY}, ${targetX - curve} ${targetY}, ${targetX} ${targetY}`}
            vectorEffect="non-scaling-stroke"
          />
        )
      })}

      {prepared.map(({ item, index }) => (
        <g key={`node-${index}`}>
          <rect
            className={`canvas-preview-node is-${item.type}`}
            x={item.x}
            y={item.y}
            width={item.width}
            height={item.height}
            rx={nodeRadius(item)}
            vectorEffect="non-scaling-stroke"
          />
          {imageHref(item) ? (
            <image
              className="canvas-preview-image"
              href={imageHref(item)}
              x={item.x}
              y={item.y}
              width={item.width}
              height={item.height}
              preserveAspectRatio="xMidYMid slice"
              clipPath={`url(#${clipIds.get(index)})`}
            />
          ) : null}
          {renderNodeDetails(item)}
        </g>
      ))}
    </svg>
  )
}
