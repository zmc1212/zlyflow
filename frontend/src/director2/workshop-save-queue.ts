/** One request at a time per beat. A response can never discard a newer edit. */
export function createWorkshopSaveQueue<T>(save: (key: string, value: T) => Promise<void>, changed: (key: string, state: "pending" | "saving" | "saved" | "error", error?: unknown) => void, delay = 650) {
  const entries = new Map<string, { value: T; version: number; timer?: ReturnType<typeof setTimeout>; running?: Promise<void> }>()
  const enqueue = (key: string, value: T) => {
    const previous = entries.get(key)
    if (previous?.timer) clearTimeout(previous.timer)
    const next = { value, version: (previous?.version || 0) + 1, running: previous?.running, timer: undefined as ReturnType<typeof setTimeout> | undefined }
    entries.set(key, next)
    changed(key, "pending")
    next.timer = setTimeout(() => { void flush(key).catch(() => {}) }, delay)
  }
  const flush = async (key: string): Promise<void> => {
    const entry = entries.get(key)
    if (!entry) return
    if (entry.timer) { clearTimeout(entry.timer); entry.timer = undefined }
    if (entry.running) { await entry.running.catch(() => {}); if (entries.has(key)) return flush(key); return }
    const version = entry.version
    changed(key, "saving")
    const running = save(key, entry.value)
    entry.running = running
    try {
      await running
      const latest = entries.get(key)
      if (latest?.version === version) { entries.delete(key); changed(key, "saved") }
      else if (latest) { latest.running = undefined; return flush(key) }
    } catch (error) {
      const latest = entries.get(key)
      if (latest) latest.running = undefined
      changed(key, "error", error)
      throw error
    }
  }
  return { enqueue, flush, pending: () => entries.size > 0, flushAll: () => Promise.allSettled([...entries.keys()].map(flush)) }
}
