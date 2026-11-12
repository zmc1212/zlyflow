import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, ConfigProvider, Input, InputNumber, Modal, Segmented, Tag, message } from "antd"
import { ArrowUpRight, EyeOff, LayoutGrid, List, MessagesSquare, RefreshCw, Search, Sparkles } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { useStudioTheme } from "../ThemeProvider"
import { musicChatPath, parseMusicPath } from "../paths"
import type { User } from "../api"
import { FeaturedMusic, MusicJob, createMusicChat, fetchFeaturedMusic, fetchMusicChat, fetchMusicJobs, fetchMusicStatus, publishFeaturedMusic, unpublishFeaturedMusic } from "./api"
import FeaturedMusicGrid from "./FeaturedMusicGrid"
import MusicComposer from "./MusicComposer"
import MusicConversation from "./MusicConversation"
import MusicJobList, { MusicArtwork, MusicPlayerBar, type MusicPlayerState } from "./MusicJobList"
import MusicLyricsPanel from "./MusicLyricsPanel"
import { MUSIC_MOODS, adjacentMusicJob, buildMusicVersionLabels, featuredMusicAsJob, filterMusicJobs, isFeaturedMusicJobId, musicAdminViewingOthers, musicCanManage, musicCanRetry, musicLyricsPreview, musicReadOnlyScope, musicScopedUserId, musicStyleTags, musicTempo, type MusicFilter, type MusicView } from "./music-library"
import "./music.css"

type MusicViewTab = "chat" | "library" | "featured"

