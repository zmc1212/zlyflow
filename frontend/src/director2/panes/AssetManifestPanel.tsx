import { useCallback, useEffect, useState } from "react"
import { Alert, Button, Checkbox, Collapse, Select, Space, Table, Tag, message } from "antd"
import { readManifest, extractManifest, actManifest, type ManifestState } from "../asset-manifest-api"
import { director2ErrorDetail } from "../api"
import { useCandidateDraft } from "../use-candidate-draft"

export default function AssetManifestPanel({ projectId, documentId, csrfToken }: { projectId: string; documentId: string; csrfToken: string }) {
  const [state, setState] = useState<ManifestState | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const draftKey = state?.job?.status === "awaiting_review" ? `asset-manifest:${projectId}:${documentId}:${state.job.id}:${state.job.revision}` : null
  const [choices, setChoices] = useCandidateDraft<Record<string, {asset_id?: string; look_id?: string}>>(draftKey, {})
  const [confirmed, setConfirmed] = useCandidateDraft(draftKey ? `${draftKey}:confirmed` : null, false)
  const load = useCallback(async () => {
    try { setState(await readManifest(projectId, documentId)); setError("") }
    catch (e) { setError(director2ErrorDetail(e, "读取资产清单失败")) }
  }, [projectId, documentId])
  useEffect(() => { setState(null); void load() }, [load])
  const job = state?.job
  const running = job && ["queued", "running"].includes(job.status)
  useEffect(() => { if (!running) return; const timer = setInterval(() => void load(), 2500); return () => clearInterval(timer) }, [running, load])
  useEffect(() => {
    if (!Object.keys(choices).length) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = "" }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [choices])
  const candidate = job?.status === "awaiting_review"
  const rows = candidate ? job.data.entries : state?.manifest?.entries || []
  async function restore(version: string) {
    if (!job) return
    setBusy(true)
    try { setState(await actManifest(csrfToken, projectId, documentId, job.id, {action: "restore", revision: job.revision, expected_version: state?.manifest?.version, version})); setError("") }
    catch (e) { setError(director2ErrorDetail(e, "恢复清单失败")) } finally { setBusy(false) }
  }
  async function perform(action: "extract" | "cancel" | "confirm") {
    setBusy(true)
    try {
      const next = action === "extract" ? await extractManifest(csrfToken, projectId, documentId)
        : await actManifest(csrfToken, projectId, documentId, job!.id, {action, revision: job!.revision, choices, issues_confirmed: confirmed})
      setState(next); setError(""); setChoices({}); setConfirmed(false)
      if (action === "confirm") message.success("全局资产清单已确认，图片可稍后在资产库补齐")
    } catch (e) { setError(director2ErrorDetail(e, "资产操作失败")) } finally { setBusy(false) }
  }
  return <Space orientation="vertical" style={{width: "100%", padding: 16}}>
    <Alert type="info" showIcon title="全局资产清单" description="按完整剧本提取角色、场景、道具与造型，逐项确认后用于镜头规划。已有图片和视频保留。" />
    {error && <Alert type="error" showIcon title={error} action={<Button onClick={() => void load()}>刷新</Button>} />}
    <Space><Tag color={state?.manifest?.status === "confirmed" ? "success" : "warning"}>{state?.manifest?.status === "confirmed" ? "已确认" : state?.manifest?.status === "stale" ? "剧本已变化，清单待更新" : "待提取确认"}</Tag>
      <Button type="primary" disabled={Boolean(running || candidate)} loading={busy} onClick={() => void perform("extract")}>提取全局资产</Button>
      {(running || candidate) && <Button disabled={busy} onClick={() => void perform("cancel")}>取消本次候选</Button>}
    </Space>
    {job && <Alert type={job.status === "failed" ? "error" : job.status === "succeeded" ? "success" : "info"} title={job.error || (job.status === "succeeded" ? "全局资产清单已确认" : job.data.message)} description={`已覆盖 ${job.data.coverage?.length || 0} 个剧本区块，共 ${job.data.coverage?.reduce((sum, row) => sum + row.characters, 0) || 0} 字符；完整输入与响应保存在任务详情。`} />}
    {candidate && job.data.issues.length > 0 && <Alert type="warning" title={`${job.data.issues.length} 项需要核对`} description={<><Collapse items={[{key: "issues", label: "展开身份与造型疑点", children: <ul>{job.data.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>}]} /><Checkbox checked={confirmed} onChange={e => setConfirmed(e.target.checked)}>我已核对歧义，并在下方明确了每项身份与造型</Checkbox></>} />}
    <Table size="small" rowKey="id" dataSource={rows} pagination={{pageSize: 8}} expandable={{expandedRowRender: row => <Collapse items={[{key: "source", label: "原文出处与别名", children: <><p>身份：{row.identity}；别名：{row.aliases?.join("、") || "无"}</p>{row.evidence.map((e, i) => <blockquote key={i}>区块 {e.scope}：{e.quote}</blockquote>)}</>}]} />}} columns={[
      {title: "资产", render: (_, row) => <>{row.name}<Tag>{({character: "角色", scene: "场景", prop: "道具"} as Record<string,string>)[row.kind]}</Tag></>},
      {title: "时代／造型", dataIndex: "era"},
      candidate ? {title: "变化", dataIndex: "difference"} : {title: "已绑定资产", render: (_, row) => {
        const asset = state?.assets.find(a => a.id === row.asset_id)
        const look = asset?.looks.find(l => l.id === row.look_id)
        return <>{asset?.name || "资产待核对"}{look && <Tag>{look.name}</Tag>}</>
      }},
      ...(candidate ? [{title: "确认映射", render: (_: unknown, row: typeof rows[number]) => <Space orientation="vertical">
        <Select aria-label={`${row.name}资产映射`} style={{minWidth: 200}} placeholder="请选择复用或新建" value={choices[row.id]?.asset_id} options={[{value: "", label: "沿用此身份，无记录则新建"}, ...(state?.assets || []).filter(a => a.kind === row.kind).map(a => ({value: a.id, label: `复用：${a.name}`}))]} onChange={asset_id => setChoices({...choices, [row.id]: {asset_id}})} />
        {row.kind === "character" && choices[row.id]?.asset_id && <Select aria-label={`${row.name}造型映射`} style={{minWidth: 200}} value={choices[row.id]?.look_id || ""} options={[{value: "", label: "沿用此造型，无记录则新建"}, ...(state?.assets.find(a => a.id === choices[row.id]?.asset_id)?.looks || []).map(l => ({value: l.id, label: `复用：${l.name}`}))]} onChange={look_id => setChoices({...choices, [row.id]: {...choices[row.id], look_id}})} />}
      </Space>}] : []),
    ]} />
    {candidate && <Button type="primary" loading={busy} disabled={rows.some(r => !choices[r.id]) || (job.data.issues.length > 0 && !confirmed)} onClick={() => void perform("confirm")}>确认全局资产清单</Button>}
    {Boolean(state?.history?.length) && <Collapse items={[{key: "history", label: "清单历史与回退", children: <Space orientation="vertical"><Alert type="warning" title="恢复清单会使相关镜头关联待核对，图片与视频保留。" />{state?.history?.map(h => <Button key={h.version} disabled={busy || Boolean(running)} onClick={() => void restore(h.version)}>恢复剧本版本 {h.source_revision} · {h.confirmed_at}</Button>)}</Space>}]} />}
  </Space>
}
