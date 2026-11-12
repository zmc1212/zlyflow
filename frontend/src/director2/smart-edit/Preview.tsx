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
  laneClips,
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

const transitionLength = (clip: EditClip | undefined) =>
  clip && clip.transition === "dissolve"
    ? Math.min(2, Math.max(0.2, clip.transition_duration ?? 0.5))
    : 0

function MediaLayer({
  clip,
  asset,
  playing,
  time,
  volumeScale,
  onProbe,
  onFail,
  style
}: {
  clip: EditClip
  asset: EditDocument["assets"][number]
  playing: boolean
  time: number
  volumeScale?: number
  onProbe: (id: string, duration: number) => void
  onFail: (message: string) => void
  style?: React.CSSProperties
}) {
  const video = useRef<HTMLVideoElement | null>(null)
  useEffect(() => {
    const element = video.current
    if (!element) return
    const target = clip.in_point + Math.max(0, time - clip.start) * clip.speed
    if (
      Number.isFinite(target) &&
      Math.abs(element.currentTime - target) > (playing ? 0.18 : 0.01)
    )
      element.currentTime = target
    element.playbackRate = clip.speed
    element.muted = clip.muted
    element.volume = Math.min(
      1,
      Math.min(1, clip.volume) *
        clipOpacity({ ...clip, opacity: 1 }, time) *
        (volumeScale ?? 1)
    )
    if (playing && element.paused)
      void element.play().catch(() => {
        onFail("素材暂时无法播放，请检查媒体地址或重新导入。")
      })
    else if (!playing && !element.paused) element.pause()
  }, [time, playing, clip, volumeScale, onFail])
  if (asset.kind === "image")
    return (
      <img
        key={asset.id}
        src={asset.url}
        alt={asset.name}
        style={style}
        onError={() => onFail("图片无法加载，请重新导入素材。")}
      />
    )
  return (
    <video
      ref={video}
      key={clip.id}
      src={asset.url}
      preload="auto"
      playsInline
      style={style}
      onLoadedMetadata={(event) => {
        if (Number.isFinite(event.currentTarget.duration))
          onProbe(asset.id, event.currentTarget.duration)
      }}
      onError={() =>
        onFail("视频无法加载，请检查媒体地址或重新导入。 ")
      }
    />
  )
}

