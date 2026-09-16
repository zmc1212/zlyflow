// 资产库面板 —— 逐行复刻自 dev0914 z-admin/src/views/project/AssetsLibraryPane.vue
// Vue → React 对应：ref→useState、computed→useMemo、watch(deep)→useEffect、onMounted/onBeforeUnmount→useEffect 清理；
// selectedAsset 的深响应直接改写在 React 中统一收敛为 applySelected/mutateSelected（同步维护 ref 供定时器与卸载前保存读取），
// 自动保存队列（700ms 防抖 + 串行队列 + beforeunload keepalive）行为与原版一致。
// 角色/场景/道具工作区与各弹窗已按原版内部分区下沉到 ./assets/ 子组件。
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react"
import { Button, Form, Input, Modal, Popconfirm, Space, Spin, Tag, message } from "antd"
import {
  Boxes,
  Compass,
  Edit3,
  Eye,
  Layers,
  MapPin,
  Package,
  Plus,
  RefreshCw,
  Save,
  Search,
  Shirt,
  Sparkles,
  Trash2,
  Users,
} from "lucide-react"
import {
  listAssets,
  createAsset,
  updateAsset,
  deleteAsset,
  generateAssetImage,
  uploadAssetSourceReference,
  deleteAssetSourceReference,
  inferAssetPromptsFromReferences,
  director2ErrorDetail,
  type Director2Asset,
} from "../api"
import CharacterWorkspace from "./assets/CharacterWorkspace"
import SceneWorkspace from "./assets/SceneWorkspace"
import PropWorkspace from "./assets/PropWorkspace"
import CreateAssetModal from "./assets/CreateAssetModal"
import EditSceneModal from "./assets/EditSceneModal"
import EditPropModal from "./assets/EditPropModal"
import IdentityModal from "./assets/IdentityModal"
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
  type AssetIdentity,
  type GenerateImageResult,
} from "./assets/shared"
import type { CreateFormState } from "./assets/CreateAssetModal"
import type { SceneDraft } from "./assets/EditSceneModal"
import type { PropDraft } from "./assets/EditPropModal"
import type { IdentityFormState } from "./assets/IdentityModal"
import { MAX_SOURCE_REFERENCE_BYTES, remainingSourceReferenceSlots, sourceReferencesOf } from "../asset-source-references"
import { useMediaPreview } from "../media-preview"
import "./assets-library.css"

interface AssetsLibraryPaneProps {
  csrfToken: string
  projectId: string
}

export type AssetsLibraryPaneHandle = {
  fetchAssets: () => Promise<void> | void
}

type AutoSaveState = "idle" | "pending" | "saving" | "saved" | "error"

type BatchGenerateOptions = {
  kind: string
  setLoading: (v: boolean) => void
  messageKey: string
  label: string
  targetType: string
  aspectRatio: string
  hasOutput: (a: Director2Asset) => boolean
  hasReference?: (a: Director2Asset) => boolean
  referenceHint?: string
  buildPayload?: (a: Director2Asset) => Record<string, unknown>
}

const AUTO_SAVE_STATUS_TEXT: Record<AutoSaveState, string> = {
  idle: "修改后自动保存",
  pending: "有修改，准备保存",
  saving: "正在自动保存",
  saved: "已自动保存",
  error: "自动保存失败",
}

