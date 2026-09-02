import { Button, Checkbox, Collapse, Input, InputNumber, Progress, Segmented, Select, Space, Tag, message } from "antd"
import { Clapperboard, Copy, ImagePlus, Star } from "lucide-react"
import { CSSProperties, ReactNode, useEffect, useMemo, useRef, useState } from "react"
import JobErrorNotice from "./JobErrorNotice"
import TakeGenerationParams from "./TakeGenerationParams"
import ShotCameraFields from "./ShotCameraFields"
import {
  H3_MAX_DURATION_SEC,
  H3_MIN_DURATION_SEC,
  compileRecipeShotPreview,
  directorRenderPassLabel,
  snapH3DurationSec,
  workflowRouteLabel,
} from "../prompt-compiler"
import { extractVideoFrame, overlaySubmittingState, shotGenerationState } from "../director-submit"
import { directorStatusColor, directorStatusLabel, isDirectorFailedStatus } from "../status-labels"
import {
  CameraDirection, RecipeProject, RecipeShot, ShotTake, TTS_VOICE_OPTIONS, defaultCameraDirection,
  recipePackedPlates, recipeShotPreferredTake,
} from "../types"
import { dialogueTimingWarning } from "../dialogue-timing"

type JobLike = {
  id: string
  status?: string
  stage?: string
  progress?: number
  error?: string | null
  mode?: string
  options?: Record<string, unknown>
  outputs?: Array<{ kind?: string; download_url?: string; cloud_url?: string; path?: string }>
}

function takeVideoUrl(take: ShotTake | undefined) {
  return take?.videoUrl || ""
}

