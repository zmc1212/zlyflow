import { useEffect, useState } from "react"
import { Alert, Button, Card, Form, Input, InputNumber, Select, Space, Spin, Tag, Typography, Upload, message } from "antd"
import { Upload as UploadIcon } from "lucide-react"
import {
  actionPrevisCommand, createActionPrevis, getActionPrevis, latestActionPrevis, reviseActionPrevis,
  type ActionPrevisPlan, type Director2Job,
} from "../api"

type Props = { csrfToken: string; projectId: string; episodeId: string; beatId: string; onDirtyChange?: (dirty: boolean) => void }
const ACTIONS = ["idle", "walk", "run", "step", "turn", "reach", "point", "wave", "push", "pull", "grab", "release", "crouch", "jump", "guard", "jab", "cross", "hook", "block", "dodge", "knee", "low_kick", "side_kick", "recoil", "recover"]
const ACTION_LABELS: Record<string, string> = { idle: "待机", walk: "行走", run: "跑动", step: "步法", turn: "转身", reach: "伸手", point: "指向", wave: "挥手", push: "推", pull: "拉", grab: "抓握", release: "松开", crouch: "下蹲", jump: "跳跃", guard: "架势", jab: "刺拳", cross: "后手直拳", hook: "摆拳", block: "格挡", dodge: "闪避", knee: "膝击", low_kick: "低扫", side_kick: "侧踢", recoil: "受击", recover: "回位" }
const OPTIONS = {
  size: [["wide", "远景"], ["medium", "中景"], ["close", "近景"], ["detail", "特写"]],
  angle: [["front", "正面"], ["side", "侧面"], ["three_quarter", "三分之二侧面"], ["over_shoulder", "过肩"], ["low", "低机位"], ["high", "俯拍"]],
  move: [["static", "固定"], ["dolly_in", "推近"], ["dolly_out", "拉远"], ["truck_left", "左移"], ["truck_right", "右移"], ["orbit_left", "左环绕"], ["orbit_right", "右环绕"], ["follow", "跟随"]],
} as const
const statusLabel: Record<string, string> = { queued: "排队分析", planning: "分析参考素材", awaiting_review: "待审稿", queued_remote: "等待远端 Blender", remote_running: "远端制作中", completed: "已通过", needs_revision: "需返修", failed: "失败", cancelled: "已取消" }

