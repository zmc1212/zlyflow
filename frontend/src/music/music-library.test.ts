import { describe, expect, it } from "vitest"
import { formatMusicDuration, type FeaturedMusic, type MusicJob } from "./api"
import { adjacentMusicJob, buildMusicVersionLabels, featuredMusicAsJob, featuredMusicJobId, filterMusicJobs, isFeaturedMusicJobId, musicAdminViewingOthers, musicArtworkUrl, musicCanManage, musicCanRetry, musicLyricCursor, musicLyricsPreview, musicReadOnlyScope, musicScopedUserId, musicStyleTags, musicTempo, musicTimeFull, musicTimeShort } from "./music-library"

const song = (patch: Partial<MusicJob> = {}): MusicJob => ({
  id: "one", owner_user_id: "user", title: "麦地", style: "folk, male vocal, acoustic guitar, 82 BPM", lyrics: "[Verse 1]\n风吹过田野", status: "succeeded", progress: 100, params: {},
  result_url: "/one.flac", result_format: "flac", cover_url: "/original.jpg", duration_seconds: 182, remote_job_id: null, remote_song_id: null, error_message: null, chat_id: null,
  created_at: null, updated_at: null, completed_at: null, ...patch,
})

describe("music library", () => {
  it("searches human-readable tags and combines queued and running songs in the active filter", () => {
    const jobs = [song(), song({ id: "two", status: "queued" }), song({ id: "three", status: "running", style: "jazz" }), song({ id: "four", status: "failed" })]
    expect(filterMusicJobs(jobs, "active", "").map((job) => job.id)).toEqual(["two", "three"])
    expect(filterMusicJobs(jobs, "succeeded", " 民谣 ").map((job) => job.id)).toEqual(["one"])
    expect(filterMusicJobs(jobs, "active", "JAZZ").map((job) => job.id)).toEqual(["three"])
  })

  it("skips jobs without a playable result while navigating the unfiltered queue", () => {
    const jobs = [song(), song({ id: "queued", status: "queued" }), song({ id: "missing", result_url: null }), song({ id: "last", result_url: "/last.flac" })]
    expect(adjacentMusicJob(jobs, "one", 1)?.id).toBe("last")
    expect(adjacentMusicJob(jobs, "last", -1)?.id).toBe("one")
    expect(adjacentMusicJob(jobs, "last", 1)).toBeNull()
    expect(adjacentMusicJob(jobs, "queued", 1)).toBeNull()
  })

  it("treats a song without lyrics as instrumental, even if its style names vocal textures", () => {
    const style = "dreamy ambient electronic, soft female pads, 76 BPM"
    expect(musicStyleTags(song({ style, lyrics: " " }))).toEqual(["氛围电子", "纯音乐"])
    expect(musicStyleTags(song({ style, lyrics: "[Chorus]\n" }))).toEqual(["氛围电子", "纯音乐"])
    expect(musicStyleTags(song({ style: "warm pop, female vocal, piano" }))).toEqual(["流行", "女声", "钢琴"])
    expect(musicTempo(style)).toBe("76 BPM")
  })

  it("uses themed cover art without changing original cover data", () => {
    const folk = song()
    expect(musicArtworkUrl(folk)).toBe("/music-art/wheat.webp")
    expect(folk.cover_url).toBe("/original.jpg")
    expect(musicArtworkUrl(song({ style: "unclassified" }))).toBe("/original.jpg")
    expect(musicArtworkUrl(song({ style: "unclassified", cover_url: null }))).toBe("/music-art/daylight.webp")
  })

  it("does not show structural markers in previews or invalid seconds at a minute boundary", () => {
    expect(musicLyricsPreview("\n[Verse 1]\r\n风吹过田野\r\n[Chorus]\r\n回家的路\r\n多一行")).toEqual(["风吹过田野", "回家的路"])
    expect(formatMusicDuration(179.8)).toBe("3:00")
    expect(formatMusicDuration(Infinity)).toBe("")
  })

  it("anchors the most recently reached lyric after seeking and skips untimed lines", () => {
    const lines = [
      { text: "星星低垂", start_seconds: 8, end_seconds: 12 },
      { text: "待对齐的词", start_seconds: null, end_seconds: null },
      { text: "星星低垂", start_seconds: 42, end_seconds: 46 },
    ]
    expect(musicLyricCursor(lines, 0)).toBe(-1)
    expect(musicLyricCursor(lines, 42)).toBe(2)
    expect(musicLyricCursor(lines, 20)).toBe(0)
    expect(musicLyricCursor(lines, 8)).toBe(0)
  })

  it("numbers chat version chains by creation order and skips single generations", () => {
    const chain = [
      song({ id: "v2", chat_id: "c1", created_at: "2026-11-08T01:00:00+00:00" }),
      song({ id: "v1", chat_id: "c1", created_at: "2026-11-08T00:00:00+00:00" }),
      song({ id: "solo", chat_id: "c2", created_at: "2026-11-08T02:00:00+00:00" }),
      song({ id: "plain", created_at: "2026-11-08T03:00:00+00:00" }),
    ]
    expect(buildMusicVersionLabels(chain)).toEqual({ v1: "对话 v1", v2: "对话 v2" })
    expect(buildMusicVersionLabels([song({ id: "v1", chat_id: "c1" })])).toEqual({})
  })

  it("formats rail timestamps short for the row and full for the hover tooltip", () => {
    // 本地时区构造：今天 09:05 与去年某天
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 9, 5)
    expect(musicTimeShort(today.toISOString(), now.getTime())).toBe("09:05")
    expect(musicTimeShort("not-a-date")).toBe("")
    expect(musicTimeShort(null)).toBe("")
    expect(musicTimeFull("2026-11-08T01:22:30+00:00")).toContain("2026")
    expect(musicTimeFull(null)).toBe("")
  })

  it("scopes music data to the current user unless an admin picks another account", () => {
    // 普通账号始终只看本人，即使传入筛选值
    expect(musicScopedUserId("employee", "all", "u1")).toBeUndefined()
    expect(musicScopedUserId("employee", "u2", "u1")).toBeUndefined()
    // 管理员：全部用户 / 指定账号 / 选中本人
    expect(musicScopedUserId("admin", "all", "u1")).toBe("all")
    expect(musicScopedUserId("super_admin", "u2", "u1")).toBe("u2")
    expect(musicScopedUserId("admin", "u1", "u1")).toBeUndefined()
    expect(musicScopedUserId("admin", "", "u1")).toBe("all")
    // 未登录（无角色）保持本人作用域
    expect(musicScopedUserId(null, "u2", undefined)).toBeUndefined()
  })

  it("only treats a concrete other user as a read-only music scope", () => {
    expect(musicReadOnlyScope("admin", "u2", "u1")).toBe(true)
    expect(musicReadOnlyScope("admin", "all", "u1")).toBe(false)
    expect(musicReadOnlyScope("admin", "u1", "u1")).toBe(false)
    expect(musicReadOnlyScope("employee", "u2", "u1")).toBe(false)
  })

  it("lets the owner manage their own music while viewing another user stays read-only", () => {
    expect(musicCanManage("u1", "u1", false)).toBe(true)
    expect(musicCanManage("u2", "u1", false)).toBe(false)
    expect(musicCanManage("u1", "u1", true)).toBe(false)
    expect(musicCanManage("u1", undefined, false)).toBe(false)
    expect(musicCanManage("u1", "u1", false)).toBe(true)
  })

  it("lets admins retry another user's failed music without granting delete", () => {
    // 管理作用域：全部用户 / 指定账号；选中本人或普通账号不算跨账号。
    expect(musicAdminViewingOthers("admin", "all", "admin-1")).toBe(true)
    expect(musicAdminViewingOthers("super_admin", "emp-1", "admin-1")).toBe(true)
    expect(musicAdminViewingOthers("admin", "admin-1", "admin-1")).toBe(false)
    expect(musicAdminViewingOthers("employee", "emp-1", "admin-1")).toBe(false)

    // 重试：管理员跨账号放行，普通员工对他人的任务仍不可重试；成功/进行中的任务永不显示重试。
    expect(musicCanRetry({ status: "failed", owner_user_id: "emp-1" }, "admin-1", true, true)).toBe(true)
    expect(musicCanRetry({ status: "failed", owner_user_id: "emp-1" }, "admin-1", false, false)).toBe(false)
    expect(musicCanRetry({ status: "succeeded", owner_user_id: "emp-1" }, "admin-1", true, true)).toBe(false)
    expect(musicCanRetry({ status: "running", owner_user_id: "emp-1" }, "admin-1", true, true)).toBe(false)
    expect(musicCanRetry({ status: "failed", owner_user_id: "admin-1" }, "admin-1", false, false)).toBe(true)
    // 删除/重命名仍由 musicCanManage 判定，管理员查看他人时保持只读。
    expect(musicCanManage("emp-1", "admin-1", true)).toBe(false)
  })

  it("projects a published featured song into a playable queue item", () => {
    const featured: FeaturedMusic = {
      id: "featured-music-1", job_id: "music-1", owner_user_id: "user-1", title: "麦地",
      summary: "适合傍晚", style: "folk, female vocal, acoustic guitar, 88 BPM", lyrics: "[Verse]\n风吹过田野",
      result_url: "https://cdn.example.com/song.flac", cover_url: "https://cdn.example.com/song.jpg",
      duration_seconds: 190, result_format: "flac", sort_order: 0,
      published_at: "2026-11-10 10:00:00", updated_at: "2026-11-10 10:00:00",
    }
    const job = featuredMusicAsJob(featured)
    expect(job.id).toBe(featuredMusicJobId("featured-music-1"))
    expect(isFeaturedMusicJobId(job.id)).toBe(true)
    expect(isFeaturedMusicJobId("music-1")).toBe(false)
    expect(job.status).toBe("succeeded")
    expect(job.result_url).toBe(featured.result_url)
    expect(job.duration_seconds).toBe(190)
    expect(musicStyleTags(job)).toEqual(["民谣", "女声", "木吉他"])
  })
})
