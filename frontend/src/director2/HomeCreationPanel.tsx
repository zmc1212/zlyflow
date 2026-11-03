import { useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Alert, Button, ConfigProvider, Input, InputNumber, Popover, Segmented, Select, Spin, Tag, Tooltip, Upload, type ThemeConfig, type UploadProps } from "antd"
import { ArrowUp, BookOpen, CircleHelp, FileSearch, FileText, History, ListOrdered, PenLine, Plus, Ratio, SlidersHorizontal, Upload as UploadIcon, X } from "lucide-react"
import { useDirectorAssistantHome } from "./assistant/DirectorAssistant"
import { director2ErrorDetail } from "./api"
import { director2DiagnosisPath } from "./paths"
import { createDiagnosis, extractFiles, getCapabilities } from "./script-diagnosis/api"
import { characterCount, DIMENSIONS } from "./script-diagnosis/model"
import { createHomeDrafts, HOME_CREATION_MODES, homeCreationTextLimit, homeDiagnosisPayload, homeProjectMessage, homeProjectRequest, homeTextLimit, type HomeCreationDraft, type HomeCreationMode } from "./home-creation"
import { creativeStyleText, emptyStoryTopics, removeStoryTopic, selectedStoryTopics, type CreativeStyle } from "./creative-presets"
import HomeCreativeOptions from "./HomeCreativeOptions"

const creationControlTheme: ThemeConfig = {
  token: { fontSize: 12, controlHeight: 32, controlHeightSM: 32, borderRadius: 8, fontFamily: '"CapCut Sans", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", Arial, sans-serif' },
  components: { Select: { optionFontSize: 12, optionHeight: 32 } },
}

const modeIcons = { import: UploadIcon, create: PenLine, novel: BookOpen, diagnose: FileSearch }

