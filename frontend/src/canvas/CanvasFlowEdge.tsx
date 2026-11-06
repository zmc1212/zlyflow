import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow, type EdgeProps } from "@xyflow/react"

export default function CanvasFlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  target,
  targetHandleId,
  style,
  markerEnd,
  markerStart,
}: EdgeProps) {
  const { getNode } = useReactFlow()
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })
  const label = targetHandleId === "prompt" ? "提示词" : getNode(target)?.type === "generator" ? "参考图" : null
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
      {label ? <EdgeLabelRenderer><span className="canvas-edge-label" style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}>{label}</span></EdgeLabelRenderer> : null}
    </>
  )
}
