import { Button, Modal, Select, Slider, Space } from "antd"
import { useEffect, useMemo, useRef, useState } from "react"
import type { VoiceExtractSource } from "../../api"
import {
  VOICE_EXTRACT_HINT,
  clampVoiceExtractWindow,
  formatVoiceExtractTime,
  isVoiceExtractWindowValid,
  voiceExtractSourceLabel,
} from "../../voice-extract-window"

function sourceKey(source: Pick<VoiceExtractSource, "episode_id" | "beat_id">): string {
  return `${source.episode_id}::${source.beat_id}`
}

interface VoiceExtractModalProps {
  open: boolean
  sources: VoiceExtractSource[]
  loadingSources?: boolean
  submitting?: boolean
  onCancel: () => void
  onSubmit: (payload: { episode_id: string; beat_id: string; start_sec: number; end_sec: number }) => void
}

export default function VoiceExtractModal({
  open,
  sources,
  loadingSources,
  submitting,
  onCancel,
  onSubmit,
}: VoiceExtractModalProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const startRef = useRef(0)
  const endRef = useRef(0)
  const loopingRef = useRef(false)
  const [selectedKey, setSelectedKey] = useState("")
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)
  const [startMarked, setStartMarked] = useState(false)
  const [endMarked, setEndMarked] = useState(false)
  const [duration, setDuration] = useState(0)
  const [looping, setLooping] = useState(false)

  const selected = useMemo(
    () => sources.find((item) => sourceKey(item) === selectedKey) || null,
    [sources, selectedKey],
  )

  function resetRange(nextDuration = 0) {
    setStart(0)
    setEnd(0)
    setStartMarked(false)
    setEndMarked(false)
    setLooping(false)
    setDuration(nextDuration)
    loopingRef.current = false
  }

  useEffect(() => {
    if (!open) {
      setSelectedKey("")
      resetRange()
      return
    }
    if (selectedKey && !sources.some((item) => sourceKey(item) === selectedKey)) {
      setSelectedKey("")
      resetRange()
    }
  }, [open, sources, selectedKey])

  useEffect(() => {
    startRef.current = start
    endRef.current = end
    loopingRef.current = looping
  }, [start, end, looping])

  useEffect(() => {
    resetRange(selected?.duration_sec || 0)
    const video = videoRef.current
    if (video) {
      video.pause()
      video.currentTime = 0
    }
  }, [selectedKey])

  const windowValid = startMarked && endMarked && isVoiceExtractWindowValid(start, end, duration)
  const sliderMax = Math.max(duration, 0.05)

  function applyRange(nextStart: number, nextEnd: number, bothMarked: boolean) {
    const [left, right] = clampVoiceExtractWindow(nextStart, nextEnd, duration || nextEnd)
    setStart(left)
    setEnd(right)
    if (bothMarked) {
      setStartMarked(true)
      setEndMarked(true)
    }
  }

  function setFromPlayhead(kind: "start" | "end") {
    const video = videoRef.current
    const time = video?.currentTime ?? 0
    setLooping(false)
    if (kind === "start") {
      setStartMarked(true)
      if (endMarked) applyRange(time, end, true)
      else setStart(Math.max(0, duration ? Math.min(time, duration) : time))
      return
    }
    setEndMarked(true)
    if (startMarked) applyRange(start, time, true)
    else setEnd(Math.max(0, duration ? Math.min(time, duration) : time))
  }

  function handleSliderChange(value: number | number[]) {
    if (!Array.isArray(value)) return
    applyRange(value[0], value[1], true)
  }

  function handleTimeUpdate() {
    const video = videoRef.current
    if (!video || !loopingRef.current) return
    const loopStart = startRef.current
    const loopEnd = endRef.current
    if (!(loopStart < loopEnd)) return
    if (video.currentTime >= loopEnd - 0.04 || video.currentTime < loopStart - 0.08) {
      video.currentTime = loopStart
    }
  }

  async function toggleLoop() {
    const video = videoRef.current
    if (!video || !windowValid) return
    if (looping) {
      video.pause()
      setLooping(false)
      return
    }
    video.currentTime = start
    setLooping(true)
    try {
      await video.play()
    } catch {
      setLooping(false)
    }
  }

  function handleOk() {
    if (!selected || !windowValid) return
    onSubmit({
      episode_id: selected.episode_id,
      beat_id: selected.beat_id,
      start_sec: start,
      end_sec: end,
    })
  }

  return (
    <Modal
      open={open}
      title="从成片提取参考音"
      width={720}
      destroyOnHidden
      onCancel={onCancel}
      className="d2-assets-library"
      okText="提取"
      okButtonProps={{ disabled: !windowValid, loading: submitting }}
      onOk={handleOk}
      cancelText="取消"
    >
      <div className="voice-extract-modal">
        {sources.length === 0 && !loadingSources ? (
          <p className="voice-extract-empty">先出一条该角色开口的镜头，再在成片里框选说话片段。</p>
        ) : (
          <>
            <label className="voice-extract-label">选成片</label>
            <Select
              placeholder="第N集 · 镜号 · 台词摘要"
              value={selectedKey || undefined}
              loading={loadingSources}
              options={sources.map((item) => ({
                value: sourceKey(item),
                label: voiceExtractSourceLabel(item),
              }))}
              onChange={(value) => setSelectedKey(value)}
              getPopupContainer={(trigger) => trigger.parentElement ?? document.body}
              style={{ width: "100%" }}
            />
            {selected ? (
              <>
                <video
                  ref={videoRef}
                  className="voice-extract-video"
                  src={selected.video_url}
                  controls
                  preload="metadata"
                  onLoadedMetadata={(event) => {
                    const next = event.currentTarget.duration
                    if (Number.isFinite(next) && next > 0) setDuration(next)
                  }}
                  onTimeUpdate={handleTimeUpdate}
                  onPause={() => { if (loopingRef.current) setLooping(false) }}
                  onEnded={() => {
                    if (loopingRef.current && videoRef.current && startRef.current < endRef.current) {
                      videoRef.current.currentTime = startRef.current
                      void videoRef.current.play()
                    }
                  }}
                />
                <p className="voice-extract-hint">
                  多人开口的成片请只框该角色单独说话的片段，不要用片头几秒。
                </p>
                <Slider
                  range
                  min={0}
                  max={sliderMax}
                  step={0.05}
                  value={[start, end]}
                  disabled={!duration}
                  onChange={handleSliderChange}
                  tooltip={{ formatter: (value) => formatVoiceExtractTime(Number(value || 0)) }}
                />
                <div className="voice-extract-times">
                  {startMarked && endMarked
                    ? `${formatVoiceExtractTime(start)} – ${formatVoiceExtractTime(end)}（${(end - start).toFixed(1)} 秒）`
                    : VOICE_EXTRACT_HINT}
                </div>
                <Space wrap>
                  <Button onClick={() => setFromPlayhead("start")}>将当前播放时刻设为起点</Button>
                  <Button onClick={() => setFromPlayhead("end")}>将当前播放时刻设为终点</Button>
                  <Button disabled={!windowValid} onClick={() => { void toggleLoop() }}>
                    {looping ? "停止试听" : "循环试听"}
                  </Button>
                </Space>
                {!windowValid ? <p className="voice-extract-warn">{VOICE_EXTRACT_HINT}</p> : null}
              </>
            ) : null}
          </>
        )}
      </div>
    </Modal>
  )
}
