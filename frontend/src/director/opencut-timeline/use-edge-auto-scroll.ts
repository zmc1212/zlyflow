/**
 * Source adaptation:
 * OpenCut classic apps/web/src/timeline/hooks/use-edge-auto-scroll.ts
 * Upstream commit: cf5e79e919144200294fb9fed22a222592a0aeea
 */
import { useEffect, useRef } from "react"
import type { RefObject } from "react"

export function useEdgeAutoScroll({
  isActive,
  getMouseClientX,
  tracksScrollRef,
  contentWidth,
  edgeThreshold = 100,
  maxScrollSpeed = 15,
}: {
  isActive: boolean
  getMouseClientX: () => number
  tracksScrollRef: RefObject<HTMLDivElement | null>
  contentWidth: number
  edgeThreshold?: number
  maxScrollSpeed?: number
}): void {
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (!isActive) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
      return
    }
    const step = () => {
      const viewport = tracksScrollRef.current
      if (!viewport) {
        rafRef.current = requestAnimationFrame(step)
        return
      }
      const rect = viewport.getBoundingClientRect()
      const relativeX = getMouseClientX() - rect.left
      const viewportWidth = viewport.clientWidth
      const scrollMax = Math.max(0, Math.max(contentWidth, viewport.scrollWidth) - viewportWidth)
      let speed = 0
      if (relativeX < edgeThreshold && viewport.scrollLeft > 0) {
        speed = -maxScrollSpeed * (1 - Math.max(0, relativeX) / edgeThreshold)
      } else if (relativeX > viewportWidth - edgeThreshold && viewport.scrollLeft < scrollMax) {
        speed = maxScrollSpeed * (1 - Math.max(0, viewportWidth - relativeX) / edgeThreshold)
      }
      if (speed !== 0) viewport.scrollLeft = Math.max(0, Math.min(scrollMax, viewport.scrollLeft + speed))
      rafRef.current = requestAnimationFrame(step)
    }
    rafRef.current = requestAnimationFrame(step)
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [contentWidth, edgeThreshold, getMouseClientX, isActive, maxScrollSpeed, tracksScrollRef])
}
