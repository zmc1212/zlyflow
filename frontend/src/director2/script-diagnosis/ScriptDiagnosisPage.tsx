import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Alert, Button, Drawer, Empty, Input, Popconfirm, Progress, Segmented, Space, Spin, Table, Tag, Tooltip, Upload, message } from "antd"
import { ArrowDown, ArrowLeft, ArrowUp, Clipboard, Copy, Download, FilePlus2, FileSearch, FileText, History, Plus, RotateCcw, Sparkles, Trash2, X } from "lucide-react"
import { ApiRequestError } from "../../api"
import { director2ErrorDetail } from "../api"
import { director2HomePath, director2ProjectPath, director2DiagnosisPath } from "../paths"
import {
  cancelDiagnosis, createDiagnosis, deleteDiagnosis, extractFiles, getCapabilities,
  getDiagnosis, getDocumentSource, listDiagnoses, retryDiagnosis,
} from "./api"
import {
  DIMENSIONS, STATUS_LABELS, characterCount, isActive, moveItem, reportMarkdown,
  type Capabilities, type Diagnosis, type DiagnosisSummary,
} from "./model"
import DiagnosisReport from "./DiagnosisReport"
import "./script-diagnosis.css"

type DraftSource = { uid: string; name: string; text?: string; error?: string; pending?: boolean }
const newKey = (): string => crypto.randomUUID?.() ||
  "diagnosis-" + Array.from(crypto.getRandomValues(new Uint32Array(4)), part => part.toString(16)).join("-")

