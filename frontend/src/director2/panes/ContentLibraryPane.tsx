// 内容库面板 —— 逐行复刻自 dev0914 z-admin/src/views/project/ContentLibraryPane.vue
// Vue → React 对应：ref→useState、computed→useMemo、onMounted→useEffect；
// ant-design-vue 组件 → antd 同名组件；API 调用首参补 csrfToken。
import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Button,
  Col,
  Collapse,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Upload,
  message,
} from "antd"
import {
  Plus,
  FileText,
  Users,
  MapPin,
  Film,
  Package,
  Sparkles,
  BookOpen,
  Activity,
  MessageSquareQuote,
} from "lucide-react"
import {
  listDocuments,
  createDocument,
  deleteDocument,
  transferAssetsFromDoc,
  transferEpisodesFromDoc,
  director2ErrorDetail,
  type Director2Document,
} from "../api"
import "./content-library.css"

interface ContentLibraryPaneProps {
  csrfToken: string
  projectId: string
  onAssetsTransferred: () => void
  onEpisodesTransferred: () => void
}

// 剧本解析结果形状（原版为 JS 未标注，按模板取值字段补全）
type DocAnalysis = {
  summary?: string
  positioning?: {
    genre?: string
    worldview?: string
    duration_per_episode?: string
    shots_per_episode?: string | number
    main_storyline?: string
  }
  episodes?: Array<{
    episode_num: number
    title: string
    summary?: string
    shots_count?: number
    shots?: Array<{
      shot_num: number
      title?: string
      camera?: string
      scene?: string
      characters?: string[]
      props?: string[]
      action?: string
      dialogue?: string
      audio?: string
      subtitle?: string
      visual_prompt?: string
    }>
  }>
  characters?: Array<{
    name: string
    role?: string
    age?: string
    gender?: string
    shots_count?: number
    fixed_props?: string[]
    description?: string
    visual_prompt?: string
  }>
  scenes?: Array<{
    name: string
    type?: string
    shots_count?: number
    description?: string
    elements?: string[]
  }>
  props?: Array<{
    name: string
    kind?: string
    related_character?: string
    count?: number
  }>
  visual_style?: { description?: string; prohibited?: string }
  production_advice?: string
}

type LibraryDocument = Omit<Director2Document, "analysis"> & { analysis?: DocAnalysis | null }

type ImportFormState = {
  filename: string
  spine_template: string
  visual_style: string
  raw_text: string
  input_mode: string
}

type AnalysisTabKey = "episodes" | "characters" | "scenes" | "props" | "globals" | "raw"

