import { useCallback, useEffect, useRef, useState } from "react"
import { Alert, Button, Progress, Select, Space, Tabs, Typography } from "antd"
import { jsonMutation, requestJson } from "../api"

type Child = { id: string; status: string; progress?: number; url?: string; error?: string;
  output_path?: string;
  quality?: number; created_at?: string; media_info?: { width?: number; height?: number; duration?: number } }
type Status = { eligible: boolean; source_job_id: string; source_revision: string; source_url?: string;
  source_path?: string;
  source_media_info?: {width?:number; height?:number; duration?:number}; children: Child[] }
const terminal = new Set(["completed", "succeeded", "failed", "cancelled"])
export const H3_CONFIRM_MODE = "minimax-h3-director-confirm-accel-r2v"

/** Business confirmation flow; all controls use the application's Ant Design provider. */
export function H3ConfirmationPanel({ endpoint, csrfToken, readOnly = false, onCreated, localUrls = {} }:
  { endpoint: string; csrfToken: string; readOnly?: boolean; onCreated?: (id: string) => void; localUrls?: Record<string,string> }) {
  const [state, setState] = useState<Status>()
  const [quality, setQuality] = useState(2)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [tabKey, setTabKey] = useState<string>()
  const requestId = useRef<string | null>(null)
  const [regenerated, setRegenerated] = useState("")
  const [pollError, setPollError] = useState("")
  const refresh = useCallback(async () => {
    const next = await requestJson<Status>(endpoint)
    setState(next)
    setPollError("")
    return next
  }, [endpoint])
  useEffect(() => {
    let active = true
    const poll = () => requestJson<Status>(endpoint).then(s => { if (active) { setState(s); setPollError("") } })
      .catch(e => { if (active) setPollError(e instanceof Error ? e.message : String(e)) })
    setState(undefined); setTabKey(undefined); setError(""); setPollError(""); requestId.current = null
    void poll()
    const timer = setInterval(() => { void poll() }, 3000)
    return () => { active = false; clearInterval(timer) }
  }, [endpoint])
  const children = (state?.children || []).map(c => ({...c, url: localUrls[c.output_path || ""] || c.url}))
  const sourceUrl = localUrls[state?.source_path || ""] || state?.source_url
  const running = children.find(c => !terminal.has(c.status))
  const successful = children.filter(c => c.url && ["completed", "succeeded"].includes(c.status))
  const sourceEndpoint = state ? endpoint.replace(/\/jobs\/[^/]+\/refine$/, `/jobs/${state.source_job_id}/refine`) : endpoint
  async function confirm() {
    if (!state || busy) return
    setBusy(true); setError("")
    requestId.current ||= crypto.randomUUID()
    try {
      const child = await requestJson<{ id?: string; job_id?: string }>(sourceEndpoint, jsonMutation(csrfToken, {
        refine_quality: quality, source_revision: state.source_revision, request_id: requestId.current,
      }))
      requestId.current = null
      await refresh()
      onCreated?.(child.id || child.job_id || "")
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function retry(child: Child) {
    setBusy(true); setError("")
    try {
      await requestJson(endpoint.replace(/\/jobs\/[^/]+\/refine$/, `/jobs/${child.id}/retry`), jsonMutation(csrfToken))
      await refresh()
    } catch(e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function cancel(child: Child) {
    setBusy(true); setError("")
    try {
      const project = endpoint.startsWith("/api/projects/")
      const url = endpoint.replace(/\/jobs\/[^/]+\/refine$/, `/jobs/${child.id}/${project ? "refine/cancel" : "cancel"}`)
      await requestJson(url, jsonMutation(csrfToken))
      await refresh()
    } catch(e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function regenerate() {
    setBusy(true); setError("")
    try {
      const child = await requestJson<{id?: string; job_id?: string}>(sourceEndpoint + "/preview", jsonMutation(csrfToken))
      const id = child.id || child.job_id || ""
      setRegenerated(id)
      onCreated?.(id)
    } catch(e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const cacheInvalid = [error, ...children.map(c => c.error || "")].some(s => /FIRST_PASS|CACHE_INVALID|缓存.*失效|实例已切换|INSTANCE_MISMATCH/.test(s))
  const media = (url: string, label: string) => <Space direction="vertical" style={{ width: "100%" }}>
    <video aria-label={label} src={url} controls preload="metadata" style={{ width: "100%", maxHeight: 460, background: "#000" }} />
    <Typography.Link href={url} target="_blank" rel="noreferrer" download>下载{label}</Typography.Link>
  </Space>
  return <section aria-label="一采确认与二采" style={{ padding: 16, marginTop: 12, border: "1px solid var(--studio-border)", borderRadius: 12, color: "var(--studio-text)", background: "var(--studio-surface)" }}>
    <Typography.Title level={5}>一采预览与二采精修</Typography.Title>
    <Typography.Paragraph>先审阅一采原片，再确认生成二采。原片始终保留；导演台二采需在工坊选择采用。</Typography.Paragraph>
    {(error || pollError) && <Alert type="error" showIcon message={error || pollError} />}
    {cacheInvalid && <Alert type="warning" showIcon message="一采缓存已失效，原片仍可使用；继续二采需要重新生成一采预览"
      action={!readOnly && <Button disabled={busy || !!running || !!regenerated} onClick={() => void regenerate()}>重新生成一采预览</Button>} />}
    {regenerated && <Alert type="success" message="已创建新的预览任务，完成后需要再次确认二采"
      description={<Typography.Link href={endpoint.startsWith("/api/projects/") ? `/director/projects/${endpoint.split("/")[3]}/jobs` : `/generate/video/${regenerated}`}>查看新预览任务</Typography.Link>} />}
    {state && (sourceUrl || successful.length > 0) && <Tabs activeKey={tabKey || successful.at(-1)?.id || "source"} onChange={setTabKey} items={[
      { key: "source", label: "一采原片", children: <>
        {state.source_media_info?.width && <Typography.Paragraph type="secondary">{state.source_media_info.width} × {state.source_media_info.height}</Typography.Paragraph>}
        {sourceUrl ? media(sourceUrl, "一采原片") : <Alert type="info" message="原片文件当前不可访问，请检查本地保存目录。" />}</> },
      ...successful.map(c => ({ key: c.id, label: `二采精修 · ${c.quality} MP`, children: <>
        <Typography.Paragraph type="secondary">{c.created_at}{c.media_info?.width ? ` · ${c.media_info.width} × ${c.media_info.height}` : ""}</Typography.Paragraph>
        {media(c.url!, "二采精修版")}
      </> })),
    ]} />}
    {running && <><Typography.Text>二采进行中，原片仍可使用</Typography.Text><Progress percent={Math.min(99, running.progress || 0)} />
      {!readOnly && <Button disabled={busy} onClick={() => void cancel(running)}>取消二采</Button>}</>}
    {children.filter(c => c.status === "failed" || c.status === "cancelled").map(c => <Alert key={c.id} type="warning" showIcon
      message={c.status === "cancelled" ? "二采已取消，原片保留" : "二采失败，原片保留"} description={c.error}
      action={!readOnly && <Button disabled={busy || !!running} onClick={() => void retry(c)}>重试失败二采</Button>} />)}
    {state?.eligible && !readOnly && <Space wrap style={{ marginTop: 12 }}>
      <Typography.Text>{running ? "已确认 · 二采进行中" : successful.length ? "再次生成二采" : "一采完成 · 待确认二采"}</Typography.Text>
      <Select aria-label="二采目标画质" value={running?.quality ?? quality} disabled={busy || !!running} style={{ width: 140 }}
        options={[{value:1,label:"1 MP"},{value:2,label:"2 MP"}]}
        onChange={value => { setQuality(value); requestId.current = null }} />
      <Button type="primary" loading={busy} disabled={!!running || cacheInvalid} onClick={() => void confirm()}>确认并生成二采</Button>
    </Space>}
  </section>
}