export default function ActionPrevisPane({ csrfToken, projectId, episodeId, beatId, onDirtyChange }: Props) {
  const [description, setDescription] = useState("")
  const [images, setImages] = useState<File[]>([])
  const [video, setVideo] = useState<File | null>(null)
  const [job, setJob] = useState<Director2Job | null>(null)
  const [plan, setPlan] = useState<ActionPrevisPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [requestDirty, setRequestDirty] = useState(false)

  useEffect(() => {
    onDirtyChange?.(dirty || requestDirty)
    return () => onDirtyChange?.(false)
  }, [dirty, requestDirty, onDirtyChange])

  useEffect(() => {
    let alive = true
    setJob(null); setPlan(null); setDirty(false)
    latestActionPrevis(projectId, episodeId, beatId).then(result => {
      if (alive) { setJob(result); setPlan((result?.payload?.plan as ActionPrevisPlan) || null) }
    }).catch(error => { if (alive) message.error(String(error)) })
    return () => { alive = false }
  }, [projectId, episodeId, beatId])

  useEffect(() => {
    if (!job || !["queued", "planning", "queued_remote", "remote_running"].includes(job.status)) return
    const timer = window.setInterval(() => {
      getActionPrevis(projectId, job.id).then(result => {
        setJob(result)
        if (result.payload?.plan && !dirty) setPlan(result.payload.plan as ActionPrevisPlan)
      }).catch(() => undefined)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [projectId, job?.id, job?.status, dirty])

  async function submit() {
    if (!description.trim()) { message.warning("请描述角色动作与镜头要求"); return }
    setBusy(true)
    try {
      const created = await createActionPrevis(csrfToken, projectId, episodeId, beatId, description, images, video)
      const result = await getActionPrevis(projectId, created.job_id)
      setJob(result); setPlan(null); setDirty(false); setRequestDirty(false)
      message.success("参考分析已提交；方案生成后可逐项审稿")
    } catch (error) { message.error(String(error)) }
    finally { setBusy(false) }
  }

  function edit(mutator: (copy: ActionPrevisPlan) => void) {
    if (!plan) return
    const copy = structuredClone(plan)
    mutator(copy)
    setPlan(copy); setDirty(true)
  }

  async function save() {
    if (!job || !plan) return
    setBusy(true)
    try {
      const result = await reviseActionPrevis(csrfToken, projectId, job.id, plan, Number(job.payload.plan_revision))
      setJob(result); setPlan(result.payload.plan as ActionPrevisPlan); setDirty(false)
      message.success("动作与镜头方案已保存为新版本")
    } catch (error) { message.error(String(error)) }
    finally { setBusy(false) }
  }

  async function command(kind: "render" | "cancel" | "retry") {
    if (!job) return
    setBusy(true)
    try {
      const result = await actionPrevisCommand(csrfToken, projectId, job.id, kind, Number(job.payload.plan_revision))
      setJob(result); setPlan((result.payload.plan as ActionPrevisPlan) || null); setDirty(false)
      message.success(kind === "render" ? "已提交远端 Blender 制作" : kind === "retry" ? "已重新排队" : "已取消")
    } catch (error) { message.error(String(error)) }
    finally { setBusy(false) }
  }

  const review = job?.status === "awaiting_review"
  const artifacts = (job?.payload?.artifacts || {}) as Record<string, string>
  const issues = (job?.payload?.quality?.issues || []) as string[]
  return <div className="xiaji-action-previs" style={{ display: "grid", gap: 12, padding: 16 }}>
    <header className="workshop-previs-intro"><Typography.Title level={5}>动作与镜头编排 <Tag>可选</Tag></Typography.Title><Typography.Paragraph type="secondary">描述动作 → 审阅编排 → 渲染白膜。先验证动作和机位，再回到提示词完成创作。</Typography.Paragraph></header>
    <Alert type="info" showIcon title="支持 1–2 名人形角色、2–15 秒" description="可上传图片或短视频作为动作参考；确认方案后才提交远端 Blender，输出 24 fps 骨骼白膜。不会自动生成最终视频。" />
    <Form layout="vertical"><Form.Item label="动作与镜头要求" htmlFor="workshop-previs-description">
      <Input.TextArea id="workshop-previs-description" aria-label="动作与镜头要求" value={description} onChange={event => { setDescription(event.target.value); setRequestDirty(Boolean(event.target.value.trim()) || images.length > 0 || Boolean(video)) }} rows={5} maxLength={3000}
        placeholder="例如：男女主近景对打，步法试探→前手刺拳被格挡→侧身闪避后低扫→受击后回位。镜头从过肩跟拍切到侧面近景，接触瞬间短推近。" />
    </Form.Item></Form>
    <Space wrap>
      <Upload accept="image/jpeg,image/png,image/webp" multiple beforeUpload={file => { setImages(prev => [...prev, file].slice(0, 4)); setRequestDirty(true); return false }} showUploadList={false}>
        <Button icon={<UploadIcon size={14} />}>参考图片（{images.length}/4）</Button>
      </Upload>
      <Upload accept="video/mp4,video/quicktime,video/webm" beforeUpload={file => { setVideo(file); setRequestDirty(true); return false }} showUploadList={false}>
        <Button icon={<UploadIcon size={14} />}>{video ? video.name : "参考短视频"}</Button>
      </Upload>
      {(images.length > 0 || video) && <Button onClick={() => { setImages([]); setVideo(null); setRequestDirty(Boolean(description.trim())) }}>清空素材</Button>}
      <Button type="primary" loading={busy} onClick={() => void submit()}>生成编排方案</Button>
    </Space>
    {job && <Card size="small" title={<Space>任务 <Tag>{statusLabel[job.status] || job.status}</Tag> <span style={{ fontWeight: 400, fontSize: 12 }}>版本 {job.payload.plan_revision || 0}</span></Space>}>
      {job.error_message && <Alert type={job.status === "failed" ? "error" : "warning"} showIcon message={job.error_message} style={{ marginBottom: 10 }} />}
      {job.payload?.observations && <Alert type="info" message="参考素材观察" description={String(job.payload.observations)} style={{ marginBottom: 10 }} />}
      {["queued", "planning", "queued_remote", "remote_running"].includes(job.status) && <Spin tip={`${statusLabel[job.status]} · ${job.progress || 0}%`}><div style={{ height: 44 }} /></Spin>}
      {plan && <div style={{ display: "grid", gap: 16 }}>
        <div><strong>动作节拍</strong><div style={{ fontSize: 12, opacity: .72 }}>时间以 24 fps 帧数表示；修改一拍结束帧会同步调整下一拍开始帧。</div></div>
        {plan.beats.map((beat, index) => <Card key={beat.id} size="small" title={`第 ${index + 1} 拍 · ${beat.start}–${beat.end} 帧`} extra={review && <Space>
          <Button size="small" disabled={index === 0} onClick={() => edit(copy => { const a = copy.beats[index - 1], b = copy.beats[index];
            const aContact = a.contact, bContact = b.contact
            const aFraction = aContact ? (aContact.frame - a.start) / (a.end - a.start) : 0
            const bFraction = bContact ? (bContact.frame - b.start) / (b.end - b.start) : 0
            ;[a.description, b.description] = [b.description, a.description]
            ;[a.actions, b.actions] = [b.actions, a.actions]
            a.contact = bContact ? { ...bContact, frame: a.start + Math.min(a.end - a.start - 1, Math.round(bFraction * (a.end - a.start))) } : null
            b.contact = aContact ? { ...aContact, frame: b.start + Math.min(b.end - b.start - 1, Math.round(aFraction * (b.end - b.start))) } : null
          })}>上移内容</Button>
          {index < plan.beats.length - 1 && <InputNumber size="small" aria-label={`第 ${index + 1} 拍结束帧`} min={beat.start + 1} max={plan.beats[index + 1].end - 1} value={beat.end} onChange={value => { if (value != null) edit(copy => { copy.beats[index].end = value; copy.beats[index + 1].start = value }) }} />}
        </Space>}>
          <Input.TextArea aria-label={`第 ${index + 1} 拍动作说明`} disabled={!review} value={beat.description} rows={2} maxLength={240} onChange={event => edit(copy => { copy.beats[index].description = event.target.value })} />
          <Space wrap style={{ marginTop: 8 }}>
            {beat.actions.map((action, actionIndex) => <Space key={action.actor}><Tag>{action.actor}</Tag><Select disabled={!review} value={action.type} style={{ width: 130 }} options={ACTIONS.map(value => ({ value, label: ACTION_LABELS[value] }))} onChange={value => edit(copy => { copy.beats[index].actions[actionIndex].type = value })} /></Space>)}
            {review && plan.actors.length === 2 && beat.actions.length === 1 && <Button size="small" onClick={() => edit(copy => { const missing = copy.actors.find(actor => actor.id !== copy.beats[index].actions[0].actor); if (missing) copy.beats[index].actions.push({ actor: missing.id, type: "guard" }) })}>补上对手动作</Button>}
            {beat.contact && <><Tag color="orange">接触点</Tag><InputNumber disabled={!review} aria-label={`第 ${index + 1} 拍接触帧`} min={beat.start} max={beat.end - 1} value={beat.contact.frame} onChange={value => { if (value != null) edit(copy => { if (copy.beats[index].contact) copy.beats[index].contact!.frame = value }) }} />
              <Select disabled={!review} aria-label="接触骨骼" value={beat.contact.bone} style={{ width: 130 }} options={["hand.L", "hand.R", "foot.L", "foot.R", "forearm.L", "forearm.R", "chest", "shoulder.L", "shoulder.R"].map(value => ({ value }))} onChange={value => edit(copy => { if (copy.beats[index].contact) copy.beats[index].contact!.bone = value })} />
              <Select disabled={!review} aria-label="目标骨骼" value={beat.contact.target_bone} style={{ width: 130 }} options={["hand.L", "hand.R", "foot.L", "foot.R", "forearm.L", "forearm.R", "chest", "shoulder.L", "shoulder.R"].map(value => ({ value }))} onChange={value => edit(copy => { if (copy.beats[index].contact) copy.beats[index].contact!.target_bone = value })} />
              {review && <Button size="small" onClick={() => edit(copy => { copy.beats[index].contact = null })}>移除接触</Button>}</>}
            {!beat.contact && review && plan.actors.length === 2 && <Button size="small" onClick={() => edit(copy => { copy.beats[index].contact = { frame: Math.floor((beat.start + beat.end) / 2), actor: "A", target_actor: "B", bone: "hand.R", target_bone: "forearm.L" } })}>添加接触点</Button>}
          </Space>
        </Card>)}
        <strong>镜头表</strong>
        {plan.shots.map((shot, index) => <Card key={shot.id} size="small" title={`机位 ${index + 1} · ${shot.start}–${shot.end} 帧`} extra={review && index < plan.shots.length - 1 && <InputNumber size="small" aria-label={`机位 ${index + 1} 切点`} min={shot.start + 1} max={plan.shots[index + 1].end - 1} value={shot.end} onChange={value => { if (value != null) edit(copy => { copy.shots[index].end = value; copy.shots[index + 1].start = value }) }} />}>
          <Space wrap>
            {(["size", "angle", "move"] as const).map(key => <Select key={key} disabled={!review} aria-label={`${shot.id} ${key}`} value={shot[key]} style={{ width: 150 }} options={OPTIONS[key].map(([value, label]) => ({ value, label }))} onChange={value => edit(copy => { copy.shots[index][key] = value })} />)}
            <Select disabled={!review} aria-label={`${shot.id} 主体`} value={shot.subject} style={{ width: 110 }} options={[{ value: "both", label: "双人" }, ...plan.actors.map(actor => ({ value: actor.id, label: actor.label }))]} onChange={value => edit(copy => { copy.shots[index].subject = value })} />
            <InputNumber disabled={!review} aria-label={`${shot.id} 焦距`} min={18} max={100} addonAfter="mm" value={shot.lens_mm} onChange={value => { if (value != null) edit(copy => { copy.shots[index].lens_mm = value }) }} />
          </Space>
        </Card>)}
        {review && <Space wrap>
          <Button disabled={!dirty} loading={busy} onClick={() => void save()}>保存方案新版本</Button>
          <Button type="primary" disabled={dirty} loading={busy} onClick={() => void command("render")}>确认并渲染白膜</Button>
          {dirty && <span style={{ fontSize: 12 }}>请先保存修改，再提交渲染</span>}
        </Space>}
      </div>}
      {artifacts.video && <div style={{ display: "grid", gap: 8, marginTop: 14 }}>
        <video src={artifacts.video} controls playsInline preload="metadata" style={{ width: "100%", maxWidth: 720, background: "#111" }} />
        {artifacts.contact_sheet && <img src={artifacts.contact_sheet} alt="白膜关键帧联系表" style={{ width: "100%", maxWidth: 720 }} />}
        <Space wrap>{([["blend", "下载可编辑 Blender 文件"], ["report", "查看质量报告"]] as const).map(([key, label]) => artifacts[key] && <a key={key} href={artifacts[key]} target="_blank" rel="noreferrer">{label}</a>)}</Space>
      </div>}
      {issues.length > 0 && <Alert type="warning" showIcon message="质量检查需要返修" description={<ul>{issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>} style={{ marginTop: 10 }} />}
      <Space style={{ marginTop: 12 }}>
        {["queued", "planning", "awaiting_review", "queued_remote", "remote_running"].includes(job.status) && <Button danger disabled={busy} onClick={() => void command("cancel")}>取消任务</Button>}
        {["failed", "needs_revision"].includes(job.status) && <Button disabled={busy} onClick={() => void command("retry")}>按已审方案重试</Button>}
      </Space>
    </Card>}
  </div>
}