export default function HomeCreationPanel({ csrfToken, onTools }: { csrfToken: string; onTools: () => void }) {
  const assistant = useDirectorAssistantHome()
  const navigate = useNavigate()
  const [mode, setMode] = useState<HomeCreationMode>("create")
  const [drafts, setDrafts] = useState(createHomeDrafts)
  const [style, setStyle] = useState<CreativeStyle>({ presetId: "none", custom: "" })
  const [topics, setTopics] = useState(emptyStoryTopics)
  const [aspect, setAspect] = useState("9:16")
  const [episodes, setEpisodes] = useState(1)
  const [pendingMode, setPendingMode] = useState<HomeCreationMode | null>(null)
  const submitting = useRef(false)
  const extractionVersions = useRef<Record<HomeCreationMode, number>>({ import: 0, create: 0, novel: 0, diagnose: 0 })
  const diagnosisSubmission = useRef<{ signature: string; key: string } | null>(null)
  const capabilities = useQuery({ queryKey: ["script-diagnosis-capabilities"], queryFn: getCapabilities, staleTime: 60_000, retry: false })
  const config = HOME_CREATION_MODES.find(item => item.value === mode)!
  const draft = drafts[mode]
  const busy = assistant.creating || pendingMode !== null
  const projectOptions = { style: creativeStyleText(style), styleId: style.presetId, topics, aspectRatio: aspect, episodeCount: episodes }
  const selectedTopics = selectedStoryTopics(topics)
  const limit = homeCreationTextLimit(mode, draft, projectOptions, capabilities.data?.max_characters)
  const count = characterCount(draft.text)
  const overLimit = count > limit
  const unavailable = mode === "diagnose" ? !capabilities.data?.available : mode !== "import" && !assistant.available
  const canSubmit = Boolean(draft.text.trim() || mode === "create" && selectedTopics.length) && !busy && !draft.reading && !overLimit && !unavailable
  const formatHint = capabilities.data
    ? `${capabilities.data.extensions.map(ext => ext.replace(/^\./, "").toUpperCase()).join(" / ")}，单文件不超过 ${Math.round(capabilities.data.max_file_bytes / 1024 / 1024)}MB`
    : "正在读取支持的文件格式，也可以直接粘贴正文"

  function updateDraft(target: HomeCreationMode, patch: Partial<HomeCreationDraft>) {
    setDrafts(current => ({ ...current, [target]: { ...current[target], ...patch } }))
  }

  async function readFile(file: File) {
    const target = mode
    const caps = capabilities.data
    if (!caps) return
    const extension = "." + (file.name.split(".").pop() || "").toLowerCase()
    if (!caps.extensions.some(ext => ext.toLowerCase() === extension)) {
      updateDraft(target, { error: "请选择支持的文本或文档格式" }); return
    }
    if (file.size > caps.max_file_bytes) {
      updateDraft(target, { error: `请选择 ${Math.round(caps.max_file_bytes / 1024 / 1024)}MB 以内的文件` }); return
    }
    const version = ++extractionVersions.current[target]
    updateDraft(target, { reading: true, error: "" })
    try {
      const result = await extractFiles(csrfToken, [file])
      if (extractionVersions.current[target] !== version) return
      const source = result.sources[0]
      if (source?.error || !source?.text?.trim()) throw new Error(source?.error || "未读取到正文，请重新上传或直接粘贴")
      if (characterCount(source.text) > homeTextLimit(target, caps.max_characters)) throw new Error("正文超出当前入口的字数上限，请选择部分章节后上传；原有输入已保留")
      updateDraft(target, { text: source.text, filename: file.name, reading: false })
    } catch (error) {
      if (extractionVersions.current[target] === version) updateDraft(target, { reading: false, error: director2ErrorDetail(error, "读取文件失败，原有输入已保留") })
    }
  }

  function removeFile() {
    extractionVersions.current[mode] += 1
    updateDraft(mode, { filename: "", reading: false, error: "" })
  }

  const uploadProps: UploadProps = {
    accept: capabilities.data?.extensions.join(","), showUploadList: false, disabled: busy || draft.reading || !capabilities.data,
    beforeUpload: file => { void readFile(file); return false },
  }

  async function start() {
    if (submitting.current || !canSubmit) return
    const target = mode
    submitting.current = true
    setPendingMode(target)
    updateDraft(target, { error: "" })
    try {
      if (target === "diagnose") {
        const payload = homeDiagnosisPayload(draft)
        const signature = JSON.stringify(payload)
        if (diagnosisSubmission.current?.signature !== signature) diagnosisSubmission.current = { signature, key: crypto.randomUUID() }
        const created = await createDiagnosis(csrfToken, { ...payload, client_request_id: diagnosisSubmission.current.key })
        navigate(director2DiagnosisPath({ id: created.id }))
      } else {
        const request = homeProjectRequest(target, draft, projectOptions)
        if (target !== "import" && characterCount(homeProjectMessage(request)) > 50_000) throw new Error("原文与创作要求合计过长，请减少部分内容后重试")
        await assistant.startProject(request)
      }
    } catch (error) {
      updateDraft(target, { error: director2ErrorDetail(error, `${config.action}失败，内容已保留，请重试`) })
    } finally {
      submitting.current = false
      setPendingMode(null)
    }
  }

  return <ConfigProvider theme={creationControlTheme}><div className="dh-create-entry">
    <div className="dh-create-panel" aria-busy={busy || draft.reading}>
      <Segmented block className="dh-create-tabs" name="director-home-creation-mode" aria-label="开始创作的方式" value={mode} onChange={value => setMode(value as HomeCreationMode)} options={HOME_CREATION_MODES.map(item => {
        const Icon = modeIcons[item.value]
        return { value: item.value, label: item.label, icon: <Icon size={16} strokeWidth={1.6} aria-hidden="true" /> }
      })} disabled={busy} />
      <div className="dh-create-composer">
        <div className="dh-create-content">
          <div className="dh-source-slot">
            <Upload {...uploadProps} className="dh-source-upload"><Button type="text" className="dh-source-trigger" aria-label={config.uploadLabel} aria-description={formatHint} disabled={uploadProps.disabled}>
              <svg className="dh-source-border" aria-hidden="true"><rect x=".5" y=".5" rx="16" vectorEffect="non-scaling-stroke" /></svg>
              <span className="dh-source-symbol">{draft.reading ? <Spin size="small" /> : draft.filename ? <FileText size={24} strokeWidth={1.5} aria-hidden="true" /> : <span className="dh-source-add"><Plus size={12} strokeWidth={1.5} aria-hidden="true" /></span>}</span>
              <span className="dh-source-copy"><Tooltip title={draft.filename || undefined}><strong>{draft.filename || config.uploadLabel}</strong></Tooltip>
                {draft.filename ? <span>正文已读取，可在右侧编辑</span> : <Tooltip title={formatHint}><span className="dh-source-formats">格式要求 <CircleHelp size={11} aria-hidden="true" /></span></Tooltip>}
              </span>
            </Button></Upload>
            {(draft.filename || draft.reading) && <Tooltip title="移除文件，保留已读取的正文"><Button type="text" className="dh-source-remove" aria-label="移除上传文件" icon={<X size={14} />} onClick={removeFile} disabled={busy} /></Tooltip>}
          </div>
          <div className="dh-create-writing">
          {mode !== "diagnose" && selectedTopics.length > 0 && <div className="dh-story-topics" aria-label="已选故事选题">{selectedTopics.map(item => <Tag key={`${item.group}:${item.label}`} closeIcon={<X size={12} aria-label={`移除选题：${item.label}`} />} closable={!busy} onClose={() => setTopics(current => removeStoryTopic(current, item.group, item.label))}># {item.label}</Tag>)}</div>}
          <Input.TextArea className="dh-create-editor" aria-label={config.inputLabel} placeholder={config.placeholder} value={draft.text} onChange={event => updateDraft(mode, { text: event.target.value, error: "" })} disabled={busy || draft.reading} autoSize={false} onKeyDown={event => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); void start() }
          }} />
          </div>
        </div>
        <div className="dh-create-toolbar">
          <Tooltip title="上传或替换文本素材"><span><Upload {...uploadProps}><Button className="dh-create-tool dh-icon-tool" type="text" aria-label="上传或替换文本素材" icon={<Plus size={18} strokeWidth={1.5} />} disabled={uploadProps.disabled} /></Upload></span></Tooltip>
          <Tooltip title="创作工具与历史"><Button className="dh-create-tool dh-icon-tool" type="text" aria-label="更多创作工具与历史" icon={<SlidersHorizontal size={16} strokeWidth={1.6} />} onClick={onTools} disabled={busy} /></Tooltip>
          <span className="dh-create-divider" aria-hidden="true" />
          {mode === "diagnose" ? <>
            <Popover trigger="click" content={<dl className="dh-diagnosis-dimensions">{DIMENSIONS.map(item => <div key={item.key}><dt>{item.label}</dt><dd>{item.hint}</dd></div>)}</dl>}><Button type="text" className="dh-create-tool" icon={<FileSearch size={16} strokeWidth={1.6} />}>五项诊断</Button></Popover>
            <Button type="text" className="dh-create-tool" icon={<History size={16} strokeWidth={1.6} />} onClick={() => navigate(director2DiagnosisPath() + "?history=1")} disabled={busy}>诊断历史</Button>
          </> : <>
            <HomeCreativeOptions style={style} topics={topics} onStyleChange={setStyle} onTopicsChange={setTopics} disabled={busy} />
            <Select className="dh-create-tool dh-aspect-tool" aria-label="短剧画面比例" variant="borderless" size="small" prefix={<Ratio size={16} strokeWidth={1.6} aria-hidden="true" />} suffixIcon={null} popupMatchSelectWidth={120} value={aspect} onChange={setAspect} disabled={busy} options={["9:16", "16:9", "1:1"].map(value => ({ value, label: value }))} />
            <Popover trigger="click" content={<label className="dh-episode-option">计划集数<InputNumber aria-label="计划集数" value={episodes} min={1} max={100} precision={0} onChange={value => setEpisodes(value || 1)} disabled={busy} /></label>}><Button className="dh-create-tool" type="text" aria-label={`计划集数，当前 ${episodes} 集`} disabled={busy} icon={<ListOrdered size={16} strokeWidth={1.6} aria-hidden="true" />}>集数：{episodes}</Button></Popover>
            {mode === "novel" && <Popover trigger="click" content={<label className="dh-adaptation-option">改编要求<Input.TextArea aria-label="小说改编要求" value={draft.requirements} onChange={event => updateDraft("novel", { requirements: event.target.value })} maxLength={1000} rows={4} placeholder="例如：保留人物关系，强化悬疑，每集结尾留一个反转" /></label>}><Button className="dh-create-tool" type="text" disabled={busy} icon={<PenLine size={16} strokeWidth={1.6} />}>改编要求{draft.requirements.trim() && <span className="dh-option-dot" aria-label="已填写" />}</Button></Popover>}
          </>}
          <span className="dh-create-toolbar-spacer" />
          <span className={`dh-create-count${overLimit ? " is-over-limit" : ""}`} aria-live="polite">{count.toLocaleString()} /{limit.toLocaleString()}字</span>
          <Tooltip title={config.action}><Button type="primary" shape="circle" className="dh-start-project" aria-label={config.action} icon={<ArrowUp size={18} strokeWidth={1.8} />} loading={busy} disabled={!canSubmit} onClick={() => void start()} /></Tooltip>
        </div>
      </div>
    </div>
    {draft.error && <Alert type="error" showIcon title={draft.error} />}
    {overLimit && <Alert type="warning" showIcon title={`已超出 ${limit.toLocaleString()} 字，请减少部分内容；输入已保留`} />}
    {capabilities.isError && <Alert type="warning" showIcon title="暂时无法读取文件能力，可粘贴正文继续创作" action={<Button size="small" onClick={() => void capabilities.refetch()}>重试</Button>} />}
    {mode === "diagnose" && capabilities.data && !capabilities.data.available && <Alert type="warning" showIcon title={capabilities.data.unavailable_reason || "诊断服务暂不可用，已有报告仍可查看"} />}
    <p className="dh-create-hint">{config.hint}</p>
    {!assistant.available && (mode === "create" || mode === "novel") && <Button type="link" onClick={onTools}>查看助手状态与模型设置</Button>}
  </div></ConfigProvider>
}
