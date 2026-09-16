import type { Director2CreationMode } from "./api"

export type { Director2CreationMode }

export function parseDirector2CreationMode(value: string | null | undefined): Director2CreationMode | null {
  return value === "agent" || value === "manual" ? value : null
}

export function director2CreationModeStorageKey(projectId: string): string {
  return `director2-creation-mode:${projectId}`
}

export function readDirector2CreationMode(projectId: string): Director2CreationMode {
  if (typeof window === "undefined") return "agent"
  try {
    return parseDirector2CreationMode(window.localStorage.getItem(director2CreationModeStorageKey(projectId))) ?? "agent"
  } catch {
    return "agent"
  }
}

export function storeDirector2CreationMode(projectId: string, mode: Director2CreationMode): void {
  try {
    window.localStorage.setItem(director2CreationModeStorageKey(projectId), mode)
  } catch {
    // 浏览器禁用 localStorage 时仅保留内存和 URL 状态。
  }
}
