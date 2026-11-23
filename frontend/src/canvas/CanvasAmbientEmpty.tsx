import { type CSSProperties } from "react"
import { useStore } from "@xyflow/react"

// 空画布的即梦式氛围层：围绕画布中心的一簇彩色点阵"星云"，
// 点阵间距/相位与 CanvasGrid 逐格对齐（公式同 CanvasGridRipples），向外渐隐回普通网格。
export function CanvasAmbientEmpty() {
  const transform = useStore((state) => state.transform)
  const [tx, ty, zoom] = transform
  const gap = zoom < 0.2 ? 72 : zoom < 0.4 ? 36 : 18
  const spacing = gap * zoom
  const phaseX = (((tx % spacing) + spacing) % spacing) + 0.625
  const phaseY = (((ty % spacing) + spacing) % spacing) + 0.625

  const style = {
    "--amb-spacing": `${spacing}px`,
    "--amb-phase-x": `${phaseX}px`,
    "--amb-phase-y": `${phaseY}px`,
  } as CSSProperties

  return (
    <div className="canvas-ambient-empty" style={style} aria-hidden="true">
      <span className="canvas-ambient-glow" />
      <span className="canvas-ambient-dots is-blue" />
      <span className="canvas-ambient-dots is-violet" />
    </div>
  )
}

// 中央提示里的渐变双星图标（呼应即梦 logo 形态：大四角星 + 小四角星）。
export function CanvasEmptySparkle({ size = 26 }: { size?: number }) {
  return (
    <svg
      className="canvas-empty-sparkle"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="canvas-empty-sparkle-grad" x1="3" y1="2" x2="21" y2="21" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#9a63ff" />
          <stop offset=".52" stopColor="#5a7bff" />
          <stop offset="1" stopColor="#37c3ff" />
        </linearGradient>
      </defs>
      <path
        d="M12.6 1.8c.14-.44.72-.44.86 0l1.5 4.7a1.9 1.9 0 0 0 1.24 1.24l4.7 1.5c.44.14.44.72 0 .86l-4.7 1.5a1.9 1.9 0 0 0-1.24 1.24l-1.5 4.7c-.14.44-.72.44-.86 0l-1.5-4.7a1.9 1.9 0 0 0-1.24-1.24l-4.7-1.5c-.44-.14-.44-.72 0-.86l4.7-1.5A1.9 1.9 0 0 0 11.1 6.5Z"
        fill="url(#canvas-empty-sparkle-grad)"
      />
      <path
        d="M6.1 13.6c.1-.3.52-.3.62 0l.62 1.9c.1.3.32.52.62.62l1.9.62c.3.1.3.52 0 .62l-1.9.62a1 1 0 0 0-.62.62l-.62 1.9c-.1.3-.52.3-.62 0l-.62-1.9a1 1 0 0 0-.62-.62l-1.9-.62c-.3-.1-.3-.52 0-.62l1.9-.62a1 1 0 0 0 .62-.62Z"
        fill="url(#canvas-empty-sparkle-grad)"
        opacity=".9"
      />
    </svg>
  )
}
