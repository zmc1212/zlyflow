import { describe, expect, it } from "vitest"
import { formatMusicDuration, type MusicJob } from "./api"
import { adjacentMusicJob, filterMusicJobs, musicArtworkUrl, musicLyricCursor, musicLyricsPreview, musicStyleTags, musicTempo } from "./music-library"

const song = (patch: Partial<MusicJob> = {}): MusicJob => ({
  id: "one", owner_user_id: "user", title: "麦地", style: "folk, male vocal, acoustic guitar, 82 BPM", lyrics: "[Verse 1]\n风吹过田野", status: "succeeded", progress: 100, params: {},
  result_url: "/one.flac", result_format: "flac", cover_url: "/original.jpg", duration_seconds: 182, remote_job_id: null, remote_song_id: null, error_message: null,
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
})
