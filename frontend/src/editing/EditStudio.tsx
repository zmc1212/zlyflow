import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Alert,
  Button,
  Checkbox,
  ColorPicker,
  Dropdown,
  Input,
  Modal,
  Popover,
  Progress,
  Segmented,
  Select,
  Spin,
  Tooltip,
  message
} from "antd"
import {
  CheckCircle2,
  ChevronDown,
  Download,
  Film,
  FolderOpen,
  HardDrive,
  Image as ImageIcon,
  LayoutGrid,
  Music2,
  Plus,
  Search,
  Type,
  Upload,
  X
} from "lucide-react"
import { readTranscript, downloadBlob, type MediaTranscript } from "./api"
import {
  RATIOS,
  frame,
  laneClips,
  makeClip,
  timecode,
  type EditAsset,
  type EditDocument,
  type EditTrack
} from "./model"
import { acquireEditSession, editorSessionKey, ensureEditableAsset, mergeEditAssetPool } from "./editing-shared"
import { assetFrames, imageFrames } from "./filmstrip"
import { useEditDocument } from "./use-edit-document"
import Preview from "./Preview"
import Timeline from "./Timeline"
import Inspector from "./Inspector"
import "./editing.css"
import "./editing-overlays.css"

type Props = {
  csrfToken: string
  scopeProjectId: string
  sequence: string
  variant: "timeline" | "multitrack"
  title: string
  /** 画布域素材池（画布媒体节点 / 导演资产），自动并入资产列表。 */
  canvasAssets: EditAsset[]
  /** 非画布 scope 且存在音轨时可从转写结果生成字幕片段。 */
  allowSubtitle?: boolean
  onClose: () => void
}

type LibraryFilter = "all" | "grouped" | "image" | "video" | "audio" | "added"

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试"

/**
 * 全屏时间线编辑器（即梦式）。
 *
 * - timeline：无限画布「时间线」节点全屏态 —— 左侧已导入/画布资产双页签，底部时间线。
 * - multitrack：导演台「多轨编辑器」节点全屏态 —— 左侧资产库（自动含当前画布资产）、
 *   中间预览、右侧片段设置、底部多轨时间线与「添加字幕」。
 *
 * 文档持久化与 SmartEditPane 完全同源（revision 乐观锁 / 409 冲突 / 导出 MP4 任务）。
 */
