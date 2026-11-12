import type { FeaturedMusic, MusicJob, MusicLyricLine } from "./api"

export type MusicFilter = "all" | "active" | "succeeded" | "failed"
export type MusicView = "grid" | "list"

export const MUSIC_MOODS = [
  { id: "folk", title: "旷野民谣", subtitle: "木吉他 · 温暖男声", image: "wheat", instrumental: false, prompt: "写给海子的一首民谣，温暖的男声与木吉他，\n有旷野的辽阔，也有回家的温柔。" },
  { id: "jazz", title: "雨夜爵士", subtitle: "萨克斯 · 慵懒节奏", image: "rain", instrumental: true, prompt: "写一首适合雨夜独处的爵士纯音乐，萨克斯与电钢琴，慵懒的鼓刷，像街灯映在湿漉漉的路面上。" },
  { id: "cinematic", title: "电影叙事", subtitle: "弦乐 · 情绪渐进", image: "mist", instrumental: true, prompt: "为一段山间旅行写电影感纯音乐，以安静的钢琴开始，弦乐逐渐铺开，从克制到辽阔，结尾留一点余韵。" },
  { id: "daylight", title: "轻快日常", subtitle: "轻打击 · 清新旋律", image: "daylight", instrumental: false, prompt: "写一首关于普通日子里小小幸福的歌，清新的女声、原声吉他与轻打击乐，旋律轻快自然，像清晨窗边的阳光。" },
  { id: "road", title: "沿途有风", subtitle: "独立流行 · 自由随性", image: "wheat", instrumental: false, prompt: "写一首适合公路旅行的独立流行歌曲，松弛的男声与吉他，鼓点有向前走的力量，关于出发、风和沿途遇见的人。" },
  { id: "city", title: "城市漫游", subtitle: "合成器 · 夜色律动", image: "rain", instrumental: true, prompt: "写一首城市夜游的电子纯音乐，复古合成器、温暖贝斯与有弹性的节奏，夜色有一点神秘，但不压抑。" },
  { id: "quiet", title: "山间留白", subtitle: "氛围 · 安静呼吸", image: "mist", instrumental: true, prompt: "写一首安静的氛围纯音乐，柔和的钢琴、稀疏的弦乐与轻微自然声，旋律缓慢，像山间薄雾，有足够的留白。" },
  { id: "letter", title: "未寄出的信", subtitle: "钢琴 · 细腻女声", image: "daylight", instrumental: false, prompt: "写一首像未寄出的信的钢琴流行歌曲，细腻的女声，关于想念与和解，主歌像轻声讲述，副歌温暖而有记忆点。" },
] as const

const GENRES: [RegExp, string][] = [
  [/\bambient\b.*\belectronic\b|\belectronic\b.*\bambient\b/i, "氛围电子"],
  [/\bacoustic\b.*\bpop\b|\bpop\b.*\bacoustic\b/i, "原声流行"],
  [/\bfolk\b/i, "民谣"], [/\bjazz\b/i, "爵士"], [/\bhip[ -]?hop\b|\brap\b/i, "嘻哈"],
  [/\brock\b/i, "摇滚"], [/\bchinese traditional\b|\bguofeng\b/i, "古风"],
  [/\belectronic\b|\bsynthpop\b/i, "电子"], [/\bambient\b/i, "氛围"],
  [/\bpop\b/i, "流行"], [/\bcinematic\b|\borchestral\b/i, "电影配乐"],
]

