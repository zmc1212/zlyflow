import { useState } from "react"
import { Button, Tag } from "antd"
import {
  Activity,
  MapPin,
  MessageSquareQuote,
  Package,
  Sparkles,
  Users,
  Video,
} from "lucide-react"
import { formatShotDurationLabel } from "../shot-plan-live"

export type ContentLibraryShot = {
  shot_num: number
  title?: string
  camera?: string
  scene?: string
  characters?: string[]
  props?: string[]
  action?: string
  dialogue?: string
  audio?: string
  subtitle?: string
  visual_prompt?: string
  duration_sec?: number | string
}

const CHARS_PER_LINE = 16

export function contentLibraryTextNeedsClamp(text: string, lines: number): boolean {
  return text.trim().length > lines * CHARS_PER_LINE
}

function ShotClampText({
  text,
  lines,
  className,
}: {
  text: string
  lines: number
  className?: string
}) {
  const [expanded, setExpanded] = useState(false)
  const needsClamp = contentLibraryTextNeedsClamp(text, lines)
  const open = expanded || !needsClamp
  return (
    <div className={["shot-clamp-block", className].filter(Boolean).join(" ")}>
      <p className={`shot-clamp${open ? " is-open" : ""}`} style={open ? undefined : { WebkitLineClamp: lines }}>
        {text}
      </p>
      {needsClamp ? (
        <Button type="link" size="small" className="shot-clamp-toggle" onClick={() => setExpanded((value) => !value)}>
          {expanded ? "收起" : "展开全部"}
        </Button>
      ) : null}
    </div>
  )
}

export default function ContentLibraryShotCard({
  shot,
  onCopyPrompt,
  entering = false,
  assembling = false,
}: {
  shot: ContentLibraryShot
  onCopyPrompt: (text: string | null | undefined) => void
  entering?: boolean
  assembling?: boolean
}) {
  const durationLabel = formatShotDurationLabel(shot.duration_sec)
  const className = [
    "shot-card",
    entering ? "is-enter" : "",
    assembling ? "is-assembling" : "",
  ].filter(Boolean).join(" ")
  return (
    <div className={className}>
      <div className="shot-card-header">
        <span className="shot-badge">镜头 {shot.shot_num}</span>
        <h4 className="shot-title" title={shot.title || undefined}>
          {shot.title || `镜头 ${shot.shot_num}`}
        </h4>
        {durationLabel ? <span className="shot-duration">{durationLabel}</span> : null}
      </div>

      <div className="shot-meta-rows">
        {shot.camera ? (
          <div className="shot-meta-row">
            <span className="meta-lbl">
              <Video size={13} /> 机位：
            </span>
            <ShotClampText text={shot.camera} lines={3} className="meta-val" />
          </div>
        ) : null}

        {shot.scene ? (
          <div className="shot-meta-row">
            <span className="meta-lbl">
              <MapPin size={13} /> 场景：
            </span>
            <span className="meta-val scene-val">{shot.scene}</span>
          </div>
        ) : null}

        {shot.characters?.length ? (
          <div className="shot-meta-row">
            <span className="meta-lbl">
              <Users size={13} /> 人物：
            </span>
            <div className="tags-cluster">
              {shot.characters.map((name) => (
                <Tag key={name} color="purple">
                  {name}
                </Tag>
              ))}
            </div>
          </div>
        ) : null}

        {shot.props?.length ? (
          <div className="shot-meta-row">
            <span className="meta-lbl">
              <Package size={13} /> 道具：
            </span>
            <div className="tags-cluster">
              {shot.props.map((name) => (
                <Tag key={name} color="orange">
                  {name}
                </Tag>
              ))}
            </div>
          </div>
        ) : null}

        {shot.action ? (
          <div className="shot-meta-row">
            <span className="meta-lbl">
              <Activity size={13} /> 动作：
            </span>
            <ShotClampText text={shot.action} lines={6} className="meta-val" />
          </div>
        ) : null}

        {shot.dialogue ? (
          <div className="shot-meta-row dialogue-row">
            <span className="meta-lbl">
              <MessageSquareQuote size={13} /> 台词：
            </span>
            <div className="dialogue-bubble">
              <ShotClampText text={shot.dialogue} lines={4} />
            </div>
          </div>
        ) : null}

        {shot.audio || shot.subtitle ? (
          <div className="shot-meta-row audio-row">
            {shot.audio ? <ShotClampText text={`🔊 ${shot.audio}`} lines={3} className="audio-text" /> : null}
            {shot.subtitle ? <ShotClampText text={`💬 ${shot.subtitle}`} lines={3} className="subtitle-text" /> : null}
          </div>
        ) : null}

        {shot.visual_prompt ? (
          <div className="shot-prompt-box">
            <div className="prompt-head">
              <span>
                <Sparkles size={12} /> AI 画面提示词 (Prompt)
              </span>
              <Button type="link" size="small" className="copy-link" onClick={() => onCopyPrompt(shot.visual_prompt)}>
                复制
              </Button>
            </div>
            <ShotClampText text={shot.visual_prompt} lines={3} className="prompt-text" />
          </div>
        ) : null}
      </div>
    </div>
  )
}