export default function EditStudio(props: Props) {
  const { csrfToken, scopeProjectId, sequence, variant, title, canvasAssets, allowSubtitle, onClose } = props
  const multitrack = variant === "multitrack"
  const ctrl = useEditDocument({ csrfToken, scopeProjectId, sequence })
  const {
    doc, docRef, loading, loadError, saveState, saveError, reload, saveLatest, commit,
    time, playing, seek, play, selected, select, undo, patch, split, remove, add, copy,
    dragClip, probeAsset, importFiles, uploading, thumbnails, captureThumbnail, job,
    startExport
  } = ctrl
  const [filter, setFilter] = useState<LibraryFilter>("all")
  const [search, setSearch] = useState("")
  const [sourceTab, setSourceTab] = useState<"imported" | "canvas">("imported")
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [localOpen, setLocalOpen] = useState(false)
  const [localPath, setLocalPath] = useState("")
  const [localRecursive, setLocalRecursive] = useState(false)
  const [localBusy, setLocalBusy] = useState(false)
  const [subtitleBusy, setSubtitleBusy] = useState(false)
  const [transcriptNote, setTranscriptNote] = useState("")
  const [importingAsset, setImportingAsset] = useState(false)
  // 即梦式胶片带：素材 id → 多帧长条图，全屏时间线片段背景
  const [strips, setStrips] = useState<Record<string, string>>({})
  const stripRequested = useRef(new Set<string>())
  const mediaInput = useRef<HTMLInputElement>(null)
  const workspace = useRef<HTMLDivElement>(null)

  // 画布域素材可能是站内交付地址：加入时间线前统一转入剪辑素材存储。
  const addFromPool = useCallback(
    async (asset: EditAsset, at?: number, track?: EditTrack) => {
      setImportingAsset(true)
      try {
        const editable = await ensureEditableAsset(csrfToken, scopeProjectId, sequence, asset)
        add(editable, at, track)
      } catch (error) {
        message.error(errorText(error))
      } finally {
        setImportingAsset(false)
      }
    },
    [add, csrfToken, scopeProjectId, sequence]
  )

  // 全屏编辑器独占该剪辑工程的写入会话；迷你节点据此暂停自动保存。
  const sessionKey = editorSessionKey(scopeProjectId, sequence)
  useEffect(() => acquireEditSession(sessionKey), [sessionKey])

  useEffect(() => {
    if (selected) setInspectorOpen(true)
  }, [selected])

  const library = useMemo(
    () => mergeEditAssetPool(doc.assets, canvasAssets),
    [doc.assets, canvasAssets]
  )
  const usedAssetIds = useMemo(() => {
    const ids = new Set(doc.clips.map((c) => c.asset_id).filter(Boolean) as string[])
    return ids
  }, [doc.clips])

  useEffect(() => {
    for (const asset of library) {
      if (asset.kind !== "video" && asset.kind !== "image") continue
      if (stripRequested.current.has(asset.id)) continue
      stripRequested.current.add(asset.id)
      const job = asset.kind === "video" ? assetFrames(asset.url) : Promise.resolve(imageFrames(asset))
      void job
        .then((result) => {
          if (result.strip) setStrips((current) => ({ ...current, [asset.id]: result.strip }))
        })
        .catch(() => undefined)
    }
  }, [library])
  const hasAudioTimeline = useMemo(
    () => doc.clips.some((c) => c.track === "audio" || c.track === "music"),
    [doc.clips]
  )

  const visibleAssets = useMemo(() => {
    const query = search.trim().toLowerCase()
    return library.filter((asset) => {
      if (filter === "image" || filter === "video" || filter === "audio") {
        if (asset.kind !== filter) return false
      }
      if (filter === "added" && !(asset.id && usedAssetIds.has(asset.id))) return false
      if (query && !asset.name.toLowerCase().includes(query)) return false
      return true
    })
  }, [library, filter, search, usedAssetIds])

  const importedAssets = useMemo(
    () =>
      doc.assets.filter(
        (a) =>
          (sourceTab === "imported") &&
          (filter === "all" || filter === "added" || filter === "grouped" || a.kind === filter) &&
          (!search.trim() || a.name.toLowerCase().includes(search.trim().toLowerCase()))
      ),
    [doc.assets, filter, search, sourceTab]
  )
  const canvasTabAssets = useMemo(
    () =>
      canvasAssets.filter(
        (a) =>
          (filter === "all" || filter === "added" || filter === "grouped" || a.kind === filter) &&
          (!search.trim() || a.name.toLowerCase().includes(search.trim().toLowerCase()))
      ),
    [canvasAssets, filter, search]
  )

  async function importLocal() {
    const path = localPath.trim()
    if (!path) {
      message.warning("请输入本机文件或文件夹的绝对路径")
      return
    }
    setLocalBusy(true)
    try {
      const { importLocalMedia } = await import("./api")
      const result = await importLocalMedia(csrfToken, scopeProjectId, sequence, path, localRecursive)
      const known = new Set(docRef.current.assets.map((asset) => asset.url))
      const fresh = result.assets.filter((asset) => !known.has(asset.url))
      if (fresh.length)
        commit((current) => ({ ...current, assets: [...current.assets, ...fresh] }))
      if (result.skipped.length)
        message.warning(`已引用 ${fresh.length} 个，跳过 ${result.skipped.length} 个：${result.skipped[0].name}（${result.skipped[0].error}）`)
      else
        message.success(fresh.length ? `已引用 ${fresh.length} 个本机素材` : "这些素材已经在素材库里")
      setLocalOpen(false)
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setLocalBusy(false)
    }
  }

  async function runExport(quality: number) {
    setExportBusy(true)
    try {
      await startExport(quality)
      message.info("已加入导出队列，完成后可直接打开成片链接")
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setExportBusy(false)
    }
  }

  const selectedClip = doc.clips.find((c) => c.id === selected)

  function downloadJson(document: EditDocument = docRef.current) {
    downloadBlob(
      new Blob([JSON.stringify(document, null, 2)], { type: "application/json" }),
      `${document.name}.zly.json`
    )
  }

  async function addSubtitles() {
    if (subtitleBusy) return
    setSubtitleBusy(true)
    setTranscriptNote("")
    try {
      const transcript: MediaTranscript = await readTranscript(scopeProjectId, sequence)
      const cues: { start: number; text: string }[] = []
      for (const item of transcript.items || []) {
        if (item.status !== "succeeded") continue
        for (const span of item.spans || []) {
          for (const segment of item.segments || []) {
            const offset = (segment.start - span.in_point) / (span.speed || 1)
            const start = span.timeline_start + Math.max(0, offset)
            if (segment.end <= span.in_point) continue
            if (start >= span.timeline_start + span.timeline_duration) continue
            const text = segment.text.trim()
            if (!text) continue
            cues.push({ start: frame(start, doc.settings.fps), text: text.slice(0, 60) })
            if (cues.length >= 120) break
          }
          if (cues.length >= 120) break
        }
        if (cues.length >= 120) break
      }
      if (!cues.length) {
        setTranscriptNote("当前工程没有可用的音轨转写结果，请先在智能剪辑工作台生成转写。")
        return
      }
      commit((current) => {
        let next = current
        for (const cue of cues) {
          const clip = makeClip(next, undefined, cue.start, "text")
          Object.assign(clip, { text: cue.text, font_size: 56, y: 36 })
          next = { ...next, clips: [...next.clips, clip] }
        }
        return next
      })
      message.success(`已按转写生成 ${cues.length} 条字幕片段，可在片段属性中调整`)
    } catch (error) {
      setTranscriptNote(`字幕生成失败：${errorText(error)}`)
    } finally {
      setSubtitleBusy(false)
    }
  }

  const keyboardGuard = useCallback(
    (event: React.KeyboardEvent) => {
      if (
        (event.target as HTMLElement).closest(
          "button,input,textarea,[contenteditable=true],[role='button']:not(.se-clip),[role='switch'],[role='tab'],[role='combobox'],[role='menuitem'],.ant-select,.ant-slider,.ant-input-number"
        )
      )
        return
      if (event.code === "Space") {
        event.preventDefault()
        play(!playing)
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault()
        undo(event.shiftKey)
      } else if (event.key === "Delete" || event.key === "Backspace") {
        if (selected) {
          event.preventDefault()
          remove()
        }
      } else if (event.key === "Escape") {
        onClose()
      } else if (event.key.toLowerCase() === "s" && !event.ctrlKey && !event.metaKey) {
        event.preventDefault()
        split()
      }
    },
    [onClose, play, playing, remove, selected, split, undo]
  )

  const saveStatus = (
    <span className={`se-save-status${saveError ? " is-error" : ""}`} role="status">
      {saveState === "已保存" && !saveError && <CheckCircle2 size={15} aria-hidden="true" />}
      {saveState}
    </span>
  )

  const settingsBody = (
    <div className="se-studio-settings">
      <div className="se-property">
        <label>剪辑名称</label>
        <Input
          value={doc.name}
          maxLength={120}
          onChange={(event) => commit((current) => ({ ...current, name: event.target.value }))}
        />
      </div>
      <div className="se-property">
        <label>画面比例</label>
        <Select
          aria-label="画面比例"
          value={doc.settings.ratio}
          options={Object.keys(RATIOS).map((value) => ({ value, label: value }))}
          onChange={(ratio) => commit((current) => ({ ...current, settings: { ...current.settings, ratio } }))}
        />
      </div>
      <div className="se-property">
        <label>帧率</label>
        <Select
          aria-label="项目帧率"
          value={doc.settings.fps}
          options={[24, 25, 30, 60].map((value) => ({ value, label: `${value} fps` }))}
          onChange={(fps) =>
            commit((current) => ({
              ...current,
              settings: { ...current.settings, fps },
              clips: current.clips.map((c) => {
                const duration = Math.max(1 / fps, frame(c.start + c.duration, fps) - frame(c.start, fps))
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
              settings: { ...current.settings, background: color.toHexString() }
            }))
          }
        />
      </div>
    </div>
  )

  const exportMenu = {
    items: [
      { key: "1080", label: "导出成片 · 高清 1080P" },
      { key: "720", label: "导出成片 · 标准 720P" },
      { type: "divider" as const },
      { key: "json", label: "下载工程 JSON 备份" }
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === "json") downloadJson()
      else void runExport(Number(key))
    }
  }

  const busyJob = !!job && ["queued", "running"].includes(job.status)

  if (loading)
    return (
      <div className="se-studio" role="status" aria-busy="true" aria-label="正在打开时间线">
        <div className="se-studio-loading"><Spin /><span>正在打开时间线工程…</span></div>
      </div>
    )
  if (loadError)
    return (
      <div className="se-studio">
        <div className="se-studio-loading">
          <Alert
            type="error"
            showIcon
            title="时间线工程加载失败"
            description={loadError}
            action={<Button onClick={() => void reload()}>重新加载</Button>}
          />
        </div>
      </div>
    )

  return (
    <div
      ref={workspace}
      className={`se-studio${multitrack ? " is-multitrack" : " is-timeline"}`}
      tabIndex={0}
      aria-label={`${title}全屏编辑`}
      onKeyDown={keyboardGuard}
    >
      <header className="se-studio-header">
        <div className="se-studio-title">
          {multitrack ? <LayoutGrid size={15} /> : <Film size={15} />}
          <strong>{title}</strong>
          {saveStatus}
          {multitrack && (
            <Popover
              open={settingsOpen}
              onOpenChange={setSettingsOpen}
              trigger={["click"]}
              placement="bottomLeft"
              content={settingsBody}
              classNames={{ root: "canvas-popup" }}
            >
              <Button size="small" className="se-studio-ratio" aria-label="剪辑设置">{doc.settings.ratio}<ChevronDown size={11} /></Button>
            </Popover>
          )}
        </div>
        <div className="se-studio-actions">
          {busyJob && (
            <span className="se-studio-export-progress" role="status">
              <Progress size="small" percent={job.progress} status={job.status === "failed" ? "exception" : job.status === "completed" ? "success" : "active"} />
              {job.status === "completed" && job.result_url
                ? <Button size="small" type="primary" href={job.result_url} target="_blank" rel="noopener noreferrer" icon={<Download size={12} />}>打开成片</Button>
                : <span>{job.status === "queued" ? "排队中" : job.status === "running" ? `合成中 ${Math.round(job.progress)}%` : job.error_message || "导出失败"}</span>}
            </span>
          )}
          <Dropdown trigger={["click"]} menu={exportMenu}>
            <Button type="primary" loading={exportBusy} icon={<Download size={14} />}>导出<ChevronDown size={12} /></Button>
          </Dropdown>
          <Button onClick={onClose}>{multitrack ? "收起" : "关闭"}</Button>
          {!multitrack && <Button type="text" aria-label="关闭全屏编辑" icon={<X size={17} />} onClick={onClose} />}
        </div>
      </header>
      {saveError && (
        <Alert
          className="se-studio-alert"
          type="error"
          showIcon
          title={saveError}
          action={
            <div className="se-inline-actions">
              <Button size="small" onClick={() => downloadJson()}>下载草稿 JSON</Button>
              <Button size="small" onClick={() => void saveLatest().catch(() => undefined)}>重试保存</Button>
            </div>
          }
        />
      )}
      <div className="se-studio-body">
        <aside className={`se-studio-library${multitrack ? "" : " with-tabs"}`} aria-label={multitrack ? "资产库" : "素材"}>
          {multitrack ? (
            <>
              <div className="se-studio-library-head">
                <strong>资产库</strong>
                <Segmented
                  size="small"
                  aria-label="资产筛选"
                  value={filter}
                  onChange={(value) => setFilter(value as LibraryFilter)}
                  options={[
                    { value: "all", label: "全部" },
                    { value: "grouped", label: "分组" },
                    { value: "image", label: "图片" },
                    { value: "video", label: "视频" },
                    { value: "audio", label: "音频" },
                    { value: "added", label: "已添加" }
                  ]}
                />
              </div>
              <Input
                prefix={<Search size={13} />}
                aria-label="搜索资产"
                placeholder="搜索资产"
                allowClear
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              {filter === "grouped" ? (
                (["video", "image", "audio"] as const).map((kind) => {
                  const items = visibleAssets.filter((asset) => asset.kind === kind)
                  if (!items.length) return null
                  return (
                    <div key={kind} className="se-studio-group">
                      <h4>{kind === "video" ? "视频" : kind === "image" ? "图片" : "音频"}</h4>
                      <div className="se-asset-grid">
                        {items.map((asset) => (
                          <StudioAssetCard key={asset.id} asset={asset} fps={doc.settings.fps} used={usedAssetIds.has(asset.id)} busy={importingAsset} onAdd={() => void addFromPool(asset)} />
                        ))}
                      </div>
                    </div>
                  )
                })
              ) : (
                <div className="se-asset-grid">
                  {visibleAssets.map((asset) => (
                    <StudioAssetCard key={asset.id} asset={asset} fps={doc.settings.fps} used={usedAssetIds.has(asset.id)} busy={importingAsset} onAdd={() => void addFromPool(asset)} />
                  ))}
                </div>
              )}
              {!visibleAssets.length && (
                <div className="se-media-empty">
                  <FolderOpen size={26} strokeWidth={1.3} />
                  <strong>资产库还没有素材</strong>
                  <p>画布上的图片、视频与音频会自动出现在这里，也可以上传或引用本机素材。</p>
                </div>
              )}
            </>
          ) : (
            <>
              <Segmented
                block
                aria-label="素材来源"
                value={sourceTab}
                onChange={(value) => setSourceTab(value as "imported" | "canvas")}
                options={[
                  { value: "imported", label: "已导入资产" },
                  { value: "canvas", label: "画布资产" }
                ]}
              />
              <div className="se-studio-library-head">
                <Segmented
                  size="small"
                  aria-label="素材类型"
                  value={filter === "all" || filter === "image" || filter === "video" || filter === "audio" ? filter : "all"}
                  onChange={(value) => setFilter(value as LibraryFilter)}
                  options={[
                    { value: "all", label: "全部" },
                    { value: "image", label: "图片" },
                    { value: "video", label: "视频" },
                    { value: "audio", label: "音频" }
                  ]}
                />
                <Tooltip title="上传素材到媒体存储">
                  <Button size="small" icon={<Upload size={13} />} loading={uploading} onClick={() => mediaInput.current?.click()}>导入</Button>
                </Tooltip>
              </div>
              <div className="se-asset-grid">
                {(sourceTab === "imported" ? importedAssets : canvasTabAssets).map((asset) => (
                  <StudioAssetCard
                    key={asset.id}
                    asset={asset}
                    fps={doc.settings.fps}
                    used={doc.assets.some((item) => item.id === asset.id)}
                    busy={importingAsset}
                    onAdd={() => void addFromPool(asset)}
                    onThumb={captureThumbnail}
                  />
                ))}
              </div>
              {!(sourceTab === "imported" ? importedAssets : canvasTabAssets).length && (
                <div className="se-media-empty">
                  {sourceTab === "imported" ? <FolderOpen size={26} strokeWidth={1.3} /> : <Film size={26} strokeWidth={1.3} />}
                  <strong>{sourceTab === "imported" ? "将文件拖至此处添加" : "画布上还没有媒体素材"}</strong>
                  <p>
                    {sourceTab === "imported"
                      ? "上传或引用本机素材，双击加入时间线。"
                      : "把图片、视频或音频节点放到画布上，它们会自动出现在这里。"}
                  </p>
                  {sourceTab === "imported" && (
                    <Button icon={<HardDrive size={13} />} onClick={() => setLocalOpen(true)}>引用本机素材</Button>
                  )}
                </div>
              )}
            </>
          )}
        </aside>
        <Preview doc={doc} time={time} playing={playing} onTime={seek} onPlay={play} onProbe={probeAsset} />
        {multitrack && inspectorOpen && (
          <Inspector doc={doc} clip={selectedClip} thumbnails={thumbnails} onPatch={patch} heading="片段设置" onClose={() => setInspectorOpen(false)} />
        )}
      </div>
      <Timeline
        doc={doc}
        thumbnails={thumbnails}
        strips={strips}
        time={time}
        selected={selected}
        canUndo={ctrl.canUndo}
        canRedo={ctrl.canRedo}
        onSelect={(id) => { select(id); setInspectorOpen(true) }}
        onTime={seek}
        onUndo={() => undo()}
        onRedo={() => undo(true)}
        onSplit={split}
        onDelete={remove}
        onCopy={copy}
        onReorder={(direction) =>
          commit((current) => {
            const clip = current.clips.find((c) => c.id === selected)
            if (!clip) return current
            const ordered = laneClips(current, clip.track)
            const index = ordered.findIndex((c) => c.id === selected)
            const other = index + direction
            if (!ordered[other]) return current
            ;[ordered[index], ordered[other]] = [ordered[other], ordered[index]]
            let cursor = 0
            const moved = new Map(ordered.map((c) => {
              const value = { ...c, start: cursor }
              cursor = frame(cursor + c.duration, current.settings.fps)
              return [c.id, value]
            }))
            return { ...current, clips: current.clips.map((c) => moved.get(c.id) || c) }
          })
        }
        onPack={() => commit((current) => {
          let cursor = 0
          const moved = new Map(laneClips(current, "video").map((c) => {
            const value = { ...c, start: cursor }
            cursor = frame(cursor + c.duration, current.settings.fps)
            return [c.id, value]
          }))
          return { ...current, clips: current.clips.map((c) => moved.get(c.id) || c) }
        })}
        onDrag={dragClip}
        onDropAsset={(id, at, track) => {
          const asset = library.find((a) => a.id === id)
          if (asset) void addFromPool(asset, at, track)
        }}
        extraToolbar={multitrack && allowSubtitle ? (
          <>
            <Tooltip title="按音轨转写结果生成字幕片段">
              <Button
                type="text"
                aria-label="添加字幕"
                icon={<Type size={15} />}
                loading={subtitleBusy}
                disabled={!hasAudioTimeline}
                onClick={() => void addSubtitles()}
              >添加字幕</Button>
            </Tooltip>
          </>
        ) : null}
      />
      {transcriptNote && <Alert className="se-studio-alert" type="warning" showIcon title={transcriptNote} closable onClose={() => setTranscriptNote("")} />}
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
    </div>
  )
}

/** 资产卡片：双击 / 拖拽加入时间线，与 SmartEditPane 素材面板同一交互语言。 */
function StudioAssetCard({
  asset,
  fps,
  used,
  busy,
  onAdd,
  onThumb
}: {
  asset: EditAsset
  fps: number
  used: boolean
  busy: boolean
  onAdd: () => void
  onThumb?: (id: string, dataUrl: string) => void
}) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [asset.url])
  const Icon = asset.kind === "audio" ? Music2 : asset.kind === "video" ? Film : ImageIcon
  return (
    <div
      className="se-asset"
      draggable
      onDragStart={(event) => event.dataTransfer.setData("application/x-zly-asset", asset.id)}
      onDoubleClick={onAdd}
      role="button"
      tabIndex={0}
      aria-label={`添加素材：${asset.name}`}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.code === "Space") {
          event.preventDefault()
          onAdd()
        }
      }}
    >
      <div className="se-asset-thumbnail">
        {asset.thumbnail || asset.kind === "image" ? (
          <img src={asset.thumbnail || asset.url} alt="" loading="lazy" onError={() => setFailed(true)} />
        ) : asset.kind === "video" ? (
          <video
            src={asset.url}
            muted
            preload="metadata"
            crossOrigin="anonymous"
            onError={(event) => {
              const media = event.currentTarget
              if (media.hasAttribute("crossorigin")) {
                media.removeAttribute("crossorigin")
                media.load()
              }
            }}
            onLoadedMetadata={(event) => {
              const media = event.currentTarget
              if (Number.isFinite(media.duration) && media.dataset.thumbAttempt === undefined) {
                media.dataset.thumbAttempt = "0"
                media.currentTime = Math.max(0.01, Math.min(1, media.duration * 0.15))
              }
            }}
            onSeeked={(event) => {
              const media = event.currentTarget
              try {
                const canvas = document.createElement("canvas")
                canvas.width = 192
                canvas.height = Math.round((192 * media.videoHeight) / media.videoWidth)
                const paint = canvas.getContext("2d")
                if (!paint) throw new Error("Canvas unavailable")
                paint.drawImage(media, 0, 0, canvas.width, canvas.height)
                const pixels = paint.getImageData(0, 0, canvas.width, canvas.height).data
                let light = 0
                let samples = 0
                for (let i = 0; i < pixels.length; i += 64) {
                  light += (pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3
                  samples++
                }
                if (light / samples < 8) {
                  const attempt = Number(media.dataset.thumbAttempt || 0) + 1
                  if (attempt < 3) {
                    media.dataset.thumbAttempt = String(attempt)
                    media.currentTime = media.duration * (attempt === 1 ? 0.35 : 0.65)
                    return
                  }
                  throw new Error("No representative frame")
                }
                onThumb?.(asset.id, canvas.toDataURL("image/jpeg", 0.72))
              } catch {
                /* 拿不到代表帧时保留视频默认首帧 */
              }
            }}
          />
        ) : (
          <Icon size={24} />
        )}
        <span className="se-asset-duration">
          {asset.kind === "image" ? <ImageIcon size={12} /> : <span>{timecode(asset.duration, fps).slice(0, 5)}</span>}
        </span>
        {used && <span className="se-asset-used">已添加</span>}
        <Button
          type="primary"
          size="small"
          loading={busy}
          aria-label={`将${asset.name}加入时间线`}
          icon={<Plus size={12} />}
          onClick={(event) => {
            event.stopPropagation()
            onAdd()
          }}
        />
      </div>
      <span className="se-asset-name" title={asset.local_path ? `${asset.name}\n${asset.local_path}` : asset.name}>{asset.name}</span>
      {failed && <span className="se-help">缩略图无法加载</span>}
    </div>
  )
}
