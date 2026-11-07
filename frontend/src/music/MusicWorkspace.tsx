import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, ConfigProvider, Input, InputNumber, Modal, Popover, Segmented, Select, Tag, message } from "antd"
import type { TextAreaRef } from "antd/es/input/TextArea"
import { ArrowUpRight, AudioLines, ChevronDown, Clock3, LayoutGrid, List, RefreshCw, Search, SlidersHorizontal, Sparkles } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useStudioTheme } from "../ThemeProvider"
import { MusicJob, createMusicFromVibe, fetchMusicJobs, fetchMusicStatus } from "./api"
import MusicCreateForm from "./MusicCreateForm"
import MusicJobList, { MusicPlayerBar, type MusicPlayerState } from "./MusicJobList"
import MusicLyricsPanel from "./MusicLyricsPanel"
import { MUSIC_MOODS, adjacentMusicJob, filterMusicJobs, musicLyricsPreview, musicStyleTags, musicTempo, type MusicFilter, type MusicView } from "./music-library"
import "./music.css"

const DURATION_OPTIONS = [{ label: "30秒", value: 30 }, { label: "1分钟", value: 60 }, { label: "3分钟", value: 180 }, { label: "3.5分钟", value: 210 }]
type MusicMode = "vibe" | "advanced"

export default function MusicWorkspace({ csrfToken }: { csrfToken: string }) {
  const { mode: themeMode } = useStudioTheme()
  const queryClient = useQueryClient()
  const statusQuery = useQuery({ queryKey: ["music-status"], queryFn: fetchMusicStatus, staleTime: 60_000, retry: false })
  const jobsQuery = useQuery({
    queryKey: ["music-jobs"], queryFn: fetchMusicJobs,
    refetchInterval: (query) => query.state.data?.some((job) => job.status === "queued" || job.status === "running") ? 4000 : 15000,
  })
  const jobs = jobsQuery.data ?? []
  const configured = Boolean(statusQuery.data?.configured) && !statusQuery.isError
  const [mode, setMode] = useState<MusicMode>("vibe")
  const [advancedVisited, setAdvancedVisited] = useState(false)
  const [vibeText, setVibeText] = useState("")
  const [instrumental, setInstrumental] = useState(false)
  const [duration, setDuration] = useState(180)
  const [submitting, setSubmitting] = useState(false)
  const [moodPage, setMoodPage] = useState(0)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [customDuration, setCustomDuration] = useState<number | null>(null)
  const [filter, setFilter] = useState<MusicFilter>("all")
  const [search, setSearch] = useState("")
  const [view, setView] = useState<MusicView>("grid")
  const editorRef = useRef<TextAreaRef>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [lyricsId, setLyricsId] = useState<string | null>(null)
  const selectedJob = jobs.find((job) => job.id === selectedId) ?? jobs.find((job) => job.status === "succeeded") ?? jobs[0] ?? null
  const lyricsPreview = selectedJob ? musicLyricsPreview(selectedJob.lyrics) : []
  const lyricsJob = jobs.find((job) => job.id === lyricsId) ?? null
  const visibleJobs = filterMusicJobs(jobs, filter, search)

  // 详情选择、曲库筛选和音频播放各自独立，避免查看另一首时播放器错配。
  const audioRef = useRef<HTMLAudioElement>(null)
  const audioJobId = useRef<string | null>(null)
  const playRequest = useRef(0)
  const pendingSeek = useRef<number | null>(null)
  const rememberedVolume = useRef(0.7)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [playerId, setPlayerId] = useState<string | null>(null)
  const [progress, setProgress] = useState<MusicPlayerState["progress"]>(null)
  const [playerVisible, setPlayerVisible] = useState(true)
  const [liveLyricsOpen, setLiveLyricsOpen] = useState(false)
  const [volume, setVolume] = useState(0.7)
  const playerJob = playerId ? jobs.find((job) => job.id === playerId) ?? null : jobs.find((job) => job.status === "succeeded" && job.result_url) ?? null
  const player = { playingId, progress }
  const showPlayer = playerVisible && Boolean(playerJob?.result_url)
  const showLiveLyrics = showPlayer && liveLyricsOpen

  useEffect(() => {
    const audio = audioRef.current
    return () => { playRequest.current += 1; audio?.pause() }
  }, [])

  useEffect(() => { if (audioRef.current) audioRef.current.volume = volume }, [volume])

  const updateProgress = () => {
    const audio = audioRef.current
    if (!audio || !audioJobId.current) return
    if (pendingSeek.current !== null && audio.readyState < 1) return
    setProgress({ id: audioJobId.current, current: audio.currentTime || 0, total: Number.isFinite(audio.duration) ? audio.duration : 0 })
  }

  const loadAudio = (job: MusicJob) => {
    const audio = audioRef.current
    if (!audio || !job.result_url || job.status !== "succeeded") return null
    if (audioJobId.current !== job.id) {
      audio.pause()
      setPlayingId(null)
      audioJobId.current = job.id
      pendingSeek.current = null
      audio.src = job.result_url
      setProgress({ id: job.id, current: 0, total: job.duration_seconds || 0 })
    }
    return audio
  }

  const toggle = (job: MusicJob) => {
    const audio = loadAudio(job)
    if (!audio) return
    setPlayerId(job.id)
    setSelectedId(job.id)
    setPlayerVisible(true)
    const request = ++playRequest.current
    if (!audio.paused) { audio.pause(); return }
    setLiveLyricsOpen(true)
    void audio.play().catch((error: unknown) => {
      if (playRequest.current !== request || (error instanceof DOMException && error.name === "AbortError")) return
      setPlayingId(null)
      message.warning("音频播放失败，请尝试下载后本地播放")
    })
  }

  const seek = (job: MusicJob, value: number) => {
    const audio = loadAudio(job)
    if (!audio) return
    setPlayerId(job.id)
    const hasMetadata = audio.readyState >= 1 && Number.isFinite(audio.duration)
    const total = hasMetadata ? audio.duration : job.duration_seconds || 0
    const current = hasMetadata ? Math.min(value, total) : value
    if (audio.readyState >= 1) audio.currentTime = current
    else pendingSeek.current = current
    setProgress({ id: job.id, current, total })
  }

  const closePlayer = () => {
    playRequest.current += 1
    audioRef.current?.pause()
    setPlayingId(null)
    setPlayerVisible(false)
    setLiveLyricsOpen(false)
  }

  const removeFromPlayer = (id: string) => {
    if (audioJobId.current === id) {
      closePlayer()
      audioRef.current?.removeAttribute("src")
      audioRef.current?.load()
      audioJobId.current = null
      pendingSeek.current = null
      setProgress(null)
    }
    if (playerJob?.id === id) { setPlayerId(null); setPlayerVisible(false); setLiveLyricsOpen(false) }
    if (selectedJob?.id === id) setSelectedId(null)
    if (lyricsId === id) setLyricsId(null)
  }

  const changeMode = (value: MusicMode) => {
    setMode(value)
    setSettingsOpen(false)
    if (value === "advanced") setAdvancedVisited(true)
  }

  const submitVibe = async () => {
    const description = vibeText.trim()
    if (!description || description.length > 1000 || submitting || !configured) return
    setSubmitting(true)
    try {
      const job = await createMusicFromVibe(csrfToken, { description, duration_seconds: duration, instrumental })
      setVibeText("")
      setSelectedId(job.id)
      setFilter("all")
      setSearch("")
      message.success("音乐已提交，正在为你创作")
      await queryClient.invalidateQueries({ queryKey: ["music-jobs"] })
    } catch (error) {
      message.error(error instanceof Error ? error.message : "音乐任务提交失败")
    } finally { setSubmitting(false) }
  }

  const showLyrics = (job: MusicJob) => { setSelectedId(job.id); setLyricsId(job.id) }
  const previous = playerJob ? adjacentMusicJob(jobs, playerJob.id, -1) : null
  const next = playerJob ? adjacentMusicJob(jobs, playerJob.id, 1) : null
  const selectedTags = selectedJob ? [...musicStyleTags(selectedJob).slice(0, 2), musicTempo(selectedJob.style), selectedJob.result_format?.toUpperCase()].filter((tag): tag is string => Boolean(tag)) : []

  return <ConfigProvider button={{ autoInsertSpace: false }} theme={{ token: { colorPrimary: themeMode === "dark" ? "#b9a7f7" : "#7751c9" } }}>
    <section className={`studio-music-workspace ${showPlayer ? "has-player" : ""} ${showLiveLyrics ? "has-live-lyrics" : ""}`} aria-label="音乐生成">
      <audio ref={audioRef} preload="metadata" onPlaying={() => setPlayingId(audioJobId.current)} onPause={(event) => { if (event.currentTarget.paused) setPlayingId(null) }} onError={() => setPlayingId(null)} onEnded={() => { setPlayingId(null); updateProgress() }} onTimeUpdate={updateProgress} onSeeked={updateProgress} onLoadedMetadata={() => {
        const audio = audioRef.current
        if (audio && pendingSeek.current !== null) { audio.currentTime = Math.min(pendingSeek.current, audio.duration || pendingSeek.current); pendingSeek.current = null }
        updateProgress()
      }} />
      {statusQuery.isError ? <Alert className="studio-music-banner" type="warning" showIcon title="暂时无法读取音乐服务状态" description="请稍后重试，已完成的歌曲仍可试听。" action={<Button size="small" onClick={() => void statusQuery.refetch()}>重试</Button>} />
        : !statusQuery.isPending && !configured ? <Alert className="studio-music-banner" type="warning" showIcon title="音乐生成服务尚未配置" description="请管理员在「管理设置 → AI 供应商 → 音乐生成」中完成配置。" /> : null}
      <div className="studio-music-hero">
        <h1 className="studio-music-hero-title">把灵感，唱成一首歌</h1>
        <p className="studio-music-hero-sub">描述一种心情、一段故事，或你脑海里的旋律</p>
        <div className="studio-music-panel">
          <div className="studio-music-mode-row">
            <Segmented className="studio-music-tabs" aria-label="音乐创作方式" value={mode} onChange={(value) => changeMode(value as MusicMode)} options={[
              { value: "vibe", label: "灵感生成", icon: <Sparkles size={19} /> },
              { value: "advanced", label: "高级创作", icon: <SlidersHorizontal size={18} /> },
            ]} />
          </div>
          <div className="studio-music-composer" hidden={mode !== "vibe"}>
            <Input.TextArea ref={editorRef} className="studio-music-composer-editor" aria-label="音乐描述" placeholder={MUSIC_MOODS[0].prompt} value={vibeText} onChange={(event) => setVibeText(event.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} variant="borderless" maxLength={1000} disabled={!configured || submitting} onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); void submitVibe() }
            }} />
            <div className="studio-music-composer-toolbar">
              <Select className="studio-music-voice" aria-label="歌曲类型" value={instrumental ? "instrumental" : "vocal"} onChange={(value) => setInstrumental(value === "instrumental")} disabled={!configured || submitting} prefix={<AudioLines size={18} />} suffixIcon={<ChevronDown size={15} />} options={[{ value: "vocal", label: "人声歌曲" }, { value: "instrumental", label: "纯音乐" }]} />
              <Select className="studio-music-duration" aria-label="歌曲时长" value={duration} onChange={setDuration} disabled={!configured || submitting} prefix={<Clock3 size={18} />} suffixIcon={<ChevronDown size={15} />} options={DURATION_OPTIONS.some((option) => option.value === duration) ? DURATION_OPTIONS : [...DURATION_OPTIONS, { label: `${duration}秒`, value: duration }]} />
              <Popover trigger="click" open={settingsOpen} onOpenChange={(open) => { setSettingsOpen(open); if (open) setCustomDuration(duration) }} placement="bottomLeft" classNames={{ root: "studio-music-settings-popover" }} content={<div className="studio-music-settings">
                <label htmlFor="music-custom-duration">自定义时长</label>
                <InputNumber id="music-custom-duration" min={10} max={600} precision={0} value={customDuration} suffix="秒" onChange={setCustomDuration} disabled={submitting} />
                <Button size="small" type="primary" disabled={customDuration === null || customDuration < 10 || customDuration > 600 || submitting} onClick={() => { if (customDuration !== null) setDuration(customDuration); setSettingsOpen(false) }}>应用时长</Button>
                <p>用歌词与风格描述精细控制音乐。</p>
                <Button type="link" onClick={() => changeMode("advanced")}>进入高级创作 <ArrowUpRight size={14} /></Button>
              </div>}>
                <Button className="studio-music-tool" icon={<SlidersHorizontal size={18} />} disabled={!configured || submitting}>更多设置</Button>
              </Popover>
              <span className="studio-music-toolbar-spacer" />
              <span className="studio-music-keyboard-hint">{vibeText.length > 900 ? `${vibeText.length}/1000` : "Ctrl + Enter 快速生成"}</span>
              <Button type="primary" className="studio-music-send" loading={submitting} disabled={!configured || !vibeText.trim()} onClick={() => void submitVibe()}>生成音乐 <ArrowUpRight size={19} /></Button>
            </div>
          </div>
          {advancedVisited && <div className="studio-music-composer studio-music-composer-advanced" hidden={mode !== "advanced"}><MusicCreateForm csrfToken={csrfToken} disabled={!configured} /></div>}
        </div>
      </div>

      <section className="studio-music-inspiration" aria-labelledby="music-moods-heading">
        <div className="studio-music-section-heading"><h2 id="music-moods-heading">从一种氛围开始</h2><Button type="text" icon={<RefreshCw size={17} />} onClick={() => setMoodPage((value) => (value + 1) % 2)}>换一组</Button></div>
        <div className="studio-music-moods">
          {MUSIC_MOODS.slice(moodPage * 4, moodPage * 4 + 4).map((mood) => <Button key={mood.id} type="text" className="studio-music-mood" disabled={submitting} onClick={() => {
            changeMode("vibe"); setVibeText(mood.prompt); setInstrumental(mood.instrumental)
            requestAnimationFrame(() => editorRef.current?.focus({ cursor: "end", preventScroll: true }))
          }}>
            <img src={`/music-art/${mood.image}.webp`} alt="" />
            <span className="studio-music-mood-copy"><strong>{mood.title}</strong><span>{mood.subtitle}</span></span><ArrowUpRight className="studio-music-mood-arrow" size={21} />
          </Button>)}
        </div>
      </section>

      <section className="studio-music-library" aria-labelledby="music-library-heading">
        <div className="studio-music-list-head">
          <h2 id="music-library-heading">我的歌曲 <span className="studio-music-list-count">{jobs.length}</span></h2>
          <Segmented className="studio-music-filters" aria-label="歌曲状态筛选" value={filter} onChange={(value) => setFilter(value as MusicFilter)} options={[
            { label: "全部", value: "all" }, { label: "生成中", value: "active" }, { label: "已完成", value: "succeeded" }, ...(filter === "failed" || jobs.some((job) => job.status === "failed") ? [{ label: "失败", value: "failed" }] : []),
          ]} />
          <div className="studio-music-library-tools">
            <Input className="studio-music-search" aria-label="搜索歌曲" placeholder="搜索歌曲" prefix={<Search size={18} />} allowClear value={search} onChange={(event) => setSearch(event.target.value)} />
            <Segmented className="studio-music-view-switch" aria-label="曲库显示方式" value={view} onChange={(value) => setView(value as MusicView)} options={[{ value: "grid", icon: <LayoutGrid size={20} />, label: <span className="studio-music-sr-only">网格视图</span> }, { value: "list", icon: <List size={21} />, label: <span className="studio-music-sr-only">列表视图</span> }]} />
          </div>
        </div>
        {jobsQuery.isError && <Alert type="error" showIcon title="歌曲列表暂时无法加载" description={jobsQuery.error.message} action={<Button size="small" onClick={() => void jobsQuery.refetch()}>重试</Button>} />}
        <div className={`studio-music-library-layout ${selectedJob && !showLiveLyrics ? "has-selection" : ""}`}>
          <MusicJobList jobs={visibleJobs} csrfToken={csrfToken} loading={jobsQuery.isPending} player={player} selectedId={selectedJob?.id} view={view} emptyText={jobs.length ? "没有符合条件的歌曲，试试其他关键词或筛选" : "还没有作品，从上方的一句灵感开始吧"} onToggle={toggle} onSelect={(job) => setSelectedId(job.id)} onLyrics={showLyrics} onRemoved={removeFromPlayer} />
          {selectedJob && !showLiveLyrics && <aside className="studio-music-listening" aria-label="当前歌曲详情">
            <p className="studio-music-listening-label">{playingId === selectedJob.id ? "正在聆听" : "歌曲详情"}</p>
            <h3>{selectedJob.title || "未命名歌曲"}</h3>
            <div className="studio-music-listening-description">{lyricsPreview.length ? lyricsPreview.map((line, index) => <p key={index}>{line}</p>) : <p>{selectedJob.status === "queued" ? "已加入创作队列。" : selectedJob.status === "running" ? "正在为你创作音乐。" : selectedJob.status === "failed" ? "这次生成未完成。" : "纯音乐作品，没有歌词。"}</p>}</div>
            <div className="studio-music-listening-tags">{selectedTags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</div>
            <Button type="link" className="studio-music-lyrics-link" onClick={() => showLyrics(selectedJob)}>{lyricsPreview.length ? "查看歌词" : "查看歌曲详情"}<ArrowUpRight size={16} /></Button>
          </aside>}
        </div>
      </section>

      {showPlayer && playerJob && <MusicPlayerBar job={playerJob} player={player} volume={volume} previous={Boolean(previous)} next={Boolean(next)} lyricsOpen={showLiveLyrics} onLyrics={() => setLiveLyricsOpen((open) => !open)} onToggle={toggle} onSeek={seek} onVolume={(value) => { if (value > 0) rememberedVolume.current = value; setVolume(value) }} onMute={() => setVolume((value) => value === 0 ? rememberedVolume.current : 0)} onPrevious={() => { if (previous) toggle(previous) }} onNext={() => { if (next) toggle(next) }} onClose={closePlayer} />}
      {showLiveLyrics && playerJob && <MusicLyricsPanel key={playerJob.id} job={playerJob} csrfToken={csrfToken} currentTime={progress?.id === playerJob.id ? progress.current : 0} playing={playingId === playerJob.id} onSeek={(seconds) => seek(playerJob, seconds)} onClose={() => {
        setLiveLyricsOpen(false)
        document.getElementById("music-player-lyrics-toggle")?.focus()
      }} />}
      <Modal open={Boolean(lyricsJob)} onCancel={() => setLyricsId(null)} title={lyricsJob?.title || "歌曲详情"} footer={null} width={640} className="studio-music-lyrics-modal" destroyOnHidden>
        {lyricsJob && <><div className="studio-music-lyrics-tags">{musicStyleTags(lyricsJob).map((tag) => <Tag key={tag}>{tag}</Tag>)}</div><pre className="studio-music-lyrics">{musicLyricsPreview(lyricsJob.lyrics).length ? lyricsJob.lyrics.trim() : "这是一首纯音乐，没有歌词。"}</pre>{lyricsJob.cover_url && <Button type="link" className="studio-music-original-cover" href={lyricsJob.cover_url} target="_blank" rel="noreferrer">查看原封面 <ArrowUpRight size={15} /></Button>}<details className="studio-music-full-style"><summary>完整音乐风格</summary><p>{lyricsJob.style}</p></details></>}
      </Modal>
    </section>
  </ConfigProvider>
}
