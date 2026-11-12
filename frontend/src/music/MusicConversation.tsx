import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, Spin, Tag, message } from "antd"
import { Pause, Play, RotateCcw } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import type { MusicChatDetail, MusicChatMessage, MusicJob } from "./api"
import { formatMusicDuration, generateMusicChatProposal, retryMusicJob } from "./api"
import { fetchMusicChat } from "./api"
import { musicArtworkUrl, musicStyleTags } from "./music-library"
import { musicChatPath } from "../paths"

type StreamMessage = MusicChatMessage & { pending?: boolean }

const STATUS_TAGS: Record<MusicJob["status"], { color: string; label: string }> = {
  queued: { color: "default", label: "排队中" }, running: { color: "processing", label: "生成中" },
  succeeded: { color: "success", label: "已完成" }, failed: { color: "error", label: "生成失败" },
}

/** 音乐对话主区流：用户消息/助手回复/提案卡/歌曲结果，承接原 Drawer 面板逻辑并放宽到主区宽度。 */
export default function MusicConversation({ chatId, jobs, csrfToken, currentUserId, isSending, streamingReply, playingId, onPlayJob, onSelectJob, readOnly = false, canRetry }: {
  chatId: string
  jobs: MusicJob[]
  csrfToken: string
  /** 当前登录账号 id；用于把他人对话也按只读处理（管理员「全部用户」视图下打开他人对话时）。 */
  currentUserId?: string
  isSending: boolean
  streamingReply: string | null
  playingId: string | null
  onPlayJob: (job: MusicJob) => void
  onSelectJob: (job: MusicJob) => void
  readOnly?: boolean
  /** 失败歌曲是否可重试；管理员跨账号查看时单独放开，未传时沿用对话只读判定。 */
  canRetry?: (job: MusicJob) => boolean
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [generatingId, setGeneratingId] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const chatQuery = useQuery({
    queryKey: ["music-chat", chatId], queryFn: () => fetchMusicChat(chatId), retry: false,
  })

  useEffect(() => {
    if (chatQuery.isError) {
      message.error("对话不存在或已被删除")
      navigate(musicChatPath(), { replace: true })
    }
  }, [chatQuery.isError, navigate])

  const generate = useMutation({
    mutationFn: (messageId: string) => generateMusicChatProposal(csrfToken, chatId, messageId),
    onSuccess: (job) => {
      message.success("已开始生成，完成后可直接试听")
      void queryClient.invalidateQueries({ queryKey: ["music-chat", chatId] })
      void queryClient.invalidateQueries({ queryKey: ["music-jobs"] })
      onSelectJob(job)
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "提案生成任务提交失败"),
  })

  const retryJob = async (job: MusicJob) => {
    try {
      await retryMusicJob(csrfToken, job.id)
      await queryClient.invalidateQueries({ queryKey: ["music-jobs"] })
      message.success("已重新排队，将优先复用已生成的歌曲")
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重试失败")
    }
  }

  const chat: MusicChatDetail | null = chatQuery.data ?? null
  const messages: StreamMessage[] = chat?.messages ?? []
  const anchorJob = chat?.anchor_job ?? null
  // 管理员只读查看他人时，或「全部用户」视图下打开归属他人的对话时，都不允许改动。
  const readOnlyChat = readOnly || Boolean(currentUserId && chat?.owner_user_id && chat.owner_user_id !== currentUserId)

  // 主区随窗口滚动；用底部哨兵把新消息滚进视野
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [messages.length, isSending, streamingReply, chatId])

  const proposalAction = (m: MusicChatMessage) => {
    const job = m.job_id ? jobs.find((item) => item.id === m.job_id) ?? null : null
    if (!job) {
      if (readOnlyChat) return <div className="studio-music-chat-proposal-state"><Tag color="default">提案未生成</Tag></div>
      return <Button type="primary" loading={generatingId === m.id} onClick={async () => {
        setGeneratingId(m.id)
        try { await generate.mutateAsync(m.id) } finally { setGeneratingId(null) }
      }}>生成这首歌</Button>
    }
    const tag = STATUS_TAGS[job.status] ?? STATUS_TAGS.queued
    return <div className="studio-music-chat-proposal-state">
      <Tag color={tag.color}>{tag.label}</Tag>
      {job.status === "running" && <span className="studio-music-chat-proposal-progress">{job.progress}%</span>}
      {job.status === "failed" && (canRetry ? canRetry(job) : !readOnlyChat) && <Button size="small" icon={<RotateCcw size={14} />} onClick={() => void retryJob(job)}>重试</Button>}
    </div>
  }

  const songResult = (m: MusicChatMessage) => {
    const job = m.job_id ? jobs.find((item) => item.id === m.job_id) : null
    if (!job) return null
    const playable = job.status === "succeeded" && Boolean(job.result_url)
    const isPlaying = playingId === job.id
    return <div className="studio-music-stream-song">
      <button type="button" className="studio-music-stream-song-cover" onClick={() => playable ? onPlayJob(job) : onSelectJob(job)}
        aria-label={playable ? `${isPlaying ? "暂停" : "播放"} ${job.title || "歌曲"}` : `查看 ${job.title || "歌曲"}`}>
        <img src={musicArtworkUrl(job)} alt="" />
        {playable && <span className="studio-music-stream-song-play">{isPlaying ? <Pause size={18} fill="currentColor" /> : <Play size={16} fill="currentColor" />}</span>}
      </button>
      <div className="studio-music-stream-song-info">
        <strong>{job.title || "未命名歌曲"}</strong>
        <p>{musicStyleTags(job).slice(0, 3).join(" · ")}</p>
      </div>
      <div className="studio-music-stream-song-side">
        {playable && <span className="studio-music-stream-song-duration">{formatMusicDuration(job.duration_seconds)}</span>}
        {playable
          ? <Button size="small" type="text" icon={<Play size={14} />} onClick={() => onPlayJob(job)}>试听</Button>
          : <Tag color={(STATUS_TAGS[job.status] ?? STATUS_TAGS.queued).color}>{(STATUS_TAGS[job.status] ?? STATUS_TAGS.queued).label}</Tag>}
      </div>
    </div>
  }

  if (chatQuery.isPending) return <div className="studio-music-stream-loading">正在加载对话…</div>

  return <div className="studio-music-stream" aria-label="音乐对话记录">
    <header className="studio-music-stream-head">
      <h1 className="studio-music-stream-title">{chat?.title || "对话创作"}</h1>
      {anchorJob && <p className="studio-music-stream-sub">基于《{anchorJob.title || "未命名歌曲"}》持续修改，生成的新版本自动成为下一轮基础</p>}
    </header>
    <div className="studio-music-stream-feed">
      {messages.map((m) => m.role === "user"
        ? <div key={m.id} className={`studio-music-stream-message is-user ${m.id.startsWith("temp-") ? "is-pending" : ""}`}>{m.content}</div>
        : <div key={m.id} className="studio-music-stream-message is-assistant">
          <p className="studio-music-chat-reply">{m.content}</p>
          {m.proposal?.changed && <div className="studio-music-chat-proposal">
            <div className="studio-music-chat-proposal-head">
              <strong>{m.proposal.title || "未命名歌曲"}</strong>
              <span>{formatMusicDuration(m.proposal.duration_seconds)}</span>
            </div>
            <p className="studio-music-chat-proposal-style">{m.proposal.style}</p>
            {m.proposal.lyrics.trim() && <pre className="studio-music-chat-proposal-lyrics">{m.proposal.lyrics}</pre>}
            <div className="studio-music-chat-proposal-actions">{proposalAction(m)}</div>
          </div>}
          {songResult(m)}
        </div>)}
      {isSending && !streamingReply && <div className="studio-music-chat-typing" aria-label="音乐助手正在思考"><span /><span /><span /></div>}
      {isSending && streamingReply !== null && <div className="studio-music-stream-message is-assistant is-streaming">
        <p className="studio-music-chat-reply">{streamingReply || "…"}</p>
        <p className="studio-music-stream-hint"><Spin size="small" /> 正在整理修改提案…</p>
      </div>}
      <div ref={bottomRef} />
    </div>
  </div>
}