/** 将已有风格标签压缩为可读信息；完整风格始终保留在歌曲详情。 */
export function musicStyleTags(job: Pick<MusicJob, "style" | "lyrics">): string[] {
  const tags: string[] = []
  const genre = GENRES.find(([pattern]) => pattern.test(job.style))?.[1]
  if (genre) tags.push(genre)
  if (!musicLyricsPreview(job.lyrics).length) tags.push("纯音乐")
  else if (/\bfemale\s+(?:vocal|voice|alto|soprano)|女声/i.test(job.style)) tags.push("女声")
  else if (/\bmale\s+(?:vocal|voice|tenor|baritone)|男声/i.test(job.style)) tags.push("男声")
  if (/\bacoustic guitar\b|木吉他/i.test(job.style)) tags.push("木吉他")
  else if (/\bpiano\b|钢琴/i.test(job.style)) tags.push("钢琴")
  else if (/\bsaxophone\b|\bsax\b|萨克斯/i.test(job.style)) tags.push("萨克斯")
  else if (/\bstrings\b|弦乐/i.test(job.style)) tags.push("弦乐")
  return tags.length ? tags : [job.style.split(/[,，]/).find((part) => part.trim())?.trim() || "自由创作"]
}

export function musicTempo(style: string): string | null {
  return style.match(/\b(\d{2,3})\s*BPM\b/i)?.[0].replace(/\s*BPM/i, " BPM") ?? null
}

export function musicArtworkUrl(job: Pick<MusicJob, "style" | "cover_url">): string {
  const mood = /\bfolk\b|民谣/i.test(job.style) ? "wheat"
    : /\bambient\b.*\belectronic\b|\belectronic\b.*\bambient\b|氛围电子/i.test(job.style) ? "flow"
    : /\bacoustic\b.*\bpop\b|\bpop\b.*\bacoustic\b|原声流行/i.test(job.style) ? "morning"
    : /\bjazz\b|爵士/i.test(job.style) ? "rain"
    : /\bcinematic\b|\borchestral\b|电影配乐/i.test(job.style) ? "mist" : null
  return mood ? `/music-art/${mood}.webp` : job.cover_url || "/music-art/daylight.webp"
}

/**
 * 音乐页的用户作用域：`undefined` 表示只看本人，`"all"` 表示全部用户，其它为指定账号 id。
 * 仅管理员（admin / super_admin）生效；普通账号与「选中本人」都返回 undefined。
 */
export function musicScopedUserId(
  role: string | null | undefined, adminFilter: string | null | undefined, currentUserId: string | null | undefined,
): string | undefined {
  if (role !== "admin" && role !== "super_admin") return undefined
  const filter = adminFilter || "all"
  return filter === currentUserId ? undefined : filter
}

/** 管理员是否正以只读方式查看某个具体用户（非本人、也非「全部用户」）的音乐数据。 */
export function musicReadOnlyScope(
  role: string | null | undefined, adminFilter: string | null | undefined, currentUserId: string | null | undefined,
): boolean {
  const scope = musicScopedUserId(role, adminFilter, currentUserId)
  return scope !== undefined && scope !== "all"
}

/** 是否可对某条音乐任务/对话执行删除、重命名、对话修改等写操作：本人且非只读查看他人时。 */
export function musicCanManage(
  ownerUserId: string | null | undefined, currentUserId: string | null | undefined, readOnly: boolean,
): boolean {
  return !readOnly && Boolean(currentUserId) && ownerUserId === currentUserId
}

/** 管理员是否正在查看他人数据（「全部用户」或某个具体账号）；用于跨账号重试入口。 */
export function musicAdminViewingOthers(
  role: string | null | undefined, adminFilter: string | null | undefined, currentUserId: string | null | undefined,
): boolean {
  return musicScopedUserId(role, adminFilter, currentUserId) !== undefined
}

/** 是否可对失败歌曲点「重试」：仅失败任务；本人可管理，或管理员正在跨账号查看。 */
export function musicCanRetry(
  job: Pick<MusicJob, "status" | "owner_user_id">, currentUserId: string | null | undefined,
  readOnly: boolean, adminViewingOthers: boolean,
): boolean {
  return job.status === "failed" && (musicCanManage(job.owner_user_id, currentUserId, readOnly) || adminViewingOthers)
}