function AudioLayer({
  clip,
  asset,
  playing,
  time,
  onProbe,
  onFail
}: {
  clip: EditClip
  asset: EditDocument["assets"][number]
  playing: boolean
  time: number
  onProbe: (id: string, duration: number) => void
  onFail: (message: string) => void
}) {
  const audio = useRef<HTMLAudioElement | null>(null)
  useEffect(() => {
    const element = audio.current
    if (!element) return
    const target = clip.in_point + Math.max(0, time - clip.start) * clip.speed
    if (
      Number.isFinite(target) &&
      Math.abs(element.currentTime - target) > (playing ? 0.18 : 0.01)
    )
      element.currentTime = target
    element.playbackRate = clip.speed
    element.muted = clip.muted
    element.volume = Math.min(
      1,
      Math.min(1, clip.volume) * clipOpacity({ ...clip, opacity: 1 }, time)
    )
    if (playing && element.paused)
      void element.play().catch(() => {
        onFail("配音或音乐无法播放，请检查媒体地址或重新导入。")
      })
    else if (!playing && !element.paused) element.pause()
  }, [time, playing, clip, onFail])
  return (
    <audio
      ref={audio}
      key={clip.id}
      src={asset.url}
      preload="auto"
      onLoadedMetadata={(event) => {
        if (Number.isFinite(event.currentTarget.duration))
          onProbe(asset.id, event.currentTarget.duration)
      }}
      onError={() => onFail("配音或音乐无法加载，请重新导入。 ")}
    />
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
    music = active("music"),
    text = active("text")
  const pictureAsset = doc.assets.find((a) => a.id === picture?.asset_id)
  // Dissolve: the outgoing picture keeps playing underneath while the incoming
  // one fades in — the same blend the exporter renders.
  const dissolve = transitionLength(picture)
  const inDissolve =
    dissolve > 0 && picture != null && time >= picture.start && time < picture.start + dissolve
  const dissolveProgress = inDissolve ? (time - (picture?.start ?? 0)) / dissolve : 1
  const outgoing =
    inDissolve && picture
      ? laneClips(doc, "video").find(
          (c) => Math.abs(c.start + c.duration - picture.start) < 0.001
        )
      : undefined
  const outgoingAsset = doc.assets.find((a) => a.id === outgoing?.asset_id)
  // Dip to black/white: solid colour covers the seam, split across the tail of
  // the previous picture and the head of the incoming one.
  const dip = (() => {
    if (!picture) return undefined
    const head = picture.transition ?? "none"
    if (head === "black" || head === "white") {
      const f = Math.min(1, Math.max(0.1, (picture.transition_duration ?? 0.5) / 2))
      if (time < picture.start + f)
        return {
          color: head === "white" ? "#ffffff" : "#000000",
          alpha: 1 - (time - picture.start) / f
        }
    }
    const next = laneClips(doc, "video").find(
      (c) => Math.abs(c.start - (picture.start + picture.duration)) < 0.001
    )
    if (next && (next.transition === "black" || next.transition === "white")) {
      const f = Math.min(1, Math.max(0.1, (next.transition_duration ?? 0.5) / 2))
      const windowStart = picture.start + picture.duration - f
      if (time >= windowStart)
        return {
          color: next.transition === "white" ? "#ffffff" : "#000000",
          alpha: (time - windowStart) / f
        }
    }
    return undefined
  })()
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
  }, [picture?.id, sound?.id, music?.id])
  useEffect(
    () => () => {
      for (const node of stage.current?.querySelectorAll("video, audio") || [])
        (node as HTMLMediaElement).pause()
    },
    []
  )
  const pictureStyle = picture
    ? {
        opacity: inDissolve ? dissolveProgress : clipOpacity(picture, time),
        transform: `translate(${picture.x}%, ${picture.y}%) scale(${picture.scale}) rotate(${picture.rotation}deg)`,
        filter: EFFECTS.find((e) => e.id === picture.effect)?.css
      }
    : undefined
  const outgoingStyle =
    outgoing && outgoingAsset
      ? {
          opacity: clipOpacity(outgoing, time),
          transform: `translate(${outgoing.x}%, ${outgoing.y}%) scale(${outgoing.scale}) rotate(${outgoing.rotation}deg)`,
          filter: EFFECTS.find((e) => e.id === outgoing.effect)?.css
        }
      : undefined
  const fail = (message: string) => setFailed(message)
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
          {outgoing &&
            outgoingAsset &&
            (outgoingAsset.kind === "image" ? (
              <img
                key={outgoingAsset.id}
                src={outgoingAsset.url}
                alt={outgoingAsset.name}
                style={outgoingStyle}
                onError={() => setFailed("图片无法加载，请重新导入素材。")}
              />
            ) : (
              <MediaLayer
                clip={outgoing}
                asset={outgoingAsset}
                playing={playing}
                time={time}
                volumeScale={1 - dissolveProgress}
                onProbe={onProbe}
                onFail={fail}
                style={outgoingStyle}
              />
            ))}
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
              <MediaLayer
                clip={picture}
                asset={pictureAsset}
                playing={playing}
                time={time}
                volumeScale={inDissolve ? dissolveProgress : 1}
                onProbe={onProbe}
                onFail={fail}
                style={pictureStyle}
              />
            ))}
          {dip && (
            <div
              className="se-preview-dip"
              style={{ background: dip.color, opacity: Math.min(1, Math.max(0, dip.alpha)) }}
            />
          )}
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
        {sound && doc.assets.find((a) => a.id === sound.asset_id) && (
          <AudioLayer
            clip={sound}
            asset={doc.assets.find((a) => a.id === sound.asset_id)!}
            playing={playing}
            time={time}
            onProbe={onProbe}
            onFail={fail}
          />
        )}
        {music && doc.assets.find((a) => a.id === music.asset_id) && (
          <AudioLayer
            clip={music}
            asset={doc.assets.find((a) => a.id === music.asset_id)!}
            playing={playing}
            time={time}
            onProbe={onProbe}
            onFail={fail}
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
