import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Button,
  Checkbox,
  Collapse,
  Empty,
  Image,
  Input,
  InputNumber,
  Popover,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  Upload,
  message,
} from "antd"
import {
  Box,
  Check,
  ChevronDown,
  Crop,
  Download,
  ExternalLink,
  FileText,
  Grid2X2,
  Image as LucideImage,
  ImageIcon,
  Layers,
  MessageSquare,
  Pencil,
  RefreshCw,
  Sparkles,
  Upload as UploadIcon,
  User,
  Video,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react"
import {
  generateXiajiBeatRender,
  generateXiajiBeatSketch,
  generateXiajiBeatVideo,
  generateXiajiEpisodeSketches,
  listXiajiAssets,
  isXiajiShotVideoMode,
  listXiajiWorkflowModes,
  patchXiajiBeat,
  uploadXiajiBeatSketch,
  waitForXiajiImageJob,
  DEFAULT_XIAJI_VIDEO_WORKFLOW,
  type XiajiAsset,
  type XiajiBeat,
  type XiajiEpisode,
  type XiajiOptionProperty,
  type XiajiWorkflowMode,
} from "./xiaji-api"

const SPLIT_KEY = "xiaji.shots.split-ratio"
const TIME_OPTIONS = ["日", "夜", "晨", "黄昏"]
const VIDEO_ASPECT_RATIO = "16:9"

function videoOptionSchema(mode?: XiajiWorkflowMode | null): Record<string, XiajiOptionProperty> {
  const options = (mode?.parameters ?? []).find((item) => item.name === "options")
  return options?.schema?.properties ?? {}
}

function durationChoices(prop?: XiajiOptionProperty) {
  const min = Number(prop?.minimum ?? 2)
  const max = Number(prop?.maximum ?? 15)
  const step = Number(prop?.step ?? 1) || 1
  const wanted = [min, 5, 8, 10, max]
  const values = [...new Set(wanted.filter((item) => item >= min && item <= max))]
  if (!values.length) {
    for (let value = min; value <= max + 1e-9; value += step) values.push(Number(value.toFixed(4)))
  }
  return values.sort((a, b) => a - b).map((item) => ({ value: String(item), label: `${item}秒` }))
}

function selectChoices(prop?: XiajiOptionProperty) {
  if (prop?.ui_options?.length) return prop.ui_options.map((item) => ({ value: item.value, label: item.label }))
  return (prop?.enum ?? []).map((item) => ({ value: item, label: item }))
}

function preferredOptionValue(prop: XiajiOptionProperty | undefined, preferred: string) {
  const allowed = new Set((prop?.ui_options ?? []).map((item) => item.value).concat(prop?.enum ?? []))
  if (preferred && (!allowed.size || allowed.has(preferred))) return preferred
  if (prop?.default != null && String(prop.default)) return String(prop.default)
  return preferred
}

function generatedResolutionLabel(definition: XiajiOptionProperty, quality: string, aspectRatio: string) {
  const megapixels = definition.megapixels_by_quality?.[quality]
  const match = aspectRatio.match(/(?:\d+(?:\.\d+)?|\.\d+)\s*:\s*(?:\d+(?:\.\d+)?|\.\d+)/)?.[0]
  const [aspectWidth, aspectHeight] = match?.split(":").map(Number) ?? []
  if (!megapixels || !aspectWidth || !aspectHeight) return undefined
  const preview = definition.ui_resolution_preview
  const multiple = preview?.multiple ?? 32
  const ratio = aspectWidth / aspectHeight
  let width = Math.round(Math.sqrt(megapixels * 1024 * 1024 * ratio) / multiple) * multiple
  let height = Math.round(Math.sqrt((megapixels * 1024 * 1024) / ratio) / multiple) * multiple
  const maxWidth = ratio >= 1 ? preview?.max_width : preview?.max_height
  const maxHeight = ratio >= 1 ? preview?.max_height : preview?.max_width
  if (maxWidth && maxHeight && (width > maxWidth || height > maxHeight)) {
    const scale = Math.min(maxWidth / width, maxHeight / height)
    width = Math.max(multiple, Math.round((width * scale) / multiple) * multiple)
    height = Math.max(multiple, Math.round((height * scale) / multiple) * multiple)
  }
  return `${width} × ${height}`
}

function sketchable(beat: XiajiBeat) {
  return beat.kind !== "scene_heading" || Boolean(beat.action || beat.heading)
}

function beatPreview(beat: XiajiBeat) {
  if (beat.kind === "dialogue") return `${beat.speaker || "对白"}：${beat.dialogue}`.trim()
  if (beat.kind === "scene_heading") return beat.heading || beat.action
  return beat.action || beat.heading
}

function assetThumb(asset?: XiajiAsset | null, slot: "front" | "reverse" | "look" = "front") {
  if (!asset) return ""
  if (slot === "reverse") return String(asset.definition?.back_image_url || "")
  if (slot === "look") {
    const looks = asset.definition?.looks || []
    const withImage = looks.find((item) => item.image_url)
    return String(withImage?.image_url || asset.image_url || "")
  }
  return String(asset.image_url || "")
}

function parseTimeOfDay(heading: string) {
  const token = heading.trim().split(/\s+/).at(-1) || ""
  return TIME_OPTIONS.includes(token) ? token : undefined
}

function applyTimeOfDay(heading: string, time: string | undefined) {
  const parts = heading.trim().split(/\s+/).filter(Boolean)
  if (parts.length && TIME_OPTIONS.includes(parts[parts.length - 1])) parts.pop()
  if (time) parts.push(time)
  return parts.join(" ")
}

function markerColor(assetId: string) {
  const palette = ["#E11D48", "#2563EB", "#16A34A", "#D97706", "#7C3AED", "#0891B2", "#DB2777", "#4F46E5"]
  let total = 0
  for (let index = 0; index < assetId.length; index += 1) {
    total = Math.imul(total, 31) + assetId.charCodeAt(index)
  }
  return palette[Math.abs(total) % palette.length]
}

function ActorPills({
  characters,
  characterIds,
  speaker,
}: {
  characters: XiajiAsset[]
  characterIds: string[]
  speaker: string
}) {
  const present = characters.filter((item) => characterIds.includes(item.id))
  if (!present.length) {
    return (
      <span className="xiaji-sketch-actor-pill">
        <span className="xiaji-sketch-actor-dot" />
        <span>{speaker || "未绑定角色"}</span>
      </span>
    )
  }
  return (
    <>
      {present.map((item) => {
        const look = item.definition?.looks?.[0]
        const lookName = look && typeof look === "object" && "name" in look ? String(look.name || "") : ""
        return (
          <span key={item.id} className="xiaji-sketch-actor-pill">
            <span className="xiaji-sketch-actor-dot" style={{ background: markerColor(item.id) }} />
            <span>
              {item.name}
              {lookName ? ` · ${lookName}` : ""}
            </span>
          </span>
        )
      })}
    </>
  )
}

function BeatGridCard({
  beat,
  selected,
  showSketch,
  onSelect,
}: {
  beat: XiajiBeat
  selected: boolean
  showSketch: boolean
  onSelect: () => void
}) {
  const pending = beat.status === "queued" || beat.status === "generating"
  return (
    <button
      type="button"
      data-beat-id={beat.id}
      className={`xiaji-shot-tile${selected ? " is-selected" : ""}`}
      onClick={onSelect}
    >
      <span className="xiaji-shot-tile-num">Beat {beat.sequence}</span>
      <div className="xiaji-shot-tile-media">
        {showSketch && beat.sketch_url ? (
          <img src={beat.sketch_url} alt="" />
        ) : pending ? (
          <Spin size="small" />
        ) : (
          <ImageIcon size={22} />
        )}
      </div>
      <p>{beatPreview(beat) || "未填写画面"}</p>
    </button>
  )
}

function AssetChip({
  asset,
  checked,
  onToggle,
}: {
  asset: XiajiAsset
  checked: boolean
  onToggle: () => void
}) {
  const thumb = assetThumb(asset, asset.kind === "character" ? "look" : "front")
  return (
    <button type="button" className={`xiaji-ref-chip${checked ? " is-on" : ""}`} onClick={onToggle}>
      {thumb ? <img src={thumb} alt="" /> : <span>{asset.name.slice(0, 1)}</span>}
      {asset.name}
    </button>
  )
}

function Inspector({
  csrfToken,
  episode,
  beat,
  assets,
  sceneView,
  onSceneView,
  onSaved,
  generating,
  onGenerate,
}: {
  csrfToken: string
  episode: XiajiEpisode
  beat: XiajiBeat
  assets: XiajiAsset[]
  sceneView: "front" | "reverse"
  onSceneView: (value: "front" | "reverse") => void
  onSaved: () => Promise<unknown>
  generating: boolean
  onGenerate: (force: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [heading, setHeading] = useState(beat.heading)
  const [speaker, setSpeaker] = useState(beat.speaker)
  const [dialogue, setDialogue] = useState(beat.dialogue)
  const [action, setAction] = useState(beat.action)
  const [sceneId, setSceneId] = useState(beat.scene_id || "")
  const [characterIds, setCharacterIds] = useState(beat.character_ids)
  const [propIds, setPropIds] = useState(beat.prop_ids)

  useEffect(() => {
    setHeading(beat.heading)
    setSpeaker(beat.speaker)
    setDialogue(beat.dialogue)
    setAction(beat.action)
    setSceneId(beat.scene_id || "")
    setCharacterIds(beat.character_ids)
    setPropIds(beat.prop_ids)
  }, [beat])

  const characters = assets.filter((item) => item.kind === "character")
  const scenes = assets.filter((item) => item.kind === "scene")
  const props = assets.filter((item) => item.kind === "prop")
  const scene = scenes.find((item) => item.id === sceneId)
  const pending = beat.status === "queued" || beat.status === "generating"

  const saveMutation = useMutation({
    mutationFn: (payload: Parameters<typeof patchXiajiBeat>[3]) => patchXiajiBeat(csrfToken, episode.id, beat.id, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episode.id] })
      await onSaved()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadXiajiBeatSketch(csrfToken, episode.id, beat.id, file),
    onSuccess: async () => {
      message.success("已上传草图")
      await queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episode.id] })
      await onSaved()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const waitAndRefresh = async (jobId: string | null | undefined) => {
    if (!jobId) return
    await waitForXiajiImageJob(jobId)
    await queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episode.id] })
    await onSaved()
  }

  const [videoFamily, setVideoFamily] = useState(DEFAULT_XIAJI_VIDEO_WORKFLOW)
  const [videoDuration, setVideoDuration] = useState("5")
  const [videoQuality, setVideoQuality] = useState("0.2")
  const [videoSpeed, setVideoSpeed] = useState("balanced")
  const [videoCustomSteps, setVideoCustomSteps] = useState(8)

  const renderMutation = useMutation({
    mutationFn: (force: boolean) => generateXiajiBeatRender(csrfToken, episode.id, beat.id, force, sceneView),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episode.id] })
      if (result.job_id) void waitAndRefresh(result.job_id)
    },
    onError: (error: Error) => message.error(error.message),
  })

  const videoMutation = useMutation({
    mutationFn: () =>
      generateXiajiBeatVideo(csrfToken, episode.id, beat.id, {
        force: true,
        family: videoFamily,
        duration: Number(videoDuration) || 5,
        quality: videoQuality,
        aspect_ratio: VIDEO_ASPECT_RATIO,
        speed: videoSpeed,
        custom_steps: videoSpeed === "custom" ? videoCustomSteps : undefined,
        scene_view: sceneView,
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episode.id] })
      if (result.job_id) void waitAndRefresh(result.job_id)
    },
    onError: (error: Error) => message.error(error.message),
  })

  const modesQuery = useQuery({
    queryKey: ["xiaji-workflow-modes"],
    queryFn: listXiajiWorkflowModes,
  })
  const videoModes = (modesQuery.data?.modes ?? []).filter(isXiajiShotVideoMode)
  const selectedVideoMode = videoModes.find((item) => item.id === videoFamily) || videoModes[0]
  const optionSchema = videoOptionSchema(selectedVideoMode)
  const durationProp = optionSchema.duration
  const qualityProp = optionSchema.quality
  const speedProp = optionSchema.speed
  const customStepsProp = optionSchema.custom_steps
  const qualityChoices = selectChoices(qualityProp)
  const resolutionChoices = qualityChoices.map((item) => ({
    value: item.value,
    label: generatedResolutionLabel(qualityProp || {}, item.value, VIDEO_ASPECT_RATIO) || item.label,
  }))
  const speedChoices = selectChoices(speedProp)
  const showCustomSteps = Boolean(customStepsProp && videoSpeed === (customStepsProp.ui_visible_when?.speed || "custom"))

  const persist = (override?: Partial<{ heading: string; speaker: string; dialogue: string; action: string; scene_id: string; character_ids: string[]; prop_ids: string[] }>) => {
    void saveMutation.mutate({
      heading,
      speaker,
      dialogue,
      action,
      scene_id: sceneId || null,
      character_ids: characterIds,
      prop_ids: propIds,
      ...override,
    })
  }

  const toggleId = (list: string[], id: string) => (list.includes(id) ? list.filter((item) => item !== id) : [...list, id])

  const frontUrl = assetThumb(scene, "front")
  const reverseUrl = assetThumb(scene, "reverse")
  const currentBg = sceneView === "reverse" ? reverseUrl || frontUrl : frontUrl

  // 折叠状态（默认展开文案、草图、视频）
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    text: true,
    sketch: true,
    render: true,
    video: true,
  })

  useEffect(() => {
    const modes = (modesQuery.data?.modes ?? []).filter(isXiajiShotVideoMode)
    if (!modes.length) return
    if (!modes.some((item) => item.id === videoFamily)) {
      const preferred = modes.find((item) => item.id === DEFAULT_XIAJI_VIDEO_WORKFLOW) || modes[0]
      setVideoFamily(preferred.id)
    }
  }, [modesQuery.data, videoFamily])

  useEffect(() => {
    const schema = videoOptionSchema(selectedVideoMode)
    setVideoDuration(preferredOptionValue(schema.duration, "5"))
    setVideoQuality(preferredOptionValue(schema.quality, "0.2"))
    setVideoSpeed(preferredOptionValue(schema.speed, "balanced"))
    const stepsDefault = schema.custom_steps?.default
    if (typeof stepsDefault === "number") setVideoCustomSteps(stepsDefault)
  }, [selectedVideoMode?.id])

  const toggleSection = (key: string) => {
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <section className="xiaji-shot-pane-container min-w-0 flex-1 overflow-hidden">
      <div className="flex h-full min-h-0 flex-col">
        {/* 顶部 Header 状态栏 */}
        <div className="xiaji-shot-pane-topbar flex min-h-10 shrink-0 items-center justify-between gap-3 border-b border-white/[0.055] px-3 py-2">
          <span className="font-mono text-xs font-medium leading-none tabular-nums text-primary">
            Beat {beat.sequence}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              title="重建索引"
              className="xiaji-pane-btn"
              onClick={() => {
                void onSaved()
                message.success("已刷新分镜索引")
              }}
            >
              <RefreshCw size={12} />
              <span>重建索引</span>
            </button>
            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 text-xs">
              <div className="flex items-center gap-1">
                <button type="button" title="草图网格" className="xiaji-pane-btn">
                  <Grid2X2 size={12} />
                  <span>草图网格</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* 纵向滚动内容区 */}
        <div className="min-h-0 flex-1 overflow-hidden">
          <div className="flex h-full flex-col overflow-hidden">
            <div className="xiaji-pane-scroll-area min-h-0 flex-1 overflow-y-auto">
              {/* 1. 文案 Section */}
              <div className="xiaji-pane-section">
                <div
                  className="xiaji-pane-section-header sticky top-0 z-20 flex min-h-11 items-center border-b border-white/[0.055] bg-[#111111] text-sm font-semibold text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.03)] transition-colors hover:bg-white/[0.035] hover:text-foreground cursor-pointer select-none"
                  onClick={() => toggleSection("text")}
                >
                  <button type="button" className="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2.5 text-left bg-transparent border-0 text-inherit cursor-pointer">
                    <ChevronDown className={`size-3.5 text-muted-foreground/55 transition-transform ${openSections.text ? "" : "-rotate-90"}`} />
                    <FileText size={16} className="text-muted-foreground/85" />
                    <span className="font-semibold tracking-tight text-foreground/90">文案</span>
                  </button>
                  <span className="mr-3 inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full border px-2 text-[10px] font-normal border-primary/18 bg-primary/[0.09] text-primary/90">
                    <Check size={10} className="text-primary" />
                    <span aria-hidden="true" className="size-1.5 rounded-full bg-primary" />
                    已编辑
                  </span>
                </div>
                {openSections.text && (
                  <div className="xiaji-pane-section-body p-3">
                    <div className="xiaji-shot-form">
                      {beat.kind === "dialogue" ? (
                        <>
                          <label>
                            <span>台词</span>
                            <Input.TextArea
                              rows={3}
                              value={dialogue}
                              placeholder="输入对白台词..."
                              onChange={(event) => setDialogue(event.target.value)}
                              onBlur={() => persist()}
                            />
                          </label>
                          <label>
                            <span>说话人</span>
                            <Select
                              allowClear
                              value={speaker || undefined}
                              placeholder="选择身份"
                              options={characters.map((item) => ({ value: item.name, label: item.name }))}
                              onChange={(value) => {
                                const next = value || ""
                                setSpeaker(next)
                                persist({ speaker: next })
                              }}
                            />
                          </label>
                        </>
                      ) : null}
                      <div className="xiaji-shot-form-row">
                        <label>
                          <span>场景</span>
                          <Select
                            allowClear
                            value={sceneId || undefined}
                            placeholder="选择场景"
                            options={scenes.map((item) => ({ value: item.id, label: item.name }))}
                            onChange={(value) => {
                              const next = value || ""
                              setSceneId(next)
                              persist({ scene_id: next })
                            }}
                          />
                        </label>
                        <label>
                          <span>时间</span>
                          <Select
                            allowClear
                            value={parseTimeOfDay(heading)}
                            placeholder="日 / 夜"
                            options={TIME_OPTIONS.map((item) => ({ value: item, label: item }))}
                            onChange={(value) => {
                              const next = applyTimeOfDay(heading, value)
                              setHeading(next)
                              persist({ heading: next })
                            }}
                          />
                        </label>
                      </div>
                      <label>
                        <span>场景说明</span>
                        <Input value={heading} onChange={(event) => setHeading(event.target.value)} onBlur={() => persist()} />
                      </label>
                      <label>
                        <span>画面描述</span>
                        <Input.TextArea rows={4} value={action} placeholder="描述画面中角色动作与环境视觉..." onChange={(event) => setAction(event.target.value)} onBlur={() => persist()} />
                      </label>
                      <div>
                        <span>出场身份</span>
                        <div className="xiaji-ref-chips mt-1">
                          {characters.length ? (
                            characters.map((item) => (
                              <AssetChip
                                key={item.id}
                                asset={item}
                                checked={characterIds.includes(item.id)}
                                onToggle={() => {
                                  const next = toggleId(characterIds, item.id)
                                  setCharacterIds(next)
                                  persist({ character_ids: next })
                                }}
                              />
                            ))
                          ) : (
                            <Typography.Text type="secondary">请先在资产库生成角色</Typography.Text>
                          )}
                        </div>
                      </div>
                      <div>
                        <span>出场道具</span>
                        <div className="xiaji-ref-chips mt-1">
                          {props.length ? (
                            props.map((item) => (
                              <AssetChip
                                key={item.id}
                                asset={item}
                                checked={propIds.includes(item.id)}
                                onToggle={() => {
                                  const next = toggleId(propIds, item.id)
                                  setPropIds(next)
                                  persist({ prop_ids: next })
                                }}
                              />
                            ))
                          ) : (
                            <Typography.Text type="secondary">未规划道具</Typography.Text>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* 2. 草图 Section */}
              <div className="xiaji-pane-section">
                <div
                  className="xiaji-pane-section-header sticky top-0 z-20 flex min-h-11 items-center border-b border-white/[0.055] bg-[#111111] text-sm font-semibold text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.03)] transition-colors hover:bg-white/[0.035] hover:text-foreground cursor-pointer select-none"
                  onClick={() => toggleSection("sketch")}
                >
                  <button type="button" className="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2.5 text-left bg-transparent border-0 text-inherit cursor-pointer">
                    <ChevronDown className={`size-3.5 text-muted-foreground/55 transition-transform ${openSections.sketch ? "" : "-rotate-90"}`} />
                    <Pencil size={16} className="text-muted-foreground/85" />
                    <span className="font-semibold tracking-tight text-foreground/90">草图</span>
                  </button>
                  <span className="mr-3 inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full border px-2 text-[10px] font-normal border-primary/18 bg-primary/[0.09] text-primary/90">
                    <span aria-hidden="true" className="size-1.5 rounded-full bg-primary" />
                    {pending ? "生成中" : beat.sketch_url ? "已选中" : "未生成"}
                  </span>
                </div>
                {openSections.sketch && (
                  <div className="xiaji-pane-section-body p-3">
                    <div className="xiaji-sketch-exact-block">
                      {/* 1. 角色/造型 Tag */}
                      <div className="xiaji-sketch-actor-row">
                        <ActorPills characters={characters} characterIds={characterIds} speaker={speaker} />
                      </div>

                      {/* 2. 主草图大卡片 + 右侧缩略图 */}
                      <div className="xiaji-sketch-cards-row">
                        <div className="xiaji-sketch-main-card">
                          {beat.sketch_url ? (
                            <Image src={beat.sketch_url} alt={`Beat ${beat.sequence}`} />
                          ) : pending ? (
                            <div className="xiaji-sketch-placeholder">
                              <Spin size="small" />
                              <span>AI 绘制中...</span>
                            </div>
                          ) : (
                            <div className="xiaji-sketch-placeholder" onClick={() => onGenerate(false)}>
                              <ImageIcon size={28} strokeWidth={1.2} />
                              <span>待生成草图</span>
                            </div>
                          )}
                        </div>

                        <div className="xiaji-sketch-thumb-card">
                          {beat.sketch_url ? (
                            <img src={beat.sketch_url} alt="" />
                          ) : (
                            <div className="xiaji-sketch-thumb-placeholder" />
                          )}
                          <span className="xiaji-sketch-version-badge">4.2d</span>
                        </div>
                      </div>

                      {/* 3. 底部 8 个工具按钮 */}
                      <div className="xiaji-sketch-bottom-toolbar">
                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          disabled={generating || pending}
                          onClick={() => onGenerate(true)}
                        >
                          <RefreshCw size={12} className={generating || pending ? "animate-spin" : ""} />
                          <span>重新生成</span>
                        </button>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已打开姿势骨骼编辑")}
                        >
                          <User size={12} />
                          <span>姿势编辑</span>
                        </button>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已开启画面画幅裁剪")}
                        >
                          <Crop size={12} />
                          <span>裁剪保存</span>
                        </button>

                        <Popover
                          trigger="click"
                          placement="top"
                          content={
                            <div className="xiaji-sketch-bg-popover p-1">
                              <div className="text-xs font-semibold mb-2">背景视角切换</div>
                              <div className="flex gap-2">
                                <Button
                                  size="small"
                                  type={sceneView === "front" ? "primary" : "default"}
                                  disabled={!frontUrl}
                                  onClick={() => onSceneView("front")}
                                >
                                  场景正面
                                </Button>
                                <Button
                                  size="small"
                                  type={sceneView === "reverse" ? "primary" : "default"}
                                  disabled={!reverseUrl}
                                  onClick={() => onSceneView("reverse")}
                                >
                                  场景背面
                                </Button>
                              </div>
                            </div>
                          }
                        >
                          <button type="button" className="xiaji-sketch-tool-btn">
                            <LucideImage size={12} />
                            <span>背景</span>
                          </button>
                        </Popover>

                        <a
                          className={`xiaji-sketch-tool-btn ${!beat.sketch_url ? "is-disabled" : ""}`}
                          href={beat.sketch_url || undefined}
                          target="_blank"
                          download
                        >
                          <Download size={12} />
                          <span>下载</span>
                        </a>

                        <Upload
                          accept="image/png,image/jpeg,image/webp,image/gif"
                          showUploadList={false}
                          beforeUpload={(file) => {
                            void uploadMutation.mutate(file)
                            return false
                          }}
                        >
                          <button type="button" className="xiaji-sketch-tool-btn">
                            <UploadIcon size={12} />
                            <span>上传</span>
                          </button>
                        </Upload>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已在导演世界同步草图骨骼绑定")}
                        >
                          <Box size={12} />
                          <span>导演世界</span>
                        </button>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已在虾画中打开独立画板")}
                        >
                          <ExternalLink size={12} />
                          <span>虾画编辑</span>
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* 3. 渲染图 Section */}
              <div className="xiaji-pane-section">
                <div
                  className="xiaji-pane-section-header sticky top-0 z-20 flex min-h-11 items-center border-b border-white/[0.055] bg-[#111111] text-sm font-semibold text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.03)] transition-colors hover:bg-white/[0.035] hover:text-foreground cursor-pointer select-none"
                  onClick={() => toggleSection("render")}
                >
                  <button type="button" className="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2.5 text-left bg-transparent border-0 text-inherit cursor-pointer">
                    <ChevronDown className={`size-3.5 text-muted-foreground/55 transition-transform ${openSections.render ? "" : "-rotate-90"}`} />
                    <LucideImage size={16} className="text-muted-foreground/85" />
                    <span className="font-semibold tracking-tight text-foreground/90">渲染图</span>
                  </button>
                  <span className="mr-3 inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full border px-2 text-[10px] font-normal border-primary/18 bg-primary/[0.09] text-primary/90">
                    <span aria-hidden="true" className="size-1.5 rounded-full bg-primary" />
                    {beat.render_status === "queued" || beat.render_status === "generating" || renderMutation.isPending
                      ? "生成中"
                      : beat.render_url
                        ? "已渲染"
                        : "待渲染"}
                  </span>
                </div>
                {openSections.render && (
                  <div className="xiaji-pane-section-body p-3">
                    <div className="xiaji-sketch-exact-block">
                      {/* 1. 角色/造型 Tag */}
                      <div className="xiaji-sketch-actor-row">
                        <ActorPills characters={characters} characterIds={characterIds} speaker={speaker} />
                      </div>

                      <div className="xiaji-sketch-cards-row">
                        <div className="xiaji-sketch-main-card">
                          {beat.render_url ? (
                            <Image src={beat.render_url} alt={`Beat ${beat.sequence} 渲染图`} />
                          ) : renderMutation.isPending || beat.render_status === "queued" || beat.render_status === "generating" ? (
                            <div className="xiaji-sketch-placeholder">
                              <Spin size="small" />
                              <span>精绘中...</span>
                            </div>
                          ) : (
                            <div
                              className="xiaji-sketch-placeholder"
                              onClick={() => {
                                if (!beat.sketch_url) {
                                  message.info("请先生成草图")
                                  return
                                }
                                renderMutation.mutate(false)
                              }}
                            >
                              <LucideImage size={28} strokeWidth={1.2} />
                              <span>待精绘渲染</span>
                            </div>
                          )}
                        </div>

                        <div className="xiaji-sketch-thumb-card">
                          {beat.render_url ? (
                            <img src={beat.render_url} alt="" />
                          ) : (
                            <div className="xiaji-sketch-thumb-placeholder" />
                          )}
                          <span className="xiaji-sketch-version-badge">4K.hd</span>
                        </div>
                      </div>

                      <div className="xiaji-sketch-bottom-toolbar">
                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          disabled={!beat.sketch_url || renderMutation.isPending}
                          onClick={() => renderMutation.mutate(true)}
                        >
                          <RefreshCw size={12} />
                          <span>{beat.render_url ? "重新生成" : "精绘渲染"}</span>
                        </button>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已开启画面画质超分增强")}
                        >
                          <Sparkles size={12} />
                          <span>画质增强</span>
                        </button>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已开启画面画幅裁剪")}
                        >
                          <Crop size={12} />
                          <span>裁剪保存</span>
                        </button>

                        <Popover
                          trigger="click"
                          placement="top"
                          content={
                            <div className="xiaji-sketch-bg-popover p-1">
                              <div className="text-xs font-semibold mb-2">场景对齐与光影</div>
                              <div className="flex gap-2">
                                <Button size="small" type={sceneView === "front" ? "primary" : "default"} onClick={() => onSceneView("front")}>
                                  场景正面
                                </Button>
                                <Button size="small" type={sceneView === "reverse" ? "primary" : "default"} onClick={() => onSceneView("reverse")}>
                                  场景背面
                                </Button>
                              </div>
                            </div>
                          }
                        >
                          <button type="button" className="xiaji-sketch-tool-btn">
                            <LucideImage size={12} />
                            <span>背景对齐</span>
                          </button>
                        </Popover>

                        <a
                          className={`xiaji-sketch-tool-btn ${!beat.render_url ? "is-disabled" : ""}`}
                          href={beat.render_url || undefined}
                          target="_blank"
                          download
                        >
                          <Download size={12} />
                          <span>下载</span>
                        </a>

                        <Upload
                          accept="image/png,image/jpeg,image/webp,image/gif"
                          showUploadList={false}
                          beforeUpload={(file) => {
                            void uploadMutation.mutate(file)
                            return false
                          }}
                        >
                          <button type="button" className="xiaji-sketch-tool-btn">
                            <UploadIcon size={12} />
                            <span>上传</span>
                          </button>
                        </Upload>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已在导演世界同步渲染图资产")}
                        >
                          <Box size={12} />
                          <span>导演世界</span>
                        </button>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已在虾画中打开精修画板")}
                        >
                          <ExternalLink size={12} />
                          <span>虾画精修</span>
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* 4. 视频 Section (内联模型、时长、MP、分辨率、部署步数参数) */}
              <div className="xiaji-pane-section">
                <div
                  className="xiaji-pane-section-header sticky top-0 z-20 flex min-h-11 items-center border-b border-white/[0.055] bg-[#111111] text-sm font-semibold text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.03)] transition-colors hover:bg-white/[0.035] hover:text-foreground cursor-pointer select-none"
                  onClick={() => toggleSection("video")}
                >
                  <button type="button" className="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2.5 text-left bg-transparent border-0 text-inherit cursor-pointer">
                    <ChevronDown className={`size-3.5 text-muted-foreground/55 transition-transform ${openSections.video ? "" : "-rotate-90"}`} />
                    <Video size={16} className="text-muted-foreground/85" />
                    <span className="font-semibold tracking-tight text-foreground/90">视频</span>
                  </button>

                  {/* 视频内联快捷参数控件 */}
                  <div className="mr-3 hidden shrink-0 items-center gap-2 md:flex" onClick={(e) => e.stopPropagation()}>
                    <Select
                      size="small"
                      value={videoFamily}
                      onChange={(val) => setVideoFamily(val)}
                      className="xiaji-header-select min-w-[180px]"
                      options={
                        videoModes.length
                          ? videoModes.map((item) => ({ value: item.id, label: item.name }))
                          : [{ value: DEFAULT_XIAJI_VIDEO_WORKFLOW, label: "LightX2V 多参考视频" }]
                      }
                    />
                    <div className="flex items-center gap-1">
                      <span className="text-[10px] text-muted-foreground">时长</span>
                      <Select
                        size="small"
                        value={videoDuration}
                        onChange={(val) => setVideoDuration(val)}
                        className="xiaji-header-select w-[76px]"
                        options={durationChoices(durationProp)}
                      />
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="text-[10px] text-muted-foreground">MP</span>
                      <Select
                        size="small"
                        value={videoQuality}
                        onChange={(val) => setVideoQuality(val)}
                        className="xiaji-header-select w-[88px]"
                        options={qualityChoices.length ? qualityChoices : [{ value: "0.2", label: "0.2 MP" }]}
                      />
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="text-[10px] text-muted-foreground">分辨率</span>
                      <Select
                        size="small"
                        value={videoQuality}
                        onChange={(val) => setVideoQuality(val)}
                        className="xiaji-header-select min-w-[118px]"
                        options={resolutionChoices.length ? resolutionChoices : [{ value: "0.2", label: "608 × 352" }]}
                      />
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="text-[10px] text-muted-foreground">部署</span>
                      <Select
                        size="small"
                        value={videoSpeed}
                        onChange={(val) => setVideoSpeed(val)}
                        className="xiaji-header-select min-w-[128px]"
                        options={speedChoices.length ? speedChoices : [{ value: "balanced", label: "均衡（8 步）" }]}
                      />
                    </div>
                    {showCustomSteps ? (
                      <InputNumber
                        size="small"
                        min={Number(customStepsProp?.minimum ?? 1)}
                        max={Number(customStepsProp?.maximum ?? 40)}
                        value={videoCustomSteps}
                        onChange={(val) => setVideoCustomSteps(Number(val) || 8)}
                        className="xiaji-header-select w-[72px]"
                      />
                    ) : null}
                  </div>

                  <span className="mr-3 inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full border px-2 text-[10px] font-normal border-primary/18 bg-primary/[0.09] text-primary/90">
                    <span aria-hidden="true" className="size-1.5 rounded-full bg-primary" />
                    {videoMutation.isPending || beat.video_status === "queued" || beat.video_status === "generating"
                      ? "生成中"
                      : beat.video_url
                        ? "已生成"
                        : "未生成"}
                  </span>
                </div>

                {openSections.video && (
                  <div className="xiaji-pane-section-body p-3">
                    <div className="xiaji-sketch-exact-block">
                      <div className="xiaji-sketch-actor-row">
                        <span className="xiaji-sketch-actor-pill">
                          <span className="xiaji-sketch-actor-dot" />
                          <span>
                            {(selectedVideoMode?.name || videoFamily)} · {videoDuration}秒 · {selectedVideoMode?.reference_mode === "collection" ? "多参考 R2V" : "首帧 I2V"}
                          </span>
                        </span>
                      </div>

                      <div className="xiaji-sketch-cards-row">
                        <div className="xiaji-video-exact-card">
                          {beat.video_url ? (
                            <video src={beat.video_url} controls playsInline className="xiaji-video-player" />
                          ) : videoMutation.isPending || beat.video_status === "queued" || beat.video_status === "generating" ? (
                            <div className="xiaji-sketch-placeholder">
                              <Spin size="small" />
                              <span>视频生成中...</span>
                            </div>
                          ) : beat.render_url ? (
                            <div className="xiaji-video-preview-wrapper">
                              <img src={beat.render_url} alt="视频首帧驱动" />
                              <div className="xiaji-video-canvas-badge">基于渲染图首帧驱动</div>
                            </div>
                          ) : (
                            <div className="xiaji-sketch-placeholder">
                              <Video size={28} strokeWidth={1.2} />
                              <span>待生成分镜视频</span>
                            </div>
                          )}
                        </div>

                        <div className="xiaji-sketch-thumb-card">
                          {beat.render_url ? (
                            <img src={beat.render_url} alt="" />
                          ) : (
                            <div className="xiaji-sketch-thumb-placeholder" />
                          )}
                          <span className="xiaji-sketch-version-badge">{videoDuration}s</span>
                        </div>
                      </div>

                      <div className="xiaji-sketch-bottom-toolbar">
                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn is-primary"
                          disabled={!beat.render_url || videoMutation.isPending}
                          onClick={() => videoMutation.mutate()}
                        >
                          <Video size={12} />
                          <span>生成视频</span>
                        </button>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          disabled={!beat.sketch_url}
                          onClick={() => message.info("已开启运镜与动态微调")}
                        >
                          <Sparkles size={12} />
                          <span>镜头微调</span>
                        </button>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已开启时间轴画幅裁剪")}
                        >
                          <Crop size={12} />
                          <span>裁剪保存</span>
                        </button>

                        <Popover
                          trigger="click"
                          placement="top"
                          content={
                            <div className="xiaji-sketch-bg-popover p-1">
                              <div className="text-xs font-semibold mb-2">背景与空间视角</div>
                              <div className="flex gap-2">
                                <Button size="small" type={sceneView === "front" ? "primary" : "default"} onClick={() => onSceneView("front")}>
                                  场景正面
                                </Button>
                                <Button size="small" type={sceneView === "reverse" ? "primary" : "default"} onClick={() => onSceneView("reverse")}>
                                  场景背面
                                </Button>
                              </div>
                            </div>
                          }
                        >
                          <button type="button" className="xiaji-sketch-tool-btn">
                            <LucideImage size={12} />
                            <span>背景</span>
                          </button>
                        </Popover>

                        <a
                          className={`xiaji-sketch-tool-btn ${!beat.video_url ? "is-disabled" : ""}`}
                          href={beat.video_url || undefined}
                          target="_blank"
                          download
                        >
                          <Download size={12} />
                          <span>下载</span>
                        </a>

                        <Upload
                          accept="video/mp4,video/webm"
                          showUploadList={false}
                          beforeUpload={() => false}
                        >
                          <button type="button" className="xiaji-sketch-tool-btn">
                            <UploadIcon size={12} />
                            <span>上传</span>
                          </button>
                        </Upload>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已同步至导演世界时间轴")}
                        >
                          <Box size={12} />
                          <span>导演世界</span>
                        </button>

                        <button
                          type="button"
                          className="xiaji-sketch-tool-btn"
                          onClick={() => message.info("已打开全屏播放监视器")}
                        >
                          <ExternalLink size={12} />
                          <span>全屏监视</span>
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

export default function XiajiShotsWorkbench({
  csrfToken,
  episode,
  onRefresh,
}: {
  csrfToken: string
  episode: XiajiEpisode
  onRefresh: () => Promise<unknown>
}) {
  const queryClient = useQueryClient()
  const shots = episode.beats.filter(sketchable)
  const [selectedId, setSelectedId] = useState(shots[0]?.id || "")
  const [showSketch, setShowSketch] = useState(true)
  const [sceneViews, setSceneViews] = useState<Record<string, "front" | "reverse">>({})
  const [splitPct, setSplitPct] = useState(() => {
    const saved = Number(window.localStorage.getItem(SPLIT_KEY))
    return Number.isFinite(saved) && saved >= 28 && saved <= 72 ? saved : 42
  })
  const splitRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const assetsQuery = useQuery({
    queryKey: ["xiaji-assets", episode.project_id],
    queryFn: () => listXiajiAssets(episode.project_id),
  })
  const assets = assetsQuery.data ?? []
  const selected = shots.find((item) => item.id === selectedId) || shots[0]

  useEffect(() => {
    if (selectedId && shots.some((item) => item.id === selectedId)) return
    setSelectedId(shots[0]?.id || "")
  }, [selectedId, shots])

  useEffect(() => {
    if (!selected) return
    const card = splitRef.current?.querySelector<HTMLElement>(`[data-beat-id="${selected.id}"]`)
    card?.scrollIntoView({ block: "nearest" })
  }, [selected?.id])

  const runJob = async (jobId: string | null | undefined) => {
    if (!jobId) return
    await waitForXiajiImageJob(jobId)
    await queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episode.id] })
    await queryClient.invalidateQueries({ queryKey: ["xiaji-episodes", episode.project_id] })
    await onRefresh()
  }

  const oneMutation = useMutation({
    mutationFn: ({ beatId, force, sceneView }: { beatId: string; force: boolean; sceneView: "front" | "reverse" }) =>
      generateXiajiBeatSketch(csrfToken, episode.id, beatId, force, sceneView),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episode.id] })
      if (result.job_id) void runJob(result.job_id)
    },
    onError: (error: Error) => message.error(error.message),
  })

  const batchMutation = useMutation({
    mutationFn: () => generateXiajiEpisodeSketches(csrfToken, episode.id, false),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episode.id] })
      for (const jobId of result.job_ids || []) void runJob(jobId)
      message.success(result.job_ids?.length ? `已入队 ${result.job_ids.length} 张草图` : "没有需要新生成的镜头")
    },
    onError: (error: Error) => message.error(error.message),
  })

  const sketched = useMemo(() => shots.filter((item) => item.sketch_url).length, [shots])

  const onSplitPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    dragging.current = true
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const onSplitPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragging.current || !splitRef.current) return
    const rect = splitRef.current.getBoundingClientRect()
    const next = Math.min(72, Math.max(28, ((event.clientX - rect.left) / rect.width) * 100))
    setSplitPct(next)
  }
  const onSplitPointerUp = () => {
    if (!dragging.current) return
    dragging.current = false
    window.localStorage.setItem(SPLIT_KEY, String(Math.round(splitPct)))
  }

  if (!shots.length) {
    return <Empty description="请先在「剧本」里生成脚本" />
  }

  return (
    <div className="xiaji-shots-workbench">
      <div className="xiaji-shots-toolbar">
        <Checkbox checked={showSketch} onChange={(event) => setShowSketch(event.target.checked)}>
          草图
        </Checkbox>
        <Typography.Text type="secondary">
          {sketched}/{shots.length} 张草图
        </Typography.Text>
        <Button type="primary" icon={<Sparkles size={14} />} loading={batchMutation.isPending} onClick={() => batchMutation.mutate()}>
          生成本集草图
        </Button>
      </div>
      <div ref={splitRef} className="xiaji-shots-split">
        <section className="xiaji-shots-grid-pane" style={{ width: `${splitPct}%` }}>
          <div className="xiaji-shot-tiles">
            {shots.map((beat) => (
              <BeatGridCard
                key={beat.id}
                beat={beat}
                selected={selected?.id === beat.id}
                showSketch={showSketch}
                onSelect={() => setSelectedId(beat.id)}
              />
            ))}
          </div>
        </section>
        <div
          className="xiaji-shots-gutter"
          role="separator"
          aria-orientation="vertical"
          onPointerDown={onSplitPointerDown}
          onPointerMove={onSplitPointerMove}
          onPointerUp={onSplitPointerUp}
        />
        <section className="xiaji-shots-detail">
          {selected ? (
            <Inspector
              csrfToken={csrfToken}
              episode={episode}
              beat={selected}
              assets={assets}
              sceneView={sceneViews[selected.id] || "front"}
              onSceneView={(value) => setSceneViews((current) => ({ ...current, [selected.id]: value }))}
              onSaved={onRefresh}
              generating={oneMutation.isPending && oneMutation.variables?.beatId === selected.id}
              onGenerate={(force) =>
                oneMutation.mutate({
                  beatId: selected.id,
                  force,
                  sceneView: sceneViews[selected.id] || "front",
                })
              }
            />
          ) : (
            <Empty description="选择左侧镜头" />
          )}
        </section>
      </div>
    </div>
  )
}
