import { BaseEdge, getBezierPath, type EdgeProps } from "@xyflow/react"

export default function CanvasFlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  markerStart,
}: EdgeProps) {
  const [path] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })
  const stroke = typeof style?.stroke === "string" ? style.stroke : "var(--studio-primary)"
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={style}
        markerEnd={markerEnd}
        markerStart={markerStart}
        interactionWidth={20}
        className="canvas-flow-edge"
      />
      <path
        d={path}
        pathLength={100}
        className="canvas-flow-edge-light"
        style={{ stroke, color: stroke }}
        aria-hidden="true"
      />
    </>
  )
}
