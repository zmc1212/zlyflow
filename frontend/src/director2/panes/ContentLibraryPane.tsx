// 内容库面板 —— 逐行复刻自 dev0914 z-admin/src/views/project/ContentLibraryPane.vue
// Vue → React 对应：ref→useState、computed→useMemo、onMounted→useEffect；
// ant-design-vue 组件 → antd 同名组件；API 调用首参补 csrfToken。
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import {
  Button,
  Collapse,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Tabs,
  Tag,
  Alert,
  message,
} from "antd"
import {
  FileText,
  Users,
  MapPin,
  Film,
  Package,
  Sparkles,
  BookOpen,
  FileSearch,
} from "lucide-react"
import DirectorAssetSummaryCard from "../../director/components/DirectorAssetSummaryCard"
import { normalizeDirectorAssetCard } from "../../director/components/director-asset-card"
import { contentLibraryHeaderTagText } from "./content-library-header"
import {
  hasVisualStyleContent,
  positioningEntries,
  type PositioningSection,
  type VisualStyleSection,
} from "./content-library-globals"
import ContentLibraryShotCard from "./content-library-shot-card"
import ShotPlanSlimProgress from "./shot-plan-slim-progress"
import {
  listDocuments,
  listJobs,
  deleteDocument,
  type Director2Document,
} from "../api"
import {
  applyShotPlanJobSnapshot,
  applyShotPlanStreamEvent,
  documentShotPlanHeaderTag,
  doneForEpisode,
  emptyShotPlanLiveState,
  episodeShotPlanError,
  isAssemblingShotPlan,
  isCurrentPlanningEpisode,
  isDocumentShotPlanning,
  isQueuedPlanningEpisode,
  markShotPlanLiveFinished,
  shotPlanEpisodeBadge,
  shotPlanProgressLabel,
  shotPlanSourceForEpisode,
  shotPlanStatusCopy,
  shotsForEpisode,
  sumShotDurationSec,
} from "../shot-plan-live"
import { streamH3PromptJobEvents } from "../workshop-prompt-stream"
import "./content-library.css"
import { director2DiagnosisPath } from "../paths"
import "../../director/components/director-asset-card.css"

interface ContentLibraryPaneProps {
  csrfToken: string
  projectId: string
}

