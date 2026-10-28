import { FileText, Frame, Image as ImageIcon, MoreHorizontal, Sparkles, Video } from "lucide-react"
import { useId, useMemo, useState } from "react"
import { canvasPreviewLines, layoutCanvasPreview } from "./canvas-home"
import type { CanvasPreview, CanvasPreviewItemType } from "./canvas-model"

const nodeKinds = {
  text: { title: "文本提示", Icon: FileText },
  image: { title: "图像", Icon: ImageIcon },
  video: { title: "视频", Icon: Video },
  generator: { title: "生成", Icon: Sparkles },
  artboard: { title: "画板", Icon: Frame },
  unknown: { title: "节点", Icon: Frame },
} satisfies Record<CanvasPreviewItemType, { title: string; Icon: typeof Frame }>

export default function CanvasPreviewThumbnail({ preview, nodeCount = 0, featured = false }: { preview?: CanvasPreview | null; nodeCount?: number | null; featured?: boolean }) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "")
  const [failed, setFailed] = useState<Set<string>>(() => new Set())
  const width = featured ? 670 : 360
  const height = featured ? 358 : 246
  const layout = useMemo(() => preview ? layoutCanvasPreview(preview, width, height) : null, [preview, width, height])

  if (!layout?.items.length) {
    return (
      <span className="canvas-home-preview-empty" aria-hidden="true">
        <Frame size={28} strokeWidth={1.3} />
        <span>{preview?.nodeCount || nodeCount ? "打开画布查看内容" : "灵感，从这里开始"}</span>
      </span>
    )
  }

  return (
    <span className={`canvas-home-thumbnail${featured ? " is-featured" : ""}`} aria-hidden="true">
      <svg className="canvas-home-preview-svg" viewBox={`0 0 ${width} ${height}`} focusable="false">
        <defs>
          {layout.items.map((item, index) => (
            <clipPath key={index} id={`${id}-node-${index}`}>
              <rect x={item.x} y={item.y} width={item.width} height={item.height} rx={featured ? 7 : 5} />
            </clipPath>
          ))}
        </defs>
        {layout.links.map(([left, right], index) => {
          const source = layout.items[left]
          const target = layout.items[right]
          const x1 = source.x + source.width
          const y1 = source.y + source.height / 2
          const x2 = target.x
          const y2 = target.y + target.height / 2
          const curve = Math.max(18, Math.min(80, Math.abs(x2 - x1) * 0.45))
          return <path key={index} className="canvas-home-preview-link" d={`M${x1},${y1} C${x1 + curve},${y1} ${x2 - curve},${y2} ${x2},${y2}`} />
        })}
        {[...layout.items].sort((a, b) => Number(b.type === "artboard") - Number(a.type === "artboard")).map((item) => {
          const index = layout.items.indexOf(item)
          const { Icon, title } = nodeKinds[item.type]
          const href = item.type === "video" ? item.cover : item.url
          const media = Boolean(href && !failed.has(href))
          const font = featured ? 10.5 : 8.5
          const header = Math.min(featured ? 25 : 20, item.height * 0.3)
          const inset = featured ? 9 : 7
          const bodyY = item.y + header + 4
          const bodyHeight = Math.max(0, item.height - header - 8)
          const detail = item.text || (item.type === "video" ? "暂无视频封面" : href && failed.has(href) ? "预览暂不可用" : "")
          const lines = canvasPreviewLines(detail, item.width - inset * 2, font, Math.min(5, Math.floor((bodyHeight - 4) / (font * 1.5))))
          const label = canvasPreviewLines(item.label || title, item.width - inset * 2 - 23, font, 1)[0]
          return (
            <g key={item.sourceIndex} className={`canvas-home-preview-node is-${item.type}`}>
              <rect className="canvas-home-preview-surface" x={item.x} y={item.y} width={item.width} height={item.height} rx={featured ? 7 : 5} />
              <g clipPath={`url(#${id}-node-${index})`}>
                {item.width > 45 && header > 12 && (
                  <>
                    <Icon x={item.x + inset} y={item.y + (header - font - 1) / 2} width={font + 1} height={font + 1} strokeWidth={1.5} />
                    <text className="canvas-home-preview-label" x={item.x + inset + font + 5} y={item.y + header * 0.69} fontSize={font}>{label}</text>
                    {item.width > 95 && <MoreHorizontal x={item.x + item.width - 16} y={item.y + (header - 10) / 2} width={10} height={10} />}
                    <path className="canvas-home-preview-divider" d={`M${item.x},${item.y + header}h${item.width}`} />
                  </>
                )}
                {media ? (
                  <image href={href} x={item.x + 4} y={bodyY} width={Math.max(1, item.width - 8)} height={Math.max(1, bodyHeight)} preserveAspectRatio="xMidYMid slice" onError={() => { setFailed((previous) => new Set(previous).add(href!)) }} />
                ) : lines.length ? (
                  <text className="canvas-home-preview-text" x={item.x + inset} y={bodyY + font + 3} fontSize={font}>
                    {lines.map((line, lineIndex) => <tspan key={lineIndex} x={item.x + inset} dy={lineIndex ? font * 1.5 : 0}>{line}</tspan>)}
                  </text>
                ) : item.type === "text" || item.type === "generator" ? (
                  <g className="canvas-home-preview-skeleton">
                    {[0.76, 0.93, 0.55].map((ratio, lineIndex) => bodyHeight > 12 + lineIndex * 9 && <rect key={lineIndex} x={item.x + inset} y={bodyY + 6 + lineIndex * 9} width={Math.max(1, (item.width - inset * 2) * ratio)} height={2.5} rx={1} />)}
                  </g>
                ) : (
                  <Icon className="canvas-home-preview-placeholder" x={item.x + item.width / 2 - 10} y={bodyY + bodyHeight / 2 - 10} width={20} height={20} strokeWidth={1.2} />
                )}
                {item.type === "video" && media && item.width > 55 && (
                  <g transform={`translate(${item.x + item.width - 18},${item.y + item.height - 17})`}>
                    <circle className="canvas-home-preview-play-bg" r={11} />
                    <path className="canvas-home-preview-play" d="M-3,-5 L5,0 L-3,5 Z" />
                  </g>
                )}
              </g>
            </g>
          )
        })}
        {layout.links.flatMap(([left, right], index) => {
          const source = layout.items[left]
          const target = layout.items[right]
          return [
            <circle key={`${index}-out`} className="canvas-home-preview-port" cx={source.x + source.width} cy={source.y + source.height / 2} r={featured ? 3.2 : 2.5} />,
            <circle key={`${index}-in`} className="canvas-home-preview-port" cx={target.x} cy={target.y + target.height / 2} r={featured ? 3.2 : 2.5} />,
          ]
        })}
      </svg>
      {layout.cropped && <span className="canvas-home-preview-scope">局部预览 · {preview?.nodeCount ?? 0} 个节点</span>}
    </span>
  )
}
