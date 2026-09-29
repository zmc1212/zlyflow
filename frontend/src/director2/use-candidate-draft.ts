import { useState, type Dispatch, type SetStateAction } from "react"

// Session-only drafts survive navigation; source/revision keys prevent stale reuse.
export function useCandidateDraft<T>(key: string | null, empty: T): [T, Dispatch<SetStateAction<T>>] {
  function read(): T {
    if (!key) return empty
    try { return JSON.parse(sessionStorage.getItem(key) || "null") ?? empty }
    catch { return empty }
  }
  const [record, setRecord] = useState(() => ({ key, value: read() }))
  const value = record.key === key ? record.value : read()
  return [value, update => {
    const next = typeof update === "function" ? (update as (old: T) => T)(value) : update
    if (key) {
      try { sessionStorage.setItem(key, JSON.stringify(next)) } catch { /* Memory state still works when storage is unavailable. */ }
    }
    setRecord({ key, value: next })
  }]
}