// 剧本解析结果形状（原版为 JS 未标注，按模板取值字段补全）
type DocAnalysis = {
  summary?: string
  logs?: string[]
  positioning?: PositioningSection
  episodes?: Array<{
    episode_num: number
    title: string
    summary?: string
    shots_count?: number
    shots_source?: string
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
      duration_sec?: number | string
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
  visual_style?: VisualStyleSection
  production_advice?: string
}

type LibraryDocument = Omit<Director2Document, "analysis"> & { analysis?: DocAnalysis | null }

type AnalysisTabKey = "episodes" | "characters" | "scenes" | "props" | "globals" | "raw"

export default function ContentLibraryPane({
  csrfToken,
  projectId,
}: ContentLibraryPaneProps) {
  const navigate = useNavigate()
  const [documents, setDocuments] = useState<LibraryDocument[]>([])
  const [selectedDoc, setSelectedDoc] = useState<LibraryDocument | null>(null)
  const [loading, setLoading] = useState(true)
  const [formatModalVisible, setFormatModalVisible] = useState(false)
  const [activeTab, setActiveTab] = useState<AnalysisTabKey>("episodes")
  const [activeEpisodeKeys, setActiveEpisodeKeys] = useState<string[]>(["1"])
  const [hideShotPlanProgress, setHideShotPlanProgress] = useState(false)
  const [shotPlanLive, setShotPlanLive] = useState(() => emptyShotPlanLiveState())
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedDocIdRef = useRef<string | null>(null)
  const shotPlanBannerRef = useRef<HTMLDivElement | null>(null)
  const episodeHeaderRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const shotPlanToastJobRef = useRef("")
  const urlDocId = searchParams.get("doc")
  const urlTab = searchParams.get("tab")

  const headerGenreTag = contentLibraryHeaderTagText(selectedDoc?.analysis?.positioning?.genre)
  const headerWorldviewTag = contentLibraryHeaderTagText(selectedDoc?.analysis?.positioning?.worldview)
  const positioningList = positioningEntries(selectedDoc?.analysis?.positioning)
  const styleSectionHasContent = hasVisualStyleContent(selectedDoc?.analysis?.visual_style)
  const planning = isDocumentShotPlanning(selectedDoc)
  const planningJobId = String(selectedDoc?.shot_plan_job_id || "")
  const shotPlanHeaderTag = documentShotPlanHeaderTag(selectedDoc)
  const totalShotsCount = useMemo(() => {
    if (!selectedDoc?.analysis?.episodes) return 0
    return selectedDoc.analysis.episodes.reduce(
      (acc, ep) => acc + shotsForEpisode(ep, shotPlanLive, planning).length,
      0,
    )
  }, [selectedDoc, shotPlanLive, planning])
  const rawPlanStatus = shotPlanStatusCopy(shotPlanLive, planning)
  const planStatus = hideShotPlanProgress ? null : rawPlanStatus
  const liveDocIdRef = useRef<string | null>(null)

  function copyText(txt: string | null | undefined) {
    if (!txt) return
    navigator.clipboard.writeText(txt).then(() => {
      message.success("已复制到剪贴板")
    }).catch(() => {
      message.info("请手动复制内容")
    })
  }

  const loadDocs = useCallback(async (opts?: { selectId?: string; silent?: boolean }) => {
    if (!opts?.silent) setLoading(true)
    try {
      const res = await listDocuments(projectId)
      const list = (res || []) as unknown as LibraryDocument[]
      setDocuments(list)
      const preferred = opts?.selectId || urlDocId || selectedDocIdRef.current
      const next = (preferred && list.find((doc) => doc.id === preferred)) || list[0] || null
      setSelectedDoc(next)
      if (opts?.selectId) setActiveEpisodeKeys(["1"])
    } catch {
      if (!opts?.silent) message.error("加载文档列表失败")
    } finally {
      if (!opts?.silent) setLoading(false)
    }
  }, [projectId, urlDocId])

  useEffect(() => {
    const refresh = (event: Event) => {
      if ((event as CustomEvent).detail.projectId === projectId) void loadDocs({ silent: true })
    }
    window.addEventListener("director-assistant-project-updated", refresh)
    return () => window.removeEventListener("director-assistant-project-updated", refresh)
  }, [projectId, loadDocs])

  function rememberSelectedDoc(doc: LibraryDocument) {
    selectedDocIdRef.current = doc.id
    setSelectedDoc(doc)
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set("doc", doc.id)
      return next
    }, { replace: true })
  }

  const revealEpisodesWorkspace = useCallback((episodeNum?: number | null) => {
    setActiveTab("episodes")
    if (episodeNum != null) setActiveEpisodeKeys([String(episodeNum)])
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      if (selectedDocIdRef.current) next.set("doc", selectedDocIdRef.current)
      next.set("tab", "episodes")
      return next
    }, { replace: true })
    window.requestAnimationFrame(() => {
      shotPlanBannerRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
    })
  }, [setSearchParams])

  async function handleDeleteDoc(id: string) {
    try {
      await deleteDocument(csrfToken, projectId, id)
      message.success("文档已删除")
      await loadDocs()
    } catch {
      message.error("删除失败")
    }
  }

  useEffect(() => {
    selectedDocIdRef.current = selectedDoc?.id ?? null
  }, [selectedDoc?.id])

  useEffect(() => {
    setHideShotPlanProgress(false)
  }, [selectedDoc?.id, planningJobId])

  useEffect(() => {
    if (selectedDoc?.id === liveDocIdRef.current) return
    liveDocIdRef.current = selectedDoc?.id ?? null
    if (!planningJobId) setShotPlanLive(emptyShotPlanLiveState())
  }, [selectedDoc?.id, planningJobId])

  useEffect(() => {
    const allowed: AnalysisTabKey[] = ["episodes", "characters", "scenes", "props", "globals", "raw"]
    if (allowed.includes(urlTab as AnalysisTabKey)) setActiveTab(urlTab as AnalysisTabKey)
  }, [urlTab])

  useEffect(() => {
    if (!planningJobId) return
    revealEpisodesWorkspace()
  }, [planningJobId, revealEpisodesWorkspace])

  useEffect(() => {
    if (!planningJobId) {
      setShotPlanLive((prev) => markShotPlanLiveFinished(prev))
      return undefined
    }
    setShotPlanLive((prev) => (prev.jobId === planningJobId ? prev : emptyShotPlanLiveState(planningJobId)))
    const controller = new AbortController()
    let active = true
    void streamH3PromptJobEvents(projectId, planningJobId, (event) => {
      if (!active) return
      setShotPlanLive((prev) => (prev.jobId === planningJobId ? applyShotPlanStreamEvent(prev, event) : prev))
      if (event.event === "done") {
        if (shotPlanToastJobRef.current !== planningJobId) {
          shotPlanToastJobRef.current = planningJobId
          message.success({ content: "镜头规划完成，关闭本抽屉后按助手进度卡继续出片", duration: 6 })
        }
      }
      if (event.event === "error") {
        const detail = event.data && typeof event.data === "object" && "message" in event.data
          ? String((event.data as { message?: string }).message || "镜头规划未完成")
          : "镜头规划未完成"
        message.error(detail)
      }
      if (event.event === "episode_done" || event.event === "done" || event.event === "error") {
        void loadDocs({ silent: true, selectId: selectedDocIdRef.current || undefined })
      }
    }, {
      signal: controller.signal,
      shouldContinue: () => active,
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [planningJobId, projectId, loadDocs])

  useEffect(() => {
    if (!planning || !planningJobId) return undefined
    const timer = window.setInterval(() => {
      void (async () => {
        await loadDocs({ silent: true })
        try {
          const jobs = await listJobs(projectId)
          const job = jobs.find((item) => item.id === planningJobId)
          if (job?.payload) {
            setShotPlanLive((prev) => (
              prev.jobId === planningJobId ? applyShotPlanJobSnapshot(prev, job.payload) : prev
            ))
          }
        } catch {
          /* 轮询只作 SSE 兜底 */
        }
      })()
    }, 2500)
    return () => window.clearInterval(timer)
  }, [planning, planningJobId, projectId, loadDocs])

  useEffect(() => {
    if (!shotPlanLive.working || shotPlanLive.episodeNum == null) return
    const key = String(shotPlanLive.episodeNum)
    setActiveEpisodeKeys([key])
    window.requestAnimationFrame(() => {
      episodeHeaderRefs.current[key]?.scrollIntoView({ block: "nearest", behavior: "smooth" })
    })
  }, [shotPlanLive.working, shotPlanLive.episodeNum])

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
            查看剧本解析出的人物与场景，分镜在剧集工坊继续。
          </p>
        </div>

        <Button icon={<BookOpen size={15} />} onClick={() => setFormatModalVisible(true)}>
          标准剧本规范
        </Button>
      </div>

      {/* 加载与主内容 */}
      <Spin spinning={loading && documents.length > 0}>
        {loading && documents.length === 0 ? (
          <div className="content-library-loading" role="status" aria-busy="true" aria-label="正在加载剧本">
            <aside className="cl-loading-sidebar" aria-hidden="true">
              <span className="studio-skeleton-bar" style={{ width: "55%" }} />
              <span className="studio-skeleton-bar" style={{ width: "86%" }} />
              <span className="studio-skeleton-bar" style={{ width: "78%" }} />
              <span className="studio-skeleton-bar" style={{ width: "82%" }} />
            </aside>
            <div className="cl-loading-detail" aria-hidden="true">
              <span className="studio-skeleton-bar cl-loading-title" style={{ width: "34%" }} />
              <span className="studio-skeleton-bar" style={{ width: "24%" }} />
              <span className="studio-skeleton-bar" style={{ width: "92%" }} />
              <span className="studio-skeleton-bar" style={{ width: "84%" }} />
              <span className="studio-skeleton-bar" style={{ width: "58%" }} />
            </div>
          </div>
        ) : documents.length === 0 ? (
          <><div className="empty-doc-box">
            <div className="empty-icon-wrap">
              <FileText size={40} />
            </div>
            <h3>还没有剧本</h3>
            <p>关闭本抽屉后，在「剧本」页点「导入剧本」粘贴或上传正文。<br />集数来自剧本，镜头数和秒数由大模型按本集动作、对白规划。</p>
          </div><p className="empty-doc-assistant-hint"><Sparkles size={18} />也可以打开智能助手，从一个想法开始。</p></>
        ) : (
          <div className="content-layout">
            {/* 左侧文档列表 */}
            <div className="doc-list-sidebar">
              <div className="doc-list-header">
                <span>已导入剧本 ({documents.length})</span>
              </div>
              <div className="doc-items-scroll">
                {documents.map((doc) => (
                  <button
                    type="button"
                    key={doc.id}
                    className={`doc-item${selectedDoc && selectedDoc.id === doc.id ? " active" : ""}`}
                    aria-pressed={selectedDoc?.id === doc.id}
                    onClick={() => rememberSelectedDoc(doc)}
                  >
                    <div className="doc-item-title">
                      <FileText size={16} className="doc-icon" />
                      <span className="name" title={doc.filename}>{doc.filename}</span>
                    </div>
                    <div className="doc-item-meta">
                      <Tag color="purple">
                        {doc.analysis?.episodes?.length ? `${doc.analysis.episodes.length} 集` : "单篇"}
                      </Tag>
                      {(() => {
                        const tag = documentShotPlanHeaderTag(doc)
                        return tag ? <Tag color={tag.color}>{tag.text}</Tag> : null
                      })()}
                      <span className="time">{doc.created_at.slice(5, 16)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* 右侧剧本与分析详情 */}
            {selectedDoc && (
              <div className="doc-detail-main">
                {/* 概览栏 */}
                <div className="detail-top-card">
                  <div className="detail-top-header">
                    <div className="detail-top-info">
                      <h3 className="detail-title" title={selectedDoc.filename}>{selectedDoc.filename}</h3>
                      <div className="detail-tags">
                        <Tag color="purple">{selectedDoc.spine_template === "drama" ? "精品分镜剧" : "解说剧模板"}</Tag>
                        {shotPlanHeaderTag ? <Tag color={shotPlanHeaderTag.color}>{shotPlanHeaderTag.text}</Tag> : null}
                        {headerGenreTag ? <Tag color="blue" title={headerGenreTag}>{headerGenreTag}</Tag> : null}
                        {headerWorldviewTag ? <Tag color="cyan" title={headerWorldviewTag}>{headerWorldviewTag}</Tag> : null}
                        <span className="char-count">约 {selectedDoc.file_size} 字符</span>
                      </div>
                    </div>

                    <Space className="detail-top-actions" wrap>
                      <Button icon={<FileSearch size={15} />} onClick={() => navigate(director2DiagnosisPath({
                        projectId, documentId: selectedDoc.id,
                      }))}>剧本诊断</Button>

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

                  {planStatus?.kind === "working" ? (
                    <div ref={shotPlanBannerRef} className="shot-plan-slim-wrap">
                      <ShotPlanSlimProgress
                        live={shotPlanLive}
                        onDismiss={() => setHideShotPlanProgress(true)}
                      />
                    </div>
                  ) : planStatus?.kind === "error" ? (
                    <div ref={shotPlanBannerRef} className="shot-plan-slim-wrap is-error">
                      <Alert
                        type="warning"
                        showIcon
                        message={planStatus.title}
                        description={planStatus.description}
                        closable
                        onClose={() => setHideShotPlanProgress(true)}
                      />
                    </div>
                  ) : null}

                {/* 结构化多维展示 Tab */}
                <div className="analysis-tabs-wrap">
                  <Tabs
                    activeKey={activeTab}
                    onChange={(key) => {
                      const nextTab = key as AnalysisTabKey
                      setActiveTab(nextTab)
                      setSearchParams((current) => {
                        const next = new URLSearchParams(current)
                        next.set("tab", nextTab)
                        return next
                      }, { replace: true })
                    }}
                    type="card"
                    items={[
                      {
                        key: "episodes",
                        label: (
                          <span className="tab-label">
                            <Film size={15} />
                            分集与镜头 ({selectedDoc.analysis?.episodes?.length || 0}集 / {totalShotsCount}镜)
                            {planning ? ` · ${shotPlanProgressLabel(shotPlanLive)}` : ""}
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
                              items={selectedDoc.analysis.episodes.map((ep) => {
                                const liveShots = shotsForEpisode(ep, shotPlanLive, planning)
                                const source = shotPlanSourceForEpisode(ep, shotPlanLive)
                                const liveDone = doneForEpisode(ep.episode_num, shotPlanLive)
                                const planError = episodeShotPlanError(
                                  ep.episode_num,
                                  selectedDoc.analysis?.logs,
                                  liveDone?.error,
                                )
                                const currentPlanning = isCurrentPlanningEpisode(ep.episode_num, shotPlanLive, planning)
                                const queued = isQueuedPlanningEpisode(ep.episode_num, shotPlanLive, planning)
                                const assembling = currentPlanning && isAssemblingShotPlan(shotPlanLive)
                                const episodeBadge = shotPlanEpisodeBadge({
                                  source,
                                  planningCurrent: currentPlanning,
                                  queued,
                                  planError,
                                  shotCount: liveShots.length,
                                  durationSec: sumShotDurationSec(liveShots),
                                })
                                const showShotCountChip = episodeBadge.color !== "success"
                                return {
                                key: String(ep.episode_num),
                                className: currentPlanning ? "is-planning-episode" : queued ? "is-queued-episode" : "",
                                label: (
                                  <div
                                    className="ep-collapse-header"
                                    data-shot-plan-episode={ep.episode_num}
                                    ref={(node) => {
                                      episodeHeaderRefs.current[String(ep.episode_num)] = node
                                    }}
                                  >
                                    <div className="ep-title-group">
                                      <span className="ep-badge">第 {ep.episode_num} 集</span>
                                      <span className="ep-main-title">{ep.title}</span>
                                      {showShotCountChip ? (
                                        <Tag color="blue">{liveShots.length || 0} 个分镜</Tag>
                                      ) : null}
                                      <Tag color={episodeBadge.color}>{episodeBadge.text}</Tag>
                                    </div>
                                    {ep.summary && (
                                      <span className="ep-header-summary" title={ep.summary}>
                                        {ep.summary}
                                      </span>
                                    )}
                                    {planError ? (
                                      <span className="ep-plan-error" title={planError}>{planError}</span>
                                    ) : null}
                                  </div>
                                ),
                                children: (
                                  <div className="episode-shots-block">
                                    {currentPlanning && liveShots.length === 0 ? (
                                      <div className="shots-assembling-empty">正在写出本集镜头…</div>
                                    ) : null}
                                    <div className="shots-grid">
                                      {liveShots.map((shot, shotIndex) => (
                                      <ContentLibraryShotCard
                                        key={`${ep.episode_num}-${shot.shot_num}-${source || "live"}`}
                                        shot={shot}
                                        entering={shotPlanLive.lastCompletedEpisodeNum === ep.episode_num && source === "llm"}
                                        assembling={Boolean(assembling && shotIndex === liveShots.length - 1)}
                                        onCopyPrompt={copyText}
                                      />
                                      ))}
                                    </div>
                                  </div>
                                ),
                                }
                              })}
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
                            {selectedDoc.analysis.characters.map((char) => {
                              const asset = normalizeDirectorAssetCard("character", char)
                              return asset ? <DirectorAssetSummaryCard key={char.name} asset={asset} onCopyPrompt={copyText} /> : null
                            })}
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
                            {selectedDoc.analysis.scenes.map((sc) => {
                              const asset = normalizeDirectorAssetCard("scene", sc)
                              return asset ? <DirectorAssetSummaryCard key={sc.name} asset={asset} onCopyPrompt={copyText} /> : null
                            })}
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
                            {selectedDoc.analysis.props.map((pr) => {
                              const asset = normalizeDirectorAssetCard("prop", pr)
                              if (!asset) return null
                              return (
                                <DirectorAssetSummaryCard
                                  key={pr.name}
                                  asset={{
                                    ...asset,
                                    relatedCharacter: asset.relatedCharacter || "场景共用",
                                    count: asset.count ?? 1,
                                  }}
                                />
                              )
                            })}
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
                                {positioningList.map((entry) => (
                                  <div className="pos-item" key={entry.key}>
                                    {entry.label && <span className="k">{entry.label}：</span>}
                                    <span
                                      className={
                                        entry.label && entry.key !== "main_storyline"
                                          ? "v"
                                          : "v storyline-v"
                                      }
                                    >
                                      {entry.text}
                                    </span>
                                  </div>
                                ))}
                                {!positioningList.length && (
                                  <p className="global-empty">
                                    剧本未写「视频定位 / 故事定位」章节，或该章节没有可识别条目。完整原文见「剧本原文预览」。
                                  </p>
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
                              {!styleSectionHasContent && (
                                <p className="global-empty">
                                  剧本未写「统一视觉风格」章节。生图与分镜的画风取项目与资产上的画风设置，本节只作阅读。
                                </p>
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
