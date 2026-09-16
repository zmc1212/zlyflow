import { ChevronDown } from "lucide-react"
import type { ReactNode } from "react"
import { episodeShotCountLabel, type StoryboardEpisodeRowStatus } from "../storyboard-stream-view"

function SpinnerRing({ active, order }: { active?: boolean; order: number }) {
  const size = 22
  const stroke = 2
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  return (
    <span className="director-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} className={active ? "is-spin" : undefined}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--director-line)" strokeWidth={stroke} />
        {active ? (
          <circle
            cx={size / 2} cy={size / 2} r={radius} fill="none"
            stroke="var(--director-accent)" strokeWidth={stroke} strokeLinecap="round"
            strokeDasharray={`${circumference * 0.28} ${circumference * 0.72}`}
          />
        ) : null}
      </svg>
      <span className="director-ring-num">{order}</span>
    </span>
  )
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5" /></svg>
  )
}

function EpisodeStatusBadge({ status, order }: { status: StoryboardEpisodeRowStatus; order: number }) {
  if (status === "completed") {
    return <span className="director-badge is-green"><CheckIcon /></span>
  }
  return <SpinnerRing active={status === "running"} order={order} />
}

export type DirectorEpisodeCapsuleProps = {
  episodeNumber: number
  title: string
  status: StoryboardEpisodeRowStatus
  open: boolean
  index: number
  shotCount: number
  onToggle: (key: string, currentlyOpen: boolean) => void
  children: ReactNode
  /** Extra class on the fold body (e.g. `is-script` for manuscript padding). */
  bodyClassName?: string
  /** Prefix for aria-controls / fold id so script and storyboard capsules do not collide. */
  idPrefix?: string
}

/** Official Task Rows–style episode parent capsule (0fr → 1fr). Shared by storyboard and script live cards. */
export default function DirectorEpisodeCapsule({
  episodeNumber,
  title,
  status,
  open,
  index,
  shotCount,
  onToggle,
  children,
  bodyClassName,
  idPrefix = "director-episode-row-body",
}: DirectorEpisodeCapsuleProps) {
  const bodyId = `${idPrefix}-${episodeNumber}`
  const bodyClass = ["director-episode-row-body", bodyClassName].filter(Boolean).join(" ")
  return (
    <section
      className={`director-episode-row is-${status}${open ? " is-open" : ""}`}
      style={{ animation: `director-fade-up 450ms cubic-bezier(0.23,1,0.32,1) ${index * 80}ms both` }}
    >
      <button
        type="button"
        className="director-episode-row-head"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => onToggle(String(episodeNumber), open)}
      >
        <span className="director-episode-row-icon" aria-hidden>
          <EpisodeStatusBadge status={status} order={episodeNumber} />
        </span>
        <span className="director-episode-row-label">{title}</span>
        <span className="director-episode-row-amount">{episodeShotCountLabel(shotCount)}</span>
        {status === "completed" ? <span className="director-task-pill is-green">已完成</span> : null}
        <ChevronDown size={14} className="director-episode-row-chevron" aria-hidden />
      </button>
      <div className={`director-episode-row-fold${open ? " is-open" : ""}`} id={bodyId} {...(!open ? { inert: true } : {})}>
        <div>
          <div className={bodyClass}>{children}</div>
        </div>
      </div>
    </section>
  )
}
