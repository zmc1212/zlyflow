import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from "antd"
import type { TextAreaRef } from "antd/es/input/TextArea"
import { CheckCircle2, ChevronLeft, FileText, Info, Library, Play, Plus, RefreshCw, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { PATHS } from "../paths"
import {
  deleteXiajiDocument,
  getXiajiDocument,
  getXiajiProject,
  listXiajiDocuments,
  pasteXiajiDocument,
  saveXiajiChapters,
  syncXiajiAssets,
  updateXiajiProject,
  uploadXiajiDocument,
  type XiajiAnalysis,
  type XiajiChapter,
  type XiajiDocumentDetail,
  type XiajiDocumentStatus,
} from "./xiaji-api"
import XiajiAssetsModule from "./XiajiAssetsModule"
import XiajiHome from "./XiajiHome"
import XiajiWorkshopModule from "./XiajiWorkshopModule"

const STATUS_LABEL: Record<XiajiDocumentStatus, { color: string; text: string }> = {
  uploaded: { color: "default", text: "已上传" },
  parsing: { color: "processing", text: "解析中" },
  indexed: { color: "blue", text: "已索引" },
  review_required: { color: "gold", text: "待校对" },
  ready: { color: "green", text: "已就绪" },
  failed: { color: "red", text: "失败" },
}

const PLACEHOLDERS = [
  { key: "styles", label: "风格中心", hint: "视觉风格和 Prompt 模板将在后续版本接入。" },
  { key: "assistant", label: "制作助手", hint: "进度查询和受控任务操作将在后续版本接入。" },
] as const

const SETTINGS_KEY = "zly-xiaji-ingest-settings"

const SPINE_OPTIONS = [
  { value: "drama", label: "精品剧" },
  { value: "narrated", label: "解说剧" },
] as const

const VISUAL_STYLE_OPTIONS = [
  { value: "chinese_period_drama", label: "写实古装剧" },
  { value: "anime", label: "动漫" },
  { value: "guoman_fantasy", label: "国漫奇幻" },
  { value: "post_apocalyptic", label: "末世废土" },
  { value: "realistic", label: "写实" },
  { value: "republican_era_drama", label: "民国剧" },
] as const

const NARRATION_OPTIONS = [
  { value: "first_person", label: "第一人称" },
  { value: "third_person", label: "第三人称" },
] as const

const ETHNICITY_OPTIONS = [
  { value: "Chinese", label: "中国人" },
  { value: "Japanese", label: "日本人" },
  { value: "Korean", label: "韩国人" },
  { value: "Western", label: "欧美" },
  { value: "Mixed", label: "混合" },
] as const

type InputMode = "upload" | "paste"
type SpineTemplate = (typeof SPINE_OPTIONS)[number]["value"]

type IngestSettings = {
  spine_template: SpineTemplate
  visual_style: string
  narration_style: string
  ethnicity: string
}

const DEFAULT_SETTINGS: IngestSettings = {
  spine_template: "drama",
  visual_style: "chinese_period_drama",
  narration_style: "first_person",
  ethnicity: "Chinese",
}

function loadSettings(projectId: string): IngestSettings {
  try {
    const raw = window.localStorage.getItem(`${SETTINGS_KEY}:${projectId}`)
    if (!raw) return DEFAULT_SETTINGS
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) as Partial<IngestSettings> }
  } catch {
    return DEFAULT_SETTINGS
  }
}

function saveSettings(projectId: string, settings: IngestSettings) {
  window.localStorage.setItem(`${SETTINGS_KEY}:${projectId}`, JSON.stringify(settings))
}

