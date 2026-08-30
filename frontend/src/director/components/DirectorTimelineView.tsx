import { Button, Dropdown, Empty, Progress, Space, Tag, Typography, message } from "antd"
import { Clapperboard, MoreHorizontal, Pause, Play } from "lucide-react"
import { CSSProperties, useEffect, useMemo, useRef, useState } from "react"
import { directorStatusColor, directorStatusLabel } from "../status-labels"
import { snapH3DurationSec } from "../prompt-compiler"
import type { RecipeProject, RecipeShot } from "../recipe-model"
import {
  assignRecipeShotPlate,
  dressedRecipePlates,
  recipePlayableShots,
  recipeShotLayout,
  recipeShotStillUrl,
  recipeTimelineMinimumPixelsPerSecond,
  recipeShotVideoUrl,
} from "../recipe-timeline"
import RecipeShotInspector from "./RecipeShotInspector"
import TimelineRuler from "./TimelineRuler"
import TimelineTrackMain from "./TimelineTrackMain"

type JobLike = {
  id: string
  status?: string
  stage?: string
  progress?: number
  error?: string | null
}

function recipeAspectVars(ratio: string): CSSProperties {
  const match = ratio.match(/(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)/)
  const width = match ? Number(match[1]) : 16
  const height = match ? Number(match[2]) : 9
  return {
    "--shot-aspect": `${width} / ${height}`,
    "--shot-aspect-w": String(width),
    "--shot-aspect-h": String(height),
  } as CSSProperties
}

