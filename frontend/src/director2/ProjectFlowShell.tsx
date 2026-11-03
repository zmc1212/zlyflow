import { useCallback, useEffect, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Dropdown, Form, Input, Modal, Select, Tooltip, message } from "antd"
import { ArrowLeft, Boxes, FileText, Film, ListChecks, MoreHorizontal, Pencil, Scissors, Settings2, Sparkles } from "lucide-react"
import { getProject, listAssets, listDocuments, listEpisodes, listSkillPacks, transferEpisodesFromDoc, updateProject, director2ErrorDetail, type Director2Project, type Director2SkillPack } from "./api"
import ScriptWorkspace from "./panes/ScriptWorkspace"
import AssetsLibraryPane from "./panes/AssetsLibraryPane"
import EpisodeWorkshopPane from "./panes/EpisodeWorkshopPane"
import JobsCenterPane from "./panes/JobsCenterPane"
import SmartEditPane from "./smart-edit/SmartEditPane"
import { director2ProjectPath, director2HomePath, director2MenuEpisodeId, type Director2Route } from "./paths"
import { useDirectorAssistant } from "./assistant/DirectorAssistant"
import { MediaPreviewProvider } from "./media-preview"
import { packIdFromSelectValue, projectBoundSkillPackId, selectValueForPackId, skillPackSelectOptions } from "./skill-pack"
import { projectStageAccess, rememberProjectPosition, type ProjectMenu } from "./project-flow"
import { novelSource } from "./home-creation"
import "./project-detail.css"
import "./project-flow.css"

const STAGES = [
  { key: "content", label: "剧本", Icon: FileText },
  { key: "assets", label: "制作资产", Icon: Boxes },
  { key: "workshop", label: "分镜", Icon: Film },
] as const

