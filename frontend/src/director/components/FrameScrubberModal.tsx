import { Button, Modal, Slider, message } from "antd"
import {
  Camera, ChevronLeft, ChevronRight, Pause, Play, RotateCcw, Video,
} from "lucide-react"
import React, { useEffect, useRef, useState } from "react"

interface FrameScrubberModalProps {
  open: boolean
  videoUrl: string
  sourceShotTitle: string
  onClose: () => void
  onCaptureFrame: (frameFile: File, frameDataUrl: string) => void
}

export default function FrameScrubberModal({
  open,
  videoUrl,
  sourceShotTitle,
  onClose,
  onCaptureFrame,
}: FrameScrubberModalProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [capturedPreview, setCapturedPreview] = useState<string | null>(null)

  useEffect(() => {
    if (open && videoRef.current) {
      videoRef.current.currentTime = 0
      setCurrentTime(0)
      setIsPlaying(false)
    }
  }, [open, videoUrl])

  const togglePlay = () => {
    if (!videoRef.current) return
    if (isPlaying) {
      videoRef.current.pause()
      setIsPlaying(false)
    } else {
      videoRef.current.play()
      setIsPlaying(true)
    }
  }

  const handleTimeUpdate = () => {
    if (!videoRef.current) return
    setCurrentTime(videoRef.current.currentTime)
  }

  const handleLoadedMetadata = () => {
    if (!videoRef.current) return
    setDuration(videoRef.current.duration || 5)
  }

  const handleSeek = (value: number) => {
    if (!videoRef.current) return
    videoRef.current.currentTime = value
    setCurrentTime(value)
  }

  const stepFrame = (frames: number) => {
    if (!videoRef.current) return
    const frameDuration = 1 / 24
    const nextTime = Math.min(duration, Math.max(0, videoRef.current.currentTime + frames * frameDuration))
    videoRef.current.currentTime = nextTime
    setCurrentTime(nextTime)
  }

  const captureCurrentFrame = () => {
    if (!videoRef.current) return
    const video = videoRef.current
    const canvas = document.createElement("canvas")
    canvas.width = video.videoWidth || 1280
    canvas.height = video.videoHeight || 720
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    const dataUrl = canvas.toDataURL("image/png")
    setCapturedPreview(dataUrl)

    canvas.toBlob((blob) => {
      if (!blob) return
      const file = new File([blob], `frame_${currentTime.toFixed(2)}s.png`, { type: "image/png" })
      onCaptureFrame(file, dataUrl)
      message.success(`已截取 ${currentTime.toFixed(2)}s 画面作为关键帧`)
      onClose()
    }, "image/png")
  }

  return (
    <Modal
      open={open}
      title={
        <div className="flex items-center gap-2 text-base font-semibold text-[#111827]">
          <Camera size={18} className="text-[#7047f6]" />
          <span>任意帧定格器 — {sourceShotTitle}</span>
        </div>
      }
      onCancel={onClose}
      footer={null}
      width={720}
      centered
      className="studio-frame-scrubber-modal"
    >
      <div className="flex flex-col gap-4 py-2">
        {/* 视频主播放窗口 */}
        <div className="relative aspect-video w-full rounded-xl overflow-hidden bg-black flex items-center justify-center shadow-md">
          <video
            ref={videoRef}
            src={videoUrl}
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={handleLoadedMetadata}
            onEnded={() => setIsPlaying(false)}
            playsInline
            crossOrigin="anonymous"
            className="w-full h-full object-contain"
          />
        </div>

        {/* 进度条与逐帧控制器 */}
        <div className="flex flex-col gap-2 bg-[#f8f9fa] p-3 rounded-xl border border-black/[0.06]">
          <div className="flex items-center justify-between text-xs text-[#6b7280]">
            <span className="font-mono">{currentTime.toFixed(2)}s / 帧 {Math.round(currentTime * 24)}</span>
            <span className="font-mono">{duration.toFixed(2)}s</span>
          </div>

          <Slider
            min={0}
            max={duration || 5}
            step={0.01}
            value={currentTime}
            onChange={handleSeek}
            className="!m-0"
          />

          {/* 播放控制与步进按钮 */}
          <div className="flex items-center justify-between pt-1">
            <div className="flex items-center gap-2">
              <Button
                type="primary"
                size="small"
                onClick={togglePlay}
                icon={isPlaying ? <Pause size={13} /> : <Play size={13} />}
                className="bg-[#7047f6]"
              >
                {isPlaying ? "暂停" : "播放"}
              </Button>

              <Button
                size="small"
                onClick={() => stepFrame(-1)}
                icon={<ChevronLeft size={13} />}
                title="上一帧 (1/24s)"
              >
                -1 帧
              </Button>

              <Button
                size="small"
                onClick={() => stepFrame(1)}
                icon={<ChevronRight size={13} />}
                title="下一帧 (1/24s)"
              >
                +1 帧
              </Button>

              <Button
                size="small"
                onClick={() => handleSeek(0)}
                icon={<RotateCcw size={13} />}
                title="跳到开头"
              >
                首帧
              </Button>

              <Button
                size="small"
                onClick={() => handleSeek(duration)}
                title="跳到结尾"
              >
                尾帧
              </Button>
            </div>

            <Button
              type="primary"
              onClick={captureCurrentFrame}
              icon={<Camera size={15} />}
              className="bg-emerald-600 hover:bg-emerald-500 font-medium"
            >
              截取当前画面作为首帧 (I2V)
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  )
}
