import { CheckCircle2, ChevronDown } from "lucide-react"
import { useState, type ReactNode } from "react"
import {
  buildStoryboardStreamModel,
  episodeShotCountLabel,
  groupPolishShotNumbers,
  polishPhaseTitle,
  polishShotLegend,
  resolveActiveEpisodeNumber,
  resolveEpisodeRowStatus,
  resolvePolishCurrentShot,
  resolvePolishGroupStatus,
  shotDurationLabel,
  type StoryboardEpisodeRowStatus,
  type StoryboardEpisodeView,
  type StoryboardShotView,
  type StoryboardStreamInput,
} from "../storyboard-stream-view"

export type DirectorStoryboardLiveBodyProps = StoryboardStreamInput & {
  settled?: boolean
}

function chipState(no: number, currentShot?: number, range?: [number, number]): string {
  if (currentShot !== undefined) {
    if (no < currentShot) return " is-done"
    if (no === currentShot) return " is-active"
    return ""
  }
  if (range && no < range[0]) return " is-done"
  if (range && no >= range[0] && no <= range[1]) return " is-active"
  return ""
}

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

function ShotStreamRow({
  shot,
  settled,
  episodeNumber,
  expanded,
  onToggle,
}: {
  shot: StoryboardShotView
  settled: boolean
  episodeNumber: number
  expanded: boolean
  onToggle: (key: string) => void
}) {
  const active = !settled && Boolean(shot.active)
  const title = shot.title || `第 ${shot.index + 1} 镜`
  const duration = shotDurationLabel(shot)
  const shotKey = `${episodeNumber}-${shot.index}`
  if (active) {
    return (
      <div className="director-shot-stream-row is-active">
        <span className="director-shot-no">{shot.index + 1}</span>
        <div className="director-shot-stream-text">
          <strong>{title}<span className="stream-caret" aria-hidden /></strong>
          {shot.description ? <p>{shot.description}</p> : null}
          {shot.dialogue ? <p className="is-dialogue">「{shot.dialogue}」</p> : null}
        </div>
      </div>
    )
  }
  const canExpand = Boolean(shot.description || shot.dialogue)
  return (
    <div className="director-shot-stream-item">
      {canExpand ? (
        <button
          type="button"
          className="director-shot-stream-row is-done is-expandable"
          aria-expanded={expanded}
          onClick={() => onToggle(shotKey)}
        >
          <span className="director-shot-no">{shot.index + 1}</span>
          <span className="director-shot-stream-title">{title}</span>
          {duration ? <span className="director-shot-stream-meta">{duration}</span> : null}
          <CheckCircle2 size={12} className="director-shot-stream-check" aria-hidden />
        </button>
      ) : (
        <div className="director-shot-stream-row is-done">
          <span className="director-shot-no">{shot.index + 1}</span>
          <span className="director-shot-stream-title">{title}</span>
          {duration ? <span className="director-shot-stream-meta">{duration}</span> : null}
          <CheckCircle2 size={12} className="director-shot-stream-check" aria-hidden />
        </div>
      )}
      {canExpand ? (
        <div className={`director-shot-stream-fold${expanded ? " is-open" : ""}`} {...(!expanded ? { inert: true } : {})}>
          <div>
            <div className="director-shot-stream-text">
              {shot.description ? <p>{shot.description}</p> : null}
              {shot.dialogue ? <p className="is-dialogue">「{shot.dialogue}」</p> : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function EpisodeCapsule({
  episodeNumber,
  title,
  status,
  open,
  index,
  shotCount,
  onToggle,
  children,
}: {
  episodeNumber: number
  title: string
  status: StoryboardEpisodeRowStatus
  open: boolean
  index: number
  shotCount: number
  onToggle: (key: string, currentlyOpen: boolean) => void
  children: ReactNode
}) {
  const bodyId = `director-episode-row-body-${episodeNumber}`
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
          <div className="director-episode-row-body">{children}</div>
        </div>
      </div>
    </section>
  )
}

function WritingEpisodeBody({
  episode,
  settled,
  openShots,
  onToggleShot,
}: {
  episode: StoryboardEpisodeView
  settled: boolean
  openShots: Record<string, boolean>
  onToggleShot: (key: string) => void
}) {
  return (
    <>
      {episode.scenes.map((scene) => (
        <div key={`scene-${episode.number}-${scene.index}`} className="director-shot-scene">【{scene.title || "场景"}】</div>
      ))}
      {episode.shots.map((shot) => (
        <ShotStreamRow
          key={`shot-${episode.number}-${shot.index}`}
          shot={shot}
          settled={settled}
          episodeNumber={episode.number}
          expanded={Boolean(openShots[`${episode.number}-${shot.index}`])}
          onToggle={onToggleShot}
        />
      ))}
    </>
  )
}

export default function DirectorStoryboardLiveBody({ settled = false, ...input }: DirectorStoryboardLiveBodyProps) {
  const model = buildStoryboardStreamModel({ ...input, live: !settled && input.live !== false })
  const live = !settled && input.live !== false
  const [manualOpen, setManualOpen] = useState<Record<string, boolean>>({})
  const [openShots, setOpenShots] = useState<Record<string, boolean>>({})
  const toggleEpisode = (key: string, currentlyOpen: boolean) => {
    setManualOpen((current) => ({ ...current, [key]: !currentlyOpen }))
  }
  const toggleShot = (key: string) => {
    setOpenShots((current) => ({ ...current, [key]: !current[key] }))
  }
  if (!model.episodes.length && !model.polish) {
    if (!live) return null
    return <div className="director-phase-panel">
      <div className="director-phase-head"><span className="director-phase-title">等待模型开始输出</span></div>
      <div className="director-live-skeleton" aria-hidden><span style={{ width: "52%" }} /><span style={{ width: "70%" }} /></div>
      <div className="director-phase-meta is-live"><span className="director-live-dot" aria-hidden />远端模型正在阅读剧本，开始输出后会逐镜出现</div>
    </div>
  }
  if (live && model.polish) {
    const phase = model.polish
    const groups = groupPolishShotNumbers(model.episodes)
    const shotCount = groups.reduce((sum, group) => sum + group.numbers.length, 0)
    const writingWait = phase.title === "写分镜" || phase.title === "阅读剧本并构思" || phase.title === "重拆不完整镜头"
    if (shotCount === 0) {
      const currentShot = resolvePolishCurrentShot(phase, model.polishLive)
      const liveLabel = currentShot != null ? `正在打磨第 ${currentShot} 镜…` : `正在${phase.title}…`
      return <div className="director-phase-panel">
        <div className="director-phase-head"><span className="director-phase-title">{polishPhaseTitle(phase)}</span></div>
        <div className="director-live-skeleton" aria-hidden><span style={{ width: "52%" }} /><span style={{ width: "70%" }} /></div>
        <div className="director-shot-stream-row is-active director-phase-live"><span className="director-shot-no">{currentShot ?? "…"}</span><div className="director-shot-stream-text"><strong><span className="is-skeleton">{liveLabel}</span></strong></div></div>
        {phase.chars ? <div className="director-phase-meta is-live"><span className="director-live-dot" aria-hidden />已收 {phase.chars.toLocaleString()} 字</div> : <div className="director-phase-meta is-live"><span className="director-live-dot" aria-hidden />开始输出后会显示字数与镜头</div>}
      </div>
    }
    if (!writingWait) {
      const currentShot = resolvePolishCurrentShot(phase, model.polishLive)
      const liveLabel = currentShot != null ? `正在打磨第 ${currentShot} 镜…` : `正在${phase.title}…`
      const legend = polishShotLegend(phase, groups)
      return <div className="director-block-shots">
        <div className="director-phase-head"><span className="director-phase-title">{polishPhaseTitle(phase)}</span></div>
        {legend ? <div className="director-phase-legend">{legend}</div> : null}
        {groups.map((group, index) => {
          const episode = model.episodes.find((item) => item.number === group.episode)
          const status = resolvePolishGroupStatus(group, currentShot, phase.range)
          const open = manualOpen[String(group.episode)] ?? status === "running"
          return (
            <EpisodeCapsule
              key={group.episode}
              episodeNumber={group.episode}
              title={episode?.title || group.label}
              status={status}
              open={open}
              index={index}
              shotCount={group.numbers.length}
              onToggle={toggleEpisode}
            >
              <div className="director-phase-shots">
                {group.numbers.map((no, localIndex) => (
                  <span
                    key={no}
                    className={`director-phase-chip${chipState(no, currentShot, phase.range)}`}
                    title={`${episode?.title || group.label} · 第 ${localIndex + 1} 镜（全剧第 ${no} 镜）`}
                  >{localIndex + 1}</span>
                ))}
              </div>
              {status === "running" ? (
                <div className="director-shot-stream-row is-active director-phase-live">
                  <span className="director-shot-no">{currentShot ?? "…"}</span>
                  <div className="director-shot-stream-text">
                    <strong>{model.polishLive?.description || model.polishLive?.dialogue ? liveLabel : <span className="is-skeleton">{liveLabel}</span>}</strong>
                    {model.polishLive?.description ? <p>{model.polishLive.description}</p> : null}
                    {model.polishLive?.dialogue ? <p className="is-dialogue">「{model.polishLive.dialogue}」</p> : null}
                  </div>
                </div>
              ) : null}
            </EpisodeCapsule>
          )
        })}
        {phase.chars ? <div className="director-phase-meta is-live"><span className="director-live-dot" aria-hidden />已收 {phase.chars.toLocaleString()} 字</div> : null}
      </div>
    }
  }
  const activeEpisode = resolveActiveEpisodeNumber(model.episodes, { live, polish: model.polish })
  return <div className="director-block-shots">
    {model.episodes.map((episode, index) => {
      const status = resolveEpisodeRowStatus(episode, activeEpisode)
      const open = manualOpen[String(episode.number)] ?? status === "running"
      return (
        <EpisodeCapsule
          key={episode.number}
          episodeNumber={episode.number}
          title={episode.title}
          status={status}
          open={open}
          index={index}
          shotCount={episode.shots.length}
          onToggle={toggleEpisode}
        >
          <WritingEpisodeBody episode={episode} settled={settled} openShots={openShots} onToggleShot={toggleShot} />
        </EpisodeCapsule>
      )
    })}
  </div>
}