export function filterMusicJobs(jobs: MusicJob[], filter: MusicFilter, query: string): MusicJob[] {  const needle = query.trim().toLocaleLowerCase()
  return jobs.filter((job) => {
    const matchesStatus = filter === "all" || (filter === "active" ? job.status === "queued" || job.status === "running" : job.status === filter)
    return matchesStatus && (!needle || `${job.title} ${job.style} ${musicStyleTags(job).join(" ")}`.toLocaleLowerCase().includes(needle))
  })
}

/** 精选歌曲在播放器里用一个稳定的合成 ID，避免与原任务 ID 冲突。 */
export const FEATURED_MUSIC_ID_PREFIX = "featured:"

export function featuredMusicJobId(featuredId: string): string {
  return `${FEATURED_MUSIC_ID_PREFIX}${featuredId}`
}

export function isFeaturedMusicJobId(jobId: string | null | undefined): boolean {
  return Boolean(jobId?.startsWith(FEATURED_MUSIC_ID_PREFIX))
}

/** 把只读精选快照投影成播放器可用的 MusicJob，不改动曲库任务状态。 */
export function featuredMusicAsJob(song: FeaturedMusic): MusicJob {
  return {
    id: featuredMusicJobId(song.id),
    owner_user_id: song.owner_user_id ?? "",
    title: song.title,
    style: song.style,
    lyrics: song.lyrics,
    status: "succeeded",
    progress: 100,
    params: {},
    result_url: song.result_url,
    result_format: song.result_format,
    cover_url: song.cover_url,
    duration_seconds: song.duration_seconds,
    remote_job_id: null,
    remote_song_id: null,
    error_message: null,
    chat_id: null,
    created_at: song.published_at,
    updated_at: song.updated_at,
    completed_at: song.published_at,
  }
}

export function adjacentMusicJob(jobs: MusicJob[], id: string, direction: -1 | 1): MusicJob | null {
  const playable = jobs.filter((job) => job.status === "succeeded" && job.result_url)
  const index = playable.findIndex((job) => job.id === id)
  return index < 0 ? null : playable[index + direction] ?? null
}

/** 对话版本链：同一 chat_id 的任务按创建时间排序，链上 ≥2 版时给每张卡片「对话 vN」标签。 */
export function buildMusicVersionLabels(jobs: MusicJob[]): Record<string, string> {
  const chains = new Map<string, MusicJob[]>()
  for (const job of jobs) {
    if (!job.chat_id) continue
    const chain = chains.get(job.chat_id) ?? []
    chain.push(job)
    chains.set(job.chat_id, chain)
  }
  const labels: Record<string, string> = {}
  for (const chain of chains.values()) {
    if (chain.length < 2) continue
    chain.sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""))
    chain.forEach((job, index) => { labels[job.id] = `对话 v${index + 1}` })
  }
  return labels
}

export function musicDate(value: string | null, now = new Date()): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const sameDay = date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
  const day = sameDay ? "今天" : date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })
  return `${day} ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })}`
}

/** 对话栏右缘的短时间：今天只显示 HH:MM，今年显示 M/D HH:MM（对齐生成页任务栏）。 */
export function musicTimeShort(value: string | null | undefined, nowMs = Date.now()): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const now = new Date(nowMs)
  const time = date.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" })
  if (date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()) return time
  if (date.getFullYear() === now.getFullYear()) return `${date.getMonth() + 1}/${date.getDate()} ${time}`
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`
}

/** 悬停提示里的完整时间。 */
export function musicTimeFull(value: string | null | undefined): string {
  if (!value) return ""
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", { hour12: false })
}

export function musicLyricText(lyrics: string): string[] {
  return lyrics.split(/\r\n?|\n/).map((line) => line.trim()).filter((line) => line && !/^\[.*\]$/.test(line))
}

export function musicLyricsPreview(lyrics: string): string[] {
  return musicLyricText(lyrics).slice(0, 2)
}

/** The last cue reached stays the scroll anchor through an instrumental gap. */
export function musicLyricCursor(lines: MusicLyricLine[], seconds: number): number {
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const start = lines[index].start_seconds
    if (start !== null && start <= seconds) return index
  }
  return -1
}
