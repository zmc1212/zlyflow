import { useLayoutEffect, useRef } from "react"

/** Adapted from OpenCut classic `src/hooks/use-committed-ref.ts`. */
export function useCommittedRef<T>(value: T) {
  const ref = useRef(value)
  useLayoutEffect(() => {
    ref.current = value
  }, [value])
  return ref
}
