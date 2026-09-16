import { useState, type ReactNode } from "react"
import DirectorEpisodeCapsule from "../director/components/DirectorEpisodeCapsule"
import type { StoryboardEpisodeRowStatus } from "../director/storyboard-stream-view"
import {
  groupScriptLiveView,
  parseScriptLiveView,
  scriptLiveSourceHasContent,
  visibleShotFields,
  type ScriptLiveBlock,
  type ScriptLiveSource,
} from "./director2-script-live-view"

type Director2ScriptLiveBodyProps = Partial<ScriptLiveSource> & {
  live?: boolean
}

function Caret({ show }: { show: boolean }) {
  return show ? <span className="stream-caret" aria-hidden /> : null
}

function BlockText({ children, caret }: { children: ReactNode; caret: boolean }) {
  return (
    <>
      {children}
      <Caret show={caret} />
    </>
  )
}

export function ScriptLiveBlocks({
  text,
  blocks,
  caret = false,
}: {
  text?: string
  blocks?: ScriptLiveBlock[]
  caret?: boolean
}) {
  const resolved = blocks ?? parseScriptLiveView(text || "")
  if (!resolved.length) {
    return caret ? <p className="director-stream-caret-line"><Caret show /></p> : null
  }
  const last = resolved.length - 1
  return (
    <>
      {resolved.map((block, index) => {
        const mark = caret && index === last
        if (block.type === "blank") {
          return mark ? <p key={index} className="director-stream-caret-line"><Caret show /></p> : <p key={index} className="is-blank">&nbsp;</p>
        }
        if (block.type === "title") {
          return <h4 key={index} className="director-script-ms-title"><BlockText caret={mark}>{block.text}</BlockText></h4>
        }
        if (block.type === "heading") {
          const scene = block.text.startsWith("【") && block.text.includes("】")
          return <h4 key={index} className={scene ? "is-scene" : "director-script-ms-heading"}><BlockText caret={mark}>{block.text}</BlockText></h4>
        }
        if (block.type === "episode") {
          return <h4 key={index} className="is-episode"><BlockText caret={mark}>{block.text}</BlockText></h4>
        }
        if (block.type === "plot") {
          return <p key={index} className="is-plot"><BlockText caret={mark}>{block.text}</BlockText></p>
        }
        if (block.type === "shot") {
          const fields = visibleShotFields(block.fields)
          return (
            <section key={index} className="director-script-shot-card">
              <h5 className="is-shot"><BlockText caret={mark && !fields.length}>{block.heading}</BlockText></h5>
              {fields.map((field, fieldIndex) => {
                const lastField = mark && fieldIndex === fields.length - 1
                const dialogue = field.label === "台词"
                return (
                  <p
                    key={`${field.label}-${fieldIndex}`}
                    className={dialogue ? "director-script-shot-field is-dialogue" : "director-script-shot-field"}
                  >
                    <span className="director-script-shot-label">{field.label}</span>
                    <BlockText caret={lastField}>{field.value}</BlockText>
                  </p>
                )
              })}
            </section>
          )
        }
        const scene = block.text.startsWith("【") && block.text.includes("】")
        return <p key={index} className={scene ? "is-scene" : undefined}><BlockText caret={mark}>{block.text}</BlockText></p>
      })}
    </>
  )
}

function scriptEpisodeStatus(
  index: number,
  total: number,
  live: boolean,
): StoryboardEpisodeRowStatus {
  if (!live) return "completed"
  if (index === total - 1) return "running"
  return "completed"
}

export default function Director2ScriptLiveBody({ title, summary, fullStory, live = false }: Director2ScriptLiveBodyProps) {
  const sourceTitle = (title || "").trim()
  const sourceSummary = (summary || "").trim()
  const sourceStory = (fullStory || "").trim()
  const [manualOpen, setManualOpen] = useState<Record<string, boolean>>({})
  if (!scriptLiveSourceHasContent({ title: sourceTitle, summary: sourceSummary, fullStory: sourceStory })) return null
  const blocks = parseScriptLiveView(sourceStory, { skipTitle: sourceTitle })
  const grouped = groupScriptLiveView(blocks)
  const useCapsules = grouped.episodes.length > 0
  const toggleEpisode = (key: string, currentlyOpen: boolean) => {
    setManualOpen((current) => ({ ...current, [key]: !currentlyOpen }))
  }

  return (
    <div className="director-stream-article">
      {sourceTitle ? <h3 className="director-stream-title">{sourceTitle}</h3> : null}
      {sourceSummary ? <p className="director-stream-lead">{sourceSummary}</p> : null}
      {useCapsules ? (
        <div className="director-stream-text is-script-episodes">
          {grouped.preamble.length ? <ScriptLiveBlocks blocks={grouped.preamble} /> : null}
          <div className="director-block-shots is-script">
            {grouped.episodes.map((episode, index) => {
              const status = scriptEpisodeStatus(index, grouped.episodes.length, live)
              const key = String(episode.number)
              const open = manualOpen[key] ?? (live && status === "running")
              const caret = live && index === grouped.episodes.length - 1
              return (
                <DirectorEpisodeCapsule
                  key={`${episode.number}-${episode.title}`}
                  episodeNumber={episode.number}
                  title={episode.title}
                  status={status}
                  open={open}
                  index={index}
                  shotCount={episode.shotCount}
                  onToggle={toggleEpisode}
                  bodyClassName="is-script"
                  idPrefix="director-script-episode-body"
                >
                  <ScriptLiveBlocks blocks={episode.blocks} caret={caret} />
                </DirectorEpisodeCapsule>
              )
            })}
          </div>
        </div>
      ) : blocks.length || live ? (
        <div className="director-stream-text">
          <ScriptLiveBlocks blocks={blocks} caret={live} />
        </div>
      ) : null}
    </div>
  )
}
