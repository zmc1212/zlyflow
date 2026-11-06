import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Alert, Button, Collapse, Drawer, Dropdown, Empty, Form, Input, Modal, Spin, Tabs, Tag, Tooltip, Upload, message } from "antd"
import { ArrowRight, BookOpen, Copy, Download, Ellipsis, Eye, FilePlus2, FileText, GripVertical, Info, Pencil, Plus, Save, Trash2, Upload as UploadIcon } from "lucide-react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { consolidateScript, createDocument, createScriptEpisode, deleteScriptEpisode, director2ErrorDetail, enqueueAssetExtraction, listDocuments, listJobs, updateDocument, type Director2Document } from "../api"
import { episodeDraftText, episodeReadingText, primaryScript, scriptBodyEpisodes, scriptBodyText, scriptDownloadText, scriptEpisodes, scriptOutlines, storySettingFields, type ScriptEpisode } from "../script-document"
import { useDirectorAssistant } from "../assistant/DirectorAssistant"
import {
  applyAssetExtractionJobSnapshot,
  applyAssetExtractionStreamEvent,
  assetExtractionDescription,
  emptyAssetExtractionLiveState,
  type AssetExtractionLiveState,
} from "../asset-extraction-live"
import { director2ProjectPath } from "../paths"
import { extractFiles, getCapabilities } from "../script-diagnosis/api"
import type { Capabilities } from "../script-diagnosis/model"
import { streamH3PromptJobEvents } from "../workshop-prompt-stream"
import ContentLibraryPane from "./ContentLibraryPane"
import "./script-workspace.css"

const SCENE_EXAMPLES = [
  { key: "office", label: "办公室" },
  { key: "banquet", label: "晚宴厅" },
  { key: "apartment", label: "出租屋" },
]
const SHOT_EXAMPLES = [["wide", "全景 · 交代空间"], ["medium", "中景 · 人物对话"], ["close", "特写 · 场景细节"]]

