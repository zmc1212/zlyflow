import { Background, useStore } from "@xyflow/react"

export function CanvasGrid() {
  const zoom = useStore((state) => state.transform[2])
  // Keep the dots legible at low zoom using wider spacing and a fixed screen size.
  const gap = zoom < 0.2 ? 72 : zoom < 0.4 ? 36 : 18

  return <Background gap={gap} size={1.25 / zoom} color="var(--canvas-grid-dot)" />
}
