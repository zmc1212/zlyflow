import { Alert, Button, Dropdown, Empty, Input, Popover, Select, Tag, Tooltip } from "antd"
import { List, MoreHorizontal, Play, Plus, RefreshCw, Search } from "lucide-react"
import { useState } from "react"
import type { Director2Beat, Director2Episode } from "../api"
import { EPISODE_FILTERS, episodeStatusLabel, type EpisodeFilter, type EpisodeSort } from "../episode-overview"
import { beatPlaybackUrl } from "../director2-video-settings"
import { sumBeatDurationSec } from "../workshop-beat-duration"
import { workshopTime } from "../workshop-editor"

export function workshopEpisodeSummary(episode: Director2Episode) {
  let data: Record<string, any> = {}
  try { data = JSON.parse(episode.data_json || "{}") } catch { /* Draft episodes may not have a storyboard yet. */ }
  const beats: Director2Beat[] = Array.isArray(data.beats) ? data.beats : []
  const first = beats.find(beat => beatPlaybackUrl(beat) || beat.render_url || beat.sketch_url)
  return { beats, cover: first?.render_url || first?.sketch_url || "", video: beatPlaybackUrl(first), duration: sumBeatDurationSec(beats), ready: beats.filter(beat => beatPlaybackUrl(beat)).length, characters: new Set(beats.flatMap(b => b.character_ids || b.characters || [])).size, scenes: new Set(beats.map(b => b.scene_id || b.scene).filter(Boolean)).size }
}

