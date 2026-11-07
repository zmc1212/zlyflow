// 资产库面板 —— 逐行复刻自 dev0914 z-admin/src/views/project/AssetsLibraryPane.vue
// Vue → React 对应：ref→useState、computed→useMemo、watch(deep)→useEffect、onMounted/onBeforeUnmount→useEffect 清理；
// selectedAsset 的深响应直接改写在 React 中统一收敛为 applySelected/mutateSelected（同步维护 ref 供定时器与卸载前保存读取），
// 自动保存队列（700ms 防抖 + 串行队列 + beforeunload keepalive）行为与原版一致。
// 角色/场景/道具工作区与各弹窗已按原版内部分区下沉到 ./assets/ 子组件。
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react"
import type { XYPosition } from "@xyflow/react"
import { useSearchParams } from "react-router-dom"
import { reconcileAssetGeneration } from "../asset-generation-result"
import { Button, Checkbox, Form, Input, Modal, Popconfirm, Segmented, Space, Spin, Tag, message } from "antd"
import {
  Boxes,
  Compass,
  Edit3,
  Plus,
  Save,
  Search,
  Shirt,
  Sparkles,
  Trash2,
  ArrowLeft,
  ArrowRight,
} from "lucide-react"
import {
  listAssets,
  listJobs,
  createAsset,
  updateAsset,
  deleteAsset,
  generateAssetImage,
  uploadAssetSourceReference,
  uploadAssetProductionImage,
  deleteAssetSourceReference,
  inferAssetPromptsFromReferences,
  uploadAssetVoice,
  applyAssetVoicePreset,
  deleteAssetVoice,
  previewAssetVoice,
  listVoiceExtractSources,
  extractAssetVoiceFromShot,
  director2ErrorDetail,
  type Director2Asset,
  type VoiceExtractSource,
} from "../api"
import CharacterWorkspace from "./assets/CharacterWorkspace"
import SceneWorkspace from "./assets/SceneWorkspace"
import PropWorkspace from "./assets/PropWorkspace"
import CreateAssetModal from "./assets/CreateAssetModal"
import EditSceneModal from "./assets/EditSceneModal"
import EditPropModal from "./assets/EditPropModal"
import IdentityModal from "./assets/IdentityModal"
import VoiceExtractModal from "./assets/VoiceExtractModal"
import {
  ASSET_TABS,
  kindLabel,
  getKindColor,
  getKindIcon,
  getKindMetaBadge,
  getSubRoleDisplay,
  getAssetDisplayAvatar,
  getAssetGradient,
  copyText,
  identityLookEnqueueBlocker,
  type AssetIdentity,
  type GenerateImageResult,
} from "./assets/shared"
import type { CreateFormState } from "./assets/CreateAssetModal"
import type { SceneDraft } from "./assets/EditSceneModal"
import type { PropDraft } from "./assets/EditPropModal"
import type { IdentityFormState } from "./assets/IdentityModal"
import { MAX_SOURCE_REFERENCE_BYTES, remainingSourceReferenceSlots, sourceReferencesOf } from "../asset-source-references"
import { MAX_VOICE_AUDIO_BYTES, hasRefAudio, isVoiceAudioFile, voiceOf } from "../voice-profile"
import { useMediaPreview } from "../media-preview"
import "./assets-library.css"
import { assetReadiness } from "../project-flow"
import { planAssetGeneration, visibleAssetSelection } from "../asset-library-generation"
import "./production-assets.css"
import { creativeStyleText } from "../creative-presets"
import { assetCreativeSettings, compileAssetCreativePrompt } from "../asset-canvas-creative"
import AssetCreationCanvas, { AssetCanvasCreateModal, type AssetCanvasActions } from "./AssetCreationCanvas"
import { appendCanvasReference, assetCanvasJobNode, assetNodeId, assetSlotPrompt, buildAssetCanvas, canvasIdentities, patchAssetSlotPrompt, readAssetCanvasLayout, targetKey, type AssetCanvasTarget } from "../asset-canvas-model"
import AssetCanvasVoiceModal from "./assets/AssetCanvasVoiceModal"

interface AssetsLibraryPaneProps {
  csrfToken: string
  projectId: string
  projectName?: string
  onChanged?: () => void
  onBack?: () => void
  onContinue?: () => void | Promise<void>
}

export type AssetsLibraryPaneHandle = {
  fetchAssets: () => Promise<void> | void
}

type AutoSaveState = "idle" | "pending" | "saving" | "saved" | "error"

const AUTO_SAVE_STATUS_TEXT: Record<AutoSaveState, string> = {
  idle: "修改后自动保存",
  pending: "有修改，准备保存",
  saving: "正在自动保存",
  saved: "已自动保存",
  error: "自动保存失败",
}

