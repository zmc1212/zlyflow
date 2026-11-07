import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, Empty, Spin } from "antd"
import { AudioLines, LocateFixed, PanelRightClose } from "lucide-react"
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { alignMusicLyrics, fetchMusicLyrics, type MusicJob } from "./api"
import { MusicArtwork, MusicEqualizer } from "./MusicJobList"
import { musicLyricCursor, musicLyricText, musicStyleTags } from "./music-library"

export default function MusicLyricsPanel({ job, csrfToken, currentTime, playing, onSeek, onClose }: {
  job: MusicJob
  csrfToken: string
  currentTime: number
  playing: boolean
  onSeek: (seconds: number) => void
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const queryKey = ["music-lyrics", job.id]
  const text = useMemo(() => musicLyricText(job.lyrics), [job.lyrics])
  const lyrics = useQuery({
    queryKey,
    queryFn: ({ signal }) => fetchMusicLyrics(job.id, signal),
    enabled: text.length > 0,
    staleTime: 10_000,
    refetchInterval: (query) => query.state.data?.status === "aligning" ? 2000 : false,
    retry: false,
  })
  const { mutate: align, isPending: requesting, isIdle: mayAutoAlign, error: requestError } = useMutation({
    mutationFn: () => alignMusicLyrics(csrfToken, job.id),
    onSuccess: (result) => queryClient.setQueryData(queryKey, result),
  })
  const status = lyrics.data?.status
  useEffect(() => {
    if (status === "idle" && mayAutoAlign) align()
  }, [align, mayAutoAlign, status])

  const timedLines = status === "ready" ? lyrics.data?.lines : undefined
  const lines = timedLines ?? text.map((line) => ({ text: line, start_seconds: null, end_seconds: null }))
  const cursor = timedLines ? musicLyricCursor(timedLines, currentTime) : -1
  const end = cursor >= 0 ? lines[cursor].end_seconds : null
  const activeIndex = end === null || currentTime < end ? cursor : -1
  const scroll = useRef<HTMLDivElement>(null)
  const anchor = useRef<HTMLLIElement>(null)
  const [following, setFollowing] = useState(true)
  useLayoutEffect(() => {
    const container = scroll.current
    if (!following || !container) return
    const line = anchor.current?.getBoundingClientRect()
    const top = line ? container.scrollTop + line.top - container.getBoundingClientRect().top - (container.clientHeight - line.height) / 2 : 0
    container.scrollTo({ top, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" })
  }, [cursor, following, timedLines])

  const pending = !lyrics.isError && !requestError && (requesting || status === "aligning" || status === "idle" || lyrics.isPending)
  const error = (lyrics.isError ? lyrics.error.message : null) ?? requestError?.message ?? lyrics.data?.message

  return <aside id="music-live-lyrics" className={"studio-music-live-lyrics" + (playing ? " is-playing" : "")} aria-labelledby="music-live-lyrics-title" onKeyDown={(event) => {
    if (event.key === "Escape" && !event.defaultPrevented) { event.stopPropagation(); onClose() }
  }}>
    <MusicArtwork job={job} className="studio-music-lyric-atmosphere" decorative />
    <header className="studio-music-lyric-heading">
      <h2 id="music-live-lyrics-title">歌词</h2>
      {timedLines && <Button type="text" className="studio-music-lyric-follow" icon={following ? <AudioLines size={17} /> : <LocateFixed size={16} />} onClick={() => setFollowing(!following)} aria-label={following ? "暂停跟随歌词" : "回到当前歌词"}>{following ? "跟随播放" : "回到当前"}</Button>}
      <Button type="text" className="studio-music-lyric-close" icon={<PanelRightClose size={19} />} onClick={onClose} aria-label="收起歌词" />
    </header>
    <div className="studio-music-lyric-track">
      <MusicArtwork job={job} className="studio-music-lyric-cover" decorative />
      <div className="studio-music-lyric-track-copy">
        <h3 title={job.title}>{job.title || "未命名歌曲"}</h3>
        <p>{musicStyleTags(job).slice(0, 2).join(" · ")}</p>
      </div>
    </div>
    {text.length === 0 ? <div className="studio-music-lyric-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这是一首纯音乐" /></div> : <>
      <div ref={scroll} className={"studio-music-lyric-scroll" + (timedLines ? " has-timing" : "")} tabIndex={0} aria-label={timedLines ? "同步歌词" : "原歌词"}
        onWheel={() => setFollowing(false)} onTouchMove={() => setFollowing(false)}
        onPointerDown={(event) => {
          const container = event.currentTarget
          if (event.clientX >= container.getBoundingClientRect().left + container.clientWidth) setFollowing(false)
        }}
        onKeyDown={(event) => {
          if (event.target === event.currentTarget && ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) setFollowing(false)
        }}>
        <ol className="studio-music-lyric-lines">
          {lines.map((line, index) => {
            const active = index === activeIndex
            const start = line.start_seconds
            return <li key={index} ref={index === cursor ? anchor : undefined} className={active ? "is-current" : ""} aria-current={active || undefined}>
              {active && <MusicEqualizer />}
              {start === null ? <span className="studio-music-lyric-line">{line.text}</span>
                : <Button type="text" className="studio-music-lyric-line" onClick={() => { setFollowing(true); onSeek(start) }}>{line.text}</Button>}
            </li>
          })}
        </ol>
      </div>
      <footer className="studio-music-lyric-footer">
        {pending ? <span role="status"><Spin size="small" />正在对齐歌词</span>
          : timedLines ? <span>点击已对齐的歌词可跳到对应位置</span>
          : <><span>{error}</span><Button type="link" size="small" onClick={() => { if (lyrics.isError) void lyrics.refetch(); else align() }}>重新对齐</Button></>}
      </footer>
    </>}
  </aside>
}