function takeId(take: ShotTake | undefined) {
  return take?.id || take?.jobId || ""
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

function ShotPreviewFrame({ children, empty = false }: { children: ReactNode; empty?: boolean }) {
  return (
    <div className={`director-inspector-frame${empty ? " is-empty" : ""}`}>
      {children}
    </div>
  )
}

type InspectorTab = "script" | "shot" | "produce"

export default function RecipeShotInspector({
  shot,
  recipe,
  previousShot,
  job,
  stillJob,
  takeJobs = [],
  compareDesktop = true,
  onChange,
  onRender,
  onGenerateStill,
  onUploadFrame,
  onExtractEndFrame,
  onGenerateTts,
  ttsBusy = false,
  submitting = false,
  submittingStill = false,
}: {
  shot: RecipeShot
  recipe: RecipeProject
  previousShot?: RecipeShot | null
  job?: JobLike
  stillJob?: JobLike
  takeJobs?: JobLike[]
  compareDesktop?: boolean
  onChange: (patch: Partial<RecipeShot>) => void
  onRender: () => void
  onGenerateStill: () => void
  onUploadFrame: (slot: "first" | "end", file: File) => Promise<void>
  onExtractEndFrame?: (file: File) => Promise<void>
  onGenerateTts?: () => void
  ttsBusy?: boolean
  submitting?: boolean
  submittingStill?: boolean
}) {
  const firstInputRef = useRef<HTMLInputElement>(null)
  const endInputRef = useRef<HTMLInputElement>(null)
  const [compareTakeId, setCompareTakeId] = useState<string | null>(null)
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("script")
  const [extracting, setExtracting] = useState(false)
  const [messageApi, messageContextHolder] = message.useMessage()
  const state = overlaySubmittingState(
    shotGenerationState(job, shot.outputVideoUrl, shot.jobId, {
      status: shot.status,
      progress: shot.progress,
    }),
    submitting,
    "正在润色提示词并提交…",
  )
  const stillState = overlaySubmittingState(
    shotGenerationState(stillJob, shot.stillUrl, shot.stillJobId, {
      status: shot.stillStatus || "idle",
      progress: 0,
    }),
    submittingStill,
    "正在提交静帧…",
  )
  const displayStatus = state.generating ? state.status : (state.status !== "idle" ? state.status : shot.status)
  const failed = !state.generating && isDirectorFailedStatus(displayStatus)
  const takes = shot.takes || []
  const approvedId = shot.approvedTakeId || ""
  const preferredTake = recipeShotPreferredTake(shot)
  const defaultTakeId = takeId(preferredTake) || takeId(takes[takes.length - 1])
  const [previewTakeId, setPreviewTakeId] = useState(defaultTakeId)
  const previewShotIdRef = useRef(shot.id)
  useEffect(() => {
    if (previewShotIdRef.current !== shot.id) {
      previewShotIdRef.current = shot.id
      setPreviewTakeId(defaultTakeId)
      setCompareTakeId(null)
      return
    }
    setPreviewTakeId((current) => (
      takes.some((take) => takeId(take) === current) ? current : defaultTakeId
    ))
  }, [defaultTakeId, shot.id, takes])
  const foundActiveIndex = takes.findIndex((take) => takeId(take) === previewTakeId)
  const activeIndex = foundActiveIndex >= 0 ? foundActiveIndex : Math.max(0, takes.length - 1)
  const activeTake = takes[activeIndex]
  const videoUrl = takeVideoUrl(activeTake) || shot.outputVideoUrl || ""
  const showVideo = Boolean(videoUrl)
  const showGenerationBadge = state.generating || stillState.generating
  const inheritedFirst = shot.usePreviousEndFrame
    ? (previousShot?.endFrameUrl || previousShot?.stillUrl || "")
    : ""
  const firstPreview = inheritedFirst || shot.firstFrameUrl || shot.stillUrl || ""
  const plates = recipePackedPlates(recipe, shot)
  const camera = shot.camera || defaultCameraDirection()
  const compareTake = takes.find((item) => takeId(item) === compareTakeId && takeId(item) !== takeId(activeTake))
  const previousHasEnd = Boolean(previousShot?.endFrameUrl || previousShot?.stillUrl)
  const submission = useMemo(
    () => compileRecipeShotPreview(recipe, shot, previousShot),
    [recipe, shot, previousShot],
  )
  const submittedSnapshot = (activeTake?.promptSnapshot || shot.compiledPrompt || "").trim()
  const promptTextLooksChinese = /[\u4e00-\u9fff]/.test(shot.promptText || "") && !(shot.promptText || "").toLowerCase().includes("the camera")
  const dialogueDurationHint = useMemo(
    () => dialogueTimingWarning(shot.dialogue, shot.durationSec),
    [shot.dialogue, shot.durationSec],
  )

  function jobForTake(take: ShotTake | undefined) {
    if (!take?.jobId) return undefined
    return takeJobs.find((entry) => entry.id === take.jobId)
  }

  async function handleExtractEnd() {
    if (!videoUrl || !onExtractEndFrame) return
    setExtracting(true)
    try {
      const captured = await extractVideoFrame(videoUrl)
      await onExtractEndFrame(captured.file)
    } finally {
      setExtracting(false)
    }
  }

  function selectTake(index: number) {
    const take = takes[index]
    if (!take) return
    setPreviewTakeId(take.id || take.jobId || "")
  }

  function approveTake(take: ShotTake) {
    const id = take.id || take.jobId || ""
    if (!id) return
    setPreviewTakeId(id)
    onChange({ approvedTakeId: id })
  }

  const comparing = Boolean(compareDesktop && showVideo && compareTake?.videoUrl)
  const emptyPreview = !showVideo && !firstPreview

  return (
    <div className="director-recipe-inspector" style={recipeAspectVars(recipe.aspectRatio)}>
      {messageContextHolder}
      <div className="director-inspector-picture">
        <div className={`director-inspector-stage${comparing ? " is-compare" : ""}`}>
          {comparing && compareTake?.videoUrl ? (
            <>
              <div className="director-take-compare-panel">
                <ShotPreviewFrame>
                  <video src={videoUrl} controls playsInline />
                </ShotPreviewFrame>
                <TakeGenerationParams take={activeTake} job={jobForTake(activeTake)} compact />
              </div>
              <div className="director-take-compare-panel">
                <ShotPreviewFrame>
                  <video src={compareTake.videoUrl} controls playsInline />
                </ShotPreviewFrame>
                <TakeGenerationParams
                  take={compareTake}
                  job={jobForTake(compareTake)}
                  compareTake={activeTake}
                  compareJob={jobForTake(activeTake)}
                  compact
                />
              </div>
            </>
          ) : (
            <ShotPreviewFrame empty={emptyPreview}>
              {showVideo ? (
                <video src={videoUrl} controls playsInline />
              ) : firstPreview ? (
                <img src={firstPreview} alt="分镜画面" />
              ) : (
                <div className="director-inspector-empty">
                  {state.generating || stillState.generating ? (
                    <>
                      <Progress percent={state.generating ? state.progress : stillState.progress} size="small" status="active" showInfo={false} />
                      <span>{state.generating ? state.label : "静帧生成中"}</span>
                    </>
                  ) : (
                    <>
                      <Clapperboard size={22} />
                      <strong>还没有成片</strong>
                      <span>可先出静帧，或改完导演参数后生成这一镜</span>
                    </>
                  )}
                </div>
              )}
            </ShotPreviewFrame>
          )}
        </div>
        {showGenerationBadge && (showVideo || firstPreview) ? (
          <div className="director-inspector-generation-bar">
            <Progress
              percent={state.generating ? state.progress : stillState.progress}
              size="small"
              status="active"
              showInfo={false}
            />
            <span>{state.generating ? state.label : stillState.label || "静帧生成中"}</span>
          </div>
        ) : null}
        <div className="director-inspector-heading">
          <Tag color={directorStatusColor(displayStatus)}>{directorStatusLabel(displayStatus)}</Tag>
          {shot.stillUrl ? <Tag>静帧</Tag> : null}
          {activeTake?.renderPass ? <Tag>{directorRenderPassLabel(activeTake.renderPass)}</Tag> : null}
          <span>{shot.durationSec}s</span>
        </div>
        {takes.length ? (
          <section className="director-take-rail" aria-label="镜头版本切换">
            <div className="director-take-rail-head">
              <strong>Takes ({takes.length})</strong>
              {approvedId ? <Tag color="success">已批准</Tag> : null}
            </div>
            <div className="director-take-rail-list">
              {takes.map((take, index) => {
                const selected = index === activeIndex
                const approved = takeId(take) === approvedId
                const id = takeId(take)
                return (
                  <div
                    key={id || index}
                    className={`director-take-rail-item${selected ? " is-active" : ""}${approved ? " is-approved" : ""}`}
                  >
                    <button type="button" className="director-take-rail-preview" onClick={() => selectTake(index)}>
                      {take.videoUrl ? (
                        <video src={take.videoUrl} muted playsInline />
                      ) : (
                        <span>Take {take.takeNumber}</span>
                      )}
                    </button>
                    <div className="director-take-rail-body">
                      <button type="button" className="director-take-rail-select" onClick={() => selectTake(index)}>
                        <span>Take {take.takeNumber}</span>
                        {take.renderPass ? <Tag className="!m-0">{directorRenderPassLabel(take.renderPass)}</Tag> : null}
                        {approved ? <Tag color="success" className="!m-0">已批准</Tag> : null}
                      </button>
                      <div className="director-take-rail-actions">
                        <Button
                          size="small"
                          type={approved ? "primary" : "default"}
                          icon={<Star size={12} />}
                          disabled={!take.videoUrl}
                          onClick={() => approveTake(take)}
                        >
                          {approved ? "已批准" : "批准"}
                        </Button>
                        {compareDesktop && take.videoUrl && id !== takeId(activeTake) ? (
                          <Button
                            size="small"
                            onClick={() => setCompareTakeId(compareTakeId === id ? null : id)}
                          >
                            {compareTakeId === id ? "关闭对比" : "A/B"}
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        ) : null}
      </div>

      <div className="director-inspector-sidebar">
        <Segmented
          className="director-inspector-tab-switch"
          block
          value={inspectorTab}
          options={[
            { label: "文案", value: "script" },
            { label: "镜头", value: "shot" },
            { label: "生成", value: "produce" },
          ]}
          onChange={(value) => setInspectorTab(value as InspectorTab)}
        />
        <div className="director-inspector-tab-scroll">
          {inspectorTab === "script" ? (
                <div className="director-inspector-tab-body">
                  <label className="director-inspector-field">
                    <span>标题</span>
                    <Input value={shot.title} onChange={(event) => onChange({ title: event.target.value })} />
                  </label>
                  <label className="director-inspector-field">
                    <span>描述（中文卡片）</span>
                    <Input.TextArea
                      value={shot.description}
                      autoSize={{ minRows: 2, maxRows: 6 }}
                      placeholder="这一镜里发生什么，给分镜卡片看"
                      onChange={(event) => onChange({ description: event.target.value })}
                    />
                  </label>
                  <label className="director-inspector-field">
                    <span>英文镜头正文</span>
                    <Input.TextArea
                      value={shot.promptText || ""}
                      autoSize={{ minRows: 3, maxRows: 8 }}
                      placeholder="MiniMax H3 镜头正文：画风、构图、动作、运镜。单独一镜，从 00:00 写起。"
                      onChange={(event) => onChange({ promptText: event.target.value })}
                    />
                    {promptTextLooksChinese ? (
                      <p>当前正文是中文。MiniMax H3 官方要求英文镜头正文；中文只应出现在对白 &lt;d&gt; 里。</p>
                    ) : null}
                  </label>
                  <label className="director-inspector-field">
                    <span>对白</span>
                    <Input.TextArea
                      value={shot.dialogue}
                      autoSize={{ minRows: 2, maxRows: 4 }}
                      placeholder="角色说的话"
                      onChange={(event) => onChange({ dialogue: event.target.value })}
                    />
                    {dialogueDurationHint ? <p>{dialogueDurationHint}</p> : null}
                  </label>
                  {shot.timingNote ? <p>时长分配：{shot.timingNote}</p> : null}
                </div>
          ) : null}
          {inspectorTab === "shot" ? (
                <div className="director-inspector-tab-body">
                  <div className="director-inspector-row">
                    <label className="director-inspector-field">
                      <span>时长（秒）</span>
                      <InputNumber
                        min={H3_MIN_DURATION_SEC}
                        max={H3_MAX_DURATION_SEC}
                        value={shot.durationSec}
                        className="w-full"
                        onChange={(value) => onChange({ durationSec: snapH3DurationSec(value ?? H3_MIN_DURATION_SEC) })}
                      />
                    </label>
                    <label className="director-inspector-field">
                      <span>场景</span>
                      <Select
                        allowClear
                        className="w-full"
                        value={shot.locationName || undefined}
                        placeholder="选择场景"
                        options={recipe.locations.map((item) => ({ value: item.name, label: item.name }))}
                        onChange={(value?: string) => onChange({ locationName: value || "" })}
                      />
                    </label>
                  </div>
                  <label className="director-inspector-field">
                    <span>角色</span>
                    <Select
                      mode="multiple"
                      className="w-full"
                      value={shot.characterNames}
                      placeholder="选择出场角色"
                      options={recipe.characters.map((item) => ({ value: item.name, label: item.name }))}
                      onChange={(value: string[]) => onChange({ characterNames: value })}
                    />
                  </label>
                  <section className="director-inspector-camera">
                    <strong>景别 / 运镜 / 机位 / 布光</strong>
                    <ShotCameraFields
                      camera={camera}
                      onChange={(next: CameraDirection) => onChange({ camera: next })}
                    />
                  </section>
                  <section className="director-inspector-frames">
                    <strong>文案衔接</strong>
                    <p>AI 会把入镜、出镜状态编入本镜 H3 提示词；它与下面的尾帧视觉承接可配合使用。</p>
                    <label className="director-inspector-field">
                      <span>入镜状态（英文提示）</span>
                      <Input.TextArea
                        value={shot.continuityIn || ""}
                        autoSize={{ minRows: 2, maxRows: 4 }}
                        placeholder="上一镜切入时的人物、道具、视线、运动方向和声音状态"
                        onChange={(event) => onChange({ continuityIn: event.target.value })}
                      />
                    </label>
                    <label className="director-inspector-field">
                      <span>出镜状态（英文提示）</span>
                      <Input.TextArea
                        value={shot.continuityOut || ""}
                        autoSize={{ minRows: 2, maxRows: 4 }}
                        placeholder="留给下一镜继承的最终构图、动作、方向或声音"
                        onChange={(event) => onChange({ continuityOut: event.target.value })}
                      />
                    </label>
                    <label className="director-inspector-field">
                      <span>转场说明</span>
                      <Input
                        value={shot.transitionNote || ""}
                        placeholder="例如：动作匹配切，雨声不断"
                        onChange={(event) => onChange({ transitionNote: event.target.value })}
                      />
                    </label>
                  </section>
                  <section className="director-inspector-frames">
                    <strong>首尾帧</strong>
                    <Checkbox
                      checked={Boolean(shot.usePreviousEndFrame)}
                      disabled={!previousShot}
                      onChange={(event) => onChange({ usePreviousEndFrame: event.target.checked })}
                    >
                      用上一镜尾帧作为本镜首帧
                    </Checkbox>
                    {!previousShot ? <p>这是第一镜，没有上一镜可承接。</p> : null}
                    {shot.usePreviousEndFrame && previousShot && !previousHasEnd ? (
                      <p>上一镜还没有尾帧或静帧，请先到上一镜截取尾帧。</p>
                    ) : null}
                    <div className="director-frame-slots">
                      <button type="button" className="director-frame-slot" onClick={() => firstInputRef.current?.click()} disabled={Boolean(shot.usePreviousEndFrame)}>
                        {firstPreview ? <img src={firstPreview} alt="首帧" /> : <span><ImagePlus size={16} />首帧</span>}
                      </button>
                      <button type="button" className="director-frame-slot" onClick={() => endInputRef.current?.click()}>
                        {shot.endFrameUrl ? <img src={shot.endFrameUrl} alt="尾帧" /> : <span><ImagePlus size={16} />尾帧</span>}
                      </button>
                    </div>
                    <input ref={firstInputRef} type="file" accept="image/*" hidden onChange={(event) => {
                      const file = event.target.files?.[0]
                      event.target.value = ""
                      if (file) void onUploadFrame("first", file)
                    }} />
                    <input ref={endInputRef} type="file" accept="image/*" hidden onChange={(event) => {
                      const file = event.target.files?.[0]
                      event.target.value = ""
                      if (file) void onUploadFrame("end", file)
                    }} />
                  </section>
                </div>
          ) : null}
          {inspectorTab === "produce" ? (
                <div className="director-inspector-tab-body">
                  <div className="director-inspector-row">
                    <label className="director-inspector-field">
                      <span>说话人</span>
                      <Select
                        allowClear
                        className="w-full"
                        value={shot.speakerName || undefined}
                        placeholder="选择说话人"
                        options={recipe.characters.map((item) => ({ value: item.name, label: item.name }))}
                        onChange={(value?: string) => {
                          const character = recipe.characters.find((item) => item.name === value)
                          onChange({ speakerName: value || null, voiceId: character?.voiceId || shot.voiceId || null })
                        }}
                      />
                    </label>
                    <label className="director-inspector-field">
                      <span>音色</span>
                      <Select
                        allowClear
                        className="w-full"
                        value={shot.voiceId || undefined}
                        placeholder="本镜音色"
                        options={TTS_VOICE_OPTIONS.map((item) => ({ value: item.id, label: item.label }))}
                        onChange={(value?: string) => onChange({ voiceId: value || null })}
                      />
                    </label>
                  </div>
                  <section className="director-inspector-tts">
                    <strong>本镜配音</strong>
                    <div className="director-inspector-heading">
                      <Tag color={directorStatusColor(shot.ttsStatus)}>{shot.ttsStatus ? directorStatusLabel(shot.ttsStatus === "idle" ? undefined : shot.ttsStatus) : "未生成"}</Tag>
                    </div>
                    {shot.ttsUrl ? <audio className="director-export-audio" src={shot.ttsUrl} controls preload="metadata" /> : null}
                    {shot.ttsError ? <JobErrorNotice error={shot.ttsError} /> : null}
                  </section>
                  {takes.length ? (
                    <Collapse
                      className="director-inspector-takes-collapse"
                      items={[{
                        key: "take-params",
                        label: `Take 生成参数（${takes.length}）`,
                        children: (
                          <div className="director-take-list">
                            {takes.map((take, index) => {
                              const selected = index === activeIndex
                              const takeJob = jobForTake(take)
                              return (
                                <div key={take.id || take.jobId || index} className={`director-take-item${selected ? " is-active" : ""}`}>
                                  <button type="button" className="director-take-preview" onClick={() => selectTake(index)}>
                                    {take.videoUrl ? <video src={take.videoUrl} muted playsInline /> : <span>Take {take.takeNumber}</span>}
                                  </button>
                                  <div className="director-take-body">
                                    <div className="director-take-meta">
                                      <span>Take {take.takeNumber}</span>
                                      {take.renderPass ? <Tag>{directorRenderPassLabel(take.renderPass)}</Tag> : null}
                                      {takeId(take) === approvedId ? <Tag color="success">已批准</Tag> : null}
                                      <Tag color={directorStatusColor(take.status)}>{directorStatusLabel(take.status)}</Tag>
                                    </div>
                                    <TakeGenerationParams
                                      take={take}
                                      job={takeJob}
                                      compareTake={selected ? undefined : activeTake}
                                      compareJob={selected ? undefined : jobForTake(activeTake)}
                                    />
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        ),
                      }]}
                    />
                  ) : (
                    <p className="director-inspector-takes-empty">还没有 Take。生成预览或终稿后会出现在预览区下方。</p>
                  )}
                  <section className="director-inspector-plates">
                    <strong>本镜参考图</strong>
                    {plates.length ? (
                      <div className="director-plate-row">
                        {plates.map((plate) => (
                          <figure key={`${plate.kind}-${plate.name}`}>
                            {plate.imageUrl ? (
                              <img src={plate.imageUrl} alt={plate.name} />
                            ) : (
                              <div className="director-plate-empty">待定妆</div>
                            )}
                            <figcaption>{plate.name}</figcaption>
                          </figure>
                        ))}
                      </div>
                    ) : (
                      <p>还没有可装箱的人物或场景定妆</p>
                    )}
                  </section>
                  <section className="director-inspector-compiled">
                    <strong>即将提交给 MiniMax 的提示词</strong>
                    <div className="director-inspector-heading">
                      <Space size={6} wrap>
                        <Tag color="purple">{workflowRouteLabel(submission.workflowId, submission.plan.route)}</Tag>
                        <Tag>{submission.durationSec}s</Tag>
                        <Tag>{submission.plan.items.length}/9 参考图</Tag>
                        {submission.wordCount ? <Tag>{submission.wordCount} 词</Tag> : null}
                      </Space>
                      <Button
                        size="small"
                        icon={<Copy size={12} />}
                        onClick={() => {
                          void navigator.clipboard.writeText(submission.prompt)
                          messageApi.success("已复制即将提交的提示词")
                        }}
                      >
                        复制
                      </Button>
                    </div>
                    {submission.plan.items.length ? (
                      <div className="director-compiled-tags">
                        {submission.plan.items.map((item) => (
                          <Tag key={`${item.role}-${item.pictureIndex}`}>{item.label}</Tag>
                        ))}
                      </div>
                    ) : (
                      <p>这一镜没有参考图，会走文生视频结构。</p>
                    )}
                    <pre className="director-compiled-prompt">{submission.prompt || "还没有可编译的镜头正文"}</pre>
                    {submittedSnapshot && submittedSnapshot !== submission.prompt ? (
                      <>
                        <p>上次实际提交的提示词与当前预览不同（改过描述或参考图后会这样）。</p>
                        <pre className="director-compiled-prompt is-snapshot">{submittedSnapshot}</pre>
                      </>
                    ) : null}
                  </section>
                </div>
          ) : null}
        </div>
        <div className="director-inspector-action-bar">
          <JobErrorNotice error={state.error || shot.error} />
          <Space wrap className="director-inspector-action-buttons">
            <Button loading={stillState.generating} onClick={onGenerateStill}>生成静帧</Button>
            <Button
              disabled={!shot.stillUrl}
              onClick={() => onChange({
                firstFrameUrl: shot.stillUrl,
                firstFrameJobId: shot.stillJobId,
                usePreviousEndFrame: false,
              })}
            >
              静帧设为首帧
            </Button>
            <Button loading={extracting} disabled={!videoUrl || !onExtractEndFrame} onClick={() => { void handleExtractEnd() }}>
              截取尾帧
            </Button>
            <Button loading={ttsBusy} disabled={!shot.dialogue.trim() || !onGenerateTts} onClick={() => onGenerateTts?.()}>
              生成本镜配音
            </Button>
            <Button type="primary" loading={state.generating} onClick={onRender}>
              {state.generating ? state.label : failed ? "重试这一镜" : "生成这一镜"}
            </Button>
          </Space>
        </div>
      </div>
    </div>
  )
}