export default function ScriptWorkspace({ csrfToken, projectId, onChanged }: { csrfToken: string; projectId: string; onChanged: () => void }) {
  const assistant = useDirectorAssistant()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [documents, setDocuments] = useState<Director2Document[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [details, setDetails] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [importing, setImporting] = useState(false)
  const [readingFile, setReadingFile] = useState(false)
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [benefitsOpen, setBenefitsOpen] = useState(false)
  const [sceneExample, setSceneExample] = useState("office")
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const [saving, setSaving] = useState(false)
  const [transferring, setTransferring] = useState(false)
  const [extraction, setExtraction] = useState<ReturnType<typeof emptyAssetExtractionLiveState> | null>(null)
  const [clock, setClock] = useState(() => Date.now())
  const [merging, setMerging] = useState(false)
  const [episodeBusy, setEpisodeBusy] = useState(false)
  const [expandedEpisodes, setExpandedEpisodes] = useState<string[]>([])
  const [form] = Form.useForm<{ filename: string; raw_text: string }>()
  const [modal, modalContext] = Modal.useModal()
  const version = useRef(0)
  const editorBase = useRef<{ id: string; text: string; draft: string; episodeNum?: number } | null>(null)
  const extractionRef = useRef<AssetExtractionLiveState | null>(null)
  const finishedJobRef = useRef("")
  const notifiedErrorRef = useRef("")
  const liveDocRef = useRef<string | null>(null)
  const docIdRef = useRef("")
  const onChangedRef = useRef(onChanged)
  onChangedRef.current = onChanged
  const doc = primaryScript(documents)
  docIdRef.current = doc?.id || ""
  const section = ["setting", "outline", "body"].includes(params.get("section") || "") ? params.get("section")! : "body"
  const analysis = doc?.analysis || {}
  const episodes = scriptEpisodes(doc?.analysis || null)
  const outlines = scriptOutlines(doc?.analysis || null)
  const bodyEpisodes = scriptBodyEpisodes(doc?.analysis || null)
  const lockedNumbers = new Set(doc?.locked_episode_nums || [])
  const changes = analysis.script_changes as { episode_nums?: number[]; section?: string; kind?: string } | undefined
  const changedEpisodes = changes?.episode_nums || []
  const pendingNumbers = episodes.filter(ep => !lockedNumbers.has(ep.episode_num)).map(ep => ep.episode_num)
  const planning = doc?.status === "planning" || !!doc?.shot_plan_job_id
  const dirty = editing && draft !== (editorBase.current?.draft ?? doc?.raw_text ?? "")
  const draftKey = (id: string) => `director-script-draft-v1:${projectId}:${id}`
  const outline = outlines.map(ep => `### 第 ${ep.episode_num} 集${ep.title ? ` · ${ep.title}` : ""}\n\n${ep.summary || "还没有本集大纲，可与助手一起完善。"}`).join("\n\n")
  const body = doc ? scriptBodyText(doc) : ""
  const assetExtractionRequired = !!doc?.asset_extraction_required
  const extractionJobId = extraction?.jobId || doc?.asset_extraction_job_id || ""
  const extractionWorking = !!extraction?.working
  const stageLabel = extractionWorking ? "正在拆解资产…" : pendingNumbers.length ? `${pendingNumbers.length} 集剧本拆解资产` : assetExtractionRequired ? "补充拆解资产" : "查看制作资产"

  function clearDraft() { if (doc) try { localStorage.removeItem(draftKey(doc.id)) } catch { /* Optional recovery. */ } }
  function discardEditing() { clearDraft(); setEditing(false); editorBase.current = null }
  function lockReason(number: number) { return doc?.episode_lock_reasons?.[String(number)] || "资产已拆解，本集剧本不可修改" }
  function beginEditing(episode?: ScriptEpisode) {
    if (!doc || (episode ? lockedNumbers.has(episode.episode_num) : lockedNumbers.size > 0)) return
    const text = episode ? episodeDraftText(episode) : doc.raw_text || ""
    editorBase.current = { id: doc.id, text: doc.raw_text || "", draft: text, episodeNum: episode?.episode_num }
    setDraft(text); setEditing(true)
  }
  useEffect(() => { setExpandedEpisodes([]) }, [doc?.id])

  const refresh = useCallback(async (silent = false) => {
    const current = ++version.current
    if (!silent) setLoading(true)
    try {
      const next = await listDocuments(projectId)
      if (current === version.current) { setDocuments(next); setError("") }
    } catch (e) { if (current === version.current) setError(director2ErrorDetail(e, "剧本加载失败")) }
    finally { if (current === version.current) setLoading(false) }
  }, [projectId])
  useEffect(() => { void refresh(); return () => { version.current++ } }, [refresh])

  const updateExtraction = useCallback((next: AssetExtractionLiveState | null) => {
    extractionRef.current = next
    setExtraction(next)
  }, [])
  const finishExtraction = useCallback(async (jobId: string, notice: string) => {
    if (finishedJobRef.current === jobId) return
    finishedJobRef.current = jobId
    updateExtraction(null)
    await refresh(true)
    onChangedRef.current()
    message.success(notice)
    setBenefitsOpen(false)
    const documentId = docIdRef.current
    if (documentId) navigate(`${director2ProjectPath(projectId, "assets")}?doc=${encodeURIComponent(documentId)}`)
  }, [navigate, projectId, refresh, updateExtraction])

  useEffect(() => {
    if (liveDocRef.current === (doc?.id ?? null)) return
    liveDocRef.current = doc?.id ?? null
    finishedJobRef.current = ""
    notifiedErrorRef.current = ""
    updateExtraction(null)
  }, [doc?.id, updateExtraction])

  useEffect(() => {
    if (!extractionWorking) return undefined
    const timer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [extractionWorking])

  useEffect(() => {
    if (!extractionJobId) return undefined
    const current = extractionRef.current
    if (!current || current.jobId !== extractionJobId) updateExtraction(emptyAssetExtractionLiveState(extractionJobId))
    const controller = new AbortController()
    let active = true
    void streamH3PromptJobEvents(projectId, extractionJobId, event => {
      if (!active) return
      const state = extractionRef.current
      if (!state || state.jobId !== extractionJobId) return
      const next = applyAssetExtractionStreamEvent(state, event)
      extractionRef.current = next
      setExtraction(next)
      if (event.event === "done") void finishExtraction(extractionJobId, next.message)
      if (event.event === "error") {
        if (notifiedErrorRef.current !== extractionJobId) {
          notifiedErrorRef.current = extractionJobId
          message.error(next.error || "资产拆解未完成")
        }
        void refresh(true)
      }
    }, { signal: controller.signal, shouldContinue: () => active })
    return () => { active = false; controller.abort() }
  }, [extractionJobId, projectId, finishExtraction, refresh, updateExtraction])

  useEffect(() => {
    if (!extractionJobId) return undefined
    let active = true
    void listJobs(projectId).then(jobs => {
      if (!active) return
      const job = jobs.find(item => item.id === extractionJobId)
      const state = extractionRef.current
      if (!job || !state || state.jobId !== extractionJobId) return
      const startedAt = Date.parse(job.created_at || "")
      if (!Number.isFinite(startedAt)) return
      const next = { ...state, startedAt }
      extractionRef.current = next
      setExtraction(next)
    }).catch(() => { /* 恢复任务时计时从本页打开开始即可 */ })
    return () => { active = false }
  }, [extractionJobId, projectId])

  useEffect(() => {
    if (!extractionWorking || !extractionJobId) return undefined
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const jobs = await listJobs(projectId)
          const job = jobs.find(item => item.id === extractionJobId)
          const state = extractionRef.current
          if (!job || !state || state.jobId !== extractionJobId) return
          const next = applyAssetExtractionJobSnapshot(state, job)
          extractionRef.current = next
          setExtraction(next)
          if (job.status === "completed" || job.status === "succeeded") {
            void finishExtraction(job.id, next.message)
          } else if (job.status === "failed" && notifiedErrorRef.current !== job.id) {
            notifiedErrorRef.current = job.id
            message.error(next.error || "资产拆解未完成")
          }
        } catch { /* SSE 仍在推送时，轮询只作兜底 */ }
      })()
    }, 4000)
    return () => window.clearInterval(timer)
  }, [extractionWorking, extractionJobId, projectId, finishExtraction])

  useEffect(() => {
    const changed = (event: Event) => { if ((event as CustomEvent).detail?.projectId === projectId) void refresh(true) }
    window.addEventListener("director-assistant-project-updated", changed)
    return () => window.removeEventListener("director-assistant-project-updated", changed)
  }, [projectId, refresh])
  useEffect(() => {
    if (!importOpen || capabilities) return
    let alive = true
    getCapabilities().then(value => { if (alive) setCapabilities(value) }).catch(() => { /* Plain text remains available. */ })
    return () => { alive = false }
  }, [importOpen, capabilities])
  useEffect(() => {
    if (!doc) return
    try {
      const cached = JSON.parse(localStorage.getItem(draftKey(doc.id)) || "null")
      if (cached && typeof cached.text === "string" && typeof cached.base === "string" && cached.text !== (cached.original ?? cached.base)) {
        const locked = cached.episodeNum ? doc.locked_episode_nums?.includes(Number(cached.episodeNum)) : !!doc.locked_episode_nums?.length
        if (locked) return
        editorBase.current = { id: doc.id, text: cached.base, draft: cached.original ?? cached.base, episodeNum: cached.episodeNum }
        setDraft(cached.text); setEditing(true)
        message.info("已恢复上次未保存的剧本修改")
      }
    } catch { /* Local recovery does not block the server document. */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.id])
  useEffect(() => {
    if (!doc || !editing || editorBase.current?.id !== doc.id) return
    try { localStorage.setItem(draftKey(doc.id), JSON.stringify({ text: draft, base: editorBase.current.text, original: editorBase.current.draft, episodeNum: editorBase.current.episodeNum })) } catch { /* beforeunload still warns. */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, editing, doc?.id])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = "" }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [dirty])

  function choose(documentId: string, nextSection = section) {
    const run = () => {
      discardEditing()
      setParams(current => { const next = new URLSearchParams(current); next.set("doc", documentId); next.set("section", nextSection); return next }, { replace: true })
    }
    if (dirty) modal.confirm({ title: "放弃未保存的修改？", okText: "放弃修改", cancelText: "继续编辑", onOk: run })
    else run()
  }
  async function save() {
    if (!doc || saving || !draft.trim()) return
    setSaving(true); setError("")
    try {
      const next = await updateDocument(csrfToken, projectId, doc.id, { raw_text: draft, base_raw_text: editorBase.current?.text ?? doc.raw_text ?? "", episode_num: editorBase.current?.episodeNum })
      clearDraft(); setDocuments(current => current.map(item => item.id === next.id ? next : item)); setEditing(false); editorBase.current = null
      await refresh(true); onChanged(); message.success("剧本已保存，其他集与已有制作资产保留")
    } catch (e) { setError(director2ErrorDetail(e, "保存失败，修改已保留")) }
    finally { setSaving(false) }
  }
  async function readFile(file: File) {
    setReadingFile(true)
    try {
      const limits = capabilities || await getCapabilities()
      const extension = file.name.split(".").pop()?.toLowerCase() || ""
      if (file.size > limits.max_file_bytes) throw new Error(`文件超过 ${Math.floor(limits.max_file_bytes / 1024 / 1024)}MB 限制`)
      const plainText = ["md", "markdown", "txt"].includes(extension)
      const extracted = plainText ? await file.text() : await extractFiles(csrfToken, [file]).then(result => {
        const source = result.sources[0]
        if (!source || source.error || !source.text) throw new Error(source?.error || "文件未提取到正文")
        return source.text
      })
      if (extracted.length > 500000) throw new Error("正文超过 500000 字符，请按分集拆分后导入")
      form.setFieldsValue({ filename: file.name.replace(/\.[^.]+$/, ""), raw_text: extracted })
    } catch (e) { message.error(director2ErrorDetail(e, "文件读取失败，已有正文保留")) }
    finally { setReadingFile(false) }
  }
  async function importScript(values: { filename: string; raw_text: string }) {
    setImporting(true)
    try {
      const existingSource = documents.find(item => item.id !== doc?.id && item.raw_text === values.raw_text)
      const next = existingSource || await createDocument(csrfToken, projectId, { filename: values.filename || "导入分集", raw_text: values.raw_text, input_mode: "file" })
      if (doc) await consolidateScript(csrfToken, projectId, doc.id, [next.id])
      await refresh(true); setImportOpen(false); choose(doc?.id || next.id, "body"); onChanged(); form.resetFields()
    } catch (e) { await refresh(true); message.error(director2ErrorDetail(e, "导入未合并，来源稿与正文已保留")) }
    finally { setImporting(false) }
  }
  async function mergeLegacyScripts() {
    if (!doc || dirty || merging) return
    setMerging(true); setError("")
    try {
      await consolidateScript(csrfToken, projectId, doc.id, documents.filter(item => item.id !== doc.id).map(item => item.id))
      await refresh(true); choose(doc.id, "body"); onChanged(); message.success("独立分集稿已并入当前剧本，来源原文与已有成片保留")
    } catch (e) { setError(director2ErrorDetail(e, "合并失败；原稿均已保留")); await refresh(true) }
    finally { setMerging(false) }
  }
  async function newEpisode() {
    if (!doc || episodeBusy || editing || planning) return
    setEpisodeBusy(true); setError("")
    try {
      const result = await createScriptEpisode(csrfToken, projectId, doc.id, doc.raw_text || "")
      await refresh(true); choose(doc.id, "body"); setExpandedEpisodes([String(result.episode_num)]); onChanged()
      message.success(`已新建第 ${result.episode_num} 集，可填写正文或与助手一起创作`)
    } catch (e) { setError(director2ErrorDetail(e, "新建分集失败")) }
    finally { setEpisodeBusy(false) }
  }
  function removeEpisode(ep: ScriptEpisode) {
    if (!doc || lockedNumbers.has(ep.episode_num) || episodeBusy || editing) return
    modal.confirm({
      title: `删除第 ${ep.episode_num} 集？`, content: "将从当前剧本中移除本集，其他分集保持不变。", okText: "删除本集", cancelText: "取消", okButtonProps: { danger: true },
      onOk: async () => {
        setEpisodeBusy(true)
        try {
          await deleteScriptEpisode(csrfToken, projectId, doc.id, ep.episode_num, doc.raw_text || "")
          await refresh(true); onChanged(); message.success(`已删除第 ${ep.episode_num} 集`)
        } catch (e) { message.error(director2ErrorDetail(e, "删除失败，原文已保留")); throw e }
        finally { setEpisodeBusy(false) }
      },
    })
  }
  function downloadScript() {
    if (!doc) return
    const url = URL.createObjectURL(new Blob([scriptDownloadText(doc)], { type: "text/markdown;charset=utf-8" }))
    const link = document.createElement("a")
    link.href = url; link.download = `${doc.filename.replace(/[/\\:*?"<>|]/g, "_") || "剧本"}.md`
    link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  async function nextStage() {
    if (!doc || dirty || transferring || extractionWorking) return
    if (!pendingNumbers.length && !assetExtractionRequired) { navigate(`${director2ProjectPath(projectId, "assets")}?doc=${encodeURIComponent(doc.id)}`); return }
    setTransferring(true); setError("")
    try {
      const result = await enqueueAssetExtraction(csrfToken, projectId, doc.id)
      const seeded = emptyAssetExtractionLiveState(result.job_id)
      if (result.duplicate) seeded.message = "已有拆解任务正在进行，正在同步进度"
      finishedJobRef.current = ""
      notifiedErrorRef.current = ""
      updateExtraction(seeded)
      setBenefitsOpen(false)
      void refresh(true)
    } catch (e) { setError(director2ErrorDetail(e, "资产拆解任务启动失败，可重试")) }
    finally { setTransferring(false) }
  }

  const moreMenu = { items: [
    { key: "upload", label: "上传文件·解析新集", icon: <UploadIcon size={14}/>, disabled: editing || planning || episodeBusy },
    { key: "new", label: "新建一集", icon: <Plus size={14}/>, disabled: !doc || editing || planning || episodeBusy },
    { key: "download", label: "下载剧本", icon: <Download size={14}/>, disabled: !doc },
  ], onClick: ({ key }: { key: string }) => { if (key === "upload") setImportOpen(true); else if (key === "new") void newEpisode(); else downloadScript() } }
  const notice = changes?.kind === "delete" ? `第 ${changedEpisodes.join("、")} 集已移除，其他分集保留` : changes?.section === "outline" ? `第 ${changedEpisodes.join("、")} 集大纲已更新，请核对对应集正文` : `第 ${changedEpisodes.join("、")} 集剧情已更新，可核对大纲并补充制作资产`

  return <div className="script-studio">
    <aside className="script-directory" aria-label="剧本目录">
      <header><span>目录</span><Button type="text" size="small" aria-label="上传文件解析新集" icon={<Plus size={14}/>} disabled={editing || planning || episodeBusy} onClick={() => setImportOpen(true)}/></header>
      <nav><div className="script-directory-group">
        <Button type="text" className="is-current" icon={<FileText size={14}/>} onClick={() => doc && choose(doc.id)}>剧本</Button>
        <div className="script-directory-sections">{[["setting", "故事设定"], ["outline", "分集大纲"], ["body", "剧本正文"]].map(([key, label]) => <Button key={key} type="text" aria-current={section === key ? "page" : undefined} className={section === key ? "is-current" : ""} onClick={() => doc && choose(doc.id, key)}>{label}</Button>)}</div>
      </div></nav>
      <Button type="text" className="script-directory-import" icon={<FilePlus2 size={15}/>} disabled={editing || planning || episodeBusy} onClick={() => setImportOpen(true)}>{doc ? "导入分集" : "导入剧本"}</Button>
    </aside>
    <main className="script-document-workspace">
      <header className="script-document-heading">
        <div><h1>剧本</h1><span>{doc ? `共 ${outlines.length} 集 · 正文 ${Array.from(doc.raw_text || "").length} 字 · ${editing ? dirty ? "有未保存修改" : "编辑中" : "已保存"}` : "从故事想法开始"}</span></div>
        <div>{doc && <>
          <Tooltip title="复制剧本"><Button type="text" aria-label="复制剧本" icon={<Copy size={15}/>} onClick={() => void navigator.clipboard.writeText(scriptDownloadText(doc)).then(() => message.success("已复制剧本")).catch(() => message.error("复制失败，请手动复制"))}/></Tooltip>
          {section === "body" && !lockedNumbers.size && <Tooltip title="编辑剧本全文"><Button type="text" aria-label="编辑剧本全文" icon={<Pencil size={15}/>} disabled={planning || saving || editing} onClick={() => beginEditing()}/></Tooltip>}
        </>}</div>
      </header>
      <Tabs className="script-section-tabs" activeKey={section} onChange={value => doc && choose(doc.id, value)} items={[["setting", "故事设定"], ["outline", "分集大纲"], ["body", "剧本正文"]].map(([key, label]) => ({ key, label }))} tabBarExtraContent={section === "body" ? <Dropdown menu={moreMenu} trigger={["click"]}><Button type="text" className="script-more-button" aria-label="剧本更多操作" icon={<Ellipsis size={17}/>} loading={episodeBusy}/></Dropdown> : undefined}/>
      {error && <Alert type="error" showIcon title={error} action={<Button size="small" disabled={dirty || saving} onClick={() => void refresh()}>重新加载</Button>}/>}
      {planning && <Alert type="info" showIcon title="镜头规划正在进行，完成后可继续编辑"/>}
      {documents.length > 1 && <Alert type="info" showIcon title={`检测到 ${documents.length - 1} 份历史独立分集稿，可并入当前剧本`} action={<Button size="small" loading={merging} disabled={dirty || planning} onClick={() => void mergeLegacyScripts()}>合并分集</Button>}/>}
      {!!changedEpisodes.length && <Alert type="info" showIcon title={notice}/>}
      {extraction && <Alert
        className="script-extraction-progress"
        type={extraction.error ? "error" : "info"}
        showIcon
        icon={extractionWorking ? <Spin size="small"/> : undefined}
        title={extraction.error || extraction.message || "正在拆解资产"}
        description={assetExtractionDescription(extraction, clock)}
        closable={!extractionWorking}
        onClose={() => updateExtraction(null)}
        action={extraction.error ? <Button size="small" disabled={dirty || planning} onClick={() => void nextStage()}>重试</Button> : undefined}
      />}
      <div className="script-document-scroll"><Spin spinning={loading && Boolean(doc)}>
        {loading && !doc ? <div className="script-loading" role="status" aria-busy="true" aria-label="正在加载剧本"><span className="studio-skeleton-bar script-loading-title" style={{ width: "32%" }}/><span className="studio-skeleton-bar" style={{ width: "96%" }}/><span className="studio-skeleton-bar" style={{ width: "88%" }}/><span className="studio-skeleton-bar" style={{ width: "92%" }}/><span className="studio-skeleton-bar" style={{ width: "64%" }}/><span className="studio-skeleton-bar" style={{ width: "90%" }}/><span className="studio-skeleton-bar" style={{ width: "78%" }}/></div>
          : !doc ? <div className="script-empty"><BookOpen size={36}/><h2>你的故事，从这里开始</h2><p>与右侧助手完善想法，采纳后剧本会出现在这里。<br/>也可以直接导入已有正文。</p><Button onClick={() => setImportOpen(true)}>导入剧本</Button><Button type="text" onClick={() => assistant.prompt("帮我创作一部短剧，先和我确认故事方向。")}>打开短剧助手</Button></div>
          : editing ? <div className="script-editing"><p>{editorBase.current?.episodeNum ? `正在编辑第 ${editorBase.current.episodeNum} 集，其他集保持原文。请保留本集标题和编号。` : "正在编辑剧本全文。"}</p><Input.TextArea aria-label="编辑剧本正文" value={draft} onChange={event => setDraft(event.target.value)} disabled={saving} autoSize={{ minRows: 18 }} maxLength={500000}/></div>
            : section === "setting" ? <Form layout="vertical" component="div" className="script-setting-form" aria-label="只读故事设定">{storySettingFields(doc).map(field => <Form.Item key={field.key} label={field.label} className={field.wide ? "script-setting-wide" : undefined}>{field.multiline ? <Input.TextArea aria-label={field.label} value={field.value} readOnly variant="filled" autoSize={{ minRows: field.key === "synopsis" ? 6 : 3, maxRows: field.key === "synopsis" ? 16 : 8 }}/>: <Input aria-label={field.label} value={field.value} readOnly variant="filled"/>}</Form.Item>)}</Form>
              : section === "body" && outlines.length && (episodes.some(ep => ep.body?.trim()) || !body.trim()) ? <div className="script-episode-list">
                <header><h2>共 {outlines.length} 集</h2><Button type="text" size="small" onClick={() => setExpandedEpisodes(expandedEpisodes.length ? [] : outlines.map(ep => String(ep.episode_num)))}>{expandedEpisodes.length ? "收起全部" : "展开全部"}</Button><Button type="text" size="small" icon={<Plus size={14}/>} onClick={() => assistant.prompt(`请承接当前剧本结尾，续写第 ${Math.max(...outlines.map(ep => ep.episode_num)) + 1} 集，先确认续写方向和范围。`)}>续写下一集</Button></header>
                <Collapse ghost activeKey={expandedEpisodes} onChange={keys => setExpandedEpisodes(Array.isArray(keys) ? keys : [keys])} items={bodyEpisodes.map(ep => {
                  const locked = lockedNumbers.has(ep.episode_num)
                  return { key: String(ep.episode_num),
                    label: <span className="script-episode-title">
                      {!locked && <span onClick={event => event.stopPropagation()}><Dropdown trigger={["click"]} menu={{ items: [{ key: "delete", label: "删除本集", danger: true, icon: <Trash2 size={14}/>, disabled: editing || episodeBusy }], onClick: () => removeEpisode(ep) }}><Button type="text" className="script-episode-more" aria-label={`第${ep.episode_num}集操作`} icon={<GripVertical size={15}/>} /></Dropdown></span>}
                      <span>{ep.episode_num}. {ep.title || "未命名"}</span>
                      {locked ? <Tooltip title={lockReason(ep.episode_num)} trigger={["hover", "focus"]}><Button type="text" size="small" className="script-episode-lock" aria-label={lockReason(ep.episode_num)} icon={<Info size={13}/>} onClick={event => event.stopPropagation()}/></Tooltip> : <Tag bordered={false}>{ep.body ? "待生成" : "正文待创作"}</Tag>}
                    </span>,
                    extra: !locked && ep.body && expandedEpisodes.includes(String(ep.episode_num)) ? <Button type="text" size="small" aria-label={`编辑第${ep.episode_num}集`} icon={<Pencil size={13}/>} disabled={planning || saving || editing} onClick={event => { event.stopPropagation(); beginEditing(ep) }}>编辑本集</Button> : null,
                    children: ep.body ? <article className="script-reading"><Markdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={["img"]}>{episodeReadingText(ep)}</Markdown></article> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本集正文尚未填写"><Button onClick={() => beginEditing(ep)}>手动填写正文</Button><Button type="text" onClick={() => assistant.prompt(`请根据当前第 ${ep.episode_num} 集大纲，只生成第 ${ep.episode_num} 集完整正文，使用「# 第${ep.episode_num}集：标题」，保留其他分集原文。`)}>与助手一起创作</Button></Empty>,
                  }
                })}/>
              </div>
                : ((section === "outline" && outline) || (section === "body" && body)) ? <article className="script-reading"><Markdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={["img"]}>{section === "outline" ? outline : body}</Markdown></article>
                  : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={section === "outline" ? "还没有分集大纲" : "还没有分集正文"}><Button onClick={() => section === "body" ? void newEpisode() : assistant.prompt("请根据当前剧本整理分集大纲，保留已有正文。")}>{section === "body" ? "新建一集" : "和助手一起完善"}</Button></Empty>}
      </Spin></div>
      <footer className="script-next-step">{editing ? <><span>保存后可继续完善当前分集</span><Button disabled={saving} onClick={() => { if (dirty) modal.confirm({ title: "放弃未保存的修改？", okText: "放弃修改", cancelText: "继续编辑", onOk: discardEditing }); else discardEditing() }}>取消</Button><Button type="primary" icon={<Save size={14}/>} loading={saving} disabled={!draft.trim() || !dirty} onClick={() => void save()}>保存剧本</Button></> : <><Button type="text" className="script-extraction-help" icon={<Eye size={14}/>} onClick={() => setBenefitsOpen(true)}>提取能得到啥？</Button><span>{pendingNumbers.length ? `第 ${pendingNumbers.join("、")} 集待补充制作资产` : "角色与场景可在制作资产中统一管理"}</span><Button type="primary" icon={<ArrowRight size={14}/>} iconPlacement="end" loading={transferring || extractionWorking} disabled={!doc?.raw_text?.trim() || planning || extractionWorking} onClick={() => void nextStage()}>{stageLabel}</Button><Button type="text" onClick={() => setDetails(true)}>解析详情</Button></>}</footer>
    </main>
    <Modal title={doc ? "上传文件·解析新集" : "导入剧本"} open={importOpen} onCancel={() => { if (!importing && !readingFile) setImportOpen(false) }} onOk={() => form.submit()} okText="导入并保存" cancelText="取消" confirmLoading={importing} okButtonProps={{ disabled: readingFile }} width={760} mask={{ closable: !importing }}>
      <Form form={form} layout="vertical" onFinish={importScript} disabled={importing || readingFile}>
        <Form.Item name="filename" label="来源名称"><Input placeholder="可留空，按正文标题命名" maxLength={255}/></Form.Item>
        <Upload accept={capabilities?.extensions.map(ext => ext.startsWith(".") ? ext : `.${ext}`).join(",") || ".md,.markdown,.txt"} showUploadList={false} beforeUpload={file => { void readFile(file); return false }}><Button icon={<FilePlus2 size={14}/>} loading={readingFile}>上传文件并读取正文</Button></Upload>
        <Form.Item name="raw_text" label="剧本正文" rules={[{ required: true, whitespace: true, message: "请粘贴或读取剧本正文" }]}><Input.TextArea rows={14} maxLength={500000} placeholder={doc ? "粘贴待追加分集，使用 # 第N集：标题；已有分集保持原文" : "粘贴剧本正文…"}/></Form.Item>
      </Form>
    </Modal>
    <Modal title="将剧本中的角色、形象和场景整理成可复用资产" open={benefitsOpen} onCancel={() => setBenefitsOpen(false)} width={960} centered className="script-extraction-modal" styles={{ body: { maxHeight: "min(76vh, 700px)", overflowY: "auto" } }} footer={<div className="script-extraction-footer"><span>按当前剧本整理角色、场景与道具，参考图可在资产库继续生成。</span><Button type="primary" loading={transferring || extractionWorking} disabled={!doc?.raw_text?.trim() || planning || dirty || extractionWorking} onClick={() => void nextStage()}>{stageLabel}</Button></div>}>
      <p className="script-extraction-intro">以下为拆解结果的展示示例，实际资产以你的剧本内容为准。</p>
      <div className="script-extraction-features">
        <div><h3>统一梳理剧本资产</h3><p>整理角色、场景与道具，减少跨集重复创建。</p></div>
        <div><h3>关联分镜中的人物与场景</h3><p>制作镜头沿用同一套资产，保持引用一致。</p></div>
        <div><h3>继续编辑与生成参考图</h3><p>在资产库调整造型、描述与参考图。</p></div>
      </div>
      <section className="script-extraction-section"><h2>角色形象 <Tag>示例</Tag></h2><p>同一角色可以管理多套造型，参考图作为后续镜头的身份与服装依据。</p><div className="script-character-examples">{[["daily", "日常造型"], ["work", "职场造型"], ["evening", "晚宴造型"]].map(([key, label]) => <figure key={key}><img src={`/director-extraction/character-${key}.webp`} alt={`${label}示例`} loading="lazy"/><figcaption>{label}</figcaption></figure>)}</div></section>
      <section className="script-extraction-section"><h2>场景资产 <Tag>示例</Tag></h2><p>同一场景的不同机位与景别，可作为后续画面设计的参考。</p><Tabs activeKey={sceneExample} onChange={setSceneExample} items={SCENE_EXAMPLES.map(item => ({ key: item.key, label: item.label, children: <div className="script-scene-examples">{SHOT_EXAMPLES.map(([shot, label]) => <figure key={shot}><img src={`/director-extraction/${item.key}-${shot}.webp`} alt={`${item.label}${label}示例`} loading="lazy"/><figcaption>{label}</figcaption></figure>)}</div> }))}/></section>
    </Modal>
    <Drawer title="剧本解析详情" open={details} onClose={() => { setDetails(false); void refresh(true); onChanged() }} size={1060} destroyOnHidden><ContentLibraryPane csrfToken={csrfToken} projectId={projectId}/></Drawer>
    {modalContext}
  </div>
}