/** 音乐工作台：整窗对话式布局（左栏对话列表在 App shell 内，本组件渲染主区两页签）。 */
export default function MusicWorkspace({ csrfToken, user, adminUserFilter = "all", adminUserName = "" }: { csrfToken: string; user: User | null; adminUserFilter?: string; adminUserName?: string }) {
  const { mode: themeMode } = useStudioTheme()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { chatId } = parseMusicPath(location.pathname)
  // 管理员可切换查看其他账号的音乐数据；普通账号始终只看本人。
  const scopedUserId = musicScopedUserId(user?.role, adminUserFilter, user?.id)
  const readOnlyScope = musicReadOnlyScope(user?.role, adminUserFilter, user?.id)
  const adminViewingOthers = musicAdminViewingOthers(user?.role, adminUserFilter, user?.id)
  const viewParam = searchParams.get("view")
  const view: MusicViewTab = viewParam === "library" || viewParam === "featured" ? viewParam : "chat"
  const setView = (next: MusicViewTab) => {
    const params = new URLSearchParams(searchParams)
    if (next === "chat") params.delete("view")
    else params.set("view", next)
    setSearchParams(params)
  }

  const statusQuery = useQuery({ queryKey: ["music-status"], queryFn: fetchMusicStatus, staleTime: 60_000, retry: false })
  const jobsQuery = useQuery({
    queryKey: ["music-jobs", scopedUserId ?? "mine"], queryFn: () => fetchMusicJobs(scopedUserId),
    refetchInterval: (query) => query.state.data?.some((job) => job.status === "queued" || job.status === "running") ? 4000 : 15000,
  })
  const jobs = jobsQuery.data ?? []
  const isAdmin = user?.role === "admin" || user?.role === "super_admin"
  // 精选音乐：管理员发布后全员可见；普通账号只读取展示快照。
  const featuredQuery = useQuery({ queryKey: ["music-featured"], queryFn: fetchFeaturedMusic, staleTime: 30_000, retry: false })
  const featuredSongs = useMemo(() => featuredQuery.data ?? [], [featuredQuery.data])
  const featuredJobs = useMemo(() => featuredSongs.map(featuredMusicAsJob), [featuredSongs])
  const featuredByJobId = useMemo(() => new Map(featuredSongs.map((song) => [song.job_id, song])), [featuredSongs])
  const configured = Boolean(statusQuery.data?.configured) && !statusQuery.isError
  const versionLabels = useMemo(() => buildMusicVersionLabels(jobs), [jobs])

  // 对话详情（锚点信息供 composer 提示；与 MusicConversation 共享同一 queryKey 缓存）
  const chatDetailQuery = useQuery({
    queryKey: ["music-chat", chatId], queryFn: () => fetchMusicChat(chatId as string),
    enabled: Boolean(chatId),
  })
  const anchorJob = chatDetailQuery.data?.anchor_job ?? null
  // 「全部用户」视图下打开归属他人的对话时同样按只读处理。
  const chatReadOnly = readOnlyScope || Boolean(user?.id && chatDetailQuery.data && chatDetailQuery.data.owner_user_id !== user.id)

  // composer 状态
  const [draft, setDraft] = useState("")
  const [sending, setSending] = useState(false)
  const [streamingReply, setStreamingReply] = useState<string | null>(null)

  // 切换对话时清掉上一段流式残留
  useEffect(() => { setStreamingReply(null) }, [chatId])

  // 曲库状态
  const [filter, setFilter] = useState<MusicFilter>("all")
  const [search, setSearch] = useState("")
  const [viewMode, setViewMode] = useState<MusicView>("grid")
  const [moodPage, setMoodPage] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [lyricsId, setLyricsId] = useState<string | null>(null)
  // 精选发布草稿：从歌曲卡片菜单进入，仅管理员可见。
  const [featuredDraft, setFeaturedDraft] = useState<{ job: MusicJob; song?: FeaturedMusic; title: string; summary: string; coverUrl: string; sortOrder: number } | null>(null)
  const [publishingFeatured, setPublishingFeatured] = useState(false)
  const [modal, modalContext] = Modal.useModal()
  const selectedJob = jobs.find((job) => job.id === selectedId) ?? jobs.find((job) => job.status === "succeeded") ?? jobs[0] ?? null
  const lyricsPreview = selectedJob ? musicLyricsPreview(selectedJob.lyrics) : []
  const lyricsJob = [...jobs, ...featuredJobs].find((job) => job.id === lyricsId) ?? null
  const visibleJobs = filterMusicJobs(jobs, filter, search)
  const recentJobs = useMemo(() => jobs.slice(0, 8), [jobs])

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
  const playerJob = playerId ? [...jobs, ...featuredJobs].find((job) => job.id === playerId) ?? jobs.find((job) => job.status === "succeeded" && job.result_url) ?? null : jobs.find((job) => job.status === "succeeded" && job.result_url) ?? null
  const playerQueue = playerJob && isFeaturedMusicJobId(playerJob.id) ? featuredJobs : jobs
  const player = { playingId, progress }
  const showPlayer = playerVisible && Boolean(playerJob?.result_url)
  const showLiveLyrics = showPlayer && liveLyricsOpen && !isFeaturedMusicJobId(playerJob?.id)

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
    const featured = isFeaturedMusicJobId(job.id)
    setPlayerId(job.id)
    if (!featured) setSelectedId(job.id)
    setPlayerVisible(true)
    const request = ++playRequest.current
    if (!audio.paused) { audio.pause(); return }
    // 精选歌曲没有可对齐的原任务，不打开逐行歌词面板；歌词在详情弹窗中查看。
    setLiveLyricsOpen(!featured)
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

  const showLyrics = (job: MusicJob) => { if (!isFeaturedMusicJobId(job.id)) setSelectedId(job.id); setLyricsId(job.id) }

  const openChatById = (id: string) => {
    setView("chat")
    navigate(musicChatPath(id))
  }

  const startChat = async (anchorJob?: MusicJob | null) => {
    try {
      // 同一锚点已有对话时直接续聊，避免反复点入口堆出空对话
      const anchorId = anchorJob?.id ?? null
      if (anchorId) {
        const existing = jobs.find((job) => job.id === anchorId)
        if (existing?.chat_id) { openChatById(existing.chat_id); return }
      }
      const chat = await createMusicChat(csrfToken, anchorId)
      await queryClient.invalidateQueries({ queryKey: ["music-chats"] })
      openChatById(chat.id)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "对话创建失败")
    }
  }

  const openJobChat = (job: MusicJob) => {
    if (job.chat_id) openChatById(job.chat_id)
    else void startChat(job)
  }

  const previous = playerJob ? adjacentMusicJob(playerQueue, playerJob.id, -1) : null
  const next = playerJob ? adjacentMusicJob(playerQueue, playerJob.id, 1) : null
  const selectedTags = selectedJob ? [...musicStyleTags(selectedJob).slice(0, 2), musicTempo(selectedJob.style), selectedJob.result_format?.toUpperCase()].filter((tag): tag is string => Boolean(tag)) : []
  const composerDisabled = sending || !configured || readOnlyScope
  const canManageJob = (job: MusicJob) => musicCanManage(job.owner_user_id, user?.id, readOnlyScope)
  // 管理员跨账号只放开失败任务的重试；删除等仍由 canManageJob 限本人。
  const canRetryJob = (job: MusicJob) => musicCanRetry(job, user?.id, readOnlyScope, adminViewingOthers)

  const openPublishFeatured = (job: MusicJob) => {
    if (!isAdmin) return
    const song = featuredByJobId.get(job.id)
    setFeaturedDraft({
      job,
      song,
      title: song?.title || job.title || "",
      summary: song?.summary || "",
      coverUrl: song?.cover_url || job.cover_url || "",
      sortOrder: song?.sort_order ?? 0,
    })
  }

  const submitFeatured = async () => {
    if (!featuredDraft) return
    const title = featuredDraft.title.trim()
    if (!title) { message.warning("请填写精选标题"); return }
    setPublishingFeatured(true)
    try {
      await publishFeaturedMusic(csrfToken, {
        job_id: featuredDraft.job.id,
        title,
        summary: featuredDraft.summary.trim(),
        cover_url: featuredDraft.coverUrl.trim(),
        sort_order: featuredDraft.sortOrder,
      })
      await queryClient.invalidateQueries({ queryKey: ["music-featured"] })
      setFeaturedDraft(null)
      message.success(featuredDraft.song ? "精选音乐已更新" : "已发布为精选音乐")
    } catch (error) { message.error(error instanceof Error ? error.message : "发布精选音乐失败") }
    finally { setPublishingFeatured(false) }
  }

  const confirmUnpublishFeatured = (song: FeaturedMusic) => {
    modal.confirm({
      title: `取消精选「${song.title || "未命名歌曲"}」？`,
      content: "取消后所有成员将不再在「精选音乐」里看到它，歌曲本身不受影响。",
      okText: "取消精选", cancelText: "保留", okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await unpublishFeaturedMusic(csrfToken, song.id)
          await queryClient.invalidateQueries({ queryKey: ["music-featured"] })
          const playerIdForSong = `featured:${song.id}`
          if (playerId === playerIdForSong) closePlayer()
          if (lyricsId === playerIdForSong) setLyricsId(null)
          message.success("已取消精选")
        } catch (error) { message.error(error instanceof Error ? error.message : "取消精选失败"); throw error }
      },
    })
  }

  return <ConfigProvider button={{ autoInsertSpace: false }} theme={{ token: { colorPrimary: themeMode === "dark" ? "#b9a7f7" : "#7751c9" } }}>
    <section className={`studio-music-workspace ${showPlayer ? "has-player" : ""} ${showLiveLyrics ? "has-live-lyrics" : ""}`} aria-label="音乐生成">
      <audio ref={audioRef} preload="metadata" onPlaying={() => setPlayingId(audioJobId.current)} onPause={(event) => { if (event.currentTarget.paused) setPlayingId(null) }} onError={() => setPlayingId(null)} onEnded={() => { setPlayingId(null); updateProgress() }} onTimeUpdate={updateProgress} onSeeked={updateProgress} onLoadedMetadata={() => {
        const audio = audioRef.current
        if (audio && pendingSeek.current !== null) { audio.currentTime = Math.min(pendingSeek.current, audio.duration || pendingSeek.current); pendingSeek.current = null }
        updateProgress()
      }} />
      {statusQuery.isError ? <Alert className="studio-music-banner" type="warning" showIcon title="暂时无法读取音乐服务状态" description="请稍后重试，已完成的歌曲仍可试听。" action={<Button size="small" onClick={() => void statusQuery.refetch()}>重试</Button>} />
        : !statusQuery.isPending && !configured ? <Alert className="studio-music-banner" type="warning" showIcon title="音乐生成服务尚未配置" description="请管理员在「管理设置 → AI 供应商 → 音乐生成」中完成配置。" /> : null}

      <div className="studio-music-view-tabs">
        <Segmented aria-label="音乐页视图" value={view} onChange={(value) => setView(value as MusicViewTab)} options={[
          { value: "chat", label: "对话创作" },
          { value: "library", label: "我的歌曲" },
          { value: "featured", label: "精选音乐" },
        ]} />
      </div>

      {view === "chat" ? (
        chatId ? <>
          <MusicConversation readOnly={readOnlyScope} canRetry={canRetryJob} currentUserId={user?.id} chatId={chatId} jobs={jobs} csrfToken={csrfToken} isSending={sending} streamingReply={streamingReply} playingId={playingId} onPlayJob={toggle} onSelectJob={(job) => setSelectedId(job.id)} />
          {chatReadOnly
            ? <p className="studio-music-view-note" role="note">正在只读查看{readOnlyScope && adminUserName ? ` ${adminUserName} ` : "该用户的"}对话，切换到本人账号或可管理的对话即可继续创作</p>
            : <MusicComposer csrfToken={csrfToken} chatId={chatId} draft={draft} onDraftChange={setDraft} disabled={composerDisabled} configured={configured} anchorJob={anchorJob} inline={false} onSendingChange={setSending} onStreamingReply={setStreamingReply} onOpenChat={openChatById} />}
        </> : readOnlyScope ? <>
          <div className="studio-music-home-head">
            <h1 className="studio-music-home-title">{adminUserName || "该用户"} 的音乐</h1>
            <p className="studio-music-home-sub">正在只读查看 {adminUserName || "该用户"} 的歌曲与对话，切换到「全部用户」或本人即可开始创作</p>
          </div>
          {recentJobs.length > 0 && <section className="studio-music-recent" aria-labelledby="music-recent-heading">
            <div className="studio-music-section-heading">
              <h2 id="music-recent-heading">最近歌曲</h2>
              <Button type="link" onClick={() => setView("library")}>全部歌曲 <ArrowUpRight size={15} /></Button>
            </div>
            <MusicJobList jobs={recentJobs} csrfToken={csrfToken} player={player} selectedId={selectedJob?.id} view="grid" emptyText="" featuredByJobId={featuredByJobId} isAdmin={isAdmin} onPublishFeatured={openPublishFeatured} onUnpublishFeatured={confirmUnpublishFeatured} versionLabels={versionLabels} canManage={canManageJob} canRetry={canRetryJob} onChat={openJobChat} onToggle={toggle} onSelect={(job) => setSelectedId(job.id)} onLyrics={showLyrics} onRemoved={removeFromPlayer} />
          </section>}
        </> : <>
          <div className="studio-music-home-head">
            <h1 className="studio-music-home-title">今天，想唱点什么？</h1>
            <p className="studio-music-home-sub">一句话描述想法，和助手在一轮轮对话里把歌磨出来</p>
          </div>
          <MusicComposer csrfToken={csrfToken} chatId={null} draft={draft} onDraftChange={setDraft} disabled={composerDisabled} configured={configured} anchorJob={null} inline onSendingChange={setSending} onStreamingReply={setStreamingReply} onOpenChat={openChatById} />
          <section className="studio-music-inspiration" aria-labelledby="music-moods-heading">
            <div className="studio-music-section-heading"><h2 id="music-moods-heading">从一种氛围开始</h2><Button type="text" icon={<RefreshCw size={17} />} onClick={() => setMoodPage((value) => (value + 1) % 2)}>换一组</Button></div>
            <div className="studio-music-moods">
              {MUSIC_MOODS.slice(moodPage * 4, moodPage * 4 + 4).map((mood) => <Button key={mood.id} type="text" className="studio-music-mood" disabled={composerDisabled} onClick={() => setDraft(mood.prompt)}>
                <img src={`/music-art/${mood.image}.webp`} alt="" />
                <span className="studio-music-mood-copy"><strong>{mood.title}</strong><span>{mood.subtitle}</span></span><ArrowUpRight className="studio-music-mood-arrow" size={21} />
              </Button>)}
            </div>
          </section>
          {recentJobs.length > 0 && <section className="studio-music-recent" aria-labelledby="music-recent-heading">
            <div className="studio-music-section-heading">
              <h2 id="music-recent-heading">最近歌曲</h2>
              <Button type="link" onClick={() => setView("library")}>全部歌曲 <ArrowUpRight size={15} /></Button>
            </div>
            <MusicJobList jobs={recentJobs} csrfToken={csrfToken} player={player} selectedId={selectedJob?.id} view="grid" emptyText="" featuredByJobId={featuredByJobId} isAdmin={isAdmin} onPublishFeatured={openPublishFeatured} onUnpublishFeatured={confirmUnpublishFeatured} versionLabels={versionLabels} canManage={canManageJob} canRetry={canRetryJob} onChat={openJobChat} onToggle={toggle} onSelect={(job) => setSelectedId(job.id)} onLyrics={showLyrics} onRemoved={removeFromPlayer} />
          </section>}
        </>
      ) : view === "featured" ? (
        <section className="studio-music-library studio-featured-music" aria-labelledby="featured-music-heading">
          <div className="studio-music-list-head">
            <h2 id="featured-music-heading">精选音乐 <span className="studio-music-list-count">{featuredSongs.length}</span></h2>
            <span className="studio-featured-music-note">{isAdmin ? "在「我的歌曲」卡片菜单里发布或更新精选" : "管理员精选，全员可试听"}</span>
          </div>
          {featuredQuery.isError && <Alert type="error" showIcon title="精选音乐暂时无法加载" description={featuredQuery.error.message} action={<Button size="small" onClick={() => void featuredQuery.refetch()}>重试</Button>} />}
          <FeaturedMusicGrid songs={featuredSongs} loading={featuredQuery.isPending} player={player} isAdmin={isAdmin} onToggle={(song) => toggle(featuredMusicAsJob(song))} onLyrics={(song) => showLyrics(featuredMusicAsJob(song))} onUnpublish={confirmUnpublishFeatured} />
        </section>
      ) : (
        <section className="studio-music-library" aria-labelledby="music-library-heading">
          <div className="studio-music-list-head">
            <h2 id="music-library-heading">{readOnlyScope ? `${adminUserName || "该用户"} 的歌曲` : "我的歌曲"} <span className="studio-music-list-count">{jobs.length}</span></h2>
            <Segmented className="studio-music-filters" aria-label="歌曲状态筛选" value={filter} onChange={(value) => setFilter(value as MusicFilter)} options={[
              { label: "全部", value: "all" }, { label: "生成中", value: "active" }, { label: "已完成", value: "succeeded" }, ...(filter === "failed" || jobs.some((job) => job.status === "failed") ? [{ label: "失败", value: "failed" }] : []),
            ]} />
            <div className="studio-music-library-tools">
              <Input className="studio-music-search" aria-label="搜索歌曲" placeholder="搜索歌曲" prefix={<Search size={18} />} allowClear value={search} onChange={(event) => setSearch(event.target.value)} />
              <Segmented className="studio-music-view-switch" aria-label="曲库显示方式" value={viewMode} onChange={(value) => setViewMode(value as MusicView)} options={[{ value: "grid", icon: <LayoutGrid size={20} />, label: <span className="studio-music-sr-only">网格视图</span> }, { value: "list", icon: <List size={21} />, label: <span className="studio-music-sr-only">列表视图</span> }]} />
            </div>
          </div>
          {readOnlyScope && <p className="studio-music-view-note" role="note">正在只读查看 {adminUserName || "该用户"} 的歌曲，切换到「全部用户」或本人即可继续创作</p>}
          {jobsQuery.isError && <Alert type="error" showIcon title="歌曲列表暂时无法加载" description={jobsQuery.error.message} action={<Button size="small" onClick={() => void jobsQuery.refetch()}>重试</Button>} />}
          <div className={`studio-music-library-layout ${selectedJob && !showLiveLyrics ? "has-selection" : ""}`}>
            <MusicJobList jobs={visibleJobs} csrfToken={csrfToken} loading={jobsQuery.isPending} player={player} selectedId={selectedJob?.id} view={viewMode} emptyText={jobs.length ? "没有符合条件的歌曲，试试其他关键词或筛选" : readOnlyScope ? "该用户还没有作品" : "还没有作品，从对话创作开始吧"} featuredByJobId={featuredByJobId} isAdmin={isAdmin} onPublishFeatured={openPublishFeatured} onUnpublishFeatured={confirmUnpublishFeatured} versionLabels={versionLabels} canManage={canManageJob} canRetry={canRetryJob} onChat={openJobChat} onToggle={toggle} onSelect={(job) => setSelectedId(job.id)} onLyrics={showLyrics} onRemoved={removeFromPlayer} />
            {selectedJob && !showLiveLyrics && <aside className="studio-music-listening" aria-label="当前歌曲详情">
              <p className="studio-music-listening-label">{playingId === selectedJob.id ? "正在聆听" : "歌曲详情"}</p>
              <h3>{selectedJob.title || "未命名歌曲"}</h3>
              <div className="studio-music-listening-description">{lyricsPreview.length ? lyricsPreview.map((line, index) => <p key={index}>{line}</p>) : <p>{selectedJob.status === "queued" ? "已加入创作队列。" : selectedJob.status === "running" ? "正在为你创作音乐。" : selectedJob.status === "failed" ? "这次生成未完成。" : "纯音乐作品，没有歌词。"}</p>}</div>
              <div className="studio-music-listening-tags">{selectedTags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</div>
              <div className="studio-music-listening-links">
                <Button type="link" className="studio-music-lyrics-link" onClick={() => showLyrics(selectedJob)}>{lyricsPreview.length ? "查看歌词" : "查看歌曲详情"}<ArrowUpRight size={16} /></Button>
                {(selectedJob.chat_id || canManageJob(selectedJob)) && <Button type="link" className="studio-music-lyrics-link" onClick={() => openJobChat(selectedJob)}><MessagesSquare size={15} />{selectedJob.chat_id ? "查看对话" : "对话修改"}</Button>}
              </div>
            </aside>}
          </div>
        </section>
      )}

      {showPlayer && playerJob && <MusicPlayerBar job={playerJob} player={player} volume={volume} previous={Boolean(previous)} next={Boolean(next)} lyricsOpen={showLiveLyrics} lyricsAvailable={!isFeaturedMusicJobId(playerJob.id)} onLyrics={() => setLiveLyricsOpen((open) => !open)} onToggle={toggle} onSeek={seek} onVolume={(value) => { if (value > 0) rememberedVolume.current = value; setVolume(value) }} onMute={() => setVolume((value) => value === 0 ? rememberedVolume.current : 0)} onPrevious={() => { if (previous) toggle(previous) }} onNext={() => { if (next) toggle(next) }} onClose={closePlayer} />}
      {showLiveLyrics && playerJob && <MusicLyricsPanel readOnly={readOnlyScope || !canManageJob(playerJob)} key={playerJob.id} job={playerJob} csrfToken={csrfToken} currentTime={progress?.id === playerJob.id ? progress.current : 0} playing={playingId === playerJob.id} onSeek={(seconds) => seek(playerJob, seconds)} onClose={() => {
        setLiveLyricsOpen(false)
        document.getElementById("music-player-lyrics-toggle")?.focus()
      }} />}
      <Modal open={Boolean(lyricsJob)} onCancel={() => setLyricsId(null)} title={lyricsJob?.title || "歌曲详情"} footer={null} width={640} className="studio-music-lyrics-modal" destroyOnHidden>
        {lyricsJob && <><div className="studio-music-lyrics-tags">{musicStyleTags(lyricsJob).map((tag) => <Tag key={tag}>{tag}</Tag>)}</div><pre className="studio-music-lyrics">{musicLyricsPreview(lyricsJob.lyrics).length ? lyricsJob.lyrics.trim() : "这是一首纯音乐，没有歌词。"}</pre>{lyricsJob.cover_url && <Button type="link" className="studio-music-original-cover" href={lyricsJob.cover_url} target="_blank" rel="noreferrer">查看原封面 <ArrowUpRight size={15} /></Button>}<details className="studio-music-full-style"><summary>完整音乐风格</summary><p>{lyricsJob.style}</p></details></>}
      </Modal>
      {modalContext}
      <Modal
        open={Boolean(featuredDraft)}
        title={featuredDraft?.song ? "更新精选音乐" : "发布为精选音乐"}
        okText={featuredDraft?.song ? "保存更新" : "发布精选"}
        cancelText="取消"
        confirmLoading={publishingFeatured}
        onCancel={() => { if (!publishingFeatured) setFeaturedDraft(null) }}
        onOk={() => void submitFeatured()}
        destroyOnHidden
        className="studio-featured-music-modal"
      >
        {featuredDraft && <div className="studio-featured-music-form">
          <div className="studio-featured-music-source">
            <MusicArtwork job={featuredDraft.job} className="studio-featured-music-source-cover" decorative />
            <div>
              <strong>{featuredDraft.job.title || "未命名歌曲"}</strong>
              <span>{featuredDraft.song ? "已发布，保存后用当前歌曲信息重新生成快照" : "发布后所有成员可在「精选音乐」里试听"}</span>
            </div>
          </div>
          <label>
            <span>精选标题</span>
            <Input maxLength={120} value={featuredDraft.title} placeholder="展示在精选音乐里的标题" onChange={(event) => setFeaturedDraft((current) => current && { ...current, title: event.target.value })} />
          </label>
          <label>
            <span>一句推荐语</span>
            <Input.TextArea rows={2} maxLength={280} showCount value={featuredDraft.summary} placeholder="留空时精选卡片显示「管理员精选」" onChange={(event) => setFeaturedDraft((current) => current && { ...current, summary: event.target.value })} />
          </label>
          <label>
            <span>封面地址</span>
            <Input value={featuredDraft.coverUrl} placeholder="留空时使用歌曲封面" onChange={(event) => setFeaturedDraft((current) => current && { ...current, coverUrl: event.target.value })} />
          </label>
          <label>
            <span>排序（数字越小越靠前）</span>
            <InputNumber min={0} max={999} precision={0} value={featuredDraft.sortOrder} onChange={(value) => setFeaturedDraft((current) => current && { ...current, sortOrder: typeof value === "number" ? value : current.sortOrder })} />
          </label>
          <Alert type="info" showIcon title="发布时会冻结当前歌曲的标题、风格、歌词、音频与封面；之后删除或修改原歌曲不影响已发布内容，需要同步时再次发布即可。" />
        </div>}
      </Modal>
    </section>
  </ConfigProvider>
}