const AssetsLibraryPane = forwardRef<AssetsLibraryPaneHandle, AssetsLibraryPaneProps>(function AssetsLibraryPane(
  { csrfToken, projectId },
  ref,
) {
  const { openMediaPreview } = useMediaPreview()
  const [assets, setAssets] = useState<Director2Asset[]>([])
  const [selectedAsset, setSelectedAsset] = useState<Director2Asset | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [autoSaveState, setAutoSaveState] = useState<AutoSaveState>("idle")

  // 与 Vue 实例级可变量（let autoSaveTimer / autoSaveQueuedSnapshot / autoSaveRunner / suppressAutoSave）对应的 ref
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const autoSaveQueuedSnapshotRef = useRef<Director2Asset | null>(null)
  const autoSaveRunnerRef = useRef<Promise<void> | null>(null)
  const suppressAutoSaveRef = useRef(false)

  // 各生成动作的独立 Loading 状态
  const [generatingAvatar, setGeneratingAvatar] = useState(false)
  const [generatingIdentityId, setGeneratingIdentityId] = useState<string | null>(null)
  const [batchGeneratingAvatars, setBatchGeneratingAvatars] = useState(false)
  const [batchGeneratingLooks, setBatchGeneratingLooks] = useState(false)
  const [batchGeneratingSceneMasters, setBatchGeneratingSceneMasters] = useState(false)
  const [batchGeneratingSceneReverses, setBatchGeneratingSceneReverses] = useState(false)
  const [batchGeneratingScenePanos, setBatchGeneratingScenePanos] = useState(false)
  const [batchGeneratingPropReferences, setBatchGeneratingPropReferences] = useState(false)
  const [batchGeneratingPropTurnarounds, setBatchGeneratingPropTurnarounds] = useState(false)
  const [batchGeneratingPropDetails, setBatchGeneratingPropDetails] = useState(false)
  const [generatingMaster, setGeneratingMaster] = useState(false)
  const [generatingReverse, setGeneratingReverse] = useState(false)
  const [uploadingSourceRef, setUploadingSourceRef] = useState(false)
  const [inferringSourcePrompts, setInferringSourcePrompts] = useState(false)
  const [generatingPano, setGeneratingPano] = useState(false)
  const [generatingProp, setGeneratingProp] = useState(false)
  const [generatingPropTurnaround, setGeneratingPropTurnaround] = useState(false)
  const [generatingPropDetail, setGeneratingPropDetail] = useState(false)

  const batchGenerationActive = useMemo(
    () => [
      batchGeneratingAvatars,
      batchGeneratingLooks,
      batchGeneratingSceneMasters,
      batchGeneratingSceneReverses,
      batchGeneratingScenePanos,
      batchGeneratingPropReferences,
      batchGeneratingPropTurnarounds,
      batchGeneratingPropDetails,
    ].some((state) => state),
    [
      batchGeneratingAvatars,
      batchGeneratingLooks,
      batchGeneratingSceneMasters,
      batchGeneratingSceneReverses,
      batchGeneratingScenePanos,
      batchGeneratingPropReferences,
      batchGeneratingPropTurnarounds,
      batchGeneratingPropDetails,
    ],
  )

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

  function cloneAssetSnapshot(asset: Director2Asset | null): Director2Asset | null {
    return asset ? JSON.parse(JSON.stringify(asset)) as Director2Asset : null
  }

  async function runAutoSaveQueue() {
    while (autoSaveQueuedSnapshotRef.current) {
      const snapshot = autoSaveQueuedSnapshotRef.current
      autoSaveQueuedSnapshotRef.current = null
      if (!snapshot.name?.trim()) {
        updateAutoSaveState("error")
        message.warning("名称不能为空，当前修改未保存")
        continue
      }
      setSaving(true)
      updateAutoSaveState("saving")
      try {
        const updated = await updateAsset(csrfToken, projectId, snapshot.id, snapshot)
        replaceAssetInList(snapshot.id, updated)
        updateAutoSaveState(autoSaveQueuedSnapshotRef.current || autoSaveTimerRef.current ? "pending" : "saved")
      } catch (err) {
        updateAutoSaveState("error")
        message.error(director2ErrorDetail(err, "自动保存失败，请检查网络后继续修改"))
      } finally {
        setSaving(false)
      }
    }
  }

  function enqueueAutoSave(snapshot: Director2Asset | null) {
    if (!snapshot?.id) return Promise.resolve()
    autoSaveQueuedSnapshotRef.current = snapshot
    if (!autoSaveRunnerRef.current) {
      autoSaveRunnerRef.current = runAutoSaveQueue().finally(() => {
        autoSaveRunnerRef.current = null
        if (autoSaveQueuedSnapshotRef.current) enqueueAutoSave(autoSaveQueuedSnapshotRef.current)
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

  function selectAsset(ast: Director2Asset) {
    flushAutoSave()
    const copy = JSON.parse(JSON.stringify(ast)) as Director2Asset
    if (!copy.extra) copy.extra = {}

    if (copy.kind === "character") {
      if (!copy.extra.identities) copy.extra.identities = []
      if (!copy.extra.avatar_prompt) {
        copy.extra.avatar_prompt = `${copy.name}，面部肖像，五官特写，眼神清亮坚毅，写实电影级光影，8k`
      }
    } else if (copy.kind === "scene") {
      if (!copy.extra.environment_prompt) {
        copy.extra.environment_prompt = copy.visual_prompt || `${copy.name}，电影级实景空间，宋式古典建筑美学，自然光影，8k`
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
          selectAsset(list[0])
        }
      } else {
        applySelected(null)
      }
    }, 50)
  }

  // 1. 生成角色头像 (1:1)
  async function handleGenerateAvatar() {
    const sel = selectedAssetRef.current
    if (!sel) return
    const extra = sel.extra || {}
    const prompt = (extra.avatar_prompt || sel.name).trim()
    setGeneratingAvatar(true)
    try {
      const res = (await generateAssetImage(csrfToken, projectId, sel.id, {
        target_type: "avatar",
        prompt,
        model: "gpt-image-2",
        aspect_ratio: "1:1",
        ...characterStylePayload(sel),
      })) as GenerateImageResult
      const cur = selectedAssetRef.current
      if (!cur) return
      const refCount = Number(res.source_reference_count || sourceReferencesOf(cur).length)
      message.success(refCount > 0 ? `「${cur.name}」头像已按 ${refCount} 张原片参考图生成` : `「${cur.name}」头像生成成功！`)
      if (res.asset) {
        applyGeneratedAsset(cur.id, res)
      } else if (res.image_url) {
        const imageUrl = res.image_url
        mutateSelected((prev) => ({
          ...prev,
          extra: { ...(prev.extra || {}), avatar_url: imageUrl },
          image_url: imageUrl,
        }))
      }
    } catch (err) {
      message.error(director2ErrorDetail(err, "头像生图失败"))
    } finally {
      setGeneratingAvatar(false)
    }
  }

  function applyGeneratedAsset(assetId: string, res: GenerateImageResult) {
    if (!res?.asset) return
    replaceAssetInList(assetId, res.asset)
    if (selectedAssetRef.current?.id === assetId) {
      suppressAutoSaveRef.current = true
      applySelected({ ...res.asset })
    }
  }

  function applyServerAsset(asset: Director2Asset) {
    replaceAssetInList(asset.id, asset)
    if (autoSaveQueuedSnapshotRef.current?.id === asset.id) {
      autoSaveQueuedSnapshotRef.current = cloneAssetSnapshot(asset)
    }
    if (selectedAssetRef.current?.id === asset.id) {
      suppressAutoSaveRef.current = true
      applySelected({ ...asset })
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

  function hasCharacterAvatar(ast: Director2Asset | null | undefined) {
    return Boolean(ast?.extra?.avatar_url || ast?.image_url)
  }

  async function handleBatchGenerateAvatars() {
    const chars = assetsRef.current.filter((a) => a.kind === "character")
    const targets = chars.filter((a) => !hasCharacterAvatar(a))
    if (!targets.length) {
      message.info(chars.length ? "所有角色已有头像，无需再生成" : "暂无角色可生成头像")
      return
    }
    setBatchGeneratingAvatars(true)
    let ok = 0
    const failed: string[] = []
    message.loading({ content: `开始一键生成 ${targets.length} 个头像…`, key: "batchAvatars" })
    try {
      for (let i = 0; i < targets.length; i += 1) {
        const ast = targets[i]
        message.loading({
          content: `正在生成头像 (${i + 1}/${targets.length})：${ast.name}`,
          key: "batchAvatars",
        })
        try {
          const extra = ast.extra || {}
          const res = (await generateAssetImage(csrfToken, projectId, ast.id, {
            target_type: "avatar",
            prompt: (extra.avatar_prompt || ast.name || "").trim(),
            model: "gpt-image-2",
            aspect_ratio: "1:1",
            ...characterStylePayload(ast),
          })) as GenerateImageResult
          applyGeneratedAsset(ast.id, res)
          ok += 1
        } catch (err) {
          failed.push(`${ast.name}: ${director2ErrorDetail(err, "失败")}`)
        }
      }
      if (failed.length) {
        message.warning({
          content: `头像完成 ${ok}/${targets.length}，失败：${failed.slice(0, 3).join("；")}`,
          key: "batchAvatars",
          duration: 6,
        })
      } else {
        message.success({ content: `已一键生成 ${ok} 个头像`, key: "batchAvatars" })
      }
    } finally {
      setBatchGeneratingAvatars(false)
    }
  }

  async function handleBatchGenerateLooks() {
    const chars = assetsRef.current.filter((a) => a.kind === "character")
    const jobs: Array<{ ast: Director2Asset; ident: AssetIdentity; costume: string }> = []
    let skippedNoAvatar = 0
    let skippedNoCostume = 0
    for (const ast of chars) {
      if (!hasCharacterAvatar(ast) && !sourceReferencesOf(ast).length) {
        skippedNoAvatar += 1
        continue
      }
      for (const ident of (ast.extra?.identities as AssetIdentity[]) || []) {
        const costume = (ident.description || ident.appearance_details || "").trim()
        if (!costume) {
          skippedNoCostume += 1
          continue
        }
        if (ident.image_url) continue
        jobs.push({ ast, ident, costume })
      }
    }
    if (!jobs.length) {
      if (skippedNoAvatar && !chars.some((a) => hasCharacterAvatar(a) || sourceReferencesOf(a).length)) {
        message.info("请先生成头像或上传原片参考图，造型图需要身份锚点")
      } else {
        message.info("所有已有头像或参考图的角色造型图已就绪（或缺少外观描述）")
      }
      return
    }
    setBatchGeneratingLooks(true)
    let ok = 0
    const failed: string[] = []
    message.loading({ content: `开始一键生成 ${jobs.length} 张造型图…`, key: "batchLooks" })
    try {
      for (let i = 0; i < jobs.length; i += 1) {
        const { ast, ident, costume } = jobs[i]
        message.loading({
          content: `正在生成造型图 (${i + 1}/${jobs.length})：${ast.name} · ${ident.name}`,
          key: "batchLooks",
        })
        try {
          const res = (await generateAssetImage(csrfToken, projectId, ast.id, {
            target_type: "identity",
            identity_id: ident.id,
            prompt: costume,
            model: "gpt-image-2",
            aspect_ratio: "16:9",
            ...characterStylePayload(ast),
          })) as GenerateImageResult
          applyGeneratedAsset(ast.id, res)
          ok += 1
        } catch (err) {
          failed.push(`${ast.name}/${ident.name}: ${director2ErrorDetail(err, "失败")}`)
        }
      }
      const skipHint = [
        skippedNoAvatar ? `${skippedNoAvatar} 个角色尚无头像已跳过` : "",
        skippedNoCostume ? `${skippedNoCostume} 个造型缺外观描述已跳过` : "",
      ].filter(Boolean).join("，")
      const skipSuffix = skipHint ? `，${skipHint}` : ""
      if (failed.length) {
        message.warning({
          content: `造型图完成 ${ok}/${jobs.length}${skipSuffix}，失败：${failed.slice(0, 3).join("；")}`,
          key: "batchLooks",
          duration: 6,
        })
      } else {
        message.success({ content: `已一键生成 ${ok} 张造型图${skipSuffix}`, key: "batchLooks" })
      }
    } finally {
      setBatchGeneratingLooks(false)
    }
  }

  async function runBatchAssetGeneration({
    kind,
    setLoading: setLoadingState,
    messageKey,
    label,
    targetType,
    aspectRatio,
    hasOutput,
    hasReference = () => true,
    referenceHint = "",
    buildPayload = () => ({}),
  }: BatchGenerateOptions) {
    const kindAssets = assetsRef.current.filter((a) => a.kind === kind)
    const pending = kindAssets.filter((a) => !hasOutput(a))
    const targets = pending.filter(hasReference)
    const skipped = pending.length - targets.length

    if (!targets.length) {
      if (!kindAssets.length) {
        message.info(`暂无${kindLabel(kind)}可生成${label}`)
      } else if (skipped) {
        message.info(referenceHint)
      } else {
        message.info(`所有${kindLabel(kind)}${label}已就绪，无需再生成`)
      }
      return
    }

    setLoadingState(true)
    let ok = 0
    const failed: string[] = []
    message.loading({ content: `开始一键生成 ${targets.length} 张${label}…`, key: messageKey })
    try {
      for (let i = 0; i < targets.length; i += 1) {
        const ast = targets[i]
        message.loading({
          content: `正在生成${label} (${i + 1}/${targets.length})：${ast.name}`,
          key: messageKey,
        })
        try {
          const res = (await generateAssetImage(csrfToken, projectId, ast.id, {
            target_type: targetType,
            model: "gpt-image-2",
            aspect_ratio: aspectRatio,
            ...buildPayload(ast),
          })) as GenerateImageResult
          applyGeneratedAsset(ast.id, res)
          ok += 1
        } catch (err) {
          failed.push(`${ast.name}: ${director2ErrorDetail(err, "失败")}`)
        }
      }

      const skipSuffix = skipped ? `，${skipped} 个缺少前置图片已跳过` : ""
      if (failed.length) {
        message.warning({
          content: `${label}完成 ${ok}/${targets.length}${skipSuffix}，失败：${failed.slice(0, 3).join("；")}`,
          key: messageKey,
          duration: 6,
        })
      } else {
        message.success({ content: `已一键生成 ${ok} 张${label}${skipSuffix}`, key: messageKey })
      }
    } finally {
      setLoadingState(false)
    }
  }

  function sceneStylePayload(ast: Director2Asset | null) {
    const extra = ast?.extra || {}
    return {
      visual_style: extra.visual_style || "",
      art_style_id: extra.art_style_id || "",
    }
  }

  function hasSceneMaster(ast: Director2Asset | null | undefined) {
    return Boolean(ast?.extra?.master_url || ast?.image_url)
  }

  function handleBatchGenerateSceneMasters() {
    return runBatchAssetGeneration({
      kind: "scene",
      setLoading: setBatchGeneratingSceneMasters,
      messageKey: "batchSceneMasters",
      label: "正面图",
      targetType: "scene_master",
      aspectRatio: "16:9",
      hasOutput: hasSceneMaster,
      buildPayload: (ast) => ({
        prompt: (ast.extra?.environment_prompt || ast.visual_prompt || ast.name || "").trim(),
        ...sceneStylePayload(ast),
      }),
    })
  }

  function handleBatchGenerateSceneReverses() {
    return runBatchAssetGeneration({
      kind: "scene",
      setLoading: setBatchGeneratingSceneReverses,
      messageKey: "batchSceneReverses",
      label: "背面图",
      targetType: "scene_reverse",
      aspectRatio: "16:9",
      hasOutput: (ast) => Boolean(ast.extra?.reverse_url),
      hasReference: hasSceneMaster,
      referenceHint: "请先生成场景正面图，背面图需要将正面图作为参考",
      buildPayload: sceneStylePayload,
    })
  }

  function handleBatchGenerateScenePanos() {
    return runBatchAssetGeneration({
      kind: "scene",
      setLoading: setBatchGeneratingScenePanos,
      messageKey: "batchScenePanos",
      label: "360图",
      targetType: "scene_pano",
      aspectRatio: "2:1",
      hasOutput: (ast) => Boolean(ast.extra?.pano_url),
      hasReference: hasSceneMaster,
      referenceHint: "请先生成场景正面图，360 图需要将正面图作为参考",
      buildPayload: sceneStylePayload,
    })
  }

  function propStylePayload(ast: Director2Asset | null) {
    const extra = ast?.extra || {}
    return {
      visual_style: extra.visual_style || "",
      art_style_id: extra.art_style_id || "",
    }
  }

  function hasPropReference(ast: Director2Asset | null | undefined) {
    return Boolean(ast?.extra?.reference_url || ast?.image_url)
  }

  function handleBatchGeneratePropReferences() {
    return runBatchAssetGeneration({
      kind: "prop",
      setLoading: setBatchGeneratingPropReferences,
      messageKey: "batchPropReferences",
      label: "参考图",
      targetType: "prop_reference",
      aspectRatio: "16:9",
      hasOutput: hasPropReference,
      buildPayload: propStylePayload,
    })
  }

  function handleBatchGeneratePropTurnarounds() {
    return runBatchAssetGeneration({
      kind: "prop",
      setLoading: setBatchGeneratingPropTurnarounds,
      messageKey: "batchPropTurnarounds",
      label: "三视图",
      targetType: "prop_turnaround",
      aspectRatio: "16:9",
      hasOutput: (ast) => Boolean(ast.extra?.turnaround_url),
      hasReference: hasPropReference,
      referenceHint: "请先生成道具参考图，三视图需要将参考图作为参考",
      buildPayload: propStylePayload,
    })
  }

  function handleBatchGeneratePropDetails() {
    return runBatchAssetGeneration({
      kind: "prop",
      setLoading: setBatchGeneratingPropDetails,
      messageKey: "batchPropDetails",
      label: "细节图",
      targetType: "prop_detail",
      aspectRatio: "16:9",
      hasOutput: (ast) => Boolean(ast.extra?.detail_url),
      hasReference: hasPropReference,
      referenceHint: "请先生成道具参考图，细节图需要将参考图作为参考",
      buildPayload: propStylePayload,
    })
  }

  // 2. 生成角色造型 (对齐 source1 look：16:9 四宫格)
  async function handleGenerateIdentityImage(ident: AssetIdentity) {
    const sel = selectedAssetRef.current
    if (!sel || !ident) return
    const extra = sel.extra || {}
    const costume = (ident.description || ident.appearance_details || "").trim()
    const hasSourceRefs = sourceReferencesOf(sel).length > 0
    if (!costume && !hasSourceRefs) {
      message.warning("请先填写外观描述，或上传原片截图作为服装参考")
      return
    }
    if (!(extra.avatar_url || sel.image_url || sourceReferencesOf(sel).length)) {
      message.warning("请先生成头像，或上传原片截图作为身份参考")
      return
    }
    setGeneratingIdentityId(ident.id || null)
    try {
      const res = (await generateAssetImage(csrfToken, projectId, sel.id, {
        target_type: "identity",
        identity_id: ident.id,
        prompt: costume,
        model: "gpt-image-2",
        aspect_ratio: "16:9",
        ...characterStylePayload(sel),
      })) as GenerateImageResult
      const cur = selectedAssetRef.current
      if (!cur) return
      const refCount = Number(res.source_reference_count || sourceReferencesOf(cur).length)
      message.success(
        refCount > 0
          ? `造型「${ident.name}」已按 ${refCount} 张原片截图的服装生成`
          : `造型「${ident.name}」造型图生成成功！`,
      )
      if (res.image_url) {
        // 与 Vue 直接改写 ident 对象一致：若选中资产已被整体替换则该改写自然失效
        mutateSelected((prev) => ({
          ...prev,
          extra: {
            ...(prev.extra || {}),
            identities: ((prev.extra?.identities as AssetIdentity[]) || []).map((it) =>
              it === ident ? { ...it, image_url: res.image_url } : it,
            ),
          },
        }))
        const idx = assetsRef.current.findIndex((a) => a.id === cur.id)
        if (idx !== -1 && res.asset) {
          replaceAssetInList(cur.id, res.asset)
        }
      }
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
      const cur = selectedAssetRef.current
      if (!cur) return
      message.success(`场景「${cur.name}」Master 主视角生成成功！`)
      if (res.image_url) {
        const imageUrl = res.image_url
        mutateSelected((prev) => ({
          ...prev,
          extra: { ...(prev.extra || {}), master_url: imageUrl },
          image_url: imageUrl,
        }))
        const idx = assetsRef.current.findIndex((a) => a.id === cur.id)
        if (idx !== -1 && res.asset) {
          replaceAssetInList(cur.id, res.asset)
        }
      }
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
        model: "gpt-image-2",
        aspect_ratio: "16:9",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      const cur = selectedAssetRef.current
      if (!cur) return
      message.success(`场景「${cur.name}」Reverse 背面反打视角生成成功！`)
      if (res.image_url) {
        mutateSelected((prev) => ({
          ...prev,
          extra: { ...(prev.extra || {}), reverse_url: res.image_url },
        }))
        const idx = assetsRef.current.findIndex((a) => a.id === cur.id)
        if (idx !== -1 && res.asset) {
          replaceAssetInList(cur.id, res.asset)
        }
      }
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
        model: "gpt-image-2",
        aspect_ratio: "2:1",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      const cur = selectedAssetRef.current
      if (!cur) return
      message.success(`场景「${cur.name}」360° 全景图生成成功！`)
      if (res.image_url) {
        mutateSelected((prev) => ({
          ...prev,
          extra: { ...(prev.extra || {}), pano_url: res.image_url },
        }))
        const idx = assetsRef.current.findIndex((a) => a.id === cur.id)
        if (idx !== -1 && res.asset) {
          replaceAssetInList(cur.id, res.asset)
        }
      }
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
        model: "gpt-image-2",
        aspect_ratio: "16:9",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      const cur = selectedAssetRef.current
      if (!cur) return
      message.success(`道具「${cur.name}」参考图生成成功！`)
      if (res.image_url) {
        const imageUrl = res.image_url
        mutateSelected((prev) => ({
          ...prev,
          extra: { ...(prev.extra || {}), reference_url: imageUrl },
          image_url: imageUrl,
        }))
        const idx = assetsRef.current.findIndex((a) => a.id === cur.id)
        if (idx !== -1 && res.asset) {
          replaceAssetInList(cur.id, res.asset)
        }
      }
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
        model: "gpt-image-2",
        aspect_ratio: "16:9",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      const cur = selectedAssetRef.current
      if (!cur) return
      message.success(`道具「${cur.name}」三视图生成成功！`)
      if (res.image_url) {
        mutateSelected((prev) => ({
          ...prev,
          extra: { ...(prev.extra || {}), turnaround_url: res.image_url },
        }))
        const idx = assetsRef.current.findIndex((a) => a.id === cur.id)
        if (idx !== -1 && res.asset) {
          replaceAssetInList(cur.id, res.asset)
        }
      }
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
        model: "gpt-image-2",
        aspect_ratio: "16:9",
        visual_style: extra.visual_style || "",
        art_style_id: extra.art_style_id || "",
      })) as GenerateImageResult
      const cur = selectedAssetRef.current
      if (!cur) return
      message.success(`道具「${cur.name}」细节特写生成成功！`)
      if (res.image_url) {
        mutateSelected((prev) => ({
          ...prev,
          extra: { ...(prev.extra || {}), detail_url: res.image_url },
        }))
        const idx = assetsRef.current.findIndex((a) => a.id === cur.id)
        if (idx !== -1 && res.asset) {
          replaceAssetInList(cur.id, res.asset)
        }
      }
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
      const created = await createAsset(csrfToken, projectId, { ...form })
      message.success(`「${created.name}」创建成功`)
      setModalVisible(false)
      setTab(created.kind)
      await fetchAssets()
      if (created && created.id) {
        const found = assetsRef.current.find((a) => a.id === created.id)
        if (found) selectAsset(found)
      }
    } catch (err) {
      message.error(director2ErrorDetail(err, "创建失败"))
    } finally {
      setSubmitting(false)
    }
  }

  useImperativeHandle(ref, () => ({ fetchAssets }))

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
    <div className="assets-library-pane d2-assets-library">
      {/* 顶部操作栏 */}
      <div className="sub-pane-header">
        <div className="header-copy">
          <h2 className="sub-pane-title">资产库</h2>
          <p className="sub-pane-subtitle">
            严格参考 source2 影视工业流水线：管理角色肖像与身份造型、场景三大机位（Master主视角 / Reverse反打背面 / Pano 360全景）及道具特写参考。
          </p>
        </div>

        <div className="header-actions">
          <div className="stats-pills">
            <span className={`stat-pill${currentTab === "character" ? " active" : ""}`} onClick={() => handleTabChange("character")}>
              <Users size={13} /> 角色 {getCountByKind("character")}
            </span>
            <span className={`stat-pill${currentTab === "scene" ? " active" : ""}`} onClick={() => handleTabChange("scene")}>
              <MapPin size={13} /> 场景 {getCountByKind("scene")}
            </span>
            <span className={`stat-pill${currentTab === "prop" ? " active" : ""}`} onClick={() => handleTabChange("prop")}>
              <Package size={13} /> 道具 {getCountByKind("prop")}
            </span>
          </div>
          <Button type="primary" className="primary-btn" icon={<Plus size={16} />} onClick={openCreateModal}>
            新增{kindLabel(currentTab)}
          </Button>
        </div>
      </div>
      {currentTab === "character" ? (
        <div className="batch-generate-bar">
          <Button
            type="primary"
            loading={batchGeneratingAvatars}
            disabled={batchGenerationActive && !batchGeneratingAvatars}
            icon={<Sparkles size={15} />}
            onClick={handleBatchGenerateAvatars}
          >
            一键生成所有头像
          </Button>
          <Button
            type="primary"
            loading={batchGeneratingLooks}
            disabled={batchGenerationActive && !batchGeneratingLooks}
            icon={<Shirt size={15} />}
            onClick={handleBatchGenerateLooks}
          >
            一键生成所有造型图
          </Button>
          <span className="batch-generate-hint">仅处理尚未出图的角色头像 / 已有头像的造型图，任务中心可查看进度</span>
        </div>
      ) : currentTab === "scene" ? (
        <div className="batch-generate-bar">
          <Button
            type="primary"
            loading={batchGeneratingSceneMasters}
            disabled={batchGenerationActive && !batchGeneratingSceneMasters}
            icon={<Sparkles size={15} />}
            onClick={handleBatchGenerateSceneMasters}
          >
            一键生成所有正面
          </Button>
          <Button
            type="primary"
            loading={batchGeneratingSceneReverses}
            disabled={batchGenerationActive && !batchGeneratingSceneReverses}
            icon={<RefreshCw size={15} />}
            onClick={handleBatchGenerateSceneReverses}
          >
            一键生成所有背面
          </Button>
          <Button
            type="primary"
            loading={batchGeneratingScenePanos}
            disabled={batchGenerationActive && !batchGeneratingScenePanos}
            icon={<Compass size={15} />}
            onClick={handleBatchGenerateScenePanos}
          >
            一键生成所有360图
          </Button>
          <span className="batch-generate-hint">仅处理尚未出图的场景；背面和 360 图需已有正面图</span>
        </div>
      ) : currentTab === "prop" ? (
        <div className="batch-generate-bar">
          <Button
            type="primary"
            loading={batchGeneratingPropReferences}
            disabled={batchGenerationActive && !batchGeneratingPropReferences}
            icon={<Sparkles size={15} />}
            onClick={handleBatchGeneratePropReferences}
          >
            一键生成所有参考图
          </Button>
          <Button
            type="primary"
            loading={batchGeneratingPropTurnarounds}
            disabled={batchGenerationActive && !batchGeneratingPropTurnarounds}
            icon={<Layers size={15} />}
            onClick={handleBatchGeneratePropTurnarounds}
          >
            一键生成所有三视图
          </Button>
          <Button
            type="primary"
            loading={batchGeneratingPropDetails}
            disabled={batchGenerationActive && !batchGeneratingPropDetails}
            icon={<Eye size={15} />}
            onClick={handleBatchGeneratePropDetails}
          >
            一键生成所有细节图
          </Button>
          <span className="batch-generate-hint">仅处理尚未出图的道具；三视图和细节图需已有参考图</span>
        </div>
      ) : null}

      <Spin spinning={loading}>
        {assets.length === 0 ? (
          <div className="empty-asset-box">
            <Boxes size={48} className="empty-icon" />
            <h3>资产库暂无资产</h3>
            <p>可前往「内容库」一键导入剧本并抽取资产，或点击右上角手动新增。</p>
            <Button type="primary" onClick={openCreateModal}>立即新增第一个资产</Button>
          </div>
        ) : (
          /* 左右结构：左边选择名称，右边显示详细与生成 (参考 source2) */
          <div className="assets-split-container">
            {/* 左侧：分类、搜索与资产名称列表 */}
            <div className="assets-sidebar-list">
              {/* 分类 Tabs (去掉全部，默认角色) */}
              <div className="sidebar-tabs">
                {ASSET_TABS.map((tab) => {
                  const KindIcon = getKindIcon(tab.key)
                  return (
                    <div
                      key={tab.key}
                      className={`sidebar-tab-item${currentTab === tab.key ? " active" : ""}`}
                      onClick={() => handleTabChange(tab.key)}
                    >
                      <KindIcon size={13} />
                      <span>{tab.label}</span>
                      <span className="tab-count-badge">{getCountByKind(tab.key)}</span>
                    </div>
                  )
                })}
              </div>

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
                  <div
                    key={ast.id}
                    className={`asset-list-item${selectedAsset && selectedAsset.id === ast.id ? " active" : ""}`}
                    onClick={() => selectAsset(ast)}
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
                  </div>
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
                      generatingAvatar={generatingAvatar}
                      generatingIdentityId={generatingIdentityId}
                      onGenerateAvatar={handleGenerateAvatar}
                      onGenerateIdentity={handleGenerateIdentityImage}
                      onRemoveIdentity={handleRemoveIdentity}
                      onOpenAddIdentity={openAddIdentityModal}
                      uploadingSourceRef={uploadingSourceRef}
                      inferringSourcePrompts={inferringSourcePrompts}
                      onUploadSourceRefs={handleUploadSourceRefs}
                      onRemoveSourceRef={handleRemoveSourceRef}
                      onInferSourcePrompts={handleInferSourcePrompts}
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
      <CreateAssetModal
        open={modalVisible}
        kindInitial={currentTab}
        submitting={submitting}
        csrfToken={csrfToken}
        projectId={projectId}
        onClose={() => setModalVisible(false)}
        onSubmit={handleCreateSubmit}
      />

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
    </div>
  )
})

export default AssetsLibraryPane
