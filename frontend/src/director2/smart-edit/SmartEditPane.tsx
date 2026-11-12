import { useCallback, useEffect, useRef, useState } from "react"
import {
  Alert,
  Button,
  Checkbox,
  ColorPicker,
  Divider,
  Dropdown,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Segmented,
  Spin,
  Switch,
  Tooltip,
  message
} from "antd"
import {
  CheckCircle2,
  ChevronDown,
  Download,
  FileJson,
  FolderOpen,
  HardDrive,
  Image as ImageIcon,
  Music2,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings2,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  Type,
  Upload
} from "lucide-react"
import { useNavigate } from "react-router-dom"
import { ApiRequestError } from "../../api"
import { director2MenuEpisodeId, director2ProjectPath } from "../paths"
import { searchFilterOption } from "../../search-match"
import { listEpisodes, type Director2Episode } from "../api"
import {
  downloadBlob,
  exportBundle,
  exportMp4,
  importLocalMedia,
  readEdit,
  readExport,
  readSources,
  saveEdit,
  uploadMedia,
  type ExportJob
} from "./api"
import {
  EFFECTS,
  RATIOS,
  blankDocument,
  duplicateClip,
  endOf,
  frame,
  laneClips,
  makeClip,
  moveClip,
  packLane,
  parseDocument,
  patchClip,
  reorderClip,
  roughCut,
  splitClip,
  timecode,
  type EditAsset,
  type EditClip,
  type EditDocument
} from "./model"
import Preview from "./Preview"
import Timeline from "./Timeline"
import Inspector from "./Inspector"
import { useDirectorAssistant } from "../assistant/DirectorAssistant"
import { canAdoptEditingResult, type EditorBridge } from "../assistant/editing-tools"
import "./smart-edit.css"

type Panel = "media" | "effects" | "text" | "settings" | "export"
type Props = { csrfToken: string; projectId: string; episodeId: string | null }
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试"

export default function SmartEditPane(props: Props) {
  const [episodes, setEpisodes] = useState<Director2Episode[]>([])
  const [episodeError, setEpisodeError] = useState("")
  const loadEpisodes = useCallback(() => {
    setEpisodeError("")
    void listEpisodes(props.projectId)
      .then(setEpisodes)
      .catch((error) => setEpisodeError(errorText(error)))
  }, [props.projectId])
  useEffect(loadEpisodes, [loadEpisodes])
  return (
    <EditWorkspace
      key={`${props.projectId}:${props.episodeId || "main"}`}
      {...props}
      episodes={episodes}
      episodeError={episodeError}
      onReloadEpisodes={loadEpisodes}
    />
  )
}

