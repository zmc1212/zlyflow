import { Button, Checkbox, Input, InputNumber, Progress, Select, Space, Tag, message } from "antd"
import { Clapperboard, Copy, ImagePlus, Star } from "lucide-react"
import { CSSProperties, ReactNode, useMemo, useRef, useState } from "react"
import JobErrorNotice from "./JobErrorNotice"
import ShotCameraFields from "./ShotCameraFields"
import {
  H3_MAX_DURATION_SEC,
  H3_MIN_DURATION_SEC,
  compileRecipeShotPreview,
  directorRenderPassLabel,
  snapH3DurationSec,
  workflowRouteLabel,
} from "../prompt-compiler"
import { extractVideoFrame, shotGenerationState } from "../director-submit"
import { directorStatusColor, directorStatusLabel, isDirectorFailedStatus } from "../status-labels"
import {
  CameraDirection, RecipeProject, RecipeShot, ShotTake, TTS_VOICE_OPTIONS, defaultCameraDirection, recipePackedPlates,
} from "../types"

type JobLike = {
  id: string
  status?: string
  stage?: string
  progress?: number
  error?: string | null
}

function takeVideoUrl(take: ShotTake | undefined) {
  return take?.videoUrl || ""
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

export default function RecipeShotInspector({
  shot,
  recipe,
  previousShot,
  job,
  stillJob,
  compareDesktop = true,
  onChange,
  onRender,
  onGenerateStill,
  onUploadFrame,
  onExtractEndFrame,
  onGenerateTts,
  ttsBusy = false,
}: {
  shot: RecipeShot
  recipe: RecipeProject
  previousShot?: RecipeShot | null
  job?: JobLike
  stillJob?: JobLike
  compareDesktop?: boolean
  onChange: (patch: Partial<RecipeShot>) => void
  onRender: () => void
  onGenerateStill: () => void
  onUploadFrame: (slot: "first" | "end", file: File) => Promise<void>
  onExtractEndFrame?: (file: File) => Promise<void>
  onGenerateTts?: () => void
  ttsBusy?: boolean
}) {
  const firstInputRef = useRef<HTMLInputElement>(null)
  const endInputRef = useRef<HTMLInputElement>(null)
  const [compareTakeId, setCompareTakeId] = useState<string | null>(null)
  const [extracting, setExtracting] = useState(false)
  const state = shotGenerationState(job, shot.outputVideoUrl, shot.jobId, {
    status: shot.status,
    progress: shot.progress,
  })
  const stillState = shotGenerationState(stillJob, shot.stillUrl, shot.stillJobId, {
    status: shot.stillStatus || "idle",
    progress: 0,
  })
  const displayStatus = state.generating ? state.status : (state.status !== "idle" ? state.status : shot.status)
  const failed = !state.generating && isDirectorFailedStatus(displayStatus)
  const takes = shot.takes || []
  const activeIndex = Math.min(Math.max(shot.activeTakeIndex || 0, 0), Math.max(takes.length - 1, 0))
  const activeTake = takes[activeIndex]
  const approvedId = shot.approvedTakeId || ""
  const videoUrl = takeVideoUrl(activeTake) || shot.outputVideoUrl || ""
  const showVideo = Boolean(videoUrl) && !state.generating
  const inheritedFirst = shot.usePreviousEndFrame
    ? (previousShot?.endFrameUrl || previousShot?.stillUrl || "")
    : ""
  const firstPreview = inheritedFirst || shot.firstFrameUrl || shot.stillUrl || ""
  const plates = recipePackedPlates(recipe, shot)
  const camera = shot.camera || defaultCameraDirection()
  const compareTake = takes.find((item) => item.id === compareTakeId && item.id !== activeTake?.id)
  const previousHasEnd = Boolean(previousShot?.endFrameUrl || previousShot?.stillUrl)
  const submission = useMemo(
    () => compileRecipeShotPreview(recipe, shot, previousShot),
    [recipe, shot, previousShot],
  )
  const submittedSnapshot = (activeTake?.promptSnapshot || shot.compiledPrompt || "").trim()
  const promptTextLooksChinese = /[\u4e00-\u9fff]/.test(shot.promptText || "") && !(shot.promptText || "").toLowerCase().includes("the camera")

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
    onChange({
      activeTakeIndex: index,
      jobId: take.jobId || take.id,
      outputVideoUrl: take.videoUrl || shot.outputVideoUrl,
      status: take.status,
      progress: take.progress,
    })
  }

  const comparing = Boolean(compareDesktop && showVideo && compareTake?.videoUrl)
  const emptyPreview = !showVideo && !(firstPreview && !state.generating)

  return (
    <div className="director-recipe-inspector" style={recipeAspectVars(recipe.aspectRatio)}>
      <div className="director-inspector-picture">
        <div className={`director-inspector-stage${comparing ? " is-compare" : ""}`}>
          {comparing && compareTake?.videoUrl ? (
            <>
              <ShotPreviewFrame>
                <video src={videoUrl} controls playsInline />
              </ShotPreviewFrame>
              <ShotPreviewFrame>
                <video src={compareTake.videoUrl} controls playsInline />
              </ShotPreviewFrame>
            </>
          ) : (
            <ShotPreviewFrame empty={emptyPreview}>
              {showVideo ? (
                <video src={videoUrl} controls playsInline />
              ) : firstPreview && !state.generating ? (
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
        <div className="director-inspector-heading">
          <Tag color={directorStatusColor(displayStatus)}>{directorStatusLabel(displayStatus)}</Tag>
          {shot.stillUrl ? <Tag>静帧</Tag> : null}
          {activeTake?.renderPass ? <Tag>{directorRenderPassLabel(activeTake.renderPass)}</Tag> : null}
          <span>{shot.durationSec}s</span>
        </div>
      </div>

      <div className="director-inspector-copy">
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
      </label>
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
        <Button size="small" loading={ttsBusy} disabled={!shot.dialogue.trim() || !onGenerateTts} onClick={() => onGenerateTts?.()}>
          生成本镜配音
        </Button>
      </section>
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
        <strong>连续性</strong>
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
        <Space wrap>
          <Button size="small" loading={stillState.generating} onClick={onGenerateStill}>生成静帧</Button>
          <Button
            size="small"
            disabled={!shot.stillUrl}
            onClick={() => onChange({
              firstFrameUrl: shot.stillUrl,
              firstFrameJobId: shot.stillJobId,
              usePreviousEndFrame: false,
            })}
          >
            静帧设为首帧
          </Button>
          <Button size="small" loading={extracting} disabled={!videoUrl || !onExtractEndFrame} onClick={() => { void handleExtractEnd() }}>
            从成片截取尾帧
          </Button>
        </Space>
      </section>

      <section className="director-inspector-takes">
        <strong>Takes {takes.length ? `(${takes.length})` : ""}</strong>
        {takes.length ? (
          <div className="director-take-list">
            {takes.map((take, index) => {
              const selected = index === activeIndex
              const approved = (take.id || take.jobId) === approvedId
              return (
                <div key={take.id || take.jobId || index} className={`director-take-item${selected ? " is-active" : ""}`}>
                  <button type="button" className="director-take-preview" onClick={() => selectTake(index)}>
                    {take.videoUrl ? <video src={take.videoUrl} muted playsInline /> : <span>Take {take.takeNumber}</span>}
                  </button>
                  <div className="director-take-meta">
                    <span>Take {take.takeNumber}</span>
                    {take.renderPass ? <Tag>{directorRenderPassLabel(take.renderPass)}</Tag> : null}
                    {approved ? <Tag color="success">已批准</Tag> : null}
                    <Tag color={directorStatusColor(take.status)}>{directorStatusLabel(take.status)}</Tag>
                  </div>
                  <Space size={4}>
                    <Button
                      size="small"
                      icon={<Star size={12} />}
                      disabled={!take.videoUrl}
                      onClick={() => onChange({
                        approvedTakeId: take.id || take.jobId || null,
                        activeTakeIndex: index,
                        outputVideoUrl: take.videoUrl || shot.outputVideoUrl,
                        jobId: take.jobId || take.id,
                      })}
                    >
                      批准
                    </Button>
                    {compareDesktop && take.videoUrl && take.id !== activeTake?.id ? (
                      <Button
                        size="small"
                        onClick={() => setCompareTakeId(compareTakeId === take.id ? null : (take.id || null))}
                      >
                        {compareTakeId === take.id ? "关闭对比" : "A/B"}
                      </Button>
                    ) : null}
                  </Space>
                </div>
              )
            })}
          </div>
        ) : (
          <p>还没有 Take。生成预览或终稿后会出现在这里。</p>
        )}
      </section>

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
              message.success("已复制即将提交的提示词")
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

      <JobErrorNotice error={state.error || shot.error} />
      <Button type="primary" loading={state.generating} onClick={onRender}>
        {failed ? "重试这一项" : "生成这一镜"}
      </Button>
      </div>
    </div>
  )
}
