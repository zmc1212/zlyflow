import { Button, Modal, Tag } from "antd"
import { Download, Film, Pause, Play, Volume2, VolumeX } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { DirectorShot, RecipeAudioMix, RecipeSubtitleStyle, defaultRecipeAudio, defaultRecipeSubtitles } from "../types"

interface SequencePlayerModalProps {
  open: boolean
  projectTitle: string
  shots: DirectorShot[]
  subtitleStyle?: RecipeSubtitleStyle
  audio?: RecipeAudioMix
  onClose: () => void
  onBatchDeliver?: () => void
}

export default function SequencePlayerModal({
  open,
  projectTitle,
  shots,
  subtitleStyle,
  audio,
  onClose,
  onBatchDeliver,
}: SequencePlayerModalProps) {
  const completedShots = shots.filter((s) => s.status === "succeeded" && Boolean(s.outputVideoUrl))
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isPlaying, setIsPlaying] = useState(true)
  const [isMuted, setIsMuted] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const videoRef = useRef<HTMLVideoElement>(null)
  const bgmRef = useRef<HTMLAudioElement>(null)
  const style = { ...defaultRecipeSubtitles(), ...subtitleStyle }
  const mix = { ...defaultRecipeAudio(), ...audio }

  const activeShot = completedShots[currentIndex]
  const dialogue = activeShot?.dialogue?.trim() || ""

  useEffect(() => {
    if (!open || !activeShot) return
    setCurrentTime(0)
    if (videoRef.current) {
      videoRef.current.currentTime = 0
      if (isPlaying) {
        videoRef.current.play().catch(() => {})
      }
    }
  }, [currentIndex, open, activeShot?.id])

  useEffect(() => {
    const bgm = bgmRef.current
    if (!bgm) return
    bgm.volume = Math.min(1, Math.max(0, mix.bgmVolume))
    if (!open || !mix.bgmUrl) {
      bgm.pause()
      return
    }
    if (isPlaying && !isMuted) {
      bgm.play().catch(() => {})
    } else {
      bgm.pause()
    }
  }, [open, isPlaying, isMuted, mix.bgmUrl, mix.bgmVolume, currentIndex])

  const handleEnded = () => {
    if (currentIndex < completedShots.length - 1) {
      setCurrentIndex((prev) => prev + 1)
    } else {
      // 循环到首个镜头
      setCurrentIndex(0)
    }
  }

  const togglePlay = () => {
    if (!videoRef.current) return
    if (videoRef.current.paused) {
      videoRef.current.play().catch(() => {})
      setIsPlaying(true)
    } else {
      videoRef.current.pause()
      setIsPlaying(false)
    }
  }

  if (completedShots.length === 0) {
    return (
      <Modal
        title="故事板连播预览"
        open={open}
        onCancel={onClose}
        footer={[
          <Button key="close" onClick={onClose}>
            关闭
          </Button>,
        ]}
      >
        <div className="py-8 text-center text-sm text-[#6b7280]">
          <Film size={36} className="mx-auto mb-3 text-[#9ca3af]" />
          <p>当前故事板暂无已生成完成的分镜视频</p>
          <p className="mt-1 text-xs text-[#9ca3af]">请先生成分镜头后再进行连播预览</p>
        </div>
      </Modal>
    )
  }

  return (
    <Modal
      title={
        <div className="flex items-center justify-between pr-8">
          <div className="flex items-center gap-2 text-base font-semibold text-[#111827]">
            <Film size={20} className="text-[#7047f6]" />
            <span>故事板成片连续串播（Master Sequence Player）</span>
            <Tag color="purple">{projectTitle}</Tag>
          </div>
          <span className="text-xs text-[#6b7280]">
            已完成 {completedShots.length} / {shots.length} 个镜头
          </span>
        </div>
      }
      open={open}
      onCancel={onClose}
      width={880}
      className="director-sequence-modal"
      footer={
        <div className="flex items-center justify-between">
          <span className="text-xs text-[#6b7280]">
            当前播放：镜头 {currentIndex + 1} / {completedShots.length} - {activeShot?.title}
          </span>
          <div className="flex items-center gap-2">
            {onBatchDeliver ? (
              <Button icon={<Download size={14} />} onClick={onBatchDeliver}>
                一键批量保存到本地目录
              </Button>
            ) : null}
            <Button type="primary" onClick={onClose} className="bg-[#7047f6]">
              完成预览
            </Button>
          </div>
        </div>
      }
      destroyOnHidden
    >
      <div className="space-y-4 py-2">
        {/* 视频主播放窗口 */}
        <div className="relative aspect-video w-full overflow-hidden rounded-2xl bg-black shadow-inner">
          {mix.bgmUrl ? <audio ref={bgmRef} src={mix.bgmUrl} loop preload="auto" /> : null}
          {activeShot?.outputVideoUrl ? (
            <video
              ref={videoRef}
              src={activeShot.outputVideoUrl}
              className="h-full w-full object-contain"
              autoPlay={isPlaying}
              muted={isMuted}
              playsInline
              onTimeUpdate={() => {
                if (videoRef.current) {
                  setCurrentTime(videoRef.current.currentTime)
                  setDuration(videoRef.current.duration || 0)
                }
              }}
              onEnded={handleEnded}
              onClick={togglePlay}
            />
          ) : null}
          {style.enabled && dialogue ? (
            <p
              className={`director-sequence-subtitle is-${style.position}`}
              style={{
                fontSize: `${style.fontSize}px`,
                color: style.textColor,
                WebkitTextStroke: `${style.strokeWidth}px ${style.strokeColor}`,
                paintOrder: "stroke fill",
                textShadow: `0 0 ${Math.max(2, style.strokeWidth)}px ${style.strokeColor}`,
              }}
            >
              {dialogue}
            </p>
          ) : null}

          {/* 浮动控制覆盖层 */}
          <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/80 to-transparent px-4 py-3 text-white">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={togglePlay}
                className="grid size-8 place-items-center rounded-lg bg-white/20 hover:bg-white/30"
              >
                {isPlaying ? <Pause size={16} /> : <Play size={16} />}
              </button>
              <button
                type="button"
                onClick={() => setIsMuted((prev) => !prev)}
                className="grid size-8 place-items-center rounded-lg bg-white/20 hover:bg-white/30"
              >
                {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
              </button>
              <span className="text-xs">
                {Math.floor(currentTime)}s / {Math.floor(duration || 5)}s
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Tag color="blue">{activeShot?.camera.scale}</Tag>
              <Tag color="purple">{activeShot?.camera.movement}</Tag>
            </div>
          </div>
        </div>

        {/* 故事板时间轴分镜头轨道 */}
        <div className="rounded-xl border border-black/[0.08] bg-[#f8f9fa] p-3">
          <div className="mb-2 flex items-center justify-between text-xs font-semibold text-[#4b5563]">
            <span>镜头时间轴序列轨道</span>
            <span>点击可跳转镜头</span>
          </div>
          <div className="flex gap-2.5 overflow-x-auto pb-1">
            {completedShots.map((shot, idx) => {
              const active = idx === currentIndex
              return (
                <button
                  key={shot.id}
                  type="button"
                  onClick={() => setCurrentIndex(idx)}
                  className={`group relative flex h-20 w-36 shrink-0 flex-col overflow-hidden rounded-lg border text-left transition ${
                    active
                      ? "border-[#7047f6] ring-2 ring-[#7047f6]/20 shadow-md"
                      : "border-black/[0.1] bg-white hover:border-black/30"
                  }`}
                >
                  <div className="relative h-12 w-full bg-black/10">
                    {shot.outputVideoUrl ? (
                      <video
                        src={shot.outputVideoUrl}
                        className="h-full w-full object-cover"
                        muted
                        preload="metadata"
                      />
                    ) : null}
                    <span className="absolute left-1 top-1 rounded bg-black/60 px-1 py-0.5 text-[9px] font-bold text-white">
                      Shot {shot.shotNumber}
                    </span>
                  </div>
                  <div className="min-w-0 flex-1 p-1">
                    <p className="truncate text-[11px] font-medium text-[#111827]">
                      {shot.title}
                    </p>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </Modal>
  )
}
