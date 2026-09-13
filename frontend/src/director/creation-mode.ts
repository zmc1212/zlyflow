// 导演台创作模式：AI 生成（9 Agent 流水线驱动）与手动编辑（直接编写各环节内容）。
// 真源是 URL ?mode=（可分享、刷新保持）；缺省时回退到工程的 localStorage 记忆，再缺省 AI 生成。
export type DirectorCreationMode = "agent" | "manual"

export const DIRECTOR_CREATION_MODE_LABELS: Record<DirectorCreationMode, string> = {
  agent: "AI 生成",
  manual: "手动编辑",
}

export function parseDirectorCreationMode(value: string | null | undefined): DirectorCreationMode | null {
  return value === "agent" || value === "manual" ? value : null
}

export function creationModeStorageKey(projectId: string): string {
  return `director-creation-mode:${projectId}`
}

export function readStoredCreationMode(projectId: string): DirectorCreationMode {
  if (typeof window === "undefined") return "agent"
  try {
    return parseDirectorCreationMode(window.localStorage.getItem(creationModeStorageKey(projectId))) ?? "agent"
  } catch {
    return "agent"
  }
}

export function storeCreationMode(projectId: string, mode: DirectorCreationMode): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(creationModeStorageKey(projectId), mode)
  } catch {
    // localStorage 不可用时仅保留 URL 状态
  }
}
