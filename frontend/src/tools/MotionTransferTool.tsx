import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Empty, Image, Input, InputNumber, Modal, Select, Slider, Spin, Switch, Tooltip, message } from "antd"
import { ArrowLeft, ArrowLeftRight, ChevronDown, Clock3, Dices, ImagePlus, MessageCircle, RectangleHorizontal, RefreshCw, ScanLine, Settings2, Sparkles, Star, Volume2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import { searchFilterOption } from "../search-match"
import {
  MOTION_REF_VIDEO_WORKFLOW,
  MOTION_SKELETON_WORKFLOW,
  MOTION_TOOL_WORKFLOWS,
  MOTION_TRANSFER_WORKFLOW,
  motionDurationError,
  motionImageLimit,
  motionReferenceError,
  motionToolDefaults,
  motionToolOptions,
  motionToolPayload,
  motionToolSubmitBlockReason,
  hasSubjects,
  type SubjectPoint,
  type MotionReferenceAsset,
  type ToolOptionDefinition,
} from "../generation/motion-transfer"
import { generateJobPath } from "../paths"
import { createLocalId } from "../lib/utils"
import { promptAutoSize } from "../prompt-autosize"
import MotionRefVideoReferences from "../generation/MotionRefVideoReferences"
import MotionTransferReferences from "../generation/MotionTransferReferences"
import AssetPickerModal from "./AssetPickerModal"
import MotionSubjectPicker from "./MotionSubjectPicker"
import { restoreReferenceFiles, roundReferenceSources, type ReferenceSource } from "../reference-assets"
import "./motion-transfer-tool.css"

const optionIcons = { control_strength: ScanLine, aspect_ratio: RectangleHorizontal, duration: Clock3, preserve_audio: Volume2, render_quality: Star, seed: Dices }

type ToolWorkflow = {
  id: string
  name: string
  description: string
  reference_labels: string[]
  reference_slots?: string[]
  accepts_video_reference?: boolean
  parameters: { name: string; schema?: { properties?: Record<string, ToolOptionDefinition> } | null }[]
}

function assetFrom(file: File): MotionReferenceAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

function optionSchemaOf(workflow: ToolWorkflow | undefined): Record<string, ToolOptionDefinition> | null | undefined {
  return workflow?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties
}

/** hero 副标题用语义文案；注册表 description 面向接口（含 references 约定），不适合直接展示。 */
const MODE_TAGLINES: Record<string, string> = {
  [MOTION_TRANSFER_WORKFLOW]: "指定人物迁移动作与表情，保留原片场景、其他人物和音乐",
  [MOTION_SKELETON_WORKFLOW]: "骨架驱动单人复刻：从原片抽取动作节奏，角色形象图锁定身份；输出音频由 H3 生成",
  [MOTION_REF_VIDEO_WORKFLOW]: "动作视频直接作为表演来源，1-6 张角色图按顺序对应表演者；运镜、场景与原声一并迁移",
}

export default function MotionTransferTool({
  csrfToken, lockedWorkflow, copy,
}: {
  csrfToken: string
  /** 锁定单一迁移方式（独立工具卡入口）：隐藏方式选择器，只加载该工作流。 */
  lockedWorkflow?: string
  /** 独立工具卡的标题/副标题覆盖；缺省沿用「动作迁移」文案。 */
  copy?: { title: string; description: string }
}) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [portrait, setPortrait] = useState<MotionReferenceAsset | null>(null)
  const [video, setVideo] = useState<MotionReferenceAsset | null>(null)
  const [characters, setCharacters] = useState<MotionReferenceAsset[]>([])
  const [characterPreview, setCharacterPreview] = useState<number | null>(null)
  const [portraitPreview, setPortraitPreview] = useState(false)
  const [videoPreview, setVideoPreview] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [prompt, setPrompt] = useState("")
  const [mode, setMode] = useState<string>(() => {
    if (lockedWorkflow) return lockedWorkflow
    const requested = searchParams.get("mode")
    return requested && MOTION_TOOL_WORKFLOWS.includes(requested) ? requested : MOTION_TRANSFER_WORKFLOW
  })
  /** 每种迁移方式各自保留一份参数值，切换不互相覆盖。 */
  const [valuesByMode, setValuesByMode] = useState<Record<string, Record<string, string | number | boolean>>>({})
  const [submitting, setSubmitting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [sourcePoints, setSourcePoints] = useState<SubjectPoint[]>([])
  const [referencePoints, setReferencePoints] = useState<SubjectPoint[]>([])
  const [selection, setSelection] = useState<"image" | "video" | null>(null)
  const [restoring, setRestoring] = useState(false)
  const initializedModes = useRef(new Set<string>())
  const submissionPending = useRef(false)

  const queryWorkflowIds = lockedWorkflow ? [lockedWorkflow] : MOTION_TOOL_WORKFLOWS
  const workflowQuery = useQuery({
    queryKey: lockedWorkflow ? ["motion-tool-workflows", lockedWorkflow] : ["motion-tool-workflows"],
    queryFn: () => Promise.all(queryWorkflowIds.map((id) => api<ToolWorkflow>(`/api/modes/${id}`))),
    staleTime: 1000 * 60,
  })
  const workflows = useMemo(() => workflowQuery.data ?? [], [workflowQuery.data])
  const workflow = workflows.find((item) => item.id === mode)
  const schema = optionSchemaOf(workflow)
  const controls = useMemo(() => motionToolOptions(schema), [schema])
  const values = valuesByMode[mode] ?? {}
  const isReplaceMode = mode === MOTION_TRANSFER_WORKFLOW
  const isMultiMode = mode === MOTION_REF_VIDEO_WORKFLOW
  const characterLimit = Math.max(1, motionImageLimit(workflow ?? null))
  const labels = workflow?.reference_labels?.length === 2
    ? workflow.reference_labels
    : ["角色形象图", "动作参考视频"]

  useEffect(() => {
    if (!workflow || initializedModes.current.has(mode)) return
    initializedModes.current.add(mode)
    const defaults = motionToolDefaults(optionSchemaOf(workflow))
    setValuesByMode((current) => (current[mode] ? current : { ...current, [mode]: defaults }))
  }, [mode, workflow])

  const restoreJobId = searchParams.get("job")
  const restoreRoundId = searchParams.get("round")
  useEffect(() => {
    if (!restoreJobId || !workflows.length) return
    let active = true
    setRestoring(true)
    type SavedRound = { id: string; mode: string; prompt: string; options: Record<string, string | number | boolean>; reference_count: number; references: ReferenceSource[] }
    void api<{ id: string; references: ReferenceSource[]; rounds: SavedRound[] }>(`/api/jobs/${encodeURIComponent(restoreJobId)}`).then(async (job) => {
      const round = restoreRoundId ? job.rounds.find((item) => item.id === restoreRoundId) : job.rounds.at(-1)
      if (!round || !MOTION_TOOL_WORKFLOWS.includes(round.mode)) throw new Error("此任务不属于动作迁移工具支持的工作流")
      const sources = roundReferenceSources(job, round)
      const files = await restoreReferenceFiles(sources.map((source) => ({
        ...source,
        kind: source.kind ?? (source.index === sources.length ? "video" as const : "image" as const),
      })))
      if (!active) return
      if (round.mode === MOTION_REF_VIDEO_WORKFLOW) {
        if (files.length < 2) throw new Error("参考素材不完整，请重新上传")
        setCharacters(files.slice(0, files.length - 1).map(assetFrom))
        setVideo(assetFrom(files[files.length - 1]))
      } else {
        if (files.length !== 2) throw new Error("参考素材不完整，请重新上传")
        setPortrait(assetFrom(files[0])); setVideo(assetFrom(files[1]))
      }
      initializedModes.current.add(round.mode)
      setValuesByMode((current) => ({
        ...current,
        [round.mode]: { ...motionToolDefaults(optionSchemaOf(workflows.find((item) => item.id === round.mode))), ...round.options },
      }))
      setPrompt(round.prompt)
      if (round.mode === MOTION_TRANSFER_WORKFLOW) {
        setSourcePoints(JSON.parse(String(round.options.source_points || "[]")))
        setReferencePoints(JSON.parse(String(round.options.reference_points || "[]")))
      }
      setMode(round.mode)
    }).catch((error) => { if (active) message.error(apiErrorMessage(error, "恢复动作迁移素材失败")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreJobId, restoreRoundId, workflows])

  useEffect(() => {
    const preview = portrait?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [portrait?.preview])
  useEffect(() => {
    const preview = video?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [video?.preview])
  const charactersRef = useRef(characters)
  charactersRef.current = characters
  useEffect(() => () => { charactersRef.current.forEach((asset) => URL.revokeObjectURL(asset.preview)) }, [])

  const acceptPortrait = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = motionReferenceError(candidate, "image")
    if (problem) {
      message.warning(problem)
      return
    }
    setPortrait(assetFrom(candidate))
    setReferencePoints([])
    if (isReplaceMode) setSelection("image")
  }

  const acceptVideo = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = motionReferenceError(candidate, "video")
    if (problem) {
      message.warning(problem)
      return
    }
    setVideo(assetFrom(candidate))
    setSourcePoints([])
    if (isReplaceMode) setSelection("video")
  }

  /** 多人版:批量接收角色形象图，顺序即 <Picture n>，超出上限或类型不符给出提示。 */
  const acceptCharacters = (files: FileList | File[] | null) => {
    const candidates = Array.from(files ?? [])
    if (!candidates.length) return
    const next = [...characters]
    let overflow = false
    for (const file of candidates) {
      if (next.length >= characterLimit) { overflow = true; break }
      const problem = motionReferenceError(file, "image")
      if (problem) { message.warning(problem); continue }
      next.push(assetFrom(file))
    }
    if (overflow) message.warning(`最多添加 ${characterLimit} 位角色形象图`)
    setCharacters(next)
  }

  const replaceCharacter = (index: number, files: FileList | File[] | null) => {
    const file = Array.from(files ?? [])[0]
    if (!file) return
    const problem = motionReferenceError(file, "image")
    if (problem) { message.warning(problem); return }
    setCharacters((current) => current.map((asset, i) => {
      if (i !== index) return asset
      URL.revokeObjectURL(asset.preview)
      return assetFrom(file)
    }))
  }

  const removeCharacter = (index: number) => {
    setCharacters((current) => {
      const target = current[index]
      if (target) URL.revokeObjectURL(target.preview)
      return current.filter((_, i) => i !== index)
    })
  }

  const moveCharacter = (index: number, direction: -1 | 1) => {
    setCharacters((current) => {
      const next = [...current]
      const target = index + direction
      if (target < 0 || target >= next.length) return current
      const [item] = next.splice(index, 1)
      next.splice(target, 0, item)
      return next
    })
  }

  const subjectCount = values.subject_count === "2" ? 2 : 1
  useEffect(() => {
    if (subjectCount === 1) {
      setSourcePoints((current) => current.filter((point) => (point.subject ?? 0) === 0))
      setReferencePoints((current) => current.filter((point) => (point.subject ?? 0) === 0))
    }
  }, [subjectCount])
  const durationError = motionDurationError(video?.duration, values.duration, schema?.duration)
  const subjectsReady = !isReplaceMode || (hasSubjects(sourcePoints, subjectCount) && hasSubjects(referencePoints, subjectCount))
  const submitBlockReason = motionToolSubmitBlockReason({
    mode,
    imageCount: isMultiMode ? characters.length : (portrait ? 1 : 0),
    hasVideo: Boolean(video),
    workflowLoaded: Boolean(workflow),
    subjectsReady,
    durationError,
    submitting,
    restoring,
  })
  const ready = !submitBlockReason

  const setOption = (name: string, next: string | number | boolean) => {
    setValuesByMode((current) => ({
      ...current,
      [mode]: { ...(current[mode] ?? motionToolDefaults(schema)), [name]: next },
    }))
  }

  const submit = async () => {
    if (submissionPending.current) return
    if (isMultiMode ? !characters.length : !portrait) {
      message.warning(isMultiMode ? "请至少添加一张角色形象图" : "请上传角色形象图")
      return
    }
    if (!video) {
      message.warning("请上传动作参考视频")
      return
    }
    if (durationError) {
      message.warning(durationError)
      return
    }
    if (!subjectsReady) {
      message.warning("请先按相同编号在形象图和视频首帧中选定每个人物")
      return
    }
    const form = new FormData()
    form.set("mode", mode)
    form.set("prompt", prompt.trim())
    const payloadValues: Record<string, string | number | boolean> = isReplaceMode
      ? {
        ...values,
        source_points: JSON.stringify(sourcePoints.filter((p) => (p.subject ?? 0) < subjectCount)),
        reference_points: JSON.stringify(referencePoints.filter((p) => (p.subject ?? 0) < subjectCount)),
      }
      : values
    form.set("options", JSON.stringify(motionToolPayload(payloadValues)))
    if (isMultiMode) characters.forEach((asset) => form.append("references", asset.file))
    else if (portrait) form.append("references", portrait.file)
    form.append("references", video.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success(`${copy?.title ?? "动作迁移"}任务已提交，可在生成页查看进度`)
      navigate(generateJobPath("video", payload.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  const renderControl = ({ name, definition, control, options }: ReturnType<typeof motionToolOptions>[number]) => {
    const value = values[name] ?? definition.default
    const field = (() => {
      if (control === "select") {
        return <Select
          aria-label={definition.label}
          value={String(value)}
          onChange={(next) => setOption(name, next)}
          className="w-full"
          options={options}
        />
      }
      if (control === "switch") {
        return <Switch
          aria-label={definition.label}
          checked={Boolean(value)}
          onChange={(checked) => setOption(name, checked)}
        />
      }
      if (control === "slider") {
        const precision = String(definition.step ?? 1).split(".")[1]?.length ?? 0
        return <div className="studio-motion-slider-field"><Slider
          aria-label={definition.label}
          ariaLabelForHandle={definition.label}
          min={definition.minimum}
          max={definition.maximum}
          step={definition.step}
          value={Number(value)}
          onChange={(next) => setOption(name, next)}
        /><output aria-live="polite">{Number(value).toFixed(precision)}</output></div>
      }
      return <InputNumber
        aria-label={definition.label}
        min={definition.minimum}
        max={definition.maximum}
        step={definition.step}
        value={Number(value)}
        onChange={(next) => { if (next !== null) setOption(name, next) }}
        className="w-full"
      />
    })()
    const Icon = optionIcons[name as keyof typeof optionIcons] ?? Settings2
    return <div key={name} className="studio-tool-motion-option" data-control={control}>
      <label className="studio-tool-section-label">
        <Icon size={19} aria-hidden="true" />
        {definition.description
          ? <Tooltip title={definition.description}><span className="cursor-help">{definition.label}</span></Tooltip>
          : definition.label}
      </label>
      {field}
    </div>
  }

  return (
    <div className="studio-tools-page studio-motion-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>{copy?.title ?? "动作迁移"}</h1>
          <p>{copy?.description ?? (MODE_TAGLINES[mode] || "三种迁移方式任选，素材与参数按方式独立保留")}</p>
        </div>
        <img className="studio-motion-hero-art" src="/tool-art/motion-transfer-pose.webp" alt="" aria-hidden="true" />
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] w-full place-items-center"><Spin tip="正在读取动作迁移能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`动作迁移能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card" aria-label="动作迁移创作">
          <div className="studio-tool-motion-materials">
            {lockedWorkflow ? null : <div className="studio-tool-motion-option" data-control="select">
              <label className="studio-tool-section-label" htmlFor="motion-tool-mode"><ArrowLeftRight size={19} aria-hidden="true" />迁移方式</label>
              <Select
                id="motion-tool-mode"
                aria-label="迁移方式"
                showSearch
                filterOption={searchFilterOption}
                value={mode}
                onChange={(next) => { setMode(next); setAdvancedOpen(false) }}
                className="w-full"
                options={workflows.map((item) => ({ value: item.id, label: item.name }))}
              />
            </div>}
            {isMultiMode ? <MotionRefVideoReferences
              variant="tool"
              labels={workflow?.reference_labels ?? []}
              characters={characters}
              maxCharacters={characterLimit}
              motion={video}
              onPickCharacters={acceptCharacters}
              onReplaceCharacter={replaceCharacter}
              onRemoveCharacter={removeCharacter}
              onMoveCharacter={moveCharacter}
              onPreviewCharacter={(index) => setCharacterPreview(index)}
              onPickMotion={(files) => acceptVideo(Array.from(files ?? [])[0])}
              onRemoveMotion={() => setVideo(null)}
              onPreviewMotion={() => setVideoPreview(true)}
              onMotionDuration={(id, duration) => {
                const seconds = Number.isFinite(duration) ? duration : undefined
                setVideo((current) => current?.id === id ? { ...current, duration: seconds } : current)
              }}
            /> : <MotionTransferReferences
              variant="tool"
              labels={labels}
              portrait={portrait ?? undefined}
              motion={video}
              onPickPortrait={(files) => acceptPortrait(files?.[0])}
              onPickMotion={(files) => acceptVideo(files?.[0])}
              onRemovePortrait={() => setPortrait(null)}
              onRemoveMotion={() => setVideo(null)}
              onPreviewPortrait={() => setPortraitPreview(true)}
              onPreviewMotion={() => setVideoPreview(true)}
              onMotionDuration={(id, duration) => {
                const seconds = Number.isFinite(duration) ? duration : undefined
                setVideo((current) => current?.id === id ? { ...current, duration: seconds } : current)
              }}
            />}
            {/* 三种方式的素材槽位都自带点击/拖入上传入口，这里只保留资产库选取 */}
            <div className="studio-motion-upload-actions">
              <Button icon={<ImagePlus size={14} />} onClick={() => setPickerOpen(true)}>从资产选取</Button>
            </div>
            {isReplaceMode ? <div className="studio-motion-subject-actions">
              <Button disabled={!portrait || restoring} onClick={() => setSelection("image")}>{hasSubjects(referencePoints, subjectCount) ? "已选形象角色 · 修改" : "选择形象图人物"}</Button>
              <Button disabled={!video || restoring} onClick={() => setSelection("video")}>{hasSubjects(sourcePoints, subjectCount) ? "已选视频人物 · 修改" : "选择视频中要替换的人物"}</Button>
            </div> : null}
            <p className="studio-motion-selection-help">
              {isReplaceMode
                ? `支持单人或双人替换。两份素材按人物编号配对，完整原片由平台自动连续生成。${restoring ? "正在恢复素材…" : ""}`
                : isMultiMode
                  ? `按顺序添加 1-${characterLimit} 张角色形象图，第 n 张对应视频中的第 n 位表演者；原片带音轨时可保留原声。${restoring ? "正在恢复素材…" : ""}`
                  : `一张角色形象图 + 一段动作参考视频，骨架驱动动作节奏；输出音频由 H3 生成。${restoring ? "正在恢复素材…" : ""}`}
            </p>
            {durationError ? <p className="studio-motion-validation" role="alert">{durationError}</p> : null}
          </div>

          <div className="studio-motion-settings">
            {isReplaceMode && subjectCount > 1 ? <Alert type="info" showIcon title="双人替换试用" description="双人替换的发型、服装细节仍可能失真，建议先生成 5 秒试片检查效果。" /> : null}
            <div className="studio-tool-motion-options">
              {controls.filter(({ definition }) => definition.ui_group === "primary" || advancedOpen).map(renderControl)}
            </div>
            {controls.some(({ definition }) => definition.ui_group === "advanced") ? <Button
              type="text" className="studio-motion-more" aria-expanded={advancedOpen}
              onClick={() => setAdvancedOpen((open) => !open)}
              icon={<Settings2 size={14} />}
            >更多设置<ChevronDown size={14} className={advancedOpen ? "is-open" : ""} /></Button> : null}

          <div className="studio-motion-prompt">
            <label className="studio-tool-section-label" htmlFor="motion-tool-prompt"><MessageCircle size={19} aria-hidden="true" />提示词 <span>（可选）</span></label>
            <Input.TextArea
              id="motion-tool-prompt"
              aria-label="提示词（可选）"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={isMultiMode
                ? "描述角色外观、服装与场景；留空则使用内置模板，自动按顺序绑定每位表演者。"
                : "可补充角色的外观、服装与表演特点；留空自动跟随原片动作与表情。"}
              autoSize={promptAutoSize(4)}
              maxLength={1500}
            />
          </div>

          <div className="studio-motion-footer">
            <span className="studio-tool-motion-note">素材各不超过 50 MB；画面比例与时长按所选迁移方式的能力生效。</span>
            <Tooltip title={submitBlockReason || undefined}>
              <span className="studio-submit-tooltip-wrap">
                <Button type="primary" size="large" loading={submitting} disabled={!ready} aria-label={submitBlockReason ? `开始生成（${submitBlockReason}）` : "开始生成"} icon={<Sparkles size={19} />} onClick={() => void submit()}>
                  {submitting ? "提交中" : "开始生成"}
                </Button>
              </span>
            </Tooltip>
          </div>
          </div>
        </section>
      )}
      <img className="studio-motion-watermark" src="/tool-art/motion-transfer-pose.webp" alt="" aria-hidden="true" />

      <Modal open={portraitPreview} footer={null} title="角色形象图" onCancel={() => setPortraitPreview(false)} width={560} destroyOnHidden>
        {portrait ? <Image src={portrait.preview} alt="角色形象图预览" className="w-full" /> : null}
      </Modal>
      <Modal open={characterPreview !== null} footer={null} title={`角色形象图 ${(characterPreview ?? -1) + 1}`} onCancel={() => setCharacterPreview(null)} width={560} destroyOnHidden>
        {characters[characterPreview ?? -1] ? <Image src={characters[characterPreview ?? -1].preview} alt="角色形象图预览" className="w-full" /> : null}
      </Modal>
      <Modal open={videoPreview} footer={null} title="动作参考视频" onCancel={() => setVideoPreview(false)} width={640} destroyOnHidden>
        {video ? <video src={video.preview} controls autoPlay className="w-full rounded-lg" /> : null}
      </Modal>

      <AssetPickerModal open={pickerOpen} onClose={() => setPickerOpen(false)}
        onPick={(picked) => { if (isMultiMode) acceptCharacters([picked]); else acceptPortrait(picked) }} />
      {isReplaceMode ? <MotionSubjectPicker asset={selection === "image" ? portrait : selection === "video" ? video : null}
        subjectCount={subjectCount}
        video={selection === "video"} points={selection === "video" ? sourcePoints : referencePoints}
        onChange={selection === "video" ? setSourcePoints : setReferencePoints} onClose={() => setSelection(null)} /> : null}
    </div>
  )
}
