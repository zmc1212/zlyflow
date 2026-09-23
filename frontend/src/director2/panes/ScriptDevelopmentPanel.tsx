import { useEffect, useState } from "react"
import { Alert, Button, Collapse, Form, Input, InputNumber, Select, Space, Spin, Tag, Typography } from "antd"
import { actScriptDevelopment, getScriptDevelopment, scriptDevelopmentWorking, startScriptDevelopment, type EpisodeStoryPlan, type ScriptDevelopment, type StoryPlan } from "../script-development"
import { director2ErrorDetail } from "../api"
import Director2ScriptLiveBody from "../Director2ScriptLiveBody"

const fields: Array<[keyof EpisodeStoryPlan, string]> = [["opening_hook", "开场吸引点"], ["goal", "人物目标"], ["obstacle", "阻力"], ["choice_and_consequence", "选择与后果"], ["emotion", "情绪变化"], ["ending_hook", "集尾钩子 / 主线兑现"], ["next_episode_bridge", "下一集承接 / 终集收束"]]

export default function ScriptDevelopmentPanel({ projectId, documentId, csrfToken, onAdopted }: {
  projectId: string; documentId: string; csrfToken: string; onAdopted?: () => void
}) {
  const [job, setJob] = useState<ScriptDevelopment | null>(null)
  const [plan, setPlan] = useState<StoryPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [feedback, setFeedback] = useState("")
  const [targets, setTargets] = useState<number[]>([])
  const [episodeCount, setEpisodeCount] = useState<number | null>(null)
  const [duration, setDuration] = useState<number | null>(null)
  const working = scriptDevelopmentWorking(job)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    setJob(null); setPlan(null); setError("")
    const read = async () => {
      try {
        const next = await getScriptDevelopment(projectId, documentId)
        if (!alive) return
        setJob(next)
        setError("")
        setPlan(current => current || next?.data.plan || null)
        timer = setTimeout(read, scriptDevelopmentWorking(next) ? 2000 : 6000)
      } catch (err) { if (alive) { setError(director2ErrorDetail(err, "读取剧本发展失败")); timer = setTimeout(read, 6000) } }
    }
    void read()
    return () => { alive = false; clearTimeout(timer) }
  }, [projectId, documentId])
  async function act(action: string) {
    if (busy) return
    setBusy(true); setError("")
    try {
      const next = action === "start"
        ? await startScriptDevelopment(csrfToken, projectId, documentId, { episode_count: episodeCount, duration_seconds: duration })
        : await actScriptDevelopment(csrfToken, projectId, documentId, job!, action, { plan, feedback, episode_numbers: targets })
      setJob(next); setPlan(next.data.plan || null)
      if (next.status === "succeeded") onAdopted?.()
    } catch (err) { setError(director2ErrorDetail(err, "剧本发展操作失败")) }
    finally { setBusy(false) }
  }
  const updateEpisode = (index: number, patch: Partial<EpisodeStoryPlan>) => setPlan(current => current ? { ...current, episodes: current.episodes.map((ep, i) => i === index ? { ...ep, ...patch } : ep) } : current)
  return <section className="director-block-card" aria-label="剧本发展">
    <Space wrap><Typography.Title level={5}>剧本发展</Typography.Title><Tag>{job?.data.phase === "adopted" ? "已采纳" : working ? "创作中" : job?.data.phase === "plan_review" ? "策划待确认" : job?.data.phase === "script_review" ? "完整稿待采纳" : "先完善故事，再规划镜头"}</Tag></Space>
    <Typography.Paragraph type="secondary">保留主线，补足冲突、人物动机、分集钩子与前后衔接。先确认策划，再集中审核完整稿。</Typography.Paragraph>
    {error || job?.error ? <Alert type="error" showIcon title={error || job?.error} /> : null}
    {!job || job.status === "succeeded" || job.status === "failed" ? <Space wrap>
      <Space orientation="vertical"><Typography.Text>目标集数（留空沿用原稿）</Typography.Text><InputNumber aria-label="目标集数" min={1} max={100} value={episodeCount} onChange={setEpisodeCount} /></Space>
      <Space orientation="vertical"><Typography.Text>单集秒数（留空由 AI 建议）</Typography.Text><InputNumber aria-label="单集时长（秒）" min={10} max={3600} value={duration} onChange={setDuration} /></Space>
      <Button type="primary" loading={busy} onClick={() => void act("start")}>{job ? "开始新一版策划" : "诊断并策划剧本"}</Button>
    </Space> : null}
    {working ? <Space><Spin size="small" /><Typography.Text>{job?.data.message}</Typography.Text></Space> : null}
    {job?.status === "failed" ? <Button loading={busy} onClick={() => void act("retry")}>从检查点重试</Button> : null}
    {job?.data.phase === "plan_review" && plan ? <Form layout="vertical">
      <Alert type="info" showIcon title={`素材诊断：${({ outline: "大纲", draft: "简稿", complete: "完整剧本" } as Record<string, string>)[plan.diagnosis?.kind || ""] || "待确认"}`} description={[plan.diagnosis?.reasons, plan.scale_reason].flat().filter(Boolean).join("；")} />
      <Form.Item label="主线"><Input.TextArea value={plan.mainline} onChange={e => setPlan({ ...plan, mainline: e.target.value })} autoSize /></Form.Item>
      <Collapse items={[{ key: "characters", label: "核心人物与人物目标", children: plan.characters.map((character, index) => typeof character === "string"
        ? <Form.Item key={index} label={`人物 ${index + 1}`}><Input.TextArea value={character} onChange={e => setPlan({ ...plan, characters: plan.characters.map((value, i) => i === index ? e.target.value : value) })} autoSize /></Form.Item>
        : <div key={index}>{[["name", "姓名"], ["description", "人物设定"], ["goal", "人物目标"], ["motivation", "动机"], ["relationships", "人物关系"]].map(([key, label]) => <Form.Item key={key} label={label}><Input.TextArea value={String(character[key] || "")} onChange={e => setPlan({ ...plan, characters: plan.characters.map((value, i) => i === index ? { ...character, [key]: e.target.value } : value) })} autoSize /></Form.Item>)}</div>) }]} />
      <Form.Item label="关键结局"><Input.TextArea value={plan.ending} onChange={e => setPlan({ ...plan, ending: e.target.value })} autoSize /></Form.Item>
      <Form.Item label="不可改内容（每行一项）"><Input.TextArea value={plan.locked_facts.join("\n")} onChange={e => setPlan({ ...plan, locked_facts: e.target.value.split("\n").filter(Boolean) })} autoSize /></Form.Item>
      <Collapse items={plan.episodes.map((ep, i) => ({ key: ep.episode_num, label: `第 ${ep.episode_num} 集 · ${ep.title} · ${ep.duration_seconds} 秒`, children: <>
        <Form.Item label="集名"><Input value={ep.title} onChange={e => updateEpisode(i, { title: e.target.value })} /></Form.Item>
        <Form.Item label="单集时长（秒）"><InputNumber min={10} max={3600} value={ep.duration_seconds} onChange={value => updateEpisode(i, { duration_seconds: value || 60 })} /></Form.Item>
        {fields.map(([key, label]) => <Form.Item key={key} label={label}><Input.TextArea value={String(ep[key])} onChange={e => updateEpisode(i, { [key]: e.target.value })} autoSize /></Form.Item>)}
      </> }))} />
      <Space wrap><Button type="primary" loading={busy} onClick={() => void act("confirm_plan")}>确认策划，扩写完整剧本</Button><Button disabled={busy} onClick={() => void act("keep_original")}>保留原稿，不扩写</Button></Space>
    </Form> : null}
    {job?.data.script_text ? <Collapse items={[{ key: "script", label: "完整剧本", children: <Director2ScriptLiveBody title={plan?.title || "剧本"} summary={plan?.mainline || ""} fullStory={job.data.script_text} live={false} /> }]} /> : null}
    {job?.data.phase === "script_review" ? <>
      <Alert type={job.data.unresolved_issues?.length ? "warning" : "info"} showIcon title={job.data.unresolved_issues?.length ? "仍有审稿意见，请查看后决定是否采纳" : "自动审稿已完成，仍需人工检查戏剧效果"} />
      {job.data.unresolved_issues?.map((issue, i) => <Typography.Paragraph key={i}>第 {issue.episode_num} 集 · {issue.category}：{issue.evidence}<br />建议：{issue.suggestion}</Typography.Paragraph>)}
      <Form layout="vertical"><Form.Item label="指定修订集"><Select mode="multiple" value={targets} onChange={setTargets} options={job.data.episodes?.map(ep => ({ value: ep.episode_num, label: `第 ${ep.episode_num} 集 · ${ep.title}` }))} /></Form.Item>
        <Form.Item label="修订要求"><Input.TextArea value={feedback} onChange={e => setFeedback(e.target.value)} placeholder="例如：第二集开头接住上一集的秘密，让主角主动做选择" /></Form.Item></Form>
      <Space><Button loading={busy} disabled={!targets.length || !feedback.trim()} onClick={() => void act("revise")}>修订所选集并检查全剧衔接</Button><Button type="primary" loading={busy} onClick={() => void act("apply")}>采纳完整稿</Button></Space>
    </> : null}
  </section>
}