function EditWorkspace({
  csrfToken,
  projectId,
  episodeId,
  episodes,
  episodeError,
  onReloadEpisodes
}: Props & {
  episodes: Director2Episode[]
  episodeError: string
  onReloadEpisodes: () => void
}) {
  const navigate = useNavigate(),
    sequence = episodeId || "main"
  const { registerEditor } = useDirectorAssistant()
  const commandLock = useRef(false)
  const [commandBusy, setCommandBusy] = useState(false)
  const [doc, setDoc] = useState<EditDocument>(blankDocument),
    [loading, setLoading] = useState(true),
    [loadError, setLoadError] = useState("")
  const [panel, setPanel] = useState<Panel>("media"),
    [filter, setFilter] = useState("all"),
    [search, setSearch] = useState("")
  const [selected, setSelected] = useState(""),
    [time, setTime] = useState(0),
    [playing, setPlaying] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  useEffect(() => {
    if (selected) setInspectorOpen(true)
  }, [selected])
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({})
  const [thumbnailFailed, setThumbnailFailed] = useState<
    Record<string, boolean>
  >({})
  const [saveState, setSaveState] = useState("已保存"),
    [saveError, setSaveError] = useState(""),
    [uploading, setUploading] = useState(false),
    [localOpen, setLocalOpen] = useState(false),
    [localPath, setLocalPath] = useState(""),
    [localRecursive, setLocalRecursive] = useState(false),
    [localBusy, setLocalBusy] = useState(false)
  const [bundleBusy, setBundleBusy] = useState(false),
    [exportBusy, setExportBusy] = useState(false),
    [quality, setQuality] = useState(1080),
    [format, setFormat] = useState("xml"),
    [includeMedia, setIncludeMedia] = useState(true)
  const [job, setJob] = useState<ExportJob | null>(null),
    [jobError, setJobError] = useState(""),
    [recovery, setRecovery] = useState<EditDocument | null>(null)
  const docRef = useRef(doc),
    revision = useRef(0),
    dirty = useRef(false),
    ready = useRef(false),
    mounted = useRef(true),
    conflict = useRef(false)
  const saving = useRef<Promise<void> | null>(null),
    recoveryKey = useRef("")
  const history = useRef({
    past: [] as EditDocument[],
    future: [] as EditDocument[]
  })
  const mediaInput = useRef<HTMLInputElement>(null),
    projectInput = useRef<HTMLInputElement>(null),
    workspace = useRef<HTMLDivElement>(null)
  const saveLatest = useCallback(async () => {
    if (saving.current) return saving.current
    if (!ready.current || !dirty.current || conflict.current) return
    const run = async () => {
      while (dirty.current && !conflict.current) {
        const snapshot = docRef.current
        if (mounted.current) {
          setSaveState("保存中…")
          setSaveError("")
        }
        try {
          const response = await saveEdit(
            csrfToken,
            projectId,
            sequence,
            revision.current,
            snapshot
          )
          revision.current = response.revision
          dirty.current = docRef.current !== snapshot
          if (dirty.current) {
            try {
              sessionStorage.setItem(
                recoveryKey.current,
                JSON.stringify({
                  revision: revision.current,
                  document: docRef.current
                })
              )
            } catch {
              /* cloud save still works */
            }
          } else sessionStorage.removeItem(recoveryKey.current)
          if (mounted.current) setSaveState(dirty.current ? "待保存" : "已保存")
        } catch (error) {
          if (error instanceof ApiRequestError && error.status === 409)
            conflict.current = true
          if (mounted.current) {
            setSaveState("保存失败")
            setSaveError(errorText(error))
          }
          throw error
        }
      }
    }
    saving.current = run().finally(() => {
      saving.current = null
    })
    return saving.current
  }, [csrfToken, projectId, sequence])

  const commit = useCallback(
    (
      change: EditDocument | ((current: EditDocument) => EditDocument),
      record = true
    ) => {
      if (!ready.current || conflict.current || commandLock.current) return
      try {
        const previous = docRef.current,
          next = typeof change === "function" ? change(previous) : change
        if (next === previous) return
        if (
          next.clips.length > 200 ||
          next.assets.length > 300 ||
          endOf(next) > 1800
        )
          throw new Error("单个工程最多 300 个素材、200 个片段、30 分钟")
        if (record) {
          history.current.past = [...history.current.past.slice(-59), previous]
          history.current.future = []
        }
        if (record) setPlaying(false)
        docRef.current = next
        dirty.current = true
        setDoc(next)
        setSaveState("待保存")
        try {
          sessionStorage.setItem(
            recoveryKey.current,
            JSON.stringify({ revision: revision.current, document: next })
          )
        } catch {
          /* save failure is shown separately */
        }
      } catch (error) {
        message.warning(errorText(error))
      }
    },
    []
  )

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError("")
    ready.current = false
    try {
      const snapshot = await readEdit(projectId, sequence)
      if (!mounted.current) return
      let document = snapshot.document
      recoveryKey.current = `zly-edit-recovery:${snapshot.draft_key}`
      try {
        const local = JSON.parse(
          sessionStorage.getItem(recoveryKey.current) || "null"
        )
        if (local?.document) {
          const parsed = parseDocument(JSON.stringify(local.document))
          if (local.revision === snapshot.revision) {
            document = parsed
            dirty.current = true
            message.info("已恢复尚未保存的浏览器草稿")
          } else setRecovery(parsed)
        }
      } catch {
        /* ignore invalid local recovery, preserve remote version */
      }
      revision.current = snapshot.revision
      docRef.current = document
      setDoc(document)
      ready.current = true
      conflict.current = false
      setSaveError("")
      history.current = { past: [], future: [] }
      setSaveState(dirty.current ? "待保存" : "已保存")
      setSelected("")
      setTime(0)
      const savedJob = sessionStorage.getItem(`${recoveryKey.current}:export`)
      if (savedJob)
        void readExport(projectId, savedJob)
          .then((value) => {
            if (mounted.current) setJob(value)
          })
          .catch(() => undefined)
      try {
        const sources = await readSources(projectId, sequence)
        if (mounted.current) {
          const existing = new Set(docRef.current.assets.map((a) => a.id)),
            additions = sources.filter((a) => !existing.has(a.id))
          if (additions.length)
            commit(
              (current) => ({
                ...current,
                assets: [...current.assets, ...additions]
              }),
              false
            )
        }
      } catch (error) {
        if (mounted.current)
          message.warning(
            `项目素材加载失败：${errorText(error)}。仍可导入本地素材。`
          )
      }
    } catch (error) {
      if (mounted.current) setLoadError(errorText(error))
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [projectId, sequence, commit])

  useEffect(() => {
    mounted.current = true
    void load()
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty.current) {
        event.preventDefault()
        event.returnValue = ""
      }
    }
    window.addEventListener("beforeunload", warn)
    return () => {
      mounted.current = false
      window.removeEventListener("beforeunload", warn)
      void saveLatest().catch(() => undefined)
    }
  }, [load, saveLatest])
  useEffect(() => {
    if (loading || !dirty.current || conflict.current) return
    const timer = window.setTimeout(() => {
      void saveLatest().catch(() => undefined)
    }, 700)
    return () => window.clearTimeout(timer)
  }, [doc, loading, saveLatest])
  const sequenceName = episodeId ? (() => { const episode = episodes.find(e => e.id === episodeId); return episode ? `第 ${episode.episode_num} 集 · ${episode.title}` : "当前分集" })() : "自由剪辑"
  useEffect(() => {
    if (loading || loadError || !ready.current) return
    const bridge: EditorBridge = {
      projectId, sequenceId: sequence, sequenceName, draftKey: recoveryKey.current,
      prepare: async () => {
        if (!mounted.current || !ready.current || conflict.current) throw new Error("请先解决剪辑加载或保存冲突，再开始铺轨")
        if (commandLock.current) throw new Error("正在处理剪辑操作，请稍后再试")
        commandLock.current = true; setCommandBusy(true); setPlaying(false)
        await saveLatest()
        return revision.current
      },
      release: () => { commandLock.current = false; if (mounted.current) setCommandBusy(false) },
      apply: (snapshot, baseRevision) => {
        if (!mounted.current || !canAdoptEditingResult(revision.current, baseRevision, snapshot.revision)) throw new Error("剪辑已变化，请重新加载已保存的铺轨结果")
        const previous = docRef.current
        const next = parseDocument(JSON.stringify(snapshot.document))
        history.current.past = [...history.current.past.slice(-59), previous]
        history.current.future = []
        const oldIds = new Set(previous.clips.map(c => c.id))
        const first = next.clips.find(c => !oldIds.has(c.id))
        revision.current = snapshot.revision; docRef.current = next; dirty.current = false
        sessionStorage.removeItem(recoveryKey.current)
        setDoc(next); setSaveState("已保存"); setSaveError(""); setPlaying(false)
        if (first) { setSelected(first.id); setTime(first.start) }
      }
    }
    return registerEditor(bridge)
  }, [loading, loadError, projectId, sequence, sequenceName, registerEditor, saveLatest])
  useEffect(() => {
    if (!playing) return
    const start = performance.now(),
      initial = time,
      end = endOf(docRef.current)
    let animation = 0
    const step = (now: number) => {
      const next = Math.min(end, initial + (now - start) / 1000)
      setTime(next)
      if (next < end) animation = requestAnimationFrame(step)
      else setPlaying(false)
    }
    animation = requestAnimationFrame(step)
    return () => cancelAnimationFrame(animation)
    // Playback clock restarts only on transport actions, not on every displayed frame.
  }, [playing]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return
    let cancelled = false,
      timer = 0
    const poll = async () => {
      try {
        const value = await readExport(projectId, job.id)
        if (cancelled) return
        setJob(value)
        setJobError("")
        if (["queued", "running"].includes(value.status))
          timer = window.setTimeout(poll, 2000)
      } catch (error) {
        if (!cancelled) {
          setJobError(errorText(error))
          timer = window.setTimeout(poll, 6000)
        }
      }
    }
    timer = window.setTimeout(poll, 1000)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [job?.id, job?.status, projectId])

  function seek(next: number) {
    setPlaying(false)
    setTime(next)
  }
  function play(value: boolean) {
    if (value && time >= endOf(doc) - 0.001) setTime(0)
    setPlaying(value)
  }
  function undo(redo = false) {
    const from = redo ? history.current.future : history.current.past,
      to = redo ? history.current.past : history.current.future
    const previous = from.pop()
    if (!previous) return
    to.push(docRef.current)
    commit(previous, false)
    setPlaying(false)
  }
  function patch(values: Partial<EditClip>) {
    commit((current) => patchClip(current, selected, values))
  }
  function split() {
    const next = splitClip(docRef.current, selected, time)
    if (next === docRef.current)
      message.info("请将播放头移到所选片段内部再拆分")
    else commit(next)
  }
  function remove() {
    commit((current) => ({
      ...current,
      clips: current.clips.filter((c) => c.id !== selected)
    }))
    setSelected("")
  }
  function add(asset: EditAsset, at?: number) {
    const current = docRef.current
    const clip = makeClip(
      current,
      asset,
      at ??
        (asset.kind === "audio"
          ? time
          : Math.max(
              0,
              ...laneClips(current, "video").map((c) => c.start + c.duration)
            ))
    )
    commit({ ...current, clips: [...current.clips, clip] })
    setSelected(clip.id)
    seek(clip.start)
  }
  function addText(preset = "default") {
    const clip = makeClip(docRef.current, undefined, time)
    if (preset === "title")
      Object.assign(clip, {
        text: "故事，从此刻开始",
        font_size: 110,
        y: 0,
        color: "#f5c451"
      })
    if (preset === "subtitle")
      Object.assign(clip, { text: "写下这一幕的对白", font_size: 56, y: 36 })
    commit((current) => ({ ...current, clips: [...current.clips, clip] }))
    setSelected(clip.id)
    seek(clip.start)
  }
  const probeAsset = useCallback(
    (id: string, duration: number) => {
      const current = docRef.current,
        asset = current.assets.find((a) => a.id === id)
      if (
        !asset ||
        !Number.isFinite(duration) ||
        Math.abs(asset.duration - duration) < 0.01 ||
        duration < 1 / current.settings.fps
      )
        return
      const fps = current.settings.fps
      commit(
        {
          ...current,
          assets: current.assets.map((a) =>
            a.id === id ? { ...a, duration } : a
          ),
          clips: current.clips.flatMap((c) => {
            if (c.asset_id !== id) return [c]
            const available =
              Math.floor(((duration - c.in_point) / c.speed) * fps) / fps
            if (available < 1 / fps) return []
            const length = Math.min(c.duration, available)
            return [
              {
                ...c,
                duration: length,
                fade_in: Math.min(c.fade_in, length / 2),
                fade_out: Math.min(c.fade_out, length / 2)
              }
            ]
          })
        },
        false
      )
    },
    [commit]
  )
  async function importFiles(files: File[]) {
    setUploading(true)
    for (const file of files) {
      if (file.size > 512 * 1024 * 1024) {
        message.error(`${file.name} 超过 512 MB`)
        continue
      }
      try {
        const asset = await uploadMedia(csrfToken, projectId, sequence, file)
        if (mounted.current)
          commit((current) => ({
            ...current,
            assets: [...current.assets, asset]
          }))
      } catch (error) {
        message.error(`${file.name}：${errorText(error)}`)
      }
    }
    if (mounted.current) setUploading(false)
  }
  async function importLocal() {
    const path = localPath.trim()
    if (!path) {
      message.warning("请输入本机文件或文件夹的绝对路径")
      return
    }
    setLocalBusy(true)
    try {
      const result = await importLocalMedia(
        csrfToken,
        projectId,
        sequence,
        path,
        localRecursive
      )
      if (mounted.current) {
        const known = new Set(docRef.current.assets.map((asset) => asset.url))
        const fresh = result.assets.filter((asset) => !known.has(asset.url))
        if (fresh.length)
          commit((current) => ({
            ...current,
            assets: [...current.assets, ...fresh]
          }))
        if (result.skipped.length)
          message.warning(
            `已引用 ${fresh.length} 个，跳过 ${result.skipped.length} 个：${result.skipped[0].name}（${result.skipped[0].error}）`
          )
        else
          message.success(
            fresh.length
              ? `已引用 ${fresh.length} 个本机素材`
              : "这些素材已经在素材库里"
          )
      }
      setLocalOpen(false)
    } catch (error) {
      message.error(errorText(error))
    } finally {
      if (mounted.current) setLocalBusy(false)
    }
  }
  async function importProject(file?: File) {
    if (!file) return
    if (file.size > 2 * 1024 * 1024) {
      message.error("工程文件不能超过 2 MB")
      return
    }
    try {
      const document = parseDocument(await file.text())
      commit(document)
      setSelected("")
      seek(0)
      message.success("工程已导入，可撤销恢复原时间线")
    } catch (error) {
      message.error(errorText(error))
    }
  }
  function downloadJson(document = docRef.current) {
    downloadBlob(
      new Blob([JSON.stringify(document, null, 2)], {
        type: "application/json"
      }),
      `${document.name}.zly.json`
    )
  }
  async function startExport() {
    setExportBusy(true)
    setJobError("")
    try {
      await saveLatest()
      const result = await exportMp4(
        csrfToken,
        projectId,
        docRef.current,
        quality
      )
      setJob(result)
      sessionStorage.setItem(`${recoveryKey.current}:export`, result.id)
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setExportBusy(false)
    }
  }
  async function bundle() {
    setBundleBusy(true)
    try {
      const blob = await exportBundle(
        csrfToken,
        projectId,
        docRef.current,
        format,
        includeMedia
      )
      downloadBlob(blob, `${docRef.current.name}-${format}.zip`)
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setBundleBusy(false)
    }
  }
  function dragClip(
    id: string,
    kind: "move" | "left" | "right",
    delta: number,
    snap: boolean
  ) {
    commit((current) => {
      const clip = current.clips.find((c) => c.id === id)
      if (!clip) return current
      const offset =
        frame(Math.abs(delta), current.settings.fps) * Math.sign(delta)
      if (kind === "move")
        return moveClip(current, id, clip.start + offset, snap)
      if (kind === "right")
        return patchClip(current, id, { duration: clip.duration + offset })
      const start = Math.max(0, clip.start + offset),
        change = start - clip.start,
        inPoint = clip.in_point + change * clip.speed
      if (inPoint < 0 || clip.duration - change < 1 / current.settings.fps)
        throw new Error("不能裁切到原始素材范围之外")
      return patchClip(current, id, {
        start,
        duration: clip.duration - change,
        in_point: inPoint
      })
    })
  }
  const selectedClip = doc.clips.find((c) => c.id === selected)
  const sampleAsset =
    doc.assets.find((a) => a.id === selectedClip?.asset_id) ||
    doc.assets.find((a) => a.kind !== "audio")
  const sampleImage =
    sampleAsset?.thumbnail ||
    (sampleAsset && thumbnails[sampleAsset.id]) ||
    (sampleAsset?.kind === "image" ? sampleAsset.url : null) ||
    (sampleAsset && thumbnailFailed[sampleAsset.id]
      ? doc.assets.find((a) => a.kind === "image")?.url
      : null)
  const panelNames: Record<Panel, string> = {
    media: "素材库",
    effects: "画面特效",
    text: "文字",
    settings: "项目设置",
    export: "导出"
  }
  const visibleAssets = doc.assets.filter(
    (a) =>
      (filter === "all" || a.kind === filter) &&
      a.name.toLowerCase().includes(search.toLowerCase())
  )
  const busyJob = !!job && ["queued", "running"].includes(job.status)
  const panels = [
    { id: "media", Icon: FolderOpen },
    { id: "effects", Icon: Sparkles },
    { id: "text", Icon: Type },
    { id: "settings", Icon: Settings2 },
    { id: "export", Icon: Download }
  ] as const
  if (loading)
    return (
      <div className="se-loading-skeleton" role="status" aria-busy="true" aria-label="正在打开剪辑工程">
        <div className="se-skeleton-header" aria-hidden="true">
          <span className="studio-skeleton-bar" style={{ width: 180, height: 22, borderRadius: 6 }} />
          <span className="studio-skeleton-bar" style={{ width: 120 }} />
        </div>
        <div className="se-skeleton-workbench" aria-hidden="true">
          <aside className="se-skeleton-library">
            <span className="studio-skeleton-bar" style={{ width: "72%" }} />
            <span className="studio-skeleton-bar" style={{ width: "86%" }} />
            <span className="studio-skeleton-bar" style={{ width: "78%" }} />
            <span className="studio-skeleton-bar" style={{ width: "82%" }} />
            <span className="studio-skeleton-bar" style={{ width: "64%" }} />
          </aside>
          <div className="se-skeleton-preview">
            <span className="studio-skeleton-bar se-skeleton-stage" />
          </div>
        </div>
        <div className="se-skeleton-timeline" aria-hidden="true">
          <span className="studio-skeleton-bar" style={{ width: "12%" }} />
          <span className="studio-skeleton-bar" style={{ width: "46%" }} />
          <span className="studio-skeleton-bar" style={{ width: "28%" }} />
        </div>
        <p className="se-skeleton-status"><Spin size="small" /><span>正在打开剪辑工程…</span></p>
      </div>
    )
  if (loadError)
    return (
      <div className="se-loading">
        <Alert
          type="error"
          showIcon
          title="剪辑工程加载失败"
          description={loadError}
          action={<Button onClick={() => void load()}>重新加载</Button>}
        />
      </div>
    )
  return (
    <div
      ref={workspace}
      className="smart-edit"
      inert={commandBusy}
      aria-busy={commandBusy}
      tabIndex={0}
      aria-label="智能剪辑工作区"
      onKeyDown={(event) => {
        if (
          (event.target as HTMLElement).closest(
            "button,input,textarea,[contenteditable=true],[role='button']:not(.se-clip),[role='switch'],[role='tab'],[role='combobox'],[role='menuitem'],.ant-select,.ant-slider,.ant-input-number"
          )
        )
          return
        if (event.code === "Space") {
          event.preventDefault()
          play(!playing)
        } else if (
          (event.ctrlKey || event.metaKey) &&
          event.key.toLowerCase() === "z"
        ) {
          event.preventDefault()
          undo(event.shiftKey)
        } else if (event.key === "Delete" || event.key === "Backspace") {
          if (selected) {
            event.preventDefault()
            remove()
          }
        } else if (
          event.key.toLowerCase() === "s" &&
          !event.ctrlKey &&
          !event.metaKey
        ) {
          event.preventDefault()
          split()
        }
      }}
    >
      <div className="se-header">
        <div className="se-header-title">
          <Dropdown
            trigger={["click"]}
            menu={{
              selectedKeys: ["edit"],
              items: [
                { key: "content", label: "内容库" },
                { key: "assets", label: "资产库" },
                { key: "workshop", label: "剧集工坊" },
                { key: "edit", label: "智能剪辑" },
                { key: "jobs", label: "全部任务" }
              ],
              onClick: ({ key }) => {
                if (key === "edit") return
                setPlaying(false)
                void saveLatest()
                  .then(() =>
                    navigate(
                      director2ProjectPath(
                        projectId,
                        key,
                        director2MenuEpisodeId({ targetMenu: key, currentMenu: "edit", currentEpisodeId: episodeId })
                      )
                    )
                  )
                  .catch(() => message.error("请先解决保存错误，再切换页面"))
              }
            }}
          >
            <Button type="text" className="se-project-menu" aria-label="切换工程模块" icon={<Scissors size={22} />}><ChevronDown size={10} /></Button>
          </Dropdown>
          <h2>智能剪辑</h2>
          {sequence.startsWith("canvas-") && <Button type="text" onClick={() => { setPlaying(false); void saveLatest().then(() => navigate(director2ProjectPath(projectId, "assets") + "?view=canvas")).catch(() => message.error("请先保存剪辑修改")) }}>返回创作画布</Button>}
          <Select
            aria-label="选择剪辑分集"
            showSearch
            filterOption={searchFilterOption}
            value={sequence}
            options={[
              { value: "main", label: "自由剪辑" },
              ...(sequence.startsWith("canvas-") ? [{ value: sequence, label: "画布剪辑工程" }] : []),
              ...episodes.map((ep) => ({
                value: ep.id,
                label: `第 ${ep.episode_num} 集 · ${ep.title}`
              }))
            ]}
            onChange={(value) => {
              setPlaying(false)
              void saveLatest()
                .then(() =>
                  navigate(
                    director2ProjectPath(
                      projectId,
                      "edit",
                      value === "main" ? null : value
                    )
                  )
                )
                .catch(() => message.error("请先解决保存错误，再切换分集"))
            }}
          />
        </div>
        <div className="se-header-actions">
          <span
            className={`se-save-status${saveError ? " is-error" : ""}`}
            role="status"
          >
            {saveState === "已保存" && !saveError && <CheckCircle2 size={18} aria-hidden="true" />}
            {saveState}
          </span>
          <Tooltip title="立即保存">
            <Button
              type="text"
              aria-label="保存剪辑工程"
              icon={<Save size={15} />}
              onClick={() => void saveLatest().catch(() => undefined)}
            />
          </Tooltip>
          {doc.clips.length ? (
            <Popconfirm
              title="按分镜重新组接时间线？"
              description="当前编辑可通过撤销恢复。"
              okText="重新粗剪"
              cancelText="取消"
              onConfirm={() => {
                commit(roughCut(docRef.current))
                seek(0)
              }}
            >
              <Button
                icon={<Sparkles size={14} />}
                disabled={!doc.assets.length || conflict.current}
              >
                智能粗剪
              </Button>
            </Popconfirm>
          ) : (
            <Button
              icon={<Sparkles size={14} />}
              disabled={!doc.assets.length}
              onClick={() => commit(roughCut(docRef.current))}
            >
              智能粗剪
            </Button>
          )}
          <Button
            type={inspectorOpen ? "default" : "text"}
            className="se-inspector-toggle"
            icon={<SlidersHorizontal size={15} />}
            aria-label="切换片段属性"
            aria-expanded={inspectorOpen}
            aria-controls="se-inspector"
            onClick={() => setInspectorOpen((current) => !current)}
          >片段属性</Button>
          <Button
            type="primary"
            icon={<Download size={14} />}
            onClick={() => setPanel("export")}
          >
            导出
          </Button>
        </div>
      </div>
      {saveError && (
        <Alert
          type="error"
          showIcon
          title={saveError}
          action={
            <div className="se-inline-actions">
              <Button size="small" onClick={() => downloadJson()}>
                下载草稿 JSON
              </Button>
              {conflict.current ? (
                <Popconfirm
                  title="下载当前草稿后，重新加载云端工程？"
                  onConfirm={() => {
                    dirty.current = false
                    void load()
                  }}
                >
                  <Button size="small">重新加载</Button>
                </Popconfirm>
              ) : (
                <Button
                  size="small"
                  onClick={() => void saveLatest().catch(() => undefined)}
                >
                  重试保存
                </Button>
              )}
            </div>
          }
        />
      )}
      {episodeError && (
        <Alert
          type="warning"
          title={`分集列表加载失败：${episodeError}`}
          action={
            <Button size="small" onClick={onReloadEpisodes}>
              重试
            </Button>
          }
        />
      )}
      {recovery && (
        <Alert
          type="warning"
          title="浏览器中有一份较早的未保存草稿，云端已更新。可先下载备份。"
          action={
            <Button size="small" onClick={() => downloadJson(recovery)}>
              下载旧草稿
            </Button>
          }
          closable
          onClose={() => setRecovery(null)}
        />
      )}
      <div className={`se-workbench${inspectorOpen ? " has-inspector" : ""}`}>
        <section className="se-library">
          <nav className="se-tools" aria-label="剪辑工具">
            {panels.map(({ id, Icon }) => (
              <Tooltip key={id} title={panelNames[id]} placement="right">
                <Button
                  type={panel === id ? "primary" : "text"}
                  aria-label={panelNames[id]}
                  aria-pressed={panel === id}
                  icon={<Icon size={18} />}
                  onClick={() => setPanel(id)}
                />
              </Tooltip>
            ))}
          </nav>
          <div className="se-library-content">
            <div className="se-panel-heading">
              <strong>{panelNames[panel]}{panel === "media" && <span className="se-asset-count">{doc.assets.length}</span>}</strong>
            </div>
            <div className="se-library-scroll">
              {panel === "media" && (
                <>
                  <Input
                    prefix={<Search size={14} />}
                    aria-label="搜索素材"
                    placeholder="搜索素材"
                    allowClear
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                  <Segmented
                    className="se-media-filter"
                    aria-label="素材类型"
                    block
                    value={filter}
                    options={[
                      { value: "all", label: "全部" },
                      { value: "video", label: "视频" },
                      { value: "image", label: "图片" },
                      { value: "audio", label: "音频" }
                    ]}
                    onChange={setFilter}
                  />
                  <div className="se-import-actions">
                    <Tooltip title="引用本机文件或文件夹，不复制、不上传">
                      <Button icon={<FolderOpen size={14} />} onClick={() => setLocalOpen(true)}>引用本机</Button>
                    </Tooltip>
                    <Tooltip title="上传到七牛云后引用">
                      <Button icon={<Upload size={14} />} loading={uploading} onClick={() => mediaInput.current?.click()}>上传素材</Button>
                    </Tooltip>
                  </div>
                  <div className="se-asset-grid">
                    {visibleAssets.map((asset) => (
                      <div
                        key={asset.id}
                        className="se-asset"
                        draggable
                        onDragStart={(event) =>
                          event.dataTransfer.setData(
                            "application/x-zly-asset",
                            asset.id
                          )
                        }
                        onDoubleClick={() => add(asset)}
                        role="button"
                        tabIndex={0}
                        aria-label={`添加素材：${asset.name}`}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.code === "Space") {
                            event.preventDefault()
                            add(asset)
                          }
                        }}
                      >
                        <div className="se-asset-thumbnail">
                          {asset.thumbnail || asset.kind === "image" ? (
                            <img
                              src={asset.thumbnail || asset.url}
                              alt=""
                              loading="lazy"
                            />
                          ) : asset.kind === "video" ? (
                            <video
                              crossOrigin="anonymous"
                              src={asset.url}
                              muted
                              preload="metadata"
                              onSeeked={(event) => {
                                const media = event.currentTarget
                                if (!media.videoWidth || thumbnails[asset.id])
                                  return
                                try {
                                  const canvas =
                                    document.createElement("canvas")
                                  canvas.width = 192
                                  canvas.height = Math.round(
                                    (192 * media.videoHeight) / media.videoWidth
                                  )
                                  const paint = canvas.getContext("2d")
                                  if (!paint)
                                    throw new Error("Canvas unavailable")
                                  paint.drawImage(
                                    media,
                                    0,
                                    0,
                                    canvas.width,
                                    canvas.height
                                  )
                                  const pixels = paint.getImageData(
                                    0,
                                    0,
                                    canvas.width,
                                    canvas.height
                                  ).data
                                  let light = 0,
                                    samples = 0
                                  for (let i = 0; i < pixels.length; i += 64) {
                                    light +=
                                      (pixels[i] +
                                        pixels[i + 1] +
                                        pixels[i + 2]) /
                                      3
                                    samples++
                                  }
                                  if (light / samples < 8) {
                                    const attempt =
                                      Number(media.dataset.thumbAttempt || 0) +
                                      1
                                    if (attempt < 3) {
                                      media.dataset.thumbAttempt =
                                        String(attempt)
                                      media.currentTime =
                                        media.duration *
                                        (attempt === 1 ? 0.35 : 0.65)
                                      return
                                    }
                                    throw new Error("No representative frame")
                                  }
                                  const thumbnail = canvas.toDataURL(
                                    "image/jpeg",
                                    0.72
                                  )
                                  setThumbnails((current) => ({
                                    ...current,
                                    [asset.id]: thumbnail
                                  }))
                                } catch {
                                  setThumbnailFailed((current) => ({
                                    ...current,
                                    [asset.id]: true
                                  }))
                                }
                              }}
                              onError={(event) => {
                                const media = event.currentTarget
                                if (media.hasAttribute("crossorigin")) {
                                  media.removeAttribute("crossorigin")
                                  media.load()
                                }
                              }}
                              onLoadedMetadata={(event) => {
                                const media = event.currentTarget
                                probeAsset(asset.id, media.duration)
                                if (Number.isFinite(media.duration)) {
                                  media.dataset.thumbAttempt = "0"
                                  media.currentTime = Math.max(
                                    0.01,
                                    Math.min(1, media.duration * 0.15)
                                  )
                                }
                              }}
                            />
                          ) : (
                            <Music2 size={25} />
                          )}
                          <span className="se-asset-duration">
                            {asset.kind === "image" ? (
                              <ImageIcon size={12} />
                            ) : (
                              timecode(asset.duration, doc.settings.fps).slice(0, 5)
                            )}
                          </span>
                          <Button
                            type="primary"
                            size="small"
                            aria-label={`将${asset.name}加入时间线`}
                            icon={<Plus size={12} />}
                            onClick={(event) => {
                              event.stopPropagation()
                              add(asset)
                            }}
                          />
                        </div>
                        <span
                          className="se-asset-name"
                          title={
                            asset.local_path
                              ? `${asset.name}\n${asset.local_path}`
                              : asset.name
                          }
                        >
                          {asset.name}
                        </span>
                      </div>
                    ))}
                  </div>
                  {!visibleAssets.length && (
                    <div className="se-media-empty">
                      <FolderOpen size={29} strokeWidth={1.3} />
                      <strong>
                        {search ? "没有匹配的素材" : "把镜头带到剪辑台"}
                      </strong>
                      <p>
                        {search
                          ? "试试其他关键词"
                          : episodeId
                            ? "本集成片、分镜图和配音会自动出现在这里，也可以引用本机素材。"
                            : "选择分集载入工坊素材，或引用本机的视频、图片与音频。"}
                      </p>
                      <Button
                        icon={<HardDrive size={14} />}
                        onClick={() => setLocalOpen(true)}
                      >
                        引用本机素材
                      </Button>
                    </div>
                  )}
                  <p className="se-help se-library-hint">双击或拖动素材到时间线</p>
                </>
              )}
              {panel === "effects" && (
                <>
                  <p className="se-help">
                    选择画面片段后应用特效，预览与 MP4 同步生效。
                  </p>
                  {sampleAsset && thumbnailFailed[sampleAsset.id] && (
                    <p className="se-help">
                      视频无法抽取预览帧，卡片使用项目图片示意；实际效果请看中央预览。
                    </p>
                  )}
                  <div className="se-effect-grid">
                    {EFFECTS.map((effect) => (
                      <Button
                        key={effect.id}
                        className={`se-effect${selectedClip?.effect === effect.id ? " is-selected" : ""}`}
                        disabled={selectedClip?.track !== "video"}
                        onClick={() => patch({ effect: effect.id })}
                      >
                        <div
                          className="se-effect-thumb"
                          style={{ filter: effect.css }}
                        >
                          {sampleImage ? (
                            <img src={sampleImage} alt="" />
                          ) : (
                            <ImageIcon size={27} strokeWidth={1.2} />
                          )}
                        </div>
                        <span>{effect.name}</span>
                      </Button>
                    ))}
                  </div>
                  <p className="se-help">调色和柔焦可在右侧属性中随时重置。</p>
                </>
              )}
              {panel === "text" && (
                <>
                  <p className="se-help">
                    添加标题或对白，再在右侧编辑内容与位置。
                  </p>
                  <div className="se-text-presets">
                    <Button onClick={() => addText()}>
                      <span>Aa</span>
                      <small>默认文字</small>
                    </Button>
                    <Button onClick={() => addText("title")}>
                      <span className="se-preset-title">大标题</span>
                      <small>故事标题</small>
                    </Button>
                    <Button onClick={() => addText("subtitle")}>
                      <span className="se-preset-subtitle">这一幕的对白</span>
                      <small>对白字幕</small>
                    </Button>
                  </div>
                </>
              )}
              {panel === "settings" && (
                <>
                  <div className="se-property">
                    <label htmlFor="se-project-name">剪辑名称</label>
                    <Input
                      id="se-project-name"
                      value={doc.name}
                      maxLength={120}
                      onChange={(event) =>
                        commit((current) => ({
                          ...current,
                          name: event.target.value
                        }))
                      }
                    />
                  </div>
                  <div className="se-property">
                    <label>画面比例</label>
                    <Select
                      aria-label="画面比例"
                      value={doc.settings.ratio}
                      options={Object.keys(RATIOS).map((value) => ({
                        value,
                        label: value
                      }))}
                      onChange={(ratio) =>
                        commit((current) => ({
                          ...current,
                          settings: { ...current.settings, ratio }
                        }))
                      }
                    />
                  </div>
                  <div className="se-property">
                    <label>帧率</label>
                    <Select
                      aria-label="项目帧率"
                      value={doc.settings.fps}
                      options={[24, 25, 30, 60].map((value) => ({
                        value,
                        label: `${value} fps`
                      }))}
                      onChange={(fps) =>
                        commit((current) => ({
                          ...current,
                          settings: { ...current.settings, fps },
                          clips: current.clips.map((c) => {
                            const duration = Math.max(
                              1 / fps,
                              frame(c.start + c.duration, fps) -
                                frame(c.start, fps)
                            )
                            return {
                              ...c,
                              start: frame(c.start, fps),
                              duration,
                              fade_in: Math.min(c.fade_in, duration / 2),
                              fade_out: Math.min(c.fade_out, duration / 2)
                            }
                          })
                        }))
                      }
                    />
                  </div>
                  <div className="se-property">
                    <label>画布背景</label>
                    <ColorPicker
                      value={doc.settings.background}
                      showText
                      disabledAlpha
                      onChange={(color) =>
                        commit((current) => ({
                          ...current,
                          settings: {
                            ...current.settings,
                            background: color.toHexString()
                          }
                        }))
                      }
                    />
                  </div>
                  <Divider />
                  <Button
                    block
                    icon={<FileJson size={15} />}
                    onClick={() => projectInput.current?.click()}
                  >
                    打开 JSON 工程
                  </Button>
                  <p className="se-help">
                    每集独立自动保存，刷新后可继续编辑。打开工程会替换当前时间线，可通过撤销恢复。
                  </p>
                  <Button
                    type="text"
                    icon={<RefreshCw size={13} />}
                    onClick={() => {
                      void readSources(projectId, sequence)
                        .then((sources) => {
                          commit((current) => ({
                            ...current,
                            assets: [
                              ...current.assets.filter(
                                (a) => !sources.some((s) => s.id === a.id)
                              ),
                              ...sources
                            ]
                          }))
                          message.success("已同步项目素材")
                        })
                        .catch((error) => message.error(errorText(error)))
                    }}
                  >
                    刷新工坊素材
                  </Button>
                </>
              )}
              {panel === "export" && (
                <>
                  <div className="se-export-section">
                    <h3>导出成片</h3>
                    <p>按当前剪辑生成 MP4，包含文字、画面调整与混音。</p>
                    <Select
                      aria-label="导出画质"
                      value={quality}
                      options={[
                        { value: 1080, label: "高清 1080P" },
                        { value: 720, label: "标准 720P" }
                      ]}
                      onChange={setQuality}
                    />
                    <Button
                      type="primary"
                      block
                      icon={<Download size={15} />}
                      loading={exportBusy}
                      disabled={!doc.clips.length || busyJob || !!saveError}
                      onClick={() => void startExport()}
                    >
                      {busyJob ? "正在导出成片" : "导出 MP4"}
                    </Button>
                    {job && (
                      <div className="se-export-progress">
                        <Progress
                          size="small"
                          percent={job.progress}
                          status={
                            job.status === "failed"
                              ? "exception"
                              : job.status === "completed"
                                ? "success"
                                : "active"
                          }
                        />
                        <span role="status">
                          {job.status === "queued"
                            ? "排队中"
                            : job.status === "running"
                              ? "正在合成，请稍候…"
                              : job.status === "completed"
                                ? "成片已就绪"
                                : job.error_message || "导出失败，请重试"}
                        </span>
                        {job.result_url && (
                          <Button
                            block
                            href={job.result_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            icon={<Download size={13} />}
                          >
                            打开 / 下载成片
                          </Button>
                        )}
                        {jobError && (
                          <p role="alert">连接暂时失败，正在重试：{jobError}</p>
                        )}
                      </div>
                    )}
                  </div>
                  <Divider />
                  <div className="se-export-section">
                    <h3>导出剪辑工程</h3>
                    <p>带到后期软件继续编辑。</p>
                    <Select
                      aria-label="工程导出格式"
                      value={format}
                      options={[
                        { value: "xml", label: "XML · Premiere / 达芬奇" },
                        { value: "jianying", label: "剪映基础草稿（实验）" },
                        { value: "otio", label: "OTIO · OpenTimelineIO" },
                        { value: "json", label: "JSON · 完整工作台工程" }
                      ]}
                      onChange={setFormat}
                    />
                    <div className="se-property-switch">
                      <span>打包已使用素材</span>
                      <Switch
                        aria-label="打包已使用素材"
                        checked={includeMedia}
                        onChange={setIncludeMedia}
                      />
                    </div>
                    <Button
                      block
                      icon={<Download size={14} />}
                      loading={bundleBusy}
                      disabled={!doc.clips.length}
                      onClick={() => void bundle()}
                    >
                      导出工程{includeMedia ? "与素材" : ""}
                    </Button>
                    <p className="se-help">
                      工程交换保留基础剪辑，文字与特效在后期软件中调整。剪映草稿兼容性取决于客户端版本。ZIP
                      同时包含完整 JSON。
                    </p>
                    <Button
                      type="text"
                      block
                      icon={<FileJson size={14} />}
                      onClick={() => downloadJson()}
                    >
                      下载 JSON 备份
                    </Button>
                  </div>
                </>
              )}
            </div>
          </div>
        </section>
        <Preview
          doc={doc}
          time={time}
          playing={playing}
          onTime={seek}
          onPlay={play}
          onProbe={probeAsset}
        />
        {inspectorOpen && <Inspector doc={doc} clip={selectedClip} thumbnails={thumbnails} onPatch={patch} onClose={() => setInspectorOpen(false)} />}
      </div>
      <Timeline
        doc={doc}
        thumbnails={thumbnails}
        time={time}
        selected={selected}
        canUndo={!!history.current.past.length}
        canRedo={!!history.current.future.length}
        onSelect={(id) => { setSelected(id); setInspectorOpen(true) }}
        onTime={seek}
        onUndo={() => undo()}
        onRedo={() => undo(true)}
        onSplit={split}
        onDelete={remove}
        onCopy={() => commit((current) => duplicateClip(current, selected))}
        onReorder={(direction) =>
          commit((current) => reorderClip(current, selected, direction))
        }
        onPack={() => commit((current) => packLane(current, "video"))}
        onDrag={dragClip}
        onDropAsset={(id, at) => {
          const asset = docRef.current.assets.find((a) => a.id === id)
          if (asset) add(asset, at)
        }}
      />
      <Modal
        open={localOpen}
        title="引用本机素材"
        okText="开始引用"
        cancelText="取消"
        confirmLoading={localBusy}
        onOk={() => void importLocal()}
        onCancel={() => setLocalOpen(false)}
      >
        <p className="se-help">
          粘贴本机的文件或文件夹绝对路径。工作台只记录原文件位置，不复制、不上传；素材移动或删除后需要重新引用。
        </p>
        <Input.TextArea
          aria-label="本机素材路径"
          placeholder={"G:\\工作区\\项目\\S01E09"}
          autoSize={{ minRows: 2, maxRows: 4 }}
          value={localPath}
          onChange={(event) => setLocalPath(event.target.value)}
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault()
              void importLocal()
            }
          }}
        />
        <Checkbox
          className="se-local-recursive"
          checked={localRecursive}
          onChange={(event) => setLocalRecursive(event.target.checked)}
        >
          路径为文件夹时包含子文件夹
        </Checkbox>
      </Modal>
      <input
        type="file"
        multiple
        accept=".mp4,.mov,.webm,.mkv,.png,.jpg,.jpeg,.webp,.mp3,.wav,.m4a,.ogg,.flac"
        hidden
        ref={mediaInput}
        onChange={(event) => {
          const files = Array.from(event.target.files || [])
          event.target.value = ""
          void importFiles(files)
        }}
      />
      <input
        type="file"
        accept=".json"
        hidden
        ref={projectInput}
        onChange={(event) => {
          const file = event.target.files?.[0]
          event.target.value = ""
          void importProject(file)
        }}
      />
    </div>
  )
}