export default function ProjectFlowShell({ csrfToken, route }: { csrfToken: string; route: Extract<Director2Route, { kind: "project" }> }) {
  const navigate = useNavigate()
  const location = useLocation()
  const projectId = route.projectId
  const activeMenu = route.menu
  const assistant = useDirectorAssistant()
  const [project, setProject] = useState<Director2Project | null>(null)
  const [skillPacks, setSkillPacks] = useState<Director2SkillPack[]>([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [savingPack, setSavingPack] = useState(false)
  const [editingInfo, setEditingInfo] = useState(false)
  const [savingInfo, setSavingInfo] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [infoForm] = Form.useForm<{ name: string; description: string }>()
  const infoSnapshot = useRef({ name: "", description: "" })
  const [inWorkshopDetail, setInWorkshopDetail] = useState(false)
  const [lastEpisode, setLastEpisode] = useState<string | null>(route.episodeId)
  const assetsPaneRef = useRef<{ fetchAssets: () => void | Promise<void> } | null>(null)
  const workshopPaneRef = useRef<{ fetchEpisodes: () => void | Promise<void> } | null>(null)
  const isWorkshopDetail = activeMenu === "workshop" && (!!route.episodeId || inWorkshopDetail)
  const flow = useQuery({ queryKey: ["director-project-flow", projectId], queryFn: async () => { const [documents, assets, episodes] = await Promise.all([listDocuments(projectId), listAssets(projectId), listEpisodes(projectId)]); return { documents, assets, episodes } }, staleTime: 10_000 })
  const access = projectStageAccess(flow.data || { documents: [], assets: [], episodes: [] })

  const loadProject = useCallback(async () => {
    try { setProject(await getProject(projectId)) }
    catch (error) { message.error(director2ErrorDetail(error, "未找到该短剧")) }
  }, [projectId])
  useEffect(() => { void loadProject() }, [loadProject])
  useEffect(() => { let alive = true; listSkillPacks().then(data => { if (alive) setSkillPacks(data.packs) }).catch(() => {}); return () => { alive = false } }, [])
  useEffect(() => {
    if (route.episodeId) setLastEpisode(route.episodeId)
    else if (route.menu === "edit") setLastEpisode(null)
    rememberProjectPosition(projectId, { menu: activeMenu, episodeId: route.episodeId, search: location.search })
  }, [projectId, activeMenu, route.episodeId, location.search])
  useEffect(() => { assistant.setOpen(activeMenu === "content" || activeMenu === "edit") }, [activeMenu, projectId, assistant.setOpen])
  const changed = useCallback(() => { void flow.refetch(); void loadProject(); void assetsPaneRef.current?.fetchAssets(); void workshopPaneRef.current?.fetchEpisodes() }, [flow.refetch, loadProject])
  useEffect(() => {
    const refresh = (event: Event) => { if ((event as CustomEvent).detail?.projectId === projectId) changed() }
    window.addEventListener("director-assistant-project-updated", refresh)
    return () => window.removeEventListener("director-assistant-project-updated", refresh)
  }, [projectId, changed])

  function navigateMenu(menu: ProjectMenu) {
    const episode = director2MenuEpisodeId({ targetMenu: menu, currentMenu: activeMenu, currentEpisodeId: route.episodeId, lastEpisodeId: lastEpisode })
    const doc = new URLSearchParams(location.search).get("doc")
    navigate(director2ProjectPath(projectId, menu, episode) + (doc && (menu === "content" || menu === "assets") ? `?doc=${encodeURIComponent(doc)}` : ""))
    if (menu !== "workshop") setInWorkshopDetail(false)
  }
  async function continueToWorkshop() {
    try {
      const documents = await listDocuments(projectId)
      const selectedId = new URLSearchParams(location.search).get("doc")
      const document = documents.find(doc => doc.id === selectedId) || documents[0]
      if (document?.shot_plan_job_id || document?.status === "planning") { message.info("镜头规划仍在进行，完成后即可继续"); return }
      if (document && Array.isArray(document.analysis?.episodes) && document.analysis.episodes.length) {
        // Append is intentionally non-destructive: existing episode IDs, takes and media remain intact.
        await transferEpisodesFromDoc(csrfToken, projectId, document.id, "append")
      }
      changed(); navigateMenu("workshop")
    } catch (error) { message.error(director2ErrorDetail(error, "进入分镜失败，请重试")) }
  }
  function editProjectInfo() {
    if (!project) return
    infoSnapshot.current = { name: project.name, description: project.description || "" }
    infoForm.resetFields(); infoForm.setFieldsValue(infoSnapshot.current); setEditingInfo(true)
  }
  async function saveInfo(values: { name: string; description: string }) {
    if (!project || savingInfo) return
    const changes: { name?: string; description?: string } = {}
    if (values.name.trim() !== infoSnapshot.current.name) changes.name = values.name.trim()
    if ((values.description || "") !== infoSnapshot.current.description) changes.description = values.description || ""
    if (!Object.keys(changes).length) { setEditingInfo(false); return }
    setSavingInfo(true)
    try { setProject(await updateProject(csrfToken, projectId, changes)); setEditingInfo(false); message.success("已保存基本信息") }
    catch (error) { message.error(director2ErrorDetail(error, "保存失败，请重试")) }
    finally { setSavingInfo(false) }
  }
  async function changePack(value: string) {
    if (savingPack) return
    setSavingPack(true)
    try { setProject(await updateProject(csrfToken, projectId, { extra: { skill_pack_id: packIdFromSelectValue(value) } })); message.success("已更新制作配方") }
    catch (error) { message.error(director2ErrorDetail(error, "更新制作配方失败")) }
    finally { setSavingPack(false) }
  }
  const source = novelSource(project?.extra)
  const tools = [
    { key: "assistant", label: "智能助手", icon: <Sparkles size={15}/>, onClick: () => assistant.setOpen(true) },
    { key: "edit", label: "智能剪辑", icon: <Scissors size={15}/>, onClick: () => navigateMenu("edit") },
    { key: "jobs", label: "全部任务", icon: <ListChecks size={15}/>, onClick: () => navigateMenu("jobs") },
    ...(source ? [{ key: "novel-source", label: "查看小说原作", icon: <FileText size={15}/>, onClick: () => setSourceOpen(true) }] : []),
    { type: "divider" as const },
    { key: "settings", label: "项目设置", icon: <Settings2 size={15}/>, onClick: () => setSettingsOpen(true) },
  ]
  return <MediaPreviewProvider><div className={`project-detail-layout project-flow-layout${activeMenu === "workshop" ? " is-workshop-focus" : ""}${activeMenu === "edit" ? " has-smart-edit" : ""}`}>
    <aside className="project-stage-rail" aria-label="项目阶段导航"><Tooltip title="返回我的短剧" placement="right"><Button type="text" aria-label="返回我的短剧" icon={<ArrowLeft size={19}/>} onClick={() => navigate(director2HomePath())}/></Tooltip><nav aria-label="创作阶段">{STAGES.map(({ key, label, Icon }) => <Tooltip key={key} placement="right" title={flow.data && !access[key] ? key === "assets" ? "先准备剧本正文" : "先拆解制作资产，也可在资产库继续" : label}><span><Button type="text" aria-label={label} aria-current={activeMenu === key ? "step" : undefined} className={activeMenu === key ? "is-selected" : ""} disabled={!!flow.data && !access[key]} onClick={() => navigateMenu(key)}><Icon size={19}/><span>{label}</span></Button></span></Tooltip>)}</nav><Dropdown trigger={["click"]} menu={{ items: tools }}><Button type="text" className="project-stage-tools" aria-label="任务与项目工具" icon={<Settings2 size={19}/>}/></Dropdown></aside>
    <div className="project-flow-body">
      {activeMenu !== "workshop" && <header className="project-flow-header"><div><span className="project-flow-name" title={project?.name}>{project?.name || "正在加载短剧…"}</span><Button type="text" size="small" aria-label="编辑基本信息" icon={<Pencil size={13}/>} disabled={!project} onClick={editProjectInfo}/></div><div><Dropdown trigger={["click"]} menu={{ items: tools }}><Button type="text" aria-label="项目更多操作" icon={<MoreHorizontal size={17}/>} /></Dropdown><Button type={assistant.open ? "default" : "text"} icon={<Sparkles size={14}/>} aria-pressed={assistant.open} onClick={() => assistant.setOpen(!assistant.open)}>智能助手</Button></div></header>}
      {flow.error && <Alert type="error" showIcon title="阶段状态加载失败" action={<Button size="small" onClick={() => void flow.refetch()}>重试</Button>}/>}
      <section className={`project-content-pane${activeMenu === "content" ? " is-script-workspace" : ""}${isWorkshopDetail ? " is-workshop-detail" : ""}${activeMenu === "workshop" && !isWorkshopDetail ? " is-workshop-overview" : ""}${activeMenu === "edit" ? " is-smart-edit" : ""}`}>
        {activeMenu === "content" && <ScriptWorkspace csrfToken={csrfToken} projectId={projectId} onChanged={changed}/>}
        {activeMenu === "assets" && <AssetsLibraryPane ref={assetsPaneRef} csrfToken={csrfToken} projectId={projectId} onChanged={changed} onBack={() => navigateMenu("content")} onContinue={continueToWorkshop}/>}
        {activeMenu === "workshop" && <div className="d2-workshop-host"><EpisodeWorkshopPane ref={workshopPaneRef} csrfToken={csrfToken} projectId={projectId} episodeId={route.episodeId} onDetailModeChange={setInWorkshopDetail} projectName={project?.name} projectControls={<><Button block type="text" icon={<Pencil size={14}/>} onClick={editProjectInfo}>编辑基本信息</Button><Button block type="text" icon={<Settings2 size={14}/>} onClick={() => setSettingsOpen(true)}>制作配方与设置</Button><Button block type="text" onClick={() => navigateMenu("jobs")}>全部任务</Button></>}/></div>}
        {activeMenu === "jobs" && <JobsCenterPane csrfToken={csrfToken} projectId={projectId}/>}
        {activeMenu === "edit" && <SmartEditPane csrfToken={csrfToken} projectId={projectId} episodeId={route.episodeId}/>}
      </section>
    </div>
    <Modal title="编辑基本信息" open={editingInfo} onOk={() => infoForm.submit()} onCancel={() => { if (!savingInfo) setEditingInfo(false) }} okText="保存" cancelText="取消" confirmLoading={savingInfo} mask={{ closable: !savingInfo }}><Form form={infoForm} layout="vertical" onFinish={saveInfo} disabled={savingInfo}><Form.Item name="name" label="剧本名称" rules={[{ required: true, whitespace: true, message: "请输入剧本名称" }, { max: 255, message: "最多 255 个字符" }]}><Input maxLength={255}/></Form.Item><Form.Item name="description" label="剧本简介"><Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }}/></Form.Item></Form></Modal>
    <Modal title="项目设置" open={settingsOpen} onCancel={() => { if (!savingPack) setSettingsOpen(false) }} footer={<Button onClick={() => setSettingsOpen(false)} disabled={savingPack}>完成</Button>}><label className="project-pack-setting">制作配方<Select aria-label="制作配方" value={selectValueForPackId(projectBoundSkillPackId(project))} options={skillPackSelectOptions(skillPacks)} loading={savingPack} disabled={savingPack || !skillPacks.length} onChange={value => void changePack(value)}/></label><p>剧本编辑与智能助手共用同一工作区，生成结果采纳后写入当前短剧。</p></Modal>
    <Modal title={`小说原作 · ${source?.name || ""}`} open={sourceOpen} onCancel={() => setSourceOpen(false)} width={880} footer={<Button onClick={() => setSourceOpen(false)}>关闭</Button>}>
      <p>原作独立保留，剧本编辑和采纳改编稿不会覆盖这里的内容。</p>
      <Input.TextArea aria-label="保存的小说原作" readOnly value={source?.text || ""} autoSize={{ minRows: 12, maxRows: 22 }} />
    </Modal>
  </div></MediaPreviewProvider>
}
