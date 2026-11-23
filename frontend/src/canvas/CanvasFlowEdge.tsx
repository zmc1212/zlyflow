import {
  BaseEdge, Position, getBezierPath, useStore, type ConnectionLineComponentProps, type EdgeProps, type EdgeTypes,
} from "@xyflow/react"
import type { CSSProperties } from "react"

const outlineOffset = 5
const outlineWidth = 1

export const canvasFlowStyle = {
  "--canvas-selection-outline-offset": `${outlineOffset}px`,
  "--canvas-selection-outline-width": `${outlineWidth}px`,
} as CSSProperties

function ConnectionHighlight({ path }: { path: string }) {
  return <path d={path} pathLength={100} className="canvas-connection-highlight" aria-hidden="true" />
}

export function CanvasConnectionTrace({ path }: { path: string }) {
  return <>
    <path d={path} className="canvas-connection-line" />
    <ConnectionHighlight path={path} />
  </>
}

function CanvasFlowEdge({
  id, source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  style, markerStart, markerEnd, interactionWidth, pathOptions,
}: EdgeProps) {
  const related = useStore((state) => Boolean(state.nodeLookup.get(source)?.selected || state.nodeLookup.get(target)?.selected))
  const [path] = getBezierPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
    curvature: pathOptions?.curvature,
  })

  return <>
    <BaseEdge
      id={id}
      path={path}
      style={style}
      markerStart={markerStart}
      markerEnd={markerEnd}
      interactionWidth={interactionWidth}
      className={related ? "canvas-edge-related" : undefined}
    />
    {related ? <ConnectionHighlight path={path} /> : null}
  </>
}

export const canvasEdgeTypes = { canvasFlow: CanvasFlowEdge } satisfies EdgeTypes

export function CanvasConnectionLine({ fromNode, fromX, fromY, toX, toY, fromPosition, toPosition }: ConnectionLineComponentProps) {
  // Offset only the live preview. Saved and pending edges use the handle at the card edge.
  const offset = fromNode.selected ? outlineOffset + outlineWidth / 2 : 0
  const sourceX = fromX + (fromPosition === Position.Right ? offset : fromPosition === Position.Left ? -offset : 0)
  const sourceY = fromY + (fromPosition === Position.Bottom ? offset : fromPosition === Position.Top ? -offset : 0)
  const [path] = getBezierPath({ sourceX, sourceY, targetX: toX, targetY: toY, sourcePosition: fromPosition, targetPosition: toPosition })

  return <CanvasConnectionTrace path={path} />
}