export default function WorkshopOverview({ episodes, total, loading, error, query, filter, sort, onQuery, onFilter, onSort, onCreate, onEdit, onSettings, onDelete, onDeleteSelected, onRefresh, onPreview }: {
  episodes: Director2Episode[]; total: number; loading: boolean; error: string; query: string; filter: EpisodeFilter; sort: EpisodeSort
  onQuery: (value: string) => void; onFilter: (value: EpisodeFilter) => void; onSort: (value: EpisodeSort) => void
  onCreate: () => void; onEdit: (id: string) => void; onSettings: (ep: Director2Episode) => void; onDelete: (ep: Director2Episode) => void; onDeleteSelected: (eps: Director2Episode[], onDeleted: (deletedIds: string[]) => void) => void; onRefresh: () => void; onPreview: (ep: Director2Episode) => void
}) {
  const [batch, setBatch] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const exportSelected = () => {
    const text = episodes.filter(episode => selected.includes(episode.id)).map(episode => "# 第 " + episode.episode_num + " 集 · " + episode.title + "\n\n" + (episode.script_text || "")).join("\n\n---\n\n")
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }))
    const link = document.createElement("a"); link.href = url; link.download = "分集剧本.md"; link.click(); URL.revokeObjectURL(url)
  }
  const deleteSelected = () => {
    const targets = episodes.filter(episode => selected.includes(episode.id))
    if (!targets.length) return
    onDeleteSelected(targets, deletedIds => setSelected(previous => previous.filter(id => !deletedIds.includes(id))))
  }
  const allSelected = episodes.length > 0 && episodes.every(episode => selected.includes(episode.id))
  const filters = <div className="ws-overview-filter"><Input placeholder="搜索集数、标题或剧本" aria-label="搜索分集" allowClear prefix={<Search size={14}/>} value={query} onChange={event => onQuery(event.target.value)}/><Select aria-label="按制作状态筛选分集" value={filter} onChange={onFilter} options={EPISODE_FILTERS.map(item => ({ value: item.value, label: item.label }))}/><Select aria-label="分集排序" value={sort} onChange={onSort} options={[{ value: "number_asc", label: "集数从小到大" }, { value: "number_desc", label: "集数从大到小" }, { value: "updated_desc", label: "最近更新优先" }]}/><Button onClick={onRefresh} loading={loading} icon={<RefreshCw size={13}/>}>刷新列表</Button></div>
  return <main className="ws-overview"><header className="ws-overview-heading"><div><h1>分集视频</h1><p>{loading && !total ? "正在加载分集列表…" : `共 ${total} 集${query || filter !== "all" ? ` · 显示 ${episodes.length} 集` : ""}`}</p></div><div className="ws-overview-actions">{batch && <><span>已选 {selected.length} 集</span><Button className="ws-subtle" disabled={!episodes.length} onClick={() => setSelected(allSelected ? [] : episodes.map(episode => episode.id))}>{allSelected ? "取消全选" : "全选"}</Button><Button className="ws-subtle" disabled={!selected.length} onClick={exportSelected}>导出选中文案</Button><Button className="ws-subtle" danger disabled={!selected.length} onClick={deleteSelected}>删除选中</Button></>}<Popover trigger="click" placement="bottomRight" content={filters}><Button className="ws-subtle" icon={<Search size={14}/>} aria-label="搜索筛选分集"/></Popover><Button className="ws-subtle" icon={<Plus size={14}/>} onClick={onCreate} disabled={loading && total === 0}>新增一集</Button><Button className="ws-subtle" icon={<List size={14}/>} onClick={() => { setBatch(!batch); setSelected([]) }}>{batch ? "完成" : "批量"}</Button></div></header>
    {error && <Alert type="error" showIcon title="分集列表加载失败" description={error} action={<Button size="small" onClick={onRefresh}>重新加载</Button>}/>}
    <div className="ws-episode-grid" aria-busy={loading && !total}>{loading && !total ? Array.from({ length: 3 }, (_, index) => <article className="ws-episode-card is-skeleton" key={index} aria-hidden="true"><span className="studio-skeleton-bar ws-skeleton-cover"/><div className="ws-episode-card-body"><div><span className="studio-skeleton-bar ws-skeleton-chip"/><span className="studio-skeleton-bar ws-skeleton-heading"/><span className="studio-skeleton-bar ws-skeleton-caption"/></div><div className="ws-episode-card-actions"><span className="studio-skeleton-bar ws-skeleton-action"/><span className="studio-skeleton-bar ws-skeleton-action is-wide"/></div></div></article>) : episodes.map(episode => {
      const info = workshopEpisodeSummary(episode)
      const complete = info.beats.length > 0 && info.ready === info.beats.length
      return <article className={"ws-episode-card" + (selected.includes(episode.id) ? " is-checked" : "")} key={episode.id} aria-label={`第 ${episode.episode_num} 集：${episode.title}`}>
        <Button type="text" className="ws-episode-cover" aria-label={`预览第${episode.episode_num}集`} onClick={() => onPreview(episode)}>{info.cover ? <img src={info.cover} alt=""/> : info.video ? <video src={info.video + "#t=0.01"} preload="metadata" muted playsInline/> : <span><Play size={22}/></span>}{info.duration > 0 && <span className="ws-episode-duration">{workshopTime(info.duration)}</span>}</Button>
        <div className="ws-episode-card-body"><div><Tag className={complete ? "ws-completed-tag" : "ws-episode-status"}>{complete ? "已完成" : episodeStatusLabel(episode.status)}</Tag><Tooltip title={episode.title}><h3>第 {episode.episode_num} 集：{episode.title}</h3></Tooltip><p>角色 {info.characters}<i>·</i>场景 {info.scenes}<i>·</i>分镜视频 {info.ready}/{info.beats.length || episode.shots_count || 0}</p></div><div className="ws-episode-card-actions">{batch && <Button type={selected.includes(episode.id) ? "primary" : "default"} size="small" onClick={() => setSelected(previous => previous.includes(episode.id) ? previous.filter(id => id !== episode.id) : [...previous, episode.id])}>{selected.includes(episode.id) ? "已选" : "选择"}</Button>}<Tooltip title="预览全片"><Button className="ws-subtle" icon={<Play size={12} fill="currentColor"/>} aria-label={`播放第${episode.episode_num}集`} disabled={!info.ready} onClick={() => onPreview(episode)}/></Tooltip><Button className="ws-subtle" onClick={() => onEdit(episode.id)}>编辑</Button><Dropdown trigger={["click"]} menu={{ items: [{ key: "edit", label: "编辑分集信息", onClick: () => onSettings(episode) }, { key: "delete", label: "删除分集", danger: true, onClick: () => onDelete(episode) }] }}><Button type="text" size="small" icon={<MoreHorizontal size={14}/>} aria-label={`第${episode.episode_num}集更多操作`}/></Dropdown></div></div>
      </article>
    })}</div>
    {!loading && !error && !episodes.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={total ? "没有匹配的分集" : "从第一集开始"}><Button onClick={total ? () => { onQuery(""); onFilter("all") } : onCreate}>{total ? "重置筛选" : "新增第 1 集"}</Button></Empty>}
  </main>
}