function optionLabel(options: readonly { value: string; label: string }[], value: string) {
  return options.find((item) => item.value === value)?.label ?? value
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function splitFilename(filename: string) {
  const dotIndex = filename.lastIndexOf(".")
  if (dotIndex <= 0 || dotIndex === filename.length - 1) {
    return { name: filename, extension: "FILE" }
  }
  return { name: filename.slice(0, dotIndex), extension: filename.slice(dotIndex).toUpperCase() }
}

function statusTag(status: XiajiDocumentStatus) {
  const item = STATUS_LABEL[status] ?? STATUS_LABEL.uploaded
  return <Tag color={item.color}>{item.text}</Tag>
}

function AnalysisPanel({
  analysis,
  error,
  csrfToken,
  projectId,
  documentId,
}: {
  analysis?: XiajiAnalysis | null
  error?: string | null
  csrfToken: string
  projectId: string
  documentId?: string | null
}) {
  const queryClient = useQueryClient()
  const canTransfer = Boolean(documentId) && Boolean(
    (analysis?.characters?.length || 0) + (analysis?.scenes?.length || 0) + (analysis?.props?.length || 0),
  )
  const transferMutation = useMutation({
    mutationFn: () => syncXiajiAssets(csrfToken, projectId, documentId || undefined),
    onSuccess: (result) => {
      const counts = result.transferred
      message.success(`已转入资产库：${counts.characters} 个角色、${counts.scenes} 个场景、${counts.props} 个道具`)
      void queryClient.invalidateQueries({ queryKey: ["xiaji-assets", projectId] })
    },
    onError: (error: Error) => message.error(error.message),
  })
  if (!analysis && !error) {
    return (
      <section className="xiaji-analysis">
        <h2>分析结果</h2>
        <Empty description="导入后会在这里显示大模型抽取的摘要、角色、场景和剧集规划" />
      </section>
    )
  }
  const logs = analysis?.logs ?? []
  return (
    <section className="xiaji-analysis">
      <h2>分析结果</h2>
      {canTransfer ? (
        <div className="xiaji-analysis-actions">
          <Button type="primary" loading={transferMutation.isPending} onClick={() => transferMutation.mutate()}>
            转入资产库
          </Button>
          <Typography.Text type="secondary">
            把下面的角色、场景、道具写入资产库，再去生成参考图和声线。
          </Typography.Text>
        </div>
      ) : null}
      {error ? <Alert type="error" showIcon message={error} /> : null}
      {analysis?.model ? (
        <Typography.Paragraph type="secondary" className="xiaji-table-hint">
          模型 {analysis.model}
        </Typography.Paragraph>
      ) : null}
      {logs.length > 0 ? (
        <div className="xiaji-analysis-logs" aria-label="导入日志">
          {logs.map((line, index) => (
            <p key={`${index}-${line}`}>
              <span>[{String(index + 1).padStart(2, "0")}]</span>
              {line}
            </p>
          ))}
        </div>
      ) : null}
      {analysis?.summary ? (
        <div className="xiaji-script-details">
          <span>内容摘要</span>
          <p>{analysis.summary}</p>
        </div>
      ) : null}
      <Table
        className="xiaji-chapter-table"
        size="small"
        rowKey="name"
        pagination={false}
        dataSource={analysis?.characters ?? []}
        locale={{ emptyText: "未识别到角色" }}
        columns={[
          { title: "角色", dataIndex: "name", width: 120 },
          { title: "定位", dataIndex: "role", width: 100 },
          {
            title: "主视角",
            dataIndex: "is_main",
            width: 80,
            render: (value: boolean) => (value ? "是" : "否"),
          },
          { title: "性别", dataIndex: "gender", width: 72 },
          { title: "年龄段", dataIndex: "age_group", width: 88 },
          { title: "外貌与性格", dataIndex: "description", ellipsis: true },
        ]}
      />
      <Table
        className="xiaji-chapter-table"
        size="small"
        rowKey="name"
        pagination={false}
        dataSource={analysis?.scenes ?? []}
        locale={{ emptyText: "未识别到场景" }}
        columns={[
          { title: "场景", dataIndex: "name" },
          { title: "类型", dataIndex: "scene_type", width: 120 },
          { title: "描述", dataIndex: "description", ellipsis: true },
        ]}
      />
      <Table
        className="xiaji-chapter-table"
        size="small"
        rowKey="name"
        pagination={false}
        dataSource={analysis?.props ?? []}
        locale={{ emptyText: "未识别到道具" }}
        columns={[
          { title: "道具", dataIndex: "name", width: 140 },
          { title: "类型", dataIndex: "prop_type", width: 120 },
          { title: "持有者", dataIndex: "owner", width: 120 },
          { title: "外观", dataIndex: "visual_prompt", ellipsis: true },
        ]}
      />
      <Table
        className="xiaji-chapter-table"
        size="small"
        rowKey="number"
        pagination={false}
        dataSource={analysis?.episodes ?? []}
        locale={{ emptyText: "尚未规划剧集" }}
        columns={[
          { title: "集", dataIndex: "number", width: 64 },
          { title: "标题", dataIndex: "title", width: 160 },
          { title: "摘要", dataIndex: "content_summary", ellipsis: true },
          { title: "冲突", dataIndex: "main_conflict", ellipsis: true },
          { title: "悬念", dataIndex: "cliffhanger", ellipsis: true },
        ]}
      />
    </section>
  )
}

function ContentLibrary({ csrfToken, projectId }: { csrfToken: string; projectId: string }) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<XiajiChapter[]>([])
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [inputMode, setInputMode] = useState<InputMode>("upload")
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [pasteText, setPasteText] = useState("")
  const pasteAreaRef = useRef<TextAreaRef>(null)
  const [composing, setComposing] = useState(false)
  const [formatOpen, setFormatOpen] = useState(false)
  const [settings, setSettings] = useState<IngestSettings>(DEFAULT_SETTINGS)
  const [savedSettings, setSavedSettings] = useState<IngestSettings>(DEFAULT_SETTINGS)
  const listQuery = useQuery({ queryKey: ["xiaji-documents", projectId], queryFn: () => listXiajiDocuments(projectId) })
  const projectQuery = useQuery({ queryKey: ["xiaji-project", projectId], queryFn: () => getXiajiProject(projectId) })
  const detailQuery = useQuery({
    queryKey: ["xiaji-document", selectedId],
    queryFn: () => getXiajiDocument(selectedId!),
    enabled: Boolean(selectedId),
  })

  useEffect(() => {
    const loaded = loadSettings(projectId)
    const fromProject = projectQuery.data?.settings
    const merged = {
      ...DEFAULT_SETTINGS,
      ...loaded,
      ...(fromProject?.spine_template ? { spine_template: fromProject.spine_template as SpineTemplate } : {}),
      ...(fromProject?.visual_style ? { visual_style: fromProject.visual_style } : {}),
      ...(fromProject?.narration_style ? { narration_style: fromProject.narration_style } : {}),
      ...(fromProject?.ethnicity ? { ethnicity: fromProject.ethnicity } : {}),
    }
    setSettings(merged)
    setSavedSettings(merged)
  }, [projectId, projectQuery.data])

  useEffect(() => {
    const documents = listQuery.data
    if (!documents?.length) {
      setSelectedId(null)
      return
    }
    if (!selectedId || !documents.some((item) => item.id === selectedId)) {
      setSelectedId(documents[0].id)
    }
  }, [listQuery.data, selectedId])

  useEffect(() => {
    const detail = detailQuery.data
    if (!detail) return
    setDrafts(detail.chapters)
    setActiveChapterId(detail.chapters[0]?.id ?? null)
  }, [detailQuery.data])

  const documents = listQuery.data ?? []
  const detail = detailQuery.data
  const activeChapter = useMemo(
    () => drafts.find((item) => item.id === activeChapterId) ?? drafts[0],
    [activeChapterId, drafts],
  )
  const settingsChanged = JSON.stringify(settings) !== JSON.stringify(savedSettings)
  const showNarration = settings.spine_template === "narrated"
  const hasImported = documents.length > 0
  const showPreview = hasImported && !composing

  const readPastedText = () => {
    const native = pasteAreaRef.current?.resizableTextArea?.textArea
    const value = native?.value ?? pasteText
    return value.trim()
  }

  const ingestSuccess = async (document: XiajiDocumentDetail) => {
    await queryClient.invalidateQueries({ queryKey: ["xiaji-documents", projectId] })
    await queryClient.invalidateQueries({ queryKey: ["xiaji-assets", projectId] })
    setSelectedId(document.id)
    setPendingFile(null)
    setPasteText("")
    setComposing(false)
    message.success(document.analysis?.summary ? "已导入并完成分析" : "已导入并完成章节识别")
  }

  const ingestSettings = {
    spine_template: settings.spine_template,
    visual_style: settings.visual_style,
    narration_style: settings.narration_style,
    ethnicity: settings.ethnicity,
  }

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadXiajiDocument(csrfToken, projectId, file, undefined, ingestSettings),
    onSuccess: (document) => void ingestSuccess(document),
    onError: (error) => message.error(error instanceof Error ? error.message : "上传失败"),
  })

  const pasteMutation = useMutation({
    mutationFn: (text: string) => pasteXiajiDocument(csrfToken, projectId, text, undefined, ingestSettings),
    onSuccess: (document) => void ingestSuccess(document),
    onError: (error) => message.error(error instanceof Error ? error.message : "导入失败"),
  })

  const saveMutation = useMutation({
    mutationFn: (chapters: XiajiChapter[]) => saveXiajiChapters(
      csrfToken,
      selectedId!,
      chapters.map((item) => ({ id: item.id, title: item.title, content: item.content })),
    ),
    onSuccess: async (document: XiajiDocumentDetail) => {
      await queryClient.invalidateQueries({ queryKey: ["xiaji-documents", projectId] })
      await queryClient.invalidateQueries({ queryKey: ["xiaji-document", document.id] })
      message.success("章节已保存")
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "保存失败"),
  })

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteXiajiDocument(csrfToken, documentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["xiaji-documents", projectId] })
      setComposing(true)
      message.success("已删除")
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "删除失败"),
  })

  const ingestBusy = uploadMutation.isPending || pasteMutation.isPending

  const startIngest = () => {
    const typed = readPastedText()
    if (inputMode === "paste" || (typed && !pendingFile)) {
      if (!typed) {
        message.warning("请先粘贴或输入正文")
        return
      }
      setPasteText(typed)
      setInputMode("paste")
      pasteMutation.mutate(typed)
      return
    }
    if (!pendingFile) {
      message.warning("请先选择小说文件，或切换到「粘贴文本」")
      return
    }
    uploadMutation.mutate(pendingFile)
  }

  const updateActive = (patch: Partial<XiajiChapter>) => {
    if (!activeChapter) return
    setDrafts((current) => current.map((item) => (item.id === activeChapter.id ? { ...item, ...patch } : item)))
  }

  const moveChapter = (index: number, delta: number) => {
    const next = index + delta
    if (next < 0 || next >= drafts.length) return
    const copy = [...drafts]
    const [item] = copy.splice(index, 1)
    copy.splice(next, 0, item)
    setDrafts(copy)
  }

  const mergeWithNext = (index: number) => {
    if (index >= drafts.length - 1) return
    const copy = [...drafts]
    const current = copy[index]
    const following = copy[index + 1]
    copy.splice(index, 2, {
      ...current,
      content: [current.content, following.content].filter(Boolean).join("\n\n"),
      char_count: current.char_count + following.char_count,
    })
    setDrafts(copy)
    setActiveChapterId(current.id)
  }

  const splitActive = () => {
    if (!activeChapter) return
    const marker = "\n\n"
    const offset = activeChapter.content.indexOf(marker)
    if (offset < 0) {
      message.warning("请在章节正文中用空行分开上下两段，再执行拆分")
      return
    }
    const first = activeChapter.content.slice(0, offset).trim()
    const second = activeChapter.content.slice(offset + marker.length).trim()
    if (!first || !second) {
      message.warning("拆分后上下两段都不能为空")
      return
    }
    const index = drafts.findIndex((item) => item.id === activeChapter.id)
    const copy = [...drafts]
    copy.splice(index, 1, { ...activeChapter, content: first, char_count: first.length }, {
      id: `tmp-${Date.now()}`,
      document_id: activeChapter.document_id,
      sequence: activeChapter.sequence + 1,
      title: `${activeChapter.title}（续）`,
      content: second,
      char_count: second.length,
    })
    setDrafts(copy)
  }

  const confirmDelete = () => {
    if (!detail) return
    Modal.confirm({
      title: `删除「${detail.title}」？`,
      content: "原文和章节会一起删除，不可恢复。",
      okText: "删除",
      okButtonProps: { danger: true },
      onOk: () => deleteMutation.mutateAsync(detail.id),
    })
  }

  const pendingMeta = pendingFile ? splitFilename(pendingFile.name) : null
  const activeIndex = drafts.findIndex((item) => item.id === activeChapter?.id)

  return (
    <div className="xiaji-ingest-page">
      <header className="xiaji-ingest-hero">
        <span className="xiaji-ingest-hero-icon" aria-hidden="true">
          <Library size={18} />
        </span>
        <div className="xiaji-ingest-hero-copy">
          <div className="xiaji-ingest-hero-row">
            <h1>内容库</h1>
            {hasImported ? (
              <Select
                className="xiaji-doc-switch"
                value={selectedId ?? undefined}
                onChange={(value) => {
                  setSelectedId(value)
                  setComposing(false)
                }}
                options={documents.map((item) => ({ value: item.id, label: item.title }))}
              />
            ) : null}
          </div>
          <p>上传剧本，开启你的创意之旅</p>
        </div>
      </header>

      <div className="xiaji-ingest-scroll">
        <div className="xiaji-ingest-width">
          {!showPreview ? (
            <section className="xiaji-ingest-card">
              <div className={`xiaji-ingest-stage ${inputMode === "paste" ? "is-paste" : ""}`}>
                {inputMode === "upload" ? (
                  pendingFile && pendingMeta ? (
                    <div className="xiaji-selected-file">
                      <div className="xiaji-selected-file-card">
                        <button
                          type="button"
                          className="xiaji-selected-file-remove"
                          aria-label="移除已选文件"
                          onClick={() => setPendingFile(null)}
                        >
                          <X size={12} />
                        </button>
                        <p title={pendingMeta.name}>{pendingMeta.name}</p>
                        <div>
                          <FileText size={16} />
                          <span>{pendingMeta.extension}</span>
                          <span>{formatSize(pendingFile.size)}</span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <Upload.Dragger
                      accept=".txt,.md,.markdown,.docx"
                      maxCount={1}
                      showUploadList={false}
                      disabled={ingestBusy}
                      beforeUpload={(file) => {
                        setPendingFile(file)
                        return false
                      }}
                      className="xiaji-dropzone"
                    >
                      <div className="xiaji-dropzone-body">
                        <span className="xiaji-dropzone-plus"><Plus size={28} strokeWidth={1.25} /></span>
                        <div className="xiaji-dropzone-copy">
                          <p>点击或拖拽上传小说文件</p>
                          <span>支持 .txt / .md / .docx，建议不超过 8MB</span>
                        </div>
                      </div>
                    </Upload.Dragger>
                  )
                ) : (
                  <div className="xiaji-paste-stage">
                    <Input.TextArea
                      ref={pasteAreaRef}
                      value={pasteText}
                      onChange={(event) => {
                        const next = typeof event === "string" ? event : event.target.value
                        setPasteText(next)
                      }}
                      placeholder="在这里粘贴小说或剧本文本"
                      className="xiaji-paste-area"
                    />
                    <div className="xiaji-paste-count">{pasteText.length} 字</div>
                  </div>
                )}
              </div>

              <div className="xiaji-ingest-toolbar">
                <Segmented
                  size="small"
                  value={inputMode}
                  onChange={(value) => setInputMode(value as InputMode)}
                  options={[
                    { label: "上传小说", value: "upload" },
                    { label: "粘贴文本", value: "paste" },
                  ]}
                />
                <Select
                  size="small"
                  value={settings.spine_template}
                  onChange={(value) => setSettings((current) => ({ ...current, spine_template: value }))}
                  options={[...SPINE_OPTIONS]}
                />
                <Select
                  size="small"
                  value={settings.visual_style}
                  onChange={(value) => setSettings((current) => ({ ...current, visual_style: value }))}
                  options={[...VISUAL_STYLE_OPTIONS]}
                />
                {showNarration ? (
                  <Select
                    size="small"
                    value={settings.narration_style}
                    onChange={(value) => setSettings((current) => ({ ...current, narration_style: value }))}
                    options={[...NARRATION_OPTIONS]}
                  />
                ) : null}
                <Select
                  size="small"
                  value={settings.ethnicity}
                  onChange={(value) => setSettings((current) => ({ ...current, ethnicity: value }))}
                  options={[...ETHNICITY_OPTIONS]}
                />
                {settings.spine_template === "drama" ? (
                  <button type="button" className="xiaji-format-link" onClick={() => setFormatOpen(true)}>
                    <Info size={14} />
                    <span>小说格式</span>
                  </button>
                ) : null}
                <div className="xiaji-ingest-actions">
                  {hasImported ? (
                    <Button onClick={() => setComposing(false)}>返回预览</Button>
                  ) : null}
                  <Button
                    htmlType="button"
                    icon={<CheckCircle2 size={14} />}
                    disabled={!settingsChanged}
                    onClick={() => {
                      saveSettings(projectId, settings)
                      void updateXiajiProject(csrfToken, projectId, { settings })
                      setSavedSettings(settings)
                      message.success("设置已保存到当前项目")
                    }}
                  >
                    保存设置
                  </Button>
                  <Button
                    htmlType="button"
                    type="primary"
                    icon={<Play size={14} />}
                    loading={ingestBusy}
                    disabled={ingestBusy}
                    onClick={startIngest}
                  >
                    开始导入
                  </Button>
                </div>
              </div>
            </section>
          ) : (
            <div className="xiaji-preview">
              <div className="xiaji-file-card">
                <span className="xiaji-file-card-icon"><FileText size={20} /></span>
                <div className="xiaji-file-card-copy">
                  <div>
                    <strong>{detail?.filename || detail?.title || "已导入文本"}</strong>
                    {detail ? statusTag(detail.status) : null}
                  </div>
                  {detail ? (
                    <span>{detail.chapter_count} 章 · {detail.char_count.toLocaleString()} 字</span>
                  ) : null}
                </div>
                <Space>
                  <Button icon={<RefreshCw size={14} />} onClick={() => {
                    setPendingFile(null)
                    setComposing(true)
                  }}>
                    重新上传
                  </Button>
                  <Button danger onClick={confirmDelete} loading={deleteMutation.isPending}>删除</Button>
                </Space>
              </div>

              <h2>章节预览</h2>
              <div className="xiaji-stat-grid">
                <article>
                  <span>文件名</span>
                  <strong title={detail?.filename}>{detail?.filename || "—"}</strong>
                </article>
                <article>
                  <span>总字符</span>
                  <strong>{(detail?.char_count ?? 0).toLocaleString()}</strong>
                </article>
                <article>
                  <span>计费字符</span>
                  <strong>{(detail?.billed_char_count ?? 0).toLocaleString()}</strong>
                </article>
                <article>
                  <span>检测到章节</span>
                  <strong>{detail?.chapter_count ?? 0}</strong>
                </article>
                <article>
                  <span>预计剧集</span>
                  <strong>{detail?.estimated_episodes ?? 0} <em>集</em></strong>
                </article>
              </div>

              <div className="xiaji-script-details">
                <span>剧本设置</span>
                <div>
                  <div>
                    <small>项目类型</small>
                    <p>{optionLabel(SPINE_OPTIONS, settings.spine_template)}</p>
                  </div>
                  <div>
                    <small>视觉风格</small>
                    <p>{optionLabel(VISUAL_STYLE_OPTIONS, settings.visual_style)}</p>
                  </div>
                  {showNarration ? (
                    <div>
                      <small>解说人称</small>
                      <p>{optionLabel(NARRATION_OPTIONS, settings.narration_style)}</p>
                    </div>
                  ) : null}
                  <div>
                    <small>人物族裔</small>
                    <p>{optionLabel(ETHNICITY_OPTIONS, settings.ethnicity)}</p>
                  </div>
                </div>
              </div>

              <Table
                className="xiaji-chapter-table"
                size="small"
                rowKey="id"
                pagination={false}
                loading={detailQuery.isLoading}
                dataSource={drafts}
                locale={{ emptyText: "没有识别到章节" }}
                onRow={(record) => ({
                  onClick: () => {
                    setActiveChapterId(record.id)
                    setEditorOpen(true)
                  },
                })}
                columns={[
                  { title: "章节", dataIndex: "sequence", width: 80, render: (_value, _record, index) => index + 1 },
                  { title: "标题", dataIndex: "title", ellipsis: true },
                  {
                    title: "字数",
                    dataIndex: "char_count",
                    width: 96,
                    align: "right",
                    render: (value: number) => value.toLocaleString(),
                  },
                ]}
              />
              <Typography.Paragraph type="secondary" className="xiaji-table-hint">
                点击章节可校对标题和正文。拆分时请在上下两段之间留一个空行。
              </Typography.Paragraph>
              <AnalysisPanel
                analysis={detail?.analysis}
                error={detail?.error}
                csrfToken={csrfToken}
                projectId={projectId}
                documentId={selectedId}
              />
            </div>
          )}
        </div>
      </div>

      <Drawer
        title={activeChapter ? `校对 · ${activeChapter.title}` : "章节校对"}
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        width={560}
        extra={
          <Space>
            <Button disabled={activeIndex <= 0} onClick={() => moveChapter(activeIndex, -1)}>上移</Button>
            <Button disabled={activeIndex < 0 || activeIndex >= drafts.length - 1} onClick={() => moveChapter(activeIndex, 1)}>下移</Button>
            <Button disabled={activeIndex < 0 || activeIndex >= drafts.length - 1} onClick={() => mergeWithNext(activeIndex)}>合并下一章</Button>
            <Button onClick={splitActive}>拆分当前章</Button>
            <Button type="primary" loading={saveMutation.isPending} disabled={!selectedId || drafts.length === 0} onClick={() => saveMutation.mutate(drafts)}>
              保存校对
            </Button>
          </Space>
        }
      >
        {activeChapter ? (
          <div className="xiaji-chapter-editor">
            <Input
              value={activeChapter.title}
              onChange={(event) => updateActive({ title: event.target.value })}
              placeholder="章节标题"
            />
            <Input.TextArea
              value={activeChapter.content}
              onChange={(event) => updateActive({ content: event.target.value, char_count: event.target.value.length })}
              autoSize={{ minRows: 16, maxRows: 32 }}
              placeholder="章节正文"
            />
          </div>
        ) : <Empty description="没有章节" />}
      </Drawer>

      <Modal title="小说格式" open={formatOpen} onCancel={() => setFormatOpen(false)} footer={null} width={640}>
        <Typography.Paragraph>
          精品剧建议按章节标题切分。当前内容库用规则识别标题，不调用大模型。
        </Typography.Paragraph>
        <pre className="xiaji-format-spec">{`第1章 开篇
正文……

第2章 转折
正文……

# Markdown 一级标题也可以作为章节`}</pre>
        <Typography.Paragraph type="secondary">
          没有标题时整篇作为一章，导入后可在章节表中拆分、合并和改标题。
        </Typography.Paragraph>
      </Modal>
    </div>
  )
}