export default function ContentLibraryPane({
  csrfToken,
  projectId,
  onAssetsTransferred,
  onEpisodesTransferred,
}: ContentLibraryPaneProps) {
  const [documents, setDocuments] = useState<LibraryDocument[]>([])
  const [selectedDoc, setSelectedDoc] = useState<LibraryDocument | null>(null)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [transferring, setTransferring] = useState(false)
  const [transferringEp, setTransferringEp] = useState(false)
  const [importModalVisible, setImportModalVisible] = useState(false)
  const [formatModalVisible, setFormatModalVisible] = useState(false)
  const [selectedScriptFileName, setSelectedScriptFileName] = useState("")
  const [activeTab, setActiveTab] = useState<AnalysisTabKey>("episodes")
  const [activeEpisodeKeys, setActiveEpisodeKeys] = useState<string[]>(["1"])
  const [importForm, setImportForm] = useState<ImportFormState>({
    filename: "",
    spine_template: "drama",
    visual_style: "chinese_period_drama",
    raw_text: "",
    input_mode: "paste",
  })

  // 计算所有镜头的总数
  const totalShotsCount = useMemo(() => {
    if (!selectedDoc?.analysis?.episodes) return 0
    return selectedDoc.analysis.episodes.reduce((acc, ep) => acc + (ep.shots?.length || 0), 0)
  }, [selectedDoc])

  function getPropTagColor(kind?: string): string {
    if (kind === "人物固定道具") return "orange"
    if (kind === "场景陈设道具") return "cyan"
    return "blue"
  }

  function getCharGradient(name: string): { background: string } {
    const gradients = [
      "linear-gradient(135deg, #6366f1 0%, #a855f7 100%)",
      "linear-gradient(135deg, #3b82f6 0%, #2dd4bf 100%)",
      "linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)",
      "linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)",
      "linear-gradient(135deg, #10b981 0%, #06b6d4 100%)",
    ]
    const charCode = (name || "").charCodeAt(0) || 0
    return { background: gradients[charCode % gradients.length] }
  }

  function copyText(txt: string | null | undefined) {
    if (!txt) return
    navigator.clipboard.writeText(txt).then(() => {
      message.success("已复制到剪贴板")
    }).catch(() => {
      message.info("请手动复制内容")
    })
  }

  const loadDocs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listDocuments(projectId)
      const list = (res || []) as unknown as LibraryDocument[]
      setDocuments(list)
      if (list.length > 0) {
        setSelectedDoc(list[0])
        setActiveEpisodeKeys(["1"])
      } else {
        setSelectedDoc(null)
      }
    } catch {
      message.error("加载文档列表失败")
    } finally {
      setLoading(false)
    }
  }, [projectId])

  function openImportModal() {
    setImportForm({
      filename: "",
      spine_template: "drama",
      visual_style: "chinese_period_drama",
      raw_text: "",
      input_mode: "paste",
    })
    setSelectedScriptFileName("")
    setImportModalVisible(true)
  }

  function handleScriptFile(file: File): boolean {
    const filename = String(file?.name || "")
    if (!/\.(md|markdown)$/i.test(filename)) {
      message.warning("请选择 Markdown 文件（.md 或 .markdown）")
      return false
    }
    const reader = new FileReader()
    reader.onload = () => {
      const text = typeof reader.result === "string" ? reader.result : ""
      if (!text.trim()) {
        message.warning("所选 Markdown 文件内容为空")
        return
      }
      setImportForm((prev) => ({
        ...prev,
        raw_text: text,
        filename: filename.replace(/\.(md|markdown)$/i, ""),
        input_mode: "file",
      }))
      setSelectedScriptFileName(filename)
      message.success(`已读取 ${filename}`)
    }
    reader.onerror = () => message.error("读取 Markdown 文件失败")
    reader.readAsText(file, "utf-8")
    return false
  }

  async function handleImportSubmit() {
    if (!importForm.raw_text.trim()) {
      message.warning("请填写或粘贴剧本正文")
      return
    }
    setImporting(true)
    try {
      await createDocument(csrfToken, projectId, {
        ...importForm,
        input_mode: importForm.input_mode || "paste",
      })
      message.success("剧本文档导入并解析成功，已拆解镜头、人物、道具与场景")
      setImportModalVisible(false)
      await loadDocs()
    } catch (err) {
      message.error(director2ErrorDetail(err, "导入失败"))
    } finally {
      setImporting(false)
    }
  }

  async function handleDeleteDoc(id: string) {
    try {
      await deleteDocument(csrfToken, projectId, id)
      message.success("文档已删除")
      await loadDocs()
    } catch {
      message.error("删除失败")
    }
  }

  async function handleTransferAssets() {
    if (!selectedDoc) return
    setTransferring(true)
    try {
      const res = await transferAssetsFromDoc(csrfToken, projectId, selectedDoc.id)
      const t = res.transferred
      message.success(`已成功转入资产库：${t.characters} 角色、${t.scenes} 场景、${t.props} 道具`)
      onAssetsTransferred()
    } catch (err) {
      message.error(director2ErrorDetail(err, "转入资产库失败"))
    } finally {
      setTransferring(false)
    }
  }

  async function handleTransferEpisodes() {
    if (!selectedDoc) return
    setTransferringEp(true)
    try {
      const res = await transferEpisodesFromDoc(csrfToken, projectId, selectedDoc.id)
      message.success(`已同步至剧集工坊：共 ${res.transferred_episodes} 集、${res.transferred_shots} 个分镜`)
      onEpisodesTransferred()
    } catch (err) {
      message.error(director2ErrorDetail(err, "同步至剧集工坊失败"))
    } finally {
      setTransferringEp(false)
    }
  }

  // 快速填入官方范例文本
  function fillSampleData() {
    setImportForm((prev) => ({
      ...prev,
      filename: "《寒门硕士：穿越古代逆袭记》第一季——AI视频详细分镜版",
      spine_template: "drama",
      visual_style: "chinese_period_drama",
      raw_text: SAMPLE_SCRIPT,
    }))
  }

  async function quickImportSample() {
    setImporting(true)
    try {
      await createDocument(csrfToken, projectId, {
        filename: "《寒门硕士：穿越古代逆袭记》第一季——AI视频详细分镜版",
        spine_template: "drama",
        visual_style: "chinese_period_drama",
        raw_text: SAMPLE_SCRIPT,
      })
      message.success("已导入《寒门硕士》标准分镜剧本并完成结构化解析")
      await loadDocs()
    } catch {
      message.error("导入范例失败")
    } finally {
      setImporting(false)
    }
  }

  useEffect(() => {
    loadDocs()
  }, [loadDocs])

  return (
    <div className="content-library-pane d2-content-library">
      {/* 顶部操作栏 */}
      <div className="sub-pane-header">
        <div>
          <h2 className="sub-pane-title">内容库</h2>
          <p className="sub-pane-subtitle">
            导入标准分镜剧本，系统自动高精度拆解分集、镜头、人物、道具、场景及全局视觉设定，并支持全链路协同流转。
          </p>
        </div>

        <Space>
          <Button icon={<BookOpen size={15} />} onClick={() => setFormatModalVisible(true)}>
            标准剧本规范
          </Button>
          <Button type="primary" className="primary-btn" icon={<Plus size={16} />} onClick={openImportModal}>
            导入剧本文档
          </Button>
        </Space>
      </div>

      {/* 加载与主内容 */}
      <Spin spinning={loading}>
        {documents.length === 0 ? (
          <div className="empty-doc-box">
            <div className="empty-icon-wrap">
              <FileText size={40} />
            </div>
            <h3>暂无导入的剧本文档</h3>
            <p>支持导入符合《短剧详细分镜规范》的标准文档，系统将自动识别镜头、角色、道具与场景要素。</p>
            <Space>
              <Button type="primary" onClick={openImportModal}>立即导入剧本</Button>
              <Button onClick={quickImportSample}>一键导入《寒门硕士》标准范例</Button>
            </Space>
          </div>
        ) : (
          <div className="content-layout">
            {/* 左侧文档列表 */}
            <div className="doc-list-sidebar">
              <div className="doc-list-header">
                <span>已导入剧本 ({documents.length})</span>
              </div>
              <div className="doc-items-scroll">
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    className={`doc-item${selectedDoc && selectedDoc.id === doc.id ? " active" : ""}`}
                    onClick={() => setSelectedDoc(doc)}
                  >
                    <div className="doc-item-title">
                      <FileText size={16} className="doc-icon" />
                      <span className="name" title={doc.filename}>{doc.filename}</span>
                    </div>
                    <div className="doc-item-meta">
                      <Tag color="purple">
                        {doc.analysis?.episodes?.length ? `${doc.analysis.episodes.length} 集` : "单篇"}
                      </Tag>
                      <span className="time">{doc.created_at.slice(5, 16)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 右侧剧本与分析详情 */}
            {selectedDoc && (
              <div className="doc-detail-main">
                {/* 概览栏 */}
                <div className="detail-top-card">
                  <div className="detail-top-header">
                    <div>
                      <h3 className="detail-title">{selectedDoc.filename}</h3>
                      <div className="detail-tags">
                        <Tag color="purple">{selectedDoc.spine_template === "drama" ? "精品分镜剧" : "解说剧模板"}</Tag>
                        {selectedDoc.analysis?.positioning?.genre && (
                          <Tag color="blue">
                            {selectedDoc.analysis.positioning.genre}
                          </Tag>
                        )}
                        {selectedDoc.analysis?.positioning?.worldview && (
                          <Tag color="cyan">
                            {selectedDoc.analysis.positioning.worldview}
                          </Tag>
                        )}
                        <span className="char-count">约 {selectedDoc.file_size} 字符</span>
                      </div>
                    </div>

                    <Space>
                      <Button
                        type="primary"
                        loading={transferring}
                        className="transfer-btn"
                        onClick={handleTransferAssets}
                        icon={<Users size={15} />}
                      >
                        转入资产库
                      </Button>

                      <Button
                        loading={transferringEp}
                        className="sync-ep-btn"
                        onClick={handleTransferEpisodes}
                        icon={<Film size={15} />}
                      >
                        同步至剧集工坊
                      </Button>

                      <Popconfirm
                        title="确认删除该剧本文档？"
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                        onConfirm={() => handleDeleteDoc(selectedDoc.id)}
                      >
                        <Button danger type="text">删除</Button>
                      </Popconfirm>
                    </Space>
                  </div>

                  {/* 全文摘要 */}
                  {selectedDoc.analysis?.summary && (
                    <div className="summary-box">
                      <span className="summary-label">内容解析摘要：</span>
                      <p className="summary-text">{selectedDoc.analysis.summary}</p>
                    </div>
                  )}
                </div>

                {/* 结构化多维展示 Tab */}
                <div className="analysis-tabs-wrap">
                  <Tabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as AnalysisTabKey)}
                    type="card"
                    items={[
                      {
                        key: "episodes",
                        label: (
                          <span className="tab-label">
                            <Film size={15} />
                            分集与镜头 ({selectedDoc.analysis?.episodes?.length || 0}集 / {totalShotsCount}镜)
                          </span>
                        ),
                        children: !selectedDoc.analysis?.episodes?.length ? (
                          <div className="empty-sub-tab">
                            暂未识别到标准分集信息（可参考「标准剧本规范」采用「# 第X集」及「### 镜头X」编排）
                          </div>
                        ) : (
                          <div className="episodes-container">
                            <Collapse
                              activeKey={activeEpisodeKeys}
                              onChange={(keys) => setActiveEpisodeKeys(Array.isArray(keys) ? keys : [keys])}
                              bordered={false}
                              className="episodes-collapse"
                              items={selectedDoc.analysis.episodes.map((ep) => ({
                                key: String(ep.episode_num),
                                label: (
                                  <div className="ep-collapse-header">
                                    <div className="ep-title-group">
                                      <span className="ep-badge">第 {ep.episode_num} 集</span>
                                      <span className="ep-main-title">{ep.title}</span>
                                      <Tag color="blue">{ep.shots_count || ep.shots?.length || 0} 个分镜</Tag>
                                    </div>
                                    {ep.summary && (
                                      <span className="ep-header-summary" title={ep.summary}>
                                        {ep.summary}
                                      </span>
                                    )}
                                  </div>
                                ),
                                children: (
                                  /* 镜头卡片流 */
                                  <div className="shots-grid">
                                    {(ep.shots || []).map((shot) => (
                                      <div
                                        key={shot.shot_num}
                                        className="shot-card"
                                      >
                                        <div className="shot-card-header">
                                          <span className="shot-badge">镜头 {shot.shot_num}</span>
                                          <h4 className="shot-title">{shot.title}</h4>
                                          {shot.camera && <Tag color="purple">{shot.camera}</Tag>}
                                        </div>

                                        <div className="shot-meta-rows">
                                          {/* 场景 */}
                                          {shot.scene && (
                                            <div className="shot-meta-row">
                                              <span className="meta-lbl"><MapPin size={13} /> 场景：</span>
                                              <span className="meta-val scene-val">{shot.scene}</span>
                                            </div>
                                          )}

                                          {/* 人物 */}
                                          {shot.characters?.length ? (
                                            <div className="shot-meta-row">
                                              <span className="meta-lbl"><Users size={13} /> 人物：</span>
                                              <div className="tags-cluster">
                                                {shot.characters.map((c) => (
                                                  <Tag
                                                    key={c}
                                                    color="purple"
                                                  >
                                                    {c}
                                                  </Tag>
                                                ))}
                                              </div>
                                            </div>
                                          ) : null}

                                          {/* 道具 */}
                                          {shot.props?.length ? (
                                            <div className="shot-meta-row">
                                              <span className="meta-lbl"><Package size={13} /> 道具：</span>
                                              <div className="tags-cluster">
                                                {shot.props.map((p) => (
                                                  <Tag
                                                    key={p}
                                                    color="orange"
                                                  >
                                                    {p}
                                                  </Tag>
                                                ))}
                                              </div>
                                            </div>
                                          ) : null}

                                          {/* 动作 */}
                                          {shot.action && (
                                            <div className="shot-meta-row">
                                              <span className="meta-lbl"><Activity size={13} /> 动作：</span>
                                              <span className="meta-val">{shot.action}</span>
                                            </div>
                                          )}

                                          {/* 台词 */}
                                          {shot.dialogue && (
                                            <div className="shot-meta-row dialogue-row">
                                              <span className="meta-lbl"><MessageSquareQuote size={13} /> 台词：</span>
                                              <div className="dialogue-bubble">{shot.dialogue}</div>
                                            </div>
                                          )}

                                          {/* 音效与字幕 */}
                                          {(shot.audio || shot.subtitle) && (
                                            <div className="shot-meta-row audio-row">
                                              {shot.audio && <span className="audio-text">🔊 {shot.audio}</span>}
                                              {shot.subtitle && <span className="subtitle-text">💬 {shot.subtitle}</span>}
                                            </div>
                                          )}

                                          {/* AI 生图提示词 */}
                                          {shot.visual_prompt && (
                                            <div className="shot-prompt-box">
                                              <div className="prompt-head">
                                                <span><Sparkles size={12} /> AI 画面提示词 (Prompt)</span>
                                                <Button type="link" size="small" className="copy-link" onClick={() => copyText(shot.visual_prompt)}>
                                                  复制
                                                </Button>
                                              </div>
                                              <p className="prompt-text">{shot.visual_prompt}</p>
                                            </div>
                                          )}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                ),
                              }))}
                            />
                          </div>
                        ),
                      },
                      {
                        key: "characters",
                        label: (
                          <span className="tab-label">
                            <Users size={15} />
                            识别人物 ({selectedDoc.analysis?.characters?.length || 0})
                          </span>
                        ),
                        children: !selectedDoc.analysis?.characters?.length ? (
                          <div className="empty-sub-tab">
                            未识别到人物角色
                          </div>
                        ) : (
                          <div className="cards-grid">
                            {selectedDoc.analysis.characters.map((char) => (
                              <div
                                key={char.name}
                                className="character-card"
                              >
                                <div className="char-header">
                                  <div className="char-avatar" style={getCharGradient(char.name)}>
                                    {char.name.slice(0, 1)}
                                  </div>
                                  <div className="char-title-meta">
                                    <div className="char-name-row">
                                      <h4 className="char-name">{char.name}</h4>
                                      <Tag color="blue">{char.role}</Tag>
                                      {char.age && <Tag color="cyan">{char.age}</Tag>}
                                      <Tag color={char.gender === "女" ? "magenta" : "geekblue"}>
                                        {char.gender}
                                      </Tag>
                                    </div>
                                    <span className="shots-stat">出现分镜：{char.shots_count || 0} 次</span>
                                  </div>
                                </div>

                                {/* 固定道具 */}
                                {char.fixed_props?.length ? (
                                  <div className="char-props-section">
                                    <span className="prop-lbl"><Package size={13} /> 固定道具：</span>
                                    <div className="tags-cluster">
                                      {char.fixed_props.map((fp) => (
                                        <Tag key={fp} color="orange">
                                          {fp}
                                        </Tag>
                                      ))}
                                    </div>
                                  </div>
                                ) : null}

                                {/* 外观设定 */}
                                <div className="char-desc-section">
                                  <p className="char-desc">{char.description}</p>
                                </div>

                                {/* 人物一致性提示词 */}
                                {char.visual_prompt && (
                                  <div className="char-prompt-section">
                                    <div className="prompt-head">
                                      <span><Sparkles size={12} /> 一致性生图 Prompt</span>
                                      <Button type="link" size="small" className="copy-link" onClick={() => copyText(char.visual_prompt)}>
                                        复制
                                      </Button>
                                    </div>
                                    <p className="prompt-text">{char.visual_prompt}</p>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        ),
                      },
                      {
                        key: "scenes",
                        label: (
                          <span className="tab-label">
                            <MapPin size={15} />
                            规划场景 ({selectedDoc.analysis?.scenes?.length || 0})
                          </span>
                        ),
                        children: !selectedDoc.analysis?.scenes?.length ? (
                          <div className="empty-sub-tab">
                            未识别到规划场景
                          </div>
                        ) : (
                          <div className="cards-grid">
                            {selectedDoc.analysis.scenes.map((sc) => (
                              <div
                                key={sc.name}
                                className="scene-card"
                              >
                                <div className="scene-header">
                                  <div className="scene-icon-wrap">
                                    <MapPin size={20} />
                                  </div>
                                  <div className="scene-meta">
                                    <h4 className="scene-name">{sc.name}</h4>
                                    <div className="scene-badges">
                                      <Tag color={sc.type === "固定场景" || sc.type === "固定场景库" ? "green" : "blue"}>
                                        {sc.type || "拍摄场地"}
                                      </Tag>
                                      {sc.shots_count ? <span className="shots-stat">引用 {sc.shots_count} 镜头</span> : null}
                                    </div>
                                  </div>
                                </div>

                                <p className="scene-desc">{sc.description}</p>

                                {/* 场景元素 */}
                                {sc.elements?.length ? (
                                  <div className="scene-elements">
                                    <span className="elem-lbl">陈设元素：</span>
                                    <div className="tags-cluster">
                                      {sc.elements.map((el) => (
                                        <Tag key={el} color="default">
                                          {el}
                                        </Tag>
                                      ))}
                                    </div>
                                  </div>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        ),
                      },
                      {
                        key: "props",
                        label: (
                          <span className="tab-label">
                            <Package size={15} />
                            关键道具 ({selectedDoc.analysis?.props?.length || 0})
                          </span>
                        ),
                        children: !selectedDoc.analysis?.props?.length ? (
                          <div className="empty-sub-tab">
                            未识别到道具要素
                          </div>
                        ) : (
                          <div className="props-grid">
                            {selectedDoc.analysis.props.map((pr) => (
                              <div
                                key={pr.name}
                                className="prop-card"
                              >
                                <div className="prop-card-top">
                                  <div className="prop-icon-wrap">
                                    <Package size={18} />
                                  </div>
                                  <div className="prop-name-box">
                                    <h4 className="prop-name">{pr.name}</h4>
                                    <Tag color={getPropTagColor(pr.kind)}>{pr.kind}</Tag>
                                  </div>
                                </div>
                                <div className="prop-card-bottom">
                                  <div className="prop-info-item">
                                    <span className="lbl">关联角色/场景：</span>
                                    <span className="val">{pr.related_character || "场景共用"}</span>
                                  </div>
                                  <div className="prop-info-item">
                                    <span className="lbl">出现频次：</span>
                                    <span className="val count-val">{pr.count || 1} 次</span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        ),
                      },
                      {
                        key: "globals",
                        label: (
                          <span className="tab-label">
                            <Sparkles size={15} />
                            视觉与全局设定
                          </span>
                        ),
                        children: (
                          <div className="globals-layout">
                            {/* 视频定位 */}
                            <div className="global-card">
                              <div className="global-card-title">
                                <Film size={16} />
                                <span>视频定位与世界观</span>
                              </div>
                              <div className="positioning-list">
                                {selectedDoc.analysis?.positioning?.genre && (
                                  <div className="pos-item">
                                    <span className="k">作品类型：</span>
                                    <span className="v">{selectedDoc.analysis.positioning.genre}</span>
                                  </div>
                                )}
                                {selectedDoc.analysis?.positioning?.worldview && (
                                  <div className="pos-item">
                                    <span className="k">世界观设定：</span>
                                    <span className="v">{selectedDoc.analysis.positioning.worldview}</span>
                                  </div>
                                )}
                                {selectedDoc.analysis?.positioning?.duration_per_episode && (
                                  <div className="pos-item">
                                    <span className="k">单集时长：</span>
                                    <span className="v">{selectedDoc.analysis.positioning.duration_per_episode}</span>
                                  </div>
                                )}
                                {selectedDoc.analysis?.positioning?.shots_per_episode && (
                                  <div className="pos-item">
                                    <span className="k">镜头规划：</span>
                                    <span className="v">{selectedDoc.analysis.positioning.shots_per_episode}</span>
                                  </div>
                                )}
                                {selectedDoc.analysis?.positioning?.main_storyline && (
                                  <div className="pos-item">
                                    <span className="k">主线剧情：</span>
                                    <span className="v storyline-v">{selectedDoc.analysis.positioning.main_storyline}</span>
                                  </div>
                                )}
                              </div>
                            </div>

                            {/* 统一视觉风格 */}
                            <div className="global-card">
                              <div className="global-card-title">
                                <Sparkles size={16} />
                                <span>统一视觉风格基调</span>
                              </div>
                              {selectedDoc.analysis?.visual_style?.description && (
                                <div className="style-quote">
                                  {selectedDoc.analysis.visual_style.description}
                                </div>
                              )}
                              {selectedDoc.analysis?.visual_style?.prohibited && (
                                <div className="prohibited-box">
                                  <span className="prohibited-title">⚠️ 禁止与负向提示词：</span>
                                  <p className="prohibited-text">{selectedDoc.analysis.visual_style.prohibited}</p>
                                </div>
                              )}
                            </div>

                            {/* 制作建议 */}
                            {selectedDoc.analysis?.production_advice && (
                              <div className="global-card full-width">
                                <div className="global-card-title">
                                  <BookOpen size={16} />
                                  <span>视频制作建议与控制策略</span>
                                </div>
                                <p className="advice-text">{selectedDoc.analysis.production_advice}</p>
                              </div>
                            )}
                          </div>
                        ),
                      },
                      {
                        key: "raw",
                        label: (
                          <span className="tab-label">
                            <FileText size={15} />
                            剧本原文预览
                          </span>
                        ),
                        children: (
                          <div className="script-preview-card">
                            <div className="preview-actions">
                              <span className="preview-info">全文共 {selectedDoc.raw_text?.length || 0} 字符</span>
                              <Button size="small" onClick={() => copyText(selectedDoc.raw_text)}>复制全文</Button>
                            </div>
                            <pre className="script-text-box">{selectedDoc.raw_text}</pre>
                          </div>
                        ),
                      },
                    ]}
                  />
                </div>
              </div>
            )}
          </div>
        )}
      </Spin>

      {/* 导入剧本弹窗 */}
      <Modal
        open={importModalVisible}
        title="导入剧本文档 (支持标准分镜格式)"
        confirmLoading={importing}
        okText="确认并深度解析"
        cancelText="取消"
        width={720}
        destroyOnHidden
        onOk={handleImportSubmit}
        onCancel={() => setImportModalVisible(false)}
        className="d2-content-library"
      >
        <Form layout="vertical">
          <div className="quick-fill-bar">
            <span className="quick-lbl">测试快捷操作：</span>
            <Button type="dashed" size="small" onClick={fillSampleData}>
              ✨ 一键填入《寒门硕士》官方标准分镜范例
            </Button>
          </div>

          <Form.Item label="剧本标题 / 作品名称" required>
            <Input
              value={importForm.filename}
              onChange={(event) => setImportForm({ ...importForm, filename: event.target.value })}
              placeholder="例如：《寒门硕士：穿越古代逆袭记》第一季"
            />
          </Form.Item>

          <Form.Item label="Markdown 文件">
            <div className="script-file-picker">
              <Upload accept=".md,.markdown,text/markdown" showUploadList={false} beforeUpload={handleScriptFile}>
                <Button icon={<FileText size={14} />}>选择 .md 文件</Button>
              </Upload>
              {selectedScriptFileName ? (
                <span className="script-file-name">{selectedScriptFileName}</span>
              ) : (
                <span className="script-file-hint">选择后会自动读取到下方编辑区</span>
              )}
            </div>
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="骨架模板">
                <Select
                  value={importForm.spine_template}
                  onChange={(value) => setImportForm({ ...importForm, spine_template: value })}
                  options={[
                    { value: "drama", label: "精品短剧 (分镜/镜头/人物/道具标准结构)" },
                    { value: "narrated", label: "解说剧 (画外旁白与画面)" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="视觉风格预设">
                <Select
                  value={importForm.visual_style}
                  onChange={(value) => setImportForm({ ...importForm, visual_style: value })}
                  options={[
                    { value: "chinese_period_drama", label: "写实古装剧 (宋式古典电影感)" },
                    { value: "anime", label: "动漫日漫二次元" },
                    { value: "guoman_fantasy", label: "3D玄幻国漫" },
                    { value: "realistic", label: "写实现代都市" },
                    { value: "post_apocalyptic", label: "废土科幻末日" },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item label="分镜剧本正文内容 (支持直接粘贴 Markdown / 文本)" required>
            <Input.TextArea
              value={importForm.raw_text}
              onChange={(event) => setImportForm({ ...importForm, raw_text: event.target.value })}
              placeholder="粘贴剧本文档，支持包含【视频定位、人物设定、视觉风格、分集分镜、固定场景库、人物一致性提示词】的标准格式..."
              rows={12}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 剧本规范说明弹窗 */}
      <Modal
        open={formatModalVisible}
        title="标准短剧分镜剧本编排规范"
        footer={null}
        width={700}
        onCancel={() => setFormatModalVisible(false)}
        className="d2-content-library"
      >
        <div className="format-guide">
          <p className="guide-lead">
            系统支持标准 Markdown 结构化剧本导入，能自动区分<strong>镜头、人物、道具、场景</strong>以及生成 <strong>AI Prompt</strong>：
          </p>
          <div className="guide-sections">
            <div className="guide-sec">
              <h5>1. 主要人物固定设定</h5>
              <pre className="guide-pre">{`
## 一、主要人物固定设定
### 沈砚——男主
17岁古代少年；清瘦高挑；剑眉；黑色长发、少年发髻；青灰粗布长衫。固定道具：旧木书箱、破旧古书、毛笔、砚台、宣纸。
            `}</pre>
            </div>

            <div className="guide-sec">
              <h5>2. 分集与分镜编排格式（兼容列表式与紧凑分号式）</h5>
              <pre className="guide-pre">{`
# 第1集：硕士穿越，醒来成了穷小子
**剧情：** 现代硕士意外穿越，醒来成为贫苦农家少年。

### 镜头1｜现代图书馆
- 人物：现代26岁沈砚
- 场景：现代大学图书馆深夜
- 道具：古籍、电脑、台灯、笔记本
- 动作：整理古籍、揉眼
- 镜头：中近景缓慢推进
- 台词：“这篇古文，到底是谁写的……”
- 提示词：现代大学图书馆深夜，年轻男硕士研究生研究古代文献，桌面古籍和电脑，暖黄台灯，电影感写实摄影。
            `}</pre>
            </div>

            <div className="guide-sec">
              <h5>3. 固定场景库与人物一致性提示词</h5>
              <pre className="guide-pre">{`
# 三、固定场景库
## 沈家
破旧茅草屋、土墙、木床、破木桌、陶碗、旧木箱、米缸、柴火。

# 四、人物一致性提示词
**沈砚：** 17岁中国古代少年，清瘦高挑，清秀脸庞，剑眉，沉静眼神，浅青灰色粗布长衫，气质沉稳聪慧。
            `}</pre>
            </div>
          </div>
        </div>
      </Modal>
    </div>
  )
}

const SAMPLE_SCRIPT = `# 《寒门硕士：穿越古代逆袭记》第一季——AI视频详细分镜版

## 视频定位
- 类型：古装 / 穿越 / 寒门逆袭 / 科举 / 爽文
- 世界观：架空“大晟王朝”
- 单集：约30秒
- 每集：6个镜头，每镜头约5秒
- 主线：现代硕士 → 穿越寒门 → 进入陆家 → 富家少爷伴读 → 夫子看中 → 免费入学 → 替少爷写诗 → 一诗成名

## 一、主要人物固定设定

### 沈砚——男主
17岁古代少年；清瘦高挑；清秀脸庞；剑眉；沉静眼神；黑色长发、少年发髻；前期穿洗得发白的青灰粗布长衫、旧布鞋；后期换浅青色长衫。气质贫寒但不卑微、聪明沉稳。固定道具：旧木书箱、破旧古书、毛笔、砚台、宣纸。

### 陆承安——富家少爷
16岁；白净少年脸；浅蓝锦袍；整齐束发；腰佩玉佩；贪玩骄傲但本性不坏。固定道具：折扇、玉佩、书卷。

### 林夫子——贵人
55岁；灰白胡须；深灰长袍；儒巾；严肃锐利；严厉、公正、爱才。固定道具：戒尺、《论语》、毛笔、砚台、木质讲案。

### 苏婉——女主
17岁；清秀温婉；纤细；黑色长发；淡青古装长裙；聪慧安静、喜欢读书。固定道具：书卷、团扇、绣花香囊。

### 周景明——竞争对手
18岁；修长英俊；深蓝锦袍；束发；腰佩玉佩；家境优越、自幼读书；性格骄傲，前期看不起寒门读书人。

## 二、统一视觉风格
> 中国古代架空王朝，大晟朝，写实古装电影风格，真实人物皮肤质感，真实布料纹理，柔和自然光，青砖黛瓦，宋式审美，低饱和古典色调，浅景深，电影构图，人物面部稳定，服装保持一致，写实而非动漫。

禁止：现代汽车、电线杆、手机、手表、拉链、现代家具、现代发型、西式建筑。

---

# 第1集：硕士穿越，醒来成了穷小子

**剧情：** 现代硕士沈砚意外穿越，醒来成为贫苦农家少年。

### 镜头1｜现代图书馆
- 人物：现代26岁沈砚
- 场景：现代大学图书馆深夜
- 道具：古籍、电脑、台灯、笔记本
- 动作：整理古籍、揉眼
- 镜头：中近景缓慢推进
- 台词：“这篇古文，到底是谁写的……”
- 提示词：现代大学图书馆深夜，年轻男硕士研究生研究古代文献，桌面古籍和电脑，暖黄台灯，电影感写实摄影。

### 镜头2｜穿越
- 场景：图书馆
- 道具：古籍
- 动作：古书掉落，沈砚伸手接，突然白光
- 镜头：快速推进→白光
- 音效：书落地、风声

### 镜头3｜破屋醒来
- 人物：沈砚、母亲
- 场景：破旧茅屋
- 道具：木床、陶碗、旧被褥
- 动作：沈砚猛然睁眼，看房顶
- 台词：“这里……是什么地方？”

### 镜头4｜母亲出现
- 动作：母亲端破陶碗进屋
- 台词：“砚儿，你终于醒了。”

### 镜头5｜家徒四壁
- 场景：土墙、木床、木桌、缺口陶碗
- 动作：沈砚环顾四周，表情从疑惑变震惊

### 镜头6｜最后半袋米
- 动作：母亲打开米缸，只有少量米
- 台词：“最后半袋米，也快吃完了。”
- 字幕：**堂堂硕士，穿越第一天，先解决吃饭问题。**

# 第2集：硕士的第一桶金

**剧情：** 沈砚利用知识解决村中灌溉问题，获得第一笔钱。

### 镜头1｜村口争论
人物：沈砚、村民；场景：村口田地；道具：农具、竹筐、木车；村民因灌溉争论。

### 镜头2｜沈砚开口
沈砚听完说道：“如果把水渠从这里引过去，不但能解决田里的水，还能少花一半工。”

### 镜头3｜画水渠
沈砚蹲地，用树枝画路线；俯拍树枝与泥地。

### 镜头4｜水渠成功
村民照做，水流进入田地，众人震惊。

### 镜头5｜众人询问
村民：“沈家小子，你什么时候懂这些了？”沈砚：“书上看的。”

### 镜头6｜第一桶金
沈砚拿钱回家，买回一袋粮食；母亲眼眶微红。沈砚：“至少，今天不用饿肚子了。”

# 第3集：进入陆家，当富家少爷伴读

### 镜头1｜陆家大门
青砖大宅、朱红大门、石狮；沈砚背旧书箱站门外。

### 镜头2｜管家考察
管家：“识字？”沈砚：“识一些。”

### 镜头3｜第一次见陆承安
陆承安穿浅蓝锦袍，坐石桌摇折扇，打量沈砚。

### 镜头4｜富少爷嘲笑
陆承安：“你这么穷，也读过书？”

### 镜头5｜第一次反击
沈砚：“读书，不看家里有几亩田。”陆承安脸色微变。

### 镜头6｜陆老爷观察
陆老爷远处看着：“这个孩子……倒是不卑不亢。”
结尾：沈砚正式成为陆承安伴读。

# 第4集：伴读竟然比少爷还会读书

### 镜头1｜陆家书房
沈砚、陆承安；书卷、砚台、毛笔；陆承安趴桌打瞌睡。

### 镜头2｜少爷求教
陆承安：“这文章到底是什么意思？”沈砚拿起书。

### 镜头3｜沈砚讲解
沈砚用简单方式解释，陆承安逐渐听懂。

### 镜头4｜私塾课堂
林夫子提问，陆承安答不上来，沈砚小声提醒。

### 镜头5｜夫子发现
林夫子突然转头：“沈砚，你来说。”所有学生看向沈砚。

### 镜头6｜惊艳回答
沈砚回答后，林夫子问：“你以前在哪里读书？”沈砚：“回夫子，学生没有正式读过书。”林夫子震惊。

# 第5集：夫子破格，免费入学

### 镜头1｜考经义
林夫子拿《论语》：“解释这一句。”沈砚回答。

### 镜头2｜考文章
林夫子：“若让你写一篇文章，如何立意？”沈砚认真回答。

### 镜头3｜众人震惊
周景明第一次认真看向沈砚。

### 镜头4｜夫子收徒
林夫子：“你可愿意拜我为师？”沈砚愣住。

### 镜头5｜说出难处
沈砚：“学生家贫，交不起束脩。”

### 镜头6｜免费入学
林夫子：“有才之人，不该因贫寒而废学。你的束脩，免了。”沈砚眼神微红。

# 第6集：替少爷写诗

### 镜头1｜书房求助
陆承安急得踱步：“父亲让我今日必须作诗。”

### 镜头2｜沈砚回应
沈砚：“那就自己写。”陆承安：“我要是会，还找你干什么？”

### 镜头3｜执笔
沈砚拿毛笔沉思。

### 镜头4｜写诗
特写笔尖、墨汁、宣纸。

### 镜头5｜少爷震惊
陆承安：“这是你写的？”沈砚：“记住，是你自己写的。”

### 镜头6｜文会
陆承安念诗，众人安静；名士：“好诗！此诗何人所作？”陆承安犹豫，画面切黑。

# 第7集：寒门才子，一诗成名

### 镜头1｜揭晓作者
陆承安：“我的伴读，沈砚。”众人哗然。

### 镜头2｜沈砚出现
沈砚站远处，众人打量他的破旧衣服。

### 镜头3｜议论
“一个伴读？”“他能写出这种诗？”

### 镜头4｜周景明挑战
周景明：“明日，我与你比试。”

### 镜头5｜沈砚接受
沈砚：“可以。”

### 镜头6｜旁白
周景明离开。旁白：“他不知道，自己从这一刻开始，已经走进了真正的读书人世界。”

# 第8集：才华带来的麻烦

### 镜头1｜茶楼议论
几个读书人在县城茶楼议论沈砚。

### 镜头2｜质疑
“一个穷伴读，怎么可能写出这种诗？”

### 镜头3｜诬陷
“我看，八成是偷来的。”

### 镜头4｜陆承安愤怒
陆承安：“他们凭什么说你？”沈砚：“因为他们不相信。”

### 镜头5｜证明
沈砚拿原稿，通过纸张、墨迹、书写习惯等细节证明文章为自己完成。

### 镜头6｜夫子评价
林夫子：“有才而不浮，有志而不狂。”沈砚拱手。林夫子：“继续读书。”

# 第9集：真正的大人物

### 镜头1｜大型文会
亭台、水榭、竹林、石桥，众多读书人聚集。

### 镜头2｜京城大儒
大儒出现，众人行礼，沈砚站在人群后。

### 镜头3｜被点名
大儒：“你就是沈砚？”沈砚：“学生正是。”

### 镜头4｜提出难题
大儒提出难题，其他学子沉默。

### 镜头5｜沈砚作答
沈砚思考后：“学生认为，此题真正的问题，并不在题面。”众人震惊。

### 镜头6｜乡试邀请
大儒：“明年乡试，你可敢参加？”沈砚：“学生，敢。”

# 第10集：寒门少年，踏上科举路

### 镜头1｜回到破屋
沈砚把赚来的钱放在桌上。

### 镜头2｜母亲拒收
母亲：“这是你的。”沈砚：“给家里买粮。”母亲：“你拿去读书。”

### 镜头3｜沈砚动容
沈砚沉默片刻，郑重点头。

### 镜头4｜陆家门口
陆承安背书箱：“沈砚，乡试一起去！”沈砚：“好。”

### 镜头5｜苏婉送书
苏婉递书：“愿你此去，得偿所愿。”沈砚：“多谢。”

### 镜头6｜第一季结尾
清晨，沈砚背书箱走在古道上，群山、晨雾、古树；镜头高空拉远。旁白：“那一年，他还只是一个吃不饱饭的寒门少年。没人知道，这个少年未来会走到哪里。”

大字：**乡试，开始。**

# 三、固定场景库

## 沈家
破旧茅草屋、土墙、木床、破木桌、陶碗、旧木箱、米缸、柴火。

## 陆家
青砖灰瓦大宅院、朱红木门、石狮、木质回廊、假山、水池、亭台。

## 私塾
木质讲案、书架、宣纸、砚台、毛笔、学生木桌、竹简。

## 文会
江南园林、水榭、竹林、石桥、亭台、灯笼、曲水。

## 古道
青石路、群山、晨雾、古树、竹林、远山。

# 四、人物一致性提示词

**沈砚：** 17岁中国古代少年，清瘦高挑，清秀脸庞，剑眉，沉静眼神，黑色长发，少年发髻，浅青灰色粗布长衫，旧布鞋，贫寒但不卑微，气质沉稳聪慧。

**陆承安：** 16岁中国古代富家少年，白净脸庞，少年感，浅蓝色锦袍，整齐束发，腰佩玉佩，手持折扇，富贵气质，略带骄傲。

**林夫子：** 55岁中国古代老夫子，灰白胡须，深灰色长袍，儒巾，严肃面容，锐利眼神，手持戒尺。

**苏婉：** 17岁中国古代少女，清秀温婉，纤细身材，黑色长发，淡青色古装长裙，清雅气质，手持书卷。

**周景明：** 18岁中国古代年轻书生，修长身材，英俊面容，深蓝色锦袍，束发，腰佩玉佩，气质骄傲。

# 五、视频制作建议

每个镜头控制在5秒左右。建议“1个镜头=1条视频”，生成后再剪辑成约30秒一集。这样更容易控制人物一致性、场景一致性、动作、台词和节奏。`
