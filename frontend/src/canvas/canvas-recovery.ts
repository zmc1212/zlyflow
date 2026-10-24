import { parseCanvasContent, readCanvasSettings, serializeCanvasDraft } from "./canvas-model"
import { CANVAS_CONTENT_LIMIT_BYTES, canvasByteSize } from "./canvas-save"

export type CanvasRecovery = { baseVersion: number; content: string }
type RecoveryStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">
const memory = new Map<string, CanvasRecovery>()
const owners = new Map<string, symbol>()

export function claimCanvasRecovery(projectId: string, owner = Symbol(projectId)): symbol {
  owners.set(projectId, owner)
  return owner
}

function storage(): RecoveryStorage | undefined {
  try { return typeof sessionStorage === "undefined" ? undefined : sessionStorage } catch { return undefined }
}

function key(projectId: string) { return `zly-canvas-recovery:${projectId}` }

export function readCanvasRecovery(projectId: string, target = storage()): CanvasRecovery | null {
  const cached = memory.get(projectId)
  if (cached) return cached
  try {
    const value = JSON.parse(target?.getItem(key(projectId)) ?? "null") as Partial<CanvasRecovery> | null
    if (!value || !Number.isInteger(value.baseVersion) || Number(value.baseVersion) < 1
      || typeof value.content !== "string" || canvasByteSize(value.content) > CANVAS_CONTENT_LIMIT_BYTES) return null
    const draft = JSON.parse(value.content)
    if (!draft || !Array.isArray(draft.nodes) || !Array.isArray(draft.edges)) return null
    const recovery = value as CanvasRecovery
    memory.set(projectId, recovery)
    return recovery
  } catch { return null }
}

export function writeCanvasRecovery(projectId: string, recovery: CanvasRecovery, target = storage(), owner?: symbol): void {
  if (owner && owners.get(projectId) !== owner) return
  memory.set(projectId, recovery)
  try { target?.setItem(key(projectId), JSON.stringify(recovery)) } catch { /* Keep the in-memory draft if the tab's quota is full. */ }
}

/** An earlier save must never clear a newer local edit. */
export function clearCanvasRecovery(projectId: string, expectedContent?: string, target = storage()): void {
  if (expectedContent !== undefined && readCanvasRecovery(projectId, target)?.content !== expectedContent) return
  memory.delete(projectId)
  try { target?.removeItem(key(projectId)) } catch { /* Storage can be disabled by the browser. */ }
}

export function normalizedCanvasContent(content: string): string {
  const draft = parseCanvasContent(content)
  return serializeCanvasDraft(draft.nodes, draft.edges, { canvasSettings: { ...readCanvasSettings(draft.canvasSettings) } })
}

export function resolveCanvasRecovery(serverContent: string, serverVersion: number, recovery: CanvasRecovery | null) {
  const savedContent = normalizedCanvasContent(serverContent)
  const restored = recovery !== null && normalizedCanvasContent(recovery.content) !== savedContent
  return {
    savedContent,
    content: restored ? recovery.content : serverContent,
    baseVersion: restored ? recovery.baseVersion : serverVersion,
    restored,
    conflict: restored && recovery.baseVersion !== serverVersion,
  }
}