export default function XiajiStudioModule({ csrfToken, projectId }: { csrfToken: string; projectId?: string }) {
  const navigate = useNavigate()
  const projectQuery = useQuery({
    queryKey: ["xiaji-project", projectId],
    queryFn: () => getXiajiProject(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  })

  useEffect(() => {
    if (projectId && projectQuery.isError) navigate(PATHS.director2, { replace: true })
  }, [navigate, projectId, projectQuery.isError])

  if (!projectId) return <XiajiHome csrfToken={csrfToken} />

  return (
    <div className="xiaji-studio">
      <div className="xiaji-project-bar">
        <Button type="text" icon={<ChevronLeft size={16} />} onClick={() => navigate(PATHS.director2)}>
          全部项目
        </Button>
        <Typography.Title level={4} className="xiaji-project-bar-name">
          {projectQuery.data?.name || "导台2 项目"}
        </Typography.Title>
      </div>
      <Tabs
        className="xiaji-studio-tabs"
        defaultActiveKey="ingest"
        items={[
          {
            key: "ingest",
            label: "内容库",
            children: <ContentLibrary csrfToken={csrfToken} projectId={projectId} />,
          },
          {
            key: "assets",
            label: "资产库",
            children: <XiajiAssetsModule csrfToken={csrfToken} projectId={projectId} />,
          },
          {
            key: "workshop",
            label: "剧集工坊",
            children: <XiajiWorkshopModule csrfToken={csrfToken} projectId={projectId} />,
          },
          ...PLACEHOLDERS.map((item) => ({
            key: item.key,
            label: item.label,
            children: (
              <Empty
                className="xiaji-placeholder"
                description={`${item.hint}当前项目：${projectQuery.data?.name || "未命名"}。`}
              />
            ),
          })),
        ]}
      />
    </div>
  )
}
