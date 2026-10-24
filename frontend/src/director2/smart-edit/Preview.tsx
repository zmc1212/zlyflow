import { useEffect, useRef, useState } from "react"
import { Button, Tooltip } from "antd"
import {
  Film,
  Maximize,
  Pause,
  Play,
  SkipBack,
  SkipForward
} from "lucide-react"
import {
  EFFECTS,
  RATIOS,
  endOf,
  timecode,
  wrapText,
  type EditClip,
  type EditDocument
} from "./model"

export function clipOpacity(clip: EditClip, time: number): number {
  const local = time - clip.start
  return (
    clip.opacity *
    Math.max(
      0,
      Math.min(
        1,
        clip.fade_in ? local / clip.fade_in : 1,
        clip.fade_out ? (clip.duration - local) / clip.fade_out : 1
      )
    )
  )
}

export default function Preview({
  doc,
  time,
  playing,
  onTime,
  onPlay,
  onProbe
}: {
  doc: EditDocument
  time: number
  playing: boolean
  onTime: (time: number) => void
  onPlay: (value: boolean) => void
  onProbe: (id: string, duration: number) => void
}) {
  const [size, setSize] = useState({ width: 640, height: 360 })
  const [failed, setFailed] = useState("")
  const well = useRef<HTMLDivElement>(null),
    stage = useRef<HTMLDivElement>(null)
  const video = useRef<HTMLVideoElement>(null),
    audio = useRef<HTMLAudioElement>(null)
  const [w, h] = RATIOS[doc.settings.ratio]
  const stageWidth = Math.max(
    1,
    Math.min(size.width - 12, ((size.height - 12) * w) / h)
  )
  const active = (track: string) =>
    doc.clips.find(
      (c) =>
        c.track === track &&
        time + 0.00001 >= c.start &&
        time < c.start + c.duration - 0.00001
    )
  const picture = active("video"),
    sound = active("audio"),
    text = active("text")
  const pictureAsset = doc.assets.find((a) => a.id === picture?.asset_id),
    audioAsset = doc.assets.find((a) => a.id === sound?.asset_id)
  useEffect(() => {
    const observer = new ResizeObserver((entries) =>
      setSize({
        width: entries[0].contentRect.width,
        height: entries[0].contentRect.height
      })
    )
    if (well.current) observer.observe(well.current)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    setFailed("")
  }, [picture?.id, sound?.id])
  useEffect(() => {
    for (const [element, clip] of [
      [video.current, picture],
      [audio.current, sound]
    ] as const) {
      if (!element || !clip) continue
      const target = clip.in_point + Math.max(0, time - clip.start) * clip.speed
      if (
        Number.isFinite(target) &&
        Math.abs(element.currentTime - target) > (playing ? 0.18 : 0.01)
      )
        element.currentTime = target
      element.playbackRate = clip.speed
      element.muted = clip.muted
      element.volume =
        Math.min(1, clip.volume) * clipOpacity({ ...clip, opacity: 1 }, time)
      if (playing && element.paused)
        void element.play().catch(() => {
          setFailed("素材暂时无法播放，请检查媒体地址或重新导入。")
        })
      else if (!playing && !element.paused) element.pause()
    }
  }, [time, playing, picture, sound])
  useEffect(
    () => () => {
      video.current?.pause()
      audio.current?.pause()
    },
    []
  )
  const pictureStyle = picture
    ? {
        opacity: clipOpacity(picture, time),
        transform: `translate(${picture.x}%, ${picture.y}%) scale(${picture.scale}) rotate(${picture.rotation}deg)`,
        filter: EFFECTS.find((e) => e.id === picture.effect)?.css
      }
    : undefined
  return (
    <section className="se-preview" aria-label="成片预览">
      <div className="se-panel-heading">
        <span>预览</span>
        <span>
          {doc.settings.ratio} <span className="se-dot">·</span>{" "}
          {doc.settings.fps} fps
        </span>
      </div>
      <div className="se-preview-well" ref={well}>
        <div
          ref={stage}
          className="se-stage"
          style={{
            width: stageWidth,
            height: (stageWidth * h) / w,
            background: doc.settings.background
          }}
        >
          {picture &&
            pictureAsset &&
            (pictureAsset.kind === "image" ? (
              <img
                key={pictureAsset.id}
                src={pictureAsset.url}
                alt={pictureAsset.name}
                style={pictureStyle}
                onError={() => setFailed("图片无法加载，请重新导入素材。")}
              />
            ) : (
              <video
                ref={video}
                key={picture.id}
                src={pictureAsset.url}
                preload="auto"
                playsInline
                style={pictureStyle}
                onLoadedMetadata={(event) => {
                  if (Number.isFinite(event.currentTarget.duration))
                    onProbe(pictureAsset.id, event.currentTarget.duration)
                }}
                onError={() =>
                  setFailed("视频无法加载，请检查媒体地址或重新导入。 ")
                }
              />
            ))}
          {text && (
            <div
              className="se-preview-text"
              style={{
                left: `${50 + text.x}%`,
                top: `${50 + text.y}%`,
                color: text.color,
                fontSize: (text.font_size * stageWidth) / 1920,
                opacity: clipOpacity(text, time)
              }}
            >
              {wrapText(text.text, text.font_size)}
            </div>
          )}
          {!doc.clips.length && (
            <div className="se-preview-placeholder">
              <Film size={36} strokeWidth={1.2} />
              <strong>你的故事，从这里成片</strong>
              <span>添加素材到时间线，或一键按分镜粗剪</span>
            </div>
          )}
          {failed && (
            <div className="se-preview-error" role="alert">
              {failed}
            </div>
          )}
        </div>
        {sound && audioAsset && (
          <audio
            key={sound.id}
            ref={audio}
            src={audioAsset.url}
            preload="auto"
            onLoadedMetadata={(event) => {
              if (Number.isFinite(event.currentTarget.duration))
                onProbe(audioAsset.id, event.currentTarget.duration)
            }}
            onError={() => setFailed("配音或音乐无法加载，请重新导入。 ")}
          />
        )}
      </div>
      <div className="se-player-controls">
        <span className="se-time">
          <b>{timecode(time, doc.settings.fps)}</b>
          <span> / {timecode(endOf(doc), doc.settings.fps)}</span>
        </span>
        <div className="se-transport">
          <Tooltip title="回到开头">
            <Button
              type="text"
              aria-label="回到开头"
              icon={<SkipBack size={15} />}
              onClick={() => onTime(0)}
            />
          </Tooltip>
          <Button
            type="text"
            className="se-play-button"
            aria-label={playing ? "暂停" : "播放"}
            disabled={!doc.clips.length}
            icon={playing ? <Pause size={19} /> : <Play size={19} />}
            onClick={() => onPlay(!playing)}
          />
          <Tooltip title="跳到结尾">
            <Button
              type="text"
              aria-label="跳到结尾"
              icon={<SkipForward size={15} />}
              onClick={() => {
                onPlay(false)
                onTime(endOf(doc))
              }}
            />
          </Tooltip>
        </div>
        <Tooltip title="全屏预览">
          <Button
            type="text"
            aria-label="全屏预览"
            icon={<Maximize size={15} />}
            onClick={() => {
              void stage.current?.requestFullscreen().catch(() => undefined)
            }}
          />
        </Tooltip>
      </div>
    </section>
  )
}