export default function ScriptDiagnosisPage({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const diagnosisId = params.get("id")
  const projectId = params.get("project")
  const documentId = params.get("doc")
  const fromDocument = Boolean(projectId && documentId && !diagnosisId)
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [capsError, setCapsError] = useState("")
  const [reload, setReload] = useState(0)
  const [mode, setMode] = useState("upload")
  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const [sources, setSources] = useState<DraftSource[]>([])
  const sourcesRef = useRef<DraftSource[]>([])
  const draftGeneration = useRef(0)
  const [documentLoading, setDocumentLoading] = useState(false)
  const [documentError, setDocumentError] = useState("")
  const [task, setTask] = useState<Diagnosis | null>(null)
  const [taskError, setTaskError] = useState("")
  const [busy, setBusy] = useState(false)
  const submission = useRef<{ signature: string; key: string } | null>(null)
  const retryKeys = useRef<Record<string, string>>({})
  const [historyOpen, setHistoryOpen] = useState(() => params.get("history") === "1")
  const [history, setHistory] = useState<DiagnosisSummary[]>([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState("")
  const [historyScope, setHistoryScope] = useState("all")
  const [historyRevision, setHistoryRevision] = useState(0)
  const selectedTask = task?.id === diagnosisId ? task : null
  const contextDocument = documentId || selectedTask?.document_id

  function updateSources(updater: (current: DraftSource[]) => DraftSource[]) {
    sourcesRef.current = updater(sourcesRef.current)
    setSources(sourcesRef.current)
  }

  useEffect(() => {
    let cancelled = false
    getCapabilities().then(result => { if (!cancelled) { setCaps(result); setCapsError("") } })
      .catch(error => { if (!cancelled) setCapsError(director2ErrorDetail(error, "无法读取诊断能力，请重试")) })
    return () => { cancelled = true }
  }, [reload])

  useEffect(() => {
    let cancelled = false
    draftGeneration.current += 1
    updateSources(() => [])
    setText("")
    setTitle("")
    setDocumentError("")
    setDocumentLoading(false)
    submission.current = null
    if (fromDocument && projectId && documentId) {
      setDocumentLoading(true)
      getDocumentSource(projectId, documentId).then(result => {
        if (!cancelled) {
          setTitle(result.title)
          updateSources(() => result.sources.map(source => ({ uid: newKey(), name: source.name, text: source.text })))
        }
      }).catch(error => {
        if (!cancelled) setDocumentError(director2ErrorDetail(error, "无法读取剧本，请返回内容库检查"))
      }).finally(() => { if (!cancelled) setDocumentLoading(false) })
    }
    return () => { cancelled = true }
  }, [projectId, documentId, fromDocument, diagnosisId])

  useEffect(() => {
    if (!diagnosisId) { setTask(null); setTaskError(""); return }
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      try {
        const result = await getDiagnosis(diagnosisId)
        if (cancelled) return
        setTask(result)
        setTaskError("")
        if (isActive(result)) timer = setTimeout(load, 2000)
      } catch (error) {
        if (!cancelled) {
          setTaskError(director2ErrorDetail(error, "无法读取诊断，请重试"))
          const status = error instanceof ApiRequestError ? error.status : 0
          if (!status || status >= 500 || status === 408 || status === 429) timer = setTimeout(load, 5000)
        }
      }
    }
    void load()
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [diagnosisId, reload])

  useEffect(() => {
    if (!historyOpen) return
    let cancelled = false
    setHistoryLoading(true)
    listDiagnoses(historyPage, historyScope === "document" ? contextDocument : null)
      .then(result => { if (!cancelled) { setHistory(result.items); setHistoryTotal(result.total); setHistoryError("") } })
      .catch(error => { if (!cancelled) setHistoryError(director2ErrorDetail(error, "无法读取诊断历史")) })
      .finally(() => { if (!cancelled) setHistoryLoading(false) })
    return () => { cancelled = true }
  }, [historyOpen, historyPage, historyScope, contextDocument, historyRevision])

  async function addFiles(files: File[]) {
    if (!caps || !files.length) return
    if (sourcesRef.current.length + files.length > caps.max_files) {
      message.warning("最多上传 " + caps.max_files + " 份文件，请移除部分文件后再试")
      return
    }
    const generation = draftGeneration.current
    const pending = files.map(file => ({
      uid: newKey(), name: file.name, pending: true,
      error: file.size > caps.max_file_bytes ? "文件超过 20MB，请拆分或转换后上传" : undefined,
    }))
    updateSources(current => [...current, ...pending.map(item => ({ ...item, pending: !item.error }))])
    const validIndices = pending.flatMap((item, index) => item.error ? [] : [index])
    if (!validIndices.length) return
    try {
      const result = await extractFiles(csrfToken, validIndices.map(index => files[index]))
      if (draftGeneration.current !== generation) return
      updateSources(current => current.map(item => {
        const index = validIndices.findIndex(originalIndex => pending[originalIndex].uid === item.uid)
        if (index < 0) return item
        const parsed = result.sources[index]
        return { ...item, pending: false, text: parsed?.text, error: parsed?.error || (!parsed?.text ? "未读取到正文，请重新上传" : undefined) }
      }))
    } catch (error) {
      if (draftGeneration.current !== generation) return
      const failedIds = new Set(validIndices.map(index => pending[index].uid))
      updateSources(current => current.map(item => failedIds.has(item.uid)
        ? { ...item, pending: false, error: director2ErrorDetail(error, "解析失败，请移除后重新上传") } : item))
    }
  }

  const inputSources = fromDocument || mode === "upload" ? sources : [{ uid: "paste", name: title.trim() || "粘贴剧本", text }]
  const count = inputSources.reduce((sum, source) => sum + characterCount(source.text || ""), 0)
  const invalid = !inputSources.length || inputSources.some(source => source.pending || source.error || !source.text?.trim())
  const overLimit = Boolean(caps && count > caps.max_characters)

  async function start() {
    if (!caps || invalid || overLimit || !caps.available || busy) return
    const payload = {
      title: title.trim() || (inputSources.length === 1 ? inputSources[0].name : "合并剧本"),
      ...(fromDocument
        ? { project_id: projectId, document_id: documentId }
        : { sources: inputSources.map(source => ({ name: source.name, text: source.text })) }),
    }
    const signature = JSON.stringify(payload)
    if (submission.current?.signature !== signature) submission.current = { signature, key: newKey() }
    setBusy(true)
    try {
      const created = await createDiagnosis(csrfToken, { ...payload, client_request_id: submission.current.key })
      setTask(created)
      navigate(director2DiagnosisPath({ id: created.id }))
    } catch (error) { message.error(director2ErrorDetail(error, "创建诊断失败，请重试")) }
    finally { setBusy(false) }
  }

  async function retry() {
    if (!selectedTask || busy) return
    setBusy(true)
    try {
      const key = retryKeys.current[selectedTask.id] ||= newKey()
      const created = await retryDiagnosis(csrfToken, selectedTask.id, key)
      setTask(created)
      navigate(director2DiagnosisPath({ id: created.id }))
    } catch (error) { message.error(director2ErrorDetail(error, "重试失败，请稍后再试")) }
    finally { setBusy(false) }
  }

  function exportReport() {
    if (!selectedTask?.report) return
    const blob = new Blob([reportMarkdown(selectedTask)], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = selectedTask.title.replace(/[\\/:*?"<>|]/g, "_") + "-诊断报告.md"
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  async function copyReport() {
    if (!selectedTask?.report) return
    try {
      await navigator.clipboard.writeText(reportMarkdown(selectedTask))
      message.success("报告已复制")
    } catch {
      message.error("复制失败，可导出报告保存")
    }
  }

  async function removeHistory(item: DiagnosisSummary) {
    try {
      await deleteDiagnosis(csrfToken, item.id)
      if (diagnosisId === item.id) navigate(director2DiagnosisPath())
      if (history.length === 1 && historyPage > 1) setHistoryPage(page => page - 1)
      setHistoryRevision(value => value + 1)
      message.success("诊断记录已删除")
    } catch (error) { message.error(director2ErrorDetail(error, "删除失败")) }
  }

  function goBack() {
    const linkedProject = projectId || selectedTask?.project_id
    const linkedDoc = documentId || selectedTask?.document_id
    navigate(linkedProject
      ? director2ProjectPath(linkedProject, "content") + (linkedDoc ? "?doc=" + encodeURIComponent(linkedDoc) : "")
      : director2HomePath())
  }

  return <div className="sd-page">
    <header className="sd-topbar">
      <Space><Button type="text" icon={<ArrowLeft size={17} />} onClick={goBack}>返回</Button><span className="sd-topbar-divider" /><FileSearch size={19} /><strong>剧本诊断</strong></Space>
      <Space>
        {selectedTask?.report && <>
          <Button icon={<Copy size={15} />} onClick={copyReport}>复制报告</Button>
          <Button icon={<Download size={15} />} onClick={exportReport}>导出报告</Button>
        </>}
        {diagnosisId && <Button icon={<Plus size={15} />} onClick={() => navigate(director2DiagnosisPath())}>新诊断</Button>}
        <Button type="text" icon={<History size={16} />} onClick={() => { setHistoryOpen(true); setHistoryRevision(value => value + 1) }}>诊断历史</Button>
      </Space>
    </header>

    {diagnosisId ? <>
      {taskError && <Alert className="sd-load-error" type="error" showIcon title={taskError}
        action={<Button size="small" onClick={() => setReload(value => value + 1)}>重新加载</Button>} />}
      {!selectedTask ? <div className="sd-task-state">{!taskError && <Spin description="正在读取诊断" />}</div>
        : selectedTask.report && selectedTask.status === "succeeded" ? <DiagnosisReport key={selectedTask.id} task={selectedTask} />
        : <div className="sd-task-state">
          {isActive(selectedTask) ? <section className="sd-progress-panel" aria-live="polite">
            <div className="sd-progress-symbol"><FileSearch size={30} /></div>
            <h1>{selectedTask.stage === "summarizing" ? "正在汇总诊断报告" : selectedTask.status === "queued" ? "剧本已提交，等待诊断" : "正在逐段审阅剧本"}</h1>
            <p>{selectedTask.title}</p>
            {selectedTask.total > 0 && <Progress percent={Math.round(selectedTask.completed / selectedTask.total * 100)} showInfo={false}
              status="normal" aria-label={"已审阅 " + selectedTask.completed + " / " + selectedTask.total + " 个片段"} />}
            <p className="sd-muted">{selectedTask.total > 0
              ? "已审阅 " + selectedTask.completed + " / " + selectedTask.total + " 个片段" : "正在准备剧本"}
              {selectedTask.stage === "summarizing" ? "，正在整合五项结论与修改建议" : ""}</p>
            <p className="sd-muted">可以离开页面，稍后从诊断历史继续查看。</p>
            <Button disabled={busy} onClick={async () => {
              setBusy(true)
              try { setTask(await cancelDiagnosis(csrfToken, selectedTask.id)) }
              catch (error) { message.error(director2ErrorDetail(error, "取消失败，请重试")) }
              finally { setBusy(false) }
            }}>取消诊断</Button>
          </section> : <section className="sd-progress-panel">
            <FileText size={32} />
            <h1>{STATUS_LABELS[selectedTask.status]}</h1>
            <p>{selectedTask.title}</p>
            {selectedTask.error && <Alert showIcon type="error" title={selectedTask.error} />}
            <p className="sd-muted">原始剧本已保留，重试将生成一份新的诊断记录。</p>
            <Space><Button type="primary" loading={busy} icon={<RotateCcw size={15} />} onClick={retry}>重新诊断</Button>
              <Button onClick={() => navigate(director2DiagnosisPath())}>使用其他剧本</Button></Space>
          </section>}
        </div>}
    </> : <div className="sd-input-scroll">
      <div className="sd-input-inner">
        <div className="sd-intro"><h1>让每一次修改，都有依据</h1><p>从时长、创意、节奏、情绪与内容风险，读懂你的剧本。</p></div>
        {capsError && <Alert type="error" showIcon title={capsError} action={<Button size="small" onClick={() => setReload(value => value + 1)}>重试</Button>} />}
        {caps && !caps.available && <Alert type="warning" showIcon title="暂时无法开始诊断"
          description={caps.unavailable_reason || "请联系管理员配置 LLM 大模型，已有报告仍可查看。"} />}
        {documentError && <Alert type="error" showIcon title={documentError}
          action={<Button size="small" onClick={() => navigate(director2DiagnosisPath())}>使用其他剧本</Button>} />}
        {!caps && !capsError ? <div className="sd-cap-loading"><Spin /></div> : caps && <Spin spinning={documentLoading}>
          <section className="sd-input-panel">
            <div className="sd-input-heading">
              {fromDocument ? <Space><FileText size={17} /><strong>来自内容库的剧本</strong></Space>
                : <Segmented aria-label="剧本输入方式" value={mode} onChange={value => setMode(String(value))}
                  options={[{ label: <Space size={6}><FilePlus2 size={15} />上传剧本</Space>, value: "upload" },
                    { label: <Space size={6}><Clipboard size={15} />粘贴文本</Space>, value: "paste" }]} />}
              {fromDocument && <Button type="text" size="small" onClick={() => navigate(director2DiagnosisPath())}>使用其他剧本</Button>}
            </div>
            {fromDocument ? <Input.TextArea aria-label="内容库剧本预览" readOnly value={sources[0]?.text || ""} rows={10} />
              : mode === "upload" ? <>
                <Upload.Dragger multiple accept={caps.extensions.join(",")} showUploadList={false} disabled={busy}
                  beforeUpload={(file, fileList) => {
                    if (file === fileList[0]) void addFiles(fileList)
                    return Upload.LIST_IGNORE
                  }}>
                  <div className="sd-drop-icon"><FilePlus2 size={29} /></div>
                  <strong>选择文件，或拖到这里</strong>
                  <p>支持 {caps.extensions.map(extension => extension.slice(1).toUpperCase()).join("、")}</p>
                  <small>最多 {caps.max_files} 份 · 每份 {Math.round(caps.max_file_bytes / 1024 / 1024)}MB · 多文件按顺序合并诊断</small>
                </Upload.Dragger>
                {sources.length > 0 && <ol className="sd-files" aria-label="合并顺序">{sources.map((source, index) => <li key={source.uid}>
                  <span className="sd-file-order">{index + 1}</span><FileText size={17} />
                  <span className="sd-file-info"><strong title={source.name}>{source.name}</strong>
                    {source.pending ? <small><Spin size="small" /> 正在提取正文</small> : source.error
                      ? <small className="sd-file-error">{source.error}</small>
                      : <small>{characterCount(source.text || "").toLocaleString()} 字符 · 解析完成</small>}</span>
                  <Space size={0}>
                    <Tooltip title="上移"><Button type="text" aria-label={"上移 " + source.name} disabled={index === 0}
                      icon={<ArrowUp size={14} />} onClick={() => updateSources(current => moveItem(current, index, index - 1))} /></Tooltip>
                    <Tooltip title="下移"><Button type="text" aria-label={"下移 " + source.name} disabled={index === sources.length - 1}
                      icon={<ArrowDown size={14} />} onClick={() => updateSources(current => moveItem(current, index, index + 1))} /></Tooltip>
                    <Button type="text" aria-label={"移除 " + source.name} icon={<X size={15} />}
                      onClick={() => updateSources(current => current.filter(item => item.uid !== source.uid))} />
                  </Space>
                </li>)}</ol>}
              </> : <Input.TextArea aria-label="剧本正文" placeholder="在这里粘贴剧本，可以是单集、多集，或完整的故事……"
                value={text} onChange={event => setText(event.target.value)} rows={10} />}
            <div className="sd-title-row"><label htmlFor="sd-title">剧本名称</label><Input id="sd-title" value={title} maxLength={255}
              onChange={event => setTitle(event.target.value)} placeholder="选填，方便在历史中查找" /></div>
            <div className="sd-input-footer"><span className={overLimit ? "sd-file-error" : "sd-muted"}>
              {count.toLocaleString()} / {caps.max_characters.toLocaleString()} 字符{overLimit ? " · 请拆分剧本后诊断" : ""}</span>
              <Button type="primary" size="large" icon={<Sparkles size={16} />} loading={busy}
                disabled={invalid || overLimit || !caps.available || documentLoading || Boolean(documentError)} onClick={start}>开始诊断</Button></div>
          </section>
        </Spin>}
        <section className="sd-feature-list" aria-label="五项诊断维度">
          <div><h2>问题从哪来，<br />一次看清</h2><p>五项诊断，每一条建议<br />都回到原文。</p></div>
          <dl>{DIMENSIONS.map(dimension => <div key={dimension.key}><dt>{dimension.label}</dt><dd>{dimension.hint}</dd></div>)}</dl>
        </section>
        <p className="sd-input-note">旧版 DOC 或扫描件请先转换。新颖度为文本创作评估，风险评估为辅助审阅。</p>
      </div>
    </div>}

    <Drawer rootClassName="sd-history-drawer" title="诊断历史" open={historyOpen} size={680} onClose={() => setHistoryOpen(false)}
      extra={<Button type="text" icon={<RotateCcw size={15} />} onClick={() => setHistoryRevision(value => value + 1)}>刷新</Button>}>
      {contextDocument && <Segmented className="sd-history-filter" value={historyScope} onChange={value => { setHistoryScope(String(value)); setHistoryPage(1) }}
        options={[{ label: "全部诊断", value: "all" }, { label: "当前剧本", value: "document" }]} />}
      {historyError && <Alert showIcon type="error" title={historyError} />}
      <Table rowKey="id" size="middle" loading={historyLoading} dataSource={history}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有诊断记录" /> }}
        pagination={{ total: historyTotal, current: historyPage, pageSize: 10, showSizeChanger: false, onChange: setHistoryPage }}
        columns={[
          { title: "剧本", dataIndex: "title", ellipsis: true, render: (value: string, item: DiagnosisSummary) =>
            <div className="sd-history-title"><strong title={value}>{value}</strong><small>{new Date(item.created_at).toLocaleString("zh-CN")}</small></div> },
          { title: "状态", width: 90, render: (_: unknown, item: DiagnosisSummary) =>
            <Tag className={"sd-tag-" + (item.status === "succeeded" ? "success" : item.status === "failed" ? "high" : "low")}
              color={item.status === "succeeded" ? "success" : item.status === "failed" ? "error" : isActive(item) ? "processing" : "default"}>{STATUS_LABELS[item.status]}</Tag> },
          { title: "操作", width: 118, render: (_: unknown, item: DiagnosisSummary) => <Space size={0}>
            <Button type="link" onClick={() => { setHistoryOpen(false); navigate(director2DiagnosisPath({ id: item.id })); setReload(value => value + 1) }}>查看</Button>
            <Popconfirm title="删除这份诊断？" description="将同时删除该记录保存的原文和报告，内容库剧本保留。" okText="删除" cancelText="取消"
              disabled={isActive(item)} okButtonProps={{ danger: true }} onConfirm={() => removeHistory(item)}>
              <Button type="text" danger aria-label={"删除诊断 " + item.title} disabled={isActive(item)} icon={<Trash2 size={15} />} />
            </Popconfirm></Space> },
        ]} />
    </Drawer>
  </div>
}
