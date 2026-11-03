import { useEffect, useState } from "react"
import { Alert, Button, Input, Modal, Select, Space, Table, message } from "antd"
import { Copy, Download, FolderPlus } from "lucide-react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { createProject, director2ErrorDetail, listAssets, listDocuments, listEpisodes, listProjects, type Director2Asset, type Director2Document, type Director2Episode, type Director2Project } from "../api"
import { ASSISTANT_API, artifactLabels, assistantMutate, type ApplicationPreview, type AssistantArtifact } from "./api"
import { primaryScript } from "../script-document"

function appliedMessage(artifact: AssistantArtifact): string {
  if (artifact.artifact_type === "script") return "已写入当前剧本；其他分集与已有成片保留"
  if (artifact.artifact_type === "episodes") return "分集大纲已写入当前剧本，可继续创作对应集正文"
  if (artifact.artifact_type === "storyboard") return "已采纳到工程：分集已写入剧集工坊"
  if (artifact.artifact_type === "assets") {
    const counts = new Map<string, number>()
    for (const asset of artifact.data.assets || []) counts.set(asset.kind, (counts.get(asset.kind) || 0) + 1)
    const detail = [["character", "角色"], ["scene", "场景"], ["prop", "道具"]]
      .map(([kind, label]) => (counts.get(kind) ? `${counts.get(kind)} ${label}` : ""))
      .filter(Boolean)
      .join("、")
    return detail ? `已采纳到工程：${detail}已写入资产库` : "已采纳到工程"
  }
  return "已采纳到工程"
}

