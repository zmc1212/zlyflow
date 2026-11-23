import { useMemo, type CSSProperties } from "react"
import { useStore } from "@xyflow/react"

// 新建节点时的网格波动动画：与 CanvasGrid 相同阈值的点阵（屏幕空间），用径向遮罩
// 做一圈向外扩散的亮环。相位公式对齐 xyflow Background 的 pattern 原点（见 canvas.css 注释）。
export type CanvasGridRipple = { id: number; x: number; y: number }

function rippleGap(zoom: number) {
  return zoom < 0.2 ? 72 : zoom < 0.4 ? 36 : 18
}

export function CanvasGridRipples({ ripples, onDone }: {
  ripples: CanvasGridRipple[]
  onDone: (id: number) => void
}) {
  const transform = useStore((state) => state.transform)
  const [tx, ty, zoom] = transform
  const spacing = rippleGap(zoom) * zoom
  // xyflow Background 的点在屏幕空间位于 (tx mod s) - s/2 + dotR + k*s；
  // 本层把点画在每格中心，因此相位取 (tx mod s) + dotR，dotR 与 Background 的
  // size*zoom/2（=0.625px）一致，保证两层点逐格重合。
  const phaseX = (((tx % spacing) + spacing) % spacing) + 0.625
  const phaseY = (((ty % spacing) + spacing) % spacing) + 0.625

  const layerStyle = useMemo(() => ({
    "--canvas-ripple-spacing": `${spacing}px`,
    "--canvas-ripple-phase-x": `${phaseX}px`,
    "--canvas-ripple-phase-y": `${phaseY}px`,
  }) as CSSProperties, [spacing, phaseX, phaseY])

  const layers = useMemo(() => ripples.map((ripple) => ({
    ripple,
    style: {
      "--ripple-x": `${ripple.x * zoom + tx}px`,
      "--ripple-y": `${ripple.y * zoom + ty}px`,
    } as CSSProperties,
  })), [ripples, tx, ty, zoom])

  if (!layers.length) return null
  return (
    <div className="canvas-grid-ripple-layer" style={layerStyle} aria-hidden="true">
      {layers.map(({ ripple, style }) => (
        <div
          key={ripple.id}
          className="canvas-grid-ripple-wave"
          style={style}
          onAnimationEnd={() => onDone(ripple.id)}
        />
      ))}
    </div>
  )
}
