import type { Director2Episode } from "./api"

export type EpisodeFilter = "all" | "draft" | "ready" | "working" | "complete"
export type EpisodeSort = "number_asc" | "number_desc" | "updated_desc"
export type EpisodeStageStatus = "wait" | "process" | "finish"

export const EPISODE_FILTERS: { value: EpisodeFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "draft", label: "草稿" },
  { value: "ready", label: "脚本就绪" },
  { value: "working", label: "制作中" },
  { value: "complete", label: "分镜完成" },
]

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿", scripting: "脚本生成中", script_ready: "脚本就绪", sketching: "出图中", sketched: "分镜完成",
}

export function episodeStatusLabel(status: string): string {
  return STATUS_LABELS[status] || status || "草稿"
}

export function episodeFilterMatches(episode: Director2Episode, filter: EpisodeFilter): boolean {
  if (filter === "all") return true
  if (filter === "draft") return episode.status === "draft" || !episode.status
  if (filter === "ready") return episode.status === "script_ready"
  if (filter === "working") return episode.status === "scripting" || episode.status === "sketching"
  return episode.status === "sketched"
}

export function episodeOverviewCounts(episodes: Director2Episode[]) {
  return {
    all: episodes.length,
    draft: episodes.filter((ep) => episodeFilterMatches(ep, "draft")).length,
    ready: episodes.filter((ep) => episodeFilterMatches(ep, "ready")).length,
    working: episodes.filter((ep) => episodeFilterMatches(ep, "working")).length,
    complete: episodes.filter((ep) => episodeFilterMatches(ep, "complete")).length,
    scriptReady: episodes.filter((ep) => ["script_ready", "sketching", "sketched"].includes(ep.status)).length,
    shots: episodes.reduce((sum, ep) => sum + Math.max(0, Number(ep.shots_count) || 0), 0),
  }
}

export function nextEpisodeNumber(episodes: Director2Episode[]): number {
  return episodes.reduce((max, ep) => Number.isSafeInteger(ep.episode_num) ? Math.max(max, ep.episode_num) : max, 0) + 1
}

export function episodeScriptSummary(script: string | null | undefined): string {
  return (script || "").replace(/^\s{0,3}#{1,6}\s+/gm, "").replace(/^\s*[-*+]\s+/gm, "").replace(/\s+/g, " ").trim()
}

export function visibleEpisodes(episodes: Director2Episode[], query: string, filter: EpisodeFilter, sort: EpisodeSort): Director2Episode[] {
  const term = query.trim().toLocaleLowerCase()
  const result = episodes.filter((ep) => {
    if (!episodeFilterMatches(ep, filter)) return false
    if (!term) return true
    const number = String(ep.episode_num)
    const searchable = [ep.title, ep.script_text || "", number.padStart(2, "0"), `第 ${number} 集`, `第${number}集`].join(" ").toLocaleLowerCase()
    return searchable.includes(term)
  })
  return result.sort((a, b) => {
    if (sort === "updated_desc") {
      const time = (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0)
      if (time) return time
    }
    const order = (a.episode_num - b.episode_num) || a.id.localeCompare(b.id)
    return sort === "number_desc" ? -order : order
  })
}

/** 分集制作状态的位置；不是镜头或视频任务的完成百分比。 */
export function episodeStageStates(status: string): EpisodeStageStatus[] {
  const reached: Record<string, number> = { scripting: 0, script_ready: 1, sketching: 1, sketched: 3 }
  return [0, 1, 2, 3].map((index) => {
    if ((status === "scripting" && index === 1) || (status === "sketching" && index === 2)) return "process"
    return index <= (reached[status] ?? -1) ? "finish" : "wait"
  })
}

export function episodeUpdatedLabel(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "暂无更新日期" : `更新于 ${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
}
