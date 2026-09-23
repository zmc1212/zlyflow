import { useEffect, useRef, useState, type ReactNode } from "react"
import { Alert, Button, Card, Collapse, Empty, Form, InputNumber, Select, Space, Switch, Tag, Typography, message } from "antd"
import { composeEpisodeVideo, director2ErrorDetail, getEpisodeDubbing, updateEpisodeProduction } from "../api"
import { materialAdopted, materialsForUnit, productionFilm, type ProductionState } from "../production"
import type { DubbingLine } from "../dubbing-track"
import DubbingWorkbench from "./DubbingWorkbench"
import "./production.css"

type Props = { state: ProductionState; csrfToken: string; projectId: string; episodeId: string; onRefresh: () => Promise<void> }

export function ProductionPicture({ state, csrfToken, projectId, episodeId, onRefresh, editor, unitId, onUnit, onSource }: Props & {
  editor: ReactNode; unitId: string; onUnit: (id: string) => void; onSource: (beatId: string) => void;
}) {
  const [previewId, setPreviewId] = useState("")
  const [busy, setBusy] = useState(false)
  const materials = materialsForUnit(state, unitId)
  const preview = materials.find(m => m.id === previewId) || materials.find(m => materialAdopted(state, m)) || materials[0]
  const unit = state.units.find(u => u.id === unitId)
  const versionLabel = (m: typeof materials[number]) => materialAdopted(state, m) ? "已采用" :
    m.unit_ids.some(id => state.adopted[id] === m.id) ? "部分采用" : "候选"
  async function adopt() {
    if (!preview) return
    setBusy(true)
    try {
      await updateEpisodeProduction(csrfToken, projectId, episodeId, "adopt", {
        expected_revision: state.revision, mode: state.active_mode, material_id: preview.id,
      })
      await onRefresh()
      message.success("已采用此版，成片将在下次导出时更新")
    } catch (err) { message.error(director2ErrorDetail(err, "采用失败")); await onRefresh() }
    finally { setBusy(false) }
  }
  const groups = [...new Set(state.units.map(u => u.part_id))]
  return <div className="production-picture">
    <aside className="production-units">
      <Typography.Title level={5}>{state.active_mode === "director" ? "连续画面" : "逐镜画面"}</Typography.Title>
      {groups.map((part, index) => <section key={part || "shots"}>
        {part && <Typography.Text type="secondary">Part {index + 1}</Typography.Text>}
        <Space direction="vertical" style={{ width: "100%" }}>
          {state.units.filter(u => u.part_id === part).map(u => <Button key={u.id} block
            type={u.id === unitId ? "primary" : "default"} onClick={() => { onUnit(u.id); setPreviewId("") }}>
            {state.adopted[u.id] ? "✓ " : "○ "}{u.title}
          </Button>)}
        </Space>
      </section>)}
      {!state.units.length && <Empty description="先生成并确认制作方案" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
    </aside>
    <div className="production-detail">
      <div className="production-unit-summary">
        <Space wrap>
          <Typography.Text strong>{unit?.title || "画面预览"}</Typography.Text>
          <Typography.Text type="secondary">{preview ? `${materials.length} 个素材版本` : "尚无生成结果，确认方案后生成画面"}</Typography.Text>
        </Space>
        <Space wrap>{unit?.source_beat_ids.map((id, i) =>
          <Button key={id} size="small" onClick={() => onSource(id)}>来源分镜 {i + 1}</Button>)}</Space>
      </div>
      {editor}
      {preview && <Card title="画面结果">
          <video key={preview.url} src={preview.url} controls playsInline className="production-video" />
          <Space wrap className="production-actions">
            <Select aria-label="画面素材版本" value={preview.id} onChange={setPreviewId} style={{ minWidth: 260 }}
              options={materials.map((m, i) => ({ value: m.id, label: `${versionLabel(m)} · ${m.created_at || m.title} · ${materials.length - i}` }))} />
            <Tag>{preview.unit_ids.length} 个画面范围 · {preview.verified ? "边界已验证" : "仅支持完整范围"}</Tag>
            <Button type="primary" disabled={materialAdopted(state, preview) || state.plan_stale} loading={busy} onClick={() => void adopt()}>
              {materialAdopted(state, preview) ? "当前采用版" : "采用此版"}
            </Button>
          </Space>
      </Card>}
      <Collapse items={[{ key: "history", label: `其他方案的历史素材（${state.materials.filter(m => m.plan_key !== state.plan_key).length}）`,
        children: <Space direction="vertical">{state.materials.filter(m => m.plan_key !== state.plan_key).map(m =>
          <Typography.Link key={m.id} href={m.url} target="_blank" rel="noreferrer">{m.created_at || m.title} · 查看历史素材</Typography.Link>)}</Space> }]} />
    </div>
  </div>
}

export function ProductionSound({ state, csrfToken, projectId, episodeId, onRefresh, unitId }: Props & { unitId?: string }) {
  const [lines, setLines] = useState<DubbingLine[]>([])
  const [lineId, setLineId] = useState("")
  const [materialId, setMaterialId] = useState("")
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)
  const [mix, setMix] = useState<"overlay" | "replace">("overlay")
  const [editingId, setEditingId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const video = useRef<HTMLVideoElement>(null)
  const audio = useRef<HTMLAudioElement>(null)
  useEffect(() => {
    const adoptedId = unitId ? state.adopted[unitId] : ""
    const selectedClip = state.timeline.find(c => c.material_id === adoptedId && c.unit_ids.includes(unitId || ""))
    const range = state.materials.find(m => m.id === adoptedId)?.ranges[unitId || ""]
    setEditingId(null)
    setMaterialId(adoptedId || "")
    setStart(range?.start ?? selectedClip?.start ?? 0)
    setEnd(range?.end ?? selectedClip?.end ?? 0)
  }, [unitId, episodeId, state.active_mode, state.adopted[unitId || ""]])
  async function loadLines() {
    try { const track = await getEpisodeDubbing(projectId, episodeId); setLines(track.lines) }
    catch (err) { message.error(director2ErrorDetail(err, "读取补配台词失败")) }
  }
  useEffect(() => { void loadLines() }, [projectId, episodeId])
  const clip = state.timeline.find(c => c.material_id === materialId && start >= c.start && (c.end == null || start < c.end))
    || state.timeline.find(c => c.material_id === materialId)
  const line = lines.find(l => l.id === lineId)
  async function save(records: unknown[]) {
    setBusy(true)
    try {
      await updateEpisodeProduction(csrfToken, projectId, episodeId, "audio", {
        expected_revision: state.revision, mode: state.active_mode, audio: records,
      })
      await onRefresh(); setEditingId(null); message.success("声音编排已保存")
    } catch (err) { message.error(director2ErrorDetail(err, "保存声音编排失败")); await onRefresh() }
    finally { setBusy(false) }
  }
  function audition() {
    if (!video.current || !audio.current) return
    video.current.currentTime = start; audio.current.currentTime = 0
    video.current.muted = mix === "replace"
    void Promise.all([video.current.play(), audio.current.play()]).catch(() => message.info("请先允许浏览器播放音频"))
  }
  return <Space direction="vertical" className="production-stack" size={16}>
    <Alert type="info" showIcon title="默认保留视频原声，无需独立配音即可导出。" description="需要旁白、内心或局部替换时，先生成配音，再绑定已采用的画面与时间区间。替换会静音该区间的整个原音轨。" />
    <Collapse items={[{ key: "voices", label: "生成或调整补配音频", children: <DubbingWorkbench csrfToken={csrfToken} projectId={projectId} episodeId={episodeId} productionMode onTrackChange={setLines} /> }]} />
    <Card title={editingId ? "重新对齐声音" : "添加声音编排"} extra={<Button onClick={() => void loadLines()}>刷新配音</Button>}>
      <Form layout="vertical">
        <div className="production-audio-fields">
          <Form.Item label="补配台词"><Select aria-label="补配台词" value={lineId || undefined} onChange={setLineId}
            options={lines.filter(l => l.status === "ready" && l.audio_url).map(l => ({ value: l.id, label: `${l.speaker}：${l.text}` }))} /></Form.Item>
          <Form.Item label="已采用画面"><Select aria-label="已采用画面" value={materialId || undefined} onChange={id => {
            setMaterialId(id); const c = state.timeline.find(c => c.material_id === id); setStart(c?.start || 0); setEnd(c?.end || 0)
          }} options={[...new Set(state.timeline.map(c => c.material_id))].map(id => ({ value: id,
            label: state.timeline.filter(c => c.material_id === id).flatMap(c => c.unit_ids).map(u => state.units.find(x => x.id === u)?.title || u).join(" / ") }))} /></Form.Item>
          <Form.Item label="素材内起点（秒）"><InputNumber aria-label="声音起点" min={0} step={0.1} value={start} onChange={n => setStart(Number(n || 0))} /></Form.Item>
          <Form.Item label="素材内终点（秒）"><InputNumber aria-label="声音终点" min={0} step={0.1} value={end} onChange={n => setEnd(Number(n || 0))} /></Form.Item>
          <Form.Item label="混音方式"><Select value={mix} onChange={setMix} options={[{ value: "overlay", label: "叠加补配" }, { value: "replace", label: "替换区间原声" }]} /></Form.Item>
        </div>
        {clip && <video ref={video} src={clip.url} controls className="production-video" onPause={() => audio.current?.pause()}
          onTimeUpdate={() => { if (video.current && video.current.currentTime >= end && !audio.current?.paused) { audio.current?.pause(); video.current.pause() } }} />}
        {line && <audio ref={audio} src={line.audio_url} controls />}
        <Space className="production-actions">
          <Button disabled={!line || !clip || end <= start} onClick={audition}>试听此区间</Button>
          <Button type="primary" loading={busy} disabled={!line || !clip || end <= start || line.duration_sec > end - start + .001}
            onClick={() => void save([...state.audio.filter(a => a.id !== editingId), { id: editingId || undefined, line_id: lineId, material_id: materialId, start, end, mix, enabled: true }])}>保存声音编排</Button>
          {line && <Typography.Text type="secondary">音频 {line.duration_sec.toFixed(2)} 秒；不会截断台词</Typography.Text>}
        </Space>
      </Form>
    </Card>
    {state.audio.map(a => <Card key={a.id} size="small" title={a.text} extra={<Tag color={a.needs_alignment ? "warning" : "success"}>{a.needs_alignment ? "需重新对齐" : a.enabled ? "已启用" : "已停用"}</Tag>}>
      <Space wrap><Typography.Text>{a.start.toFixed(2)}–{a.end.toFixed(2)} 秒 · {a.mix === "replace" ? "替换原声" : "叠加"}</Typography.Text>
        <Switch checked={a.enabled} disabled={busy} onChange={enabled => void save(state.audio.map(x => x.id === a.id ? { ...x, enabled } : x))} />
        <Button onClick={() => { setEditingId(a.id); setLineId(a.line_id); setMaterialId(a.material_id); setStart(a.start); setEnd(a.end); setMix(a.mix) }}>编辑 / 重新对齐</Button>
        <Button danger disabled={busy} onClick={() => void save(state.audio.filter(x => x.id !== a.id))}>移除</Button>
        <audio src={a.audio_url} controls />
      </Space>
    </Card>)}
  </Space>
}

export function ProductionFilm({ state, csrfToken, projectId, episodeId, onRefresh, onJob, jobActive }: Props & { onJob: (ids: string[]) => void; jobActive: boolean }) {
  const [busy, setBusy] = useState(false)
  const film = productionFilm(state)
  async function exportFilm() {
    setBusy(true)
    try {
      const result = await composeEpisodeVideo(csrfToken, projectId, episodeId, { expected_revision: state.revision, production_mode: state.active_mode })
      onJob([result.job_id]); await onRefresh(); message.success("成片导出已入队")
    } catch (err) { message.error(director2ErrorDetail(err, "导出失败")); await onRefresh() }
    finally { setBusy(false) }
  }
  return <Space direction="vertical" size={16} className="production-stack">
    <Card title="本集成片" extra={<Button type="primary" loading={busy || jobActive} disabled={!state.ready || jobActive} onClick={() => void exportFilm()}>{state.needs_export ? "导出当前采用版" : "重新导出"}</Button>}>
      <Space wrap><Tag>{state.active_mode === "director" ? "Director 连续画面" : "普通逐镜"}</Tag>
        <Tag>{Object.keys(state.adopted).length}/{state.units.length} 个画面已采用</Tag>
        <Tag>{state.audio.filter(a => a.enabled).length ? "原声 + 已编排补配" : "保留视频原声"}</Tag>
        <Tag color={state.needs_export ? "warning" : "success"}>{state.needs_export ? "有更新待导出" : "成片已是当前采用版"}</Tag>
      </Space>
      {state.block_reasons.map(reason => <Alert key={reason} type="warning" showIcon title={reason} className="production-actions" />)}
      {film ? <><video key={film.url} src={film.url} controls playsInline className="production-video" />
        <Button href={film.url} target="_blank" rel="noreferrer" download>下载 / 打开成片</Button></> : <Empty description="画面生成后会显示本集成片。局部采用或补配后，可在此导出更新版。" />}
    </Card>
    <Collapse items={[{ key: "history", label: `历史导出（${state.exports.length + state.legacy_exports.length}）`, children:
      <Space direction="vertical">{[...state.exports, ...state.legacy_exports].slice().reverse().map((e, i) =>
        <Typography.Link key={`${e.job_id}-${i}`} href={e.url} target="_blank" rel="noreferrer">{e.created_at || e.title || "历史成片"}</Typography.Link>)}</Space> }]} />
  </Space>
}