export default function ArtifactDialog({ artifact, projectId, csrfToken, onClose, onApplied }: {
  artifact: AssistantArtifact | null; projectId: string | null; csrfToken: string; onClose: () => void; onApplied: () => Promise<void>
}) {
  const [projects, setProjects] = useState<Director2Project[]>([])
  const [target, setTarget] = useState<string | undefined>(projectId || undefined)
  const [assets, setAssets] = useState<Director2Asset[]>([])
  const [documents, setDocuments] = useState<Director2Document[]>([])
  const [episodes, setEpisodes] = useState<Director2Episode[]>([])
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<ApplicationPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [newName, setNewName] = useState("")
  const [loadingTargets, setLoadingTargets] = useState(false)
  const mainScript = primaryScript(documents)
  const scriptDraft = artifact?.artifact_type === "script" || artifact?.artifact_type === "episodes"
  const effectiveMapping = scriptDraft ? { ...mapping, script_action: mapping.script_action || "append_episodes", ...(mainScript ? { document: mainScript.id } : {}) } : mapping
  const canApply = artifact && !["prompt", "plan"].includes(artifact.artifact_type)
  useEffect(() => {
    if (!artifact) return
    setTarget(projectId || undefined); setMapping({}); setPreview(null); setError(""); setNewName(artifact.title)
    listProjects().then(setProjects).catch(e => setError(director2ErrorDetail(e, "读取工程失败")))
  }, [artifact?.id, projectId])
  useEffect(() => {
    let alive = true
    setAssets([]); setDocuments([]); setEpisodes([]); setLoadingTargets(!!target)
    if (target && artifact) Promise.all([listAssets(target), listDocuments(target), listEpisodes(target)]).then(([a, d, e]) => { if (alive) { setAssets(a); setDocuments(d); setEpisodes(e) } }).catch(e => { if (alive) setError(director2ErrorDetail(e, "读取更新目标失败")) }).finally(() => { if (alive) setLoadingTargets(false) })
    return () => { alive = false }
  }, [target, artifact?.id])
  function map(key: string, value: string) { setMapping(current => ({ ...current, [key]: value })); setPreview(null) }
  async function prepare() {
    if (!artifact || !target) return
    setBusy(true); setError("")
    try { setPreview(await assistantMutate<ApplicationPreview>(csrfToken, `/artifacts/${artifact.id}/preview`, { project_id: target, mapping: effectiveMapping })) }
    catch (e) { setError(director2ErrorDetail(e, "生成变更预览失败")) }
    finally { setBusy(false) }
  }
  async function adopt() {
    if (!preview || !artifact) return
    setBusy(true); setError("")
    try {
      await assistantMutate(csrfToken, `/applications/${preview.id}/apply`)
      window.dispatchEvent(new CustomEvent("director-assistant-project-updated", { detail: { projectId: target } }))
      await onApplied(); message.success(appliedMessage(artifact)); onClose()
    } catch (e) { setError(director2ErrorDetail(e, "采纳失败，请重新预览变更")); setPreview(null) }
    finally { setBusy(false) }
  }
  async function createTarget() {
    setBusy(true)
    try { const project = await createProject(csrfToken, { name: newName.trim() || "未命名工程" }); setProjects(current => [project, ...current]); setTarget(project.id); setPreview(null) }
    catch (e) { setError(director2ErrorDetail(e, "创建工程失败")) }
    finally { setBusy(false) }
  }
  return <Modal title={artifact ? `${artifact.title} · 第 ${artifact.revision} 版` : "创作产物"} open={!!artifact} onCancel={() => { if (!busy) onClose() }} width={980} className="assistant-artifact-modal" zIndex={1200} centered styles={{ container: { maxHeight: "calc(100vh - 48px)", display: "flex", flexDirection: "column" }, body: { minHeight: 0, overflowY: "auto" }, footer: { flexShrink: 0 } }} footer={<Space>
    <Button icon={<Copy size={14} />} onClick={async () => { try { await navigator.clipboard.writeText(artifact?.content || ""); message.success("已复制全文") } catch { message.error("复制失败，请手动选择正文") } }}>复制</Button>
    <Button icon={<Download size={14} />} href={artifact ? `${ASSISTANT_API}/artifacts/${artifact.id}/export` : undefined}>导出 Markdown</Button>
    {canApply && !artifact.application_id && <Button onClick={prepare} loading={busy && !preview} disabled={!target || busy || loadingTargets}>预览写入变更</Button>}
    {canApply && !artifact.application_id && <Button type="primary" loading={busy && !!preview} disabled={!preview || busy} onClick={adopt}>采纳到工程</Button>}
    {artifact?.application_id && <Button disabled>已采纳</Button>}
  </Space>}>
    {artifact && <>
      <div className="assistant-artifact-meta">{artifactLabels[artifact.artifact_type]} · {artifact.application_id ? "已采纳" : "会话草稿"}</div>
      <div className="assistant-markdown assistant-artifact-content"><Markdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={["img"]}>{artifact.content}</Markdown></div>
      {canApply && !artifact.application_id && <div className="assistant-application-target">
        <label>采纳到工程</label><Select aria-label="采纳目标工程" showSearch optionFilterProp="label" placeholder="选择工程" value={target} disabled={!!projectId || busy} onChange={value => { setTarget(value); setMapping({}); setPreview(null) }} options={projects.map(p => ({ label: p.name, value: p.id }))} />
        {!projectId && <div className="assistant-create-target"><Input aria-label="新工程名称" value={newName} onChange={e => setNewName(e.target.value)} maxLength={255} /><Button onClick={createTarget} loading={busy} icon={<FolderPlus size={14} />}>新建工程</Button></div>}
        {target && <>
          {scriptDraft && <div className="assistant-mapping-row"><span>当前剧本</span><span>{mainScript?.filename || "首次采纳后建立主剧本"}</span></div>}
          {artifact.artifact_type === "script" && artifact.data.section !== "setting" && mainScript && <div className="assistant-mapping-row"><span>写入范围</span><Select aria-label="剧本写入方式" disabled={busy || loadingTargets} value={mapping.script_action || "append_episodes"} onChange={v => map("script_action", v)} options={[{ label: "追加新分集（保留已有分集）", value: "append_episodes" }, { label: "更新草稿中的分集（保留其他分集）", value: "update_episodes" }]} /></div>}
          {artifact.data.assets?.map((a, i) => <div className="assistant-mapping-row" key={i}><span>{a.name}</span><Select aria-label={`资产 ${a.name} 的写入目标`} value={mapping[`asset:${i}`] || ""} onChange={v => map(`asset:${i}`, v)} options={[{ label: "新增资产", value: "" }, ...assets.filter(v => v.kind === a.kind).map(v => ({ label: `更新：${v.name}`, value: v.id }))]} /></div>)}
          {artifact.artifact_type === "episodes" && <Alert type="info" showIcon title="大纲按集写入当前剧本，已有正文和制作镜头保留" />}
          {artifact.artifact_type === "storyboard" && artifact.data.episodes?.map(e => <div className="assistant-mapping-row" key={e.episode_num}><span>第{e.episode_num}集 · {e.title}</span><Select aria-label={`第${e.episode_num}集的写入目标`} value={mapping[`episode:${e.episode_num}`] ?? e.episode_id ?? ""} onChange={v => map(`episode:${e.episode_num}`, v)} options={[{ label: "新增分集", value: "" }, ...episodes.map(v => ({ label: `更新：第${v.episode_num}集 · ${v.title}`, value: v.id }))]} /></div>)}
        </>}
      </div>}
      {error && <Alert type="error" showIcon title={error} />}
      {preview && <Table size="small" pagination={false} rowKey="target_id" dataSource={preview.changes} columns={[{ title: "变更", dataIndex: "operation", render: (v: string) => v === "add" ? "新增" : "更新" }, { title: `目标工程：${preview.project_name}`, dataIndex: "label" }]} />}
    </>}
  </Modal>
}