export default function DirectorTimelineView({
  recipe,
  shots,
  selectedShot,
  previousShot,
  checkedShotIds,
  jobs,
  submittingShotIds,
  submittingStillIds,
  ttsBusy = false,
  generatingBoard = false,
  pipelineError,
  pipelinePercent = 0,
  pipelineStage,
  boardActionLabel,
  boardBusy = false,
  running = false,
  failedShotCount = 0,
  onSelectShot,
  onSetCheckedShotIds,
  onChangeShot,
  onAddShot,
  onDeleteShot,
  onDuplicateShot,
  onRenderShot,
  onGenerateStill,
  onUploadFrame,
  onExtractEndFrame,
  onGenerateTts,
  onGenerateBoard,
  onGenerateSelected,
  onRetryFailed,
  onCancelSelected,
}: {
  recipe: RecipeProject
  shots: RecipeShot[]
  selectedShot: RecipeShot | null
  previousShot?: RecipeShot | null
  checkedShotIds: string[]
  jobs: JobLike[]
  submittingShotIds: string[]
  submittingStillIds: string[]
  ttsBusy?: boolean
  generatingBoard?: boolean
  pipelineError?: string
  pipelinePercent?: number
  pipelineStage?: string | null
  boardActionLabel: string
  boardBusy?: boolean
  running?: boolean
  failedShotCount?: number
  onSelectShot: (shotId: string) => void
  onSetCheckedShotIds: (ids: string[]) => void
  onChangeShot: (shotId: string, patch: Partial<RecipeShot>) => void
  onAddShot: () => void
  onDeleteShot: (shotId: string) => void
  onDuplicateShot: (shotId: string) => void
  onRenderShot: (shotId: string) => void
  onGenerateStill: (shotId: string) => void
  onUploadFrame: (shotId: string, slot: "first" | "end", file: File) => Promise<void>
  onExtractEndFrame: (shotId: string, file: File) => Promise<void>
  onGenerateTts: (shotId: string) => void
  onGenerateBoard: () => void
  onGenerateSelected: () => void
  onRetryFailed: () => void
  onCancelSelected: () => void
}) {
  const plates = useMemo(() => dressedRecipePlates(recipe), [recipe])
  const playable = useMemo(() => recipePlayableShots(shots), [shots])
  const layout = useMemo(() => recipeShotLayout(shots), [shots])
  const playableLayout = useMemo(
    () => layout.filter((item) => playable.some((shot) => shot.id === item.shot.id)),
    [layout, playable],
  )
  const totalDurationSec = layout[layout.length - 1]?.endSec || 0
  const [playheadSec, setPlayheadSec] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [pixelsPerSecond, setPixelsPerSecond] = useState(48)
  const [unit, setUnit] = useState<"seconds" | "frames">("seconds")
  const [snapEnabled, setSnapEnabled] = useState(true)
  const [scrollLeft, setScrollLeft] = useState(0)
  const videoRef = useRef<HTMLVideoElement>(null)
  const minPixelsPerSecond = useMemo(() => recipeTimelineMinimumPixelsPerSecond(shots), [shots])
  const playheadShot = playing
    ? playableLayout.find((item) => playheadSec >= item.startSec && playheadSec < item.endSec)
      || playableLayout.find((item) => item.startSec >= playheadSec)
      || playableLayout[playableLayout.length - 1]
    : layout.find((item) => playheadSec >= item.startSec && playheadSec < item.endSec)
      || layout[layout.length - 1]
  const previewShot = playing ? playheadShot?.shot || selectedShot : selectedShot
  const previewVideo = previewShot ? recipeShotVideoUrl(previewShot) : ""
  const previewStill = previewShot ? recipeShotStillUrl(previewShot) : ""

  useEffect(() => {
    if (pixelsPerSecond < minPixelsPerSecond) setPixelsPerSecond(minPixelsPerSecond)
  }, [minPixelsPerSecond, pixelsPerSecond])

  useEffect(() => {
    if (playing || !selectedShot) return
    const item = layout.find((entry) => entry.shot.id === selectedShot.id)
    if (item && Math.abs(playheadSec - item.startSec) > item.shot.durationSec) {
      setPlayheadSec(item.startSec)
    }
  }, [layout, playheadSec, playing, selectedShot])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !previewVideo) return
    if (playing) {
      const offset = Math.max(0, playheadSec - (playheadShot?.startSec || 0))
      if (Math.abs(video.currentTime - offset) > 0.35) video.currentTime = offset
      video.play().catch(() => {})
      return
    }
    video.pause()
  }, [playheadShot?.startSec, playheadSec, playing, previewVideo])

  function seekTo(timeSec: number) {
    const next = Math.min(Math.max(0, timeSec), Math.max(totalDurationSec, 0))
    setPlayheadSec(next)
    const hit = layout.find((item) => next >= item.startSec && next < item.endSec)
      || layout[layout.length - 1]
    if (hit) onSelectShot(hit.shot.id)
  }

  function startSequence() {
    if (!playable.length) {
      message.warning("还没有已生成的镜头可串播")
      return
    }
    const fromSelected = selectedShot && playable.some((shot) => shot.id === selectedShot.id)
      ? selectedShot
      : playable[0]
    const item = layout.find((entry) => entry.shot.id === fromSelected.id)
    setPlayheadSec(item?.startSec || 0)
    onSelectShot(fromSelected.id)
    setPlaying(true)
  }

  function handleVideoTime(currentTime: number) {
    if (!playing || !playheadShot) return
    setPlayheadSec(playheadShot.startSec + currentTime)
  }

  function handleVideoEnded() {
    if (!playing || !previewShot) {
      setPlaying(false)
      return
    }
    const index = playableLayout.findIndex((item) => item.shot.id === previewShot.id)
    const next = playableLayout[index + 1]
    if (!next) {
      setPlaying(false)
      return
    }
    setPlayheadSec(next.startSec)
    onSelectShot(next.shot.id)
  }

  function handleAssignPlate(plate: { name: string; kind: "character" | "location" }) {
    if (!selectedShot) {
      message.warning("请先在时间轴选中一镜")
      return
    }
    const result = assignRecipeShotPlate(recipe, selectedShot, plate)
    if (result.rejected) {
      message.warning("本镜参考图已满 9 张，请先去掉一个角色或场景")
      return
    }
    onChangeShot(selectedShot.id, {
      characterNames: result.shot.characterNames,
      locationName: result.shot.locationName,
    })
  }

  return (
    <div className="director-timeline-view" style={recipeAspectVars(recipe.aspectRatio)}>
      <aside className="director-timeline-assets">
        <Typography.Title level={5}>定妆素材</Typography.Title>
        <p className="director-output-hint">点选中镜头后加入角色或场景，装箱仍走现有参考图规则。</p>
        {plates.length ? (
          <ul className="director-timeline-asset-list">
            {plates.map((plate) => {
              const active = selectedShot
                ? plate.kind === "location"
                  ? selectedShot.locationName === plate.name
                  : selectedShot.characterNames.includes(plate.name)
                : false
              return (
                <li key={`${plate.kind}-${plate.id}`}>
                  <button
                    type="button"
                    className={`director-timeline-asset${active ? " is-active" : ""}`}
                    onClick={() => handleAssignPlate(plate)}
                  >
                    <img src={plate.imageUrl} alt="" />
                    <span>
                      <strong>{plate.name}</strong>
                      <em>{plate.kind === "location" ? "场景" : "角色"}</em>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先在方案视图完成角色或场景定妆" />
        )}
      </aside>

      <div className="director-timeline-center">
        <div className="director-timeline-preview">
          <div className="director-timeline-preview-bar">
            <div>
              <strong>{previewShot ? `#${previewShot.shotNumber} ${previewShot.title}` : "镜头预览"}</strong>
              {previewShot ? <Tag color={directorStatusColor(previewShot.status)}>{directorStatusLabel(previewShot.status)}</Tag> : null}
            </div>
            <Space wrap>
              <Button
                icon={playing ? <Pause size={14} /> : <Play size={14} />}
                disabled={!playable.length}
                onClick={() => playing ? setPlaying(false) : startSequence()}
              >
                {playing ? "暂停串播" : "串播"}
              </Button>
              <Dropdown
                trigger={["click"]}
                menu={{
                  items: [
                    { key: "selected", label: `生成选中（${checkedShotIds.length}）`, disabled: !checkedShotIds.length || running },
                    { key: "retry", label: `仅重试失败项（${failedShotCount}）`, disabled: !failedShotCount || running },
                    { key: "cancel", label: "取消选中任务", disabled: !checkedShotIds.length },
                  ],
                  onClick: ({ key }) => {
                    if (key === "selected") onGenerateSelected()
                    if (key === "retry") onRetryFailed()
                    if (key === "cancel") onCancelSelected()
                  },
                }}
              >
                <Button icon={<MoreHorizontal size={14} />}>批量操作{checkedShotIds.length ? ` · ${checkedShotIds.length}` : ""}</Button>
              </Dropdown>
              <Button type="primary" icon={<Clapperboard size={14} />} loading={boardBusy} disabled={!shots.length || running} onClick={onGenerateBoard}>
                {boardActionLabel}
              </Button>
            </Space>
          </div>
          <div className="director-timeline-monitor">
            {previewVideo ? (
              <video
                ref={videoRef}
                key={previewVideo}
                src={previewVideo}
                controls={!playing}
                playsInline
                onTimeUpdate={(event) => handleVideoTime(event.currentTarget.currentTime)}
                onEnded={handleVideoEnded}
              />
            ) : previewStill ? (
              <img src={previewStill} alt="" />
            ) : generatingBoard ? (
              <div className="director-timeline-monitor-empty">
                <Progress percent={pipelinePercent} status="active" />
                <p>{pipelineStage || "正在根据剧本生成全部分镜"}</p>
              </div>
            ) : (
              <div className="director-timeline-monitor-empty">
                <Clapperboard size={22} />
                <strong>{shots.length ? "这一镜还没有成片" : "还没有分镜"}</strong>
                <span>{shots.length ? "在右侧生成这一镜，或点串播查看已出片镜头" : "根据剧本生成分镜后即可在时间轴剪辑"}</span>
              </div>
            )}
          </div>
        </div>

        <div className="director-timeline-panel">
          {shots.length ? (
            <>
              <TimelineRuler
                shots={shots}
                totalDurationSec={totalDurationSec}
                currentTimeSec={playheadSec}
                pixelsPerSecond={pixelsPerSecond}
                minPixelsPerSecond={minPixelsPerSecond}
                unit={unit}
                snapEnabled={snapEnabled}
                scrollLeft={scrollLeft}
                onSeek={seekTo}
                onUnitToggle={() => setUnit((current) => current === "seconds" ? "frames" : "seconds")}
                onZoomChange={setPixelsPerSecond}
                onSnapChange={setSnapEnabled}
              />
              <TimelineTrackMain
                shots={shots}
                selectedShotId={selectedShot?.id}
                checkedShotIds={checkedShotIds}
                pixelsPerSecond={pixelsPerSecond}
                currentTimeSec={playheadSec}
                onSelectShot={(shot, additive) => {
                  setPlaying(false)
                  const item = layout.find((entry) => entry.shot.id === shot.id)
                  if (item) setPlayheadSec(item.startSec)
                  if (additive) {
                    const next = checkedShotIds.includes(shot.id)
                      ? checkedShotIds.filter((id) => id !== shot.id)
                      : [...checkedShotIds, shot.id]
                    onSetCheckedShotIds(next)
                  }
                  onSelectShot(shot.id)
                }}
                onSetCheckedShotIds={onSetCheckedShotIds}
                onAddShot={onAddShot}
                onDeleteShot={onDeleteShot}
                onDuplicateShot={(shot) => onDuplicateShot(shot.id)}
                onUpdateShotDuration={(shotId, durationSec) => onChangeShot(shotId, { durationSec: snapH3DurationSec(durationSec) })}
                onCanvasScroll={setScrollLeft}
                onSeek={seekTo}
              />
            </>
          ) : (
            <div className="director-timeline-empty">
              <Empty description={pipelineError ? "分镜生成失败" : "还没有可剪辑的镜头"}>
                <Button type="primary" loading={running} disabled={running} onClick={onGenerateBoard}>
                  根据剧本生成全部分镜
                </Button>
              </Empty>
            </div>
          )}
        </div>
      </div>

      <aside className="director-timeline-inspector">
        {selectedShot ? (
          <RecipeShotInspector
            shot={selectedShot}
            recipe={recipe}
            previousShot={previousShot}
            job={jobs.find((entry) => entry.id === selectedShot.jobId)}
            stillJob={jobs.find((entry) => entry.id === selectedShot.stillJobId)}
            compareDesktop
            onChange={(patch) => onChangeShot(selectedShot.id, patch)}
            submitting={submittingShotIds.includes(selectedShot.id)}
            submittingStill={submittingStillIds.includes(selectedShot.id)}
            onRender={() => onRenderShot(selectedShot.id)}
            onGenerateStill={() => onGenerateStill(selectedShot.id)}
            onUploadFrame={(slot, file) => onUploadFrame(selectedShot.id, slot, file)}
            onExtractEndFrame={(file) => onExtractEndFrame(selectedShot.id, file)}
            onGenerateTts={() => onGenerateTts(selectedShot.id)}
            ttsBusy={ttsBusy}
          />
        ) : (
          <div className="director-inspector-empty">
            <Clapperboard size={22} />
            <strong>选中一镜后编辑</strong>
            <span>提示词、首尾帧、Takes 和生成这一镜都在这里</span>
          </div>
        )}
      </aside>
    </div>
  )
}