const AssetsLibraryPane = forwardRef<AssetsLibraryPaneHandle, AssetsLibraryPaneProps>(function AssetsLibraryPane(
  { csrfToken, projectId, projectName, onChanged, onBack, onContinue },
  ref,
) {
  const { openMediaPreview } = useMediaPreview()
  const [searchParams, setSearchParams] = useSearchParams()
  const [detailOpen, setDetailOpen] = useState(!!searchParams.get("asset") || searchParams.get("view") === "canvas")
  const [canvasWorking, setCanvasWorking] = useState<string | null>(null)
  const canvasWorkingRef = useRef<string | null>(null)
  const [canvasRecoveredWork, setCanvasRecoveredWork] = useState<string | null>(null)
  const canvasRecoveredWorkRef = useRef<string | null>(null)
  const [canvasJobsLoading, setCanvasJobsLoading] = useState(true)
  const [canvasErrors, setCanvasErrors] = useState<Record<string, string>>({})
  const [canvasVoiceOpen, setCanvasVoiceOpen] = useState(false)
  const canvasCreateOrigin = useRef<XYPosition | null>(null)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([])
  const [batchProgress, setBatchProgress] = useState<{ completed: number; total: number; label: string } | null>(null)
  const batchGeneratingRef = useRef(false)
  const [continuing, setContinuing] = useState(false)
  const [flowModal, flowModalContext] = Modal.useModal()
  const [assets, setAssets] = useState<Director2Asset[]>([])
  const [selectedAsset, setSelectedAsset] = useState<Director2Asset | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [autoSaveState, setAutoSaveState] = useState<AutoSaveState>("idle")

  // 与 Vue 实例级可变量（let autoSaveTimer / autoSaveQueuedSnapshot / autoSaveRunner / suppressAutoSave）对应的 ref
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const autoSaveQueuedSnapshotRef = useRef(new Map<string, Director2Asset>())
  const failedSaveSnapshotsRef = useRef(new Map<string, Director2Asset>())
  const autoSaveRunnerRef = useRef<Promise<void> | null>(null)
  const suppressAutoSaveRef = useRef(false)

  // 各生成动作的独立 Loading 状态
  const [generatingIdentityId, setGeneratingIdentityId] = useState<string | null>(null)
  const [generatingMaster, setGeneratingMaster] = useState(false)
  const [generatingReverse, setGeneratingReverse] = useState(false)
  const [uploadingSourceRef, setUploadingSourceRef] = useState(false)
  const [inferringSourcePrompts, setInferringSourcePrompts] = useState(false)
  const [uploadingVoice, setUploadingVoice] = useState(false)
  const [previewingVoice, setPreviewingVoice] = useState(false)
  const [applyingVoicePreset, setApplyingVoicePreset] = useState(false)
  const [voiceExtractOpen, setVoiceExtractOpen] = useState(false)
  const [extractSources, setExtractSources] = useState<VoiceExtractSource[]>([])
  const [loadingExtractSources, setLoadingExtractSources] = useState(false)
  const [extractingVoice, setExtractingVoice] = useState(false)
  const [generatingPano, setGeneratingPano] = useState(false)
  const [generatingProp, setGeneratingProp] = useState(false)
  const [generatingPropTurnaround, setGeneratingPropTurnaround] = useState(false)
  const [generatingPropDetail, setGeneratingPropDetail] = useState(false)

  const [submitting, setSubmitting] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)

  // 场景编辑弹窗状态 (对齐 source2 SceneDialog)——草稿状态下沉到 EditSceneModal
  const [editSceneModalVisible, setEditSceneModalVisible] = useState(false)
  const [savingSceneModal, setSavingSceneModal] = useState(false)

  // 道具编辑弹窗状态 (对齐 source2 PropDialog)——草稿状态下沉到 EditPropModal
  const [editPropModalVisible, setEditPropModalVisible] = useState(false)
  const [savingPropModal, setSavingPropModal] = useState(false)

  // 360 全景查看器状态
  const [panoViewerVisible, setPanoViewerVisible] = useState(false)
  const [currentPanoUrl, setCurrentPanoUrl] = useState("")

  // 手动输入直链弹窗
  const [manualUrlModalVisible, setManualUrlModalVisible] = useState(false)
  const [manualUrlTarget, setManualUrlTarget] = useState("master")
  const [manualUrlInput, setManualUrlInput] = useState("")

  const [identityModalVisible, setIdentityModalVisible] = useState(false)
  const [savingIdentity, setSavingIdentity] = useState(false)

  // 去掉「全部」，默认显示「角色」
  const [currentTab, setCurrentTab] = useState("character")
  const [searchKeyword, setSearchKeyword] = useState("")

  // 原版遗留的生成配置（未被模板与逻辑引用，逐行保留）
  const [genConfig] = useState({ model: "NanoBanana 标准", aspect_ratio: "1:1" })
  void genConfig

  // —— 同步 ref（供 setTimeout / beforeunload / 异步续体读取最新值，等价 Vue 的 .value 语义）——
  const assetsRef = useRef<Director2Asset[]>([])
  const selectedAssetRef = useRef<Director2Asset | null>(null)
  const currentTabRef = useRef("character")
  const searchKeywordRef = useRef("")
  const autoSaveStateRef = useRef<AutoSaveState>("idle")
  const projectIdRef = useRef(projectId)

  useEffect(() => {
    projectIdRef.current = projectId
  }, [projectId])

  function setAssetsList(next: Director2Asset[]) {
    assetsRef.current = next
    setAssets(next)
  }

  function replaceAssetInList(id: string, replacement: Director2Asset) {
    setAssetsList(assetsRef.current.map((a) => (a.id === id ? { ...replacement } : a)))
  }

  function applySelected(next: Director2Asset | null) {
    selectedAssetRef.current = next
    setSelectedAsset(next)
  }

  function mutateSelected(updater: (prev: Director2Asset) => Director2Asset): Director2Asset | null {
    const prev = selectedAssetRef.current
    if (!prev) return null
    const next = updater(prev)
    applySelected(next)
    return next
  }

  function setTab(tabKey: string) {
    currentTabRef.current = tabKey
    setCurrentTab(tabKey)
  }

  function handleSearchChange(value: string) {
    searchKeywordRef.current = value
    setSearchKeyword(value)
  }

  function updateAutoSaveState(v: AutoSaveState) {
    autoSaveStateRef.current = v
    setAutoSaveState(v)
  }

  const autoSaveStatusText = AUTO_SAVE_STATUS_TEXT[autoSaveState] || "修改后自动保存"

  function getCountByKind(k: string): number {
    return assets.filter((a) => a.kind === k).length
  }

  const filteredAssets = useMemo(() => {
    let list = assets.filter((a) => a.kind === currentTab)
    const kw = searchKeyword.trim().toLowerCase()
    if (kw) {
      list = list.filter(
        (a) =>
          (a.name && a.name.toLowerCase().includes(kw)) ||
          (a.role && a.role.toLowerCase().includes(kw)) ||
          (a.description && a.description.toLowerCase().includes(kw)),
      )
    }
    return list
  }, [assets, currentTab, searchKeyword])

  const visibleSelectedIds = visibleAssetSelection(filteredAssets, selectedAssetIds)
  const missingAssetCount = assets.filter(asset => asset.kind === currentTab && assetReadiness(asset).ready < assetReadiness(asset).total).length

  useEffect(() => {
    setSelectedAssetIds([])
    setSelectionMode(false)
  }, [currentTab, searchKeyword, projectId])

  function cloneAssetSnapshot(asset: Director2Asset | null): Director2Asset | null {
    return asset ? JSON.parse(JSON.stringify(asset)) as Director2Asset : null
  }

  async function runAutoSaveQueue() {
    while (autoSaveQueuedSnapshotRef.current.size) {
      const snapshot = autoSaveQueuedSnapshotRef.current.values().next().value!
      autoSaveQueuedSnapshotRef.current.delete(snapshot.id)
      if (!snapshot.name?.trim()) {
        updateAutoSaveState("error")
        message.warning("名称不能为空，当前修改未保存")
        continue
      }
      setSaving(true)
      updateAutoSaveState("saving")
      try {
        const updated = await updateAsset(csrfToken, projectId, snapshot.id, snapshot)
        failedSaveSnapshotsRef.current.delete(snapshot.id)
        const pending = autoSaveQueuedSnapshotRef.current.get(snapshot.id)
        const editing = selectedAssetRef.current?.id === snapshot.id && autoSaveTimerRef.current ? selectedAssetRef.current : null
        replaceAssetInList(snapshot.id, pending || editing || updated)
        updateAutoSaveState(failedSaveSnapshotsRef.current.size ? "error" : autoSaveQueuedSnapshotRef.current.size || autoSaveTimerRef.current ? "pending" : "saved")
      } catch (err) {
        failedSaveSnapshotsRef.current.set(snapshot.id, snapshot)
        updateAutoSaveState("error")
        message.error(director2ErrorDetail(err, "自动保存失败，请检查网络后继续修改"))
      } finally {
        setSaving(false)
      }
    }
  }

  function enqueueAutoSave(snapshot: Director2Asset | null) {
    if (!snapshot?.id) return Promise.resolve()
    autoSaveQueuedSnapshotRef.current.set(snapshot.id, snapshot)
    if (!autoSaveRunnerRef.current) {
      autoSaveRunnerRef.current = runAutoSaveQueue().finally(() => {
        autoSaveRunnerRef.current = null
        const next = autoSaveQueuedSnapshotRef.current.values().next().value
        if (next) enqueueAutoSave(next)
      })
    }
    return autoSaveRunnerRef.current
  }

  function flushAutoSave() {
    const hadPendingTimer = Boolean(autoSaveTimerRef.current)
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current)
      autoSaveTimerRef.current = null
    }
    const sel = selectedAssetRef.current
    if (sel && (hadPendingTimer || autoSaveStateRef.current === "pending")) {
      return enqueueAutoSave(cloneAssetSnapshot(sel))
    }
    return autoSaveRunnerRef.current || Promise.resolve()
  }

  function persistPendingAssetBeforeUnload() {
    const sel = selectedAssetRef.current
    if (!sel || !["pending", "saving"].includes(autoSaveStateRef.current)) return
    const snapshot = cloneAssetSnapshot(sel)
    if (!snapshot) return
    const body = JSON.stringify(snapshot)
    if (body.length > 60000) return
    const encProjectId = encodeURIComponent(projectIdRef.current)
    const assetId = encodeURIComponent(snapshot.id)
    fetch(`/api/projects/${encProjectId}/assets/${assetId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {})
  }

  async function handleSaveDetail() {
    if (!selectedAssetRef.current) return
    for (const failed of failedSaveSnapshotsRef.current.values()) autoSaveQueuedSnapshotRef.current.set(failed.id, failed)
    updateAutoSaveState("pending")
    await flushAutoSave()
  }

  // 对应原版 watch(selectedAsset, { deep: true })：任何一次选中资产变更都会重置 700ms 防抖定时器
  useEffect(() => {
    if (suppressAutoSaveRef.current) {
      suppressAutoSaveRef.current = false
      return
    }
    if (!selectedAsset?.id) return
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current)
    updateAutoSaveState("pending")
    autoSaveTimerRef.current = setTimeout(() => {
      autoSaveTimerRef.current = null
      enqueueAutoSave(cloneAssetSnapshot(selectedAssetRef.current))
    }, 700)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAsset])

  useEffect(() => {
    setVoiceExtractOpen(false)
    setExtractSources([])
  }, [selectedAsset?.id])

  function selectAsset(ast: Director2Asset) {
    flushAutoSave()
    const copy = JSON.parse(JSON.stringify(ast)) as Director2Asset
    if (!copy.extra) copy.extra = {}

    if (copy.kind === "character") {
      if (!copy.extra.identities) copy.extra.identities = []
    } else if (copy.kind === "scene") {
      if (!copy.extra.environment_prompt) {
        copy.extra.environment_prompt = copy.visual_prompt || copy.description || `${copy.name}，电影级实景空间，忠于剧本的时代与环境设定，自然光影`
      }
      if (!copy.extra.reverse_prompt) {
        copy.extra.reverse_prompt = `${copy.name}，对立反打机位视角，180度对立景深透视，空间镜头，8k`
      }
      if (!copy.extra.pano_prompt) {
        copy.extra.pano_prompt = `${copy.name}，360度球形全景等距柱状图，无缝环视无死角，8k`
      }
    } else if (copy.kind === "prop") {
      if (!copy.extra.visual_prompt) {
        copy.extra.visual_prompt = copy.visual_prompt || `${copy.name} 概念参考图，电影级质感，真实器物纹理光影，8k`
      }
      if (!copy.extra.turnaround_prompt) {
        copy.extra.turnaround_prompt = `${copy.name} 道具三视图转面设计，正视、侧视、背视，纯色背景，工业造型图纸，8k`
      }
      if (!copy.extra.detail_prompt) {
        copy.extra.detail_prompt = `${copy.name} 静物微距特写摄影，局部材质包浆与雕刻细节，8k`
      }
      if (!copy.extra.owner) {
        copy.extra.owner = copy.role || ""
      }
      if (!copy.extra.prop_type) {
        copy.extra.prop_type = "object"
      }
    }

    suppressAutoSaveRef.current = true
    applySelected(copy)
    updateAutoSaveState("idle")
  }

  async function fetchAssets() {
    setLoading(true)
    try {
      const res = await listAssets(projectId)
      const list = res || []
      setAssetsList(list)
      const charList = list.filter((a) => a.kind === currentTabRef.current)
      if (charList.length > 0) {
        if (!selectedAssetRef.current || selectedAssetRef.current.kind !== currentTabRef.current) {
          selectAsset(charList[0])
        } else {
          const found = list.find((a) => a.id === selectedAssetRef.current?.id)
          if (found) selectAsset(found)
        }
      } else if (list.length > 0) {
        setTab(list[0].kind)
        selectAsset(list[0])
      } else {
        applySelected(null)
      }
    } catch {
      message.error("加载资产列表失败")
    } finally {
      setLoading(false)
    }
  }

  function handleTabChange(tabKey: string) {
    setTab(tabKey)
    setTimeout(() => {
      const kw = (searchKeywordRef.current || "").trim().toLowerCase()
      let list = assetsRef.current.filter((a) => a.kind === tabKey)
      if (kw) {
        list = list.filter(
          (a) =>
            (a.name && a.name.toLowerCase().includes(kw)) ||
            (a.role && a.role.toLowerCase().includes(kw)) ||
            (a.description && a.description.toLowerCase().includes(kw)),
        )
      }
      if (list.length > 0) {
        if (!selectedAssetRef.current || selectedAssetRef.current.kind !== tabKey) {
          if (detailOpen) openAsset(list[0])
          else selectAsset(list[0])
        }
      } else {
        applySelected(null)
        if (detailOpen) closeAsset()
      }
    }, 50)
  }

  function applyGeneratedAsset(assetId: string, res: GenerateImageResult) {
    const update = reconcileAssetGeneration(assetsRef.current, selectedAssetRef.current, assetId, res?.asset)
    if (!update) return
    setAssetsList(update.assets)
    const pending = autoSaveQueuedSnapshotRef.current.get(assetId)
    if (pending?.id === assetId) {
      autoSaveQueuedSnapshotRef.current.set(assetId, reconcileAssetGeneration([pending], pending, assetId, res.asset)?.selected || pending)
    }
    if (selectedAssetRef.current?.id === assetId && update.selected) {
      suppressAutoSaveRef.current = true
      applySelected(update.selected)
    }
  }

  function applyServerAsset(asset: Director2Asset) {
    replaceAssetInList(asset.id, asset)
    if (autoSaveQueuedSnapshotRef.current.has(asset.id)) {
      autoSaveQueuedSnapshotRef.current.set(asset.id, cloneAssetSnapshot(asset)!)
    }
    if (selectedAssetRef.current?.id === asset.id) {
      suppressAutoSaveRef.current = true
      applySelected({ ...asset })
    }
  }

  async function generateSelectedAssets() {
    if (batchGeneratingRef.current || canvasWorkingRef.current || canvasRecoveredWorkRef.current || canvasJobsLoading) return
    const selectedIds = visibleAssetSelection(filteredAssets, selectedAssetIds)
    if (!selectedIds.length) return
    batchGeneratingRef.current = true
    try {
      await flushAutoSave()
      if (autoSaveStateRef.current === "error") { message.error("资产修改尚未保存，请先重试保存"); return }
      const plan = planAssetGeneration(assetsRef.current, selectedIds)
      if (!plan.items.length) {
        if (plan.blocked.length) message.warning(`${plan.blocked[0].label}：${plan.blocked[0].reason}`)
        else message.info("所选资产图片已就绪，可打开资产重新生成")
        return
      }
      setBatchProgress({ completed: 0, total: plan.items.length, label: "正在准备资产…" })
      const failures: string[] = []
      let completed = 0
      for (const item of plan.items) {
        const key = assetNodeId(item.assetId, targetKey(item.target))
        canvasWorkingRef.current = key; setCanvasWorking(key)
        setBatchProgress({ completed, total: plan.items.length, label: item.label })
        setCanvasErrors(previous => { const next = { ...previous }; delete next[key]; return next })
        try {
          const asset = canvasAsset(item.assetId)
          if (item.target.type === "identity") {
            const identities = canvasIdentities(asset)
            if (JSON.stringify(identities) !== JSON.stringify(asset.extra?.identities)) {
              const saved = await updateAsset(csrfToken, projectId, asset.id, { extra: { ...asset.extra, identities } })
              applyServerAsset(saved)
            }
          }
          const result = await generateAssetImage(csrfToken, projectId, item.assetId, item.payload)
          applyGeneratedAsset(item.assetId, result)
        } catch (err) {
          const reason = director2ErrorDetail(err, "图片生成失败")
          failures.push(`${item.label}：${reason}`)
          setCanvasErrors(previous => ({ ...previous, [key]: reason }))
        }
        completed += 1
        setBatchProgress({ completed, total: plan.items.length, label: item.label })
      }
      const skipped = plan.blocked.length ? `，${plan.blocked.length} 个形象缺少描述或参考图，未生成` : ""
      if (failures.length) message.warning({ content: `已生成 ${completed - failures.length}/${plan.items.length} 张${skipped}；${failures.slice(0, 2).join("；")}`, duration: 8 })
      else if (skipped) message.warning({ content: `已生成 ${completed} 张${skipped}`, duration: 6 })
      else message.success(`已生成 ${completed} 张图片`)
      onChanged?.()
    } catch (err) {
      message.error(director2ErrorDetail(err, "资产生成失败"))
    } finally {
      batchGeneratingRef.current = false
      canvasWorkingRef.current = null; setCanvasWorking(null); setBatchProgress(null)
    }
  }

  async function handleUploadSourceRefs(files: File[]) {
    const sel = selectedAssetRef.current
    if (!sel || !files.length) return
    const remaining = remainingSourceReferenceSlots(sel)
    const accepted: File[] = []
    for (const file of files.slice(0, remaining)) {
      if (!file.type.startsWith("image/") && !/\.(jpe?g|png|webp|gif)$/i.test(file.name)) {
        message.warning(`「${file.name}」不是图片`)
        continue
      }
      if (file.size > MAX_SOURCE_REFERENCE_BYTES) {
        message.warning(`「${file.name}」超过 10 MB`)
        continue
      }
      accepted.push(file)
    }
    if (!accepted.length) return
    setUploadingSourceRef(true)
    try {
      let latest = sel
      for (const file of accepted) {
        latest = await uploadAssetSourceReference(csrfToken, projectId, sel.id, file)
        applyServerAsset(latest)
      }
      message.success(`已上传 ${accepted.length} 张原片参考图`)
    } catch (err) {
      message.error(director2ErrorDetail(err, "上传参考图失败"))
    } finally {
      setUploadingSourceRef(false)
    }
  }

  async function handleRemoveSourceRef(refId: string) {
    const sel = selectedAssetRef.current
    if (!sel) return
    try {
      const updated = await deleteAssetSourceReference(csrfToken, projectId, sel.id, refId)
      applyServerAsset(updated)
      message.success("已删除原片参考图")
    } catch (err) {
      message.error(director2ErrorDetail(err, "删除参考图失败"))
    }
  }

  async function handleInferSourcePrompts() {
    const sel = selectedAssetRef.current
    if (!sel) return
    if (!sourceReferencesOf(sel).length) {
      message.warning("请先上传至少一张原片参考图")
      return
    }
    setInferringSourcePrompts(true)
    try {
      const updated = await inferAssetPromptsFromReferences(csrfToken, projectId, sel.id)
      applyServerAsset(updated)
      message.success("已根据原片截图覆盖提示词")
    } catch (err) {
      message.error(director2ErrorDetail(err, "反推提示词失败"))
    } finally {
      setInferringSourcePrompts(false)
    }
  }

  async function handleUploadVoice(file: File) {
    const sel = selectedAssetRef.current
    if (!sel) return
    if (!isVoiceAudioFile(file)) {
      message.warning("请上传 wav / mp3 / m4a / flac / ogg")
      return
    }
    if (file.size > MAX_VOICE_AUDIO_BYTES) {
      message.warning("参考音不能超过 20 MB")
      return
    }
    setUploadingVoice(true)
    try {
      const updated = await uploadAssetVoice(csrfToken, projectId, sel.id, file)
      applyServerAsset(updated)
      message.success("已绑定角色参考音")
    } catch (err) {
      message.error(director2ErrorDetail(err, "上传参考音失败"))
    } finally {
      setUploadingVoice(false)
    }
  }

  async function handleApplyVoicePreset(presetId: string) {
    const sel = selectedAssetRef.current
    if (!sel) return
    setApplyingVoicePreset(true)
    try {
      const updated = await applyAssetVoicePreset(csrfToken, projectId, sel.id, presetId)
      applyServerAsset(updated)
      message.success("已绑定内置短剧声线")
    } catch (err) {
      message.error(director2ErrorDetail(err, "绑定内置声线失败"))
    } finally {
      setApplyingVoicePreset(false)
    }
  }

  async function handleDeleteVoice() {
    const sel = selectedAssetRef.current
    if (!sel) return
    try {
      const updated = await deleteAssetVoice(csrfToken, projectId, sel.id)
      applyServerAsset(updated)
      message.success("已删除角色参考音")
    } catch (err) {
      message.error(director2ErrorDetail(err, "删除参考音失败"))
    }
  }

  async function handlePreviewVoice() {
    const sel = selectedAssetRef.current
    if (!sel) return
    const voice = voiceOf(sel.extra)
    if (!hasRefAudio(sel.extra)) {
      message.warning("请先绑定角色参考音")
      return
    }
    setPreviewingVoice(true)
    try {
      const result = await previewAssetVoice(csrfToken, projectId, sel.id, {
        default_emotion: voice.default_emotion,
        emo_alpha: voice.emo_alpha,
        duration_factor: voice.duration_factor,
      })
      applyServerAsset(result.asset)
      message.success("试听已生成")
    } catch (err) {
      message.error(director2ErrorDetail(err, "试听失败"))
    } finally {
      setPreviewingVoice(false)
    }
  }

  async function handleOpenVoiceExtract() {
    const sel = selectedAssetRef.current
    if (!sel) return
    setVoiceExtractOpen(true)
    setLoadingExtractSources(true)
    try {
      const payload = await listVoiceExtractSources(projectId, sel.id)
      setExtractSources(payload.sources || [])
    } catch (err) {
      setExtractSources([])
      message.error(director2ErrorDetail(err, "列出成片失败"))
    } finally {
      setLoadingExtractSources(false)
    }
  }

  async function submitVoiceExtract(payload: {
    episode_id: string
    beat_id: string
    start_sec: number
    end_sec: number
  }) {
    const sel = selectedAssetRef.current
    if (!sel) return
    setExtractingVoice(true)
    try {
      const updated = await extractAssetVoiceFromShot(csrfToken, projectId, sel.id, payload)
      applyServerAsset(updated)
      setVoiceExtractOpen(false)
      message.success("已从成片提取角色参考音")
    } catch (err) {
      message.error(director2ErrorDetail(err, "从成片提取失败"))
    } finally {
      setExtractingVoice(false)
    }
  }

  function handleExtractVoiceFromShot(payload: {
    episode_id: string
    beat_id: string
    start_sec: number
    end_sec: number
  }) {
    const sel = selectedAssetRef.current
    if (!sel) return
    if (hasRefAudio(sel.extra)) {
      Modal.confirm({
        title: "覆盖已绑定的参考音？",
        content: "从成片提取会替换当前参考音，并清除内置声线绑定。",
        okText: "覆盖并提取",
        cancelText: "取消",
        className: "d2-assets-library",
        onOk: () => submitVoiceExtract(payload),
      })
      return
    }
    void submitVoiceExtract(payload)
  }

  function characterStylePayload(ast: Director2Asset | null) {
    const extra = ast?.extra || {}
    return {
      ethnicity: extra.ethnicity || "Chinese",
      visual_style: extra.visual_style || "",
      art_style_id: extra.art_style_id || "",
      body_type: extra.body_type || "",
      gender: extra.gender || "",
    }
  }

  // 2. 生成角色设定板 (16:9 / 2K)
  async function handleGenerateIdentityImage(ident: AssetIdentity) {
    const sel = selectedAssetRef.current
    if (!sel || !ident) return
    const blocker = identityLookEnqueueBlocker(sel, ident)
    if (blocker) {
      message.warning(blocker)
      return
    }
    const costume = (ident.description || ident.appearance_details || "").trim()
    setGeneratingIdentityId(ident.id || null)
    try {
      const res = (await generateAssetImage(csrfToken, projectId, sel.id, {
        target_type: "identity",
        identity_id: ident.id,
        prompt: costume,
        model: "gpt-image-2.5",
        aspect_ratio: "16:9",
        ...characterStylePayload(sel),
      })) as GenerateImageResult
      const refCount = Number(res.source_reference_count || sourceReferencesOf(sel).length)
      message.success(
        refCount > 0
          ? `造型「${ident.name}」已按 ${refCount} 张原片截图的服装生成`
          : `造型「${ident.name}」造型图生成成功！`,
      )
      applyGeneratedAsset(sel.id, res)
    } catch (err) {
      message.error(director2ErrorDetail(err, "造型形象生成失败"))
    } finally {
      setGeneratingIdentityId(null)
    }
  }

  // 3. 生成场景 Master 主视角 (16:9)
  async function handleGenerateSceneMaster() {
    const sel = selectedAssetRef.current
    if (!sel) return
    const prompt = (sel.extra?.environment_prompt || sel.visual_prompt || sel.name).trim()
    setGeneratingMaster(true)
    try {
      const res = (await generateAssetImage(csrfToken, projectId, sel.id, {
        target_type: "scene_master",
        prompt,
        aspect_ratio: "16:9",
      })) as GenerateImageResult
      message.success(`场景「${sel.name}」Master 主视角生成成功！`)
      applyGeneratedAsset(sel.id, res)
    } catch (err) {
      message.error(director2ErrorDetail(err, "主视角生成失败"))
    } finally {
      setGeneratingMaster(false)
    }
  }

  // 4. 生成场景 Reverse 背面（对齐 source1：16:9 + Master 为 REFERENCE 1）
  async function handleGenerateSceneReverse() {
    const sel = selectedAssetRef.current
    if (!sel) return
    const extra = sel.extra || {}
    const master = (extra.master_url || sel.image_url || "").trim()
    if (!master) {
      message.warning("请先生成或上传正面源图，背面图需要把它作为 REFERENCE 1 传入")
      return
    }
    setGeneratingReverse(true)
    try {
      const res = (await generateAssetImage(csrfToken, projectId, sel.id, {
        target_type: "scene_reverse",
        model: "gpt-image-2.5",
        aspect_ratio: "16:9",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      message.success(`场景「${sel.name}」Reverse 背面反打视角生成成功！`)
      applyGeneratedAsset(sel.id, res)
    } catch (err) {
      message.error(director2ErrorDetail(err, "反打视角生成失败"))
    } finally {
      setGeneratingReverse(false)
    }
  }

  // 5. 生成场景 Pano 360（对齐 source1：2:1 + Master/Reverse 参考图）
  async function handleGenerateScenePano() {
    const sel = selectedAssetRef.current
    if (!sel) return
    const extra = sel.extra || {}
    const master = (extra.master_url || sel.image_url || "").trim()
    if (!master) {
      message.warning("请先生成或上传正面源图，360全景需要把它作为 REFERENCE 1 传入")
      return
    }
    setGeneratingPano(true)
    try {
      const res = (await generateAssetImage(csrfToken, projectId, sel.id, {
        target_type: "scene_pano",
        model: "gpt-image-2.5",
        aspect_ratio: "2:1",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      message.success(`场景「${sel.name}」360° 全景图生成成功！`)
      applyGeneratedAsset(sel.id, res)
    } catch (err) {
      message.error(director2ErrorDetail(err, "360 全景图生成失败"))
    } finally {
      setGeneratingPano(false)
    }
  }

  // 6. 生成道具主视图（对齐 source1：16:9 产品静物正面）
  async function handleGeneratePropReference() {
    const sel = selectedAssetRef.current
    if (!sel) return
    const extra = sel.extra || {}
    setGeneratingProp(true)
    try {
      const res = (await generateAssetImage(csrfToken, projectId, sel.id, {
        target_type: "prop_reference",
        model: "gpt-image-2.5",
        aspect_ratio: "16:9",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      message.success(`道具「${sel.name}」参考图生成成功！`)
      applyGeneratedAsset(sel.id, res)
    } catch (err) {
      message.error(director2ErrorDetail(err, "道具参考图生成失败"))
    } finally {
      setGeneratingProp(false)
    }
  }

  // 7. 生成道具转面三视图（对齐 source1：16:9 1x3 + 主视图 REFERENCE 1）
  async function handleGeneratePropTurnaround() {
    const sel = selectedAssetRef.current
    if (!sel) return
    const extra = sel.extra || {}
    const master = (extra.reference_url || sel.image_url || "").trim()
    if (!master) {
      message.warning("请先生成或上传主视图，转面三视图需要把它作为 REFERENCE 1 传入")
      return
    }
    setGeneratingPropTurnaround(true)
    try {
      const res = (await generateAssetImage(csrfToken, projectId, sel.id, {
        target_type: "prop_turnaround",
        model: "gpt-image-2.5",
        aspect_ratio: "16:9",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      message.success(`道具「${sel.name}」三视图生成成功！`)
      applyGeneratedAsset(sel.id, res)
    } catch (err) {
      message.error(director2ErrorDetail(err, "三视图生成失败"))
    } finally {
      setGeneratingPropTurnaround(false)
    }
  }

  // 8. 生成道具细节特写（对齐 source1：16:9 微距 + 主视图 REFERENCE 1）
  async function handleGeneratePropDetail() {
    const sel = selectedAssetRef.current
    if (!sel) return
    const extra = sel.extra || {}
    const master = (extra.reference_url || sel.image_url || "").trim()
    if (!master) {
      message.warning("请先生成或上传主视图，细节特写需要把它作为 REFERENCE 1 传入")
      return
    }
    setGeneratingPropDetail(true)
    try {
      const res = (await generateAssetImage(csrfToken, projectId, sel.id, {
        target_type: "prop_detail",
        model: "gpt-image-2.5",
        aspect_ratio: "16:9",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      message.success(`道具「${sel.name}」细节特写生成成功！`)
      applyGeneratedAsset(sel.id, res)
    } catch (err) {
      message.error(director2ErrorDetail(err, "细节特写生成失败"))
    } finally {
      setGeneratingPropDetail(false)
    }
  }

  // 删除场景视角图片
  async function handleDeleteSceneImage(slotType: "master" | "reverse" | "pano") {
    if (!selectedAssetRef.current?.extra) return
    mutateSelected((prev) => {
      const extra = { ...(prev.extra || {}) }
      if (slotType === "master") {
        extra.master_url = ""
        return { ...prev, extra, image_url: "" }
      }
      if (slotType === "reverse") {
        extra.reverse_url = ""
        return { ...prev, extra }
      }
      extra.pano_url = ""
      return { ...prev, extra }
    })
    await handleSaveDetail()
    message.success(`已删除 ${slotType.toUpperCase()} 图片`)
  }

  // 删除道具视角图片
  async function handleDeletePropImage(slot: "reference" | "turnaround" | "detail" = "reference") {
    if (!selectedAssetRef.current?.extra) return
    mutateSelected((prev) => {
      const extra = { ...(prev.extra || {}) }
      if (slot === "reference") {
        extra.reference_url = ""
        return { ...prev, extra, image_url: "" }
      }
      if (slot === "turnaround") {
        extra.turnaround_url = ""
        return { ...prev, extra }
      }
      extra.detail_url = ""
      return { ...prev, extra }
    })
    await handleSaveDetail()
    message.success("已清除对应视角图片")
  }

  // 场景编辑弹窗
  function openEditSceneModal() {
    if (!selectedAssetRef.current) return
    setEditSceneModalVisible(true)
  }

  async function handleSaveSceneModal(draft: SceneDraft, envPrompt: string) {
    if (!draft.name.trim()) {
      message.warning("场景名称不能为空")
      return
    }
    setSavingSceneModal(true)
    try {
      const next = mutateSelected((prev) => ({
        ...prev,
        name: draft.name,
        role: draft.role,
        description: draft.description,
        visual_prompt: envPrompt,
        extra: {
          ...(prev.extra || {}),
          scene_type: draft.scene_type,
          environment_prompt: envPrompt,
        },
      }))
      if (!next) return
      const updated = await updateAsset(csrfToken, projectId, next.id, next)
      message.success("场景设定已保存更新")
      setEditSceneModalVisible(false)
      replaceAssetInList(next.id, updated)
    } catch {
      message.error("保存场景失败")
    } finally {
      setSavingSceneModal(false)
    }
  }

  // 道具编辑弹窗 (严格对齐 source2 PropDialog)
  function openEditPropModal() {
    if (!selectedAssetRef.current) return
    setEditPropModalVisible(true)
  }

  async function handleSavePropModal(draft: PropDraft) {
    if (!draft.name.trim()) {
      message.warning("道具名称不能为空")
      return
    }
    setSavingPropModal(true)
    try {
      const next = mutateSelected((prev) => ({
        ...prev,
        name: draft.name,
        role: draft.owner,
        description: draft.description,
        visual_prompt: draft.visual_prompt,
        extra: {
          ...(prev.extra || {}),
          owner: draft.owner,
          prop_type: draft.prop_type,
          visual_prompt: draft.visual_prompt,
          turnaround_prompt: draft.turnaround_prompt,
          detail_prompt: draft.detail_prompt,
        },
      }))
      if (!next) return
      const updated = await updateAsset(csrfToken, projectId, next.id, next)
      message.success("道具设定已保存更新")
      setEditPropModalVisible(false)
      replaceAssetInList(next.id, updated)
    } catch {
      message.error("保存道具失败")
    } finally {
      setSavingPropModal(false)
    }
  }

  // 360 全景查看器
  function openPanoViewerModal(url: string) {
    setCurrentPanoUrl(url)
    setPanoViewerVisible(true)
  }

  // 手动指定 URL
  function triggerManualUrlInput(target: string) {
    setManualUrlTarget(target)
    setManualUrlInput("")
    setManualUrlModalVisible(true)
  }

  async function handleConfirmManualUrl() {
    if (!manualUrlInput.trim()) {
      message.warning("请输入图片链接")
      return
    }
    const url = manualUrlInput.trim()

    mutateSelected((prev) => {
      const extra = { ...(prev.extra || {}) }
      if (manualUrlTarget === "master") {
        extra.master_url = url
        return { ...prev, extra, image_url: url }
      }
      if (manualUrlTarget === "reverse") {
        extra.reverse_url = url
        return { ...prev, extra }
      }
      if (manualUrlTarget === "pano") {
        extra.pano_url = url
        return { ...prev, extra }
      }
      if (manualUrlTarget === "prop" || manualUrlTarget === "prop_reference") {
        extra.reference_url = url
        return { ...prev, extra, image_url: url }
      }
      if (manualUrlTarget === "prop_turnaround") {
        extra.turnaround_url = url
        return { ...prev, extra }
      }
      if (manualUrlTarget === "prop_detail") {
        extra.detail_url = url
        return { ...prev, extra }
      }
      return { ...prev, extra }
    })

    setManualUrlModalVisible(false)
    await handleSaveDetail()
  }

  // 新增身份/造型弹窗
  function openAddIdentityModal() {
    if (!selectedAssetRef.current) return
    setIdentityModalVisible(true)
  }

  async function handleConfirmAddIdentity(form: IdentityFormState) {
    if (!form.name.trim()) {
      message.warning("请输入造型名称")
      return
    }
    setSavingIdentity(true)
    try {
      const next = mutateSelected((prev) => {
        const extra = { ...(prev.extra || {}) }
        const identities = [...((extra.identities as AssetIdentity[]) || [])]
        identities.push({
          id: `ident-${Date.now().toString(36)}`,
          name: form.name.trim(),
          description: form.description.trim(),
          visual_prompt: form.visual_prompt.trim(),
          image_url: "",
        })
        extra.identities = identities
        return { ...prev, extra }
      })
      if (!next) return
      const updated = await updateAsset(csrfToken, projectId, next.id, next)
      message.success(`已为「${next.name}」新增造型「${form.name}」`)
      replaceAssetInList(next.id, updated)
      setIdentityModalVisible(false)
    } catch {
      message.error("新增造型失败")
    } finally {
      setSavingIdentity(false)
    }
  }

  async function handleRemoveIdentity(idx: number) {
    const sel = selectedAssetRef.current
    if (!sel?.extra?.identities) return
    const next = mutateSelected((prev) => ({
      ...prev,
      extra: {
        ...(prev.extra || {}),
        identities: ((prev.extra?.identities as AssetIdentity[]) || []).filter((_, i) => i !== idx),
      },
    }))
    if (!next) return
    try {
      const updated = await updateAsset(csrfToken, projectId, next.id, next)
      message.success("造型已删除")
      replaceAssetInList(next.id, updated)
    } catch {
      message.error("删除造型失败")
    }
  }

  // 角色工作区字段落库辅助（自动保存由 selectedAsset 监听统一驱动）
  function patchSelectedField(patch: Partial<Director2Asset>) {
    mutateSelected((prev) => ({ ...prev, ...patch }))
  }

  function patchSelectedExtra(patch: Record<string, any>) {
    mutateSelected((prev) => ({ ...prev, extra: { ...(prev.extra || {}), ...patch } }))
  }

  function patchSelectedIdentity(idx: number, patch: Record<string, any>) {
    mutateSelected((prev) => ({
      ...prev,
      extra: {
        ...(prev.extra || {}),
        identities: ((prev.extra?.identities as AssetIdentity[]) || []).map((it, i) =>
          i === idx ? { ...it, ...patch } : it,
        ),
      },
    }))
  }

  async function handleDeleteAsset(id: string) {
    try {
      await deleteAsset(csrfToken, projectId, id)
      message.success("资产已删除")
      await fetchAssets()
    } catch {
      message.error("删除失败")
    }
  }

  function openCreateModal() {
    // createForm 的重置等价下沉到 CreateAssetModal 的 destroyOnHidden 挂载初始化
    setModalVisible(true)
  }

  async function handleCreateSubmit(form: CreateFormState) {
    if (!form.name.trim()) {
      message.warning("请输入名称")
      return
    }
    setSubmitting(true)
    try {
      const position = canvasCreateOrigin.current
      const created = await createAsset(csrfToken, projectId, { ...form, ...(position ? { extra: { creation_canvas: { version: 1, positions: { group: { ...position } }, links: [] } } } : {}) })
      canvasCreateOrigin.current = null
      message.success(`「${created.name}」创建成功`)
      setModalVisible(false)
      setTab(created.kind)
      await fetchAssets()
      if (created && created.id) {
        const found = assetsRef.current.find((a) => a.id === created.id)
        if (found) openAsset(found)
      }
    } catch (err) {
      message.error(director2ErrorDetail(err, "创建失败"))
    } finally {
      setSubmitting(false)
    }
  }

  useImperativeHandle(ref, () => ({ fetchAssets }))

  const requestedAsset = searchParams.get("asset")
  const requestedView = searchParams.get("view")
  useEffect(() => {
    if (!requestedAsset) { setDetailOpen(requestedView === "canvas"); return }
    const found = assets.find(asset => asset.id === requestedAsset)
    if (found && selectedAssetRef.current?.id !== found.id) { setTab(found.kind); selectAsset(found) }
    if (found) setDetailOpen(true)
    // A URL addresses the same asset ID as the existing detail editor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedAsset, requestedView, assets])

  function openAsset(asset: Director2Asset) {
    if (selectedAssetRef.current?.id !== asset.id) selectAsset(asset)
    setDetailOpen(true)
    setSearchParams(current => { const next = new URLSearchParams(current); next.set("asset", asset.id); next.set("view", "canvas"); return next }, { replace: detailOpen })
  }
  async function closeAsset() {
    await flushAutoSave()
    if (autoSaveStateRef.current === "error") { message.error("资产修改尚未保存，请重试保存后再返回"); return }
    setDetailOpen(false)
    setSearchParams(current => { const next = new URLSearchParams(current); next.delete("asset"); next.delete("view"); next.delete("node"); return next })
    onChanged?.()
  }

  function canvasAsset(id: string) {
    const asset = selectedAssetRef.current?.id === id ? selectedAssetRef.current : assetsRef.current.find(item => item.id === id)
    if (!asset) throw new Error("资产不存在，请刷新资产库")
    return asset
  }
  function patchCanvasAsset(id: string, patch: Partial<Director2Asset> = {}, extra: Record<string, unknown> = {}) {
    const asset = canvasAsset(id)
    if (selectedAssetRef.current?.id !== id) openAsset(asset)
    const next = { ...canvasAsset(id), ...patch, extra: { ...canvasAsset(id).extra, ...extra } }
    suppressAutoSaveRef.current = false
    applySelected(next); replaceAssetInList(id, next); updateAutoSaveState("pending")
    return next
  }
  async function saveCanvasChanges() {
    await handleSaveDetail()
    if (autoSaveStateRef.current === "error") throw new Error("自动保存失败，请重试；修改仍保留在当前画布")
  }
  function ensureCanvasIdentity(id: string, target: AssetCanvasTarget) {
    const asset = canvasAsset(id)
    if (target.type === "identity") {
      const looks = canvasIdentities(asset)
      if (JSON.stringify(looks) !== JSON.stringify(asset.extra?.identities)) patchCanvasAsset(id, {}, { identities: looks })
    }
  }
  async function canvasGenerate(id: string, target: AssetCanvasTarget, context: { prompt?: string; images?: string[] } = {}) {
    if (batchGeneratingRef.current || canvasWorkingRef.current || canvasRecoveredWorkRef.current || canvasJobsLoading) return
    const key = assetNodeId(id, targetKey(target))
    canvasWorkingRef.current = key; setCanvasWorking(key)
    setCanvasErrors(previous => { const next = { ...previous }; delete next[key]; return next })
    try {
      ensureCanvasIdentity(id, target)
      await saveCanvasChanges()
      const asset = canvasAsset(id)
      const creative = assetCreativeSettings(asset, target)
      const design = creative.design || {}
      const result = await generateAssetImage(csrfToken, projectId, id, {
        target_type: target.type, identity_id: target.identityId,
        images: context.images || [],
        prompt: compileAssetCreativePrompt(context.prompt ?? assetSlotPrompt(asset, target), creative),
        aspect_ratio: target.type === "scene_pano" ? "2:1" : creative.aspectRatio || "16:9",
        ...(creative.model ? { model: creative.model } : {}),
        ...(creative.style ? { visual_style: creativeStyleText(creative.style) } : {}),
        ...(design["性别表达"] ? { gender: design["性别表达"] } : {}),
        ...(design["体型"] ? { body_type: design["体型"] } : {}),
        ...(design["区域 / 文化背景"] ? { ethnicity: [design["区域 / 文化背景"], design["地区细分（可选）"]].filter(Boolean).join(" / ") } : {}),
      })
      applyGeneratedAsset(id, result)
      message.success(`「${asset.name}」节点图片已更新`)
    } catch (err) {
      const detail = director2ErrorDetail(err, "节点图片生成失败")
      setCanvasErrors(previous => ({ ...previous, [key]: detail })); message.error(detail)
    } finally { canvasWorkingRef.current = null; setCanvasWorking(null) }
  }
  async function canvasUpload(id: string, target: AssetCanvasTarget | null, files: File[]) {
    if (batchGeneratingRef.current || canvasWorkingRef.current || canvasRecoveredWorkRef.current || !files.length) return
    const asset = canvasAsset(id)
    const limit = target ? 1 : remainingSourceReferenceSlots(asset)
    const accepted = files.slice(0, limit)
    if (!limit) { message.warning("每项资产最多添加 9 张参考图"); return }
    if (accepted.some(file => (!file.type.startsWith("image/") && !/\.(png|jpe?g|webp|gif)$/i.test(file.name)) || file.size > MAX_SOURCE_REFERENCE_BYTES)) { message.warning("请上传不超过 10 MB 的图片"); return }
    const key = assetNodeId(id, target ? targetKey(target) : "references")
    canvasWorkingRef.current = key; setCanvasWorking(key)
    try {
      if (target) ensureCanvasIdentity(id, target)
      await saveCanvasChanges()
      if (target) {
        const result = await uploadAssetProductionImage(csrfToken, projectId, id, target.type, target.identityId, accepted[0])
        applyGeneratedAsset(id, { asset: result })
      } else {
        for (const file of accepted) {
          const result = await uploadAssetSourceReference(csrfToken, projectId, id, file)
          patchCanvasAsset(id, {}, { source_references: result.extra.source_references })
        }
        await saveCanvasChanges()
      }
      message.success(target ? "图片已绑定到当前节点" : "参考图已添加")
    } catch (err) { message.error(director2ErrorDetail(err, "图片上传失败")) }
    finally { canvasWorkingRef.current = null; setCanvasWorking(null) }
  }
  // 稳定传给画布的资产数组引用：否则父组件任意 re-render（轮询/保存态）都会生成新数组，
  // 导致画布 buildAssetCanvas/effect 重建空转，干扰 xyflow 测量与草稿自动保存。
  const canvasAssets = useMemo(() => assets.map(asset => selectedAsset?.id === asset.id ? selectedAsset : asset), [assets, selectedAsset])
  const canvasActions: AssetCanvasActions = {
    select: id => openAsset(canvasAsset(id)), showList: closeAsset,
    create: (kind, position) => { canvasCreateOrigin.current = position ? { ...position } : null; setTab(kind); openCreateModal() },
    addLook: id => { openAsset(canvasAsset(id)); openAddIdentityModal() },
    saveDefinition: async (id, name, role, description) => { patchCanvasAsset(id, { name, role, description }, { canvas_definition: description, description }); await saveCanvasChanges() },
    saveMetadata: async (id, target, name) => {
      const asset = canvasAsset(id)
      if (target.type === "identity") patchCanvasAsset(id, {}, { identities: canvasIdentities(asset).map(look => look.id === target.identityId ? { ...look, name } : look) })
      else patchCanvasAsset(id, {}, { canvas_node_names: { ...(asset.extra?.canvas_node_names || {}), [targetKey(target)]: name } })
      await saveCanvasChanges()
    },
    prompt: (id, target, prompt) => { patchCanvasAsset(id, {}, patchAssetSlotPrompt(canvasAsset(id), target, prompt)) },
    configure: async (id, target, settings) => {
      const asset = canvasAsset(id)
      patchCanvasAsset(id, {}, { canvas_settings: { ...(asset.extra?.canvas_settings || {}), [targetKey(target)]: { ...assetCreativeSettings(asset, target), ...settings } } })
      await saveCanvasChanges()
    },
    generate: canvasGenerate, upload: canvasUpload,
    removeReference: async (id, refId) => { try { await saveCanvasChanges(); const result = await deleteAssetSourceReference(csrfToken, projectId, id, refId); patchCanvasAsset(id, {}, { source_references: result.extra.source_references }); await saveCanvasChanges() } catch (err) { message.error(director2ErrorDetail(err, "移除参考图失败")) } },
    connect: (sourceId, targetId) => {
      const graph = buildAssetCanvas(assetsRef.current), source = graph.nodes.find(node => node.id === sourceId), target = graph.nodes.find(node => node.id === targetId)
      if (!source?.data.image || target?.data.role !== "references" || source.data.asset.id === target.data.asset.id) { message.info("将已有图片连到其他资产的参考图节点"); return }
      try {
        const asset = canvasAsset(target.data.asset.id), layout = readAssetCanvasLayout(asset)
        const link = { sourceAssetId: source.data.asset.id, sourceKey: source.data.key, url: source.data.image }
        patchCanvasAsset(asset.id, {}, { source_references: appendCanvasReference(asset, link.url, `${source.data.asset.name} · ${source.data.title}`), creation_canvas: { ...layout, links: [...layout.links.filter(item => item.sourceAssetId !== link.sourceAssetId || item.sourceKey !== link.sourceKey), link] } })
        message.success("已将当前图片作为参考图快照")
      } catch (err) { message.warning(err instanceof Error ? err.message : "无法连接参考图") }
    },
    voice: id => { openAsset(canvasAsset(id)); setCanvasVoiceOpen(true) },
    save: saveCanvasChanges, continue: onContinue ? continueProduction : undefined,
  }

  useEffect(() => {
    setCanvasJobsLoading(true)
    let stopped = false, polling = false
    const read = async () => {
      if (polling) return
      polling = true
      try {
        const jobs = await listJobs(projectId)
        if (stopped) return
        const active = jobs.find(job => assetCanvasJobNode(job) && ["running", "queued", "pending"].includes(job.status))
        const next = active ? assetCanvasJobNode(active) : null
        const previous = canvasRecoveredWorkRef.current
        canvasRecoveredWorkRef.current = next; setCanvasRecoveredWork(next)
        setCanvasJobsLoading(false)
        if (previous && previous !== next) {
          const finished = jobs.find(job => assetCanvasJobNode(job) === previous)
          if (finished && ["failed", "error", "cancelled"].includes(finished.status)) setCanvasErrors(errors => ({ ...errors, [previous]: finished.error_message || "节点图片任务未完成，请在任务中心查看原因" }))
        }
        if (previous && !next && !canvasWorkingRef.current && !batchGeneratingRef.current) {
          await flushAutoSave()
          if (!stopped && autoSaveStateRef.current !== "error") await fetchAssets()
        }
      } catch { /* Preserve any known active job until the task service responds again. */ }
      finally { polling = false }
    }
    void read()
    const timer = window.setInterval(() => void read(), 5000)
    return () => { stopped = true; window.clearInterval(timer) }
    // The job view only restores pending production slots; it never resubmits them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])
  async function continueProduction() {
    if (continuing) return
    const run = async () => {
      setContinuing(true)
      try {
        flushAutoSave(); await autoSaveRunnerRef.current
        if (autoSaveStateRef.current === "error") { message.error("资产修改尚未保存，请先重试保存"); return }
        await onContinue?.()
      } finally { setContinuing(false) }
    }
    const missing = assets.filter(asset => assetReadiness(asset).ready < assetReadiness(asset).total).length
    if (missing) flowModal.confirm({ title: `还有 ${missing} 项资产待完善参考图`, content: "可以先进入分镜编辑，出片前再回来补齐参考图。", okText: "继续进入分镜", cancelText: "返回完善", onOk: run })
    else await run()
  }

  useEffect(() => {
    window.addEventListener("beforeunload", persistPendingAssetBeforeUnload)
    fetchAssets()
    return () => {
      window.removeEventListener("beforeunload", persistPendingAssetBeforeUnload)
      flushAutoSave()
    }
    // 对应原版 onMounted + onBeforeUnmount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className={`assets-library-pane d2-assets-library production-assets${detailOpen ? " is-asset-canvas" : ""}`}>
      {detailOpen ? <AssetCreationCanvas projectId={projectId} projectTitle={projectName} csrfToken={csrfToken} assets={canvasAssets} selectedId={selectedAsset?.id} selectedNode={searchParams.get("node")} saveStatus={autoSaveStatusText} saveError={autoSaveState === "error"} loading={loading || canvasJobsLoading} working={canvasWorking || canvasRecoveredWork} errors={canvasErrors} actions={canvasActions}/> : <>
      {/* 顶部操作栏 */}
      <div className="sub-pane-header">
        <div className="header-copy">
          <h2 className="sub-pane-title">{detailOpen ? selectedAsset?.name || "资产详情" : "制作资产库"}</h2>
          <p className="sub-pane-subtitle">
            统一角色造型、场景与道具，为每个镜头准备一致的视觉参考。
          </p>
        </div>

        <div className="header-actions">
          <Segmented aria-label="资产视图" value="list" disabled={!!batchProgress} options={[{ value: "list", label: "列表" }, { value: "canvas", label: "画布" }]} onChange={value => { if (value === "canvas") { if (selectedAsset) openAsset(selectedAsset); else { setDetailOpen(true); setSearchParams(current => { const next = new URLSearchParams(current); next.set("view", "canvas"); return next }) } } }}/>
          {detailOpen && <Button icon={<ArrowLeft size={14}/>} onClick={closeAsset}>返回资产列表</Button>}
          <Button type="primary" className="primary-btn" icon={<Plus size={16} />} disabled={!!batchProgress} onClick={openCreateModal}>
            新增{kindLabel(currentTab)}
          </Button>
        </div>
      </div>
      <div className="asset-library-controls">
        <Segmented
          className="asset-kind-switch"
          aria-label="资产分类"
          value={currentTab}
          disabled={!!batchProgress}
          onChange={(value) => handleTabChange(String(value))}
          options={ASSET_TABS.map((tab) => {
            const KindIcon = getKindIcon(tab.key)
            return {
              value: tab.key,
              label: <span className="asset-kind-label"><KindIcon size={13} />{tab.label}<span className="asset-kind-count">{getCountByKind(tab.key)}</span></span>,
            }
          })}
        />
        <Input className="production-asset-search" aria-label="搜索制作资产" placeholder="搜索资产…" allowClear disabled={!!batchProgress} value={searchKeyword} onChange={event => handleSearchChange(event.target.value)} prefix={<Search size={14}/>}/>
      </div>
      <div className="production-assets-status" role="region" aria-label="资产生成操作">
        <div className="production-assets-status-copy" aria-live="polite">
          {batchProgress ? <><strong>正在生成 {batchProgress.completed} / {batchProgress.total}</strong><span>{batchProgress.label}</span></> : selectionMode ? <>
            <strong>{visibleSelectedIds.length ? `已选择 ${visibleSelectedIds.length} 个${kindLabel(currentTab)}` : `请选择要生成${currentTab === "character" ? "形象图" : "设定图"}的${kindLabel(currentTab)}`}</strong>
            {visibleSelectedIds.length > 0 && <span>将补齐{currentTab === "character" ? "所有缺少的形象图" : "缺少的设定图"}，已有图片保留</span>}
          </> : <>
            <strong>生成或导入{kindLabel(currentTab)}{currentTab === "character" ? "形象图" : "设定图"}</strong>
            <span>{missingAssetCount ? `有 ${missingAssetCount} 个${kindLabel(currentTab)}${currentTab === "character" ? "未有完整形象图" : "尚无设定图"}，你可以手动上传或者 AI 批量生成` : `${kindLabel(currentTab)}${currentTab === "character" ? "形象图" : "设定图"}已就绪，可点击卡片上传或重新生成`}</span>
          </>}
        </div>
        <div className="production-assets-selection-actions">
          {selectionMode ? <>
            <Checkbox checked={filteredAssets.length > 0 && visibleSelectedIds.length === filteredAssets.length} indeterminate={visibleSelectedIds.length > 0 && visibleSelectedIds.length < filteredAssets.length} disabled={!!batchProgress || !filteredAssets.length} onChange={event => setSelectedAssetIds(event.target.checked ? filteredAssets.map(asset => asset.id) : [])}>选择全部</Checkbox>
            <Button type="text" disabled={!!batchProgress} onClick={() => { setSelectionMode(false); setSelectedAssetIds([]) }}>取消选择</Button>
            <Button type="primary" icon={<Sparkles size={14}/>} loading={!!batchProgress} disabled={!visibleSelectedIds.length || loading || canvasJobsLoading || !!canvasWorking || !!canvasRecoveredWork} onClick={() => void generateSelectedAssets()}>生成</Button>
          </> : <Button autoInsertSpace={false} disabled={!filteredAssets.length || loading} onClick={() => { setSelectedAssetIds([]); setSelectionMode(true) }}>多选</Button>}
        </div>
      </div>
      <Spin spinning={loading && assets.length > 0}>
        {loading && assets.length === 0 ? (
          <div className="production-assets-loading" role="status" aria-busy="true" aria-label="正在加载资产">
            {Array.from({ length: 10 }, (_, index) => (
              <div className="pa-loading-card" key={index} aria-hidden="true">
                <span className="studio-skeleton-bar pa-loading-cover" />
                <span className="studio-skeleton-bar" style={{ width: "64%" }} />
                <span className="studio-skeleton-bar" style={{ width: "40%" }} />
              </div>
            ))}
          </div>
        ) : assets.length === 0 ? (
          <div className="empty-asset-box">
            <Boxes size={48} className="empty-icon" />
            <h3>资产库暂无资产</h3>
            <p>在「剧本」阶段拆解制作资产，或新建角色、场景与道具节点。</p>
            <Button type="primary" onClick={openCreateModal}>立即新增第一个资产</Button>
          </div>
        ) : !detailOpen ? (
          <div className="production-asset-grid">
            {filteredAssets.map(asset => {
              const readiness = assetReadiness(asset)
              const image = getAssetDisplayAvatar(asset)
              const Icon = getKindIcon(asset.kind)
              const selected = visibleSelectedIds.includes(asset.id)
              const busy = [canvasWorking, canvasRecoveredWork].some(node => node?.startsWith(`${asset.id}::`))
              const failed = Object.keys(canvasErrors).some(node => node.startsWith(`${asset.id}::`))
              const content = <>{image ? <img src={image} alt={`${asset.name}参考图`} loading="lazy" onError={event => { event.currentTarget.style.visibility = "hidden" }}/>: <Icon size={28}/>}{busy && <span className="production-asset-working"><Spin size="small"/>正在生成</span>}{!selectionMode && <span className="production-asset-hover">上传或生成</span>}</>
              const caption = <><h3 title={asset.name}>{asset.name}</h3><p className={busy ? "" : failed ? "is-missing" : readiness.ready === readiness.total ? "is-ready" : "is-missing"}>{busy ? "图片生成中…" : failed ? "生成未完成，可重试" : readiness.label}</p></>
              return <article className={`production-asset-card${selected ? " is-selected" : ""}`} key={asset.id}>
                {selectionMode ? <Checkbox className="production-asset-choice" aria-label={`选择${asset.name}`} checked={selected} disabled={!!batchProgress} onChange={event => setSelectedAssetIds(ids => event.target.checked ? [...ids.filter(id => id !== asset.id), asset.id] : ids.filter(id => id !== asset.id))}><div className="production-asset-image">{content}</div>{caption}</Checkbox> : <><Button type="text" className="production-asset-image" aria-label={`在画布中编辑${asset.name}`} onClick={() => openAsset(asset)}>{content}</Button>{caption}</>}
              </article>
            })}
            {!filteredAssets.length && <p className="production-assets-empty">{searchKeyword ? "没有找到匹配的资产" : `暂无${kindLabel(currentTab)}，可以新建或从剧本中拆解`}</p>}
            {!selectionMode && <Button type="dashed" className="production-asset-add" icon={<Plus size={24}/>} onClick={openCreateModal}>新增{kindLabel(currentTab)}</Button>}
          </div>
        ) : (
          /* 左右结构：左边选择名称，右边显示详细与生成 (参考 source2) */
          <div className="assets-split-container">
            {/* 左侧：分类、搜索与资产名称列表 */}
            <div className="assets-sidebar-list">
              {/* 搜索过滤 */}
              <div className="sidebar-search-box">
                <Input
                  value={searchKeyword}
                  onChange={(event) => handleSearchChange(event.target.value)}
                  placeholder={`搜索${kindLabel(currentTab)}名称 / 设定...`}
                  allowClear
                  size="small"
                  prefix={<Search size={13} className="text-gray" />}
                />
              </div>

              {/* 资产列表滚动区 */}
              <div className="sidebar-items-scroll">
                {filteredAssets.length === 0 ? (
                  <div className="no-filter-match">
                    暂无{kindLabel(currentTab)}数据
                  </div>
                ) : null}
                {filteredAssets.map((ast) => (
                  <button
                    type="button"
                    key={ast.id}
                    className={`asset-list-item${selectedAsset && selectedAsset.id === ast.id ? " active" : ""}`}
                    aria-pressed={selectedAsset?.id === ast.id}
                    onClick={() => openAsset(ast)}
                  >
                    {/* 缩略图或单字头像 */}
                    <div className={`item-avatar ${ast.kind}`} style={getAssetGradient(ast.name)}>
                      {getAssetDisplayAvatar(ast) ? (
                        <img
                          src={getAssetDisplayAvatar(ast)}
                          className="avatar-img"
                          alt=""
                        />
                      ) : (
                        <span className="avatar-char">
                          {ast.name ? ast.name.slice(0, 1) : "?"}
                        </span>
                      )}
                      {getAssetDisplayAvatar(ast) ? <span className="has-image-dot" title="已有视觉图" /> : null}
                    </div>

                    {/* 名称与定位 */}
                    <div className="item-info">
                      <div className="item-name-row">
                        <span className="item-name" title={ast.name}>{ast.name}</span>
                        <Tag color={getKindColor(ast.kind)} className="kind-tag">
                          {getKindMetaBadge(ast)}
                        </Tag>
                      </div>
                      <div className="item-sub-row">
                        <span className="item-role" title={ast.role || "无定位"}>
                          {getSubRoleDisplay(ast)}
                        </span>
                        {/* 角色显示造型数，场景显示全景/机位状态，道具显示归属人 */}
                        {ast.kind === "character" && ast.extra?.identities?.length ? (
                          <span className="extra-count-chip">
                            {ast.extra.identities.length}造型
                          </span>
                        ) : ast.kind === "scene" ? (
                          <span className="extra-count-chip scene-chip">
                            {ast.extra?.pano_url ? "360°就绪" : (ast.extra?.reverse_url ? "正反打就绪" : "主视角")}
                          </span>
                        ) : ast.kind === "prop" && ast.extra?.owner ? (
                          <span className="extra-count-chip prop-chip">
                            {String(ast.extra.owner).slice(0, 4)}
                          </span>
                        ) : null}
                      </div>
                    </div>

                    {/* 选中激活指示条 */}
                    {selectedAsset && selectedAsset.id === ast.id ? <div className="item-active-bar" /> : null}
                  </button>
                ))}
              </div>
            </div>

            {/* 右侧：详细信息与 AI 形象生成工作区 (参考 source2) */}
            <div className="asset-detail-workspace">
              {!selectedAsset ? (
                <div className="empty-detail-state">
                  <div className="empty-detail-icon">
                    <Boxes size={36} />
                  </div>
                  <h4>请在左侧选择一个{kindLabel(currentTab)}</h4>
                  <p>点击左侧名称即可查看详细配置、AI 生图提示词及在线生成视觉形象。</p>
                </div>
              ) : (
                <div className="detail-content-wrap">
                  {/* 顶部操作栏 */}
                  <div className="detail-header-card">
                    <div className="header-left">
                      <div className="header-title-row">
                        <h3 className="detail-asset-name">{selectedAsset.name}</h3>
                        <Tag color={getKindColor(selectedAsset.kind)}>
                          {kindLabel(selectedAsset.kind)}
                        </Tag>
                        {selectedAsset.role ? (
                          <Tag color="blue">
                            {selectedAsset.role}
                          </Tag>
                        ) : null}
                        <span className="update-time">更新于 {(selectedAsset.updated_at || "").slice(5, 16)}</span>
                      </div>
                    </div>

                    <Space>
                      {selectedAsset.kind === "character" ? (
                        <Button
                          type="dashed"
                          className="add-identity-btn"
                          icon={<Shirt size={15} />}
                          onClick={openAddIdentityModal}
                        >
                          + 新增身份/造型
                        </Button>
                      ) : null}
                      {selectedAsset.kind === "scene" ? (
                        <Button
                          className="edit-action-btn"
                          icon={<Edit3 size={15} />}
                          onClick={openEditSceneModal}
                        >
                          编辑场景
                        </Button>
                      ) : null}
                      {selectedAsset.kind === "prop" ? (
                        <Button
                          className="edit-action-btn"
                          icon={<Edit3 size={15} />}
                          onClick={openEditPropModal}
                        >
                          编辑道具
                        </Button>
                      ) : null}
                      <span className={`auto-save-status is-${autoSaveState}`}>
                        <Save size={14} />
                        {autoSaveStatusText}
                      </span>
                      <Popconfirm
                        title="确定删除此资产？"
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                        onConfirm={() => handleDeleteAsset(selectedAsset.id)}
                      >
                        <Button danger type="text" icon={<Trash2 size={15} />}>
                          删除
                        </Button>
                      </Popconfirm>
                    </Space>
                  </div>

                  {/* ========================= A/B/C. 三类资产专属工作区 ========================= */}
                  {selectedAsset.kind === "character" ? (
                    <CharacterWorkspace
                      asset={selectedAsset}
                      onFieldChange={patchSelectedField}
                      onExtraChange={patchSelectedExtra}
                      onIdentityChange={patchSelectedIdentity}
                      generatingIdentityId={generatingIdentityId}
                      onGenerateIdentity={handleGenerateIdentityImage}
                      onRemoveIdentity={handleRemoveIdentity}
                      onOpenAddIdentity={openAddIdentityModal}
                      uploadingSourceRef={uploadingSourceRef}
                      inferringSourcePrompts={inferringSourcePrompts}
                      onUploadSourceRefs={handleUploadSourceRefs}
                      onRemoveSourceRef={handleRemoveSourceRef}
                      onInferSourcePrompts={handleInferSourcePrompts}
                      uploadingVoice={uploadingVoice}
                      previewingVoice={previewingVoice}
                      applyingVoicePreset={applyingVoicePreset}
                      onUploadVoice={handleUploadVoice}
                      onApplyVoicePreset={handleApplyVoicePreset}
                      onDeleteVoice={handleDeleteVoice}
                      onPreviewVoice={handlePreviewVoice}
                      extractingVoice={extractingVoice}
                      onExtractVoiceFromShot={handleOpenVoiceExtract}
                    />
                  ) : selectedAsset.kind === "scene" ? (
                    <SceneWorkspace
                      asset={selectedAsset}
                      onFieldChange={patchSelectedField}
                      onExtraChange={patchSelectedExtra}
                      generatingMaster={generatingMaster}
                      generatingReverse={generatingReverse}
                      generatingPano={generatingPano}
                      onGenerateMaster={handleGenerateSceneMaster}
                      onGenerateReverse={handleGenerateSceneReverse}
                      onGeneratePano={handleGenerateScenePano}
                      onDeleteSceneImage={handleDeleteSceneImage}
                      onManualUrl={triggerManualUrlInput}
                      onOpenPanoViewer={openPanoViewerModal}
                      onOpenEditScene={openEditSceneModal}
                      uploadingSourceRef={uploadingSourceRef}
                      inferringSourcePrompts={inferringSourcePrompts}
                      onUploadSourceRefs={handleUploadSourceRefs}
                      onRemoveSourceRef={handleRemoveSourceRef}
                      onInferSourcePrompts={handleInferSourcePrompts}
                    />
                  ) : selectedAsset.kind === "prop" ? (
                    <PropWorkspace
                      asset={selectedAsset}
                      onFieldChange={patchSelectedField}
                      onExtraChange={patchSelectedExtra}
                      generatingProp={generatingProp}
                      generatingPropTurnaround={generatingPropTurnaround}
                      generatingPropDetail={generatingPropDetail}
                      onGenerateReference={handleGeneratePropReference}
                      onGenerateTurnaround={handleGeneratePropTurnaround}
                      onGenerateDetail={handleGeneratePropDetail}
                      onDeletePropImage={handleDeletePropImage}
                      onManualUrl={triggerManualUrlInput}
                      onOpenEditProp={openEditPropModal}
                      uploadingSourceRef={uploadingSourceRef}
                      inferringSourcePrompts={inferringSourcePrompts}
                      onUploadSourceRefs={handleUploadSourceRefs}
                      onRemoveSourceRef={handleRemoveSourceRef}
                      onInferSourcePrompts={handleInferSourcePrompts}
                    />
                  ) : null}
                </div>
              )}
            </div>
          </div>
        )}
      </Spin>

      {onContinue && <footer className="production-assets-next"><Button icon={<ArrowLeft size={14}/>} onClick={onBack} disabled={continuing}>上一步</Button><span>资产设定会用于后续分镜，可随时回来调整</span><Button type="primary" icon={<ArrowRight size={14}/>} iconPlacement="end" loading={continuing} disabled={loading} onClick={() => void continueProduction()}>进入分镜</Button></footer>}
      </>}
      {flowModalContext}

      {/* 360 全景查看器弹窗 (PanoViewerModal) */}
      <Modal
        open={panoViewerVisible}
        title="360° 全景空间查看器 (Panorama Viewer)"
        footer={null}
        width={960}
        destroyOnHidden
        onCancel={() => setPanoViewerVisible(false)}
        className="d2-assets-library"
      >
        <div className="pano-viewer-body">
          <div className="pano-image-container">
            <img src={currentPanoUrl} className="pano-panoramic-img" alt="360 Panorama" />
          </div>
          <div className="pano-viewer-tips">
            <Compass size={15} className="text-blue" />
            <span>支持 360° 全景等距柱状图漫游展示，在 3D 虚拟影棚与自由运镜模式中作为沉浸式天空盒背景。</span>
            <button
              type="button"
              className="download-link"
              onClick={() => openMediaPreview({ src: currentPanoUrl, title: "360° 全景原图" })}
            >
              预览原图
            </button>
          </div>
        </div>
      </Modal>

      {/* 手动输入图片 URL 弹窗 */}
      <Modal
        open={manualUrlModalVisible}
        title={`手动指定 ${manualUrlTarget} 图片地址`}
        okText="确认指定"
        cancelText="取消"
        width={500}
        onOk={handleConfirmManualUrl}
        onCancel={() => setManualUrlModalVisible(false)}
        className="d2-assets-library"
      >
        <Form layout="vertical">
          <Form.Item label="图片 URL 直链">
            <Input value={manualUrlInput} onChange={(event) => setManualUrlInput(event.target.value)} placeholder="https://..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新增身份/造型弹窗 (参考 source2 CreateIdentityModal) */}
      <IdentityModal
        open={identityModalVisible}
        asset={selectedAsset}
        saving={savingIdentity}
        onCancel={() => setIdentityModalVisible(false)}
        onConfirm={handleConfirmAddIdentity}
      />

      {/* 新建资产弹窗 */}
      <AssetCanvasCreateModal open={modalVisible} kind={currentTab} busy={submitting} onCancel={() => { canvasCreateOrigin.current = null; setModalVisible(false) }} onSubmit={(name, description) => void handleCreateSubmit({ kind: currentTab, name, description, role: "", visual_prompt: description, image_url: "" })}/>
      {/* Retained for compatibility during the canvas migration; no public route opens the legacy form. */}
      {false && <CreateAssetModal
        open={modalVisible}
        kindInitial={currentTab}
        submitting={submitting}
        csrfToken={csrfToken}
        projectId={projectId}
        onClose={() => setModalVisible(false)}
        onSubmit={handleCreateSubmit}
      />}

      <AssetCanvasVoiceModal open={canvasVoiceOpen} asset={selectedAsset} onClose={() => setCanvasVoiceOpen(false)} uploading={uploadingVoice} previewing={previewingVoice} applying={applyingVoicePreset} onUpload={handleUploadVoice} onPreset={handleApplyVoicePreset} onPreview={handlePreviewVoice} onExtract={handleOpenVoiceExtract} onExtraChange={patchSelectedExtra}/>

      {/* 编辑场景弹窗 (严格对齐 source2 SceneDialog) */}
      <EditSceneModal
        open={editSceneModalVisible}
        asset={selectedAsset}
        saving={savingSceneModal}
        onCancel={() => setEditSceneModalVisible(false)}
        onConfirm={handleSaveSceneModal}
      />

      {/* 编辑道具弹窗 (严格对齐 source2 PropDialog) */}
      <EditPropModal
        open={editPropModalVisible}
        asset={selectedAsset}
        saving={savingPropModal}
        onCancel={() => setEditPropModalVisible(false)}
        onConfirm={handleSavePropModal}
      />

      <VoiceExtractModal
        open={voiceExtractOpen}
        sources={extractSources}
        loadingSources={loadingExtractSources}
        submitting={extractingVoice}
        onCancel={() => setVoiceExtractOpen(false)}
        onSubmit={handleExtractVoiceFromShot}
      />
    </div>
  )
})

export default AssetsLibraryPane
