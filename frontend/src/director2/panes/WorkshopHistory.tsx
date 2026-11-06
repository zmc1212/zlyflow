import { useEffect, useState } from "react"
import { Alert, Button, Empty, Modal, Tag, message } from "antd"
import { Check } from "lucide-react"
import { adoptBeatVideoTake, director2ErrorDetail, listBeatVideoTakes, type Director2Beat } from "../api"

export default function WorkshopHistory({ projectId, episodeId, beat, csrfToken, onClose, onAdopt }: { projectId: string; episodeId: string; beat: Director2Beat; csrfToken: string; onClose: () => void; onAdopt: (beat: Director2Beat) => void }) {
  const [takes, setTakes] = useState<NonNullable<Director2Beat["video_takes"]>>([])
  const [selected, setSelected] = useState("")
  const [adopted, setAdopted] = useState(beat.video_url || "")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [saving, setSaving] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true); setError("")
    listBeatVideoTakes(projectId, episodeId, beat.id).then(result => {
      if (!active) return
      setTakes(result.takes); setAdopted(result.adopted_url); setSelected(result.adopted_url || result.takes.at(-1)?.url || "")
    }).catch(reason => { if (active) setError(director2ErrorDetail(reason, "历史版本加载失败")) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [projectId, episodeId, beat.id, revision])
  const current = takes.find(take => take.url === selected)
  const adopt = async () => {
    if (!current || saving) return
    setSaving(true)
    try { const result = await adoptBeatVideoTake(csrfToken, projectId, episodeId, beat.id, current.url); setAdopted(current.url); onAdopt(result.beat); message.success("已采用此版本") }
    catch (reason) { message.error(director2ErrorDetail(reason, "采用失败，当前版本未改变")) }
    finally { setSaving(false) }
  }
  return <Modal open title={"片段 " + String(beat.sequence).padStart(2, "0") + " · 历史版本"} onCancel={onClose} footer={null} width={1080} centered destroyOnHidden className="ws-history-modal">
    {error ? <Alert type="error" showIcon title={error} action={<Button onClick={() => setRevision(v => v + 1)}>重试</Button>}/> : loading ? <div className="ws-history-layout" role="status" aria-busy="true" aria-label="正在加载历史版本"><div className="ws-history-skeleton-preview" aria-hidden="true"><span className="studio-skeleton-bar ws-history-skeleton-stage"/></div><div className="ws-history-skeleton-list" aria-hidden="true">{Array.from({ length: 3 }, (_, index) => <div className="ws-history-skeleton-entry" key={index}><span className="studio-skeleton-bar ws-history-skeleton-thumb"/><span className="studio-skeleton-bar" style={{ width: "72%" }}/></div>)}</div></div> : <div className="ws-history-layout"><div className="ws-history-preview">{current ? <video key={current.upscaled_url || current.url} src={current.upscaled_url || current.url} controls playsInline preload="metadata"/> : <Empty description="暂无成功成片"/>}</div><div className="ws-history-list">{takes.map((take, index) => <div className={"ws-history-entry" + (selected === take.url ? " is-selected" : "")} key={take.id || take.url}><Button type="text" aria-label={"预览版本" + (index + 1)} onClick={() => setSelected(take.url)}><video src={(take.upscaled_url || take.url) + "#t=0.01"} muted preload="metadata"/><span>版本 {String(index + 1).padStart(2, "0")}<small>{take.created_at || "已保存成片"}</small></span>{adopted === take.url && <Tag icon={<Check size={11}/>}>已采用</Tag>}</Button>{selected === take.url && <Button size="small" disabled={adopted === take.url} loading={saving} onClick={() => void adopt()}>{adopted === take.url ? "当前采用" : "采用此版"}</Button>}</div>)}</div></div>}
  </Modal>
}
